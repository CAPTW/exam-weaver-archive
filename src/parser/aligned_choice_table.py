"""Structured preservation for answer choices laid out as labeled columns."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .table_format import parse_format_payload, serialize_format_payload
from .table_structure import normalize_rectangular_table


ALIGNED_CHOICE_SOURCE_KIND = "aligned_choice_fields"


def normalize_aligned_choice_fields(value: Any) -> tuple[list[str], list[list[str]]]:
    """Validate and normalize an audited ``(가)/(나)/(다)`` choice matrix."""

    if not isinstance(value, dict):
        raise ValueError("aligned choice fields must be an object")
    raw_headers = value.get("headers")
    raw_rows = value.get("rows")
    if not isinstance(raw_headers, list) or not 2 <= len(raw_headers) <= 4:
        raise ValueError("aligned choice fields require two to four headers")
    headers = [str(item or "").strip() for item in raw_headers]
    expected = [f"({letter})" for letter in "가나다라"[: len(headers)]]
    if headers != expected:
        raise ValueError(f"invalid aligned choice headers: {headers!r}")
    if not isinstance(raw_rows, list) or len(raw_rows) not in (4, 5):
        raise ValueError("aligned choice fields require four or five rows")
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, (list, tuple)) or len(raw_row) != len(headers):
            raise ValueError("aligned choice row width does not match headers")
        row = [str(item or "").strip() for item in raw_row]
        if any(not item for item in row):
            raise ValueError("aligned choice cells cannot be empty")
        rows.append(row)
    return headers, rows


def canonical_aligned_choice_text(
    headers: Sequence[str], values: Sequence[str]
) -> str:
    """Return searchable plain text without losing the field-to-label mapping."""

    if len(headers) != len(values):
        raise ValueError("aligned choice value width does not match headers")
    return " / ".join(
        f"{str(header).strip()} {str(value).strip()}"
        for header, value in zip(headers, values)
    )


def build_aligned_choice_format(
    headers: Sequence[str],
    values: Sequence[str],
    choice_number: int,
) -> str:
    """Build one editable two-row table for a single logical choice."""

    headers, rows = normalize_aligned_choice_fields(
        {"headers": list(headers), "rows": [list(values)] * 4}
    )
    values = rows[0]
    cells = []
    for row_index, row in enumerate((headers, values)):
        for column_index, text in enumerate(row):
            cells.append(
                {
                    "row": row_index,
                    "col": column_index,
                    "text": text,
                    "row_span": 1,
                    "col_span": 1,
                    "horizontal_alignment": "center",
                    "vertical_alignment": "center",
                }
            )
    table = normalize_rectangular_table(
        {
            "id": f"aligned-choice-{int(choice_number)}",
            "rows": [headers, values],
            "cells": cells,
            "column_widths": [1 / len(headers)] * len(headers),
            "layout": {"width_mode": "manual", "wide": False},
            "anchor": {"offset": 0, "before_context": "", "after_context": ""},
            "source": {
                "kind": ALIGNED_CHOICE_SOURCE_KIND,
                "headers": headers,
            },
            "confidence": {
                "score": 1.0,
                "reasons": ["aligned_choice_columns"],
            },
            "render_mode": "native",
        }
    )
    encoded = serialize_format_payload(
        {"schema_version": 2, "tables": [table]}
    )
    if encoded is None:  # pragma: no cover - normalized table is always meaningful
        raise ValueError("failed to encode aligned choice table")
    return encoded


def build_aligned_choice_payloads(value: Any) -> tuple[list[str], list[str]]:
    """Return canonical texts and editable table payloads for audited fields."""

    headers, rows = normalize_aligned_choice_fields(value)
    texts = [canonical_aligned_choice_text(headers, row) for row in rows]
    formats = [
        build_aligned_choice_format(headers, row, number)
        for number, row in enumerate(rows, start=1)
    ]
    return texts, formats


def aligned_choice_fields(format_json: Any) -> tuple[list[str], list[str]] | None:
    """Read one aligned choice row from a stored format payload."""

    payload = parse_format_payload(format_json)
    tables = payload.get("tables") or []
    if len(tables) != 1:
        return None
    table = tables[0]
    if (table.get("source") or {}).get("kind") != ALIGNED_CHOICE_SOURCE_KIND:
        return None
    rows = table.get("rows") or []
    if len(rows) != 2 or not rows[0] or len(rows[0]) != len(rows[1]):
        return None
    headers = [str(item or "").strip() for item in rows[0]]
    values = [str(item or "").strip() for item in rows[1]]
    try:
        normalize_aligned_choice_fields(
            {"headers": headers, "rows": [values] * 4}
        )
    except ValueError:
        return None
    return headers, values


def is_aligned_choice_format(format_json: Any) -> bool:
    return aligned_choice_fields(format_json) is not None
