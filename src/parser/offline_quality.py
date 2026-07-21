"""Fail-closed quality checks for offline exam parser candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .formatting import has_suspicious_text_artifact
from .offline_exam import ParsedOfflineQuestion
from .rich_text_quality import inspect_rich_text
from .text_quality import text_quality_issue_codes


MIN_IMPORT_CONFIDENCE = 0.70

_PLACEHOLDER = re.compile(
    r"(?:원문\s*(?:보기\s*)?참조|보기\s*참조|이미지\s*참조|첨부\s*(?:파일|그림)\s*참조)",
    re.IGNORECASE,
)
_CONTAMINATION = re.compile(
    r"(?:(?:^|\s)\d{1,3}\s*[.)]\s*(?=(?:다음|아래|[「<]))"
    r"|(?:^|\s)@(?=\s|$)|해양경찰\s*채용시험|\b(?:19|20)\d{2}년\s*도.{0,40}(?:시험|경찰|해양)"
    r"|^\s*(?:\([0O1-5]\)|[0O])\s+"
    r"|무단\s*(?:복제|전재)|정답\s*[:：]?)",
    re.IGNORECASE,
)
_SINGLE_PROPOSITION = re.compile(r"^[㉠-㉭](?:\s+.+)?$")
_QUESTION_TEXT_IN_CHOICE = re.compile(
    r"(?:"
    r"(?:가장\s*)?(?:옳|틀)[^?？\n]{0,24}것은\s*[?？]"
    r"|고려하지\s*아니한다[.)]"
    r"|어느\s+[^?？\n]{0,40}(?:인가|있는가)\s*[?？9]?"
    r")"
)
_OUTER_DAMAGED_MARKER = re.compile(r"^[㉦㉨㉭]")
_NON_BLOCKING_DIAGNOSTICS = {
    "aligned_choice_table_recovery",
    "coordinate_choice_recovery",
    "document_noise_removed",
    "damaged_choice_recovery",
    "explicit_proposition_choices",
    "legacy_choice_grid_recovery",
    "source_duplicate_choices",
    "source_choice_repair",
    "source_text_repair",
    "source_unavailable_choices",
    "table_choice_recovery",
    "underlined_choice_recovery",
    "validated_baseline_recovery",
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
    _append_text_quality_reasons(reasons, stem, "stem")
    for choice in choices:
        _append_text_quality_reasons(reasons, choice, "choice")
    question_inspection = inspect_rich_text(
        stem,
        question.question_format_json,
        owner="question",
        text_path="stem",
        format_path="question_format_json",
    )
    for issue in question_inspection.issues:
        reasons.append(f"{issue.code}_question_format")
    for surface in question_inspection.surfaces[1:]:
        _append_text_quality_reasons(
            reasons,
            surface.text,
            "question_format",
        )
    for index, choice in enumerate(choices):
        format_json = (
            question.choice_format_jsons[index]
            if index < len(question.choice_format_jsons)
            else None
        )
        inspection = inspect_rich_text(
            choice,
            format_json,
            owner="choice",
            text_path=f"choices[{index}]",
            format_path=f"choice_format_jsons[{index}]",
        )
        for issue in inspection.issues:
            reasons.append(f"{issue.code}_choice_format")
        for surface in inspection.surfaces[1:]:
            _append_text_quality_reasons(
                reasons,
                surface.text,
                "choice_format",
            )
    if len(choices) not in (4, 5):
        reasons.append("invalid_choice_count")
    if any(not choice for choice in choices):
        reasons.append("empty_choice")
    if any(_PLACEHOLDER.search(choice) for choice in choices):
        reasons.append("placeholder_choice")
    if (
        len(set(_normalized(choice) for choice in choices)) != len(choices)
        and "source_duplicate_choices" not in question.diagnostics
    ):
        reasons.append("duplicate_choice")
    if (
        _looks_like_promoted_propositions(choices)
        and "explicit_proposition_choices" not in question.diagnostics
    ):
        reasons.append("proposition_choices")
    if (
        "source_text_repair" not in question.diagnostics
        and any(_CONTAMINATION.search(choice) for choice in choices)
    ):
        reasons.append("contaminated_choice")
    if any(_QUESTION_TEXT_IN_CHOICE.search(choice) for choice in choices):
        reasons.append("question_text_in_choice")
    if any(_OUTER_DAMAGED_MARKER.search(choice) for choice in choices):
        reasons.append("damaged_marker_choice")
    lengths = [len(_normalized(choice)) for choice in choices]
    if (
        len(lengths) == 4
        and max(lengths[:3]) <= 15
        and lengths[3] >= 50
        and lengths[3] > 3 * max(1, *lengths[:3])
    ):
        reasons.append("choice_tail_contamination")
    if (
        len(lengths) == 4
        and lengths[0] <= 6
        and min(lengths[1:3]) >= 40
        and lengths[3] >= max(lengths[1:3]) + 40
    ):
        reasons.append("mixed_choice_layers")
    if (
        len(choices) == 4
        and len(re.findall(r"[㉠-㉭@]\s*[-:]", choices[-1])) >= 2
        and not any(
            re.search(r"[㉠-㉭@]\s*[-:]", choice)
            for choice in choices[:3]
        )
    ):
        reasons.append("mixed_choice_layers")
    if (
        len(choices) == 4
        and all(re.search(r"[㉠-㉭@]\s*-", choice) for choice in choices[:3])
        and not re.search(r"[㉠-㉭@]\s*-", choices[-1])
    ):
        reasons.append("mixed_choice_layers")
    if question.confidence < minimum_confidence:
        reasons.append("low_confidence")
    if any(
        diagnostic not in _NON_BLOCKING_DIAGNOSTICS
        for diagnostic in question.diagnostics
    ):
        reasons.append("parser_diagnostic")

    unique_reasons = tuple(dict.fromkeys(reasons))
    return QualityResult(importable=not unique_reasons, reason_codes=unique_reasons)


def _append_text_quality_reasons(reasons: list[str], text: str, location: str) -> None:
    if has_suspicious_text_artifact(text):
        reasons.append(f"suspicious_{location}")
    for code in text_quality_issue_codes(text):
        if code == "unbalanced_delimiter":
            reasons.append(f"unbalanced_{location}_delimiter")
        else:
            reasons.append(f"{code}_{location}")


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
