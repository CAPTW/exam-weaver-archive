"""Content-aware column widths for native DOCX tables."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from ..parser.table_structure import (
    normalize_column_widths,
    normalize_rectangular_table,
)


NARROW_TABLE_WIDTH_MM = 82.0
WIDE_TABLE_WIDTH_MM = 180.0
MIN_COLUMN_WIDTH_MM = 12.0
MAX_COLUMN_SHARE = 0.75
MM_PER_DISPLAY_UNIT = 1.6
MAX_NARROW_WRAP_LINES = 3
NARROW_CHARACTERS = frozenset(" \t.,:;!'\"|ilI")


@dataclass(frozen=True)
class TableLayout:
    column_widths: tuple[float, ...]
    column_widths_mm: tuple[float, ...]
    total_width_mm: float
    width_mode: str
    wide: bool
    estimated_max_lines: int
    fallback_used: bool = False


def _line_display_units(line: str) -> float:
    total = 0.0
    for character in str(line or ""):
        if character in NARROW_CHARACTERS:
            total += 0.5
        elif unicodedata.east_asian_width(character) in {"W", "F", "A"}:
            total += 2.0
        else:
            total += 1.0
    return total


def display_units(text: str) -> float:
    """Return the display units of the longest explicit line."""
    return max((_line_display_units(line) for line in str(text or "").splitlines()), default=0.0)


def _normalized_ratios(values: Iterable[float], count: int) -> list[float]:
    widths = normalize_column_widths(list(values), count)
    return widths or ([1.0 / count] * count)


def _column_scores(table: dict, column_count: int) -> list[float]:
    scores = [1.0] * column_count
    source_widths = normalize_column_widths(
        table.get("column_widths"),
        column_count,
    )
    for cell in table["cells"]:
        col = int(cell["col"])
        col_span = min(int(cell.get("col_span", 1)), column_count - col)
        need = max(1.0, display_units(cell.get("text", "")))
        if col_span == 1:
            scores[col] = max(scores[col], need)
            continue
        if source_widths:
            span_widths = source_widths[col:col + col_span]
            span_total = sum(span_widths)
            shares = [width / span_total for width in span_widths]
        else:
            shares = [1.0 / col_span] * col_span
        for offset, share in enumerate(shares):
            scores[col + offset] = max(scores[col + offset], need * share)
    return scores


def _cap_column_widths(widths: list[float], total_width_mm: float) -> list[float]:
    if len(widths) < 2:
        return widths
    cap = total_width_mm * MAX_COLUMN_SHARE
    capped = list(widths)
    for _iteration in range(len(widths)):
        oversized = [index for index, width in enumerate(capped) if width > cap + 1e-9]
        if not oversized:
            break
        for index in oversized:
            capped[index] = cap
        remaining = [index for index in range(len(capped)) if index not in oversized]
        if not remaining:
            break
        target = total_width_mm - sum(capped[index] for index in oversized)
        current = sum(capped[index] for index in remaining)
        if current <= 0:
            share = target / len(remaining)
            for index in remaining:
                capped[index] = share
        else:
            scale = target / current
            for index in remaining:
                capped[index] *= scale
    return capped


def _allocate_widths(ratios: list[float], total_width_mm: float) -> list[float]:
    count = len(ratios)
    ratios = _normalized_ratios(ratios, count)
    if count * MIN_COLUMN_WIDTH_MM > total_width_mm:
        return [total_width_mm / count] * count

    desired = [ratio * total_width_mm for ratio in ratios]
    remaining = total_width_mm - count * MIN_COLUMN_WIDTH_MM
    weights = [max(0.0, width - MIN_COLUMN_WIDTH_MM) for width in desired]
    weight_total = sum(weights)
    if weight_total <= 0:
        weights = ratios
        weight_total = sum(weights)
    widths = [
        MIN_COLUMN_WIDTH_MM + remaining * weight / weight_total
        for weight in weights
    ]
    widths = _cap_column_widths(widths, total_width_mm)
    correction = total_width_mm - sum(widths)
    widths[-1] += correction
    return widths


def _estimated_lines(table: dict, widths_mm: list[float]) -> int:
    maximum = 1
    for cell in table["cells"]:
        col = int(cell["col"])
        col_span = min(int(cell.get("col_span", 1)), len(widths_mm) - col)
        available = sum(widths_mm[col:col + col_span])
        if available <= 0:
            return MAX_NARROW_WRAP_LINES + 1
        lines = str(cell.get("text") or "").splitlines() or [""]
        wrapped = sum(
            max(1, math.ceil(_line_display_units(line) * MM_PER_DISPLAY_UNIT / available))
            for line in lines
        )
        maximum = max(maximum, wrapped)
    return maximum


def fallback_table_layout(table_spec) -> TableLayout:
    """Return a safe equal-width layout without inspecting cell contents."""
    rows = table_spec.get("rows") if isinstance(table_spec, dict) else None
    column_count = max(
        1,
        max(
            (
                len(row)
                for row in rows or []
                if isinstance(row, (list, tuple))
            ),
            default=1,
        ),
    )
    requested_wide = bool(
        isinstance(table_spec, dict)
        and isinstance(table_spec.get("layout"), dict)
        and table_spec["layout"].get("wide")
    )
    wide = requested_wide or column_count >= 5 or (
        column_count * MIN_COLUMN_WIDTH_MM > NARROW_TABLE_WIDTH_MM
    )
    total = WIDE_TABLE_WIDTH_MM if wide else NARROW_TABLE_WIDTH_MM
    widths_mm = [total / column_count] * column_count
    return TableLayout(
        column_widths=tuple(1.0 / column_count for _ in range(column_count)),
        column_widths_mm=tuple(widths_mm),
        total_width_mm=total,
        width_mode="auto",
        wide=wide,
        estimated_max_lines=1,
        fallback_used=True,
    )


def resolve_table_layout(table_spec: dict) -> TableLayout:
    """Resolve authoritative ratios, physical widths, and section width."""
    try:
        table = normalize_rectangular_table(table_spec)
        column_count = len(table["rows"][0])
        mode = table.get("layout", {}).get("width_mode", "auto")
        stored = normalize_column_widths(table.get("column_widths"), column_count)
        scores = _column_scores(table, column_count)
        if mode in {"manual", "source"} and stored:
            ratios = stored
        else:
            mode = "auto"
            ratios = _normalized_ratios(scores, column_count)

        narrow_widths = _allocate_widths(ratios, NARROW_TABLE_WIDTH_MM)
        narrow_lines = _estimated_lines(table, narrow_widths)
        wide = bool(table.get("layout", {}).get("wide")) or column_count >= 5
        wide = wide or column_count * MIN_COLUMN_WIDTH_MM > NARROW_TABLE_WIDTH_MM
        # A one-cell <보기> block is prose inside a border, so wrapping is the
        # expected layout.  Promoting it to a full-page table merely because it
        # wraps creates a 180 mm table inside the two-column exam flow.  Only
        # multi-column tables use wrap pressure as an automatic wide-layout
        # signal; an explicit ``layout.wide`` request still wins above.
        wide = wide or (
            column_count > 1
            and narrow_lines > MAX_NARROW_WRAP_LINES
        )
        total = WIDE_TABLE_WIDTH_MM if wide else NARROW_TABLE_WIDTH_MM
        widths_mm = _allocate_widths(ratios, total)
        final_lines = _estimated_lines(table, widths_mm)
        final_ratios = [width / total for width in widths_mm]
        return TableLayout(
            column_widths=tuple(final_ratios),
            column_widths_mm=tuple(widths_mm),
            total_width_mm=total,
            width_mode=mode,
            wide=wide,
            estimated_max_lines=final_lines,
        )
    except Exception:
        return fallback_table_layout(table_spec)
