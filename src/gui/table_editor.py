"""Interactive editor for one schema-v2 table specification."""

from __future__ import annotations

import copy
from typing import Callable

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from qfluentwidgets import PushButton

from ..parser.table_structure import (
    TableStructureError,
    delete_columns,
    delete_rows,
    insert_column,
    insert_row,
    merge_cells,
    normalize_rectangular_table,
    set_auto_width_mode,
    set_manual_column_widths,
    split_cell,
)


class TableEditorDialog(QDialog):
    """Edit cell text, shape, merges, and column widths for one table."""

    def __init__(self, table_spec, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"표 편집 · {(table_spec or {}).get('id', 'table')}")
        self.table_spec = normalize_rectangular_table(table_spec)
        self._rendering = False
        self._header_touched = False

        root = QVBoxLayout(self)
        toolbar = QGridLayout()
        definitions = [
            ("위에 행 추가", self.add_row_above),
            ("아래에 행 추가", self.add_row_below),
            ("왼쪽에 열 추가", self.add_column_left),
            ("오른쪽에 열 추가", self.add_column_right),
            ("선택 행 삭제", self.delete_selected_rows),
            ("선택 열 삭제", self.delete_selected_columns),
            ("셀 병합", self.merge_selected_cells),
            ("셀 분할", self.split_current_cell),
            ("폭 자동 맞춤", self.auto_fit_widths),
        ]
        self.structure_buttons = []
        for index, (label, callback) in enumerate(definitions):
            button = PushButton(label, self)
            button.clicked.connect(callback)
            toolbar.addWidget(button, index // 5, index % 5)
            self.structure_buttons.append(button)

        self.grid = QTableWidget(self)
        self.grid.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.grid.horizontalHeader().sectionResized.connect(self._on_header_resized)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root.addLayout(toolbar)
        root.addWidget(self.grid, 1)
        root.addWidget(buttons)
        self._render_table()
        self.resize(920, 520)

    def _on_header_resized(self, _logical_index, _old_size, _new_size):
        if not self._rendering:
            self._header_touched = True

    def _current_position(self) -> tuple[int, int]:
        row = self.grid.currentRow()
        col = self.grid.currentColumn()
        return (max(0, row), max(0, col))

    def _selected_indices(self):
        indexes = self.grid.selectedIndexes()
        if not indexes:
            row, col = self._current_position()
            return {(row, col)}
        return {(index.row(), index.column()) for index in indexes}

    def _sync_text_from_grid(self):
        table = normalize_rectangular_table(self.table_spec)
        for cell in table["cells"]:
            row = cell["row"]
            col = cell["col"]
            item = self.grid.item(row, col)
            if item is None:
                continue
            text = item.text()
            cell["text"] = text
            table["rows"][row][col] = text
        self.table_spec = normalize_rectangular_table(table)

    def _capture_header_widths(self):
        if not self._header_touched:
            return
        widths = [
            self.grid.columnWidth(column)
            for column in range(self.grid.columnCount())
        ]
        self.table_spec = set_manual_column_widths(self.table_spec, widths)

    def _sync_model_from_grid(self):
        self._sync_text_from_grid()
        self._capture_header_widths()

    def _render_table(self, current: tuple[int, int] | None = None):
        self.table_spec = normalize_rectangular_table(self.table_spec)
        rows = self.table_spec["rows"]
        column_count = len(rows[0])
        self._rendering = True
        try:
            self.grid.clearSpans()
            self.grid.clearContents()
            self.grid.setRowCount(len(rows))
            self.grid.setColumnCount(column_count)
            for cell in self.table_spec["cells"]:
                row = cell["row"]
                col = cell["col"]
                self.grid.setItem(row, col, QTableWidgetItem(cell.get("text", "")))
                row_span = int(cell.get("row_span", 1))
                col_span = int(cell.get("col_span", 1))
                if row_span > 1 or col_span > 1:
                    self.grid.setSpan(row, col, row_span, col_span)

            mode = self.table_spec.get("layout", {}).get("width_mode", "auto")
            widths = self.table_spec.get("column_widths") or []
            if mode in {"manual", "source"} and len(widths) == column_count:
                available = max(480, self.grid.viewport().width())
                for column, width in enumerate(widths):
                    self.grid.setColumnWidth(column, max(24, round(available * width)))
            else:
                self.grid.resizeColumnsToContents()

            if current is not None:
                row = min(max(0, current[0]), len(rows) - 1)
                col = min(max(0, current[1]), column_count - 1)
                self.grid.setCurrentCell(row, col)
        finally:
            self._rendering = False
            self._header_touched = False

    def _apply_structure(
        self,
        operation: Callable,
        *args,
        current: tuple[int, int] | None = None,
    ) -> bool:
        self._sync_model_from_grid()
        before = copy.deepcopy(self.table_spec)
        try:
            self.table_spec = operation(self.table_spec, *args)
        except TableStructureError as exc:
            self.table_spec = before
            QMessageBox.warning(self, "표 편집", str(exc))
            return False
        self._render_table(current=current)
        return True

    def add_row_above(self):
        row, col = self._current_position()
        self._apply_structure(insert_row, row, current=(row, col))

    def add_row_below(self):
        row, col = self._current_position()
        self._apply_structure(insert_row, row + 1, current=(row + 1, col))

    def add_column_left(self):
        row, col = self._current_position()
        self._apply_structure(insert_column, col, current=(row, col))

    def add_column_right(self):
        row, col = self._current_position()
        self._apply_structure(insert_column, col + 1, current=(row, col + 1))

    def delete_selected_rows(self):
        selected = self._selected_indices()
        rows = sorted({row for row, _col in selected})
        anchor_row = min(rows)
        _row, col = self._current_position()
        self._apply_structure(delete_rows, rows, current=(anchor_row, col))

    def delete_selected_columns(self):
        selected = self._selected_indices()
        columns = sorted({col for _row, col in selected})
        anchor_col = min(columns)
        row, _col = self._current_position()
        self._apply_structure(delete_columns, columns, current=(row, anchor_col))

    def _selection_rectangle(self) -> tuple[int, int, int, int]:
        selected = self._selected_indices()
        rows = [row for row, _col in selected]
        columns = [col for _row, col in selected]
        top, bottom = min(rows), max(rows)
        left, right = min(columns), max(columns)
        expected = {
            (row, col)
            for row in range(top, bottom + 1)
            for col in range(left, right + 1)
        }
        if selected != expected:
            raise TableStructureError(
                "non_rectangular_selection",
                "셀 병합은 연속된 직사각형 영역만 가능합니다.",
            )
        return top, left, bottom, right

    def merge_selected_cells(self):
        self._sync_model_from_grid()
        before = copy.deepcopy(self.table_spec)
        try:
            rectangle = self._selection_rectangle()
            self.table_spec = merge_cells(self.table_spec, *rectangle)
        except TableStructureError as exc:
            self.table_spec = before
            QMessageBox.warning(self, "표 편집", str(exc))
            return False
        self._render_table(current=(rectangle[0], rectangle[1]))
        return True

    def split_current_cell(self):
        row, col = self._current_position()
        return self._apply_structure(split_cell, row, col, current=(row, col))

    def auto_fit_widths(self):
        self._sync_text_from_grid()
        self.table_spec = set_auto_width_mode(self.table_spec)
        self._render_table(current=self._current_position())
        return True

    def result_table_spec(self):
        self._sync_model_from_grid()
        return copy.deepcopy(self.table_spec)
