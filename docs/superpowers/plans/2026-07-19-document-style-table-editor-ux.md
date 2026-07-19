# Document-Style Table Editor UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace flat table summaries in the question editor with read-only visual table previews and provide a large, keyboard-friendly table editor with multiline cells, structure commands, alignment, undo/redo, DOCX-width preview, and source-image comparison.

**Architecture:** Keep schema-v2 table payloads and repository persistence unchanged. Add a focused preview module for rendering and card actions, a snapshot-based edit session around `QUndoStack`, and extend the existing `TableEditorDialog` to coordinate the grid, commands, view modes, and optional source panel. `QuestionEditor` remains responsible only for locating table payloads and applying accepted replacements.

**Tech Stack:** Python 3, PyQt5, PyQt-Fluent-Widgets, python-docx, pytest, existing `src.parser.table_structure` and `src.exporter.table_layout` modules.

## Global Constraints

- Do not change the SQLite schema or migrate `question_format_json` / `choice_format_json`.
- Preserve every unknown table metadata field, including `anchor`, `source`, `confidence`, and custom extension keys.
- Keep table previews read-only; editing starts only from double-click or `표 편집`.
- Support plain multiline text plus horizontal and vertical cell alignment; rich-text formatting is out of scope.
- Record every data-changing editor operation as a multi-level undo/redo command; view mode, zoom, and source-panel visibility are not undoable data changes.
- Use the existing 82 mm two-column and 180 mm one-column decisions from `src/exporter/table_layout.py` for `DOCX 실제 폭`.
- Preserve Mounted problem-bank write routing by returning the accepted table spec through `QuestionEditor._replace_table_spec()` and the existing final-save path.
- Keep primary actions visible at a 980×640 table-editor window and a 960×780 question-editor window on Windows display scales of 100%, 125%, and 150%.
- Do not add a new runtime dependency.

---

## File Structure

- Create `src/gui/table_preview.py`: read-only table renderer, metadata summary, and reusable `TablePreviewCard` action signals.
- Create `src/gui/table_edit_session.py`: normalized working copy, snapshot undo commands, text/alignment/structure/width mutations, dirty state.
- Modify `src/gui/table_editor.py`: multiline delegate, command bar, command-state rules, undo integration, edit-fit/DOCX-width modes, source comparison, status text.
- Modify `src/gui/interface/editor.py`: replace flat one-line cards with `TablePreviewCard`, remove the redundant structure modal, open the editor from card signals, refresh accepted results.
- Create `tests/test_table_preview.py`: preview rendering, spans, alignment, height, metadata, fallback, and card signals.
- Create `tests/test_table_edit_session.py`: snapshot commands, undo/redo, cancel isolation, alignment, structure, and width behavior.
- Modify `tests/test_table_editor_dialog.py`: multiline keyboard behavior, command enablement, status errors, width drag coalescing, view modes, source comparison, shortcuts, and minimum layout.
- Modify `tests/test_editor_table_format.py`: QuestionEditor card integration, edit acceptance/cancel behavior, metadata preservation, and source availability.
- Modify `tests/test_docx_exporter.py`: explicit horizontal/vertical alignment and manual-width regression coverage for an editor-produced spec.
- Modify `tests/test_validate_table_payloads.py`: normalize/serialize round-trip coverage for alignment, spans, and manual widths.
- Modify `tests/test_mounted_browser.py`: table-payload edits remain routed to the owning Mounted problem bank.

---

### Task 1: Read-only visual table preview and action card

**Files:**
- Create: `src/gui/table_preview.py`
- Create: `tests/test_table_preview.py`

**Interfaces:**
- Consumes: `normalize_rectangular_table(table_spec: Any) -> dict`, `resolve_table_layout(table_spec: dict) -> TableLayout`, `fallback_table_layout(table_spec: dict) -> TableLayout`.
- Produces: `TablePreviewMetadata`, `build_preview_metadata(owner: str, table_spec: dict) -> TablePreviewMetadata`, `ReadOnlyTablePreview.set_table_spec(table_spec: dict) -> None`, and `TablePreviewCard(owner: str, table_spec: dict, parent: QWidget | None = None)` with `editRequested(str, str)`, `sourceRequested(str, str)`, `deleteRequested(str, str)`, and `renderModeChanged(str, str, str)` signals.

- [ ] **Step 1: Write failing metadata and preview rendering tests**

```python
# tests/test_table_preview.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QAbstractItemView

from src.gui.table_preview import (
    ReadOnlyTablePreview,
    TablePreviewCard,
    build_preview_metadata,
)


APP = QApplication.instance() or QApplication([])


def _table():
    return {
        "id": "view-table-1",
        "rows": [["<보기>", "설명"], ["A", "B"]],
        "cells": [
            {
                "row": 0,
                "col": 0,
                "text": "<보기>",
                "row_span": 1,
                "col_span": 2,
                "horizontal_alignment": "center",
                "vertical_alignment": "top",
            },
            {"row": 1, "col": 0, "text": "A"},
            {"row": 1, "col": 1, "text": "B"},
        ],
        "layout": {"width_mode": "manual", "wide": False},
        "column_widths": [0.35, 0.65],
        "source": {"image_path": "missing-source.png"},
        "render_mode": "native",
    }


def test_metadata_reports_owner_shape_merge_width_and_docx_layout():
    metadata = build_preview_metadata("question", _table())

    assert metadata.owner_label == "발문"
    assert metadata.table_id == "view-table-1"
    assert metadata.dimensions == "2행 × 2열"
    assert metadata.merged_cells == 1
    assert metadata.width_label == "수동"
    assert metadata.docx_label == "DOCX 2단 · 82mm"


def test_preview_is_read_only_and_renders_spans_alignment_and_tooltip():
    preview = ReadOnlyTablePreview(_table())
    preview.show()
    APP.processEvents()

    item = preview.item(0, 0)
    assert preview.editTriggers() == QAbstractItemView.NoEditTriggers
    assert preview.selectionMode() == QAbstractItemView.NoSelection
    assert preview.rowSpan(0, 0) == 1
    assert preview.columnSpan(0, 0) == 2
    assert item.text() == "<보기>"
    assert item.toolTip() == "<보기>"
    assert item.textAlignment() & Qt.AlignHCenter
    assert item.textAlignment() & Qt.AlignTop
    assert preview.maximumHeight() == 180
    preview.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: Run the focused tests and confirm the module is missing**

Run: `python -m pytest tests/test_table_preview.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.gui.table_preview'`.

- [ ] **Step 3: Implement metadata and the read-only grid**

```python
# src/gui/table_preview.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton

from ..exporter.table_layout import fallback_table_layout, resolve_table_layout
from ..parser.table_structure import normalize_rectangular_table


WIDTH_LABELS = {"auto": "자동", "source": "원본", "manual": "수동"}


@dataclass(frozen=True)
class TablePreviewMetadata:
    owner_label: str
    table_id: str
    dimensions: str
    merged_cells: int
    width_label: str
    docx_label: str
    layout_fallback: bool


def _owner_label(owner: str) -> str:
    if owner == "question":
        return "발문"
    return f"{int(owner.split(':', 1)[1])}번 선지"


def build_preview_metadata(owner: str, table_spec: dict) -> TablePreviewMetadata:
    table = normalize_rectangular_table(table_spec)
    try:
        layout = resolve_table_layout(table)
    except Exception:
        layout = fallback_table_layout(table)
    rows = len(table["rows"])
    columns = len(table["rows"][0])
    merged = sum(
        int(cell.get("row_span", 1)) > 1 or int(cell.get("col_span", 1)) > 1
        for cell in table["cells"]
    )
    return TablePreviewMetadata(
        owner_label=_owner_label(owner),
        table_id=str(table.get("id") or "table"),
        dimensions=f"{rows}행 × {columns}열",
        merged_cells=merged,
        width_label=WIDTH_LABELS.get(layout.width_mode, "자동"),
        docx_label=(
            f"DOCX {'1단' if layout.wide else '2단'} · "
            f"{int(layout.total_width_mm)}mm"
        ),
        layout_fallback=bool(layout.fallback_used),
    )


def cell_qt_alignment(cell: dict) -> Qt.Alignment:
    horizontal = {
        "left": Qt.AlignLeft,
        "center": Qt.AlignHCenter,
        "right": Qt.AlignRight,
    }.get(str(cell.get("horizontal_alignment") or "left"), Qt.AlignLeft)
    vertical = {
        "top": Qt.AlignTop,
        "center": Qt.AlignVCenter,
        "bottom": Qt.AlignBottom,
    }.get(str(cell.get("vertical_alignment") or "center"), Qt.AlignVCenter)
    return horizontal | vertical


class ReadOnlyTablePreview(QTableWidget):
    activated = pyqtSignal()

    def __init__(self, table_spec: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMaximumHeight(180)
        self.verticalHeader().hide()
        self.horizontalHeader().hide()
        self.setWordWrap(True)
        self.set_table_spec(table_spec)

    def set_table_spec(self, table_spec: dict) -> None:
        table = normalize_rectangular_table(table_spec)
        self.clear()
        self.clearSpans()
        self.setRowCount(len(table["rows"]))
        self.setColumnCount(len(table["rows"][0]))
        for cell in table["cells"]:
            row, column = int(cell["row"]), int(cell["col"])
            text = str(cell.get("text") or "")
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            item.setTextAlignment(int(cell_qt_alignment(cell)))
            self.setItem(row, column, item)
            row_span = int(cell.get("row_span", 1))
            column_span = int(cell.get("col_span", 1))
            if row_span > 1 or column_span > 1:
                self.setSpan(row, column, row_span, column_span)
        self.resizeRowsToContents()
        for row in range(self.rowCount()):
            self.setRowHeight(row, min(64, self.rowHeight(row)))

    def mouseDoubleClickEvent(self, event):
        self.activated.emit()
        event.accept()
```

- [ ] **Step 4: Run the preview tests and confirm metadata/grid behavior passes**

Run: `python -m pytest tests/test_table_preview.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Add card action and fallback tests**

```python
# append to tests/test_table_preview.py
def test_card_emits_edit_from_button_and_double_click_signal():
    card = TablePreviewCard("question", _table())
    emitted = []
    card.editRequested.connect(lambda owner, table_id: emitted.append((owner, table_id)))

    card.edit_button.click()
    card.preview.activated.emit()

    assert emitted == [
        ("question", "view-table-1"),
        ("question", "view-table-1"),
    ]
    assert card.source_button.isEnabled() is False
    card.deleteLater()
    APP.processEvents()


def test_card_render_mode_signal_uses_owner_table_and_selected_mode():
    card = TablePreviewCard("choice:2", _table())
    emitted = []
    card.renderModeChanged.connect(
        lambda owner, table_id, mode: emitted.append((owner, table_id, mode))
    )

    card.mode_combo.setCurrentIndex(card.mode_combo.findData("image"))

    assert emitted[-1] == ("choice:2", "view-table-1", "image")
    card.deleteLater()
    APP.processEvents()
```

- [ ] **Step 6: Implement the complete card and preview fallback**

```python
# append to src/gui/table_preview.py
class TablePreviewCard(QFrame):
    editRequested = pyqtSignal(str, str)
    sourceRequested = pyqtSignal(str, str)
    deleteRequested = pyqtSignal(str, str)
    renderModeChanged = pyqtSignal(str, str, str)

    def __init__(self, owner: str, table_spec: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.owner = owner
        self.table_spec = normalize_rectangular_table(table_spec)
        self.table_id = str(self.table_spec.get("id") or "table")
        metadata = build_preview_metadata(owner, self.table_spec)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)
        summary = BodyLabel(
            " · ".join(
                (
                    metadata.owner_label,
                    metadata.table_id,
                    metadata.dimensions,
                    f"병합 {metadata.merged_cells}",
                    metadata.width_label,
                    metadata.docx_label,
                )
            ),
            self,
        )
        root.addWidget(summary)
        try:
            self.preview = ReadOnlyTablePreview(self.table_spec, self)
        except Exception:
            self.preview = QLabel(self._flat_summary(), self)
            self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.edit_button = PrimaryPushButton("표 편집", self)
        self.source_button = PushButton("원본 비교", self)
        self.mode_combo = ComboBox(self)
        self.delete_button = PushButton("표 삭제", self)
        for button in (self.edit_button, self.source_button, self.delete_button):
            button.setMinimumHeight(32)
        for label, value in (
            ("자동", "auto"),
            ("원본 이미지", "image"),
            ("편집 가능한 표", "native"),
        ):
            self.mode_combo.addItem(label, value)
        current_mode = str(self.table_spec.get("render_mode") or "auto")
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(current_mode)))
        source_path = str((self.table_spec.get("source") or {}).get("image_path") or "")
        source_available = bool(source_path and Path(source_path).is_file())
        self.source_button.setEnabled(source_available)
        if not source_available:
            self.source_button.setToolTip("저장된 원본 표 이미지가 없습니다.")

        self.edit_button.clicked.connect(self._emit_edit)
        if isinstance(self.preview, ReadOnlyTablePreview):
            self.preview.activated.connect(self._emit_edit)
        self.source_button.clicked.connect(
            lambda: self.sourceRequested.emit(self.owner, self.table_id)
        )
        self.delete_button.clicked.connect(
            lambda: self.deleteRequested.emit(self.owner, self.table_id)
        )
        self.mode_combo.currentIndexChanged.connect(
            lambda _index: self.renderModeChanged.emit(
                self.owner,
                self.table_id,
                str(self.mode_combo.currentData()),
            )
        )
        actions.addWidget(self.edit_button)
        actions.addWidget(self.source_button)
        actions.addStretch(1)
        actions.addWidget(self.mode_combo)
        actions.addWidget(self.delete_button)
        root.addLayout(actions)

    def _emit_edit(self) -> None:
        self.editRequested.emit(self.owner, self.table_id)

    def _flat_summary(self) -> str:
        return " / ".join(
            " | ".join(str(value or "") for value in row)
            for row in self.table_spec.get("rows") or []
        ) or "표 내용을 표시할 수 없습니다."
```

- [ ] **Step 7: Run the complete preview suite**

Run: `python -m pytest tests/test_table_preview.py -q`

Expected: `4 passed`.

- [ ] **Step 8: Commit the preview component**

```bash
git add src/gui/table_preview.py tests/test_table_preview.py
git commit -m "feat: add visual table preview cards"
```

---

### Task 2: Snapshot edit session with undo and redo

**Files:**
- Create: `src/gui/table_edit_session.py`
- Create: `tests/test_table_edit_session.py`

**Interfaces:**
- Consumes: `normalize_rectangular_table`, `insert_row`, `insert_column`, `delete_rows`, `delete_columns`, `merge_cells`, `split_cell`, `set_manual_column_widths`, and `set_auto_width_mode`.
- Produces: `TableEditSession(table_spec: dict)`, `TableEditSession.apply(label: str, operation: Callable[[dict], dict]) -> bool`, `replace_cell_text`, `clear_cells`, `align_cells`, `set_manual_widths`, `set_auto_widths`, `result`, `is_dirty`, and public `undo_stack: QUndoStack`.

- [ ] **Step 1: Write failing edit-session tests**

```python
# tests/test_table_edit_session.py
from src.gui.table_edit_session import TableEditSession
from src.parser.table_structure import insert_row, merge_cells


def _table():
    return {
        "id": "t1",
        "rows": [["A", "B"], ["C", "D"]],
        "source": {"sha256": "keep"},
    }


def test_text_edit_is_one_undoable_command_and_preserves_metadata():
    session = TableEditSession(_table())

    assert session.replace_cell_text(0, 0, "A\n수정") is True
    assert session.result()["rows"][0][0] == "A\n수정"
    assert session.result()["source"]["sha256"] == "keep"
    assert session.undo_stack.count() == 1

    session.undo_stack.undo()
    assert session.result()["rows"][0][0] == "A"
    session.undo_stack.redo()
    assert session.result()["rows"][0][0] == "A\n수정"


def test_structure_alignment_clear_and_width_actions_round_trip():
    session = TableEditSession(_table())
    session.apply("아래에 행 삽입", lambda table: insert_row(table, 2))
    session.align_cells({(0, 0), (0, 1)}, horizontal="center", vertical="top")
    session.clear_cells({(0, 1)})
    session.set_manual_widths([30, 70])

    result = session.result()
    assert len(result["rows"]) == 3
    assert result["rows"][0][1] == ""
    assert result["cells"][0]["horizontal_alignment"] == "center"
    assert result["cells"][0]["vertical_alignment"] == "top"
    assert result["column_widths"] == [0.3, 0.7]
    assert session.undo_stack.count() == 4

    for _index in range(4):
        session.undo_stack.undo()
    assert session.result()["rows"] == [["A", "B"], ["C", "D"]]


def test_cancel_isolation_keeps_input_object_unchanged():
    original = _table()
    session = TableEditSession(original)
    session.apply("셀 병합", lambda table: merge_cells(table, 0, 0, 0, 1))

    assert original["rows"] == [["A", "B"], ["C", "D"]]
    assert session.is_dirty() is True
```

- [ ] **Step 2: Run the focused tests and confirm the module is missing**

Run: `python -m pytest tests/test_table_edit_session.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.gui.table_edit_session'`.

- [ ] **Step 3: Implement the snapshot command and edit session**

```python
# src/gui/table_edit_session.py
from __future__ import annotations

import copy
from collections.abc import Callable, Iterable

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QUndoCommand, QUndoStack

from ..parser.table_structure import (
    normalize_rectangular_table,
    set_auto_width_mode,
    set_manual_column_widths,
)


Coordinate = tuple[int, int]


class SnapshotTableCommand(QUndoCommand):
    def __init__(
        self,
        session: "TableEditSession",
        label: str,
        before: dict,
        after: dict,
    ):
        super().__init__(label)
        self._session = session
        self._before = copy.deepcopy(before)
        self._after = copy.deepcopy(after)

    def undo(self) -> None:
        self._session._set_snapshot(self._before)

    def redo(self) -> None:
        self._session._set_snapshot(self._after)


class TableEditSession(QObject):
    changed = pyqtSignal(dict)

    def __init__(self, table_spec: dict):
        super().__init__()
        self._original = normalize_rectangular_table(copy.deepcopy(table_spec))
        self._working = copy.deepcopy(self._original)
        self.undo_stack = QUndoStack(self)

    def _set_snapshot(self, table_spec: dict) -> None:
        self._working = normalize_rectangular_table(copy.deepcopy(table_spec))
        self.changed.emit(self.result())

    def apply(self, label: str, operation: Callable[[dict], dict]) -> bool:
        before = self.result()
        after = normalize_rectangular_table(operation(copy.deepcopy(before)))
        if after == before:
            return False
        self.undo_stack.push(SnapshotTableCommand(self, label, before, after))
        return True

    def replace_cell_text(self, row: int, column: int, text: str) -> bool:
        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                if int(cell["row"]) == row and int(cell["col"]) == column:
                    cell["text"] = str(text or "")
                    table["rows"][row][column] = str(text or "")
                    break
            return table

        return self.apply("셀 내용 편집", operation)

    def clear_cells(self, coordinates: Iterable[Coordinate]) -> bool:
        targets = set(coordinates)

        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                coordinate = (int(cell["row"]), int(cell["col"]))
                if coordinate in targets:
                    cell["text"] = ""
                    table["rows"][coordinate[0]][coordinate[1]] = ""
            return table

        return self.apply("셀 내용 삭제", operation)

    def align_cells(
        self,
        coordinates: Iterable[Coordinate],
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> bool:
        targets = set(coordinates)

        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                coordinate = (int(cell["row"]), int(cell["col"]))
                if coordinate not in targets:
                    continue
                if horizontal is not None:
                    cell["horizontal_alignment"] = horizontal
                if vertical is not None:
                    cell["vertical_alignment"] = vertical
            return table

        label = "가로 정렬" if horizontal is not None else "세로 정렬"
        return self.apply(label, operation)

    def set_manual_widths(self, pixel_widths: list[int]) -> bool:
        return self.apply(
            "열 너비 조정",
            lambda table: set_manual_column_widths(table, pixel_widths),
        )

    def set_auto_widths(self) -> bool:
        return self.apply("폭 자동 맞춤", set_auto_width_mode)

    def result(self) -> dict:
        return copy.deepcopy(self._working)

    def is_dirty(self) -> bool:
        return self._working != self._original
```

- [ ] **Step 4: Run edit-session tests**

Run: `python -m pytest tests/test_table_edit_session.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Add no-op, merged-cell, and auto-width tests**

```python
# append to tests/test_table_edit_session.py
def test_no_op_does_not_add_undo_command():
    session = TableEditSession(_table())

    assert session.replace_cell_text(0, 0, "A") is False
    assert session.undo_stack.count() == 0


def test_alignment_targets_merged_origin_without_creating_covered_cells():
    session = TableEditSession(_table())
    session.apply("셀 병합", lambda table: merge_cells(table, 0, 0, 0, 1))

    session.align_cells({(0, 0)}, horizontal="right", vertical="bottom")
    merged = session.result()["cells"][0]

    assert merged["col_span"] == 2
    assert merged["horizontal_alignment"] == "right"
    assert merged["vertical_alignment"] == "bottom"


def test_auto_width_is_undoable():
    session = TableEditSession({
        "rows": [["A", "B"]],
        "column_widths": [0.25, 0.75],
        "layout": {"width_mode": "manual"},
    })

    session.set_auto_widths()
    assert session.result()["layout"]["width_mode"] == "auto"
    session.undo_stack.undo()
    assert session.result()["layout"]["width_mode"] == "manual"
```

- [ ] **Step 6: Run the complete edit-session suite**

Run: `python -m pytest tests/test_table_edit_session.py -q`

Expected: `6 passed`.

- [ ] **Step 7: Commit the edit session**

```bash
git add src/gui/table_edit_session.py tests/test_table_edit_session.py
git commit -m "feat: add undoable table edit sessions"
```

---

### Task 3: Multiline cell delegate and undo-aware editor core

**Files:**
- Modify: `src/gui/table_editor.py:1-254`
- Modify: `tests/test_table_editor_dialog.py`

**Interfaces:**
- Consumes: `TableEditSession`, its `changed` signal and mutation methods, plus existing structure operations from `src.parser.table_structure`.
- Produces: `CellTextEdit`, `MultilineTableDelegate`, `TableEditorDialog.session`, `TableEditorDialog.statusLabel`, `apply_horizontal_alignment`, `apply_vertical_alignment`, and command-state updates.

- [ ] **Step 1: Replace legacy toolbar assertions with failing interaction tests**

```python
# append imports in tests/test_table_editor_dialog.py
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest


def test_multiline_delegate_commits_once_and_undo_restores_previous_text():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.setCurrentCell(0, 0)
    dialog.grid.editItem(dialog.grid.item(0, 0))
    editor = dialog.grid.findChild(dialog.cell_editor_class)

    editor.selectAll()
    QTest.keyClicks(editor, "first")
    QTest.keyClick(editor, Qt.Key_Return)
    QTest.keyClicks(editor, "second")
    QTest.keyClick(editor, Qt.Key_Tab)
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["first\nsecond"]]
    assert dialog.session.undo_stack.count() == 1
    dialog.session.undo_stack.undo()
    assert dialog.result_table_spec()["rows"] == [["A"]]
    _close(dialog)


def test_escape_cancels_uncommitted_cell_text():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.editItem(dialog.grid.item(0, 0))
    editor = dialog.grid.findChild(dialog.cell_editor_class)
    editor.selectAll()
    QTest.keyClicks(editor, "discard")
    QTest.keyClick(editor, Qt.Key_Escape)
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["A"]]
    assert dialog.session.undo_stack.count() == 0
    _close(dialog)


def test_delete_clears_text_without_removing_rows_or_columns():
    dialog = _dialog({"rows": [["A", "B"], ["C", "D"]]})
    dialog.grid.setCurrentCell(0, 0)

    QTest.keyClick(dialog.grid, Qt.Key_Delete)

    assert dialog.result_table_spec()["rows"] == [["", "B"], ["C", "D"]]
    assert dialog.grid.rowCount() == 2
    assert dialog.grid.columnCount() == 2
    assert dialog.session.undo_stack.count() == 1
    _close(dialog)
```

- [ ] **Step 2: Run the interaction tests and confirm the legacy dialog fails them**

Run: `python -m pytest tests/test_table_editor_dialog.py -q`

Expected: FAIL because `cell_editor_class`, `session`, and multiline keyboard handling do not exist.

- [ ] **Step 3: Implement the multiline editor and delegate**

```python
# add to src/gui/table_editor.py
from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtWidgets import QPlainTextEdit, QStyledItemDelegate

from .table_edit_session import TableEditSession
from .table_preview import cell_qt_alignment


class CellTextEdit(QPlainTextEdit):
    navigateRequested = pyqtSignal(int)
    cancelRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Tab and not event.modifiers() & Qt.ShiftModifier:
            self.navigateRequested.emit(1)
            return
        if event.key() == Qt.Key_Backtab or (
            event.key() == Qt.Key_Tab and event.modifiers() & Qt.ShiftModifier
        ):
            self.navigateRequested.emit(-1)
            return
        if event.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
            return
        super().keyPressEvent(event)


class MultilineTableDelegate(QStyledItemDelegate):
    def createEditor(self, parent, _option, _index):
        editor = CellTextEdit(parent)
        self._active_editor = editor
        editor.setTabChangesFocus(False)
        editor.navigateRequested.connect(
            lambda direction, widget=editor: self._commit_and_navigate(widget, direction)
        )
        editor.cancelRequested.connect(
            lambda widget=editor: self.closeEditor.emit(widget, self.RevertModelCache)
        )
        return editor

    def setEditorData(self, editor, index):
        editor.setPlainText(str(index.data(Qt.EditRole) or ""))
        editor.selectAll()

    def setModelData(self, editor, model, index):
        model.setData(index, editor.toPlainText(), Qt.EditRole)

    def _commit_and_navigate(self, editor, direction: int):
        editor.setProperty("tableNavigationDirection", direction)
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, self.NoHint)

    def destroyEditor(self, editor, index):
        if getattr(self, "_active_editor", None) is editor:
            self._active_editor = None
        super().destroyEditor(editor, index)

    def commit_active_editor(self) -> None:
        editor = getattr(self, "_active_editor", None)
        if editor is not None:
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, self.NoHint)


class TableGrid(QTableWidget):
    deleteRequested = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.state() != QAbstractItemView.EditingState:
            self.deleteRequested.emit()
            return
        super().keyPressEvent(event)
```

- [ ] **Step 4: Refactor `TableEditorDialog` to render the session and record committed edits**

```python
# core changes inside TableEditorDialog.__init__ and render/commit methods
self.session = TableEditSession(table_spec)
self.table_spec = self.session.result()
self.cell_editor_class = CellTextEdit
self.grid = TableGrid(self)
self.delegate = MultilineTableDelegate(self.grid)
self.grid.setItemDelegate(self.delegate)
self.grid.itemChanged.connect(self._on_item_changed)
self.grid.itemSelectionChanged.connect(self._update_command_state)
self.grid.currentCellChanged.connect(lambda *_args: self._update_command_state())
self.grid.deleteRequested.connect(
    lambda: self.session.clear_cells(self._selected_indices())
)
self.delegate.closeEditor.connect(self._after_editor_closed)
self.session.changed.connect(self._render_session_snapshot)


def _render_session_snapshot(self, table_spec: dict) -> None:
    current = self._current_position()
    self.table_spec = table_spec
    self._render_table(current=current)
    self._update_command_state()


def _make_grid_item(self, cell: dict) -> QTableWidgetItem:
    item = QTableWidgetItem(str(cell.get("text") or ""))
    item.setTextAlignment(int(cell_qt_alignment(cell)))
    item.setToolTip(str(cell.get("text") or ""))
    return item


def _on_item_changed(self, item: QTableWidgetItem) -> None:
    if self._rendering:
        return
    self.session.replace_cell_text(item.row(), item.column(), item.text())


def _after_editor_closed(self, editor, _hint) -> None:
    direction = int(editor.property("tableNavigationDirection") or 0)
    if direction:
        self._move_logical_cell(direction)


def _move_logical_cell(self, direction: int) -> None:
    row, column = self._current_position()
    positions = [
        (cell["row"], cell["col"])
        for cell in self.session.result()["cells"]
    ]
    positions.sort()
    current_index = positions.index((row, column))
    target_index = current_index + direction
    if 0 <= target_index < len(positions):
        self.grid.setCurrentCell(*positions[target_index])
```

- [ ] **Step 5: Add alignment, command-state, and status tests**

```python
# append to tests/test_table_editor_dialog.py
def test_alignment_applies_to_selection_and_is_undoable():
    dialog = _dialog({"rows": [["A", "B"]]})
    selection = dialog.grid.selectionModel()
    for column in range(2):
        selection.select(
            dialog.grid.model().index(0, column),
            QItemSelectionModel.Select,
        )

    dialog.apply_horizontal_alignment("center")
    dialog.apply_vertical_alignment("top")

    cells = dialog.result_table_spec()["cells"]
    assert {cell["horizontal_alignment"] for cell in cells} == {"center"}
    assert {cell["vertical_alignment"] for cell in cells} == {"top"}
    assert dialog.session.undo_stack.count() == 2
    dialog.session.undo_stack.undo()
    assert {cell["vertical_alignment"] for cell in dialog.result_table_spec()["cells"]} == {"center"}
    _close(dialog)


def test_command_state_disables_invalid_merge_split_and_last_dimension_delete():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.setCurrentCell(0, 0)
    APP.processEvents()

    assert dialog.actions["merge"].isEnabled() is False
    assert dialog.actions["split"].isEnabled() is False
    assert dialog.actions["delete_rows"].isEnabled() is False
    assert dialog.actions["delete_columns"].isEnabled() is False
    assert "최소 1개" in dialog.actions["delete_rows"].toolTip()
    _close(dialog)


def test_structure_error_stays_in_status_and_does_not_open_modal():
    dialog = _dialog({
        "rows": [["AB", ""], ["C", "D"]],
        "cells": [
            {"row": 0, "col": 0, "text": "AB", "col_span": 2},
            {"row": 1, "col": 0, "text": "C"},
            {"row": 1, "col": 1, "text": "D"},
        ],
    })
    dialog.grid.setCurrentCell(0, 1)

    result = dialog.add_column_left()

    assert result is False
    assert "병합된 셀" in dialog.statusLabel.text()
    _close(dialog)
```

- [ ] **Step 6: Route structure, clear, alignment, undo, and status through the session**

```python
# replace direct mutations and QMessageBox warnings in src/gui/table_editor.py
def _apply_structure(self, label, operation, *args, current=None) -> bool:
    try:
        changed = self.session.apply(label, lambda table: operation(table, *args))
    except TableStructureError as exc:
        self._set_status(str(exc), error=True)
        return False
    if changed and current is not None:
        self.grid.setCurrentCell(*current)
    return changed


def apply_horizontal_alignment(self, alignment: str) -> bool:
    return self.session.align_cells(
        self._selected_indices(),
        horizontal=alignment,
    )


def apply_vertical_alignment(self, alignment: str) -> bool:
    return self.session.align_cells(
        self._selected_indices(),
        vertical=alignment,
    )


def _set_status(self, message: str, *, error: bool = False) -> None:
    self.statusLabel.setText(message)
    self.statusLabel.setProperty("error", error)
    self.statusLabel.style().unpolish(self.statusLabel)
    self.statusLabel.style().polish(self.statusLabel)


def result_table_spec(self):
    self.delegate.commit_active_editor()
    return self.session.result()
```

- [ ] **Step 7: Run the editor core tests**

Run: `python -m pytest tests/test_table_editor_dialog.py tests/test_table_edit_session.py -q`

Expected: all tests pass, including the retained structure and serialization regressions.

- [ ] **Step 8: Commit the editor core**

```bash
git add src/gui/table_editor.py tests/test_table_editor_dialog.py
git commit -m "feat: add undoable multiline table editing"
```

---

### Task 4: Command bar, width modes, zoom, and source comparison

**Files:**
- Modify: `src/gui/table_editor.py`
- Modify: `tests/test_table_editor_dialog.py`

**Interfaces:**
- Consumes: `resolve_table_layout`, `fallback_table_layout`, `TableEditSession.set_manual_widths`, `TableEditSession.set_auto_widths`.
- Produces: `TableEditorDialog(table_spec, parent=None, show_source=False)`, `actions: dict[str, QAction]`, `viewModeCombo`, `zoomCombo`, `editorSplitter`, `sourcePanel`, `_apply_view_widths()`, and `_update_command_state()`.

- [ ] **Step 1: Write failing width-mode and zoom tests**

```python
# append to tests/test_table_editor_dialog.py
def test_docx_actual_width_uses_layout_mm_and_screen_dpi():
    dialog = _dialog({
        "rows": [["A", "B"]],
        "column_widths": [0.25, 0.75],
        "layout": {"width_mode": "manual", "wide": False},
    })
    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("docx"))
    dialog.zoomCombo.setCurrentIndex(dialog.zoomCombo.findData(1.0))
    APP.processEvents()

    dpi = dialog.logicalDpiX()
    expected_total = round(82.0 * dpi / 25.4)
    actual_total = sum(dialog.grid.columnWidth(column) for column in range(2))

    assert actual_total == pytest.approx(expected_total, abs=3)
    assert dialog.grid.columnWidth(0) / actual_total == pytest.approx(0.25, abs=0.03)
    assert "DOCX 2단 · 82mm" in dialog.statusLabel.text()
    _close(dialog)


def test_view_mode_and_zoom_do_not_change_undo_stack_or_payload():
    dialog = _dialog({"rows": [["A", "B"]]})
    before = dialog.result_table_spec()

    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("docx"))
    dialog.zoomCombo.setCurrentIndex(dialog.zoomCombo.findData(1.25))
    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("fit"))

    assert dialog.session.undo_stack.count() == 0
    assert dialog.result_table_spec() == before
    _close(dialog)
```

- [ ] **Step 2: Write failing width-drag coalescing and source-panel tests**

```python
# append to tests/test_table_editor_dialog.py
def test_one_header_drag_creates_one_undo_command():
    dialog = _dialog({"rows": [["A", "B"]]})
    header = dialog.grid.horizontalHeader()

    dialog._begin_header_resize()
    dialog.grid.setColumnWidth(0, 180)
    dialog.grid.setColumnWidth(1, 60)
    dialog._finish_header_resize()

    assert dialog.session.undo_stack.count() == 1
    assert dialog.result_table_spec()["layout"]["width_mode"] == "manual"
    dialog.session.undo_stack.undo()
    assert dialog.result_table_spec()["layout"]["width_mode"] == "auto"
    _close(dialog)


def test_source_panel_only_enables_for_loadable_image(tmp_path):
    image = tmp_path / "table.png"
    image.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c6360f8cfc000000301010018dd8db10000000049454e44ae426082"
        )
    )
    dialog = _dialog({
        "rows": [["A"]],
        "source": {"image_path": str(image)},
    })

    assert dialog.actions["toggle_source"].isEnabled() is True
    dialog.actions["toggle_source"].trigger()
    assert dialog.sourcePanel.isVisibleTo(dialog) is True
    dialog.sourceZoomCombo.setCurrentIndex(dialog.sourceZoomCombo.findData(1.0))
    assert dialog.sourceImageLabel.pixmap().width() == 1
    assert dialog.session.undo_stack.count() == 0
    _close(dialog)


def test_command_groups_wrap_and_accessible_focus_order_is_stable():
    dialog = _dialog({"rows": [["A", "B"]]})

    dialog.commandBar.reflow(760)
    assert dialog.commandBar.group_rows() >= 2
    dialog.commandBar.reflow(1800)
    assert dialog.commandBar.group_rows() == 1
    assert dialog.actions["undo"].shortcut().toString() == "Ctrl+Z"
    assert dialog.grid.accessibleName() == "표 셀 편집 영역"
    assert dialog.saveButton.minimumHeight() >= 32
    assert dialog.minimumWidth() == 980
    assert dialog.minimumHeight() == 640
    _close(dialog)
```

- [ ] **Step 3: Run the new view tests and verify they fail**

Run: `python -m pytest tests/test_table_editor_dialog.py -q`

Expected: FAIL because view controls, source panel, and resize coalescing are not implemented.

- [ ] **Step 4: Build the grouped command bar and keyboard actions**

```python
# relevant setup in src/gui/table_editor.py
from pathlib import Path

from PyQt5.QtGui import QAction, QKeySequence, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QToolButton,
    QGridLayout,
    QDialogButtonBox,
    QWidget,
)


class ResponsiveCommandBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)

    def add_group(self, group: QWidget) -> None:
        self._groups.append(group)
        self.reflow(max(1, self.width()))

    def reflow(self, available_width: int) -> None:
        while self._grid.count():
            self._grid.takeAt(0)
        row = 0
        column = 0
        used = 0
        spacing = self._grid.horizontalSpacing()
        for group in self._groups:
            required = max(group.minimumSizeHint().width(), group.sizeHint().width())
            if column and used + spacing + required > available_width:
                row += 1
                column = 0
                used = 0
            self._grid.addWidget(group, row, column)
            column += 1
            used += (spacing if used else 0) + required

    def group_rows(self) -> int:
        return 1 + max(
            (self._grid.getItemPosition(index)[0] for index in range(self._grid.count())),
            default=-1,
        )

    def resizeEvent(self, event):
        self.reflow(event.size().width())
        super().resizeEvent(event)


def _action_group(parent, title: str, actions: list[QAction]) -> QWidget:
    group = QWidget(parent)
    row = QHBoxLayout(group)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    label = QLabel(title, group)
    row.addWidget(label)
    for action in actions:
        button = QToolButton(group)
        button.setDefaultAction(action)
        button.setMinimumHeight(32)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        row.addWidget(button)
    return group


def _make_action(self, key, text, callback, shortcut=None):
    action = QAction(text, self)
    action.setToolTip(text)
    action.triggered.connect(callback)
    if shortcut is not None:
        action.setShortcut(QKeySequence(shortcut))
    self.actions[key] = action
    self.addAction(action)
    return action


def _build_actions(self):
    self.actions = {}
    self._make_action("undo", "실행 취소", self.session.undo_stack.undo, "Ctrl+Z")
    self._make_action("redo", "다시 실행", self.session.undo_stack.redo, "Ctrl+Y")
    self._make_action("row_above", "위에 행 삽입", self.add_row_above)
    self._make_action("row_below", "아래에 행 삽입", self.add_row_below)
    self._make_action("column_left", "왼쪽에 열 삽입", self.add_column_left)
    self._make_action("column_right", "오른쪽에 열 삽입", self.add_column_right)
    self._make_action("delete_rows", "선택 행 삭제", self.delete_selected_rows)
    self._make_action("delete_columns", "선택 열 삭제", self.delete_selected_columns)
    self._make_action("merge", "셀 병합", self.merge_selected_cells)
    self._make_action("split", "셀 분할", self.split_current_cell)
    self._make_action("align_left", "왼쪽 정렬", lambda: self.apply_horizontal_alignment("left"))
    self._make_action("align_center", "가운데 정렬", lambda: self.apply_horizontal_alignment("center"))
    self._make_action("align_right", "오른쪽 정렬", lambda: self.apply_horizontal_alignment("right"))
    self._make_action("align_top", "위쪽 정렬", lambda: self.apply_vertical_alignment("top"))
    self._make_action("align_middle", "세로 가운데", lambda: self.apply_vertical_alignment("center"))
    self._make_action("align_bottom", "아래쪽 정렬", lambda: self.apply_vertical_alignment("bottom"))
    self._make_action("auto_width", "폭 자동 맞춤", self.auto_fit_widths)
    self._make_action("toggle_source", "원본 비교", self._toggle_source_panel)
    redo_alternate = QAction(self)
    redo_alternate.setShortcut(QKeySequence("Ctrl+Shift+Z"))
    redo_alternate.triggered.connect(self.session.undo_stack.redo)
    self.addAction(redo_alternate)
    self.actions["undo"].setEnabled(False)
    self.actions["redo"].setEnabled(False)
    self.session.undo_stack.canUndoChanged.connect(self.actions["undo"].setEnabled)
    self.session.undo_stack.canRedoChanged.connect(self.actions["redo"].setEnabled)


def _build_command_bar(self):
    self.commandBar = ResponsiveCommandBar(self)
    for title, keys in (
        ("편집", ["undo", "redo"]),
        ("행·열", ["row_above", "row_below", "column_left", "column_right", "delete_rows", "delete_columns"]),
        ("셀", ["merge", "split"]),
        ("가로 정렬", ["align_left", "align_center", "align_right"]),
        ("세로 정렬", ["align_top", "align_middle", "align_bottom"]),
        ("배치", ["auto_width", "toggle_source"]),
    ):
        self.commandBar.add_group(
            _action_group(self.commandBar, title, [self.actions[key] for key in keys])
        )


def _build_dialog_chrome(self) -> None:
    root = QVBoxLayout(self)
    root.setContentsMargins(12, 12, 12, 10)
    root.setSpacing(8)
    root.addWidget(self.commandBar)
    view_row = QHBoxLayout()
    self.viewModeCombo = QComboBox(self)
    self.viewModeCombo.addItem("편집 맞춤", "fit")
    self.viewModeCombo.addItem("DOCX 실제 폭", "docx")
    self.zoomCombo = QComboBox(self)
    for label, value in (
        ("50%", 0.5),
        ("75%", 0.75),
        ("100%", 1.0),
        ("125%", 1.25),
        ("150%", 1.5),
        ("화면 맞춤", "fit"),
    ):
        self.zoomCombo.addItem(label, value)
    self.zoomCombo.setCurrentIndex(self.zoomCombo.findData(1.0))
    self.viewModeCombo.currentIndexChanged.connect(self._apply_view_widths)
    self.zoomCombo.currentIndexChanged.connect(self._apply_view_widths)
    view_row.addWidget(QLabel("표시", self))
    view_row.addWidget(self.viewModeCombo)
    view_row.addWidget(self.zoomCombo)
    view_row.addStretch(1)
    root.addLayout(view_row)
    root.addWidget(self.editorSplitter, 1)
    self.statusLabel = QLabel("준비", self)
    root.addWidget(self.statusLabel)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
    self.saveButton = buttons.button(QDialogButtonBox.Save)
    self.cancelButton = buttons.button(QDialogButtonBox.Cancel)
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    root.addWidget(buttons)
```

- [ ] **Step 5: Implement edit-fit and DOCX actual-width calculations**

```python
# add to src/gui/table_editor.py
from ..exporter.table_layout import fallback_table_layout, resolve_table_layout


def _resolved_layout(self):
    try:
        return resolve_table_layout(self.session.result())
    except Exception:
        return fallback_table_layout(self.session.result())


def _apply_view_widths(self) -> None:
    table = self.session.result()
    layout = self._resolved_layout()
    ratios = list(layout.column_widths)
    if self.viewModeCombo.currentData() == "docx":
        zoom_data = self.zoomCombo.currentData()
        physical_pixels = layout.total_width_mm * self.logicalDpiX() / 25.4
        if zoom_data == "fit":
            zoom = min(1.0, max(0.1, self.grid.viewport().width() / physical_pixels))
        else:
            zoom = float(zoom_data or 1.0)
        total_pixels = round(
            physical_pixels * zoom
        )
        status = (
            f"DOCX {'1단' if layout.wide else '2단'} · "
            f"{int(layout.total_width_mm)}mm"
        )
    else:
        total_pixels = max(480, self.grid.viewport().width())
        status = "편집 맞춤"
    self._rendering = True
    try:
        for column, ratio in enumerate(ratios):
            self.grid.setColumnWidth(column, max(36, round(total_pixels * ratio)))
    finally:
        self._rendering = False
    actual_mode = self.viewModeCombo.currentData() == "docx"
    self.gridScroll.setWidgetResizable(not actual_mode)
    self.gridScroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
    if actual_mode:
        chrome = self.grid.verticalHeader().width() + self.grid.frameWidth() * 2 + 4
        self.grid.resize(total_pixels + chrome, max(360, self.grid.sizeHint().height()))
    self._set_status(status)


def _configure_editor_geometry_and_focus(self) -> None:
    self.setMinimumSize(980, 640)
    available = self.screen().availableGeometry().size()
    self.resize(min(1180, available.width()), min(760, available.height()))
    self.grid.setAccessibleName("표 셀 편집 영역")
    self.sourcePanel.setAccessibleName("원본 표 이미지 비교 영역")
    self.saveButton.setMinimumHeight(32)
    self.cancelButton.setMinimumHeight(32)
    self.setTabOrder(self.commandBar, self.grid)
    self.setTabOrder(self.grid, self.sourcePanel)
    self.setTabOrder(self.sourcePanel, self.saveButton)
    self.setTabOrder(self.saveButton, self.cancelButton)


def _begin_header_resize(self) -> None:
    self._resize_before = self.session.result()


def _finish_header_resize(self) -> None:
    if self._resize_before is None or not self._header_touched:
        self._resize_before = None
        return
    widths = [
        self.grid.columnWidth(column)
        for column in range(self.grid.columnCount())
    ]
    self.session.set_manual_widths(widths)
    self._resize_before = None
    self._header_touched = False


class HeaderResizeTracker(QObject):
    def __init__(self, dialog):
        super().__init__(dialog.grid.horizontalHeader())
        self.dialog = dialog

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            self.dialog._header_touched = False
            self.dialog._begin_header_resize()
        elif event.type() == QEvent.MouseButtonRelease:
            self.dialog._finish_header_resize()
        return super().eventFilter(watched, event)


def _install_header_resize_tracking(self) -> None:
    self._resize_before = None
    self._header_touched = False
    self.grid.horizontalHeader().sectionResized.connect(
        lambda *_args: setattr(self, "_header_touched", not self._rendering)
    )
    self.headerResizeTracker = HeaderResizeTracker(self)
    self.grid.horizontalHeader().viewport().installEventFilter(
        self.headerResizeTracker
    )
```

- [ ] **Step 6: Implement source comparison and non-destructive view state**

```python
# add to src/gui/table_editor.py
def _load_source_image(self) -> None:
    source_path = str(
        (self.session.result().get("source") or {}).get("image_path") or ""
    )
    pixmap = QPixmap(source_path) if source_path else QPixmap()
    available = bool(source_path and Path(source_path).is_file() and not pixmap.isNull())
    self.actions["toggle_source"].setEnabled(available)
    if not available:
        self.actions["toggle_source"].setToolTip(
            "저장된 원본 표 이미지를 읽을 수 없습니다."
        )
        self.sourcePanel.hide()
        return
    self._sourcePixmap = pixmap
    self._apply_source_zoom()
    if self._show_source_on_open:
        self.sourcePanel.show()


def _toggle_source_panel(self) -> None:
    self.sourcePanel.setVisible(not self.sourcePanel.isVisible())


def _apply_source_zoom(self) -> None:
    if getattr(self, "_sourcePixmap", QPixmap()).isNull():
        return
    zoom = self.sourceZoomCombo.currentData()
    if zoom == "fit":
        size = self.sourceScroll.viewport().size()
        rendered = self._sourcePixmap.scaled(
            size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    else:
        factor = float(zoom or 1.0)
        rendered = self._sourcePixmap.scaled(
            round(self._sourcePixmap.width() * factor),
            round(self._sourcePixmap.height() * factor),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
    self.sourceImageLabel.setPixmap(rendered)


def _build_source_panel(self) -> None:
    self.sourcePanel = QWidget(self)
    panel_layout = QVBoxLayout(self.sourcePanel)
    self.sourceZoomCombo = QComboBox(self.sourcePanel)
    for label, value in (("화면 맞춤", "fit"), ("50%", 0.5), ("100%", 1.0), ("150%", 1.5)):
        self.sourceZoomCombo.addItem(label, value)
    self.sourceZoomCombo.currentIndexChanged.connect(self._apply_source_zoom)
    self.sourceScroll = QScrollArea(self.sourcePanel)
    self.sourceScroll.setWidgetResizable(True)
    self.sourceImageLabel = QLabel(self.sourceScroll)
    self.sourceImageLabel.setAlignment(Qt.AlignCenter)
    self.sourceScroll.setWidget(self.sourceImageLabel)
    panel_layout.addWidget(self.sourceZoomCombo)
    panel_layout.addWidget(self.sourceScroll, 1)
    self.sourcePanel.hide()


# store this at the start of TableEditorDialog.__init__
self._show_source_on_open = bool(show_source)


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


def _update_command_state(self) -> None:
    rows = self.grid.rowCount()
    columns = self.grid.columnCount()
    selected = self._selected_indices()
    selected_rows = {row for row, _column in selected}
    selected_columns = {column for _row, column in selected}
    rectangular = self._is_rectangular_selection(selected)
    current = self._cell_at_current_position()
    merged = [
        cell
        for cell in self.session.result()["cells"]
        if int(cell.get("row_span", 1)) > 1 or int(cell.get("col_span", 1)) > 1
    ]
    merge_conflict = any(
        any(
            int(cell["row"]) <= row < int(cell["row"]) + int(cell.get("row_span", 1))
            and int(cell["col"]) <= column < int(cell["col"]) + int(cell.get("col_span", 1))
            for row, column in selected
        )
        for cell in merged
    )
    can_merge = rectangular and len(selected) > 1 and not merge_conflict
    self.actions["merge"].setEnabled(can_merge)
    self.actions["merge"].setToolTip(
        "셀 병합" if can_merge else "연속된 직사각형의 일반 셀을 두 개 이상 선택하세요."
    )
    self.actions["split"].setEnabled(
        bool(current and (current["row_span"] > 1 or current["col_span"] > 1))
    )
    self.actions["split"].setToolTip(
        "셀 분할" if self.actions["split"].isEnabled()
        else "분할할 병합 셀의 시작 위치를 선택하세요."
    )
    row_conflict = any(
        any(
            int(cell["row"]) <= row < int(cell["row"]) + int(cell.get("row_span", 1))
            for row in selected_rows
        )
        for cell in merged
    )
    column_conflict = any(
        any(
            int(cell["col"]) <= column < int(cell["col"]) + int(cell.get("col_span", 1))
            for column in selected_columns
        )
        for cell in merged
    )
    can_delete_rows = len(selected_rows) < rows and not row_conflict
    can_delete_columns = len(selected_columns) < columns and not column_conflict
    self.actions["delete_rows"].setEnabled(can_delete_rows)
    self.actions["delete_columns"].setEnabled(can_delete_columns)
    if rows == 1:
        self.actions["delete_rows"].setToolTip("표에는 최소 1개의 행이 필요합니다.")
    elif row_conflict:
        self.actions["delete_rows"].setToolTip("병합 셀과 겹치는 행은 먼저 분할하세요.")
    else:
        self.actions["delete_rows"].setToolTip("선택 행 삭제")
    if columns == 1:
        self.actions["delete_columns"].setToolTip("표에는 최소 1개의 열이 필요합니다.")
    elif column_conflict:
        self.actions["delete_columns"].setToolTip("병합 셀과 겹치는 열은 먼저 분할하세요.")
    else:
        self.actions["delete_columns"].setToolTip("선택 열 삭제")
    current_row, current_column = self._current_position()
    insertion_boundaries = {
        "row_above": ("row", current_row),
        "row_below": ("row", current_row + 1),
        "column_left": ("col", current_column),
        "column_right": ("col", current_column + 1),
    }
    for key, (axis, boundary) in insertion_boundaries.items():
        span_key = "row_span" if axis == "row" else "col_span"
        conflict = any(
            int(cell[axis]) < boundary < int(cell[axis]) + int(cell.get(span_key, 1))
            for cell in merged
        )
        self.actions[key].setEnabled(not conflict)
        if conflict:
            self.actions[key].setToolTip("병합 셀 내부에는 행이나 열을 삽입할 수 없습니다.")
        else:
            self.actions[key].setToolTip(self.actions[key].text())
```

- [ ] **Step 7: Run editor, layout, and DOCX layout tests**

Run: `python -m pytest tests/test_table_editor_dialog.py tests/test_table_edit_session.py tests/test_table_layout.py -q`

Expected: all tests pass.

- [ ] **Step 8: Commit advanced editor controls**

```bash
git add src/gui/table_editor.py tests/test_table_editor_dialog.py
git commit -m "feat: add document width and source table views"
```

---

### Task 5: Integrate visual cards into QuestionEditor

**Files:**
- Modify: `src/gui/interface/editor.py:365-602`
- Modify: `tests/test_editor_table_format.py`
- Modify: `tests/test_editor_layout.py`

**Interfaces:**
- Consumes: `TablePreviewCard` signals and `TableEditorDialog.result_table_spec()`.
- Produces: `QuestionEditor.tablePreviewCards: dict[tuple[str, str], TablePreviewCard]`; retains `tableRenderModeCombos` as an alias to each card's combo for compatibility; removes `_table_preview()`, `_show_table_structure()`, and the path-only `_show_table_source()` modal.

- [ ] **Step 1: Write failing visual-card integration tests**

```python
# append to tests/test_editor_table_format.py
from PyQt5.QtWidgets import QDialog
from qfluentwidgets import PushButton

from src.gui.table_preview import ReadOnlyTablePreview, TablePreviewCard


def test_question_editor_uses_visual_preview_card_instead_of_flat_structure_row():
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    card = editor.tablePreviewCards[("question", "table-1")]

    assert isinstance(card, TablePreviewCard)
    assert isinstance(card.preview, ReadOnlyTablePreview)
    assert card.preview.rowCount() == 2
    assert card.preview.columnCount() == 2
    assert not any(
        button.text() == "구조 보기"
        for button in editor.tableCardsWidget.findChildren(PushButton)
    )
    editor.deleteLater()
    APP.processEvents()


def test_accepting_table_dialog_replaces_payload_and_refreshes_preview(monkeypatch):
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    class AcceptedDialog:
        def __init__(self, table, parent, show_source=False):
            self.table = table
            self.show_source = show_source

        def exec(self):
            return QDialog.Accepted

        def result_table_spec(self):
            result = dict(self.table)
            result["rows"] = [["변경", "완료"]]
            result["cells"] = []
            return result

    monkeypatch.setattr("src.gui.interface.editor.TableEditorDialog", AcceptedDialog)
    editor._edit_table_structure("question", "table-1")

    card = editor.tablePreviewCards[("question", "table-1")]
    table = json.loads(editor.question_data["question_format_json"])["tables"][0]
    assert table["rows"] == [["변경", "완료"]]
    assert table["source"]["sha256"] == "abc123"
    assert card.preview.item(0, 0).text() == "변경"
    editor.deleteLater()
    APP.processEvents()


def test_canceling_table_dialog_does_not_replace_payload(monkeypatch):
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    before = editor.question_data["question_format_json"]

    class RejectedDialog:
        def __init__(self, table, parent, show_source=False):
            self.table = table
            self.show_source = show_source

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr("src.gui.interface.editor.TableEditorDialog", RejectedDialog)
    editor._edit_table_structure("question", "table-1")

    assert editor.question_data["question_format_json"] == before
    editor.deleteLater()
    APP.processEvents()


def test_source_compare_opens_the_same_editor_with_source_panel_requested(monkeypatch):
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    requested = []

    class SourceDialog:
        def __init__(self, table, parent, show_source=False):
            requested.append(show_source)

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr("src.gui.interface.editor.TableEditorDialog", SourceDialog)
    editor._compare_table_source("question", "table-1")

    assert requested == [True]
    editor.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: Run integration tests and verify the flat-card implementation fails**

Run: `python -m pytest tests/test_editor_table_format.py -q`

Expected: FAIL because `tablePreviewCards` does not exist and the old `구조 보기` action is present.

- [ ] **Step 3: Replace dynamic flat rows with `TablePreviewCard` instances**

```python
# imports in src/gui/interface/editor.py
from ..table_preview import TablePreviewCard


# replacement for _init_table_cards and _rebuild_table_cards portions
def _init_table_cards(self):
    self.tableSectionLabel = BodyLabel("표", self)
    self.tableCardsWidget = QWidget(self)
    self.tableCardsLayout = QVBoxLayout(self.tableCardsWidget)
    self.tableCardsLayout.setContentsMargins(0, 0, 0, 0)
    self.tableCardsLayout.setSpacing(10)
    self.tablePreviewCards = {}
    self.tableRenderModeCombos = {}
    self._rebuild_table_cards()


def _add_table_preview_card(self, owner: str, table: dict) -> None:
    table_id = str(table["id"])
    card = TablePreviewCard(owner, table, self.tableCardsWidget)
    card.editRequested.connect(self._edit_table_structure)
    card.sourceRequested.connect(self._compare_table_source)
    card.deleteRequested.connect(self._delete_table)
    card.renderModeChanged.connect(self._set_table_render_mode)
    self.tableCardsLayout.addWidget(card)
    key = (owner, table_id)
    self.tablePreviewCards[key] = card
    self.tableRenderModeCombos[key] = card.mode_combo


def _rebuild_table_cards(self):
    self._clear_table_cards()
    self.tablePreviewCards = {}
    self.tableRenderModeCombos = {}
    owners = [("question", self.question_data.get("question_format_json"))]
    owners.extend(
        (
            f"choice:{int(choice.get('choice_number') or 0)}",
            choice.get("choice_format_json") or choice.get("format_json"),
        )
        for choice in self.question_data.get("choices") or []
    )
    for owner, format_json in owners:
        for table in parse_format_payload(format_json).get("tables", []):
            self._add_table_preview_card(owner, table)
    self.tableSectionLabel.setVisible(True)
    self.tableCardsWidget.setVisible(bool(self.tablePreviewCards))
```

- [ ] **Step 4: Remove redundant structure-summary methods and preserve edit flow**

```python
# keep this accepted-result flow in src/gui/interface/editor.py
def _open_table_editor(self, owner, table_id, *, show_source=False):
    table = self._find_owner_table(owner, table_id)
    if not table:
        return
    dialog = TableEditorDialog(table, self, show_source=show_source)
    if dialog.exec() != QDialog.Accepted:
        return
    self._replace_table_spec(owner, table_id, dialog.result_table_spec())


def _edit_table_structure(self, owner, table_id):
    self._open_table_editor(owner, table_id, show_source=False)


def _compare_table_source(self, owner, table_id):
    self._open_table_editor(owner, table_id, show_source=True)


# delete these obsolete methods and their button wiring:
# _table_preview
# _show_table_structure
# _show_table_source
```

- [ ] **Step 5: Add viewport and card-height layout coverage**

```python
# append to tests/test_editor_layout.py
def test_table_preview_card_keeps_question_editor_primary_actions_visible():
    data = _question_editor_data()
    data["question_format_json"] = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "large",
            "rows": [[f"R{row}C{column}" for column in range(6)] for row in range(12)],
        }],
    }, ensure_ascii=False)
    editor = QuestionEditor(
        question_data=data,
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    editor.resize(960, 780)
    editor.show()
    APP.processEvents()

    card = editor.tablePreviewCards[("question", "large")]
    assert card.preview.maximumHeight() == 180
    assert editor.buttonBar.isVisibleTo(editor) is True
    assert editor.btnSave.isVisibleTo(editor) is True
    editor.deleteLater()
    APP.processEvents()
```

- [ ] **Step 6: Run QuestionEditor integration and layout tests**

Run: `python -m pytest tests/test_editor_table_format.py tests/test_editor_layout.py -q`

Expected: all tests pass, including existing image, marker, create-mode, and table metadata tests.

- [ ] **Step 7: Commit QuestionEditor integration**

```bash
git add src/gui/interface/editor.py tests/test_editor_table_format.py tests/test_editor_layout.py
git commit -m "feat: integrate visual table cards into question editor"
```

---

### Task 6: DOCX, payload, Mounted routing, real-database, and visual regression gates

**Files:**
- Modify: `tests/test_docx_exporter.py`
- Modify: `tests/test_validate_table_payloads.py`
- Modify: `tests/test_table_editor_dialog.py`
- Modify: `tests/test_mounted_browser.py`
- Verify: `src/exporter/docx.py`
- Verify: `src/database/mounted_repository.py`
- Verify: `scripts/validate_table_payloads.py`

**Interfaces:**
- Consumes: final editor-produced schema-v2 payloads and the existing DOCX native-table renderer.
- Produces: regression proof only; no production interface changes are expected unless a test exposes a real defect.

- [ ] **Step 1: Add an editor-produced DOCX alignment and width regression test**

```python
# append to tests/test_docx_exporter.py
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH


def test_editor_table_alignment_and_manual_width_survive_docx_export(tmp_path):
    output_path = tmp_path / "edited-table.docx"
    table = {
        "id": "edited",
        "rows": [["왼쪽", "오른쪽"], ["위", "아래"]],
        "cells": [
            {
                "row": 0, "col": 0, "text": "왼쪽",
                "horizontal_alignment": "left", "vertical_alignment": "center",
            },
            {
                "row": 0, "col": 1, "text": "오른쪽",
                "horizontal_alignment": "right", "vertical_alignment": "center",
            },
            {
                "row": 1, "col": 0, "text": "위",
                "horizontal_alignment": "center", "vertical_alignment": "top",
            },
            {
                "row": 1, "col": 1, "text": "아래",
                "horizontal_alignment": "center", "vertical_alignment": "bottom",
            },
        ],
        "column_widths": [0.3, 0.7],
        "layout": {"width_mode": "manual", "wide": False},
        "render_mode": "native",
    }
    questions = [{
        "question_text": "표를 확인하시오.",
        "question_format_json": json.dumps({
            "schema_version": 2,
            "tables": [table],
        }, ensure_ascii=False),
        "correct_answer": 1,
        "choices": [{"choice_number": 1, "choice_text": "정답"}],
    }]

    DocxExporter().export("표 편집 회귀", questions, str(output_path))
    document = Document(output_path)
    exported = document.tables[0]

    assert exported.cell(0, 0).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert exported.cell(0, 1).paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert exported.cell(1, 0).vertical_alignment == WD_CELL_VERTICAL_ALIGNMENT.TOP
    assert exported.cell(1, 1).vertical_alignment == WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
    first = exported.cell(0, 0).width
    second = exported.cell(0, 1).width
    assert first / (first + second) == pytest.approx(0.3, abs=0.03)
```

- [ ] **Step 2: Add full payload round-trip coverage**

```python
# append to tests/test_validate_table_payloads.py
def test_normalize_database_preserves_editor_alignment_spans_and_widths(tmp_path):
    payload = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "editor-table",
            "rows": [["AB", ""], ["C", "D"]],
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "text": "AB",
                    "row_span": 1,
                    "col_span": 2,
                    "horizontal_alignment": "center",
                    "vertical_alignment": "top",
                },
                {"row": 1, "col": 0, "text": "C"},
                {"row": 1, "col": 1, "text": "D"},
            ],
            "column_widths": [0.4, 0.6],
            "layout": {"width_mode": "manual", "wide": False},
        }],
    }, ensure_ascii=False)
    db_path = tmp_path / "bank.db"
    _database(db_path, payload, None)

    normalize_database(db_path, source_root=tmp_path)

    with sqlite3.connect(db_path) as conn:
        table = json.loads(
            conn.execute("SELECT question_format_json FROM questions").fetchone()[0]
        )["tables"][0]
    assert table["cells"][0]["col_span"] == 2
    assert table["cells"][0]["horizontal_alignment"] == "center"
    assert table["cells"][0]["vertical_alignment"] == "top"
    assert table["column_widths"] == [0.4, 0.6]
```

- [ ] **Step 3: Add an owning-Mount write-routing regression test**

```python
# append to tests/test_mounted_browser.py
# add beside the existing standard-library imports
import json


def test_table_payload_edit_is_written_only_to_owning_mount(tmp_path, monkeypatch):
    repository, first_db, second_db = _mounted_fixture(tmp_path)
    widget = BrowserInterface(repository=repository)
    existing = repository.get_question("second::1")
    edited = dict(existing)
    edited["question_format_json"] = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "edited-table",
            "rows": [["A", "B"]],
            "cells": [
                {"row": 0, "col": 0, "text": "A"},
                {"row": 0, "col": 1, "text": "B"},
            ],
            "column_widths": [0.3, 0.7],
            "layout": {"width_mode": "manual", "wide": False},
        }],
    }, ensure_ascii=False)
    editor = SimpleNamespace(get_data=lambda: edited)
    monkeypatch.setattr(browser_module.InfoBar, "success", lambda **_kwargs: None)

    widget._save_open_editor("second::1", editor, repository)

    assert ExamRepository(str(second_db)).get_question(1)["question_format_json"]
    assert ExamRepository(str(first_db)).get_question(1)["question_format_json"] is None
    widget.deleteLater()
    APP.processEvents()
```

- [ ] **Step 4: Run focused end-to-end regression tests**

Run: `python -m pytest tests/test_docx_exporter.py tests/test_validate_table_payloads.py tests/test_mounted_browser.py -q`

Expected: all tests pass; the existing Mounted write-routing tests remain green.

- [ ] **Step 5: Run the actual problem-bank table validator read-only**

Run: `python scripts/validate_table_payloads.py --db C:\Users\user\Documents\Codex\exam-weaver-archive\data\exam_bank.db`

Expected: JSON reports `"tables": 75` and `"errors": 0`. Do not pass the normalization/write flag during this regression check.

- [ ] **Step 6: Run the complete automated test suite**

Run: `python -m pytest -q`

Expected: all tests pass with only the repository's documented optional-fixture skips.

- [ ] **Step 7: Run source compilation and diff hygiene checks**

Run: `python -m compileall -q src`

Expected: exit code 0 and no output.

Run: `git diff --check`

Expected: exit code 0 and no whitespace errors.

- [ ] **Step 8: Perform fixed-size visual QA in the running app**

Run: `Run_Latest_App.bat`

Check these exact states against the approved visual reference:

- Open a question containing a 1×1 `<보기>` table at a 960×780 question-editor size; confirm the preview is a real bordered cell and the bottom `저장`/`취소` bar remains visible.
- Open a 3×2 table with a merged cell at a 1280×900 question-editor size; confirm spans, tooltips, metadata, scrollbars, and action hierarchy.
- Open the dedicated editor at 1180×760; type two lines with Enter, move with Tab/Shift+Tab, undo and redo, merge and split, apply all six alignment states, drag a header, and cancel once to verify isolation.
- Switch between `편집 맞춤` and `DOCX 실제 폭` at 82 mm and 180 mm cases; test 50%, 100%, and 150% zoom without changing undo history.
- Toggle the source panel for a table with a valid crop and confirm it stays disabled with an explanatory tooltip for a table without a crop.
- Repeat the editor check at Windows display scales 100%, 125%, and 150%; confirm no primary action is clipped and the command groups wrap instead of overflowing.

- [ ] **Step 9: Commit regression gates or any test-exposed minimal fix**

```bash
git add tests/test_docx_exporter.py tests/test_validate_table_payloads.py tests/test_table_editor_dialog.py tests/test_mounted_browser.py
git add src/exporter/docx.py src/gui/table_editor.py
git commit -m "test: verify document-style table editing regressions"
```

- [ ] **Step 10: Record final branch state for merge handoff**

Run: `git status --short --branch`

Expected: `## codex/multicell-table-editor` with no tracked changes. The repository-root user-owned ZIP remains outside this isolated worktree and must not be staged or deleted.
