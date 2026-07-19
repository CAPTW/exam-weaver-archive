import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtGui import QImage
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QPlainTextEdit

from src.gui.table_editor import TableEditorDialog
from src.parser.table_format import parse_format_payload, serialize_format_payload
from src.parser.table_structure import insert_column
from src.parser.view_table import add_one_cell_table


APP = QApplication.instance() or QApplication([])


def _dialog(table=None):
    dialog = TableEditorDialog(table or {"id": "t1", "rows": [["A"]]})
    dialog.show()
    APP.processEvents()
    return dialog


def _close(dialog):
    dialog.close()
    dialog.deleteLater()
    APP.processEvents()


def test_dialog_exposes_all_structure_actions():
    dialog = _dialog()

    assert [button.text() for button in dialog.structure_buttons] == [
        "위에 행 추가",
        "아래에 행 추가",
        "왼쪽에 열 추가",
        "오른쪽에 열 추가",
        "선택 행 삭제",
        "선택 열 삭제",
        "셀 병합",
        "셀 분할",
        "폭 자동 맞춤",
    ]
    _close(dialog)


def test_add_below_and_right_expands_one_cell_table():
    dialog = _dialog()
    dialog.grid.setCurrentCell(0, 0)

    dialog.add_row_below()
    dialog.add_column_right()

    assert dialog.table_spec["rows"] == [["A", ""], ["", ""]]
    assert dialog.grid.rowCount() == 2
    assert dialog.grid.columnCount() == 2
    _close(dialog)


def test_add_above_and_left_uses_current_cell_position():
    dialog = _dialog({"rows": [["A", "B"], ["C", "D"]]})
    dialog.grid.setCurrentCell(1, 1)

    dialog.add_row_above()
    dialog.grid.setCurrentCell(2, 1)
    dialog.add_column_left()

    assert dialog.table_spec["rows"] == [
        ["A", "", "B"],
        ["", "", ""],
        ["C", "", "D"],
    ]
    _close(dialog)


def test_selected_rows_and_columns_are_deleted_together():
    dialog = _dialog({
        "rows": [
            ["A", "B", "C"],
            ["D", "E", "F"],
            ["G", "H", "I"],
        ]
    })
    selection = dialog.grid.selectionModel()
    for row, col in ((0, 1), (2, 1)):
        selection.select(
            dialog.grid.model().index(row, col),
            QItemSelectionModel.Select,
        )

    dialog.delete_selected_rows()

    assert dialog.table_spec["rows"] == [["D", "E", "F"]]
    dialog.grid.setCurrentCell(0, 1)
    dialog.delete_selected_columns()
    assert dialog.table_spec["rows"] == [["D", "F"]]
    _close(dialog)


def test_rectangular_selection_merges_and_splits():
    dialog = _dialog({"rows": [["A", "B"], ["C", "D"]]})
    selection = dialog.grid.selectionModel()
    for row in range(2):
        for col in range(2):
            selection.select(
                dialog.grid.model().index(row, col),
                QItemSelectionModel.Select,
            )

    dialog.merge_selected_cells()

    assert dialog.grid.rowSpan(0, 0) == 2
    assert dialog.grid.columnSpan(0, 0) == 2
    assert dialog.table_spec["rows"][0][0] == "A\nB\nC\nD"

    dialog.grid.setCurrentCell(0, 0)
    dialog.split_current_cell()
    assert dialog.table_spec["rows"] == [["A", "B"], ["C", "D"]]
    _close(dialog)


def test_header_resize_is_persisted_as_manual_width():
    dialog = _dialog({"rows": [["A", "B"]]})
    dialog.grid.setColumnWidth(0, 210)
    dialog.grid.setColumnWidth(1, 70)
    APP.processEvents()

    result = dialog.result_table_spec()

    assert result["layout"]["width_mode"] == "manual"
    assert result["column_widths"] == pytest.approx([0.75, 0.25], abs=0.02)
    _close(dialog)


def test_auto_fit_marks_width_mode_auto():
    dialog = _dialog({
        "rows": [["A", "긴 설명"]],
        "column_widths": [0.5, 0.5],
        "layout": {"width_mode": "manual"},
    })

    dialog.auto_fit_widths()

    assert dialog.result_table_spec()["layout"]["width_mode"] == "auto"
    _close(dialog)


def test_result_captures_last_uncommitted_cell_text():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.item(0, 0).setText("수정된 값")

    assert dialog.result_table_spec()["rows"] == [["수정된 값"]]
    _close(dialog)


def test_parse_edit_serialize_reopen_preserves_structure_and_metadata():
    payload = parse_format_payload({
        "tables": [{
            "id": "source-table",
            "rows": [["A", "B"], ["C", "D"]],
            "column_widths": [0.4, 0.6],
            "anchor": {"offset": 3, "before_context": "앞"},
            "source": {"image_path": "table.png", "sha256": "abc"},
            "custom_table": {"keep": True},
        }]
    })
    dialog = _dialog(payload["tables"][0])
    dialog.grid.setCurrentCell(1, 1)
    dialog.add_row_below()
    dialog.grid.setCurrentCell(1, 1)
    dialog.add_column_right()
    selection = dialog.grid.selectionModel()
    selection.clearSelection()
    for row in range(1, 3):
        for col in range(1, 3):
            selection.select(
                dialog.grid.model().index(row, col),
                QItemSelectionModel.Select,
            )
    dialog.merge_selected_cells()
    dialog.grid.setColumnWidth(0, 90)
    dialog.grid.setColumnWidth(1, 180)
    dialog.grid.setColumnWidth(2, 90)
    APP.processEvents()

    encoded = serialize_format_payload({"tables": [dialog.result_table_spec()]})
    reopened = parse_format_payload(encoded)["tables"][0]

    assert reopened["id"] == "source-table"
    assert reopened["anchor"]["offset"] == 3
    assert reopened["source"]["sha256"] == "abc"
    assert reopened["custom_table"] == {"keep": True}
    assert len(reopened["rows"]) == 3
    assert len(reopened["rows"][0]) == 3
    merged = next(cell for cell in reopened["cells"] if cell["row_span"] == 2)
    assert merged["col_span"] == 2
    assert len(merged["merge_backup"]) == 4
    assert reopened["layout"]["width_mode"] == "manual"
    assert sum(reopened["column_widths"]) == pytest.approx(1.0)
    _close(dialog)


def test_manual_view_table_expands_without_losing_view_metadata():
    encoded = add_one_cell_table("앞 뒤", None, "<보기>\n① A ② B", 1)
    original = parse_format_payload(encoded)["tables"][0]
    dialog = _dialog(original)
    dialog.grid.setCurrentCell(0, 0)

    dialog.add_row_below()
    dialog.add_row_below()
    dialog.add_column_right()
    result = dialog.result_table_spec()

    assert result["rows"][0][0] == "<보기>\n① A ② B"
    assert len(result["rows"]) == 3
    assert len(result["rows"][0]) == 2
    assert result["anchor"]["offset"] == 1
    assert result["source"]["kind"] == "view_block_text"
    assert result["render_mode"] == "native"
    _close(dialog)


def test_direct_cell_change_is_one_undoable_command():
    dialog = _dialog({"rows": [["A"]]})

    dialog.grid.item(0, 0).setText("수정")
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["수정"]]
    assert dialog.session.undo_stack.count() == 1
    dialog.session.undo_stack.undo()
    assert dialog.result_table_spec()["rows"] == [["A"]]
    _close(dialog)


def test_multiline_enter_and_tab_commit_one_edit_command():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.setCurrentCell(0, 0)
    dialog.grid.editItem(dialog.grid.item(0, 0))
    APP.processEvents()
    editor = dialog.grid.findChild(QPlainTextEdit)

    assert editor is not None
    editor.selectAll()
    QTest.keyClicks(editor, "first")
    QTest.keyClick(editor, Qt.Key_Return)
    QTest.keyClicks(editor, "second")
    QTest.keyClick(editor, Qt.Key_Tab)
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["first\nsecond"]]
    assert dialog.session.undo_stack.count() == 1
    _close(dialog)


def test_escape_cancels_uncommitted_cell_text():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.setCurrentCell(0, 0)
    dialog.grid.editItem(dialog.grid.item(0, 0))
    APP.processEvents()
    editor = dialog.grid.findChild(QPlainTextEdit)

    assert editor is not None
    editor.selectAll()
    QTest.keyClicks(editor, "discard")
    QTest.keyClick(editor, Qt.Key_Escape)
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["A"]]
    assert dialog.session.undo_stack.count() == 0
    _close(dialog)


def test_delete_clears_text_without_removing_structure():
    dialog = _dialog({"rows": [["A", "B"], ["C", "D"]]})
    dialog.grid.setCurrentCell(0, 0)

    QTest.keyClick(dialog.grid, Qt.Key_Delete)
    APP.processEvents()

    assert dialog.result_table_spec()["rows"] == [["", "B"], ["C", "D"]]
    assert dialog.grid.rowCount() == 2
    assert dialog.grid.columnCount() == 2
    assert dialog.session.undo_stack.count() == 1
    _close(dialog)


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
    assert {
        cell["vertical_alignment"]
        for cell in dialog.result_table_spec()["cells"]
    } == {"center"}
    _close(dialog)


def test_command_state_disables_invalid_merge_split_and_dimension_delete():
    dialog = _dialog({"rows": [["A"]]})
    dialog.grid.setCurrentCell(0, 0)
    dialog._update_command_state()

    assert dialog.actions["merge"].isEnabled() is False
    assert dialog.actions["split"].isEnabled() is False
    assert dialog.actions["delete_rows"].isEnabled() is False
    assert dialog.actions["delete_columns"].isEnabled() is False
    assert "최소 1개" in dialog.actions["delete_rows"].toolTip()
    _close(dialog)


def test_structure_error_uses_status_instead_of_modal():
    dialog = _dialog({
        "rows": [["AB", ""]],
        "cells": [{"row": 0, "col": 0, "text": "AB", "col_span": 2}],
    })
    result = dialog._apply_structure(
        "열 삽입",
        insert_column,
        1,
        current=(0, 1),
    )

    assert result is False
    assert "병합된 셀" in dialog.statusLabel.text()
    _close(dialog)


def test_docx_actual_width_uses_layout_mm_and_screen_dpi():
    dialog = _dialog({
        "rows": [["A", "B"]],
        "column_widths": [0.25, 0.75],
        "layout": {"width_mode": "manual", "wide": False},
    })
    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("docx"))
    dialog.zoomCombo.setCurrentIndex(dialog.zoomCombo.findData(1.0))
    APP.processEvents()

    expected_total = round(82.0 * dialog.logicalDpiX() / 25.4)
    actual_total = sum(
        dialog.grid.columnWidth(column)
        for column in range(dialog.grid.columnCount())
    )

    assert actual_total == pytest.approx(expected_total, abs=3)
    assert dialog.grid.columnWidth(0) / actual_total == pytest.approx(
        0.25,
        abs=0.03,
    )
    assert "DOCX 2단 · 82mm" in dialog.statusLabel.text()
    _close(dialog)


def test_wide_docx_actual_width_uses_180_mm():
    dialog = _dialog({
        "rows": [["A", "B"]],
        "layout": {"width_mode": "auto", "wide": True},
    })
    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("docx"))
    dialog.zoomCombo.setCurrentIndex(dialog.zoomCombo.findData(1.0))
    APP.processEvents()

    expected_total = round(180.0 * dialog.logicalDpiX() / 25.4)
    actual_total = sum(
        dialog.grid.columnWidth(column)
        for column in range(dialog.grid.columnCount())
    )

    assert actual_total == pytest.approx(expected_total, abs=3)
    assert "DOCX 1단 · 180mm" in dialog.statusLabel.text()
    _close(dialog)


def test_view_mode_and_zoom_do_not_change_undo_stack_or_payload():
    dialog = _dialog({"rows": [["A", "B"]]})
    before = dialog.result_table_spec()

    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("docx"))
    dialog.zoomCombo.setCurrentIndex(dialog.zoomCombo.findData(1.25))
    dialog.viewModeCombo.setCurrentIndex(dialog.viewModeCombo.findData("fit"))
    APP.processEvents()

    assert dialog.session.undo_stack.count() == 0
    assert dialog.result_table_spec() == before
    _close(dialog)


def test_one_header_drag_creates_one_undo_command():
    dialog = _dialog({"rows": [["A", "B"]]})

    dialog._begin_header_resize()
    dialog.grid.setColumnWidth(0, 180)
    dialog.grid.setColumnWidth(1, 60)
    dialog._finish_header_resize()

    assert dialog.session.undo_stack.count() == 1
    assert dialog.result_table_spec()["layout"]["width_mode"] == "manual"
    dialog.session.undo_stack.undo()
    assert dialog.result_table_spec()["layout"]["width_mode"] == "auto"
    _close(dialog)


def test_source_panel_loads_valid_image_and_does_not_change_history(tmp_path):
    image_path = tmp_path / "table.png"
    image = QImage(10, 6, QImage.Format_ARGB32)
    image.fill(Qt.white)
    assert image.save(str(image_path), "PNG") is True
    dialog = _dialog({
        "rows": [["A"]],
        "source": {"image_path": str(image_path)},
    })

    assert dialog.actions["toggle_source"].isEnabled() is True
    dialog.actions["toggle_source"].trigger()
    dialog.sourceZoomCombo.setCurrentIndex(
        dialog.sourceZoomCombo.findData(1.0)
    )
    APP.processEvents()

    assert dialog.sourcePanel.isVisibleTo(dialog) is True
    assert dialog.sourceImageLabel.pixmap().width() == 10
    assert dialog.sourceImageLabel.pixmap().height() == 6
    assert dialog.session.undo_stack.count() == 0
    _close(dialog)


def test_source_panel_is_disabled_when_original_is_missing():
    dialog = _dialog({
        "rows": [["A"]],
        "source": {"image_path": "missing-source.png"},
    })

    assert dialog.actions["toggle_source"].isEnabled() is False
    assert "원본" in dialog.actions["toggle_source"].toolTip()
    assert dialog.sourcePanel.isHidden() is True
    _close(dialog)


def test_command_groups_wrap_and_primary_actions_remain_accessible():
    dialog = _dialog({"rows": [["A", "B"]]})

    narrow_height = dialog.commandFlow.heightForWidth(480)
    wide_height = dialog.commandFlow.heightForWidth(2400)

    assert narrow_height > wide_height
    assert dialog.actions["undo"].shortcut().toString() == "Ctrl+Z"
    assert dialog.actions["redo"].shortcut().toString() == "Ctrl+Y"
    assert dialog.grid.accessibleName() == "표 셀 편집 영역"
    assert dialog.sourcePanel.accessibleName() == "원본 표 이미지 비교 영역"
    assert dialog.saveButton.minimumHeight() >= 32
    assert dialog.cancelButton.minimumHeight() >= 32
    assert dialog.minimumWidth() == 980
    assert dialog.minimumHeight() == 640
    _close(dialog)


def test_merged_region_disables_conflicting_structure_commands():
    dialog = _dialog({
        "rows": [["AB", ""], ["C", "D"]],
        "cells": [
            {"row": 0, "col": 0, "text": "AB", "col_span": 2},
            {"row": 1, "col": 0, "text": "C"},
            {"row": 1, "col": 1, "text": "D"},
        ],
    })
    dialog.grid.setCurrentCell(0, 0)
    dialog._update_command_state()

    assert dialog.actions["delete_rows"].isEnabled() is False
    assert dialog.actions["delete_columns"].isEnabled() is False
    assert "병합" in dialog.actions["delete_rows"].toolTip()
    assert "병합" in dialog.actions["delete_columns"].toolTip()
    _close(dialog)
