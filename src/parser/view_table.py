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
VIEW_TABLE_SOURCE_KIND = "view_block_text"


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


def promote_view_block(
    text: str,
    format_json: Any = None,
) -> tuple[str, Optional[str], bool]:
    """Move the last explicit view block into a native one-cell table."""
    value = str(text or "")
    payload = parse_format_payload(format_json)
    if any(
        (table.get("source") or {}).get("kind") == VIEW_TABLE_SOURCE_KIND
        for table in payload.get("tables") or []
    ):
        return value, serialize_format_payload(payload), False

    matches = list(VIEW_MARKER_RE.finditer(value))
    if not matches:
        return value, serialize_format_payload(payload), False
    marker = matches[-1]
    trailing = value[marker.end():].strip()

    prefix = value[:marker.start()].rstrip()
    marker_text = marker.group(0).strip()
    cell_text = f"{marker_text}\n{trailing}" if trailing else marker_text
    encoded = add_one_cell_table(
        prefix,
        payload,
        cell_text,
        len(prefix),
        reason="explicit_view_marker",
    )
    return prefix, encoded, True


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
