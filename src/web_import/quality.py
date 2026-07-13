"""Quality gate for parsed COMCBT exams before DB import."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.web_import.models import ComcbtParsedExam
from src.parser.question import ALL_CHOICES_CORRECT


IMAGE_CHOICE_PLACEHOLDER = "[이미지 선지]"
VISUAL_HINT_RE = re.compile(
    r"((?:다음|아래|위)\s*(?:그림|사진|그래프|회로|선도|기호|도표|파형|진리표|타임차트)|"
    r"(?:그림|사진|그래프|회로|선도|기호|도표|파형|진리표|타임차트)\s*(?:을|를)\s*(?:보고|참조)|"
    r"\b(?:following|below|above)\s+(?:fig\.?|figure|diagram|chart|graph)\b|"
    r"\bshown\s+in\s+(?:fig\.?|figure|diagram|chart|graph)\b)",
    re.IGNORECASE,
)


@dataclass
class ParsedExamQualityReport:
    importable: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    question_count: int = 0
    answer_count: int = 0
    group_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_parsed_exam(parsed_exam: ComcbtParsedExam) -> ParsedExamQualityReport:
    """Return a blocking/non-blocking quality report for a parsed exam."""

    questions = list(parsed_exam.questions or [])
    groups = list(getattr(parsed_exam, "groups", None) or [])
    diagnostics = dict(getattr(parsed_exam, "diagnostics", None) or {})
    errors: list[str] = []
    warnings: list[str] = []

    if len(questions) < 1:
        errors.append("question_count: parsed exam must contain at least one question")

    if diagnostics.get("invalid_group_range") is True:
        errors.append("invalid_group_range: parser reported an invalid group range")
    if diagnostics.get("ambiguous_group_range") is True:
        errors.append("ambiguous_group_range: ambiguous group ranges are not importable in this phase")

    for question in questions:
        _validate_question(question, errors, warnings)

    _validate_groups(questions, groups, errors)

    return ParsedExamQualityReport(
        importable=not errors,
        errors=errors,
        warnings=warnings,
        question_count=len(questions),
        answer_count=sum(1 for question in questions if getattr(question, "correct_answer", None) is not None),
        group_count=len(groups),
        diagnostics=diagnostics,
    )


def write_quality_report(report: ParsedExamQualityReport, path: Path | str) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def _validate_question(question: Any, errors: list[str], warnings: list[str]) -> None:
    question_number = getattr(question, "number", "?")
    if not str(getattr(question, "text", "") or "").strip():
        errors.append(f"blank_question_text: question {question_number} has no text")

    choices = list(getattr(question, "choices", None) or [])
    choice_numbers = sorted(getattr(choice, "number", None) for choice in choices)
    expected_numbers = list(range(1, len(choices) + 1))
    if len(choices) not in (4, 5) or choice_numbers != expected_numbers:
        errors.append(
            f"choice_count: question {question_number} must have contiguous 4 or 5 choices from 1"
        )

    correct_answer = getattr(question, "correct_answer", None)
    if correct_answer != ALL_CHOICES_CORRECT and correct_answer not in set(choice_numbers):
        errors.append(
            f"invalid_correct_answer: question {question_number} answer must match a choice number"
        )

    for choice in choices:
        choice_number = getattr(choice, "number", "?")
        text = str(getattr(choice, "text", "") or "").strip()
        if not text:
            errors.append(
                f"blank_choice_text: question {question_number} choice {choice_number} has no text"
            )

    if _requires_image_payload(question) and not _has_attached_image_payload(question):
        errors.append(
            f"missing_question_image: question {question_number} is marked image-required without an image payload"
        )


def _requires_image_payload(question: Any) -> bool:
    if bool(getattr(question, "has_image", False)):
        return True
    question_text = str(getattr(question, "text", "") or "")
    if VISUAL_HINT_RE.search(question_text):
        return True
    return any(
        str(getattr(choice, "text", "") or "").strip() == IMAGE_CHOICE_PLACEHOLDER
        for choice in getattr(question, "choices", None) or []
    )


def _has_attached_image_payload(question: Any) -> bool:
    if getattr(question, "image_path", None):
        return True
    for choice in getattr(question, "choices", None) or []:
        if getattr(choice, "image_path", None) or getattr(choice, "choice_image_path", None):
            return True
    return False


def _validate_groups(questions: list[Any], groups: list[Any], errors: list[str]) -> None:
    group_by_id: dict[str, Any] = {}
    for group in groups:
        group_id = str(getattr(group, "group_id", "") or "")
        if not group_id:
            errors.append("group_missing_id: group has no id")
            continue
        if group_id in group_by_id:
            errors.append(f"duplicate_group_id: {group_id}")
        group_by_id[group_id] = group

        if bool(getattr(group, "ambiguous_range", False)):
            errors.append(f"ambiguous_group_range: {group_id} is ambiguous")

        explicit_range = bool(getattr(group, "explicit_range", False))
        range_start = getattr(group, "range_start", None)
        range_end = getattr(group, "range_end", None)
        if explicit_range and (range_start is None or range_end is None):
            errors.append(f"group_range_missing: {group_id} is explicit without range bounds")
        if range_start is not None and range_end is not None:
            if int(range_start) > int(range_end):
                errors.append(f"group_range_order: {group_id} start exceeds end")
            expected_numbers = [
                int(getattr(question, "number"))
                for question in questions
                if int(range_start) <= int(getattr(question, "number", -1)) <= int(range_end)
            ]
            child_numbers = [int(number) for number in getattr(group, "child_numbers", [])]
            if child_numbers != expected_numbers:
                errors.append(
                    f"group_child_mismatch: {group_id} children {child_numbers} do not match range {expected_numbers}"
                )
            for question in questions:
                question_number = int(getattr(question, "number", -1))
                if int(range_start) <= question_number <= int(range_end):
                    if getattr(question, "group_id", None) != group_id:
                        errors.append(
                            f"group_assignment_mismatch: question {question_number} is not assigned to {group_id}"
                        )

    for question in questions:
        group_id = getattr(question, "group_id", None)
        if not group_id:
            continue
        if group_id not in group_by_id:
            errors.append(
                f"unknown_group_id: question {getattr(question, 'number', '?')} references {group_id}"
            )
        group_order = getattr(question, "group_order", None)
        if not isinstance(group_order, int) or group_order < 1:
            errors.append(
                f"invalid_group_order: question {getattr(question, 'number', '?')} has invalid group order"
            )
