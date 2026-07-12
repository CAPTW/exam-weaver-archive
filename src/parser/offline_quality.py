"""Fail-closed quality checks for offline exam parser candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .offline_exam import ParsedOfflineQuestion


MIN_IMPORT_CONFIDENCE = 0.70

_PLACEHOLDER = re.compile(
    r"(?:원문\s*(?:보기\s*)?참조|보기\s*참조|이미지\s*참조|첨부\s*(?:파일|그림)\s*참조)",
    re.IGNORECASE,
)
_CONTAMINATION = re.compile(
    r"(?:\b\d+\s*/\s*\d+\b|(?:^|\s)\d{1,3}\s*[.)]\s*[A-Za-z가-힣<]"
    r"|해양경찰\s*채용시험|무단\s*(?:복제|전재)|정답\s*[:：]?)",
    re.IGNORECASE,
)
_SINGLE_PROPOSITION = re.compile(r"^[㉠-㉭](?:\s+.+)?$")
_NON_BLOCKING_DIAGNOSTICS = {
    "coordinate_choice_recovery",
    "document_noise_removed",
}


@dataclass(frozen=True)
class QualityResult:
    importable: bool
    reason_codes: tuple[str, ...]


def validate_offline_question(
    question: ParsedOfflineQuestion,
    *,
    minimum_confidence: float = MIN_IMPORT_CONFIDENCE,
) -> QualityResult:
    """Return all structural rejection reasons; uncertainty always rejects."""

    reasons: list[str] = []
    stem = question.stem.strip()
    choices = [choice.strip() for choice in question.choices]

    if not stem:
        reasons.append("empty_stem")
    if len(choices) not in (4, 5):
        reasons.append("invalid_choice_count")
    if any(not choice for choice in choices):
        reasons.append("empty_choice")
    if any(_PLACEHOLDER.search(choice) for choice in choices):
        reasons.append("placeholder_choice")
    if len(set(_normalized(choice) for choice in choices)) != len(choices):
        reasons.append("duplicate_choice")
    if _looks_like_promoted_propositions(choices):
        reasons.append("proposition_choices")
    if any(_CONTAMINATION.search(choice) for choice in choices):
        reasons.append("contaminated_choice")
    if question.confidence < minimum_confidence:
        reasons.append("low_confidence")
    if any(
        diagnostic not in _NON_BLOCKING_DIAGNOSTICS
        for diagnostic in question.diagnostics
    ):
        reasons.append("parser_diagnostic")

    return QualityResult(importable=not reasons, reason_codes=tuple(reasons))


def _looks_like_promoted_propositions(choices: list[str]) -> bool:
    if len(choices) not in (4, 5):
        return False
    matches = [_SINGLE_PROPOSITION.match(choice) for choice in choices]
    if not all(matches):
        return False
    labels = [match.group(0).strip()[0] for match in matches if match]
    first = ord("㉠")
    return [ord(label) for label in labels] == list(range(first, first + len(labels)))


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
