"""Position-aware semantic parser for offline exam question papers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import fmean
from typing import Iterable, Sequence

from .layout import LayoutLine, LayoutWord, StructuredPage


_QUESTION_START = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*(.*)$")
_CHOICE_MARKERS = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
_CHOICE_PATTERN = re.compile(r"([①②③④⑤])")
_DAMAGED_MARKER = re.compile(r"^[①-⑤㉠-㉭]\s*")
_DOCUMENT_NOISE = re.compile(
    r"(?:무단\s*(?:복제|전재)|해기사\s*시험\s*전문|정답\s*및\s*해설)",
    re.IGNORECASE,
)
_PROPOSITION_MARKER = re.compile(r"^[㉠-㉭]$")


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
                if self._is_document_noise(record, normalized, repeated):
                    removed_noise_pages.add(page.number)
                    continue
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

    def _is_document_noise(
        self, record: _LineRecord, normalized: str, repeated: set[str]
    ) -> bool:
        y0 = record.bbox[1]
        if y0 >= 0.88:
            return True
        if y0 <= 0.07 and (normalized in repeated or not _QUESTION_START.match(record.text)):
            return True
        if normalized in repeated and (y0 <= 0.12 or y0 >= 0.88):
            return True
        return bool(_DOCUMENT_NOISE.search(record.text))

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

        stem_parts = [first_stem_text] if first_stem_text else []
        explicit_choices: dict[int, str] = {}
        explicit_marker_numbers: list[int] = []
        active_choice: int | None = None

        for index, record in enumerate(region[1:], start=1):
            if use_recovery and index == recovered_index:
                continue
            pieces = self._explicit_choice_pieces(record.text)
            if pieces:
                for choice_number, text in pieces:
                    explicit_marker_numbers.append(choice_number)
                    explicit_choices[choice_number] = text
                    active_choice = choice_number
                continue
            if active_choice is not None:
                continuation = record.text.strip()
                if continuation:
                    previous = explicit_choices.get(active_choice, "")
                    explicit_choices[active_choice] = " ".join(
                        part for part in (previous, continuation) if part
                    )
            else:
                stem_parts.append(record.text)

        diagnostics: list[str] = []
        if explicit_choices:
            choices = [explicit_choices[key].strip() for key in sorted(explicit_choices)]
            if len(set(explicit_marker_numbers)) != len(explicit_marker_numbers):
                diagnostics.append("duplicate_choice_marker")
            expected_markers = list(range(1, len(explicit_marker_numbers) + 1))
            if explicit_marker_numbers != expected_markers:
                diagnostics.append("invalid_choice_sequence")
        else:
            choices = recovered_choices
            if recovered_choices:
                diagnostics.append("coordinate_choice_recovery")

        if len(choices) not in (4, 5):
            diagnostics.append("invalid_choice_count")
        if region[0].page in removed_noise_pages:
            diagnostics.append("document_noise_removed")

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
            groups = self._horizontal_cells(records[index].words)
            if len(groups) != 4:
                continue
            if self._is_sequential_proposition_row(groups):
                continue
            raw_values = [" ".join(str(word.text).strip() for word in group) for group in groups]
            values = [self._strip_damaged_marker(value) for value in raw_values]
            values = self._repair_fused_numeric_marker(values)
            if all(values) and sum(value.isdigit() for value in values) >= 3:
                return index, values
        return None

    def _is_sequential_proposition_row(
        self, groups: Sequence[Sequence[LayoutWord]]
    ) -> bool:
        labels = []
        for group in groups:
            first_text = str(group[0].text).strip() if group else ""
            if not _PROPOSITION_MARKER.fullmatch(first_text):
                return False
            labels.append(first_text)
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
