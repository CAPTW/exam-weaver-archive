"""Deterministic figure crops for scanned offline exam pages.

The source PDFs often store an entire scanned page as one image.  Embedded-image
bounding boxes are therefore not useful for locating a diagram.  This module
uses the structured OCR layout to isolate the vertical band between the end of
the question stem and the first answer choice, then trims only the visible ink
inside that band.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageOps

from .layout import BBox, LayoutLine, StructuredPage


_QUESTION_START = re.compile(r"^\s*(\d{1,3})\s*[.)•]\s*")
_CHOICE_START = re.compile(r"^\s*(?:[①②③④⑤㉠-㉭@]|[❶❷❸❹❺])\s*")
_VISUAL_STEM = re.compile(
    r"(?:그림|사진|그래프|회로|선도|도표|파형|기호|타임차트|"
    r"\bfig\.?\b|\bfigure\b|\bdiagram\b|\bchart\b|\bgraph\b)",
    re.IGNORECASE,
)


def needs_figure_crop(stem: str) -> bool:
    """Return whether a stem explicitly depends on visual context."""

    return bool(_VISUAL_STEM.search(str(stem or "")))


def locate_figure_band(
    page: StructuredPage,
    question_number: int,
    stem: str,
    choices: Sequence[str] = (),
) -> BBox | None:
    """Locate a figure-only OCR band without including answer-choice rows."""

    if not needs_figure_crop(stem):
        return None
    ordered = sorted(page.lines, key=lambda line: (line.column, line.bbox[1], line.bbox[0]))
    start_index = next(
        (
            index
            for index, line in enumerate(ordered)
            if (match := _QUESTION_START.match(line.text))
            and int(match.group(1)) == int(question_number)
        ),
        None,
    )
    if start_index is None:
        return None

    start = ordered[start_index]
    region: list[LayoutLine] = []
    for line in ordered[start_index:]:
        if line.column != start.column:
            if region:
                break
            continue
        match = _QUESTION_START.match(line.text)
        if region and match:
            break
        region.append(line)
    # A purely graphical symbol can produce no OCR line of its own, leaving
    # only the stem and the first choice as layout anchors.
    if len(region) < 2:
        return None

    first_choice_index = next(
        (
            index
            for index, line in enumerate(region[1:], start=1)
            if _is_choice_line(line, choices)
        ),
        None,
    )
    if first_choice_index is None or first_choice_index < 1:
        return None

    pre_choice = region[:first_choice_index]
    # Question punctuation must belong to the opening stem block.  OCR can
    # produce question marks inside circuit labels (for example ``-?b``), so
    # scanning the entire pre-choice region can cut away most of a diagram.
    stem_search_bottom = float(start.bbox[1]) + 0.10
    terminator_indexes = [
        index
        for index, line in enumerate(pre_choice)
        if float(line.bbox[1]) <= stem_search_bottom
        and re.search(r"[?？]", line.text)
    ]
    if terminator_indexes:
        stem_end_index = terminator_indexes[-1]
        # Parenthetical conditions commonly follow the question mark on the
        # next tightly-spaced line.  Keep consuming stem continuations until a
        # real vertical gap introduces the diagram.
        for index in range(stem_end_index + 1, len(pre_choice)):
            previous = pre_choice[index - 1]
            current = pre_choice[index]
            gap = float(current.bbox[1]) - float(previous.bbox[3])
            if gap > 0.014:
                break
            stem_end_index = index
    else:
        # A large gap after consecutive stem lines is the most reliable fallback
        # when OCR loses the question mark.
        stem_end_index = 0
        for index in range(1, len(pre_choice)):
            previous = pre_choice[index - 1]
            current = pre_choice[index]
            gap = float(current.bbox[1]) - float(previous.bbox[3])
            # Consecutive OCR stem lines are normally separated by less than
            # 1.3% of the page height.  Diagram labels can begin only slightly
            # farther away, so a looser cutoff risks treating the top of a
            # circuit as prose and cutting it off.
            if gap >= 0.013:
                break
            stem_end_index = index

    stem_bottom = float(pre_choice[stem_end_index].bbox[3])
    choice_top = float(region[first_choice_index].bbox[1])
    top = stem_bottom + 0.003
    bottom = choice_top - 0.004
    if not 0.025 <= bottom - top <= 0.42:
        return None

    if start.column == 0:
        left, right = 0.025, 0.485
    elif start.column == 1:
        left, right = 0.505, 0.975
    else:
        left = max(0.015, float(start.bbox[0]) - 0.025)
        right = min(0.985, float(start.bbox[2]) + 0.025)
    return (left, top, right, bottom)


def _is_choice_line(line: LayoutLine, choices: Sequence[str]) -> bool:
    if _CHOICE_START.match(line.text):
        return True
    if any(getattr(word, "visual_choice_marker", False) for word in line.words):
        return True
    line_value = _comparable_text(line.text)
    for choice in choices:
        choice_value = _comparable_text(choice)
        if len(choice_value) < 4:
            continue
        if choice_value in line_value:
            return True
        if SequenceMatcher(None, choice_value, line_value).ratio() >= 0.62:
            return True
    return False


def _comparable_text(value: str) -> str:
    value = re.sub(
        r"^(?:[①②③④⑤㉠-㉭@❶❷❸❹❺]\s*|(?:年|2)\s+)",
        "",
        str(value or ""),
    )
    value = value.replace("•", "·").replace("ㆍ", "·")
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", value).casefold()


def trim_figure_ink(
    page_image: Image.Image,
    normalized_band: Sequence[float],
    *,
    threshold: int = 220,
    padding: int = 8,
) -> Image.Image | None:
    """Crop a normalized band and tighten it around non-background pixels."""

    width, height = page_image.size
    left, top, right, bottom = (float(value) for value in normalized_band)
    pixel_box = (
        max(0, int(left * width)),
        max(0, int(top * height)),
        min(width, int(right * width)),
        min(height, int(bottom * height)),
    )
    if pixel_box[2] - pixel_box[0] < 20 or pixel_box[3] - pixel_box[1] < 20:
        return None

    candidate = page_image.crop(pixel_box).convert("L")
    candidate = ImageOps.autocontrast(candidate, cutoff=1)
    dark = candidate.point(lambda value: 255 if value < threshold else 0)
    dark_width, dark_height = dark.size
    pixels = dark.load()
    min_row_ink = max(2, round(dark_width * 0.002))
    min_column_ink = max(2, round(dark_height * 0.002))
    active_rows = [
        row
        for row in range(dark_height)
        if sum(pixels[column, row] > 0 for column in range(dark_width)) >= min_row_ink
    ]
    active_columns = [
        column
        for column in range(dark_width)
        if sum(pixels[column, row] > 0 for row in range(dark_height)) >= min_column_ink
    ]
    if not active_rows or not active_columns:
        return None

    ink_box = (
        max(0, min(active_columns) - padding),
        max(0, min(active_rows) - padding),
        min(dark_width, max(active_columns) + padding + 1),
        min(dark_height, max(active_rows) + padding + 1),
    )
    cropped = page_image.crop((
        pixel_box[0] + ink_box[0],
        pixel_box[1] + ink_box[1],
        pixel_box[0] + ink_box[2],
        pixel_box[1] + ink_box[3],
    ))
    if cropped.width < width * 0.07 or cropped.height < height * 0.02:
        return None
    return cropped


def materialize_offline_figure_crops(
    pdf_path: Path,
    pages: Sequence[StructuredPage],
    candidates: Iterable[object],
    output_dir: Path,
    *,
    scale: float = 2.0,
) -> tuple[object, ...]:
    """Attach deterministic figure crops to parsed offline questions."""

    source = Path(pdf_path)
    items = list(candidates)
    if not source.is_file() or source.suffix.casefold() != ".pdf":
        return tuple(items)
    page_map = {int(page.number): page for page in pages}
    targets: list[tuple[int, object, BBox]] = []
    for index, candidate in enumerate(items):
        page_number = int(getattr(candidate, "source_page", 0) or 0)
        page = page_map.get(page_number)
        if page is None:
            continue
        band = locate_figure_band(
            page,
            int(getattr(candidate, "number", 0) or 0),
            str(getattr(candidate, "stem", "") or ""),
            tuple(str(value) for value in (getattr(candidate, "choices", ()) or ())),
        )
        if band is not None:
            targets.append((index, candidate, band))
    if not targets:
        return tuple(items)

    import fitz

    digest = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
    safe_stem = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", source.stem).strip("_")[:64]
    target_dir = Path(output_dir) / "question_images" / f"{safe_stem}_{digest}"
    document = fitz.open(source)
    try:
        rendered: dict[int, Image.Image] = {}
        for index, candidate, band in targets:
            page_number = int(getattr(candidate, "source_page"))
            if not 1 <= page_number <= document.page_count:
                continue
            page_image = rendered.get(page_number)
            if page_image is None:
                pixmap = document[page_number - 1].get_pixmap(
                    matrix=fitz.Matrix(scale, scale),
                    alpha=False,
                )
                page_image = Image.frombytes(
                    "RGB",
                    (pixmap.width, pixmap.height),
                    pixmap.samples,
                )
                rendered[page_number] = page_image
            crop = trim_figure_ink(page_image, band)
            if crop is None:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            number = int(getattr(candidate, "number", 0) or 0)
            path = target_dir / f"p{page_number:03d}_q{number:03d}.png"
            crop.save(path, format="PNG", optimize=True)
            diagnostics = tuple(getattr(candidate, "diagnostics", ()) or ())
            if "figure_crop_heuristic" not in diagnostics:
                diagnostics = (*diagnostics, "figure_crop_heuristic")
            items[index] = replace(
                candidate,
                image_path=str(path),
                image_bbox=tuple(float(value) for value in band),
                diagnostics=diagnostics,
            )
    finally:
        document.close()
    return tuple(items)
