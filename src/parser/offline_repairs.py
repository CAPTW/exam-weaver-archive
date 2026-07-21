"""Source-traceable repairs for OCR text that cannot be recovered reliably.

Only values transcribed from the registered source PDF are accepted here.  The
repair key deliberately uses the source filename, PDF page and printed question
number so it is stable before a rebuilt database assigns row IDs.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from .aligned_choice_table import build_aligned_choice_payloads
from .offline_exam import ParsedOfflineQuestion
from .formatting import merge_spans, normalize_latex_text


RepairKey = tuple[str, int, int]
RepairRecord = Mapping[str, object]
RepairMap = Mapping[RepairKey, RepairRecord]

_DATA_PATH = Path(__file__).resolve().parent / "offline_source_repairs.json"
_CHOICE_DIAGNOSTICS = {
    "duplicate_choice_marker",
    "invalid_choice_count",
    "invalid_choice_sequence",
}


def _normalized_rich_text(value: str, format_json: str | None = None) -> tuple[str, str | None]:
    formatted = normalize_latex_text(str(value or ""))
    try:
        payload = json.loads(format_json) if format_json else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    spans = merge_spans(payload.get("spans") or [], formatted.spans)
    if spans:
        payload["spans"] = spans
    else:
        payload.pop("spans", None)
    return formatted.text, json.dumps(payload, ensure_ascii=False) if payload else None


@lru_cache(maxsize=1)
def load_audited_source_repairs() -> dict[RepairKey, RepairRecord]:
    """Load exact-source repairs bundled with the parser."""

    if not _DATA_PATH.is_file():
        return {}
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    records: dict[RepairKey, RepairRecord] = {}
    for item in payload.get("repairs", []):
        if not isinstance(item, Mapping) or item.get("confidence") != "exact_source":
            continue
        source_path = str(item.get("source_pdf_relative_path", "") or "")
        filename = Path(source_path.replace("\\", "/")).name.casefold()
        page = int(item.get("source_page", 0) or 0)
        number = int(item.get("question_number", 0) or 0)
        if not filename or page < 1 or number < 1:
            raise ValueError(f"invalid audited source repair key: {item!r}")
        key = (filename, page, number)
        if key in records:
            raise ValueError(f"duplicate audited source repair key: {key!r}")
        records[key] = item
    return records


def apply_audited_source_repair(
    candidate: ParsedOfflineQuestion,
    source_path: Path,
    *,
    repairs: RepairMap | None = None,
) -> ParsedOfflineQuestion:
    """Apply a source-confirmed stem/choice repair before quality validation."""

    available = repairs if repairs is not None else load_audited_source_repairs()
    key = (source_path.name.casefold(), candidate.source_page, candidate.number)
    repair = available.get(key)
    if repair is None or repair.get("confidence") != "exact_source":
        return candidate

    raw_stem = repair.get("repaired_stem")
    stem = str(raw_stem).strip() if raw_stem is not None else candidate.stem
    stem, question_format_json = _normalized_rich_text(
        stem,
        candidate.question_format_json if raw_stem is None else None,
    )
    raw_question_spans = repair.get("repaired_question_spans")
    if raw_question_spans is not None:
        if not isinstance(raw_question_spans, list):
            raise ValueError(f"invalid audited question spans for {key!r}")
        try:
            payload = json.loads(question_format_json) if question_format_json else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        verified_spans = []
        for raw_span in raw_question_spans:
            if not isinstance(raw_span, Mapping):
                raise ValueError(f"invalid audited question span for {key!r}")
            span = dict(raw_span)
            start = int(span.get("start", -1))
            end = int(span.get("end", -1))
            if not 0 <= start < end <= len(stem):
                raise ValueError(f"invalid audited question span range for {key!r}")
            if not span.get("underline") and not span.get("latex"):
                raise ValueError(f"unsupported audited question span for {key!r}")
            span["start"] = start
            span["end"] = end
            verified_spans.append(span)
        payload["spans"] = merge_spans(payload.get("spans") or [], verified_spans)
        question_format_json = json.dumps(payload, ensure_ascii=False)
    raw_choices = repair.get("repaired_choices")
    raw_choice_overrides = repair.get("repaired_choice_overrides")
    raw_choice_fields = repair.get("repaired_choice_fields")
    raw_question_image_path = repair.get("repaired_question_image_path")
    image_path = (
        str(raw_question_image_path).strip()
        if raw_question_image_path is not None
        else candidate.image_path
    )
    if raw_question_image_path is not None and not image_path:
        raise ValueError(f"invalid audited question image path for {key!r}")
    if sum(
        value is not None
        for value in (raw_choices, raw_choice_overrides, raw_choice_fields)
    ) > 1:
        raise ValueError(f"ambiguous audited choices for {key!r}")
    choices = candidate.choices
    choice_format_jsons = candidate.choice_format_jsons
    diagnostics = list(candidate.diagnostics)
    if raw_choice_fields is not None:
        choices, formats = build_aligned_choice_payloads(raw_choice_fields)
        choice_format_jsons = tuple(formats)
        diagnostics = [
            value for value in diagnostics if value not in _CHOICE_DIAGNOSTICS
        ]
        diagnostics.append("aligned_choice_table_recovery")
    elif raw_choices is not None:
        if not isinstance(raw_choices, list) or len(raw_choices) not in (4, 5):
            raise ValueError(f"invalid audited choices for {key!r}")
        normalized = [
            _normalized_rich_text(str(value).strip())
            for value in raw_choices
        ]
        choices = [value for value, _format in normalized]
        choice_format_jsons = tuple(format_json for _value, format_json in normalized)
        if any(not value for value in choices):
            raise ValueError(f"empty audited choice for {key!r}")
        diagnostics = [
            value for value in diagnostics if value not in _CHOICE_DIAGNOSTICS
        ]
        if len({re.sub(r"\s+", "", value).casefold() for value in choices}) != len(
            choices
        ):
            diagnostics.append("source_duplicate_choices")
        if all(re.match(r"^[㉠-㉭](?:\s|$)", value) for value in choices):
            diagnostics.append("explicit_proposition_choices")
    elif raw_choice_overrides is not None:
        if not isinstance(raw_choice_overrides, Mapping) or not raw_choice_overrides:
            raise ValueError(f"invalid audited choice overrides for {key!r}")
        choices = list(candidate.choices)
        choice_format_jsons = candidate.choice_format_jsons
        for raw_number, raw_value in raw_choice_overrides.items():
            number = int(raw_number)
            value = str(raw_value).strip()
            if number < 1 or not value:
                raise ValueError(f"invalid audited choice override for {key!r}")
            if number > len(choices):
                return replace(
                    candidate,
                    stem=stem,
                    confidence=1.0 if raw_stem is not None else candidate.confidence,
                    diagnostics=tuple(
                        dict.fromkeys(
                            (*candidate.diagnostics, "audited_choice_override_unapplied")
                        )
                    ),
                    question_format_json=question_format_json,
                    image_path=image_path,
                )
            normalized_value, normalized_format = _normalized_rich_text(value)
            choices[number - 1] = normalized_value
            formats = list(choice_format_jsons)
            while len(formats) < len(choices):
                formats.append(None)
            formats[number - 1] = normalized_format
            choice_format_jsons = tuple(formats)
        diagnostics = [
            value for value in diagnostics if value not in _CHOICE_DIAGNOSTICS
        ]
        if len({re.sub(r"\s+", "", value).casefold() for value in choices}) != len(
            choices
        ):
            diagnostics.append("source_duplicate_choices")

    diagnostics.append("source_text_repair")
    return replace(
        candidate,
        stem=stem,
        choices=list(choices),
        confidence=1.0,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        question_format_json=question_format_json,
        choice_format_jsons=tuple(choice_format_jsons),
        image_path=image_path,
    )
