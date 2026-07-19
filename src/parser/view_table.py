"""Promote explicit Korean view blocks into editable one-cell tables."""

from __future__ import annotations

import re
from typing import Any, Optional

from .table_format import (
    normalize_table_spec,
    parse_format_payload,
    resolve_table_anchor,
    serialize_format_payload,
)


VIEW_MARKER_RE = re.compile(
    r"(?:<|＜|〈|《|\[|【)\s*보\s*기\s*(?:>|＞|〉|》|\]|】)"
)
RELAXED_VIEW_MARKER_RE = re.compile(
    r"(?<![A-Za-z가-힣])"
    r"(?:(?P<open><|＜|〈|《|\[|【)\s*)?"
    r"보(?P<inner>\s*)기\s*"
    r"(?P<close>>|＞|〉|》|\]|】)?"
)
PROPOSITION_MARKER_RE = re.compile(r"[㉠-㉭]")
VIEW_REFERENCE_TAIL_RE = re.compile(
    r"^\s*(?:중|에서|의|는|은|상|와|과|를|을|에)"
    r"(?=\s|[「『\[('“\"A-Za-z가-힣]|$)"
)
QUESTION_TAIL_RE = re.compile(
    r"(?:"
    r"[?？]"
    r"|(?:것은|것인가|무엇인가|누구인가|몇\s*개\s*인가|"
    r"몇\s*명\s*인가|나열한\s*것은|고른\s*것은)\s*[279]?"
    r")\s*$"
)
VIEW_TABLE_SOURCE_KIND = "view_block_text"
CANONICAL_VIEW_MARKER = "<보기>"


def _next_view_table_id(payload: dict) -> str:
    used = {
        str(table.get("id") or "")
        for table in payload.get("tables") or []
        if isinstance(table, dict)
    }
    number = 1
    while f"view-table-{number}" in used:
        number += 1
    return f"view-table-{number}"


def _one_cell_spec(
    text: str,
    cell_text: str,
    offset: int,
    table_id: str,
    reason: str,
) -> dict:
    offset = min(len(text), max(0, int(offset)))
    value = str(cell_text or "")
    return normalize_table_spec(
        {
            "id": table_id,
            "rows": [[value]],
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "text": value,
                    "row_span": 1,
                    "col_span": 1,
                    "horizontal_alignment": "left",
                    "vertical_alignment": "center",
                }
            ],
            "anchor": {
                "offset": offset,
                "before_context": text[max(0, offset - 24):offset],
                "after_context": text[offset:offset + 24],
            },
            "source": {"kind": VIEW_TABLE_SOURCE_KIND},
            "confidence": {"score": 1.0, "reasons": [str(reason)]},
            "render_mode": "native",
        }
    )


def add_one_cell_table(
    text: str,
    format_json: Any,
    cell_text: str,
    offset: int,
    reason: str = "manual_editor",
) -> Optional[str]:
    """Append an editable one-cell table at a bounded text anchor."""
    owner_text = str(text or "")
    payload = parse_format_payload(format_json)
    table_id = _next_view_table_id(payload)
    tables = list(payload.get("tables") or [])
    tables.append(
        _one_cell_spec(
            owner_text,
            str(cell_text or ""),
            offset,
            table_id,
            reason,
        )
    )
    payload["tables"] = tables
    return serialize_format_payload(payload)


def _single_cell_text(table: dict) -> Optional[str]:
    rows = table.get("rows") or []
    if len(rows) != 1 or not isinstance(rows[0], list) or len(rows[0]) != 1:
        return None
    return str(rows[0][0] or "")


def _looks_like_question_tail(value: str) -> bool:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    return len(compact) >= 6 and QUESTION_TAIL_RE.search(compact) is not None


def _repair_question_tail(value: str) -> str:
    original = str(value or "").strip()
    return re.sub(
        r"((?:것은|것인가|무엇인가|누구인가|몇\s*개\s*인가|"
        r"몇\s*명\s*인가|나열한\s*것은|고른\s*것은))\s*[279]\s*$",
        r"\1?",
        original,
    )


def _join_view_reference(owner_text: str, prompt_tail: str) -> str:
    owner = str(owner_text or "").rstrip()
    if not VIEW_MARKER_RE.search(owner[-16:]):
        owner = f"{owner} {CANONICAL_VIEW_MARKER}".strip()
    attach = re.match(r"^(?:에서|의|는|은|와|과|를|을|에)(?=\s|[「『\[(A-Za-z가-힣]|$)", prompt_tail)
    separator = "" if attach else " "
    return f"{owner}{separator}{prompt_tail}".strip()


def _is_broken_marker(match: re.Match[str]) -> bool:
    return bool(
        match.group("open")
        or match.group("close")
        or match.group("inner")
    ) and VIEW_MARKER_RE.fullmatch(match.group(0).strip()) is None


def _marker_candidates(value: str) -> list[tuple[int, int, str, bool]]:
    candidates = [
        (match.start(), match.end(), match.group(0).strip(), False)
        for match in VIEW_MARKER_RE.finditer(value)
    ]
    balanced_ranges = [(start, end) for start, end, _text, _broken in candidates]
    for match in RELAXED_VIEW_MARKER_RE.finditer(value):
        if not _is_broken_marker(match):
            continue
        if any(match.start() < end and match.end() > start for start, end in balanced_ranges):
            continue
        before = value[:match.start()].rstrip()
        after = value[match.end():].lstrip()
        if not after or not _looks_like_question_tail(before):
            continue
        candidates.append((match.start(), match.end(), CANONICAL_VIEW_MARKER, True))
    return sorted(candidates, key=lambda item: (item[0], item[1]))


def _secondary_view_boundary(body: str) -> Optional[tuple[int, int]]:
    """Return the real view-header boundary hidden inside a promoted cell."""

    for match in RELAXED_VIEW_MARKER_RE.finditer(body):
        has_delimiter = bool(match.group("open") or match.group("close"))
        visibly_spaced = bool(match.group("inner"))
        if not has_delimiter and not visibly_spaced:
            continue
        before = body[:match.start()].rstrip()
        after = body[match.end():].lstrip()
        if before and after and (
            _looks_like_question_tail(before)
            or VIEW_REFERENCE_TAIL_RE.match(body) is not None
        ):
            return match.start(), match.end()

    for marker in PROPOSITION_MARKER_RE.finditer(body):
        before = body[:marker.start()].rstrip()
        if _looks_like_question_tail(before):
            return marker.start(), marker.start()

    for terminator in re.finditer(r"[?？]", body):
        if body[terminator.end():].strip():
            return terminator.end(), terminator.end()
    return None


def _replace_single_cell_text(table: dict, value: str, owner_text: str) -> dict:
    updated = dict(table)
    updated["rows"] = [[value]]
    cells = [
        dict(cell)
        for cell in (updated.get("cells") or [])
        if isinstance(cell, dict)
    ]
    target = next(
        (
            cell
            for cell in cells
            if int(cell.get("row", -1)) == 0 and int(cell.get("col", -1)) == 0
        ),
        None,
    )
    if target is None:
        target = {
            "row": 0,
            "col": 0,
            "row_span": 1,
            "col_span": 1,
            "horizontal_alignment": "left",
            "vertical_alignment": "center",
        }
        cells.append(target)
    target["text"] = value
    updated["cells"] = cells
    offset = len(owner_text)
    updated["anchor"] = {
        "offset": offset,
        "before_context": owner_text[max(0, offset - 24):offset],
        "after_context": "",
    }
    confidence = dict(updated.get("confidence") or {})
    reasons = [str(reason) for reason in confidence.get("reasons") or []]
    if "recovered_view_reference_boundary" not in reasons:
        reasons.append("recovered_view_reference_boundary")
    confidence["score"] = 1.0
    confidence["reasons"] = reasons
    updated["confidence"] = confidence
    return normalize_table_spec(updated)


def _repair_existing_view_boundary(
    text: str,
    payload: dict,
) -> tuple[str, dict, bool]:
    """Move a mistakenly promoted reference phrase back into the stem."""

    tables = list(payload.get("tables") or [])
    for index, table in enumerate(tables):
        if not isinstance(table, dict):
            continue
        if (table.get("source") or {}).get("kind") != VIEW_TABLE_SOURCE_KIND:
            continue
        cell_text = _single_cell_text(table)
        if cell_text is None:
            continue
        leading = VIEW_MARKER_RE.match(cell_text.strip())
        if leading is None:
            continue
        body = cell_text.strip()[leading.end():].strip()
        if VIEW_REFERENCE_TAIL_RE.match(body) is None:
            continue
        boundary = _secondary_view_boundary(body)
        if boundary is None:
            continue
        start, end = boundary
        prompt_tail = _repair_question_tail(body[:start])
        view_body = body[end:].strip()
        if not prompt_tail or not view_body:
            continue

        owner_text = _join_view_reference(text, prompt_tail)
        repaired_cell = f"{CANONICAL_VIEW_MARKER}\n{view_body}"
        tables[index] = _replace_single_cell_text(table, repaired_cell, owner_text)
        payload["tables"] = tables
        return owner_text, payload, True
    return text, payload, False


def has_misplaced_view_boundary(text: str, format_json: Any) -> bool:
    """Return whether a saved view table still contains part of the prompt."""

    payload = parse_format_payload(format_json)
    _text, _payload, changed = _repair_existing_view_boundary(
        str(text or ""),
        payload,
    )
    return changed


def promote_view_block(
    text: str,
    format_json: Any = None,
) -> tuple[str, Optional[str], bool]:
    """Move the real view block into a native one-cell table.

    OCR frequently leaves a reference marker intact (``다음 <보기> 중``)
    while dropping the closing bracket from the later block header.  Broken
    rows already saved by older versions are repaired before new promotion.
    """
    value = str(text or "")
    payload = parse_format_payload(format_json)
    value, payload, repaired = _repair_existing_view_boundary(value, payload)
    if repaired:
        return value, serialize_format_payload(payload), True

    if any(
        (table.get("source") or {}).get("kind") == VIEW_TABLE_SOURCE_KIND
        for table in payload.get("tables") or []
    ):
        return value, serialize_format_payload(payload), False

    candidates = _marker_candidates(value)
    if not candidates:
        return value, serialize_format_payload(payload), False
    start, end, marker_text, broken = candidates[-1]
    trailing = value[end:].strip()

    prefix = _repair_question_tail(value[:start])
    marker_text = CANONICAL_VIEW_MARKER if broken else marker_text
    cell_text = f"{marker_text}\n{trailing}" if trailing else marker_text
    encoded = add_one_cell_table(
        prefix,
        payload,
        cell_text,
        len(prefix),
        reason="recovered_broken_view_marker" if broken else "explicit_view_marker",
    )
    encoded_payload = parse_format_payload(encoded)
    prefix, encoded_payload, _repaired = _repair_existing_view_boundary(
        prefix,
        encoded_payload,
    )
    return prefix, serialize_format_payload(encoded_payload), True


def _table_plain_text(table: dict) -> str:
    rows = table.get("rows") or []
    return "\n".join(
        "\t".join(str(cell or "") for cell in row)
        for row in rows
        if isinstance(row, list)
    ).strip()


def _insert_block(text: str, offset: int, block: str) -> str:
    left = text[:offset].rstrip()
    right = text[offset:].lstrip()
    return "\n".join(part for part in (left, block.strip(), right) if part)


def remove_table_and_restore(
    text: str,
    format_json: Any,
    table_id: str,
) -> tuple[str, Optional[str], bool]:
    """Remove one table and restore its flattened text at the saved anchor."""
    value = str(text or "")
    payload = parse_format_payload(format_json)
    tables = list(payload.get("tables") or [])
    target = next(
        (table for table in tables if str(table.get("id")) == str(table_id)),
        None,
    )
    if target is None:
        return value, serialize_format_payload(payload), False

    offset, _recovered = resolve_table_anchor(value, target.get("anchor"))
    restored = _insert_block(value, offset, _table_plain_text(target))
    remaining = [table for table in tables if table is not target]
    if remaining:
        payload["tables"] = remaining
    else:
        payload.pop("tables", None)
    return restored, serialize_format_payload(payload), True
