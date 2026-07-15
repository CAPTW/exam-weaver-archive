"""Document inventory and fail-closed adapters for offline exam PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Sequence

from .extractor import PDFExtractor
from .layout import StructuredPage
from .offline_exam import OfflineExamParser, ParsedOfflineQuestion
from .offline_quality import validate_offline_question
from .offline_repairs import apply_audited_source_repair
from .question import ALL_CHOICES_CORRECT


class DocumentRole(str, Enum):
    QUESTION = "question"
    ANSWER = "answer"
    NOTICE = "notice"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RejectedOfflineQuestion:
    question: ParsedOfflineQuestion
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class OfflineParseResult:
    path: Path
    role: DocumentRole
    metadata: Mapping[str, object]
    questions: tuple[ParsedOfflineQuestion, ...]
    rejected: tuple[RejectedOfflineQuestion, ...]
    structured_pages: tuple[StructuredPage, ...] = ()


class OfflineSetValidationError(RuntimeError):
    """Raised before persistence when an expected offline exam set is incomplete."""


Probe = Mapping[str, Any] | object | Callable[[Path], Mapping[str, Any] | object]

_NOTICE_TEXT = re.compile(r"(?:채용|시험|연간).{0,30}공고|공고.{0,30}(?:채용|시험|계획)")
_ANSWER_TEXT = re.compile(r"(?:기출)?(?:정답|답안)|정답\s*&\s*해설|확정\s*답안|정답\s*및\s*해설")
_QUESTION_TEXT = re.compile(r"(?:기출)?문제(?:지)?")


def classify_offline_document(path: Path, probe: Probe | None = None) -> DocumentRole:
    """Classify an offline PDF before extraction.

    Strong filename roles win over content-density probes. Recruitment notices
    are checked first because their names often contain the word ``시험``.
    """

    path = Path(path)
    searchable_path = _normalize_role_text(str(path))
    filename = _normalize_role_text(path.name)

    if _NOTICE_TEXT.search(filename):
        return DocumentRole.NOTICE
    if _ANSWER_TEXT.search(searchable_path) or "정답안" in searchable_path:
        return DocumentRole.ANSWER
    if _QUESTION_TEXT.search(filename):
        return DocumentRole.QUESTION

    # The two native 2023 question papers omit an explicit role marker.
    if re.search(r"2023\s*2차\s*-\s*(?:물리|항해)$", _normalize_role_text(path.stem)):
        return DocumentRole.QUESTION

    probe_value = probe(path) if callable(probe) else probe
    probe_data = _probe_mapping(probe_value)
    probe_text = _normalize_role_text(str(probe_data.get("text", "") or ""))
    probe_role = _normalize_role_text(str(probe_data.get("role", "") or ""))
    if _NOTICE_TEXT.search(probe_text):
        return DocumentRole.NOTICE
    if probe_role in {"정답", "답", "답안", "해설", "answer"}:
        return DocumentRole.ANSWER
    if _ANSWER_TEXT.search(probe_text) or int(probe_data.get("answer_marker_count", 0) or 0) > 0:
        return DocumentRole.ANSWER
    if probe_role in {"자료", "문제", "문제지", "question"}:
        return DocumentRole.QUESTION
    question_markers = int(probe_data.get("question_marker_count", 0) or 0)
    choice_markers = int(probe_data.get("choice_marker_count", 0) or 0)
    if question_markers > 0 and choice_markers >= 4:
        return DocumentRole.QUESTION
    return DocumentRole.UNKNOWN


def parse_offline_question_pdf(
    path: Path,
    metadata: Mapping[str, object] | None,
) -> OfflineParseResult:
    """Extract and parse one question PDF through the shared structured path.

    Answers, notices, and unknown documents are filtered before expensive PDF
    extraction. Structurally invalid candidates are retained only in the review
    collection and are never repaired with generic choices.
    """

    source_path = Path(path)
    frozen_metadata = MappingProxyType(dict(metadata or {}))
    role = classify_offline_document(source_path, frozen_metadata.get("probe"))
    if role is not DocumentRole.QUESTION:
        return OfflineParseResult(source_path, role, frozen_metadata, (), ())

    pages = extract_offline_structured_pages(source_path, frozen_metadata)
    candidates = OfflineExamParser().parse_pages(pages)

    accepted: list[ParsedOfflineQuestion] = []
    rejected: list[RejectedOfflineQuestion] = []
    for candidate in candidates:
        quality = validate_offline_question(candidate)
        if quality.importable:
            accepted.append(candidate)
        else:
            rejected.append(RejectedOfflineQuestion(candidate, quality.reason_codes))

    return OfflineParseResult(
        source_path,
        role,
        frozen_metadata,
        tuple(accepted),
        tuple(rejected),
        pages,
    )


def extract_offline_structured_pages(
    path: Path, metadata: Mapping[str, object] | None = None
) -> tuple[StructuredPage, ...]:
    """Extract structured pages for a document whose role is already known."""

    source_metadata = dict(metadata or {})
    output_dir = source_metadata.get("extract_dir", "outputs/offline_parser_cache")
    content = PDFExtractor(str(output_dir)).extract(str(Path(path)))
    return tuple(
        page.structured_page
        for page in content.pages
        if getattr(page, "structured_page", None) is not None
    )


def require_complete_offline_set(
    questions: Mapping[int, object],
    *,
    expected_numbers: Sequence[int],
    answers: Sequence[int],
    rejected_count: int,
    choice_counts: Mapping[int, int],
    unavailable_answer_numbers: Iterable[int] = (),
) -> None:
    """Block a complete exam set before any partial or invalid data can persist."""

    expected = [int(number) for number in expected_numbers]
    unavailable = {int(number) for number in unavailable_answer_numbers}
    present = set(int(number) for number in questions)
    missing = [number for number in expected if number not in present]
    extra = sorted(present - set(expected))
    if missing or extra:
        raise OfflineSetValidationError(
            f"missing_questions: missing={missing} extra={extra}"
        )
    if rejected_count:
        raise OfflineSetValidationError(
            f"rejected_questions: count={int(rejected_count)}"
        )
    invalid_answers: list[tuple[int, object]] = []
    if len(answers) != len(expected):
        invalid_answers.append((-1, f"count={len(answers)} expected={len(expected)}"))
    else:
        for number, answer in zip(expected, answers):
            choice_count = int(choice_counts.get(number, 0) or 0)
            if number in unavailable:
                valid = answer == 0
            else:
                valid = isinstance(answer, int) and (
                    answer == ALL_CHOICES_CORRECT or 1 <= answer <= choice_count
                )
            if not valid:
                invalid_answers.append((number, answer))
    if invalid_answers:
        raise OfflineSetValidationError(f"invalid_answers: {invalid_answers}")


def require_persistable_offline_questions(items: Iterable[object]) -> None:
    """Defense-in-depth guard at the database persistence boundary."""

    invalid: list[tuple[int, object]] = []
    for item in items:
        question = getattr(item, "question", item)
        number = int(getattr(question, "number", 0) or 0)
        answer = getattr(question, "correct_answer", None)
        answer_available = bool(getattr(question, "answer_available", True))
        choice_count = len(getattr(question, "choices", ()) or ())
        if answer_available:
            valid = isinstance(answer, int) and (
                answer == ALL_CHOICES_CORRECT or 1 <= answer <= choice_count
            )
        else:
            valid = answer == 0
        if not valid:
            invalid.append((number, answer))
    if invalid:
        raise OfflineSetValidationError(f"invalid_answers: {invalid}")


def select_group_questions(
    group: Mapping[str, object],
    parse_source: Callable[[Path, Mapping[str, object] | None], OfflineParseResult],
    cache: MutableMapping[str, OfflineParseResult],
    metadata: Mapping[str, object] | None = None,
    candidate_transform: Callable[
        [ParsedOfflineQuestion, Path], ParsedOfflineQuestion
    ] | None = None,
) -> tuple[dict[int, ParsedOfflineQuestion], int]:
    """Select shared-parser questions whose source pages belong to one exam group."""

    raw_pages = list(group.get("pages", []) or [])
    source_paths = sorted(
        {
            str(page.get("source_path", "") or "")
            for page in raw_pages
            if isinstance(page, Mapping) and page.get("source_path")
        }
    )

    selected: dict[int, ParsedOfflineQuestion] = {}
    rejected_count = 0
    for source_path in source_paths:
        result = cache.get(source_path)
        if result is None:
            result = parse_source(Path(source_path), metadata)
            cache[source_path] = result
        source_page_numbers = {
            int(page.get("page", 0) or 0)
            for page in raw_pages
            if isinstance(page, Mapping)
            and str(page.get("source_path", "") or "") == source_path
            and int(page.get("page", 0) or 0) > 0
        }
        scoped_pages = tuple(
            page
            for page in result.structured_pages
            if page.number in source_page_numbers
        )
        available_page_numbers = {page.number for page in result.structured_pages}
        if source_page_numbers and not source_page_numbers <= available_page_numbers:
            missing = sorted(source_page_numbers - available_page_numbers)
            raise OfflineSetValidationError(
                "structured_scope_incomplete: "
                f"source={source_path} requested={sorted(source_page_numbers)} "
                f"available={sorted(available_page_numbers)} missing={missing}"
            )
        if source_page_numbers:
            candidates = OfflineExamParser().parse_pages(list(scoped_pages))
            scoped_questions: list[ParsedOfflineQuestion] = []
            for candidate in candidates:
                candidate = apply_audited_source_repair(
                    candidate, Path(source_path)
                )
                if candidate_transform is not None:
                    candidate = candidate_transform(candidate, Path(source_path))
                quality = validate_offline_question(candidate)
                if quality.importable:
                    scoped_questions.append(candidate)
                else:
                    rejected_count += 1
        else:
            rejected_count += len(result.rejected)
            scoped_questions = list(result.questions)
        for question in scoped_questions:
            current = selected.get(question.number)
            if current is None or question.confidence > current.confidence:
                selected[question.number] = question
    return selected, rejected_count


def _probe_mapping(probe: object | None) -> Mapping[str, Any]:
    if probe is None:
        return {}
    if isinstance(probe, Mapping):
        return probe
    values = getattr(probe, "__dict__", None)
    return values if isinstance(values, Mapping) else {}


def _normalize_role_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ")).strip().casefold()
