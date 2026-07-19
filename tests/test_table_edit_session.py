import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QApplication

from src.gui.table_edit_session import TableEditSession
from src.parser.table_structure import insert_row, merge_cells


APP = QApplication.instance() or QApplication([])


def _table():
    return {
        "id": "t1",
        "rows": [["A", "B"], ["C", "D"]],
        "source": {"sha256": "keep"},
        "custom_table": {"keep": True},
    }


def test_text_edit_is_one_undoable_command_and_preserves_metadata():
    session = TableEditSession(_table())

    assert session.replace_cell_text(0, 0, "A\n수정") is True
    assert session.result()["rows"][0][0] == "A\n수정"
    assert session.result()["source"]["sha256"] == "keep"
    assert session.result()["custom_table"] == {"keep": True}
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
    assert result["column_widths"] == pytest.approx([0.3, 0.7])
    assert session.undo_stack.count() == 4

    for _index in range(4):
        session.undo_stack.undo()
    assert session.result()["rows"] == [["A", "B"], ["C", "D"]]


def test_cancel_isolation_keeps_input_object_unchanged():
    original = _table()
    session = TableEditSession(original)
    session.apply("셀 병합", lambda table: merge_cells(table, 0, 0, 0, 1))

    assert original["rows"] == [["A", "B"], ["C", "D"]]
    assert "cells" not in original
    assert session.is_dirty() is True


def test_no_op_does_not_add_undo_command_or_emit_change():
    session = TableEditSession(_table())
    emitted = []
    session.changed.connect(emitted.append)

    assert session.replace_cell_text(0, 0, "A") is False
    assert session.undo_stack.count() == 0
    assert emitted == []


def test_alignment_targets_merged_origin_without_creating_covered_cells():
    session = TableEditSession(_table())
    session.apply("셀 병합", lambda table: merge_cells(table, 0, 0, 0, 1))

    session.align_cells({(0, 0)}, horizontal="right", vertical="bottom")
    merged = next(
        cell for cell in session.result()["cells"]
        if cell["row"] == 0 and cell["col"] == 0
    )

    assert merged["col_span"] == 2
    assert merged["horizontal_alignment"] == "right"
    assert merged["vertical_alignment"] == "bottom"
    assert not any(
        cell["row"] == 0 and cell["col"] == 1
        for cell in session.result()["cells"]
    )


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
