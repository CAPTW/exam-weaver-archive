"""Position-aware semantic parser for offline exam question papers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from statistics import fmean
from typing import Iterable, Sequence

from .layout import LayoutLine, LayoutWord, StructuredPage


_QUESTION_START = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*(.*)$")
_CHOICE_MARKERS = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
_CHOICE_PATTERN = re.compile(r"([①②③④⑤])")
_DAMAGED_VERTICAL_MARKERS = {"㉦": 1, "㉨": 2, "㉭": 3}
_DAMAGED_VERTICAL_PATTERN = re.compile(r"^([㉦㉨㉭])\s*")
_DAMAGED_MARKER = re.compile(r"^[①-⑤㉠-㉭]\s*")
_DOCUMENT_NOISE = re.compile(
    r"(?:무단\s*(?:복제|전재)|해기사\s*시험\s*전문|정답\s*및\s*해설"
    r"|론박.*(?:합격코스|커리큘럼)|해양공무원전문학원|ronpark\.com"
    r"|동시학습\s*실전대비|고민하지\s*말고)",
    re.IGNORECASE,
)
_PAGE_COUNTER = re.compile(r"^\s*\d+\s*(?:/|-|쪽\s*/\s*)\s*\d+\s*$")
_PAGE_COUNTER_SUFFIX = re.compile(r"\b\d+\s*/\s*\d+\s*$")
_FOOTER_TEXT = re.compile(
    r"(?:해양경찰.*채용시험|시험지\s*[A-Z가-힣0-9]*형|무단\s*(?:복제|전재))",
    re.IGNORECASE,
)
_HEADER_TEXT = re.compile(
    r"(?:해양경찰.*(?:채용)?시험|수험번호\s*[:：]?|과목명\s*[:：]?|문제지\s*[A-Z가-힣0-9]*형)",
    re.IGNORECASE,
)
_PROPOSITION_MARKER = re.compile(r"^([㉠-㉭])")


@dataclass(frozen=True)
class ParsedOfflineQuestion:
    """A semantic question candidate produced without subject metadata."""

    number: int
    stem: str
    choices: list[str]
    source_page: int
    confidence: float
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class _LineRecord:
    text: str
    words: tuple[LayoutWord, ...]
    bbox: tuple[float, float, float, float]
    page: int
    column: int | None
    ambiguous_bottom_margin: bool = False
    ambiguous_top_margin: bool = False


class OfflineExamParser:
    """Construct question candidates from structured PDF pages.

    Layout objects are intentionally consumed by their documented attributes.
    This keeps extraction and semantic parsing independently testable.
    """

    def parse_pages(
        self, pages: list[StructuredPage]
    ) -> list[ParsedOfflineQuestion]:
        records, removed_noise_pages = self._document_lines(pages)
        regions = self._question_regions(records)
        return [
            self._parse_region(region, removed_noise_pages)
            for region in regions
        ]

    def _document_lines(
        self, pages: Sequence[StructuredPage]
    ) -> tuple[list[_LineRecord], set[int]]:
        repeated = self._repeated_margin_text(pages)
        records: list[_LineRecord] = []
        removed_noise_pages: set[int] = set()

        for page in sorted(pages, key=lambda item: item.number):
            indexed_lines = list(enumerate(page.lines))
            indexed_lines.sort(key=lambda item: self._reading_order_key(item[1], item[0]))
            for _, line in indexed_lines:
                record = self._record(line, page.number)
                normalized = self._normalized_text(record.text)
                role = self._document_line_role(record, normalized, repeated)
                if role == "noise":
                    removed_noise_pages.add(page.number)
                    continue
                if role == "ambiguous_bottom_margin":
                    record = replace(record, ambiguous_bottom_margin=True)
                elif role == "ambiguous_top_margin":
                    record = replace(record, ambiguous_top_margin=True)
                if record.text:
                    records.append(record)
        return records, removed_noise_pages

    def _record(self, line: LayoutLine, fallback_page: int) -> _LineRecord:
        words = tuple(sorted(line.words, key=lambda word: word.bbox[0]))
        text = " ".join(
            str(word.text).strip() for word in words if str(word.text).strip()
        ).strip()
        bbox = tuple(float(value) for value in line.bbox)
        return _LineRecord(
            text=text,
            words=words,
            bbox=bbox,  # type: ignore[arg-type]
            page=int(getattr(line, "page", fallback_page)),
            column=getattr(line, "column", None),
        )

    def _reading_order_key(self, line: LayoutLine, original_index: int) -> tuple:
        column = getattr(line, "column", None)
        column_key = column if isinstance(column, int) and column >= 0 else 0
        bbox = line.bbox
        return (column_key, float(bbox[1]), float(bbox[0]), original_index)

    def _repeated_margin_text(self, pages: Sequence[StructuredPage]) -> set[str]:
        occurrences: dict[str, set[int]] = {}
        for page in pages:
            for line in page.lines:
                y0 = float(line.bbox[1])
                if y0 > 0.12 and y0 < 0.88:
                    continue
                text = self._normalized_text(
                    " ".join(str(word.text) for word in line.words)
                )
                if text:
                    occurrences.setdefault(text, set()).add(page.number)
        return {text for text, page_numbers in occurrences.items() if len(page_numbers) >= 2}

    def _document_line_role(
        self, record: _LineRecord, normalized: str, repeated: set[str]
    ) -> str:
        y0 = record.bbox[1]
        if _DOCUMENT_NOISE.search(record.text):
            return "noise"
        if y0 <= 0.07:
            if _QUESTION_START.match(record.text):
                return "body"
            if (
                normalized in repeated
                or _HEADER_TEXT.search(record.text)
                or _PAGE_COUNTER_SUFFIX.search(record.text)
            ):
                return "noise"
            return "ambiguous_top_margin"
        if normalized in repeated and (y0 <= 0.12 or y0 >= 0.88):
            return "noise"
        if y0 >= 0.88:
            if _PAGE_COUNTER.fullmatch(record.text) or _FOOTER_TEXT.search(record.text):
                return "noise"
            if self._plausible_coordinate_choice_row(record.words):
                return "body"
            return "ambiguous_bottom_margin"
        return "body"

    def _question_regions(
        self, records: Sequence[_LineRecord]
    ) -> list[list[_LineRecord]]:
        regions: list[list[_LineRecord]] = []
        current: list[_LineRecord] = []
        for record in records:
            if _QUESTION_START.match(record.text):
                if current:
                    regions.append(current)
                current = [record]
            elif current:
                current.append(record)
        if current:
            regions.append(current)
        return regions

    def _parse_region(
        self, region: Sequence[_LineRecord], removed_noise_pages: set[int]
    ) -> ParsedOfflineQuestion:
        start = _QUESTION_START.match(region[0].text)
        assert start is not None
        number = int(start.group(1))
        first_stem_text = start.group(2).strip()

        recovery = self._recover_coordinate_choice_row(region[1:])
        has_explicit_choices = any(
            self._explicit_choice_pieces(record.text) for record in region[1:]
        )
        recovered_index: int | None = None
        recovered_choices: list[str] = []
        if recovery is not None:
            relative_index, recovered_choices = recovery
            recovered_index = relative_index + 1
        use_recovery = recovered_index is not None and not has_explicit_choices
        damaged_recovery = None
        if not has_explicit_choices and not use_recovery:
            damaged_recovery = self._recover_damaged_vertical_choices(region)
        damaged_indexes: set[int] = set()
        damaged_choices: list[str] = []
        if damaged_recovery is not None:
            damaged_indexes, damaged_choices = damaged_recovery

        stem_parts = [first_stem_text] if first_stem_text else []
        explicit_choices: dict[int, str] = {}
        explicit_marker_numbers: list[int] = []
        explicit_choice_indexes: set[int] = set()
        active_choice: int | None = None

        for index, record in enumerate(region[1:], start=1):
            if use_recovery and index == recovered_index:
                continue
            if index in damaged_indexes:
                continue
            pieces = self._explicit_choice_pieces(record.text)
            if pieces:
                explicit_choice_indexes.add(index)
                for choice_number, text in pieces:
                    explicit_marker_numbers.append(choice_number)
                    explicit_choices[choice_number] = text
                    active_choice = choice_number
                continue
            if active_choice is not None:
                explicit_choice_indexes.add(index)
                continuation = record.text.strip()
                if continuation:
                    previous = explicit_choices.get(active_choice, "")
                    explicit_choices[active_choice] = " ".join(
                        part for part in (previous, continuation) if part
                    )
            else:
                stem_parts.append(record.text)

        diagnostics: list[str] = []
        explicit_sequence_valid = False
        if explicit_choices:
            choices = [explicit_choices[key].strip() for key in sorted(explicit_choices)]
            if len(set(explicit_marker_numbers)) != len(explicit_marker_numbers):
                diagnostics.append("duplicate_choice_marker")
            expected_markers = list(range(1, len(explicit_marker_numbers) + 1))
            explicit_sequence_valid = (
                len(explicit_choices) in (4, 5)
                and len(set(explicit_marker_numbers)) == len(explicit_marker_numbers)
                and explicit_marker_numbers == expected_markers
            )
            if explicit_marker_numbers != expected_markers:
                diagnostics.append("invalid_choice_sequence")
        else:
            choices = recovered_choices or damaged_choices
            if recovered_choices:
                diagnostics.append("coordinate_choice_recovery")
            elif damaged_choices:
                diagnostics.append("damaged_choice_recovery")

        if len(choices) not in (4, 5):
            diagnostics.append("invalid_choice_count")
        region_pages = {record.page for record in region}
        if region_pages & removed_noise_pages:
            diagnostics.append("document_noise_removed")
        recovered_margin_indexes = set(damaged_indexes)
        if use_recovery and recovered_index is not None:
            recovered_margin_indexes.add(recovered_index)
        has_visual_choice_sequence = any(
            getattr(word, "visual_choice_marker", False)
            for record in region
            for word in record.words
        )
        if has_visual_choice_sequence and explicit_sequence_valid:
            recovered_margin_indexes.update(explicit_choice_indexes)
        if any(
            record.ambiguous_bottom_margin
            for index, record in enumerate(region)
            if index not in recovered_margin_indexes
        ):
            diagnostics.append("ambiguous_bottom_margin")
        if any(
            record.ambiguous_top_margin
            for index, record in enumerate(region)
            if index not in recovered_margin_indexes
        ):
            diagnostics.append("ambiguous_top_margin")

        confidence = self._region_confidence(region)
        return ParsedOfflineQuestion(
            number=number,
            stem="\n".join(part.strip() for part in stem_parts if part.strip()),
            choices=choices,
            source_page=region[0].page,
            confidence=confidence,
            diagnostics=tuple(diagnostics),
        )

    def _explicit_choice_pieces(self, text: str) -> list[tuple[int, str]]:
        matches = list(_CHOICE_PATTERN.finditer(text))
        if not matches or text[: matches[0].start()].strip():
            return []
        pieces: list[tuple[int, str]] = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            pieces.append(
                (_CHOICE_MARKERS[match.group(1)], text[match.end() : end].strip())
            )
        return pieces

    def _recover_coordinate_choice_row(
        self, records: Sequence[_LineRecord]
    ) -> tuple[int, list[str]] | None:
        for index in range(len(records) - 1, -1, -1):
            inline_values = self._inline_numeric_choice_values(records[index].words)
            if inline_values is not None:
                return index, inline_values
            groups = self._horizontal_cells(records[index].words)
            if len(groups) != 4:
                continue
            if self._is_sequential_proposition_row(groups):
                continue
            if not self._has_damaged_marker_evidence(records[index].words):
                continue
            raw_values = [" ".join(str(word.text).strip() for word in group) for group in groups]
            values = [self._strip_damaged_marker(value) for value in raw_values]
            values = self._repair_fused_numeric_marker(values)
            if all(values) and self._plausible_choice_values(values):
                return index, values
        return None

    def _plausible_coordinate_choice_row(self, words: Sequence[LayoutWord]) -> bool:
        if self._inline_numeric_choice_values(words) is not None:
            return True
        groups = self._horizontal_cells(words)
        if len(groups) != 4 or self._is_sequential_proposition_row(groups):
            return False
        if not self._has_damaged_marker_evidence(words):
            return False
        values = [
            self._strip_damaged_marker(" ".join(str(word.text).strip() for word in group))
            for group in groups
        ]
        return all(values) and self._plausible_choice_values(values)

    @staticmethod
    def _plausible_choice_values(values: Sequence[str]) -> bool:
        compact_value = re.compile(r"^\d+(?:\s*(?:개|명|년|회|차|%))?$")
        return sum(bool(compact_value.fullmatch(value.strip())) for value in values) >= 3

    def _inline_numeric_choice_values(
        self, words: Sequence[LayoutWord]
    ) -> list[str] | None:
        ordered = sorted(words, key=lambda word: word.bbox[0])
        marker_indexes = [
            index
            for index, word in enumerate(ordered)
            if str(word.text).strip() == "㉭"
        ]
        if marker_indexes != [2] or len(ordered) != 5:
            return None
        values = [
            str(word.text).strip()
            for index, word in enumerate(ordered)
            if index != marker_indexes[0]
        ]
        return values if self._plausible_choice_values(values) else None

    @staticmethod
    def _has_damaged_marker_evidence(words: Sequence[LayoutWord]) -> bool:
        return any(
            _DAMAGED_MARKER.match(str(word.text).strip())
            for word in words
        )

    def _recover_damaged_vertical_choices(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        grid_recovery = self._recover_two_by_two_choice_grid(region)
        if grid_recovery is not None:
            return grid_recovery
        records = list(region[1:])
        markers: list[tuple[int, int]] = []
        for index, record in enumerate(records):
            match = _DAMAGED_VERTICAL_PATTERN.match(record.text)
            if match:
                markers.append((index, _DAMAGED_VERTICAL_MARKERS[match.group(1)]))
        if not markers:
            return None
        if len(markers) >= 4 and [number for _, number in markers[-4:]] == [1, 2, 3, 1]:
            markers = [
                (markers[-4][0], 1),
                (markers[-3][0], 2),
                (markers[-2][0], 3),
                (markers[-1][0], 4),
            ]
        marker_numbers = [number for _, number in markers]
        if marker_numbers != sorted(set(marker_numbers)) or marker_numbers[-1] > 4:
            return None

        first_index, first_number = markers[0]
        if first_number == 1:
            choice_start = first_index
        else:
            choice_start = self._leading_choice_block_start(records, first_index)
            if choice_start is None:
                return None

        choices: list[str] = []
        if choice_start < first_index:
            leading = self._split_damaged_choice_records(
                records[choice_start:first_index], first_number - 1
            )
            if leading is None:
                return None
            choices.extend(leading)

        for marker_offset, (start_index, number) in enumerate(markers):
            next_index = markers[marker_offset + 1][0] if marker_offset + 1 < len(markers) else len(records)
            next_number = markers[marker_offset + 1][1] if marker_offset + 1 < len(markers) else 5
            segment = self._split_damaged_choice_records(
                records[start_index:next_index], next_number - number
            )
            if segment is None:
                return None
            choices.extend(segment)
        if len(choices) != 4 or any(not choice.strip() for choice in choices):
            return None
        return set(range(choice_start + 1, len(region))), choices

    @staticmethod
    def _leading_choice_block_start(
        records: Sequence[_LineRecord], first_marker_index: int
    ) -> int | None:
        if first_marker_index <= 0:
            return None
        anchor_x = float(records[first_marker_index - 1].bbox[0])
        choice_start = first_marker_index - 1
        while choice_start > 0:
            previous_x = float(records[choice_start - 1].bbox[0])
            if abs(previous_x - anchor_x) > 0.008:
                break
            choice_start -= 1
        return choice_start

    def _recover_two_by_two_choice_grid(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        for second_index in range(len(region) - 1, 1, -1):
            second = region[second_index]
            if not _DAMAGED_VERTICAL_PATTERN.match(second.text):
                continue
            marker = _DAMAGED_VERTICAL_PATTERN.match(second.text)
            if marker is None or _DAMAGED_VERTICAL_MARKERS[marker.group(1)] != 3:
                continue
            first = region[second_index - 1]
            first_cells = self._split_two_horizontal_cells(first.words)
            second_words = tuple(
                word
                for word in second.words
                if str(word.text).strip() != marker.group(1)
            )
            second_cells = self._split_two_horizontal_cells(second_words)
            if first_cells is None or second_cells is None:
                continue
            choices = first_cells + second_cells
            if all(len(re.findall(r"[㉠-㉭]", choice)) == 1 for choice in choices):
                continue
            if all(choices):
                return {second_index - 1, second_index}, choices
        return None

    @staticmethod
    def _split_two_horizontal_cells(words: Sequence[LayoutWord]) -> list[str] | None:
        ordered = sorted(words, key=lambda word: word.bbox[0])
        if len(ordered) < 2:
            return None
        gaps = [
            float(ordered[index].bbox[0]) - float(ordered[index - 1].bbox[2])
            for index in range(1, len(ordered))
        ]
        split_index = max(range(1, len(ordered)), key=lambda index: gaps[index - 1])
        if gaps[split_index - 1] < 0.08:
            return None
        cells = (ordered[:split_index], ordered[split_index:])
        return [
            " ".join(str(word.text).strip() for word in cell).strip()
            for cell in cells
        ]

    def _split_damaged_choice_records(
        self, records: Sequence[_LineRecord], expected_count: int
    ) -> list[str] | None:
        if expected_count < 1 or len(records) < expected_count:
            return None
        texts = [record.text.strip() for record in records]
        texts[0] = _DAMAGED_VERTICAL_PATTERN.sub("", texts[0]).strip()
        if expected_count == 1:
            return [" ".join(texts).strip()]
        if len(texts) == expected_count:
            return texts
        boundaries = [
            index
            for index in range(1, len(records))
            if float(records[index].bbox[2]) - float(records[index - 1].bbox[2])
            >= 0.08
        ]
        if len(boundaries) != expected_count - 1:
            return None
        groups: list[str] = []
        start = 0
        for boundary in boundaries + [len(texts)]:
            groups.append(" ".join(texts[start:boundary]).strip())
            start = boundary
        return groups

    def _is_sequential_proposition_row(
        self, groups: Sequence[Sequence[LayoutWord]]
    ) -> bool:
        labels = []
        for group in groups:
            cell_text = "".join(str(word.text).strip() for word in group)
            marker = _PROPOSITION_MARKER.match(cell_text)
            if marker is None:
                return False
            labels.append(marker.group(1))
        first = ord("㉠")
        return [ord(label) for label in labels] == list(range(first, first + len(labels)))

    def _horizontal_cells(
        self, words: Sequence[LayoutWord]
    ) -> list[list[LayoutWord]]:
        ordered = sorted(words, key=lambda word: word.bbox[0])
        if len(ordered) < 4:
            return []
        groups: list[list[LayoutWord]] = [[ordered[0]]]
        for word in ordered[1:]:
            gap = float(word.bbox[0]) - float(groups[-1][-1].bbox[2])
            if gap >= 0.10:
                groups.append([word])
            else:
                groups[-1].append(word)
        return groups

    def _strip_damaged_marker(self, value: str) -> str:
        return _DAMAGED_MARKER.sub("", value.strip()).strip(" .):-")

    def _repair_fused_numeric_marker(self, values: list[str]) -> list[str]:
        typical_lengths = [len(value) for value in values if value.isdigit() and len(value) <= 2]
        if not typical_lengths:
            return values
        expected_length = round(fmean(typical_lengths))
        repaired = list(values)
        for index, value in enumerate(repaired):
            if (
                value.isdigit()
                and len(value) == expected_length + 1
                and value[0] == str(index + 1)
            ):
                repaired[index] = value[1:]
        return repaired

    def _region_confidence(self, region: Iterable[_LineRecord]) -> float:
        values: list[float] = []
        for record in region:
            for word in record.words:
                confidence = getattr(word, "confidence", None)
                if confidence is not None:
                    values.append(float(confidence))
        return round(fmean(values) if values else 1.0, 4)

    @staticmethod
    def _normalized_text(text: str) -> str:
        return re.sub(r"\s+", "", text).casefold()
