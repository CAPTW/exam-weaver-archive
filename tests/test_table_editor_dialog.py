import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtCore import QItemSelectionModel
from PyQt5.QtWidgets import QApplication

from src.gui.table_editor import TableEditorDialog


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
