"""Interactive editor for one schema-v2 table specification."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import (
    QEvent,
    QItemSelectionModel,
    QObject,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FlowLayout,
    FluentIcon as FIF,
    PushButton,
)

from ..exporter.table_layout import fallback_table_layout, resolve_table_layout
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


class HeaderResizeTracker(QObject):
    """Coalesce one mouse-driven header resize into one undo command."""

    def __init__(self, dialog: "TableEditorDialog"):
        super().__init__(dialog.grid.horizontalHeader())
        self.dialog = dialog

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            self.dialog._begin_header_resize()
        elif event.type() == QEvent.MouseButtonRelease:
            self.dialog._finish_header_resize()
        return super().eventFilter(watched, event)


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
        self._resize_active = False

        self._build_actions()
        self._build_command_bar()

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
        self.headerResizeTracker = HeaderResizeTracker(self)
        self.grid.horizontalHeader().viewport().installEventFilter(
            self.headerResizeTracker
        )

        self.statusLabel = QLabel("준비", self)
        self.statusLabel.setAccessibleName("표 편집 상태")
        self._build_source_panel()
        self._build_editor_splitter()
        self._build_view_row()
        self._build_dialog_buttons()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        root.addWidget(self.commandBar)
        root.addWidget(self.viewRowWidget)
        root.addWidget(self.editorSplitter, 1)
        root.addWidget(self.statusLabel)
        root.addWidget(self.buttonBox)

        self.session.changed.connect(self._render_session_snapshot)
        self._render_table(current=(0, 0))
        self._load_source_image()
        self._update_command_state()
        self._configure_geometry_and_focus()

    def _create_action(
        self,
        key: str,
        label: str,
        callback,
        *,
        icon=None,
        shortcut: str | None = None,
    ) -> QAction:
        action = QAction(icon.icon(), label, self) if icon else QAction(label, self)
        action.setToolTip(label)
        action.triggered.connect(
            lambda _checked=False, handler=callback: handler()
        )
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            self.addAction(action)
        self.actions[key] = action
        return action

    def _build_actions(self) -> None:
        self.actions = {}
        self._create_action(
            "undo",
            "실행 취소",
            self.session.undo_stack.undo,
            icon=FIF.RETURN,
            shortcut="Ctrl+Z",
        )
        self._create_action(
            "redo",
            "다시 실행",
            self.session.undo_stack.redo,
            icon=FIF.ROTATE,
            shortcut="Ctrl+Y",
        )
        redo_alternate = QAction(self)
        redo_alternate.setShortcut(QKeySequence("Ctrl+Shift+Z"))
        redo_alternate.triggered.connect(self.session.undo_stack.redo)
        self.addAction(redo_alternate)

        structure = [
            ("row_above", "위에 행 추가", self.add_row_above, FIF.ADD),
            ("row_below", "아래에 행 추가", self.add_row_below, FIF.ADD),
            ("column_left", "왼쪽에 열 추가", self.add_column_left, FIF.ADD),
            ("column_right", "오른쪽에 열 추가", self.add_column_right, FIF.ADD),
            ("delete_rows", "선택 행 삭제", self.delete_selected_rows, FIF.DELETE),
            (
                "delete_columns",
                "선택 열 삭제",
                self.delete_selected_columns,
                FIF.DELETE,
            ),
            ("merge", "셀 병합", self.merge_selected_cells, FIF.EDIT),
            ("split", "셀 분할", self.split_current_cell, FIF.EDIT),
            ("auto_width", "폭 자동 맞춤", self.auto_fit_widths, FIF.FIT_PAGE),
        ]
        for key, label, callback, icon in structure:
            self._create_action(key, label, callback, icon=icon)

        alignment = [
            ("align_left", "왼쪽 정렬", self.apply_horizontal_alignment, "left"),
            (
                "align_center",
                "가운데 정렬",
                self.apply_horizontal_alignment,
                "center",
            ),
            ("align_right", "오른쪽 정렬", self.apply_horizontal_alignment, "right"),
            ("align_top", "위쪽 정렬", self.apply_vertical_alignment, "top"),
            (
                "align_middle",
                "세로 가운데",
                self.apply_vertical_alignment,
                "center",
            ),
            ("align_bottom", "아래쪽 정렬", self.apply_vertical_alignment, "bottom"),
        ]
        for key, label, callback, value in alignment:
            self._create_action(
                key,
                label,
                lambda handler=callback, alignment=value: handler(alignment),
                icon=FIF.ALIGNMENT,
            )
        self._create_action(
            "toggle_source",
            "원본 비교",
            self._toggle_source_panel,
            icon=FIF.VIEW,
        )

        self.actions["undo"].setEnabled(False)
        self.actions["redo"].setEnabled(False)
        self.session.undo_stack.canUndoChanged.connect(
            self.actions["undo"].setEnabled
        )
        self.session.undo_stack.canRedoChanged.connect(
            self.actions["redo"].setEnabled
        )

    def _create_action_button(self, key: str, parent: QWidget) -> PushButton:
        action = self.actions[key]
        button = PushButton(action.icon(), action.text(), parent)
        button.setMinimumHeight(32)
        button.setToolTip(action.toolTip())
        button.setEnabled(action.isEnabled())
        button.clicked.connect(action.trigger)
        action.changed.connect(
            lambda target=button, source=action: (
                target.setEnabled(source.isEnabled()),
                target.setToolTip(source.toolTip()),
            )
        )
        return button

    def _create_command_group(
        self,
        title: str,
        keys: tuple[str, ...],
    ) -> QFrame:
        group = QFrame(self.commandBar)
        group.setObjectName("TableCommandGroup")
        row = QHBoxLayout(group)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(4)
        label = BodyLabel(title, group)
        label.setMinimumWidth(label.sizeHint().width())
        row.addWidget(label)
        for key in keys:
            button = self._create_action_button(key, group)
            self.actionButtons[key] = button
            row.addWidget(button)
        return group

    def _build_command_bar(self) -> None:
        self.commandBar = QWidget(self)
        self.commandBar.setObjectName("TableCommandBar")
        self.commandFlow = FlowLayout(self.commandBar, needAni=False)
        self.commandFlow.setContentsMargins(0, 0, 0, 0)
        self.commandFlow.setHorizontalSpacing(8)
        self.commandFlow.setVerticalSpacing(6)
        self.actionButtons = {}
        groups = (
            ("편집", ("undo", "redo")),
            (
                "행",
                (
                    "row_above",
                    "row_below",
                    "delete_rows",
                ),
            ),
            (
                "열",
                (
                    "column_left",
                    "column_right",
                    "delete_columns",
                ),
            ),
            ("셀", ("merge", "split")),
            ("가로", ("align_left", "align_center", "align_right")),
            ("세로", ("align_top", "align_middle", "align_bottom")),
            ("배치", ("auto_width", "toggle_source")),
        )
        for title, keys in groups:
            self.commandFlow.addWidget(self._create_command_group(title, keys))
        structure_order = (
            "row_above",
            "row_below",
            "column_left",
            "column_right",
            "delete_rows",
            "delete_columns",
            "merge",
            "split",
            "auto_width",
        )
        self.structure_buttons = [
            self.actionButtons[key]
            for key in structure_order
        ]

    def _build_view_row(self) -> None:
        self.viewRowWidget = QWidget(self)
        row = QHBoxLayout(self.viewRowWidget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(BodyLabel("표시", self.viewRowWidget))
        self.viewModeCombo = ComboBox(self.viewRowWidget)
        self.viewModeCombo.addItem("편집 맞춤", userData="fit")
        self.viewModeCombo.addItem("DOCX 실제 폭", userData="docx")
        self.zoomCombo = ComboBox(self.viewRowWidget)
        for label, value in (
            ("50%", 0.5),
            ("75%", 0.75),
            ("100%", 1.0),
            ("125%", 1.25),
            ("150%", 1.5),
            ("화면 맞춤", "fit"),
        ):
            self.zoomCombo.addItem(label, userData=value)
        self.zoomCombo.setCurrentIndex(self.zoomCombo.findData(1.0))
        self.viewModeCombo.currentIndexChanged.connect(self._apply_view_widths)
        self.zoomCombo.currentIndexChanged.connect(self._apply_view_widths)
        row.addWidget(self.viewModeCombo)
        row.addWidget(self.zoomCombo)
        row.addStretch(1)

    def _build_source_panel(self) -> None:
        self.sourcePanel = QWidget(self)
        self.sourcePanel.setAccessibleName("원본 표 이미지 비교 영역")
        layout = QVBoxLayout(self.sourcePanel)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)
        heading = QHBoxLayout()
        heading.addWidget(BodyLabel("원본 표", self.sourcePanel))
        heading.addStretch(1)
        self.sourceZoomCombo = ComboBox(self.sourcePanel)
        for label, value in (
            ("화면 맞춤", "fit"),
            ("50%", 0.5),
            ("100%", 1.0),
            ("150%", 1.5),
        ):
            self.sourceZoomCombo.addItem(label, userData=value)
        self.sourceZoomCombo.currentIndexChanged.connect(self._apply_source_zoom)
        heading.addWidget(self.sourceZoomCombo)
        layout.addLayout(heading)
        self.sourceScroll = QScrollArea(self.sourcePanel)
        self.sourceScroll.setWidgetResizable(False)
        self.sourceScroll.setAlignment(Qt.AlignCenter)
        self.sourceImageLabel = QLabel(self.sourceScroll)
        self.sourceImageLabel.setAlignment(Qt.AlignCenter)
        self.sourceScroll.setWidget(self.sourceImageLabel)
        layout.addWidget(self.sourceScroll, 1)
        self.sourcePanel.hide()

    def _build_editor_splitter(self) -> None:
        self.editorSplitter = QSplitter(Qt.Horizontal, self)
        self.editorCanvas = QWidget(self.editorSplitter)
        canvas_layout = QVBoxLayout(self.editorCanvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.gridScroll = QScrollArea(self.editorCanvas)
        self.gridScroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.gridScroll.setWidgetResizable(True)
        self.gridScroll.setWidget(self.grid)
        canvas_layout.addWidget(self.gridScroll)
        self.editorSplitter.addWidget(self.editorCanvas)
        self.editorSplitter.addWidget(self.sourcePanel)
        self.editorSplitter.setStretchFactor(0, 3)
        self.editorSplitter.setStretchFactor(1, 2)

    def _build_dialog_buttons(self) -> None:
        self.buttonBox = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        self.saveButton = self.buttonBox.button(QDialogButtonBox.Save)
        self.cancelButton = self.buttonBox.button(QDialogButtonBox.Cancel)
        self.saveButton.setText("저장")
        self.cancelButton.setText("취소")
        self.saveButton.setMinimumHeight(32)
        self.cancelButton.setMinimumHeight(32)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def _configure_geometry_and_focus(self) -> None:
        self.setMinimumSize(980, 640)
        screen = self.screen().availableGeometry().size()
        self.resize(min(1180, screen.width()), min(760, screen.height()))
        self.setTabOrder(self.commandBar, self.viewModeCombo)
        self.setTabOrder(self.viewModeCombo, self.zoomCombo)
        self.setTabOrder(self.zoomCombo, self.grid)
        self.setTabOrder(self.grid, self.sourcePanel)
        self.setTabOrder(self.sourcePanel, self.saveButton)
        self.setTabOrder(self.saveButton, self.cancelButton)

    def _on_header_resized(self, _logical_index, _old_size, _new_size):
        if not self._rendering:
            self._header_touched = True

    def _begin_header_resize(self) -> None:
        self._resize_active = True
        self._header_touched = False

    def _finish_header_resize(self) -> None:
        if not self._resize_active or not self._header_touched:
            self._resize_active = False
            return
        widths = [
            self.grid.columnWidth(column)
            for column in range(self.grid.columnCount())
        ]
        self._resize_active = False
        self._header_touched = False
        self.session.set_manual_widths(widths)

    def _resolved_layout(self):
        try:
            return resolve_table_layout(self.session.result())
        except Exception:
            return fallback_table_layout(self.session.result())

    def _apply_view_widths(self, *_args) -> None:
        if not hasattr(self, "viewModeCombo") or self.grid.columnCount() < 1:
            return
        layout = self._resolved_layout()
        ratios = list(layout.column_widths)
        actual_mode = self.viewModeCombo.currentData() == "docx"
        if actual_mode:
            zoom_data = self.zoomCombo.currentData()
            physical_pixels = (
                layout.total_width_mm * self.logicalDpiX() / 25.4
            )
            if zoom_data == "fit":
                viewport_width = max(1, self.gridScroll.viewport().width())
                zoom = min(1.0, max(0.1, viewport_width / physical_pixels))
            else:
                zoom = float(zoom_data or 1.0)
            total_pixels = round(physical_pixels * zoom)
            status = (
                f"DOCX {'1단' if layout.wide else '2단'} · "
                f"{int(layout.total_width_mm)}mm"
            )
        else:
            viewport_width = (
                self.gridScroll.viewport().width()
                if hasattr(self, "gridScroll")
                else self.grid.viewport().width()
            )
            total_pixels = max(480, viewport_width - 4)
            status = "편집 맞춤"

        self._rendering = True
        try:
            assigned = 0
            for column, ratio in enumerate(ratios):
                if column == len(ratios) - 1:
                    width = max(36, total_pixels - assigned)
                else:
                    width = max(36, round(total_pixels * ratio))
                self.grid.setColumnWidth(column, width)
                assigned += width
        finally:
            self._rendering = False

        self.gridScroll.setWidgetResizable(not actual_mode)
        self.gridScroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        if actual_mode:
            chrome = (
                self.grid.verticalHeader().width()
                + self.grid.frameWidth() * 2
                + 4
            )
            self.grid.resize(
                total_pixels + chrome,
                max(360, self.grid.sizeHint().height()),
            )
        self._set_status(status)

    def _load_source_image(self) -> None:
        source_path = str(
            (self.session.result().get("source") or {}).get("image_path")
            or ""
        )
        pixmap = QPixmap(source_path) if source_path else QPixmap()
        available = bool(
            source_path
            and Path(source_path).is_file()
            and not pixmap.isNull()
        )
        self.actions["toggle_source"].setEnabled(available)
        if not available:
            self.actions["toggle_source"].setToolTip(
                "저장된 원본 표 이미지가 없습니다."
            )
            self.sourcePanel.hide()
            return
        self.actions["toggle_source"].setToolTip("원본 표 이미지 비교")
        self._sourcePixmap = pixmap
        self._apply_source_zoom()
        if self._show_source_on_open:
            self.sourcePanel.show()
            QTimer.singleShot(0, self._apply_source_zoom)

    def _toggle_source_panel(self) -> None:
        if not self.actions["toggle_source"].isEnabled():
            return
        self.sourcePanel.setVisible(not self.sourcePanel.isVisible())
        if self.sourcePanel.isVisible():
            QTimer.singleShot(0, self._apply_source_zoom)

    def _apply_source_zoom(self, *_args) -> None:
        pixmap = getattr(self, "_sourcePixmap", QPixmap())
        if pixmap.isNull():
            return
        zoom = self.sourceZoomCombo.currentData()
        if zoom == "fit":
            available = self.sourceScroll.viewport().size()
            rendered = pixmap.scaled(
                max(1, available.width()),
                max(1, available.height()),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        else:
            factor = float(zoom or 1.0)
            rendered = pixmap.scaled(
                max(1, round(pixmap.width() * factor)),
                max(1, round(pixmap.height() * factor)),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        self.sourceImageLabel.setPixmap(rendered)
        self.sourceImageLabel.resize(rendered.size())

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
        if hasattr(self, "viewModeCombo"):
            self._apply_view_widths()

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
        table = self.session.result()
        merged = [
            cell
            for cell in table["cells"]
            if int(cell.get("row_span", 1)) > 1
            or int(cell.get("col_span", 1)) > 1
        ]
        current = self._cell_at_current_position()
        merge_conflict = any(
            any(
                int(cell["row"]) <= row
                < int(cell["row"]) + int(cell.get("row_span", 1))
                and int(cell["col"]) <= column
                < int(cell["col"]) + int(cell.get("col_span", 1))
                for row, column in selected
            )
            for cell in merged
        )
        can_merge = (
            self._is_rectangular_selection(selected)
            and len(selected) > 1
            and not merge_conflict
        )
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
        row_conflict = any(
            any(
                int(cell["row"]) <= row
                < int(cell["row"]) + int(cell.get("row_span", 1))
                for row in selected_rows
            )
            for cell in merged
        )
        column_conflict = any(
            any(
                int(cell["col"]) <= column
                < int(cell["col"]) + int(cell.get("col_span", 1))
                for column in selected_columns
            )
            for cell in merged
        )
        can_delete_rows = (
            len(selected_rows) < self.grid.rowCount()
            and not row_conflict
        )
        can_delete_columns = (
            len(selected_columns) < self.grid.columnCount()
            and not column_conflict
        )
        self.actions["delete_rows"].setEnabled(can_delete_rows)
        self.actions["delete_columns"].setEnabled(can_delete_columns)
        if self.grid.rowCount() == 1:
            row_tooltip = "표에는 최소 1개의 행이 필요합니다."
        elif row_conflict:
            row_tooltip = "병합 셀과 겹치는 행은 먼저 분할하세요."
        else:
            row_tooltip = "선택 행 삭제"
        if self.grid.columnCount() == 1:
            column_tooltip = "표에는 최소 1개의 열이 필요합니다."
        elif column_conflict:
            column_tooltip = "병합 셀과 겹치는 열은 먼저 분할하세요."
        else:
            column_tooltip = "선택 열 삭제"
        self.actions["delete_rows"].setToolTip(row_tooltip)
        self.actions["delete_columns"].setToolTip(column_tooltip)

        current_row, current_column = self._current_position()
        boundaries = {
            "row_above": ("row", "row_span", current_row),
            "row_below": ("row", "row_span", current_row + 1),
            "column_left": ("col", "col_span", current_column),
            "column_right": ("col", "col_span", current_column + 1),
        }
        for key, (axis, span_key, boundary) in boundaries.items():
            conflict = any(
                int(cell[axis])
                < boundary
                < int(cell[axis]) + int(cell.get(span_key, 1))
                for cell in merged
            )
            self.actions[key].setEnabled(not conflict)
            self.actions[key].setToolTip(
                "병합 셀 내부에는 행이나 열을 삽입할 수 없습니다."
                if conflict
                else self.actions[key].text()
            )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.statusLabel.setText(str(message))
        self.statusLabel.setProperty("error", bool(error))

    def result_table_spec(self):
        self._commit_pending_editor()
        self._capture_header_widths()
        return self.session.result()
