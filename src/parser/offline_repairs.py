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

from .offline_exam import ParsedOfflineQuestion


RepairKey = tuple[str, int, int]
RepairRecord = Mapping[str, object]
RepairMap = Mapping[RepairKey, RepairRecord]

_DATA_PATH = Path(__file__).resolve().parent / "offline_source_repairs.json"
_CHOICE_DIAGNOSTICS = {
    "duplicate_choice_marker",
    "invalid_choice_count",
    "invalid_choice_sequence",
}


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
    raw_choices = repair.get("repaired_choices")
    raw_choice_overrides = repair.get("repaired_choice_overrides")
    if raw_choices is not None and raw_choice_overrides is not None:
        raise ValueError(f"ambiguous audited choices for {key!r}")
    choices = candidate.choices
    diagnostics = list(candidate.diagnostics)
    if raw_choices is not None:
        if not isinstance(raw_choices, list) or len(raw_choices) not in (4, 5):
            raise ValueError(f"invalid audited choices for {key!r}")
        choices = [str(value).strip() for value in raw_choices]
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
        for raw_number, raw_value in raw_choice_overrides.items():
            number = int(raw_number)
            value = str(raw_value).strip()
            if number < 1 or number > len(choices) or not value:
                raise ValueError(f"invalid audited choice override for {key!r}")
            choices[number - 1] = value
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
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )
