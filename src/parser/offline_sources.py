"""Document inventory and fail-closed adapters for offline exam PDFs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, MutableMapping

from .extractor import PDFExtractor
from .offline_exam import OfflineExamParser, ParsedOfflineQuestion
from .offline_quality import validate_offline_question


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

    output_dir = frozen_metadata.get("extract_dir", "outputs/offline_parser_cache")
    content = PDFExtractor(str(output_dir)).extract(str(source_path))
    pages = tuple(
        page.structured_page
        for page in content.pages
        if getattr(page, "structured_page", None) is not None
    )
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
    )


def select_group_questions(
    group: Mapping[str, object],
    parse_source: Callable[[Path, Mapping[str, object] | None], OfflineParseResult],
    cache: MutableMapping[str, OfflineParseResult],
    metadata: Mapping[str, object] | None = None,
) -> tuple[dict[int, ParsedOfflineQuestion], int]:
    """Select shared-parser questions whose source pages belong to one exam group."""

    raw_pages = list(group.get("pages", []) or [])
    page_numbers = {
        int(page.get("page", 0) or 0)
        for page in raw_pages
        if isinstance(page, Mapping)
    }
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
        rejected_count += sum(
            rejected.question.source_page in page_numbers
            for rejected in result.rejected
        )
        for question in result.questions:
            if question.source_page not in page_numbers:
                continue
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
