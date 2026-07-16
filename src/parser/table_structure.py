"""Pure structure operations for schema-v2 table payloads."""

from __future__ import annotations

import copy
import math
from typing import Any, Iterable

from .table_format import normalize_table_spec


class TableStructureError(ValueError):
    """A recoverable table editing error with a stable machine code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def normalize_column_widths(widths: Any, column_count: int) -> list[float]:
    """Return positive ratios that sum to one, or an empty list."""
    if not isinstance(widths, (list, tuple)) or len(widths) != column_count:
        return []
    numbers: list[float] = []
    for value in widths:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(number) or number <= 0:
            return []
        numbers.append(number)
    total = sum(numbers)
    if total <= 0:
        return []
    return [number / total for number in numbers]


def _positive_int(value: Any, default: int = 1) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _cell_defaults(row: int, col: int, text: str = "") -> dict:
    return {
        "row": row,
        "col": col,
        "text": str(text or ""),
        "row_span": 1,
        "col_span": 1,
        "horizontal_alignment": "left",
        "vertical_alignment": "center",
    }


def normalize_rectangular_table(table: Any) -> dict:
    """Repair one table into a rectangular, non-overlapping editable model."""
    result = copy.deepcopy(table) if isinstance(table, dict) else {}
    raw_cells = [
        copy.deepcopy(cell)
        for cell in result.get("cells") or []
        if isinstance(cell, dict)
    ]
    rows = [
        [str(value or "") for value in row]
        for row in result.get("rows") or []
        if isinstance(row, (list, tuple))
    ]

    inferred_rows = 0
    inferred_columns = 0
    for cell in raw_cells:
        try:
            row = int(cell.get("row", 0))
            col = int(cell.get("col", 0))
        except (TypeError, ValueError):
            continue
        if row < 0 or col < 0:
            continue
        inferred_rows = max(inferred_rows, row + _positive_int(cell.get("row_span")))
        inferred_columns = max(
            inferred_columns,
            col + _positive_int(cell.get("col_span")),
        )

    row_count = max(1, len(rows), inferred_rows)
    column_count = max(
        1,
        max((len(row) for row in rows), default=0),
        inferred_columns,
    )
    rows.extend([[] for _ in range(row_count - len(rows))])
    rows = [row + [""] * (column_count - len(row)) for row in rows]

    candidates = []
    for position, cell in enumerate(raw_cells):
        try:
            row = int(cell.get("row", 0))
            col = int(cell.get("col", 0))
        except (TypeError, ValueError):
            continue
        if not 0 <= row < row_count or not 0 <= col < column_count:
            continue
        row_span = min(_positive_int(cell.get("row_span")), row_count - row)
        col_span = min(_positive_int(cell.get("col_span")), column_count - col)
        candidates.append((row, col, position, row_span, col_span, cell))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))

    occupied: set[tuple[int, int]] = set()
    cells: list[dict] = []
    for row, col, _position, row_span, col_span, raw_cell in candidates:
        covered = {
            (covered_row, covered_col)
            for covered_row in range(row, row + row_span)
            for covered_col in range(col, col + col_span)
        }
        if covered & occupied:
            continue
        cell = copy.deepcopy(raw_cell)
        cell.update({
            "row": row,
            "col": col,
            "text": str(cell.get("text", rows[row][col]) or ""),
            "row_span": row_span,
            "col_span": col_span,
            "horizontal_alignment": str(
                cell.get("horizontal_alignment") or "left"
            ),
            "vertical_alignment": str(cell.get("vertical_alignment") or "center"),
        })
        rows[row][col] = cell["text"]
        for covered_row, covered_col in covered:
            if (covered_row, covered_col) != (row, col):
                rows[covered_row][covered_col] = ""
        occupied.update(covered)
        cells.append(cell)

    for row in range(row_count):
        for col in range(column_count):
            if (row, col) in occupied:
                continue
            cells.append(_cell_defaults(row, col, rows[row][col]))
            occupied.add((row, col))

    cells.sort(key=lambda cell: (cell["row"], cell["col"]))
    result["rows"] = rows
    result["cells"] = cells
    result["column_widths"] = normalize_column_widths(
        result.get("column_widths"),
        column_count,
    )
    normalized = normalize_table_spec(result)
    if (
        normalized["layout"]["width_mode"] in {"manual", "source"}
        and not normalized["column_widths"]
    ):
        normalized["layout"]["width_mode"] = "auto"
    return normalized


def _dimensions(table: dict) -> tuple[int, int]:
    rows = table["rows"]
    return len(rows), len(rows[0])


def _merged_cells(table: dict) -> list[dict]:
    return [
        cell
        for cell in table["cells"]
        if int(cell.get("row_span", 1)) > 1 or int(cell.get("col_span", 1)) > 1
    ]


def _raise_merge_conflict() -> None:
    raise TableStructureError(
        "merged_region_conflict",
        "병합된 셀과 겹칩니다. 해당 셀을 먼저 분할하세요.",
    )


def _validate_insert_index(index: Any, limit: int) -> int:
    try:
        value = int(index)
    except (TypeError, ValueError):
        value = -1
    if not 0 <= value <= limit:
        raise TableStructureError("invalid_selection", "표 범위를 벗어난 위치입니다.")
    return value


def _validated_indices(indices: Iterable[int], limit: int) -> list[int]:
    try:
        values = sorted({int(index) for index in indices})
    except (TypeError, ValueError):
        values = []
    if not values or values[0] < 0 or values[-1] >= limit:
        raise TableStructureError("invalid_selection", "삭제할 행 또는 열을 선택하세요.")
    return values


def insert_row(table: Any, index: int) -> dict:
    result = normalize_rectangular_table(table)
    row_count, column_count = _dimensions(result)
    index = _validate_insert_index(index, row_count)
    for cell in _merged_cells(result):
        start = cell["row"]
        if start < index < start + cell["row_span"]:
            _raise_merge_conflict()

    result["rows"].insert(index, [""] * column_count)
    for cell in result["cells"]:
        if cell["row"] >= index:
            cell["row"] += 1
    result["row_heights"] = []
    return normalize_rectangular_table(result)


def insert_column(table: Any, index: int) -> dict:
    result = normalize_rectangular_table(table)
    _row_count, column_count = _dimensions(result)
    index = _validate_insert_index(index, column_count)
    for cell in _merged_cells(result):
        start = cell["col"]
        if start < index < start + cell["col_span"]:
            _raise_merge_conflict()

    for row in result["rows"]:
        row.insert(index, "")
    for cell in result["cells"]:
        if cell["col"] >= index:
            cell["col"] += 1

    widths = normalize_column_widths(result.get("column_widths"), column_count)
    if widths:
        old_scale = column_count / (column_count + 1)
        widths = [width * old_scale for width in widths]
        widths.insert(index, 1 / (column_count + 1))
        result["column_widths"] = widths
    return normalize_rectangular_table(result)


def delete_rows(table: Any, indices: Iterable[int]) -> dict:
    result = normalize_rectangular_table(table)
    row_count, _column_count = _dimensions(result)
    indices = _validated_indices(indices, row_count)
    if len(indices) >= row_count:
        raise TableStructureError(
            "minimum_table_size",
            "표에는 최소 1개의 행과 1개의 열이 필요합니다.",
        )
    selected = set(indices)
    for cell in _merged_cells(result):
        if any(cell["row"] <= row < cell["row"] + cell["row_span"] for row in selected):
            _raise_merge_conflict()

    result["rows"] = [
        row for row_index, row in enumerate(result["rows"]) if row_index not in selected
    ]
    cells = []
    for cell in result["cells"]:
        if cell["row"] in selected:
            continue
        cell["row"] -= sum(index < cell["row"] for index in indices)
        cells.append(cell)
    result["cells"] = cells
    result["row_heights"] = []
    return normalize_rectangular_table(result)


def delete_columns(table: Any, indices: Iterable[int]) -> dict:
    result = normalize_rectangular_table(table)
    _row_count, column_count = _dimensions(result)
    indices = _validated_indices(indices, column_count)
    if len(indices) >= column_count:
        raise TableStructureError(
            "minimum_table_size",
            "표에는 최소 1개의 행과 1개의 열이 필요합니다.",
        )
    selected = set(indices)
    for cell in _merged_cells(result):
        if any(cell["col"] <= col < cell["col"] + cell["col_span"] for col in selected):
            _raise_merge_conflict()

    result["rows"] = [
        [value for col, value in enumerate(row) if col not in selected]
        for row in result["rows"]
    ]
    cells = []
    for cell in result["cells"]:
        if cell["col"] in selected:
            continue
        cell["col"] -= sum(index < cell["col"] for index in indices)
        cells.append(cell)
    result["cells"] = cells

    widths = normalize_column_widths(result.get("column_widths"), column_count)
    if widths:
        result["column_widths"] = normalize_column_widths(
            [width for col, width in enumerate(widths) if col not in selected],
            column_count - len(indices),
        )
    return normalize_rectangular_table(result)


def _rectangles_intersect(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> bool:
    first_top, first_left, first_bottom, first_right = first
    second_top, second_left, second_bottom, second_right = second
    return not (
        first_bottom < second_top
        or second_bottom < first_top
        or first_right < second_left
        or second_right < first_left
    )


def merge_cells(
    table: Any,
    top: int,
    left: int,
    bottom: int,
    right: int,
) -> dict:
    result = normalize_rectangular_table(table)
    row_count, column_count = _dimensions(result)
    try:
        top, bottom = sorted((int(top), int(bottom)))
        left, right = sorted((int(left), int(right)))
    except (TypeError, ValueError):
        raise TableStructureError("invalid_selection", "병합할 셀을 선택하세요.")
    if not (0 <= top <= bottom < row_count and 0 <= left <= right < column_count):
        raise TableStructureError("invalid_selection", "병합할 셀을 선택하세요.")
    if top == bottom and left == right:
        raise TableStructureError(
            "merge_requires_multiple_cells",
            "병합하려면 두 개 이상의 셀을 선택하세요.",
        )

    selection = (top, left, bottom, right)
    for cell in _merged_cells(result):
        rectangle = (
            cell["row"],
            cell["col"],
            cell["row"] + cell["row_span"] - 1,
            cell["col"] + cell["col_span"] - 1,
        )
        if _rectangles_intersect(selection, rectangle):
            _raise_merge_conflict()

    backup = [
        {"row": row, "col": col, "text": result["rows"][row][col]}
        for row in range(top, bottom + 1)
        for col in range(left, right + 1)
    ]
    combined = "\n".join(item["text"] for item in backup if item["text"])
    origin = next(
        cell
        for cell in result["cells"]
        if cell["row"] == top and cell["col"] == left
    )
    origin = copy.deepcopy(origin)
    origin.update({
        "text": combined,
        "row_span": bottom - top + 1,
        "col_span": right - left + 1,
        "merge_backup": backup,
    })
    result["cells"] = [
        cell
        for cell in result["cells"]
        if not (top <= cell["row"] <= bottom and left <= cell["col"] <= right)
    ]
    result["cells"].append(origin)
    for row in range(top, bottom + 1):
        for col in range(left, right + 1):
            result["rows"][row][col] = ""
    result["rows"][top][left] = combined
    return normalize_rectangular_table(result)


def split_cell(table: Any, row: int, col: int) -> dict:
    result = normalize_rectangular_table(table)
    try:
        row = int(row)
        col = int(col)
    except (TypeError, ValueError):
        row = col = -1
    origin = next(
        (
            cell
            for cell in result["cells"]
            if cell["row"] == row and cell["col"] == col
        ),
        None,
    )
    if origin is None or (
        origin.get("row_span", 1) == 1 and origin.get("col_span", 1) == 1
    ):
        raise TableStructureError(
            "split_requires_merged_origin",
            "분할할 병합 셀의 시작 위치를 선택하세요.",
        )

    row_span = int(origin["row_span"])
    col_span = int(origin["col_span"])
    backup = {
        (int(item["row"]), int(item["col"])): str(item.get("text") or "")
        for item in origin.get("merge_backup") or []
        if isinstance(item, dict) and "row" in item and "col" in item
    }
    result["cells"] = [cell for cell in result["cells"] if cell is not origin]
    for target_row in range(row, row + row_span):
        for target_col in range(col, col + col_span):
            if backup:
                text = backup.get((target_row, target_col), "")
            elif (target_row, target_col) == (row, col):
                text = str(origin.get("text") or "")
            else:
                text = ""
            result["rows"][target_row][target_col] = text
            cell = _cell_defaults(target_row, target_col, text)
            if (target_row, target_col) == (row, col):
                cell["horizontal_alignment"] = origin.get(
                    "horizontal_alignment", "left"
                )
                cell["vertical_alignment"] = origin.get(
                    "vertical_alignment", "center"
                )
            result["cells"].append(cell)
    return normalize_rectangular_table(result)


def set_manual_column_widths(table: Any, pixel_widths: Any) -> dict:
    result = normalize_rectangular_table(table)
    _row_count, column_count = _dimensions(result)
    widths = normalize_column_widths(pixel_widths, column_count)
    if not widths:
        raise TableStructureError(
            "invalid_column_widths",
            "모든 열의 너비는 0보다 커야 합니다.",
        )
    result["column_widths"] = widths
    result.setdefault("layout", {})["width_mode"] = "manual"
    return normalize_rectangular_table(result)


def set_auto_width_mode(table: Any) -> dict:
    result = normalize_rectangular_table(table)
    result.setdefault("layout", {})["width_mode"] = "auto"
    return normalize_rectangular_table(result)
