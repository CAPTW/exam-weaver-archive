"""Interactive editor for one schema-v2 table specification."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QItemSelectionModel, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QStyledItemDelegate,
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
    split_cell,
)
from .table_edit_session import TableEditSession
from .table_preview import cell_qt_alignment


class CellTextEdit(QPlainTextEdit):
    """Multiline cell editor with explicit table navigation signals."""

    navigateRequested = pyqtSignal(int)
    cancelRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab and not event.modifiers() & Qt.ShiftModifier:
            self.navigateRequested.emit(1)
            return
        if event.key() == Qt.Key_Backtab or (
            event.key() == Qt.Key_Tab
            and event.modifiers() & Qt.ShiftModifier
        ):
            self.navigateRequested.emit(-1)
            return
        if event.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
            return
        super().keyPressEvent(event)


class MultilineTableDelegate(QStyledItemDelegate):
    """Commit a multiline cell once and optionally move logically."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_editor = None

    def createEditor(self, parent, _option, _index):
        editor = CellTextEdit(parent)
        self._active_editor = editor
        editor.setTabChangesFocus(False)
        editor.navigateRequested.connect(
            lambda direction, widget=editor: self._commit_and_navigate(
                widget,
                direction,
            )
        )
        editor.cancelRequested.connect(
            lambda widget=editor: self.closeEditor.emit(
                widget,
                self.RevertModelCache,
            )
        )
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(str(index.data(Qt.EditRole) or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.EditRole)

    def _commit_and_navigate(self, editor, direction: int) -> None:
        editor.setProperty("tableNavigationDirection", int(direction))
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, self.NoHint)

    def destroyEditor(self, editor, index):
        if self._active_editor is editor:
            self._active_editor = None
        super().destroyEditor(editor, index)

    def commit_active_editor(self) -> None:
        editor = self._active_editor
        if editor is None:
            return
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, self.NoHint)


class TableGrid(QTableWidget):
    """Table widget that distinguishes cell clearing from structure deletion."""

    deleteRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key_Delete
            and self.state() != QAbstractItemView.EditingState
        ):
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)


class TableEditorDialog(QDialog):
    """Edit cell text, shape, merges, alignment, and column widths."""

    def __init__(self, table_spec, parent=None, show_source=False):
        super().__init__(parent)
        self.setWindowTitle(f"표 편집 · {(table_spec or {}).get('id', 'table')}")
        self._show_source_on_open = bool(show_source)
        self.session = TableEditSession(table_spec)
        self.table_spec = self.session.result()
        self._rendering = False
        self._header_touched = False

        root = QVBoxLayout(self)
        toolbar = QGridLayout()
        self.actions = {}
        definitions = [
            ("row_above", "위에 행 추가", self.add_row_above),
            ("row_below", "아래에 행 추가", self.add_row_below),
            ("column_left", "왼쪽에 열 추가", self.add_column_left),
            ("column_right", "오른쪽에 열 추가", self.add_column_right),
            ("delete_rows", "선택 행 삭제", self.delete_selected_rows),
            ("delete_columns", "선택 열 삭제", self.delete_selected_columns),
            ("merge", "셀 병합", self.merge_selected_cells),
            ("split", "셀 분할", self.split_current_cell),
            ("auto_width", "폭 자동 맞춤", self.auto_fit_widths),
        ]
        self.structure_buttons = []
        for index, (key, label, callback) in enumerate(definitions):
            action = QAction(label, self)
            action.setToolTip(label)
            action.triggered.connect(
                lambda _checked=False, handler=callback: handler()
            )
            self.actions[key] = action
            button = PushButton(label, self)
            button.clicked.connect(action.trigger)
            toolbar.addWidget(button, index // 5, index % 5)
            self.structure_buttons.append(button)

        alignment_definitions = [
            ("align_left", "왼쪽 정렬", self.apply_horizontal_alignment, "left"),
            ("align_center", "가운데 정렬", self.apply_horizontal_alignment, "center"),
            ("align_right", "오른쪽 정렬", self.apply_horizontal_alignment, "right"),
            ("align_top", "위쪽 정렬", self.apply_vertical_alignment, "top"),
            ("align_middle", "세로 가운데", self.apply_vertical_alignment, "center"),
            ("align_bottom", "아래쪽 정렬", self.apply_vertical_alignment, "bottom"),
        ]
        for index, (key, label, callback, value) in enumerate(
            alignment_definitions,
            start=len(definitions),
        ):
            action = QAction(label, self)
            action.setToolTip(label)
            action.triggered.connect(
                lambda _checked=False, handler=callback, alignment=value:
                handler(alignment)
            )
            self.actions[key] = action
            button = PushButton(label, self)
            button.clicked.connect(action.trigger)
            toolbar.addWidget(button, index // 5, index % 5)

        self.actions["undo"] = QAction("실행 취소", self)
        self.actions["redo"] = QAction("다시 실행", self)
        self.actions["undo"].triggered.connect(self.session.undo_stack.undo)
        self.actions["redo"].triggered.connect(self.session.undo_stack.redo)
        self.session.undo_stack.canUndoChanged.connect(
            self.actions["undo"].setEnabled
        )
        self.session.undo_stack.canRedoChanged.connect(
            self.actions["redo"].setEnabled
        )
        self.actions["undo"].setEnabled(False)
        self.actions["redo"].setEnabled(False)

        self.grid = TableGrid(self)
        self.grid.setAccessibleName("표 셀 편집 영역")
        self.grid.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.grid.horizontalHeader().sectionResized.connect(
            self._on_header_resized
        )
        self.delegate = MultilineTableDelegate(self.grid)
        self.grid.setItemDelegate(self.delegate)
        self.grid.itemChanged.connect(self._on_item_changed)
        self.grid.itemSelectionChanged.connect(self._update_command_state)
        self.grid.currentCellChanged.connect(
            lambda *_args: self._update_command_state()
        )
        self.grid.deleteRequested.connect(self._clear_selected_cells)
        self.delegate.closeEditor.connect(self._after_editor_closed)

        self.statusLabel = QLabel("준비", self)
        self.statusLabel.setAccessibleName("표 편집 상태")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        root.addLayout(toolbar)
        root.addWidget(self.grid, 1)
        root.addWidget(self.statusLabel)
        root.addWidget(buttons)

        self.session.changed.connect(self._render_session_snapshot)
        self._render_table(current=(0, 0))
        self._update_command_state()
        self.resize(920, 520)

    def _on_header_resized(self, _logical_index, _old_size, _new_size):
        if not self._rendering:
            self._header_touched = True

    def _current_position(self) -> tuple[int, int]:
        row = self.grid.currentRow()
        column = self.grid.currentColumn()
        return max(0, row), max(0, column)

    def _selected_indices(self) -> set[tuple[int, int]]:
        indexes = self.grid.selectedIndexes()
        if not indexes:
            return {self._current_position()}
        return {(index.row(), index.column()) for index in indexes}

    def _capture_header_widths(self) -> None:
        if not self._header_touched:
            return
        widths = [
            self.grid.columnWidth(column)
            for column in range(self.grid.columnCount())
        ]
        self._header_touched = False
        self.session.set_manual_widths(widths)

    def _render_session_snapshot(self, table_spec: dict) -> None:
        current = self._current_position()
        selected = self._selected_indices()
        self.table_spec = normalize_rectangular_table(table_spec)
        self._render_table(current=current, selected=selected)
        self._update_command_state()

    def _render_table(
        self,
        current: tuple[int, int] | None = None,
        selected: set[tuple[int, int]] | None = None,
    ) -> None:
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
                row = int(cell["row"])
                column = int(cell["col"])
                text = str(cell.get("text") or "")
                item = QTableWidgetItem(text)
                item.setTextAlignment(int(cell_qt_alignment(cell)))
                item.setToolTip(text)
                self.grid.setItem(row, column, item)
                row_span = int(cell.get("row_span", 1))
                column_span = int(cell.get("col_span", 1))
                if row_span > 1 or column_span > 1:
                    self.grid.setSpan(
                        row,
                        column,
                        row_span,
                        column_span,
                    )

            mode = self.table_spec.get("layout", {}).get("width_mode", "auto")
            widths = self.table_spec.get("column_widths") or []
            if mode in {"manual", "source"} and len(widths) == column_count:
                available = max(480, self.grid.viewport().width())
                for column, width in enumerate(widths):
                    self.grid.setColumnWidth(
                        column,
                        max(24, round(available * float(width))),
                    )
            else:
                self.grid.resizeColumnsToContents()

            if current is not None:
                row = min(max(0, current[0]), len(rows) - 1)
                column = min(max(0, current[1]), column_count - 1)
                self.grid.setCurrentCell(row, column)
            if selected:
                selection_model = self.grid.selectionModel()
                for row, column in selected:
                    if 0 <= row < len(rows) and 0 <= column < column_count:
                        selection_model.select(
                            self.grid.model().index(row, column),
                            QItemSelectionModel.Select,
                        )
        finally:
            self._rendering = False
            self._header_touched = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._rendering:
            return
        self.session.replace_cell_text(item.row(), item.column(), item.text())

    def _after_editor_closed(self, editor, _hint) -> None:
        direction = int(editor.property("tableNavigationDirection") or 0)
        if direction:
            QTimer.singleShot(0, lambda: self._move_logical_cell(direction))

    def _move_logical_cell(self, direction: int) -> None:
        positions = sorted(
            (int(cell["row"]), int(cell["col"]))
            for cell in self.session.result()["cells"]
        )
        current = self._current_position()
        if current not in positions:
            return
        target_index = positions.index(current) + int(direction)
        if 0 <= target_index < len(positions):
            self.grid.setCurrentCell(*positions[target_index])

    def _commit_pending_editor(self) -> None:
        self.delegate.commit_active_editor()

    def _apply_structure(
        self,
        label: str,
        operation: Callable,
        *args,
        current: tuple[int, int] | None = None,
    ) -> bool:
        self._commit_pending_editor()
        try:
            changed = self.session.apply(
                label,
                lambda table: operation(table, *args),
            )
        except TableStructureError as exc:
            self._set_status(str(exc), error=True)
            return False
        if changed and current is not None:
            self.grid.setCurrentCell(*current)
        return changed

    def add_row_above(self):
        row, column = self._current_position()
        return self._apply_structure(
            "위에 행 삽입",
            insert_row,
            row,
            current=(row, column),
        )

    def add_row_below(self):
        row, column = self._current_position()
        return self._apply_structure(
            "아래에 행 삽입",
            insert_row,
            row + 1,
            current=(row + 1, column),
        )

    def add_column_left(self):
        row, column = self._current_position()
        return self._apply_structure(
            "왼쪽에 열 삽입",
            insert_column,
            column,
            current=(row, column),
        )

    def add_column_right(self):
        row, column = self._current_position()
        return self._apply_structure(
            "오른쪽에 열 삽입",
            insert_column,
            column + 1,
            current=(row, column + 1),
        )

    def delete_selected_rows(self):
        selected = self._selected_indices()
        rows = sorted({row for row, _column in selected})
        anchor_row = min(rows)
        _row, column = self._current_position()
        return self._apply_structure(
            "선택 행 삭제",
            delete_rows,
            rows,
            current=(anchor_row, column),
        )

    def delete_selected_columns(self):
        selected = self._selected_indices()
        columns = sorted({column for _row, column in selected})
        anchor_column = min(columns)
        row, _column = self._current_position()
        return self._apply_structure(
            "선택 열 삭제",
            delete_columns,
            columns,
            current=(row, anchor_column),
        )

    def _selection_rectangle(self) -> tuple[int, int, int, int]:
        selected = self._selected_indices()
        rows = [row for row, _column in selected]
        columns = [column for _row, column in selected]
        top, bottom = min(rows), max(rows)
        left, right = min(columns), max(columns)
        expected = {
            (row, column)
            for row in range(top, bottom + 1)
            for column in range(left, right + 1)
        }
        if selected != expected:
            raise TableStructureError(
                "non_rectangular_selection",
                "셀 병합은 연속된 직사각형 영역만 가능합니다.",
            )
        return top, left, bottom, right

    def merge_selected_cells(self):
        self._commit_pending_editor()
        try:
            rectangle = self._selection_rectangle()
            changed = self.session.apply(
                "셀 병합",
                lambda table: merge_cells(table, *rectangle),
            )
        except TableStructureError as exc:
            self._set_status(str(exc), error=True)
            return False
        if changed:
            self.grid.setCurrentCell(rectangle[0], rectangle[1])
        return changed

    def split_current_cell(self):
        row, column = self._current_position()
        return self._apply_structure(
            "셀 분할",
            split_cell,
            row,
            column,
            current=(row, column),
        )

    def auto_fit_widths(self):
        self._commit_pending_editor()
        return self.session.set_auto_widths()

    def apply_horizontal_alignment(self, alignment: str):
        self._commit_pending_editor()
        return self.session.align_cells(
            self._selected_indices(),
            horizontal=alignment,
        )

    def apply_vertical_alignment(self, alignment: str):
        self._commit_pending_editor()
        return self.session.align_cells(
            self._selected_indices(),
            vertical=alignment,
        )

    def _clear_selected_cells(self) -> None:
        self.session.clear_cells(self._selected_indices())

    def _cell_at_current_position(self) -> dict | None:
        row, column = self._current_position()
        return next(
            (
                cell
                for cell in self.session.result()["cells"]
                if int(cell["row"]) == row and int(cell["col"]) == column
            ),
            None,
        )

    @staticmethod
    def _is_rectangular_selection(selected: set[tuple[int, int]]) -> bool:
        if not selected:
            return False
        rows = [row for row, _column in selected]
        columns = [column for _row, column in selected]
        return selected == {
            (row, column)
            for row in range(min(rows), max(rows) + 1)
            for column in range(min(columns), max(columns) + 1)
        }

    def _update_command_state(self) -> None:
        if not self.actions or self.grid.rowCount() < 1:
            return
        selected = self._selected_indices()
        current = self._cell_at_current_position()
        can_merge = self._is_rectangular_selection(selected) and len(selected) > 1
        can_split = bool(
            current
            and (
                int(current.get("row_span", 1)) > 1
                or int(current.get("col_span", 1)) > 1
            )
        )
        self.actions["merge"].setEnabled(can_merge)
        self.actions["merge"].setToolTip(
            "셀 병합"
            if can_merge
            else "연속된 직사각형 셀을 두 개 이상 선택하세요."
        )
        self.actions["split"].setEnabled(can_split)
        self.actions["split"].setToolTip(
            "셀 분할"
            if can_split
            else "분할할 병합 셀의 시작 위치를 선택하세요."
        )

        selected_rows = {row for row, _column in selected}
        selected_columns = {column for _row, column in selected}
        can_delete_rows = len(selected_rows) < self.grid.rowCount()
        can_delete_columns = len(selected_columns) < self.grid.columnCount()
        self.actions["delete_rows"].setEnabled(can_delete_rows)
        self.actions["delete_columns"].setEnabled(can_delete_columns)
        self.actions["delete_rows"].setToolTip(
            "선택 행 삭제"
            if can_delete_rows
            else "표에는 최소 1개의 행이 필요합니다."
        )
        self.actions["delete_columns"].setToolTip(
            "선택 열 삭제"
            if can_delete_columns
            else "표에는 최소 1개의 열이 필요합니다."
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.statusLabel.setText(str(message))
        self.statusLabel.setProperty("error", bool(error))

    def result_table_spec(self):
        self._commit_pending_editor()
        self._capture_header_widths()
        return self.session.result()
