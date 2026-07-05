"""PDF and text parser for public comcbt.com teacher exams."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import fitz

from src.parser.question import Choice, Question
from src.web_import.models import (
    ComcbtAttachment,
    ComcbtDocument,
    ComcbtParsedExam,
    ComcbtParseResult,
    ComcbtQuestionGroup,
)


FILLED_CIRCLED = {
    "❶": 1,
    "❷": 2,
    "❸": 3,
    "❹": 4,
    "❺": 5,
}
OPEN_CIRCLED = {
    "①": 1,
    "②": 2,
    "③": 3,
    "④": 4,
    "⑤": 5,
}
CHOICE_SYMBOLS = {**FILLED_CIRCLED, **OPEN_CIRCLED}
CHOICE_RE = re.compile(r"([①②③④⑤❶❷❸❹❺])")
QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*\.(?!\d)\s*(.*)")
SUBJECT_LINE_RE = re.compile(r"^\d+\s*과목\s*:\s*(.+)$")
RANGE_RE = re.compile(
    r"(?:\[\s*(?:문제\s*)?(?P<bracket_start>\d{1,3})\s*[~∼～-]\s*(?P<bracket_end>\d{1,3})\s*\]|"
    r"(?:문제|문항)\s*(?P<prefix_start>\d{1,3})\s*[~∼～-]\s*(?P<prefix_end>\d{1,3}))"
)
PASSAGE_MARKER_RE = re.compile(
    r"(\[공통(?:지문)?\]|\[\s*(?:문제\s*)?\d{1,3}\s*[~∼～-]\s*\d{1,3}\s*\]|"
    r"다음\s*(?:글|자료|지문)[을를]?\s*(?:읽고|보고)|다음은\s*.*물음에\s*답하시오)"
)
VISUAL_HINT_RE = re.compile(
    r"((?:다음|아래|위)\s*(?:그림|사진|그래프|회로|선도|기호|도표|파형|진리표|타임차트)|"
    r"(?:그림|사진|그래프|회로|선도|기호|도표|파형|진리표|타임차트)\s*(?:을|를)\s*(?:보고|참조)|"
    r"\b(?:following|below|above)\s+(?:fig\.?|figure|diagram|chart|graph)\b|"
    r"\bshown\s+in\s+(?:fig\.?|figure|diagram|chart|graph)\b)",
    re.IGNORECASE,
)
TAIL_MARKERS = (
    "전자문제집 CBT 홈페이지",
    "기출문제 및 해설집 다운로드",
    "전자문제집 CBT 앱",
)
OPEN_SYMBOL_BY_NUMBER = {
    1: "㉮",
    2: "㉯",
    3: "㉴",
    4: "㉵",
    5: "⑤",
}


class ComcbtParseError(ValueError):
    """Raised when a COMCBT document has contradictory parse signals."""


@dataclass(frozen=True)
class PdfTextLine:
    text: str
    page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None
    page_width: Optional[float] = None
    page_height: Optional[float] = None


@dataclass(frozen=True)
class PdfImageBox:
    page: int
    bbox: tuple[float, float, float, float]
    page_width: Optional[float] = None
    page_height: Optional[float] = None


@dataclass
class _SubjectEvent:
    subject_name: str


@dataclass
class _PassageEvent:
    lines: list[PdfTextLine]


@dataclass
class _QuestionEvent:
    number: int
    lines: list[PdfTextLine]

    @property
    def source_page(self) -> Optional[int]:
        for line in self.lines:
            if line.page is not None:
                return line.page + 1
        return None


class ComcbtPdfParser:
    """Parse COMCBT teacher PDFs into the existing Question/Choice model."""

    def __init__(self, image_scale: float = 2.0):
        self.image_scale = image_scale

    def parse_pdf(
        self,
        pdf_path: Path | str,
        document: ComcbtDocument,
        attachments: Optional[list[ComcbtAttachment]] = None,
        selected_attachment: Optional[ComcbtAttachment] = None,
        image_dir: Optional[Path | str] = None,
    ) -> ComcbtParsedExam:
        path = Path(pdf_path)
        doc = fitz.open(path)
        try:
            layout_lines, image_boxes = extract_document_layout(doc)
            text = "\n".join(line.text for line in layout_lines)
            if not text.strip():
                text = "\n".join(page.get_text() for page in doc)

            exam_type = exam_type_from_title(document.title)
            subject_name = subject_from_title(document.title) or "과목 구분 없음"
            year = document.year or infer_year_from_text(text) or datetime.now().year
            session = document.session or 1
            if layout_lines:
                result = self.parse_lines_result(
                    lines=layout_lines,
                    image_boxes=image_boxes,
                    exam_type=exam_type,
                    subject_name=subject_name,
                    year=year,
                    session=session,
                )
            else:
                result = self.parse_text_result(
                    text=text,
                    exam_type=exam_type,
                    subject_name=subject_name,
                    year=year,
                    session=session,
                )
            if image_dir:
                self._attach_question_crops(doc, result.questions, Path(image_dir), document)
            return ComcbtParsedExam(
                title=document.title,
                source_url=document.url,
                exam_type=exam_type,
                subject_name=subject_name,
                year=year,
                session=session,
                questions=result.questions,
                attachments=attachments or [],
                selected_attachment=selected_attachment,
                groups=result.groups,
                diagnostics=result.diagnostics,
            )
        finally:
            doc.close()

    def parse_text(
        self,
        text: str,
        exam_type: str,
        subject_name: str,
        year: int,
        session: int,
    ) -> list[Question]:
        return self.parse_text_result(
            text=text,
            exam_type=exam_type,
            subject_name=subject_name,
            year=year,
            session=session,
        ).questions

    def parse_text_result(
        self,
        text: str,
        exam_type: str,
        subject_name: str,
        year: int,
        session: int,
    ) -> ComcbtParseResult:
        lines = [PdfTextLine(raw_line) for raw_line in (text or "").splitlines()]
        return self.parse_lines_result(
            lines=lines,
            image_boxes=[],
            exam_type=exam_type,
            subject_name=subject_name,
            year=year,
            session=session,
        )

    def parse_lines_result(
        self,
        lines: list[PdfTextLine | str],
        image_boxes: Optional[list[PdfImageBox]] = None,
        exam_type: str = "COMCBT",
        subject_name: str = "과목 구분 없음",
        year: int = 0,
        session: int = 1,
    ) -> ComcbtParseResult:
        normalized_lines = normalize_layout_lines(lines)
        events = split_parse_events(normalized_lines)
        expected_numbers = [
            event.number for event in events if isinstance(event, _QuestionEvent)
        ]
        answer_key = parse_answer_key(
            [line.text for line in normalized_lines],
            expected_numbers=expected_numbers,
        )
        questions: list[Question] = []
        groups: list[ComcbtQuestionGroup] = []
        current_subject = subject_name
        active_ambiguous_group: Optional[ComcbtQuestionGroup] = None
        group_counter = 0

        for event in events:
            if isinstance(event, _SubjectEvent):
                current_subject = event.subject_name
                active_ambiguous_group = None
                continue

            if isinstance(event, _PassageEvent):
                active_ambiguous_group = None
                group_counter += 1
                group = build_group(event.lines, group_counter)
                groups.append(group)
                if group.ambiguous_range:
                    active_ambiguous_group = group
                continue

            block_lines: list[PdfTextLine] = []
            for line in event.lines:
                subject_match = SUBJECT_LINE_RE.match(line.text)
                if subject_match:
                    current_subject = normalize_space(subject_match.group(1))
                    continue
                block_lines.append(line)

            question_text, choices, inline_answer = parse_question_block(
                [line.text for line in block_lines]
            )
            tail_answer = answer_key.get(event.number)
            if inline_answer and tail_answer and inline_answer != tail_answer:
                raise ComcbtParseError(
                    f"Answer mismatch for question {event.number}: "
                    f"inline={inline_answer} tail={tail_answer}"
                )
            correct_answer = inline_answer or tail_answer
            for choice in choices:
                if not normalize_space(choice.text):
                    choice.text = "[이미지 선지]"

            has_embedded_image = block_has_embedded_image(block_lines, image_boxes or [])
            question = Question(
                number=event.number,
                text=question_text,
                choices=choices,
                correct_answer=correct_answer,
                has_image=needs_visual_context(question_text, choices) or has_embedded_image,
                image_path=None,
                source_page=event.source_page,
                subject_name=current_subject,
                year=year,
                session=session,
                exam_type=exam_type,
            )
            questions.append(question)
            if active_ambiguous_group is not None:
                attach_group_metadata(
                    question,
                    active_ambiguous_group,
                    group_order=len(active_ambiguous_group.child_numbers) + 1,
                )
                active_ambiguous_group.child_numbers.append(question.number)

        attach_explicit_groups(questions, groups)
        diagnostics = build_group_diagnostics(groups)
        return ComcbtParseResult(questions=questions, groups=groups, diagnostics=diagnostics)

    def _attach_question_crops(
        self,
        doc: fitz.Document,
        questions: list[Question],
        image_dir: Path,
        document: ComcbtDocument,
    ) -> None:
        spans = locate_question_spans(doc)
        by_number = {question.number: question for question in questions}
        safe_mid = re.sub(r"[^A-Za-z0-9_-]+", "_", document.mid or "comcbt")
        safe_doc = re.sub(r"[^A-Za-z0-9_-]+", "_", document.document_srl or "doc")
        output_dir = image_dir / safe_mid / safe_doc
        for number, span in spans.items():
            question = by_number.get(number)
            if not question or not question.has_image:
                continue
            page = doc[int(span["page"])]
            rect = fitz.Rect(
                float(span.get("x0", 0)),
                max(0, float(span["top"]) - 4),
                float(span.get("x1", page.rect.width)),
                min(page.rect.height, float(span["bottom"]) + 4),
            )
            if rect.height < 20:
                continue
            output_dir.mkdir(parents=True, exist_ok=True)
            image_path = output_dir / f"q{number:03d}.png"
            pix = page.get_pixmap(matrix=fitz.Matrix(self.image_scale, self.image_scale), clip=rect)
            pix.save(str(image_path))
            question.image_path = str(image_path)
            question.has_image = True


def normalize_space(value: str) -> str:
    value = html.unescape(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_pdf_lines(text: str) -> list[str]:
    return [line.text for line in normalize_layout_lines(
        [PdfTextLine(raw_line) for raw_line in (text or "").splitlines()]
    )]


def normalize_layout_lines(lines: list[PdfTextLine | str]) -> list[PdfTextLine]:
    normalized: list[PdfTextLine] = []
    for raw_line in lines:
        line = raw_line if isinstance(raw_line, PdfTextLine) else PdfTextLine(str(raw_line))
        text = normalize_space(line.text)
        if not text or is_cbt_footer_line(text):
            continue
        normalized.append(PdfTextLine(
            text=text,
            page=line.page,
            bbox=line.bbox,
            page_width=line.page_width,
            page_height=line.page_height,
        ))
    filtered = remove_repeated_header_footer_lines(normalized)
    if any(line.bbox is not None for line in filtered):
        return sorted(filtered, key=line_reading_order_key)
    return filtered


def line_column(line: PdfTextLine) -> int:
    if not line.bbox or not line.page_width:
        return 0
    if is_top_full_width_line(line):
        return -1
    x0, _, x1, _ = line.bbox
    return 0 if ((x0 + x1) / 2) < (line.page_width / 2) else 1


def is_top_full_width_line(line: PdfTextLine) -> bool:
    if not line.bbox or not line.page_width:
        return False
    if not is_full_width_line(line):
        return False
    _, y0, _, _ = line.bbox
    top_limit = max(120.0, (line.page_height or 0.0) * 0.20)
    return y0 <= top_limit


def is_full_width_line(line: PdfTextLine) -> bool:
    if not line.bbox or not line.page_width:
        return False
    x0, _, x1, _ = line.bbox
    width = max(0.0, x1 - x0)
    return (
        width >= line.page_width * 0.55
        or (x0 < line.page_width * 0.25 and x1 > line.page_width * 0.75)
    )


def column_bounds(page_width: Optional[float], column: int) -> tuple[float, float]:
    if not page_width:
        return (0.0, 0.0)
    if column < 0:
        return (0.0, page_width)
    midpoint = page_width / 2
    return (0.0, midpoint) if column == 0 else (midpoint, page_width)


def line_reading_order_key(line: PdfTextLine) -> tuple[int, int, float, float]:
    page = line.page if line.page is not None else -1
    if not line.bbox:
        return (page, 0, 0.0, 0.0)
    x0, y0, _, _ = line.bbox
    return (page, line_column(line), y0, x0)


def image_reading_order_key(image: PdfImageBox) -> tuple[int, int, float, float]:
    if not image.bbox:
        return (image.page, 0, 0.0, 0.0)
    x0, y0, x1, _ = image.bbox
    column = 0
    if image.page_width:
        column = 0 if ((x0 + x1) / 2) < (image.page_width / 2) else 1
    return (image.page, column, y0, x0)


def is_cbt_footer_line(text: str) -> bool:
    if "최강 자격증 기출문제 전자문제집 CBT" in text:
        return True
    return text.startswith("전자문제집 CBT :")


def remove_repeated_header_footer_lines(lines: list[PdfTextLine]) -> list[PdfTextLine]:
    pages_by_text: dict[str, set[int]] = {}
    for line in lines:
        if line.page is None:
            continue
        pages_by_text.setdefault(line.text, set()).add(line.page)

    filtered: list[PdfTextLine] = []
    for line in lines:
        page_count = len(pages_by_text.get(line.text, set()))
        if page_count >= 2 and is_margin_line(line) and not is_structural_line(line.text):
            continue
        filtered.append(line)
    return filtered


def is_margin_line(line: PdfTextLine) -> bool:
    if not line.bbox or line.page_height is None:
        return False
    _, top, _, bottom = line.bbox
    return top < 55 or bottom > line.page_height - 45


def is_structural_line(text: str) -> bool:
    if any(marker in text for marker in TAIL_MARKERS):
        return True
    if QUESTION_START_RE.match(text) or SUBJECT_LINE_RE.match(text):
        return True
    if PASSAGE_MARKER_RE.search(text) or RANGE_RE.search(text):
        return True
    if CHOICE_RE.search(text):
        return True
    return bool(re.fullmatch(r"\d{1,3}", text))


def split_parse_events(lines: list[PdfTextLine]) -> list[_SubjectEvent | _PassageEvent | _QuestionEvent]:
    events: list[_SubjectEvent | _PassageEvent | _QuestionEvent] = []
    current_number: Optional[int] = None
    current_lines: list[PdfTextLine] = []
    passage_lines: list[PdfTextLine] = []
    in_tail = False

    def flush_question() -> None:
        nonlocal current_number, current_lines
        if current_number is not None:
            events.append(_QuestionEvent(current_number, current_lines))
        current_number = None
        current_lines = []

    def flush_passage() -> None:
        nonlocal passage_lines
        if passage_lines:
            events.append(_PassageEvent(passage_lines))
        passage_lines = []

    for line in lines:
        if any(marker in line.text for marker in TAIL_MARKERS):
            in_tail = True
        if in_tail:
            continue

        question_match = QUESTION_START_RE.match(line.text)
        if question_match:
            number = int(question_match.group(1))
            if 1 <= number <= 500:
                flush_passage()
                flush_question()
                current_number = number
                current_lines = [replace_line_text(line, question_match.group(2).strip())]
                continue

        starts_new_context = SUBJECT_LINE_RE.match(line.text) or is_passage_marker(line.text)
        if current_number is not None:
            if starts_new_context and block_has_choice_marker(current_lines):
                flush_question()
            else:
                current_lines.append(line)
                continue

        subject_match = SUBJECT_LINE_RE.match(line.text)
        if subject_match:
            flush_passage()
            events.append(_SubjectEvent(normalize_space(subject_match.group(1))))
            continue

        if is_passage_marker(line.text):
            flush_passage()
            passage_lines = [line]
            continue

        if passage_lines:
            passage_lines.append(line)

    flush_question()
    flush_passage()
    return events


def split_question_blocks(lines: list[str]) -> list[tuple[int, list[str]]]:
    events = split_parse_events([PdfTextLine(line) for line in lines])
    return [
        (event.number, [line.text for line in event.lines])
        for event in events
        if isinstance(event, _QuestionEvent)
    ]


def replace_line_text(line: PdfTextLine, text: str) -> PdfTextLine:
    return PdfTextLine(
        text=text,
        page=line.page,
        bbox=line.bbox,
        page_width=line.page_width,
        page_height=line.page_height,
    )


def block_has_choice_marker(lines: list[PdfTextLine]) -> bool:
    return any(CHOICE_RE.search(line.text) for line in lines)


def is_passage_marker(text: str) -> bool:
    return bool(PASSAGE_MARKER_RE.search(text) or RANGE_RE.search(text))


def build_group(lines: list[PdfTextLine], group_index: int) -> ComcbtQuestionGroup:
    text = normalize_space(" ".join(line.text for line in lines))
    range_match = RANGE_RE.search(text)
    range_start = range_end = None
    explicit_range = False
    if range_match:
        range_start, range_end = group_range_bounds(range_match)
        if range_start > range_end:
            range_start, range_end = range_end, range_start
        explicit_range = True
    source_page = next((line.page + 1 for line in lines if line.page is not None), None)
    return ComcbtQuestionGroup(
        group_id=f"group-{group_index}",
        text=text,
        child_numbers=[],
        range_start=range_start,
        range_end=range_end,
        explicit_range=explicit_range,
        ambiguous_range=not explicit_range,
        source_page=source_page,
    )


def group_range_bounds(match: re.Match) -> tuple[int, int]:
    start = match.group("bracket_start") or match.group("prefix_start")
    end = match.group("bracket_end") or match.group("prefix_end")
    return int(start), int(end)


def attach_explicit_groups(questions: list[Question], groups: list[ComcbtQuestionGroup]) -> None:
    for group in groups:
        if not group.explicit_range or group.range_start is None or group.range_end is None:
            continue
        child_numbers: list[int] = []
        for question in questions:
            if group.range_start <= question.number <= group.range_end:
                attach_group_metadata(question, group, group_order=len(child_numbers) + 1)
                if question.number not in child_numbers:
                    child_numbers.append(question.number)
        group.child_numbers = child_numbers


def attach_group_metadata(
    question: Question,
    group: ComcbtQuestionGroup,
    group_order: Optional[int] = None,
) -> None:
    question.group_id = group.group_id
    question.group_order = group_order
    question.shared_passage = group.text


def build_group_diagnostics(groups: list[ComcbtQuestionGroup]) -> dict[str, object]:
    ranges = [
        [group.range_start, group.range_end]
        for group in groups
        if group.range_start is not None and group.range_end is not None
    ]
    child_count = sum(len(group.child_numbers) for group in groups)
    return {
        "group_detected": bool(groups),
        "group_range": ranges[0] if len(ranges) == 1 else ranges or None,
        "group_child_count": child_count,
        "ambiguous_group_range": any(group.ambiguous_range for group in groups),
        "invalid_group_range": any(
            group.explicit_range and not group.child_numbers for group in groups
        ),
    }


def parse_question_block(lines: list[str]) -> tuple[str, list[Choice], Optional[int]]:
    stem_parts: list[str] = []
    choices: list[Choice] = []
    current_choice: Optional[Choice] = None
    inline_answer: Optional[int] = None

    def append_to_current_choice(value: str) -> None:
        nonlocal current_choice
        value = normalize_space(value)
        if not value:
            return
        if current_choice is None:
            stem_parts.append(value)
            return
        current_choice.text = normalize_space(f"{current_choice.text} {value}")

    for line in lines:
        if not line:
            continue
        matches = choice_marker_matches(line)
        if matches and current_choice is None:
            prefix = normalize_space(line[:matches[0].start()])
            if prefix and not prefix_allows_inline_choices(prefix):
                matches = []
        if not matches:
            append_to_current_choice(line)
            continue
        prefix = normalize_space(line[:matches[0].start()])
        if prefix:
            append_to_current_choice(prefix)
        for index, match in enumerate(matches):
            symbol = match.group(1)
            number = CHOICE_SYMBOLS[symbol]
            if symbol in FILLED_CIRCLED:
                if inline_answer is not None and inline_answer != number:
                    raise ComcbtParseError(
                        f"Multiple inline answers in one question: {inline_answer}, {number}"
                    )
                inline_answer = number
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
            choice_text = normalize_space(line[start:end])
            current_choice = Choice(
                number=number,
                symbol=OPEN_SYMBOL_BY_NUMBER[number],
                text=choice_text,
            )
            choices.append(current_choice)

    stem = normalize_space(" ".join(part for part in stem_parts if part))
    choices = dedupe_choices(choices)
    return stem, choices, inline_answer


def choice_marker_matches(line: str) -> list[re.Match]:
    """Return circled markers that are formatted as answer choices.

    Filled circled numbers can also appear as references inside stems, such as
    "스위치 S를 ❶에 접속하였다가 ❷로 전환". Those are not choices.
    """
    return [
        match
        for match in CHOICE_RE.finditer(line)
        if is_choice_marker_context(line, match)
    ]


def is_choice_marker_context(line: str, match: re.Match) -> bool:
    start = match.start()
    end = match.end()
    after = line[end] if end < len(line) else ""
    if after and after in ":：":
        return False
    before = line[start - 1] if start > 0 else ""
    if not before:
        return True
    return before.isspace() or before in "([{:;|/\\"


def prefix_allows_inline_choices(prefix: str) -> bool:
    value = normalize_space(prefix)
    if not value:
        return True
    return value.endswith(("?", "？", ":", "："))


def dedupe_choices(choices: list[Choice]) -> list[Choice]:
    deduped: list[Choice] = []
    seen = set()
    for choice in choices:
        if choice.number in seen:
            continue
        seen.add(choice.number)
        deduped.append(choice)
    return deduped


def parse_answer_key(
    lines: list[str],
    expected_numbers: Optional[list[int]] = None,
) -> dict[int, int]:
    tail_start = None
    for index, line in enumerate(lines):
        if any(marker in line for marker in TAIL_MARKERS):
            tail_start = index
            break
    if tail_start is None:
        return {}

    expected_numbers = expected_numbers or []
    rows: list[tuple[str, list[int]]] = []
    collecting = False
    for line in lines[tail_start + 1:]:
        stripped = normalize_space(line)
        if is_answer_number_row(stripped):
            rows.append(("number", [int(token) for token in re.findall(r"\d{1,3}", stripped)]))
            collecting = True
            continue
        if is_answer_symbol_row(stripped):
            if not collecting:
                continue
            rows.append(("answer", [
                CHOICE_SYMBOLS[token] for token in re.findall(r"[①②③④⑤❶❷❸❹❺]", stripped)
            ]))
            continue
        if collecting:
            break

    numbers, answers = parse_answer_table_rows(rows)
    if not numbers or len(numbers) != len(answers):
        return {}
    if len(set(numbers)) != len(numbers):
        return {}
    if expected_numbers:
        if not answer_numbers_match_expected(numbers, expected_numbers):
            return {}
    return dict(zip(numbers, answers))


def parse_answer_table_rows(rows: list[tuple[str, list[int]]]) -> tuple[list[int], list[int]]:
    if not rows:
        return [], []

    numbers: list[int] = []
    answers: list[int] = []
    index = 0
    while index < len(rows):
        if rows[index][0] != "number":
            return [], []

        number_block: list[int] = []
        while index < len(rows) and rows[index][0] == "number":
            number_block.extend(rows[index][1])
            index += 1
        answer_block: list[int] = []
        while index < len(rows) and rows[index][0] == "answer":
            answer_block.extend(rows[index][1])
            index += 1
        if not number_block or len(number_block) != len(answer_block):
            return [], []
        numbers.extend(number_block)
        answers.extend(answer_block)
    return numbers, answers


def is_answer_number_row(text: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{1,3}\s*)+", text))


def is_answer_symbol_row(text: str) -> bool:
    return bool(re.fullmatch(r"(?:[①②③④⑤❶❷❸❹❺]\s*)+", text))


def answer_numbers_match_expected(numbers: list[int], expected_numbers: list[int]) -> bool:
    expected_set = set(expected_numbers)
    if any(number not in expected_set for number in numbers):
        return False
    expected_positions = {number: index for index, number in enumerate(expected_numbers)}
    positions = [expected_positions[number] for number in numbers]
    if positions != sorted(positions):
        return False
    return True


def needs_visual_context(question_text: str, choices: list[Choice]) -> bool:
    if any(choice.text == "[이미지 선지]" for choice in choices):
        return True
    return bool(VISUAL_HINT_RE.search(question_text or ""))


def block_has_embedded_image(lines: list[PdfTextLine], image_boxes: list[PdfImageBox]) -> bool:
    if not lines or not image_boxes:
        return False
    block_boxes = question_block_bboxes(lines)
    for image_box in image_boxes:
        block_box = block_boxes.get(image_box.page)
        if block_box and rects_intersect(block_box, image_box.bbox):
            return True
    return False


def question_block_bboxes(lines: list[PdfTextLine]) -> dict[int, tuple[float, float, float, float]]:
    boxes: dict[int, tuple[float, float, float, float]] = {}
    for line in lines:
        if line.page is None or line.bbox is None:
            continue
        x0, y0, x1, y1 = line.bbox
        if line.page_width is not None:
            x0, x1 = column_bounds(line.page_width, line_column(line))
        current = boxes.get(line.page)
        if current is None:
            boxes[line.page] = (x0, y0, x1, y1)
        else:
            boxes[line.page] = (
                min(current[0], x0),
                min(current[1], y0),
                max(current[2], x1),
                max(current[3], y1),
            )
    return boxes


def rects_intersect(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return first[0] <= second[2] and second[0] <= first[2] and first[1] <= second[3] and second[1] <= first[3]


def locate_question_spans(doc: fitz.Document) -> dict[int, dict[str, float | int]]:
    spans: dict[int, dict[str, float | int]] = {}
    for page_index, page in enumerate(doc):
        page_lines, _ = extract_page_layout(page, page_index)
        spans.update(question_spans_from_lines(page_lines, {page_index: float(page.rect.height)}))
    return spans


def question_spans_from_lines(
    lines: list[PdfTextLine],
    page_heights: Optional[dict[int, float]] = None,
) -> dict[int, dict[str, float | int]]:
    starts: list[tuple[int, PdfTextLine]] = []
    for line in sorted(lines, key=line_reading_order_key):
        match = QUESTION_START_RE.match(line.text)
        if not match or line.page is None or line.bbox is None:
            continue
        number = int(match.group(1))
        if 1 <= number <= 500:
            starts.append((number, line))

    starts_by_column: dict[tuple[int, int], list[tuple[int, PdfTextLine]]] = {}
    for number, line in starts:
        starts_by_column.setdefault((line.page, line_column(line)), []).append((number, line))

    spans: dict[int, dict[str, float | int]] = {}
    for (page, column), column_starts in starts_by_column.items():
        column_starts.sort(key=lambda item: item[1].bbox[1] if item[1].bbox else 0.0)
        for index, (number, line) in enumerate(column_starts):
            assert line.bbox is not None
            _, top, _, _ = line.bbox
            if index + 1 < len(column_starts) and column_starts[index + 1][1].bbox is not None:
                bottom = float(column_starts[index + 1][1].bbox[1])
            else:
                page_height = (page_heights or {}).get(page, line.page_height or 0.0)
                bottom = max(0.0, float(page_height) - 20.0) if page_height else float(line.bbox[3])
            x0, x1 = column_bounds(line.page_width, column)
            if x1 <= x0:
                x0, x1 = float(line.bbox[0]), float(line.bbox[2])
            spans[number] = {
                "page": page,
                "column": column,
                "top": float(top),
                "bottom": float(bottom),
                "x0": x0,
                "x1": x1,
            }
    return spans


def extract_document_layout(doc: fitz.Document) -> tuple[list[PdfTextLine], list[PdfImageBox]]:
    lines: list[PdfTextLine] = []
    images: list[PdfImageBox] = []
    for page_index, page in enumerate(doc):
        page_lines, page_images = extract_page_layout(page, page_index)
        lines.extend(page_lines)
        images.extend(page_images)
    lines.sort(key=line_reading_order_key)
    images.sort(key=image_reading_order_key)
    return lines, images


def extract_page_layout(page: fitz.Page, page_index: int) -> tuple[list[PdfTextLine], list[PdfImageBox]]:
    lines: list[PdfTextLine] = []
    images: list[PdfImageBox] = []
    data = page.get_text("dict")
    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    for block in data.get("blocks", []):
        bbox = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
        if block.get("type") == 1:
            images.append(PdfImageBox(
                page=page_index,
                bbox=bbox,
                page_width=page_width,
                page_height=page_height,
            ))
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", []))
            text = normalize_space(text)
            if not text:
                continue
            line_bbox = tuple(float(value) for value in line.get("bbox", block.get("bbox", bbox)))
            lines.append(PdfTextLine(
                text=text,
                page=page_index,
                bbox=line_bbox,
                page_width=page_width,
                page_height=page_height,
            ))
    return sorted(lines, key=line_reading_order_key), sorted(images, key=image_reading_order_key)


def extract_page_lines(page: fitz.Page) -> list[dict]:
    lines, _ = extract_page_layout(page, 0)
    return [{"text": line.text, "bbox": line.bbox} for line in lines if line.bbox is not None]


def exam_type_from_title(title: str) -> str:
    cleaned = title
    cleaned = re.sub(r"\s*-\s*최강 자격증.*$", "", cleaned)
    cleaned = re.sub(r"\s*-\s*.+전자문제집 CBT.*$", "", cleaned)
    cleaned = re.sub(r"\s*필기\s*기출문제.*$", "", cleaned)
    cleaned = re.sub(r"\s*기출문제.*$", "", cleaned)
    return normalize_space(cleaned) or "COMCBT"


def subject_from_title(title: str) -> Optional[str]:
    exam_type = exam_type_from_title(title)
    if not exam_type:
        return None
    tokens = exam_type.split()
    return tokens[-1] if tokens else None


def infer_year_from_text(text: str) -> Optional[int]:
    match = re.search(r"(20\d{2})년", text or "")
    return int(match.group(1)) if match else None
