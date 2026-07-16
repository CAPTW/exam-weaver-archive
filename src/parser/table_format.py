"""Versioned table formatting payloads shared by parsing, editing, and export."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Optional


SCHEMA_VERSION = 2
AUTO_RENDER_THRESHOLD = 0.90
TABLE_RENDER_MODES = {"auto", "image", "native"}
TABLE_WIDTH_MODES = {"auto", "source", "manual"}
COMPLEXITY_FLAGS = (
    "has_formula",
    "has_embedded_image",
    "has_rotated_text",
    "has_complex_merge",
    "has_duplicate_text_risk",
)


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _bounded_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(1.0, max(0.0, number))


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, number)


def _clean_rows(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    rows = []
    for row in value:
        if not isinstance(row, (list, tuple)):
            continue
        rows.append([str(cell or "") for cell in row])
    return rows


def _clean_numbers(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    numbers = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            numbers.append(number)
    return numbers


def _normalized_widths(value: Any, column_count: int) -> list[float]:
    numbers = _clean_numbers(value)
    if (
        column_count < 1
        or len(numbers) != column_count
        or any(number <= 0 for number in numbers)
    ):
        return []
    total = sum(numbers)
    if total <= 0:
        return []
    return [number / total for number in numbers]


def normalize_table_spec(table: Any, index: int = 0) -> dict:
    """Upgrade a legacy or partial table spec without discarding unknown fields."""
    normalized = _as_dict(table)
    normalized["id"] = str(normalized.get("id") or f"table-{index + 1}")
    normalized["rows"] = _clean_rows(normalized.get("rows"))

    cells = []
    for raw_cell in normalized.get("cells") or []:
        if not isinstance(raw_cell, dict):
            continue
        cell = copy.deepcopy(raw_cell)
        try:
            cell["row"] = int(cell.get("row", 0))
            cell["col"] = int(cell.get("col", 0))
        except (TypeError, ValueError):
            continue
        cell["text"] = str(cell.get("text") or "")
        cell["row_span"] = _positive_int(cell.get("row_span"))
        cell["col_span"] = _positive_int(cell.get("col_span"))
        cell["horizontal_alignment"] = str(
            cell.get("horizontal_alignment") or "left"
        )
        cell["vertical_alignment"] = str(
            cell.get("vertical_alignment") or "center"
        )
        cells.append(cell)
    normalized["cells"] = cells

    column_count = max((len(row) for row in normalized["rows"]), default=0)
    normalized["column_widths"] = _normalized_widths(
        normalized.get("column_widths"),
        column_count,
    )
    normalized["row_heights"] = _clean_numbers(normalized.get("row_heights"))
    normalized["borders"] = list(normalized.get("borders") or [])

    layout = _as_dict(normalized.get("layout"))
    width_mode = str(layout.get("width_mode") or "").lower()
    if width_mode not in TABLE_WIDTH_MODES:
        width_mode = "source" if normalized["column_widths"] else "auto"
    if width_mode in {"manual", "source"} and not normalized["column_widths"]:
        width_mode = "auto"
    layout["width_mode"] = width_mode
    layout["wide"] = bool(layout.get("wide", False))
    normalized["layout"] = layout

    anchor = _as_dict(normalized.get("anchor"))
    try:
        anchor["offset"] = int(anchor.get("offset", 0))
    except (TypeError, ValueError):
        anchor["offset"] = 0
    anchor["before_context"] = str(anchor.get("before_context") or "")
    anchor["after_context"] = str(anchor.get("after_context") or "")
    normalized["anchor"] = anchor

    source = _as_dict(normalized.get("source"))
    if "bbox" in source and isinstance(source["bbox"], (list, tuple)):
        source["bbox"] = list(source["bbox"][:4])
    normalized["source"] = source

    confidence = _as_dict(normalized.get("confidence"))
    confidence["score"] = _bounded_float(confidence.get("score"))
    confidence["reasons"] = [
        str(reason) for reason in confidence.get("reasons") or [] if str(reason)
    ]
    normalized["confidence"] = confidence

    complexity = _as_dict(normalized.get("complexity"))
    for flag in COMPLEXITY_FLAGS:
        complexity[flag] = bool(complexity.get(flag, False))
    normalized["complexity"] = complexity

    render_mode = str(normalized.get("render_mode") or "auto").lower()
    normalized["render_mode"] = (
        render_mode if render_mode in TABLE_RENDER_MODES else "auto"
    )
    normalized["recommended_render"] = _automatic_render_mode(normalized)
    return normalized


def parse_format_payload(value: Any) -> dict:
    """Return a schema-v2 payload from JSON, dict, legacy data, or invalid input."""
    payload = _as_dict(value)
    payload["schema_version"] = SCHEMA_VERSION
    raw_tables = payload.get("tables")
    if isinstance(raw_tables, list):
        tables = [
            normalize_table_spec(table, index)
            for index, table in enumerate(raw_tables)
            if isinstance(table, dict)
        ]
        if tables:
            payload["tables"] = tables
        else:
            payload.pop("tables", None)
    elif "tables" in payload:
        payload.pop("tables", None)
    if not isinstance(payload.get("spans"), list):
        payload.pop("spans", None)
    return payload


def serialize_format_payload(payload: dict) -> Optional[str]:
    normalized = parse_format_payload(payload)
    meaningful = {key: value for key, value in normalized.items() if key != "schema_version"}
    if not meaningful:
        return None
    return json.dumps(normalized, ensure_ascii=False)


def merge_format_spans(existing: Any, spans: list[dict]) -> Optional[str]:
    """Replace text spans while keeping tables and forward-compatible metadata."""
    payload = parse_format_payload(existing)
    if spans:
        payload["spans"] = copy.deepcopy(spans)
    else:
        payload.pop("spans", None)
    return serialize_format_payload(payload)


def resolve_table_anchor(text: str, anchor: Any) -> tuple[int, bool]:
    """Resolve a stored insertion anchor, recovering it from surrounding context."""
    text = str(text or "")
    anchor = _as_dict(anchor)
    try:
        offset = int(anchor.get("offset", 0))
    except (TypeError, ValueError):
        offset = -1
    before = str(anchor.get("before_context") or "")
    after = str(anchor.get("after_context") or "")
    if 0 <= offset <= len(text):
        context_matches = (
            (not before or text[:offset].endswith(before))
            and (not after or text[offset:].startswith(after))
        )
        if context_matches:
            return offset, False
    if before and after:
        before_start = text.find(before)
        if before_start >= 0:
            candidate = before_start + len(before)
            after_start = text.find(after, candidate)
            if after_start >= 0:
                return after_start, True
    if before:
        before_start = text.find(before)
        if before_start >= 0:
            return before_start + len(before), True
    if after:
        after_start = text.find(after)
        if after_start >= 0:
            return after_start, True
    return len(text), True


def _automatic_render_mode(table: dict) -> str:
    score = _bounded_float((table.get("confidence") or {}).get("score"))
    complexity = table.get("complexity") or {}
    has_complexity = any(bool(complexity.get(flag)) for flag in COMPLEXITY_FLAGS)
    has_structure = bool(table.get("rows") or table.get("cells"))
    if score >= AUTO_RENDER_THRESHOLD and has_structure and not has_complexity:
        return "native"
    return "image"


def effective_table_render_mode(table: dict, document_mode: str = "auto") -> str:
    """Resolve per-table override, document preference, then automatic policy."""
    table_mode = str((table or {}).get("render_mode") or "auto").lower()
    if table_mode in {"image", "native"}:
        return table_mode
    document_mode = str(document_mode or "auto").lower()
    if document_mode in {"image", "native"}:
        return document_mode
    return _automatic_render_mode(normalize_table_spec(table or {}))


def _source_path(source: dict, source_root: Optional[Path]) -> Optional[Path]:
    value = source.get("image_path")
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute() and source_root is not None:
        path = Path(source_root) / path
    return path


def validate_table_spec(
    table: dict,
    text: str = "",
    page_size: Optional[tuple[float, float]] = None,
    source_root: Optional[Path] = None,
) -> list[str]:
    """Return stable validation error codes for one normalized table."""
    table = normalize_table_spec(table)
    errors: list[str] = []
    source = table["source"]
    path = _source_path(source, source_root)
    if source.get("image_path"):
        if path is None or not path.is_file():
            errors.append("source_image_missing")
        elif source.get("sha256"):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest.lower() != str(source["sha256"]).lower():
                errors.append("source_hash_mismatch")

    bbox = source.get("bbox")
    if bbox is not None:
        valid_bbox = False
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                x0, y0, x1, y1 = (float(value) for value in bbox)
                valid_bbox = x0 >= 0 and y0 >= 0 and x1 > x0 and y1 > y0
                if page_size:
                    valid_bbox = valid_bbox and x1 <= page_size[0] and y1 <= page_size[1]
            except (TypeError, ValueError):
                valid_bbox = False
        if not valid_bbox:
            errors.append("bbox_out_of_page")

    rows = table["rows"]
    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    for cell in table["cells"]:
        if (
            cell["row"] < 0
            or cell["col"] < 0
            or cell["row"] + cell["row_span"] > row_count
            or cell["col"] + cell["col_span"] > column_count
        ):
            errors.append("cell_out_of_bounds")
            break

    anchor = table["anchor"]
    try:
        raw_offset = int(anchor.get("offset", 0))
    except (TypeError, ValueError):
        raw_offset = -1
    if text and not 0 <= raw_offset <= len(text):
        before = str(anchor.get("before_context") or "")
        after = str(anchor.get("after_context") or "")
        if not ((before and before in text) or (after and after in text)):
            errors.append("anchor_unresolved")

    score = table["confidence"]["score"]
    has_source = bool(path and path.is_file())
    if score < AUTO_RENDER_THRESHOLD and not has_source and not rows:
        errors.append("low_confidence_without_source")
    return errors
