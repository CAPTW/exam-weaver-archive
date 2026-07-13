"""Import locally saved public exam-style exam PDFs into the question DB.

The PDFs in the shared study-material folder are often browser printouts of
public exam pages, not clean attachment PDFs. This importer removes site chrome,
pairs question PDFs with answer PDFs, blocks existing exam-subject-year-session
keys, and then reuses the COMCBT parser/import quality gate.

Example:
    python scripts/import_public_exam_pdf_folder.py "T:\\내 드라이브\\[공부] 시험자료" --apply
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.web_import.comcbt_pdf import (  # noqa: E402
    CHOICE_SYMBOLS,
    QUESTION_START_RE,
    ComcbtPdfParser,
    PdfTextLine,
    answer_numbers_match_expected,
    extract_page_layout,
    is_answer_number_row,
    is_answer_symbol_row,
    normalize_space,
    parse_answer_table_rows,
)
from src.parser.offline_sources import (  # noqa: E402
    extract_offline_structured_pages,
    parse_offline_question_pdf,
)
from src.parser.question import ALL_CHOICES_CORRECT, Choice, Question  # noqa: E402
from src.web_import.importer import (  # noqa: E402
    ComcbtImportService,
    QuestionSource,
    sha256_file,
    utc_timestamp,
)
from src.web_import.models import ComcbtParsedExam, ComcbtQuestionGroup  # noqa: E402
from src.web_import.quality import evaluate_parsed_exam  # noqa: E402


DEFAULT_ROOT = Path(r"T:\내 드라이브\[공부] 시험자료")
DEFAULT_DB = ROOT / "data" / "exam_bank.db"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "public_exam_pdf_import_20260703"

QUESTION_ROLE_MARKERS = {"자료", "문제", "문제지"}
ANSWER_ROLE_MARKERS = {"정답", "답", "답안", "해설"}
ROLE_MARKERS = QUESTION_ROLE_MARKERS | ANSWER_ROLE_MARKERS
UNKNOWN_SUBJECT = "과목 구분 없음"
PROVIDER = "public_exam_pdf"
BOUNDARY_MARKER = "__PUBLIC_EXAM_QUESTION_BOUNDARY__"

EXAM_START_RE = re.compile(
    r"(\d{4}\s*년도?.{0,80}(?:시험|채용).{0,40}문\s*제\s*지|"
    r"(?:시험|채용).{0,40}문\s*제\s*지|"
    r"\b문\s*제\s*지\b)"
)
QUESTION_RE = re.compile(r"^\s*(\d{1,3})\s*\.(?!\d)\s*")
QUESTION_MARKER_RE = re.compile(r"(?<!\d)(?:^|\s)(?:문\s*)?\d{1,3}\s*\.(?!\d)")
TRAILING_QUESTION_START_RE = re.compile(r"\s(?:문\s*)?(\d{1,3})\s*\.(?!\d)\s+(?=(?:다음|아래|위|[가-힣A-Za-z]))")
YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")
SESSION_RE = re.compile(r"제\s*(\d{1,2})\s*회|(?<!\d)([1-3])\s*차")
SUBJECT_FROM_TEXT_RE = re.compile(r"(?:과\s*목|과목명)\s*[:：]?\s*([가-힣A-Za-z0-9()·/\- ]{2,40})")
ANSWER_TOKEN_RE = re.compile(r"\d{1,3}|[①②③④⑤❶❷❸❹❺]")
CHOICE_MARKER_RE = re.compile(r"[①②③④⑤❶❷❸❹❺]")

NOISE_MARKERS = (
    "공기출",
    "검색 알림",
    "마이스터디",
    "회원정보",
    "직렬 선택",
    "직렬별",
    "연도별",
    "과목별",
    "게시판",
    "조회수",
    "댓글",
    "해설등록",
    "해설수정",
    "영상검색",
    "영상등록",
    "선택해제",
    "불러오는 중",
    "Board Pagination",
    "글쓰기",
    "출석체크",
    "다크모드",
    "프리미엄",
    "랜덤게임",
    "D-day",
    "더보기",
    "All rights reserved",
    "사업자등록번호",
    "저작권 관련 신고",
    "권리 관계",
    "첨부파일",
    "다운로드",
    "목록",
    "추천",
    "비추천",
    "매우어려움",
    "어려움",
    "보통",
    "쉬움",
    "매우쉬움",
)
NO_TEXT_LISTING_MARKERS = (
    "공기출",
    "연도별",
    "과목별",
    "직렬 선택",
    "전체보기",
    "댓글 쓰기",
    "정렬",
    "제목 제목+내용",
    "Board Pagination",
    "글쓰기",
    "조회수",
    "목록",
)
HARD_STOP_MARKERS = (
    "기출 ZIP",
    "직렬과 연도를",
    "전체선택",
    "수정내역",
    "정렬 >",
    "영상검색",
    "영상등록",
    "해설등록",
    "해설수정",
    "댓글",
    "Board Pagination",
    "All rights reserved",
    "사업자등록번호",
    "저작권 관련 신고",
    "권리 관계",
)
COMMON_SUBJECT_LABELS = {
    "국어",
    "영어",
    "한국사",
    "형법",
    "형사소송법",
    "경찰학",
    "행정법",
    "헌법",
    "사회",
    "과학",
    "수학",
}

# Independent exam-format facts. OCR question/answer output is deliberately
# excluded from this registry because truncated extraction cannot establish a
# document's expected coverage.
TRUSTED_EXAM_FORMAT_QUESTION_COUNTS = {
    "해경": 20,
    "해경 1차": 20,
    "해경 2차": 20,
    "해경 3차": 20,
    "해경 경채": 20,
}


@dataclass(frozen=True)
class ExamKey:
    exam_type: str
    subject_name: str
    year: int
    session: int

    def normalized(self) -> tuple[str, str, int, int]:
        return (
            normalize_key_label(self.exam_type),
            normalize_key_label(self.subject_name),
            int(self.year),
            int(self.session),
        )


@dataclass(frozen=True)
class PdfMeta:
    path: Path
    relative_path: str
    role: str
    exam_type: str
    subject_name: str
    year: int
    session: int
    document_id: str
    top_category: str
    expected_question_count: int | None = None

    @property
    def key(self) -> ExamKey:
        return ExamKey(self.exam_type, self.subject_name, self.year, self.session)


@dataclass
class CleanTextResult:
    lines: list[PdfTextLine]
    page_count: int
    text_extractable: bool
    start_page: int | None
    end_page: int | None
    question_marker_count: int
    notes: list[str]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class NoTextProbeResult:
    cause: str
    raw_text_length: int
    question_marker_count: int
    choice_marker_count: int
    image_count: int
    page_count: int = 0
    error: str = ""


@dataclass
class ProcessResult:
    path: str
    relative_path: str
    status: str
    exam_type: str = ""
    subject_name: str = ""
    year: int | None = None
    session: int | None = None
    page_count: int | None = None
    parsed_questions: int = 0
    parsed_answers: int = 0
    saved: int = 0
    answer_pair: str = ""
    reason: str = ""


class ExistingKeyIndex:
    def __init__(self, keys: Iterable[ExamKey]):
        self._keys = {key.normalized() for key in keys}
        self._keys.update(alias.normalized() for key in keys for alias in existing_key_aliases(key))

    def contains(self, key: ExamKey) -> bool:
        if key.normalized() in self._keys:
            return True
        return any(alias.normalized() in self._keys for alias in candidate_key_aliases(key))


def normalize_key_label(value: str) -> str:
    value = normalize_space(value or "")
    value = value.replace("해양경찰", "해경")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[()（）\[\]{}]", "", value)
    return value.lower()


def normalize_exam_label(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"^\[?공부\]?\s*", "", value)
    return value or "미분류 시험"


def normalize_subject_label(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"^(자료|정답|답안|문제지?)(?:\s+|[_-]+)", "", value)
    value = re.sub(r"(?:\s+|[_-]+)(자료|정답|답안|문제지?)$", "", value)
    return value or UNKNOWN_SUBJECT


def existing_key_aliases(key: ExamKey) -> list[ExamKey]:
    aliases: list[ExamKey] = []
    exam = normalize_space(key.exam_type)
    subject = normalize_space(key.subject_name)

    if "해양경찰" in exam:
        aliases.append(ExamKey("해경", subject, key.year, key.session))
    haegyeong_session = re.fullmatch(r"(해경|해양경찰)\s*(\d+)차", exam)
    if haegyeong_session:
        aliases.append(ExamKey("해경", subject, key.year, int(haegyeong_session.group(2))))
        aliases.append(ExamKey("해양경찰", subject, key.year, int(haegyeong_session.group(2))))

    second_stage = re.fullmatch(r"(.+?)\((\d+)차\)", exam)
    if second_stage:
        aliases.append(ExamKey(normalize_exam_label(second_stage.group(1)), subject, key.year, int(second_stage.group(2))))

    if subject == UNKNOWN_SUBJECT:
        public_job = re.match(
            r"(?P<grade>\d+)급\s+(?P<org>국가직|지방직|서울시|국회직|법원직|기상직|군무원|계리직)\s*(?:공무원)?\s+(?P<subject>.+)$",
            exam,
        )
        if public_job:
            aliases.append(
                ExamKey(
                    f"{public_job.group('org')} {public_job.group('grade')}급",
                    normalize_subject_label(public_job.group("subject")),
                    key.year,
                    key.session,
                )
            )
        police = re.match(r"(?:경찰공무원|경찰)\s*(?:\(순경\))?\s*(?P<subject>.+)$", exam)
        if police:
            aliases.append(ExamKey("경찰", normalize_subject_label(police.group("subject")), key.year, key.session))

    return aliases


def candidate_key_aliases(key: ExamKey) -> list[ExamKey]:
    aliases: list[ExamKey] = []
    exam = normalize_space(key.exam_type)
    subject = normalize_space(key.subject_name)

    if exam == "해경":
        aliases.append(ExamKey("해양경찰", subject, key.year, key.session))
    haegyeong_session = re.fullmatch(r"(해경|해양경찰)\s*(\d+)차", exam)
    if haegyeong_session:
        aliases.append(ExamKey("해경", subject, key.year, int(haegyeong_session.group(2))))
        aliases.append(ExamKey("해양경찰", subject, key.year, int(haegyeong_session.group(2))))
    second_stage = re.fullmatch(r"(.+?)\((\d+)차\)", exam)
    if second_stage:
        aliases.append(ExamKey(normalize_exam_label(second_stage.group(1)), subject, key.year, int(second_stage.group(2))))
    public_job = re.match(
        r"(?P<org>국가직|지방직|서울시|국회직|법원직|기상직|군무원|계리직)\s+(?P<grade>\d+)급",
        exam,
    )
    if public_job and subject != UNKNOWN_SUBJECT:
        aliases.append(
            ExamKey(
                f"{public_job.group('grade')}급 {public_job.group('org')} 공무원 {subject}",
                UNKNOWN_SUBJECT,
                key.year,
                key.session,
            )
        )
    if exam.startswith("경찰") and subject != UNKNOWN_SUBJECT:
        aliases.append(ExamKey(f"경찰공무원 {subject}", UNKNOWN_SUBJECT, key.year, key.session))
    return aliases


def load_existing_keys(db_path: Path) -> ExistingKeyIndex:
    keys: list[ExamKey] = []
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT e.code AS exam_type,
                   s.name_ko AS subject_name,
                   q.year,
                   q.session
            FROM questions q
            JOIN exam_subjects es ON q.exam_subject_id = es.id
            JOIN exams e ON es.exam_id = e.id
            JOIN subjects s ON es.subject_id = s.id
            GROUP BY e.code, s.name_ko, q.year, q.session
            """
        ).fetchall()
    for row in rows:
        keys.append(
            ExamKey(
                str(row["exam_type"]),
                str(row["subject_name"]),
                int(row["year"]),
                int(row["session"]),
            )
        )
    return ExistingKeyIndex(keys)


def iter_pdf_paths(root: Path) -> Iterable[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                dirs: list[Path] = []
                files: list[Path] = []
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dirs.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".pdf"):
                            files.append(Path(entry.path))
                    except OSError:
                        continue
                for file_path in sorted(files, key=lambda value: value.name):
                    yield file_path
                stack.extend(sorted(dirs, key=lambda value: value.name, reverse=True))
        except OSError:
            continue


def infer_meta(path: Path, root: Path, text: str = "") -> PdfMeta:
    try:
        relative_path = str(path.relative_to(root))
        rel_parts = path.relative_to(root).parts
    except ValueError:
        relative_path = str(path)
        rel_parts = path.parts

    top_category = rel_parts[0] if len(rel_parts) > 1 else path.parent.name
    stem_parts = [part for part in path.stem.split("_") if part]
    role = ""
    role_index = -1
    for index, part in enumerate(stem_parts):
        matched_role = role_marker_for_part(part)
        if matched_role:
            role = matched_role
            role_index = index
            break

    year = infer_year(stem_parts, rel_parts, text)
    session = infer_session(rel_parts, stem_parts, text)
    document_id = infer_document_id(path, stem_parts)
    exam_type = infer_exam_type(top_category, stem_parts)
    subject_name = infer_subject_name(path, root, stem_parts, role_index, text)

    return PdfMeta(
        path=path,
        relative_path=relative_path,
        role=role or "자료",
        exam_type=exam_type,
        subject_name=subject_name,
        year=year,
        session=session,
        document_id=document_id,
        top_category=top_category,
        expected_question_count=trusted_expected_question_count(exam_type),
    )


def trusted_expected_question_count(exam_type: str) -> int | None:
    """Return only counts registered from an independent known exam format."""

    return TRUSTED_EXAM_FORMAT_QUESTION_COUNTS.get(normalize_exam_label(exam_type))


def infer_year(stem_parts: list[str], rel_parts: tuple[str, ...], text: str) -> int:
    for value in list(stem_parts) + list(rel_parts):
        match = YEAR_RE.search(value)
        if match:
            return int(match.group(1))
    match = YEAR_RE.search(text or "")
    if match:
        return int(match.group(1))
    return datetime.now().year


def infer_session(rel_parts: tuple[str, ...], stem_parts: list[str], text: str) -> int:
    for source in [text, *stem_parts, *rel_parts]:
        for match in SESSION_RE.finditer(source or ""):
            value = match.group(1) or match.group(2)
            if value:
                return int(value)
    return 1


def infer_document_id(path: Path, stem_parts: list[str]) -> str:
    if stem_parts and re.fullmatch(r"\d{4,}", stem_parts[-1]):
        return stem_parts[-1]
    digest = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", path.stem).strip("_")
    return digest[:80] or path.stem


def role_marker_for_part(part: str) -> str:
    value = normalize_space(part)
    for marker in sorted(ANSWER_ROLE_MARKERS, key=len, reverse=True):
        if value.startswith(marker) or marker in value:
            return marker
    for marker in sorted(QUESTION_ROLE_MARKERS, key=len, reverse=True):
        if value == marker or value.startswith(f"{marker}(") or value.startswith(f"{marker}["):
            return marker
    return ""


def infer_exam_type(top_category: str, stem_parts: list[str]) -> str:
    if (
        len(stem_parts) >= 2
        and YEAR_RE.fullmatch(stem_parts[0])
        and top_category in COMMON_SUBJECT_LABELS
    ):
        return normalize_exam_label(stem_parts[1])
    if top_category:
        return normalize_exam_label(top_category)
    if len(stem_parts) >= 2 and YEAR_RE.fullmatch(stem_parts[0]):
        return normalize_exam_label(stem_parts[1])
    return "미분류 시험"


def infer_subject_name(
    path: Path,
    root: Path,
    stem_parts: list[str],
    role_index: int,
    text: str,
) -> str:
    subject_parts: list[str] = []
    if role_index > 2:
        subject_parts = stem_parts[2:role_index]
    elif role_index > 1 and len(stem_parts) > 2:
        subject_parts = stem_parts[2:role_index]

    subject = normalize_subject_label(" ".join(subject_parts))
    if subject != UNKNOWN_SUBJECT and not YEAR_RE.fullmatch(subject):
        return subject

    text_match = SUBJECT_FROM_TEXT_RE.search(text or "")
    if text_match:
        candidate = normalize_subject_label(text_match.group(1))
        candidate = re.split(r"\s{2,}|문제지|응시번호|성명", candidate)[0]
        if candidate and candidate != UNKNOWN_SUBJECT:
            return candidate

    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        rel_parts = path.parts
    parent_parts = [part for part in rel_parts[:-1] if not YEAR_RE.fullmatch(part)]
    if len(parent_parts) >= 2:
        candidate = normalize_subject_label(parent_parts[-1])
        if candidate != normalize_exam_label(parent_parts[0]):
            return candidate

    return UNKNOWN_SUBJECT


def is_answer_secondary(path: Path, meta: PdfMeta) -> bool:
    if meta.role not in ANSWER_ROLE_MARKERS:
        return False
    prefix = filename_prefix_before_role(path.stem, meta.role)
    if not prefix:
        return False
    return any(path.parent.glob(f"{prefix}_자료_*.pdf")) or any(path.parent.glob(f"{prefix}_문제_*.pdf"))


def should_promote_answer_pdf(path: Path, role: str) -> bool:
    if role not in ANSWER_ROLE_MARKERS:
        return False
    prefix = filename_prefix_before_role(path.stem, role)
    if not prefix:
        return True
    has_question_pdf = any(path.parent.glob(f"{prefix}_자료_*.pdf")) or any(path.parent.glob(f"{prefix}_문제_*.pdf"))
    return not has_question_pdf


def filename_prefix_before_role(stem: str, role: str) -> str:
    parts = stem.split("_")
    role_index = next((index for index, part in enumerate(parts) if role_marker_for_part(part) == role), -1)
    if role_index < 0:
        return ""
    return "_".join(parts[:role_index])


def find_answer_pair(path: Path, meta: PdfMeta) -> Path | None:
    if meta.role not in QUESTION_ROLE_MARKERS:
        return None
    prefix = filename_prefix_before_role(path.stem, meta.role)
    if not prefix:
        return None
    candidates: list[Path] = []
    for marker in ANSWER_ROLE_MARKERS:
        candidates.extend(path.parent.glob(f"{prefix}_{marker}*.pdf"))
    candidates = [candidate for candidate in candidates if candidate != path]
    return sorted(candidates, key=lambda value: value.name)[0] if candidates else None


def clean_pdf_text(path: Path) -> CleanTextResult:
    lines: list[PdfTextLine] = []
    notes: list[str] = []
    started = False
    seen_question = False
    start_page: int | None = None
    end_page: int | None = None
    fallback_pages: list[tuple[int, list[PdfTextLine]]] = []
    fallback_page_indexes: set[int] = set()
    previous_page: tuple[int, list[PdfTextLine], int, int] | None = None

    doc = fitz.open(path)
    try:
        for page_index, page in enumerate(doc):
            page_lines, _ = extract_page_layout(page, page_index)
            page_text = "\n".join(line.text for line in page_lines)
            page_question_count = count_question_markers(page_text)
            page_choice_count = len(re.findall(r"[①②③④⑤❶❷❸❹❺]", page_text))
            if is_fallback_examish_page(page_question_count, page_choice_count):
                if previous_page is not None:
                    previous_index, previous_lines, previous_question_count, _ = previous_page
                    if previous_index == page_index - 1 and previous_question_count >= 1:
                        append_fallback_page(fallback_pages, fallback_page_indexes, previous_index, previous_lines)
                append_fallback_page(fallback_pages, fallback_page_indexes, page_index, page_lines)

            if not started and is_exam_start_page(page_text, page_question_count, page_choice_count):
                started = True
                start_page = page_index + 1
                if previous_page is not None and is_fallback_examish_page(page_question_count, page_choice_count):
                    previous_index, previous_lines, previous_question_count, _ = previous_page
                    if previous_index == page_index - 1 and previous_question_count >= 1:
                        previous_clean_lines, _, previous_seen_question = clean_page_lines(previous_lines, False)
                        if previous_clean_lines:
                            lines.extend(previous_clean_lines)
                            start_page = previous_index + 1
                            end_page = previous_index + 1
                            seen_question = seen_question or previous_seen_question

            if not started:
                previous_page = (page_index, page_lines, page_question_count, page_choice_count)
                continue

            clean_lines, hard_stop, page_seen_question = clean_page_lines(page_lines, seen_question)
            if clean_lines:
                lines.extend(clean_lines)
                end_page = page_index + 1
            seen_question = seen_question or page_seen_question
            if hard_stop and seen_question:
                break
            previous_page = (page_index, page_lines, page_question_count, page_choice_count)

        if not lines and fallback_pages:
            notes.append("fallback_question_marker_pages")
            start_page = fallback_pages[0][0] + 1
            end_page = fallback_pages[-1][0] + 1
            for _, page_lines in fallback_pages:
                clean_lines, _, _ = clean_page_lines(page_lines, True)
                lines.extend(clean_lines)

        question_marker_count = sum(1 for line in lines if QUESTION_RE.match(line.text))
        text_extractable = bool(normalize_space("\n".join(line.text for line in lines)))
        if not text_extractable:
            notes.append("no_extractable_exam_text")
        if question_marker_count == 0 and text_extractable:
            notes.append("no_question_markers")
        return CleanTextResult(
            lines=lines,
            page_count=doc.page_count,
            text_extractable=text_extractable,
            start_page=start_page,
            end_page=end_page,
            question_marker_count=question_marker_count,
            notes=notes,
        )
    finally:
        doc.close()


def append_fallback_page(
    fallback_pages: list[tuple[int, list[PdfTextLine]]],
    fallback_page_indexes: set[int],
    page_index: int,
    page_lines: list[PdfTextLine],
) -> None:
    if page_index in fallback_page_indexes:
        return
    fallback_pages.append((page_index, page_lines))
    fallback_page_indexes.add(page_index)


def is_fallback_examish_page(question_count: int, choice_count: int) -> bool:
    return question_count >= 1 and choice_count >= 4


def count_question_markers(text: str) -> int:
    return len(QUESTION_MARKER_RE.findall(text or ""))


def count_choice_markers(text: str) -> int:
    return len(CHOICE_MARKER_RE.findall(text or ""))


def classify_no_text_probe(raw_text: str, image_count: int, clean_text_length: int = 0) -> str:
    compact_text = normalize_space(raw_text or "")
    raw_text_length = len(compact_text)
    question_marker_count = count_question_markers(raw_text or "")
    choice_marker_count = count_choice_markers(raw_text or "")
    listing_marker_count = sum(1 for marker in NO_TEXT_LISTING_MARKERS if marker in compact_text)

    if clean_text_length > 0:
        return "has_clean_text"
    if raw_text_length == 0 and image_count > 0:
        return "ocr_required"
    if raw_text_length == 0 and image_count == 0:
        return "empty_or_unreadable_pdf"
    if question_marker_count >= 1 and choice_marker_count >= 4:
        return "text_start_detection_failed"
    if choice_marker_count == 0 and (question_marker_count >= 5 or listing_marker_count >= 3):
        return "listing_or_non_exam_page"
    if raw_text_length >= 500:
        return "text_non_exam_or_answer_only"
    return "unknown_no_text"


def build_no_text_probe_result(raw_text: str, image_count: int, page_count: int, error: str = "") -> NoTextProbeResult:
    return NoTextProbeResult(
        cause=classify_no_text_probe(raw_text, image_count),
        raw_text_length=len(normalize_space(raw_text or "")),
        question_marker_count=count_question_markers(raw_text or ""),
        choice_marker_count=count_choice_markers(raw_text or ""),
        image_count=image_count,
        page_count=page_count,
        error=error,
    )


def probe_no_text_pdf(path: Path) -> NoTextProbeResult:
    try:
        raw_pages: list[str] = []
        image_count = 0
        with fitz.open(path) as doc:
            for page in doc:
                raw_pages.append(page.get_text("text") or "")
                image_count += len(page.get_images(full=True))
            page_count = doc.page_count
        return build_no_text_probe_result("\n".join(raw_pages), image_count, page_count)
    except Exception as exc:  # pragma: no cover - depends on damaged PDFs.
        return NoTextProbeResult(
            cause="pdf_probe_error",
            raw_text_length=0,
            question_marker_count=0,
            choice_marker_count=0,
            image_count=0,
            page_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )


def no_text_probe_reason(clean_notes: list[str], probe: NoTextProbeResult) -> str:
    parts = list(clean_notes)
    parts.extend(
        [
            f"raw_probe={probe.cause}",
            f"raw_text_length={probe.raw_text_length}",
            f"raw_question_markers={probe.question_marker_count}",
            f"raw_choice_markers={probe.choice_marker_count}",
            f"raw_images={probe.image_count}",
        ]
    )
    if probe.error:
        parts.append(f"raw_probe_error={probe.error}")
    return ";".join(parts)


def is_fast_skippable_non_exam_listing(meta: PdfMeta, probe: NoTextProbeResult) -> bool:
    return (
        meta.role in QUESTION_ROLE_MARKERS
        and meta.subject_name == UNKNOWN_SUBJECT
        and probe.cause == "listing_or_non_exam_page"
        and probe.raw_text_length >= 1000
        and probe.choice_marker_count == 0
    )


def is_exam_start_page(page_text: str, question_count: int, choice_count: int) -> bool:
    if EXAM_START_RE.search(page_text):
        return True
    return is_fallback_examish_page(question_count, choice_count)


def clean_page_lines(
    page_lines: list[PdfTextLine],
    seen_question_before_page: bool,
) -> tuple[list[PdfTextLine], bool, bool]:
    clean_lines: list[PdfTextLine] = []
    hard_stop = False
    seen_question = False
    skipped_header = False

    for line in page_lines:
        text = normalize_gong_line(line.text)
        if not text:
            continue
        if is_repeated_exam_header_line(text) or (
            (seen_question_before_page or seen_question) and EXAM_START_RE.search(text)
        ):
            skipped_header = seen_question_before_page or seen_question
            continue
        if skipped_header and (seen_question_before_page or seen_question):
            clean_lines.append(copy_line(line, BOUNDARY_MARKER))
            skipped_header = False
        if contains_question_marker(text):
            seen_question = True

        if is_noise_line(text):
            if (seen_question_before_page or seen_question) and is_hard_stop_line(text):
                hard_stop = True
                break
            continue

        clean_lines.append(
            PdfTextLine(
                text=text,
                page=line.page,
                bbox=line.bbox,
                page_width=line.page_width,
                page_height=line.page_height,
            )
        )

    return clean_lines, hard_stop, seen_question


def normalize_gong_line(text: str) -> str:
    text = normalize_space(text)
    if not text:
        return ""
    match = re.search(r"(\d{4}\s*년도?.{0,120}문\s*제\s*지.*)$", text)
    if match:
        text = match.group(1)
    text = re.sub(r"(?<!\d)문\s*(\d{1,3})\s*\.", r"\1.", text)
    text = re.sub(r"\s*ZIPN\s*", " ", text)
    text = re.sub(r"\[\s*image\s*\]", " [image] ", text, flags=re.IGNORECASE)
    text = re.sub(r"^nambupolice\.com\s*", "", text, flags=re.IGNORECASE)
    return normalize_space(text)


def is_noise_line(text: str) -> bool:
    if EXAM_START_RE.search(text):
        return False
    question_match = QUESTION_RE.match(text)
    if question_match:
        remainder = normalize_space(text[question_match.end():])
        if re.fullmatch(r"\[image\](?:\s*답\s*\+\d+|\s*\d{4}\.\d{1,2}\.\d{1,2}\.)?", remainder):
            return True
        return False
    if is_answer_number_row(text) or is_answer_symbol_row(text):
        return False
    if re.fullmatch(r"(?:\d{1,3}\s+){4,}\d{1,3}\s+(?:[①②③④⑤❶❷❸❹❺]\s*){4,}", text):
        return False
    return is_hard_stop_line(text) or any(marker in text for marker in NOISE_MARKERS)


def contains_question_marker(text: str) -> bool:
    return bool(QUESTION_RE.match(text) or re.search(r"(?<!\d)(?:^|\s)\d{1,3}\.(?!\d)", text))


def is_hard_stop_line(text: str) -> bool:
    return any(marker in text for marker in HARD_STOP_MARKERS)


def is_repeated_exam_header_line(text: str) -> bool:
    return any(marker in text for marker in ("응시번호", "성명", "남부경찰학원", "http://", "과목 "))


def parse_gong_answer_key(lines: list[PdfTextLine], expected_numbers: list[int]) -> dict[int, int]:
    row_key = parse_answer_rows_anywhere([line.text for line in lines], expected_numbers)
    token_key = parse_answer_tokens_anywhere("\n".join(line.text for line in lines), expected_numbers)
    if len(token_key) > len(row_key):
        return token_key
    return row_key


def parse_answer_rows_anywhere(lines: list[str], expected_numbers: list[int]) -> dict[int, int]:
    rows: list[tuple[str, list[int]]] = []
    collecting = False
    for line in lines:
        stripped = normalize_space(line)
        if is_answer_number_row(stripped):
            rows.append(("number", [int(token) for token in re.findall(r"\d{1,3}", stripped)]))
            collecting = True
            continue
        if is_answer_symbol_row(stripped):
            if collecting:
                rows.append(("answer", [CHOICE_SYMBOLS[token] for token in re.findall(r"[①②③④⑤❶❷❸❹❺]", stripped)]))
            continue
        if collecting and rows:
            numbers, answers = parse_answer_table_rows(rows)
            if numbers and len(numbers) == len(answers):
                key = validate_answer_key(dict(zip(numbers, answers)), expected_numbers)
                if key:
                    return key
            rows = []
            collecting = False

    numbers, answers = parse_answer_table_rows(rows)
    if not numbers or len(numbers) != len(answers):
        return {}
    return validate_answer_key(dict(zip(numbers, answers)), expected_numbers)


def parse_answer_tokens_anywhere(text: str, expected_numbers: list[int]) -> dict[int, int]:
    tokens = ANSWER_TOKEN_RE.findall(text or "")
    if not tokens:
        return {}
    expected_set = set(expected_numbers)
    collected: dict[int, int] = {}
    best: dict[int, int] = {}
    index = 0
    while index < len(tokens):
        if not is_ascii_number_token(tokens[index]):
            index += 1
            continue
        number_start = index
        numbers: list[int] = []
        while index < len(tokens) and is_ascii_number_token(tokens[index]):
            value = int(tokens[index])
            if 1 <= value <= 500:
                numbers.append(value)
                index += 1
            else:
                break
        if len(numbers) < 5:
            index = number_start + 1
            continue
        answer_tokens: list[str] = []
        while index < len(tokens) and tokens[index] in CHOICE_SYMBOLS:
            answer_tokens.append(tokens[index])
            index += 1
        if numbers and numbers[0] == 2 and len(answer_tokens) == len(numbers) + 1:
            numbers = [1, *numbers]
        if len(answer_tokens) != len(numbers):
            index = number_start + 1
            continue
        if not is_monotonic_number_block(numbers):
            index = number_start + 1
            continue
        block = dict(zip(numbers, [CHOICE_SYMBOLS[token] for token in answer_tokens]))
        if expected_set:
            block = {number: answer for number, answer in block.items() if number in expected_set}
        if len(block) > len(best):
            best = block
        collected.update(block)
    return validate_answer_key(collected, expected_numbers) or validate_answer_key(best, expected_numbers)


def is_ascii_number_token(token: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{1,3}", token or ""))


def is_monotonic_number_block(numbers: list[int]) -> bool:
    if len(set(numbers)) != len(numbers):
        return False
    return all(right == left + 1 for left, right in zip(numbers, numbers[1:]))


def validate_answer_key(answer_key: dict[int, int], expected_numbers: list[int]) -> dict[int, int]:
    if not answer_key:
        return {}
    if len(set(answer_key)) != len(answer_key):
        return {}
    if expected_numbers:
        ordered_numbers = [number for number in sorted(answer_key) if number in set(expected_numbers)]
        if not ordered_numbers:
            return {}
        if not answer_numbers_match_expected(ordered_numbers, expected_numbers):
            return {}
        answer_key = {number: answer_key[number] for number in ordered_numbers}
    if len(answer_key) < 5:
        return {}
    return answer_key


def build_parsed_exam(
    meta: PdfMeta,
    question_text: CleanTextResult,
    answer_text: CleanTextResult | None,
    source_url: str,
) -> tuple[ComcbtParsedExam, dict[int, int]]:
    parser = ComcbtPdfParser()
    parser_lines = replace_boundary_markers(
        protect_nonsequential_question_starts(expand_parser_lines(question_text.lines)),
        meta.subject_name,
    )
    result = parser.parse_lines_result(
        parser_lines,
        image_boxes=[],
        exam_type=meta.exam_type,
        subject_name=meta.subject_name,
        year=meta.year,
        session=meta.session,
    )
    answer_lines = list(parser_lines)
    if answer_text is not None:
        answer_lines.extend(replace_boundary_markers(expand_parser_lines(answer_text.lines), meta.subject_name))
    expected_numbers = [question.number for question in result.questions]
    answer_key = parse_gong_answer_key(answer_lines, expected_numbers)
    for question in result.questions:
        if question.correct_answer is None:
            question.correct_answer = answer_key.get(question.number)
    parsed = ComcbtParsedExam(
        title=f"{meta.exam_type} {meta.year}년 {meta.session}회 {meta.subject_name}",
        source_url=source_url,
        exam_type=meta.exam_type,
        subject_name=meta.subject_name,
        year=meta.year,
        session=meta.session,
        questions=result.questions,
        attachments=[],
        selected_attachment=None,
        groups=result.groups,
        diagnostics=dict(result.diagnostics),
    )
    return parsed, answer_key


def build_ocr_required_exam(
    path: Path,
    meta: PdfMeta,
    answer_text: CleanTextResult | None,
    source_url: str,
    answer_path: Path | None = None,
) -> tuple[ComcbtParsedExam, dict[int, int]]:
    """Convert shared structured-parser output into the public importer model."""

    offline = parse_offline_question_pdf(
        path,
        {
            "exam_type": meta.exam_type,
            "subject_name": meta.subject_name,
            "year": meta.year,
            "session": meta.session,
            "probe": {"role": meta.role},
        },
    )
    answer_key: dict[int, int] = {}
    answer_lines: list[PdfTextLine] = []
    if answer_text is not None:
        if answer_text.text_extractable:
            answer_lines = replace_boundary_markers(
                expand_parser_lines(answer_text.lines), meta.subject_name
            )
        elif answer_path is not None:
            answer_pages = extract_offline_structured_pages(
                answer_path, {"probe": {"role": "정답"}}
            )
            answer_lines = structured_pages_to_pdf_lines(answer_pages)
    if answer_lines:
        answer_key = parse_gong_answer_key(answer_lines, [])

    if meta.expected_question_count:
        expected_numbers = list(range(1, meta.expected_question_count + 1))
    else:
        expected_numbers = []

    questions = [
        Question(
            number=candidate.number,
            text=candidate.stem,
            choices=[
                Choice(number=index, symbol=str(index), text=text)
                for index, text in enumerate(candidate.choices, start=1)
            ],
            correct_answer=answer_key.get(candidate.number),
            source_page=candidate.source_page,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            exam_type=meta.exam_type,
        )
        for candidate in offline.questions
    ]
    actual_numbers = [question.number for question in questions]
    groups = structured_question_groups(offline.structured_pages, meta, questions)
    return (
        ComcbtParsedExam(
            title=f"{meta.exam_type} {meta.year}년 {meta.session}회 {meta.subject_name}",
            source_url=source_url,
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            questions=questions,
            attachments=[],
            selected_attachment=None,
            groups=groups,
            diagnostics={
                "parser": "offline_structured",
                "rejected_question_count": len(offline.rejected),
                "expected_question_numbers": expected_numbers,
                "actual_question_numbers": actual_numbers,
                "expected_question_coverage_unknown": not expected_numbers,
                "question_coverage_mismatch": bool(expected_numbers) and actual_numbers != expected_numbers,
            },
        ),
        answer_key,
    )


def structured_pages_to_pdf_lines(pages) -> list[PdfTextLine]:
    """Adapt normalized structured layout lines to the COMCBT line model."""

    output: list[PdfTextLine] = []
    for page in pages:
        for line in page.lines:
            x0, y0, x1, y1 = line.bbox
            output.append(
                PdfTextLine(
                    text=line.text,
                    page=page.number - 1,
                    bbox=(
                        x0 * page.width,
                        y0 * page.height,
                        x1 * page.width,
                        y1 * page.height,
                    ),
                    page_width=page.width,
                    page_height=page.height,
                )
            )
    return output


def structured_question_groups(
    pages, meta: PdfMeta, questions: list[Question]
) -> list[ComcbtQuestionGroup]:
    """Recover shared-passage groups from the same structured OCR lines."""

    if not pages:
        return []
    context = ComcbtPdfParser().parse_lines_result(
        structured_pages_to_pdf_lines(pages),
        image_boxes=[],
        exam_type=meta.exam_type,
        subject_name=meta.subject_name,
        year=meta.year,
        session=meta.session,
    )
    by_number = {question.number: question for question in questions}
    for group in context.groups:
        child_numbers = list(group.child_numbers)
        if not child_numbers and group.range_start is not None and group.range_end is not None:
            child_numbers = [
                number
                for number in range(group.range_start, group.range_end + 1)
                if number in by_number
            ]
            group.child_numbers = child_numbers
        for order, number in enumerate(child_numbers, start=1):
            question = by_number.get(number)
            if question is None:
                continue
            question.group_id = group.group_id
            question.group_order = order
            question.shared_passage = group.text
    return context.groups


def replace_boundary_markers(lines: list[PdfTextLine], subject_name: str) -> list[PdfTextLine]:
    return [
        copy_line(line, f"1과목 : {subject_name}") if line.text == BOUNDARY_MARKER else line
        for line in lines
    ]


def expand_parser_lines(lines: list[PdfTextLine]) -> list[PdfTextLine]:
    expanded: list[PdfTextLine] = []
    for line in lines:
        for segment in split_embedded_question_starts(line.text):
            expanded.extend(split_inline_choices(line, segment))
    return expanded


def split_embedded_question_starts(text: str) -> list[str]:
    value = normalize_space(text)
    if not value:
        return []
    matches = list(re.finditer(r"(?<!\d)(?=(?:^|\s)(\d{1,3})\.(?!\d))", value))
    if not matches:
        return [value]

    segments: list[str] = []
    first_start = matches[0].start()
    if first_start > 0:
        prefix = normalize_space(value[:first_start])
        if prefix:
            segments.append(prefix)
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        segment = normalize_space(value[start:end])
        if segment:
            segments.append(segment)
    return segments


def split_inline_choices(template_line: PdfTextLine, text: str) -> list[PdfTextLine]:
    markers = list(re.finditer(r"[①②③④⑤❶❷❸❹❺]", text))
    if len(markers) < 2:
        trailing_split = split_trailing_question_start_from_choice(text)
        if len(trailing_split) > 1:
            return [copy_line(template_line, segment) for segment in trailing_split]
        if (
            len(markers) == 1
            and markers[0].group(0) in {"①", "❶"}
            and normalize_space(text[: markers[0].start()])
        ):
            prefix = normalize_space(text[: markers[0].start()])
            suffix = normalize_space(text[markers[0].start():])
            return [copy_line(template_line, prefix), copy_line(template_line, suffix)]
        return [copy_line(template_line, text)]
    segments: list[str] = []
    prefix = normalize_space(text[: markers[0].start()])
    if prefix:
        segments.append(prefix)
    for index, marker in enumerate(markers):
        start = marker.start()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        segment = normalize_space(text[start:end])
        if segment:
            segments.append(segment)
    split_segments: list[str] = []
    for segment in segments:
        split_segments.extend(split_trailing_question_start_from_choice(segment))
    return [copy_line(template_line, segment) for segment in split_segments]


def split_trailing_question_start_from_choice(text: str) -> list[str]:
    value = normalize_space(text)
    if not value:
        return [value] if value else []
    matches = list(TRAILING_QUESTION_START_RE.finditer(value))
    if not matches:
        return [value]
    match = matches[-1]
    if not any(symbol in value[: match.start()] for symbol in CHOICE_SYMBOLS):
        return [value]
    prefix = normalize_space(value[: match.start()])
    suffix = normalize_gong_line(value[match.start():])
    return [segment for segment in (prefix, suffix) if segment]


def protect_nonsequential_question_starts(lines: list[PdfTextLine]) -> list[PdfTextLine]:
    protected: list[PdfTextLine] = []
    expected_next = 1
    in_embedded_numbered_list = False
    embedded_number = 0

    for line in lines:
        text = normalize_space(line.text)
        if re.search(r"[①②③④⑤❶❷❸❹❺]", text):
            in_embedded_numbered_list = False

        match = QUESTION_RE.match(text)
        if not match:
            protected.append(line)
            continue

        number = int(match.group(1))
        if in_embedded_numbered_list:
            if number == expected_next and is_likely_real_question_start(text, match.end(), expected_next):
                in_embedded_numbered_list = False
                protected.append(line)
                expected_next += 1
                continue
            if number <= max(expected_next, embedded_number + 1):
                protected.append(copy_line(line, re.sub(r"^\s*(\d{1,3})\s*\.", r"\1)", text, count=1)))
                embedded_number = number
                continue
            in_embedded_numbered_list = False

        if number == expected_next:
            protected.append(line)
            expected_next += 1
            continue

        if number < expected_next:
            in_embedded_numbered_list = True
            embedded_number = number
            protected.append(copy_line(line, re.sub(r"^\s*(\d{1,3})\s*\.", r"\1)", text, count=1)))
            continue

        protected.append(line)
        if number > expected_next:
            expected_next = number + 1

    return protected


def is_likely_real_question_start(text: str, question_prefix_end: int, expected_number: int) -> bool:
    remainder = normalize_space(text[question_prefix_end:])
    if len(remainder) < 4:
        return False
    if re.search(r"(다음|아래|무엇|어느|어떤|옳|알 수|고르|적절|\?)", remainder):
        return True
    return expected_number >= 10 and len(remainder) >= 12


def copy_line(line: PdfTextLine, text: str) -> PdfTextLine:
    text = strip_inline_artifacts(text)
    return PdfTextLine(
        text=text,
        page=line.page,
        bbox=line.bbox,
        page_width=line.page_width,
        page_height=line.page_height,
    )


def strip_inline_artifacts(text: str) -> str:
    value = normalize_space(text)
    value = re.sub(
        r"\s+(?:19|20)\d{2}\s*년\s*도?.{0,120}(?:해\s*양|경\s*찰|채\s*용|시\s*험|문\s*제).*$",
        "",
        value,
    )
    value = re.sub(r"\s+\[image\]\s*(?:직렬|연도|0|수정내역|신고|저장).*$", "", value)
    return normalize_space(value)


def extra_quality_errors(parsed: ComcbtParsedExam, answer_key: dict[int, int]) -> list[str]:
    errors: list[str] = []
    questions = list(parsed.questions)
    numbers = [question.number for question in questions]
    if len(questions) < 10:
        errors.append("question_count_below_safe_threshold")
    if parsed.diagnostics.get("question_coverage_mismatch"):
        errors.append("question_coverage_mismatch")
    if parsed.diagnostics.get("expected_question_coverage_unknown"):
        errors.append("expected_question_coverage_unknown")
    if int(parsed.diagnostics.get("rejected_question_count", 0) or 0):
        errors.append("offline_rejected_questions")
    if questions and not answer_key and not any(question.correct_answer is not None for question in questions):
        errors.append("answer_key_missing")
    if numbers and sorted(numbers) != list(range(min(numbers), max(numbers) + 1)):
        errors.append("question_numbers_not_contiguous")
    if answer_key and len(questions) != len(answer_key):
        errors.append(f"answer_key_count_mismatch: questions={len(questions)} answers={len(answer_key)}")
    if any(
        not isinstance(answer, int)
        or not (answer == ALL_CHOICES_CORRECT or 1 <= answer <= 5)
        for answer in answer_key.values()
    ):
        errors.append("invalid_answer_value")
    if any(
        question.correct_answer is not None
        and (
            not isinstance(question.correct_answer, int)
            or not (
                question.correct_answer == ALL_CHOICES_CORRECT
                or 1 <= question.correct_answer <= len(question.choices)
            )
        )
        for question in questions
    ):
        errors.append("invalid_question_answer")
    if parsed.subject_name == UNKNOWN_SUBJECT and all((q.subject_name or UNKNOWN_SUBJECT) == UNKNOWN_SUBJECT for q in questions):
        errors.append("unknown_subject")
    return errors


def filter_fragment_questions(
    parsed: ComcbtParsedExam,
    answer_key: dict[int, int],
) -> tuple[ComcbtParsedExam, dict[int, int], int]:
    kept = [
        question
        for question in parsed.questions
        if normalize_space(question.text) or list(question.choices or [])
    ]
    removed = len(parsed.questions) - len(kept)
    if removed == 0:
        return parsed, answer_key, 0

    kept_numbers = {question.number for question in kept}
    groups: list[ComcbtQuestionGroup] = []
    for group in parsed.groups:
        child_numbers = [number for number in group.child_numbers if number in kept_numbers]
        if not child_numbers:
            continue
        groups.append(
            ComcbtQuestionGroup(
                group_id=group.group_id,
                text=group.text,
                child_numbers=child_numbers,
                range_start=group.range_start,
                range_end=group.range_end,
                explicit_range=group.explicit_range,
                ambiguous_range=group.ambiguous_range,
                source_page=group.source_page,
            )
        )

    filtered = ComcbtParsedExam(
        title=parsed.title,
        source_url=parsed.source_url,
        exam_type=parsed.exam_type,
        subject_name=parsed.subject_name,
        year=parsed.year,
        session=parsed.session,
        questions=kept,
        attachments=parsed.attachments,
        selected_attachment=parsed.selected_attachment,
        groups=groups,
        diagnostics=dict(parsed.diagnostics),
    )
    return filtered, {number: answer for number, answer in answer_key.items() if number in kept_numbers}, removed


def filter_existing_key_questions(
    parsed: ComcbtParsedExam,
    existing_keys: ExistingKeyIndex,
) -> tuple[ComcbtParsedExam, int]:
    kept = []
    skipped = 0
    for question in parsed.questions:
        key = ExamKey(
            str(question.exam_type or parsed.exam_type),
            str(question.subject_name or parsed.subject_name),
            int(question.year or parsed.year),
            int(question.session or parsed.session),
        )
        if existing_keys.contains(key):
            skipped += 1
        else:
            kept.append(question)

    if skipped == 0:
        return parsed, 0

    kept_numbers = {question.number for question in kept}
    groups: list[ComcbtQuestionGroup] = []
    for group in parsed.groups:
        child_numbers = [number for number in group.child_numbers if number in kept_numbers]
        if not child_numbers:
            continue
        groups.append(
            ComcbtQuestionGroup(
                group_id=group.group_id,
                text=group.text,
                child_numbers=child_numbers,
                range_start=group.range_start,
                range_end=group.range_end,
                explicit_range=group.explicit_range,
                ambiguous_range=group.ambiguous_range,
                source_page=group.source_page,
            )
        )
    filtered = ComcbtParsedExam(
        title=parsed.title,
        source_url=parsed.source_url,
        exam_type=parsed.exam_type,
        subject_name=parsed.subject_name,
        year=parsed.year,
        session=parsed.session,
        questions=kept,
        attachments=parsed.attachments,
        selected_attachment=parsed.selected_attachment,
        groups=groups,
        diagnostics=dict(parsed.diagnostics),
    )
    return filtered, skipped


def process_pdf(
    path: Path,
    root: Path,
    db_path: Path,
    out_dir: Path,
    existing_keys: ExistingKeyIndex,
    apply: bool,
    pre_skip_existing: bool,
    include_answer_pdfs: bool,
    write_text_cache: bool,
) -> ProcessResult:
    quick_meta = infer_meta(path, root)
    if (
        quick_meta.role in ANSWER_ROLE_MARKERS
        and not include_answer_pdfs
        and not should_promote_answer_pdf(path, quick_meta.role)
    ):
        return ProcessResult(
            path=str(path),
            relative_path=quick_meta.relative_path,
            status="skipped_answer_secondary",
            exam_type=quick_meta.exam_type,
            subject_name=quick_meta.subject_name,
            year=quick_meta.year,
            session=quick_meta.session,
        )
    if pre_skip_existing and quick_meta.subject_name != UNKNOWN_SUBJECT and existing_keys.contains(quick_meta.key):
        return ProcessResult(
            path=str(path),
            relative_path=quick_meta.relative_path,
            status="skipped_existing_key_precheck",
            exam_type=quick_meta.exam_type,
            subject_name=quick_meta.subject_name,
            year=quick_meta.year,
            session=quick_meta.session,
            reason="exam_subject_year_session already exists",
        )

    no_text_pre_probe: NoTextProbeResult | None = None
    if quick_meta.subject_name == UNKNOWN_SUBJECT and quick_meta.role in QUESTION_ROLE_MARKERS:
        no_text_pre_probe = probe_no_text_pdf(path)
        if is_fast_skippable_non_exam_listing(quick_meta, no_text_pre_probe):
            return ProcessResult(
                path=str(path),
                relative_path=quick_meta.relative_path,
                status="skipped_non_exam_listing",
                exam_type=quick_meta.exam_type,
                subject_name=quick_meta.subject_name,
                year=quick_meta.year,
                session=quick_meta.session,
                page_count=no_text_pre_probe.page_count,
                reason=no_text_probe_reason(["pre_probe_non_exam_listing"], no_text_pre_probe),
            )

    question_text = clean_pdf_text(path)
    meta = infer_meta(path, root, question_text.text)
    answer_pair = find_answer_pair(path, meta)
    answer_text = clean_pdf_text(answer_pair) if answer_pair is not None else None
    if write_text_cache:
        write_text_cache_files(out_dir, meta, question_text, answer_pair, answer_text)

    use_shared_ocr_parser = False
    if not question_text.text_extractable:
        no_text_probe = no_text_pre_probe or probe_no_text_pdf(path)
        use_shared_ocr_parser = no_text_probe.cause == "ocr_required"
        if not use_shared_ocr_parser:
            status = "skipped_non_exam_listing" if no_text_probe.cause == "listing_or_non_exam_page" else "blocked_no_text"
            return ProcessResult(
                path=str(path),
                relative_path=meta.relative_path,
                status=status,
                exam_type=meta.exam_type,
                subject_name=meta.subject_name,
                year=meta.year,
                session=meta.session,
                page_count=question_text.page_count or no_text_probe.page_count,
                answer_pair=str(answer_pair or ""),
                reason=no_text_probe_reason(question_text.notes, no_text_probe),
            )

    if pre_skip_existing and existing_keys.contains(meta.key):
        return ProcessResult(
            path=str(path),
            relative_path=meta.relative_path,
            status="skipped_existing_key_precheck",
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            page_count=question_text.page_count,
            answer_pair=str(answer_pair or ""),
            reason="exam_subject_year_session already exists",
        )

    try:
        source_url = local_source_url(path)
        if use_shared_ocr_parser:
            parsed, answer_key = build_ocr_required_exam(
                path, meta, answer_text, source_url, answer_path=answer_pair
            )
        else:
            parsed, answer_key = build_parsed_exam(meta, question_text, answer_text, source_url)
    except Exception as exc:
        return ProcessResult(
            path=str(path),
            relative_path=meta.relative_path,
            status="blocked_parse_error",
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            page_count=question_text.page_count,
            answer_pair=str(answer_pair or ""),
            reason=f"{type(exc).__name__}: {exc}",
        )

    if use_shared_ocr_parser and not parsed.questions:
        return ProcessResult(
            path=str(path),
            relative_path=meta.relative_path,
            status="blocked_no_text",
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            page_count=question_text.page_count,
            answer_pair=str(answer_pair or ""),
            reason="shared structured OCR parser produced no importable questions",
        )

    parsed, answer_key, skipped_fragment_questions = filter_fragment_questions(parsed, answer_key)
    parsed, skipped_existing_questions = filter_existing_key_questions(parsed, existing_keys)
    if not parsed.questions:
        return ProcessResult(
            path=str(path),
            relative_path=meta.relative_path,
            status="skipped_existing_key",
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            page_count=question_text.page_count,
            parsed_questions=0,
            parsed_answers=0,
            answer_pair=str(answer_pair or ""),
            reason=(
                f"all parsed questions overlap existing keys; skipped={skipped_existing_questions}; "
                f"fragment_questions_removed={skipped_fragment_questions}"
            ),
        )

    report = evaluate_parsed_exam(parsed)
    additional_errors = extra_quality_errors(parsed, answer_key)
    if additional_errors or not report.importable:
        write_review_payload(out_dir, meta, parsed, report.errors + additional_errors)
        return ProcessResult(
            path=str(path),
            relative_path=meta.relative_path,
            status="blocked_quality",
            exam_type=meta.exam_type,
            subject_name=meta.subject_name,
            year=meta.year,
            session=meta.session,
            page_count=question_text.page_count,
            parsed_questions=len(parsed.questions),
            parsed_answers=sum(1 for question in parsed.questions if question.correct_answer),
            answer_pair=str(answer_pair or ""),
            reason="; ".join(report.errors + additional_errors),
        )

    source = QuestionSource(
        provider=PROVIDER,
        source_url=source_url,
        document_id=meta.document_id,
        attachment_url=None,
        attachment_filename=path.name,
        content_hash=sha256_file(path),
        fetched_at=utc_timestamp(),
    )
    service = ComcbtImportService(db_path)
    quality_report_path = out_dir / "quality_reports" / f"{safe_file_stem(path)}.json"
    result = service.import_exam(
        parsed,
        source,
        force=False,
        quality_report_path=quality_report_path,
        apply=apply,
    )
    append_questions_master(out_dir, meta, parsed, result.status)

    return ProcessResult(
        path=str(path),
        relative_path=meta.relative_path,
        status=result.status if apply else "dry_run_importable",
        exam_type=meta.exam_type,
        subject_name=meta.subject_name,
        year=meta.year,
        session=meta.session,
        page_count=question_text.page_count,
        parsed_questions=len(parsed.questions),
        parsed_answers=sum(1 for question in parsed.questions if question.correct_answer),
        saved=result.saved,
        answer_pair=str(answer_pair or ""),
            reason=";".join(
                part
                for part in [
                    f"skipped_existing_questions={skipped_existing_questions}" if skipped_existing_questions else "",
                    f"fragment_questions_removed={skipped_fragment_questions}" if skipped_fragment_questions else "",
                ]
                if part
            ),
    )


def local_source_url(path: Path) -> str:
    return "file:///" + str(path.resolve()).replace("\\", "/")


def safe_file_stem(path: Path) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]+", "_", path.stem).strip("_")[:120]


def write_text_cache_files(
    out_dir: Path,
    meta: PdfMeta,
    question_text: CleanTextResult,
    answer_pair: Path | None,
    answer_text: CleanTextResult | None,
) -> None:
    text_dir = out_dir / "extracted_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "pdf_id": meta.document_id,
        "filename": meta.path.name,
        "relative_path": meta.relative_path,
        "start_page": question_text.start_page,
        "end_page": question_text.end_page,
        "text": question_text.text,
        "answer_pair": str(answer_pair or ""),
        "answer_text": answer_text.text if answer_text else "",
    }
    (text_dir / f"{safe_file_stem(meta.path)}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_review_payload(out_dir: Path, meta: PdfMeta, parsed: ComcbtParsedExam, errors: list[str]) -> None:
    review_dir = out_dir / "review_payloads"
    review_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "path": str(meta.path),
            "relative_path": meta.relative_path,
            "exam_type": meta.exam_type,
            "subject_name": meta.subject_name,
            "year": meta.year,
            "session": meta.session,
        },
        "errors": errors,
        "summary": parsed.to_summary(),
        "question_numbers": [question.number for question in parsed.questions],
    }
    (review_dir / f"{safe_file_stem(meta.path)}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_questions_master(out_dir: Path, meta: PdfMeta, parsed: ComcbtParsedExam, import_status: str) -> None:
    path = out_dir / "02_questions_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "question_id",
                "pdf_id",
                "filename",
                "relative_path",
                "page_start",
                "page_end",
                "year",
                "exam_name",
                "subject",
                "section",
                "question_number",
                "topic_l1",
                "topic_l2",
                "topic_l3",
                "concept_tags",
                "question_type",
                "difficulty_estimate",
                "cognitive_skill",
                "evidence_excerpt",
                "answer_present",
                "confidence",
                "needs_human_review",
                "review_reason",
                "import_status",
            ],
        )
        if write_header:
            writer.writeheader()
        for question in parsed.questions:
            writer.writerow(
                {
                    "question_id": f"{meta.document_id}:{question.number}",
                    "pdf_id": meta.document_id,
                    "filename": meta.path.name,
                    "relative_path": meta.relative_path,
                    "page_start": question.source_page or "",
                    "page_end": question.source_page or "",
                    "year": question.year or parsed.year,
                    "exam_name": question.exam_type or parsed.exam_type,
                    "subject": question.subject_name or parsed.subject_name,
                    "section": "",
                    "question_number": question.number,
                    "topic_l1": question.subject_name or parsed.subject_name,
                    "topic_l2": "",
                    "topic_l3": "",
                    "concept_tags": "",
                    "question_type": "multiple_choice",
                    "difficulty_estimate": "unknown",
                    "cognitive_skill": "unknown",
                    "evidence_excerpt": normalize_space(question.text)[:160],
                    "answer_present": bool(question.correct_answer),
                    "confidence": "0.85",
                    "needs_human_review": "false",
                    "review_reason": "",
                    "import_status": import_status,
                }
            )


def append_inventory(out_dir: Path, result: ProcessResult) -> None:
    path = out_dir / "01_pdf_inventory.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "filename",
                "relative_path",
                "page_count",
                "text_extractable",
                "ocr_required",
                "inferred_exam",
                "inferred_year",
                "inferred_subject",
                "session",
                "status",
                "parsed_questions",
                "parsed_answers",
                "saved",
                "answer_pair",
                "notes",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "filename": Path(result.path).name,
                "relative_path": result.relative_path,
                "page_count": result.page_count or "",
                "text_extractable": result.status not in {"blocked_no_text", "skipped_non_exam_listing"},
                "ocr_required": "raw_probe=ocr_required" in result.reason,
                "inferred_exam": result.exam_type,
                "inferred_year": result.year or "",
                "inferred_subject": result.subject_name,
                "session": result.session or "",
                "status": result.status,
                "parsed_questions": result.parsed_questions,
                "parsed_answers": result.parsed_answers,
                "saved": result.saved,
                "answer_pair": result.answer_pair,
                "notes": result.reason,
            }
        )


def append_review_queue(out_dir: Path, result: ProcessResult) -> None:
    if not result.status.startswith("blocked"):
        return
    path = out_dir / "human_review_queue.csv"
    write_header = not path.exists()
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "relative_path",
                "status",
                "exam_type",
                "subject_name",
                "year",
                "session",
                "parsed_questions",
                "parsed_answers",
                "review_reason",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "relative_path": result.relative_path,
                "status": result.status,
                "exam_type": result.exam_type,
                "subject_name": result.subject_name,
                "year": result.year or "",
                "session": result.session or "",
                "parsed_questions": result.parsed_questions,
                "parsed_answers": result.parsed_answers,
                "review_reason": result.reason,
            }
        )


def load_processed_paths(out_dir: Path) -> set[str]:
    inventory = out_dir / "01_pdf_inventory.csv"
    if not inventory.exists():
        return set()
    with inventory.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return {row["relative_path"] for row in csv.DictReader(handle) if row.get("relative_path")}


def load_reprocess_pdf_paths(reprocess_list: Path, root: Path, statuses: Iterable[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    status_filter = {status for status in (statuses or []) if status}
    with reprocess_list.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            if status_filter and (row.get("status") or "") not in status_filter:
                continue
            relative_path = row.get("relative_path") or ""
            absolute_path = row.get("absolute_path") or row.get("path") or ""
            path = root / relative_path if relative_path else Path(absolute_path)
            if not path:
                continue
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            paths.append(path)
    return paths


def parse_reprocess_status_filters(values: Iterable[str]) -> list[str]:
    statuses: list[str] = []
    for value in values:
        statuses.extend(part.strip() for part in value.split(",") if part.strip())
    return statuses


def backup_db(db_path: Path, out_dir: Path) -> Path:
    backup_dir = out_dir / "db_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}.{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def write_summary(out_dir: Path, summary: dict) -> None:
    (out_dir / "import_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(DEFAULT_ROOT), help="PDF root folder")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Target SQLite question DB")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output/report directory")
    parser.add_argument("--apply", action="store_true", help="Write importable questions to DB")
    parser.add_argument("--max-files", type=int, default=None, help="Stop after N newly processed PDFs")
    parser.add_argument("--resume", action="store_true", help="Skip PDFs already present in inventory")
    parser.add_argument("--include-answer-pdfs", action="store_true", help="Also process answer PDFs as primary candidates")
    parser.add_argument("--write-text-cache", action="store_true", help="Write cleaned text JSON cache for every processed PDF")
    parser.add_argument("--no-pre-skip-existing", action="store_true", help="Do not skip existing keys before text extraction")
    parser.add_argument("--skip-backup", action="store_true", help="Do not create a DB backup before apply mode")
    parser.add_argument("--reprocess-list", default="", help="CSV with relative_path or absolute_path column to process")
    parser.add_argument(
        "--reprocess-status",
        action="append",
        default=[],
        help="Only process rows from --reprocess-list with this status. Can be repeated or comma-separated.",
    )
    parser.add_argument("--log-every", type=int, default=25, help="Progress print interval")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = Path(args.root)
    db_path = Path(args.db)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not root.exists():
        raise SystemExit(f"PDF root does not exist: {root}")
    if not db_path.exists():
        raise SystemExit(f"DB does not exist: {db_path}")

    processed_paths = load_processed_paths(out_dir) if args.resume else set()
    reprocess_statuses = parse_reprocess_status_filters(args.reprocess_status)
    reprocess_pdf_paths = (
        load_reprocess_pdf_paths(Path(args.reprocess_list), root, reprocess_statuses) if args.reprocess_list else None
    )
    existing_keys = load_existing_keys(db_path)
    backup_path = str(backup_db(db_path, out_dir)) if args.apply and not args.skip_backup else ""

    counts: Counter[str] = Counter()
    total_seen = 0
    total_processed = 0
    total_saved = 0
    started_at = datetime.now().isoformat(timespec="seconds")

    print(f"root={root}")
    print(f"db={db_path}")
    print(f"output={out_dir}")
    print(f"mode={'apply' if args.apply else 'dry-run'}")
    if backup_path:
        print(f"backup={backup_path}")

    pdf_paths = reprocess_pdf_paths if reprocess_pdf_paths is not None else iter_pdf_paths(root)
    for pdf_path in pdf_paths:
        total_seen += 1
        try:
            rel = str(pdf_path.relative_to(root))
        except ValueError:
            rel = str(pdf_path)
        if rel in processed_paths:
            counts["resume_skipped"] += 1
            continue

        result = process_pdf(
            path=pdf_path,
            root=root,
            db_path=db_path,
            out_dir=out_dir,
            existing_keys=existing_keys,
            apply=args.apply,
            pre_skip_existing=not args.no_pre_skip_existing,
            include_answer_pdfs=args.include_answer_pdfs,
            write_text_cache=args.write_text_cache,
        )
        append_inventory(out_dir, result)
        append_review_queue(out_dir, result)
        processed_paths.add(rel)
        counts[result.status] += 1
        total_processed += 1
        total_saved += result.saved

        if args.apply and result.saved:
            existing_keys = load_existing_keys(db_path)

        if total_processed % max(1, args.log_every) == 0:
            print(
                f"processed={total_processed} seen={total_seen} "
                f"saved={total_saved} latest={result.status} {result.relative_path}"
            )

        if args.max_files is not None and total_processed >= args.max_files:
            break

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "db": str(db_path),
        "output_dir": str(out_dir),
        "mode": "apply" if args.apply else "dry-run",
        "backup_path": backup_path,
        "seen_pdf_count": total_seen,
        "processed_pdf_count": total_processed,
        "saved_question_count": total_saved,
        "status_counts": dict(counts),
    }
    write_summary(out_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
