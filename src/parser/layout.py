"""Immutable, normalized layout records for native PDF text and OCR words."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence


BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class LayoutWord:
    text: str
    bbox: BBox
    confidence: Optional[float] = None
    column: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "bbox", tuple(float(value) for value in self.bbox))


@dataclass(frozen=True)
class LayoutLine:
    words: tuple[LayoutWord, ...]
    bbox: BBox
    page: int
    column: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "words", tuple(self.words))
        object.__setattr__(self, "bbox", tuple(float(value) for value in self.bbox))

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


@dataclass(frozen=True)
class StructuredPage:
    number: int
    width: float
    height: float
    kind: str
    lines: tuple[LayoutLine, ...]
    images: tuple[BBox, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "width", float(self.width))
        object.__setattr__(self, "height", float(self.height))
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(
            self,
            "images",
            tuple(tuple(float(value) for value in bbox) for bbox in self.images),
        )

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class _RawWord:
    text: str
    bbox: BBox
    confidence: Optional[float]

    @property
    def center_x(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


def normalize_bbox(bbox: Sequence[float], width: float, height: float) -> BBox:
    """Scale an absolute bounding box into a page-relative 0..1 coordinate model."""
    safe_width = max(float(width), 1.0)
    safe_height = max(float(height), 1.0)
    x0, y0, x1, y1 = (float(value) for value in bbox)
    return (
        _clamp(x0 / safe_width),
        _clamp(y0 / safe_height),
        _clamp(x1 / safe_width),
        _clamp(y1 / safe_height),
    )


def build_structured_page(
    words: Iterable[Sequence[object] | Mapping[str, object]],
    *,
    page_number: int,
    width: float,
    height: float,
    source: str = "native",
    images: Iterable[Sequence[float]] = (),
    divider_x: Optional[float] = None,
) -> StructuredPage:
    """Build a page from absolute-coordinate words supplied by PDF or OCR adapters."""
    raw_words = tuple(_coerce_word(word) for word in words)
    raw_words = tuple(word for word in raw_words if word is not None and word.text.strip())
    normalized_images = tuple(normalize_bbox(bbox, width, height) for bbox in images)
    full_page_image = any(_bbox_area(bbox) >= 0.72 for bbox in normalized_images)

    physical_rows = _group_raw_lines(raw_words)
    detected_divider = _detect_column_divider(
        raw_words,
        physical_rows,
        width=float(width),
        height=float(height),
        explicit_divider=divider_x,
    )
    lines = _make_layout_lines(
        raw_words,
        physical_rows,
        page_number=page_number,
        width=float(width),
        height=float(height),
        divider_x=detected_divider,
    )
    kind = _classify_page(
        raw_words,
        source=source,
        full_page_image=full_page_image,
        height=float(height),
        has_column_geometry=detected_divider is not None,
    )
    return StructuredPage(
        number=page_number,
        width=width,
        height=height,
        kind=kind,
        lines=lines,
        images=normalized_images,
    )


def _coerce_word(word: Sequence[object] | Mapping[str, object]) -> Optional[_RawWord]:
    try:
        if isinstance(word, Mapping):
            text = str(word.get("text", "") or "")
            bbox_value = word.get("bbox")
            if bbox_value is None:
                bbox_value = (word["x0"], word["y0"], word["x1"], word["y1"])
            confidence_value = word.get("confidence")
        else:
            x0, y0, x1, y1, text = word[:5]
            bbox_value = (x0, y0, x1, y1)
            confidence_value = word[5] if len(word) == 6 else None
        x0, y0, x1, y1 = (float(value) for value in bbox_value)
        confidence = float(confidence_value) if confidence_value is not None else None
    except (KeyError, TypeError, ValueError):
        return None
    return _RawWord(str(text or ""), (x0, y0, x1, y1), confidence)


def _group_raw_lines(words: Sequence[_RawWord]) -> list[list[_RawWord]]:
    if not words:
        return []
    heights = [max(word.bbox[3] - word.bbox[1], 1.0) for word in words]
    tolerance = max(2.0, median(heights) * 0.45)
    rows: list[list[_RawWord]] = []
    row_centers: list[float] = []
    for word in sorted(words, key=lambda item: (item.center_y, item.bbox[0], item.text)):
        best_index = None
        best_distance = None
        for index, center in enumerate(row_centers):
            distance = abs(word.center_y - center)
            if distance <= tolerance and (best_distance is None or distance < best_distance):
                best_index = index
                best_distance = distance
        if best_index is None:
            rows.append([word])
            row_centers.append(word.center_y)
        else:
            rows[best_index].append(word)
            row_centers[best_index] = sum(item.center_y for item in rows[best_index]) / len(rows[best_index])
    return [sorted(row, key=lambda item: (item.bbox[0], item.bbox[1], item.text)) for row in rows]


def _detect_column_divider(
    words: Sequence[_RawWord],
    rows: Sequence[Sequence[_RawWord]],
    *,
    width: float,
    height: float,
    explicit_divider: Optional[float],
) -> Optional[float]:
    if len(words) < 4 or width <= 0 or height <= 0:
        return None

    body_rows = [row for row in rows if _row_is_in_body(row, height)]
    body_words = tuple(word for row in body_rows for word in row)
    if len(body_words) < 4:
        return None

    minimum_gutter = width * 0.08
    candidates: list[tuple[float, float]] = []
    for row in body_rows:
        for previous, current in zip(row, row[1:]):
            gap = current.bbox[0] - previous.bbox[2]
            midpoint = (previous.bbox[2] + current.bbox[0]) / 2
            if gap >= minimum_gutter and width * 0.30 <= midpoint <= width * 0.70:
                candidates.append((midpoint, gap))

    if explicit_divider is not None and width * 0.25 <= explicit_divider <= width * 0.75:
        split = float(explicit_divider)
    elif candidates:
        split = median(midpoint for midpoint, _ in candidates)
    else:
        intervals = _merged_x_intervals(body_words)
        global_gaps = [
            ((left[1] + right[0]) / 2, right[0] - left[1])
            for left, right in zip(intervals, intervals[1:])
            if right[0] - left[1] >= minimum_gutter
            and width * 0.30 <= (left[1] + right[0]) / 2 <= width * 0.70
        ]
        if not global_gaps:
            return None
        split = max(global_gaps, key=lambda item: item[1])[0]

    separated_rows = 0
    left_only_rows = 0
    right_only_rows = 0
    for row in body_rows:
        left = [word for word in row if word.center_x < split]
        right = [word for word in row if word.center_x >= split]
        if left and right:
            cross_gap = min(word.bbox[0] for word in right) - max(word.bbox[2] for word in left)
            if cross_gap >= minimum_gutter:
                separated_rows += 1
        elif left:
            left_only_rows += 1
        elif right:
            right_only_rows += 1

    left_count = sum(word.center_x < split for word in body_words)
    right_count = len(body_words) - left_count
    has_repeated_bilateral_evidence = separated_rows >= 2
    has_staggered_column_evidence = left_only_rows >= 2 and right_only_rows >= 2
    if (
        not (has_repeated_bilateral_evidence or has_staggered_column_evidence)
        or left_count < 2
        or right_count < 2
    ):
        return None
    return split


def _merged_x_intervals(words: Sequence[_RawWord]) -> list[tuple[float, float]]:
    intervals: list[list[float]] = []
    for word in sorted(words, key=lambda item: (item.bbox[0], item.bbox[2])):
        if not intervals or word.bbox[0] > intervals[-1][1]:
            intervals.append([word.bbox[0], word.bbox[2]])
        else:
            intervals[-1][1] = max(intervals[-1][1], word.bbox[2])
    return [(start, end) for start, end in intervals]


def _make_layout_lines(
    words: Sequence[_RawWord],
    physical_rows: Sequence[Sequence[_RawWord]],
    *,
    page_number: int,
    width: float,
    height: float,
    divider_x: Optional[float],
) -> tuple[LayoutLine, ...]:
    if divider_x is None:
        grouped = _group_raw_lines(words)
        return tuple(_layout_line(row, page_number, 0, width, height) for row in grouped)

    columns = {
        0: [word for word in words if word.center_x < divider_x],
        1: [word for word in words if word.center_x >= divider_x],
    }
    output = []
    for column in (0, 1):
        for row in _group_raw_lines(columns[column]):
            output.append(_layout_line(row, page_number, column, width, height))
    return tuple(output)


def _layout_line(
    row: Sequence[_RawWord],
    page_number: int,
    column: int,
    width: float,
    height: float,
) -> LayoutLine:
    ordered = sorted(row, key=lambda item: (item.bbox[0], item.bbox[1], item.text))
    words = tuple(
        LayoutWord(
            text=word.text,
            bbox=normalize_bbox(word.bbox, width, height),
            confidence=word.confidence,
            column=column,
        )
        for word in ordered
    )
    absolute_bbox = (
        min(word.bbox[0] for word in ordered),
        min(word.bbox[1] for word in ordered),
        max(word.bbox[2] for word in ordered),
        max(word.bbox[3] for word in ordered),
    )
    return LayoutLine(
        words=words,
        bbox=normalize_bbox(absolute_bbox, width, height),
        page=page_number,
        column=column,
    )


def _classify_page(
    words: Sequence[_RawWord],
    *,
    source: str,
    full_page_image: bool,
    height: float,
    has_column_geometry: bool,
) -> str:
    normalized_text = ["".join(word.text.split()).casefold() for word in words if word.text.strip()]
    repeated_ratio = 0.0
    if normalized_text:
        repeated_ratio = 1.0 - (len(set(normalized_text)) / len(normalized_text))

    if not words and (source == "ocr" or full_page_image):
        return "scanned"

    body_words = tuple(word for word in words if height * 0.08 <= word.center_y <= height * 0.90)
    body_rows = _group_raw_lines(body_words)
    body_character_count = sum(len("".join(word.text.split())) for word in body_words)
    has_dense_body = (
        len(body_words) >= 6
        and len(body_rows) >= 3
        and body_character_count >= 10
    )
    has_column_body = (
        has_column_geometry
        and len(body_words) >= 4
        and len(body_rows) >= 2
        and body_character_count >= 6
    )
    if not (has_dense_body or has_column_body):
        return "non_question"
    if full_page_image and source == "native" and len(words) >= 6 and repeated_ratio >= 0.5:
        return "image_with_fake_text_layer"
    if source == "ocr":
        return "scanned"
    return "native"


def _row_is_in_body(row: Sequence[_RawWord], height: float) -> bool:
    if not row or height <= 0:
        return False
    center_y = sum(word.center_y for word in row) / len(row)
    return height * 0.08 <= center_y <= height * 0.90


def _bbox_area(bbox: BBox) -> float:
    return max(bbox[2] - bbox[0], 0.0) * max(bbox[3] - bbox[1], 0.0)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
