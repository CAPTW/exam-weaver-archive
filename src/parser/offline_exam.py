"""Position-aware semantic parser for offline exam question papers."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from statistics import fmean
from typing import Iterable, Sequence

from .layout import LayoutLine, LayoutWord, StructuredPage


_QUESTION_START = re.compile(
    r"^\s*(\d{1,3})\s*(?:[.)•]|\s+(?=(?:다음|[「\[]|r[가-힣])))\s*(.*)$"
)
_QUESTION_LEAD = re.compile(r"^\s*(?:다음|아래|[「\[]|r(?=[가-힣\[]))")
_EMBEDDED_QUESTION_START = re.compile(r".*?(\d{1,3})\s*[.)]\s*(다음.*)$")
_CHOICE_MARKERS = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5}
_CHOICE_PATTERN = re.compile(r"([①②③④⑤])")
_DAMAGED_VERTICAL_MARKERS = {"㉦": 1, "㉨": 2, "㉭": 3}
_DAMAGED_VERTICAL_PATTERN = re.compile(r"^([㉦㉨㉭])\s*")
_DAMAGED_MARKER = re.compile(r"^[①-⑤㉠-㉭]\s*")
_DOCUMENT_NOISE = re.compile(
    r"(?:무단\s*(?:복제|전재)|해기사\s*시험\s*전문|정답\s*및\s*해설"
    r"|채용\s*시험\s*문제지"
    r"|론박.*(?:합격코스|커리큘럼)|해양공무원전문학원|ronpark\.com"
    r"|동시학습(?:\s*실전대비)?|고민하지\s*말고)",
    re.IGNORECASE,
)
_PAGE_COUNTER = re.compile(r"^\s*\d+\s*(?:/|-|쪽\s*/\s*)\s*\d+\s*$")
_PAGE_COUNTER_SUFFIX = re.compile(r"\b\d+\s*/\s*\d+\s*$")
_FOOTER_TEXT = re.compile(
    r"(?:해양경찰.*채용시험|시험지\s*[A-Z가-힣0-9]*형|무단\s*(?:복제|전재))",
    re.IGNORECASE,
)
_HEADER_TEXT = re.compile(
    r"(?:해양경찰.*(?:채용)?시험|수험번호\s*[:：]?|과목명\s*[:：]?|문제지\s*[A-Z가-힣0-9]*형"
    r"|(?:19|20)\d{2}\s*년\s*도.{0,40}(?:해양경찰|해\s*양?\s*[영경])"
    r"|[12]\s*[09]\s*\d\s*\d\s*년.{0,20}(?:자\s*경|경\s*공\s*원))",
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
        visual_marker_x = {
            round(float(word.bbox[0]), 3)
            for word in words
            if getattr(word, "visual_choice_marker", False)
        }
        if visual_marker_x:
            words = tuple(
                word
                for word in words
                if not (
                    not getattr(word, "visual_choice_marker", False)
                    and re.fullmatch(r"[㉦㉨㉭]", str(word.text).strip())
                    and any(
                        abs(float(word.bbox[0]) - marker_x) <= 0.004
                        for marker_x in visual_marker_x
                    )
                )
            )
        if (
            len(words) > 1
            and re.fullmatch(r"\d{1,3}[.)]?", str(words[0].text).strip())
            and any(getattr(word, "visual_choice_marker", False) for word in words[1:])
        ):
            words = words[1:]
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
            if _PROPOSITION_MARKER.match(record.text):
                return "body"
            if record.text.rstrip().endswith("?"):
                return "body"
            return "ambiguous_bottom_margin"
        return "body"

    def _question_regions(
        self, records: Sequence[_LineRecord]
    ) -> list[list[_LineRecord]]:
        records = self._relocate_hanging_question_numbers(records)
        candidate_gutters: dict[tuple[int, int | None], float] = {}
        for record in records:
            if not _QUESTION_START.match(record.text):
                continue
            key = (record.page, record.column)
            candidate_gutters[key] = min(
                candidate_gutters.get(key, float("inf")), float(record.bbox[0])
            )
        regions: list[list[_LineRecord]] = []
        current: list[_LineRecord] = []
        current_number: int | None = None
        current_page: int | None = None
        choice_numbers: set[int] = set()
        previous_record: _LineRecord | None = None
        for record_index, record in enumerate(records):
            start = _QUESTION_START.match(record.text)
            key = (record.page, record.column)
            gutter = candidate_gutters.get(key)
            expected_number = (current_number + 1) if current_number is not None else 1
            embedded = _EMBEDDED_QUESTION_START.match(record.text)
            if (
                start is None
                and embedded is not None
                and int(embedded.group(1)) == expected_number
                and gutter is not None
            ):
                record = replace(
                    record,
                    text=f"{expected_number}. {embedded.group(2)}",
                    bbox=(gutter, record.bbox[1], record.bbox[2], record.bbox[3]),
                )
                start = _QUESTION_START.match(record.text)

            if start is None and gutter is not None and _QUESTION_LEAD.match(record.text):
                aligned_lead = gutter + 0.010 <= float(record.bbox[0]) <= gutter + 0.065
                first_missing = current_number is None and any(
                    match is not None and int(match.group(1)) == 2
                    for later in records
                    if (match := _QUESTION_START.match(later.text)) is not None
                )
                follows_complete_choices = choice_numbers == {1, 2, 3, 4}
                next_number = next(
                    (
                        int(match.group(1))
                        for later in records[record_index + 1:]
                        if later.page >= record.page
                        and (match := _QUESTION_START.match(later.text)) is not None
                        and int(match.group(1)) > expected_number
                    ),
                    None,
                )
                follows_number_gap = next_number == expected_number + 1
                separated_from_previous = (
                    previous_record is None
                    or previous_record.page != record.page
                    or previous_record.column != record.column
                    or float(record.bbox[1]) - float(previous_record.bbox[1]) >= 0.024
                )
                if (
                    aligned_lead
                    and separated_from_previous
                    and (first_missing or follows_complete_choices or follows_number_gap)
                ):
                    record = replace(
                        record,
                        text=f"{expected_number}. {record.text}",
                        bbox=(gutter, record.bbox[1], record.bbox[2], record.bbox[3]),
                    )
                    start = _QUESTION_START.match(record.text)

            is_top_level = False
            if start is not None:
                assert gutter is not None
                number = int(start.group(1))
                aligned = float(record.bbox[0]) <= gutter + 0.020
                backward_on_same_page = (
                    current_number is not None
                    and current_page == record.page
                    and number <= current_number
                )
                expected_number = (current_number + 1) if current_number is not None else None
                dropped_prefix = (
                    backward_on_same_page
                    and expected_number is not None
                    and expected_number > number
                    and str(expected_number).endswith(str(number))
                )
                if aligned and dropped_prefix:
                    number = expected_number
                    record = replace(record, text=f"{number}. {start.group(2)}")
                    start = _QUESTION_START.match(record.text)
                    assert start is not None
                    backward_on_same_page = False
                is_top_level = aligned and not backward_on_same_page
            if is_top_level:
                leading_next_page: list[_LineRecord] = []
                if (
                    current
                    and choice_numbers == {1, 2, 3, 4}
                    and current[0].page != record.page
                ):
                    while (
                        current
                        and current[-1].page == record.page
                        and current[-1].column == record.column
                        and float(current[-1].bbox[1]) < float(record.bbox[1])
                        and not self._explicit_choice_pieces(current[-1].text)
                    ):
                        leading_next_page.insert(0, current.pop())
                if current:
                    regions.append(current)
                current = [record, *leading_next_page]
                current_number = int(start.group(1))
                current_page = record.page
                choice_numbers = set()
            elif current:
                current.append(record)
                choice_numbers.update(
                    number for number, _text in self._explicit_choice_pieces(record.text)
                )
                if self._plausible_coordinate_choice_row(record.words):
                    choice_numbers.update({1, 2, 3, 4})
            previous_record = record
        if current:
            regions.append(current)
        return regions

    @staticmethod
    def _relocate_hanging_question_numbers(
        records: Sequence[_LineRecord],
    ) -> list[_LineRecord]:
        relocated = list(records)
        for index, record in enumerate(tuple(relocated)):
            start = _QUESTION_START.match(record.text)
            if (
                start is None
                or not start.group(2).strip()
                or _QUESTION_LEAD.match(start.group(2))
            ):
                continue
            for target_index in range(index + 1, min(index + 3, len(relocated))):
                target = relocated[target_index]
                if target.page != record.page or target.column != record.column:
                    break
                if not _QUESTION_LEAD.match(target.text):
                    continue
                preceding_text = " ".join(
                    item.text for item in relocated[index:target_index]
                ).strip()
                if not re.search(r"(?:다[.]?|[.!?])\s*$", preceding_text):
                    continue
                words = list(record.words)
                if not words:
                    break
                words = words[1:]
                if not words:
                    break
                relocated[index] = replace(
                    record,
                    text=" ".join(str(word.text).strip() for word in words).strip(),
                    words=tuple(words),
                    bbox=(words[0].bbox[0], record.bbox[1], record.bbox[2], record.bbox[3]),
                )
                relocated[target_index] = replace(
                    target,
                    text=f"{start.group(1)}. {target.text}",
                    bbox=(record.bbox[0], target.bbox[1], target.bbox[2], target.bbox[3]),
                )
                break
        return relocated

    def _parse_region(
        self, region: Sequence[_LineRecord], removed_noise_pages: set[int]
    ) -> ParsedOfflineQuestion:
        start = _QUESTION_START.match(region[0].text)
        assert start is not None
        number = int(start.group(1))
        first_stem_text = start.group(2).strip()

        labeled_numeric_recovery = (
            self._recover_labeled_numeric_table(region[1:])
            or self._recover_wrapped_labeled_table(region[1:])
        )
        shifted_grid_recovery = self._recover_shifted_two_by_two_grid(region)
        shifted_recovery = self._recover_shifted_visual_choices(region)
        table_recovery = self._recover_transposed_percentage_table(region[1:])
        recovery = self._recover_coordinate_choice_row(region[1:])
        has_explicit_choices = any(
            self._explicit_choice_pieces(record.text) for record in region[1:]
        ) and shifted_recovery is None and labeled_numeric_recovery is None and shifted_grid_recovery is None
        recovered_index: int | None = None
        recovered_choices: list[str] = []
        shifted_indexes: set[int] = set()
        shifted_choices: list[str] = []
        labeled_numeric_indexes: set[int] = set()
        labeled_numeric_choices: list[str] = []
        shifted_grid_indexes: set[int] = set()
        shifted_grid_overlay_indexes: set[int] = set()
        shifted_grid_choices: list[str] = []
        if shifted_grid_recovery is not None:
            (
                shifted_grid_indexes,
                shifted_grid_choices,
                shifted_grid_overlay_indexes,
            ) = shifted_grid_recovery
        if labeled_numeric_recovery is not None:
            relative_indexes, labeled_numeric_choices = labeled_numeric_recovery
            labeled_numeric_indexes = {index + 1 for index in relative_indexes}
        if shifted_recovery is not None:
            shifted_indexes, shifted_choices = shifted_recovery
        table_indexes: set[int] = set()
        if table_recovery is not None:
            relative_indexes, recovered_choices = table_recovery
            table_indexes = {index + 1 for index in relative_indexes}
        if recovery is not None and table_recovery is None:
            relative_index, recovered_choices = recovery
            recovered_index = relative_index + 1
        use_table_recovery = bool(table_indexes) and not has_explicit_choices
        use_recovery = (
            recovered_index is not None
            and not has_explicit_choices
            and not use_table_recovery
        )
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
        table_prefix_indexes: set[int] = set()
        table_first_choice_prefix = ""
        explicit_records = [
            (index, self._explicit_choice_pieces(record.text))
            for index, record in enumerate(region[1:], start=1)
            if self._explicit_choice_pieces(record.text)
        ]
        explicit_numbers = [
            number for _index, pieces in explicit_records for number, _text in pieces
        ]
        if explicit_numbers == [1, 2, 3, 4] and explicit_records:
            first_explicit = explicit_records[0][0]
            terminator = max(
                (
                    index for index, record in enumerate(region[:first_explicit])
                    if re.search(r"[?？]", record.text)
                ),
                default=0,
            )
            prelude = list(range(terminator + 1, first_explicit))
            if len(prelude) >= 3:
                header_words = sorted(region[prelude[0]].words, key=lambda word: word.bbox[0])
                gaps = [
                    float(right.bbox[0]) - float(left.bbox[2])
                    for left, right in zip(header_words, header_words[1:])
                ]
                if (
                    len(header_words) >= 3
                    and float(header_words[-1].bbox[2]) - float(header_words[0].bbox[0]) >= 0.20
                    and sum(gap >= 0.06 for gap in gaps) >= 2
                ):
                    table_prefix_indexes = set(prelude[1:])
                    table_first_choice_prefix = " ".join(
                        region[index].text for index in prelude[1:]
                    ).strip()

        for index, record in enumerate(region[1:], start=1):
            if use_table_recovery and index in table_indexes:
                continue
            if use_recovery and index == recovered_index:
                continue
            if index in damaged_indexes:
                continue
            if index in shifted_indexes:
                continue
            if index in labeled_numeric_indexes:
                continue
            if index in shifted_grid_indexes:
                continue
            if index in table_prefix_indexes:
                continue
            if index in shifted_grid_overlay_indexes:
                stripped = self._strip_overlaid_visual_prefix(record)
                if stripped:
                    stem_parts.append(stripped)
                continue
            pieces = self._explicit_choice_pieces(record.text)
            if pieces:
                explicit_choice_indexes.add(index)
                for choice_number, text in pieces:
                    explicit_marker_numbers.append(choice_number)
                    if choice_number == 1 and table_first_choice_prefix:
                        text = " ".join(
                            part for part in (table_first_choice_prefix, text) if part
                        )
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
            choices = (
                labeled_numeric_choices
                or shifted_grid_choices
                or shifted_choices
                or recovered_choices
                or damaged_choices
            )
            if labeled_numeric_choices:
                diagnostics.append("table_choice_recovery")
            elif shifted_grid_choices:
                diagnostics.append("damaged_choice_recovery")
            elif shifted_choices:
                diagnostics.append("damaged_choice_recovery")
            elif use_table_recovery:
                diagnostics.append("table_choice_recovery")
            elif recovered_choices:
                diagnostics.append("coordinate_choice_recovery")
            elif damaged_choices:
                diagnostics.append("damaged_choice_recovery")

        if len(choices) not in (4, 5):
            diagnostics.append("invalid_choice_count")
        region_pages = {record.page for record in region}
        if region_pages & removed_noise_pages:
            diagnostics.append("document_noise_removed")
        recovered_margin_indexes = set(damaged_indexes)
        recovered_margin_indexes.update(shifted_indexes)
        recovered_margin_indexes.update(labeled_numeric_indexes)
        recovered_margin_indexes.update(shifted_grid_indexes)
        if use_table_recovery:
            recovered_margin_indexes.update(table_indexes)
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

    def _recover_shifted_visual_choices(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        explicit_records = [
            (index, self._explicit_choice_pieces(record.text))
            for index, record in enumerate(region[1:], start=1)
            if self._explicit_choice_pieces(record.text)
        ]
        explicit_numbers = [
            pieces[0][0] for _index, pieces in explicit_records if len(pieces) == 1
        ]
        if explicit_numbers == [1, 2, 3, 4] and len(explicit_records) == 4:
            first_text = explicit_records[0][1][0][1]
            if len(self._normalized_text(first_text)) <= 8:
                fourth_index = explicit_records[-1][0]
                damaged_fourth = next(
                    (
                        index
                        for index in range(fourth_index + 1, len(region))
                        if _DAMAGED_VERTICAL_PATTERN.match(region[index].text)
                    ),
                    None,
                )
                if damaged_fourth is not None:
                    actual_starts = [
                        explicit_records[1][0],
                        explicit_records[2][0],
                        explicit_records[3][0],
                        damaged_fourth,
                    ]
                    boundaries = actual_starts[1:] + [len(region)]
                    choices = []
                    for offset, (start_index, end_index) in enumerate(
                        zip(actual_starts, boundaries)
                    ):
                        parts = [
                            record.text.strip()
                            for record in region[start_index:end_index]
                        ]
                        if offset < 3:
                            parts[0] = _CHOICE_PATTERN.sub("", parts[0], count=1).strip()
                        else:
                            parts[0] = _DAMAGED_VERTICAL_PATTERN.sub("", parts[0]).strip()
                        choice = " ".join(part for part in parts if part).strip()
                        if not choice:
                            return None
                        choices.append(choice)
                    return set(range(explicit_records[0][0], len(region))), choices
                content_xs = []
                for index, _pieces in explicit_records[1:]:
                    words = sorted(region[index].words, key=lambda word: word.bbox[0])
                    if len(words) < 2 or not getattr(
                        words[0], "visual_choice_marker", False
                    ):
                        break
                    content_xs.append(float(words[1].bbox[0]))
                if len(content_xs) == 3 and max(content_xs) - min(content_xs) <= 0.008:
                    content_x = fmean(content_xs)
                    split_index = next(
                        (
                            index
                            for index in range(fourth_index + 1, len(region))
                            if abs(float(region[index].bbox[0]) - content_x) <= 0.012
                            and re.search(r"[.!?。]\s*$", region[index - 1].text)
                        ),
                        None,
                    )
                    if split_index is not None:
                        actual_starts = [
                            explicit_records[1][0],
                            explicit_records[2][0],
                            explicit_records[3][0],
                            split_index,
                        ]
                        boundaries = actual_starts[1:] + [len(region)]
                        choices = []
                        for offset, (start_index, end_index) in enumerate(
                            zip(actual_starts, boundaries)
                        ):
                            parts = [
                                record.text.strip()
                                for record in region[start_index:end_index]
                            ]
                            if offset < 3:
                                parts[0] = _CHOICE_PATTERN.sub(
                                    "", parts[0], count=1
                                ).strip()
                            choice = " ".join(part for part in parts if part).strip()
                            if not choice:
                                return None
                            choices.append(choice)
                        return set(
                            range(explicit_records[0][0], len(region))
                        ), choices

        if explicit_numbers != [2, 3, 4]:
            return None
        if len(explicit_records) != 3 or any(len(pieces) != 1 for _index, pieces in explicit_records):
            return None

        first_choice_index = explicit_records[0][0]
        has_prompt_overlay = any(
            any(
                getattr(word, "visual_choice_marker", False)
                and str(word.text).strip() == "①"
                for word in record.words
            )
            and not self._explicit_choice_pieces(record.text)
            for record in region[1:first_choice_index]
        )
        if not has_prompt_overlay:
            return None

        content_xs = []
        for index, _pieces in explicit_records:
            words = sorted(region[index].words, key=lambda word: word.bbox[0])
            marker_positions = [
                offset
                for offset, word in enumerate(words)
                if getattr(word, "visual_choice_marker", False)
            ]
            if marker_positions != [0] or len(words) < 2:
                return None
            content_xs.append(float(words[1].bbox[0]))
        if max(content_xs) - min(content_xs) > 0.008:
            return None
        content_x = fmean(content_xs)

        fourth_marker_index = explicit_records[-1][0]
        split_index: int | None = None
        for index in range(fourth_marker_index + 1, len(region)):
            record = region[index]
            if abs(float(record.bbox[0]) - content_x) > 0.012:
                continue
            if index == fourth_marker_index + 1 and index == len(region) - 1:
                split_index = index
                break
            if re.search(r"[.!?。]\s*$", region[index - 1].text):
                split_index = index
                break
        if split_index is None:
            return None

        starts = [item[0] for item in explicit_records]
        boundaries = [starts[1], starts[2], split_index, len(region)]
        choices: list[str] = []
        for offset, (start_index, end_index) in enumerate(zip(starts + [split_index], boundaries)):
            parts = [record.text.strip() for record in region[start_index:end_index]]
            if offset < 3:
                parts[0] = _CHOICE_PATTERN.sub("", parts[0], count=1).strip()
            choice = " ".join(part for part in parts if part).strip()
            if not choice:
                return None
            choices.append(choice)
        return set(range(first_choice_index, len(region))), choices

    def _recover_shifted_two_by_two_grid(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str], set[int]] | None:
        explicit = [
            (index, pieces)
            for index, record in enumerate(region[1:], start=1)
            if (pieces := self._explicit_choice_pieces(record.text))
        ]
        if (
            len(explicit) != 4
            or [pieces[0][0] for _index, pieces in explicit] != [1, 2, 3, 4]
            or any(len(pieces) != 1 for _index, pieces in explicit)
        ):
            return None
        overlay = explicit[:2]
        grid = explicit[2:]
        if [index for index, _pieces in grid] != [len(region) - 2, len(region) - 1]:
            return None
        first_overlay_words = sorted(
            region[overlay[0][0]].words, key=lambda word: word.bbox[0]
        )
        second_overlay_words = sorted(
            region[overlay[1][0]].words, key=lambda word: word.bbox[0]
        )
        if (
            len(first_overlay_words) < 2
            or abs(
                float(first_overlay_words[1].bbox[0])
                - float(first_overlay_words[0].bbox[0])
            ) > 0.006
            or not second_overlay_words
            or not re.match(r"^[②-⑤][가-힣]", str(second_overlay_words[0].text).strip())
        ):
            return None

        choices: list[str] = []
        for index, _pieces in grid:
            words = sorted(region[index].words, key=lambda word: word.bbox[0])
            if not words or not getattr(words[0], "visual_choice_marker", False):
                return None
            payload = [
                word for word in words[1:]
                if str(word.text).strip() not in {"@", ".", ":", "•"}
            ]
            if len(payload) < 2:
                return None
            gaps = [
                float(payload[offset].bbox[0])
                - float(payload[offset - 1].bbox[2])
                for offset in range(1, len(payload))
            ]
            split = max(range(1, len(payload)), key=lambda offset: gaps[offset - 1])
            if gaps[split - 1] < 0.06:
                return None
            choices.extend(
                " ".join(str(word.text).strip() for word in cell).strip()
                for cell in (payload[:split], payload[split:])
            )
        if len(choices) != 4 or any(not choice for choice in choices):
            return None
        return (
            {index for index, _pieces in grid},
            choices,
            {index for index, _pieces in overlay},
        )

    @staticmethod
    def _strip_overlaid_visual_prefix(record: _LineRecord) -> str:
        words = sorted(record.words, key=lambda word: word.bbox[0])
        parts = []
        for offset, word in enumerate(words):
            text = str(word.text).strip()
            if offset == 0 and getattr(word, "visual_choice_marker", False):
                text = _CHOICE_PATTERN.sub("", text, count=1).strip()
            if text:
                parts.append(text)
        return " ".join(parts).strip()

    def _recover_labeled_numeric_table(
        self, records: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        numeric = re.compile(r"^\d+(?:\.\d+)?(?:개|명|인|년|회|차|m|톤|%)?$")
        fused_numeric = re.compile(
            r"[:.]\s*(\d+(?:\.\d+)?(?:개|명|인|년|회|차|m|톤|%)?)$"
        )
        for start in range(len(records) - 3):
            rows = records[start:start + 4]
            values = []
            for row in rows:
                row_values = []
                for word in row.words:
                    text = str(word.text).strip()
                    if numeric.fullmatch(text):
                        row_values.append((text, float(word.bbox[0])))
                    elif match := fused_numeric.search(text):
                        row_values.append((match.group(1), float(word.bbox[0])))
                values.append(row_values)
            if any(len(row_values) != 3 for row_values in values):
                continue
            columns = [
                [row_values[column][1] for row_values in values]
                for column in range(3)
            ]
            if any(max(columns[index]) - min(columns[index]) > 0.015 for index in (0, 2)):
                continue
            if any(
                min(
                    row_values[index + 1][1] - row_values[index][1]
                    for index in range(2)
                ) < 0.04
                for row_values in values
            ):
                continue
            visual_rows = sum(
                any(getattr(word, "visual_choice_marker", False) for word in row.words)
                for row in rows
            )
            damaged_rows = sum(
                any(
                    _DAMAGED_MARKER.match(str(word.text).strip())
                    for word in row.words
                )
                for row in rows
            )
            if visual_rows < 2 or damaged_rows < 1:
                continue
            choices = [
                " ".join(text for text, _x in row_values)
                for row_values in values
            ]
            return set(range(start, start + 4)), choices
        return None

    def _recover_wrapped_labeled_table(
        self, records: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        def payload_words(record: _LineRecord) -> list[LayoutWord]:
            return [
                word
                for word in sorted(record.words, key=lambda item: item.bbox[0])
                if not getattr(word, "visual_choice_marker", False)
                and not _DAMAGED_MARKER.fullmatch(str(word.text).strip())
                and str(word.text).strip() not in {"@", ".", ":", "•", "-"}
            ]

        for start in range(len(records) - 7):
            window = records[start:start + 8]
            if any(
                not 0.010 <= float(right.bbox[1]) - float(left.bbox[1]) <= 0.035
                for left, right in zip(window, window[1:])
            ):
                continue
            rows = []
            valid = True
            for offset in range(0, 8, 2):
                leading = payload_words(window[offset])
                continuation = payload_words(window[offset + 1])
                if len(leading) < 2 or not continuation:
                    valid = False
                    break
                gaps = [
                    float(leading[index].bbox[0])
                    - float(leading[index - 1].bbox[2])
                    for index in range(1, len(leading))
                ]
                split = max(range(1, len(leading)), key=lambda index: gaps[index - 1])
                if gaps[split - 1] < 0.07:
                    valid = False
                    break
                first = " ".join(str(word.text).strip() for word in leading[:split])
                second = " ".join(str(word.text).strip() for word in leading[split:])
                third = " ".join(str(word.text).strip() for word in continuation)
                if not all((first, second, third)):
                    valid = False
                    break
                rows.append(" ".join((first, second, third)))
            if not valid:
                continue
            visual_rows = sum(
                any(getattr(word, "visual_choice_marker", False) for word in window[offset].words)
                for offset in range(0, 8, 2)
            )
            damaged_rows = sum(
                any(
                    _DAMAGED_MARKER.match(str(word.text).strip())
                    for word in window[offset].words
                )
                for offset in range(0, 8, 2)
            )
            if visual_rows < 2 or damaged_rows < 1:
                continue
            return set(range(start, start + 8)), rows
        return None

    def _recover_transposed_percentage_table(
        self, records: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        percentage = re.compile(r"^\d+(?:\.\d+)?(?:%0?|/0)$")
        for start in range(len(records) - 3):
            rows = records[start:start + 4]
            values = [
                [word for word in row.words if percentage.fullmatch(str(word.text).strip())]
                for row in rows
            ]
            if any(len(row_values) != 4 for row_values in values):
                continue
            columns = [
                [float(row_values[column].bbox[0]) for row_values in values]
                for column in range(4)
            ]
            if any(max(column) - min(column) > 0.015 for column in columns):
                continue
            if any(
                not any(float(word.bbox[0]) < columns[0][row_index] - 0.015 for word in row.words)
                for row_index, row in enumerate(rows)
            ):
                continue
            choices = [
                " ".join(str(values[row][column].text).strip() for row in range(4))
                for column in range(4)
            ]
            consumed = set(range(start, start + 4))
            if start > 0 and sum(
                str(word.text).strip()[:1] in _DAMAGED_VERTICAL_MARKERS
                for word in records[start - 1].words
            ) >= 1:
                consumed.add(start - 1)
            return consumed, choices
        return None

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
            if len(groups) == 4 and self._is_sequential_proposition_row(groups):
                continue
            inline_values = self._inline_numeric_choice_values(records[index].words)
            if inline_values is not None:
                adjacent_numeric_table = any(
                    self._compact_numeric_word_count(records[neighbor].words) >= 4
                    for neighbor in (index - 1, index + 1)
                    if 0 <= neighbor < len(records)
                )
                if not adjacent_numeric_table:
                    return index, inline_values
            if len(groups) != 4:
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
        groups = self._horizontal_cells(words)
        if len(groups) == 4 and self._is_sequential_proposition_row(groups):
            return False
        if self._inline_numeric_choice_values(words) is not None:
            return True
        if len(groups) != 4:
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
        compact_value = re.compile(r"^\d+(?:\s*(?:개|명|인|년|회|차|%))?$")
        return sum(bool(compact_value.fullmatch(value.strip())) for value in values) >= 3

    def _inline_numeric_choice_values(
        self, words: Sequence[LayoutWord]
    ) -> list[str] | None:
        ordered = sorted(words, key=lambda word: word.bbox[0])
        compact_numeric = re.compile(r"^\d+(?:\.\d+)?(?:개|명|인|년|회|차|m|톤|%|/0)?$")
        numeric_words = [
            word for word in ordered if compact_numeric.fullmatch(str(word.text).strip())
        ]
        damaged_tokens = [
            word
            for word in ordered
            if _DAMAGED_MARKER.fullmatch(str(word.text).strip())
            or re.fullmatch(r"\([0O가-힣]", str(word.text).strip())
        ]
        if (
            len(numeric_words) == 4
            and damaged_tokens
            and float(numeric_words[-1].bbox[0]) - float(numeric_words[0].bbox[0]) >= 0.24
            and min(
                float(right.bbox[0]) - float(left.bbox[0])
                for left, right in zip(numeric_words, numeric_words[1:])
            ) >= 0.065
        ):
            return self._repair_fused_numeric_marker(
                [str(word.text).strip() for word in numeric_words]
            )
        if (
            len(ordered) == 6
            and _DAMAGED_MARKER.fullmatch(str(ordered[0].text).strip())
            and _DAMAGED_MARKER.fullmatch(str(ordered[4].text).strip())
        ):
            values = [
                str(word.text).strip()
                for index, word in enumerate(ordered)
                if index not in {0, 4}
            ]
            values = self._repair_fused_numeric_marker(values)
            if self._plausible_choice_values(values):
                return values
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
    def _compact_numeric_word_count(words: Sequence[LayoutWord]) -> int:
        compact_numeric = re.compile(
            r"^\d+(?:\.\d+)?(?:개|명|인|년|회|차|m|톤|%|/0)?$"
        )
        return sum(
            bool(compact_numeric.fullmatch(str(word.text).strip()))
            for word in words
        )

    @staticmethod
    def _has_damaged_marker_evidence(words: Sequence[LayoutWord]) -> bool:
        return any(
            _DAMAGED_MARKER.match(str(word.text).strip())
            for word in words
        )

    def _recover_damaged_vertical_choices(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        two_ring_recovery = self._recover_two_ring_four_paragraphs(region)
        if two_ring_recovery is not None:
            return two_ring_recovery
        paragraph_recovery = self._recover_four_damaged_paragraphs(region)
        if paragraph_recovery is not None:
            return paragraph_recovery
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
        visual_at_marker = any(
            record.words
            and record.text.lstrip().startswith("@")
            and str(record.words[0].text).strip().startswith("@")
            and getattr(record.words[0], "visual_choice_marker", False)
            for record in records[markers[-1][0]:]
        )
        if choices[-1].lstrip().startswith("@") and visual_at_marker:
            choices[-1] = choices[-1].lstrip()[1:].lstrip()
        return set(range(choice_start + 1, len(region))), choices

    def _recover_two_ring_four_paragraphs(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        marked = [
            index
            for index, record in enumerate(region[1:], start=1)
            if _DAMAGED_VERTICAL_PATTERN.match(record.text)
        ]
        if len(marked) != 2 or marked[0] >= marked[1]:
            return None
        inferred = [
            index
            for index in range(marked[0] + 1, marked[1])
            if re.search(r"[.!?。]\s*$", region[index - 1].text)
            and float(region[index].bbox[0]) >= float(region[marked[0]].bbox[0]) + 0.020
        ]
        if len(inferred) != 2:
            return None
        starts = [marked[0], *inferred, marked[1]]
        choices = []
        for offset, start_index in enumerate(starts):
            end_index = starts[offset + 1] if offset + 1 < len(starts) else len(region)
            parts = [record.text.strip() for record in region[start_index:end_index]]
            if start_index in marked:
                parts[0] = _DAMAGED_VERTICAL_PATTERN.sub("", parts[0]).strip()
            choice = " ".join(part for part in parts if part).strip()
            if not choice:
                return None
            choices.append(choice)
        return set(range(starts[0], len(region))), choices

    def _recover_four_damaged_paragraphs(
        self, region: Sequence[_LineRecord]
    ) -> tuple[set[int], list[str]] | None:
        candidates = []
        for index, record in enumerate(region[1:], start=1):
            words = sorted(record.words, key=lambda word: word.bbox[0])
            if not words:
                continue
            lead = str(words[0].text).strip()
            if re.fullmatch(r"[㉦㉨㉭1-5]", lead):
                candidates.append((index, lead))
        if len(candidates) != 4:
            return None
        if not any(lead.isdigit() for _index, lead in candidates):
            return None
        if sum(lead in _DAMAGED_VERTICAL_MARKERS for _index, lead in candidates) < 2:
            return None
        starts = [index for index, _lead in candidates]
        if max(float(region[index].bbox[0]) for index in starts) - min(
            float(region[index].bbox[0]) for index in starts
        ) > 0.008:
            return None
        choices = []
        for offset, start_index in enumerate(starts):
            end_index = starts[offset + 1] if offset + 1 < len(starts) else len(region)
            parts = [record.text.strip() for record in region[start_index:end_index]]
            parts[0] = re.sub(r"^[㉦㉨㉭1-5]\s*", "", parts[0]).strip()
            choice = " ".join(part for part in parts if part).strip()
            if not choice:
                return None
            choices.append(choice)
        return set(range(starts[0], len(region))), choices

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
