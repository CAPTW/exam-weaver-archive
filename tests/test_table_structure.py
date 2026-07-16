import copy

import pytest

from src.parser.table_structure import (
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


def _table():
    return {
        "id": "t1",
        "rows": [["A", "B"], ["C", "D"]],
        "cells": [
            {
                "row": row,
                "col": col,
                "text": text,
                "row_span": 1,
                "col_span": 1,
            }
            for row, values in enumerate([["A", "B"], ["C", "D"]])
            for col, text in enumerate(values)
        ],
        "column_widths": [0.6, 0.4],
        "layout": {"width_mode": "source"},
        "custom": {"keep": True},
    }


def test_normalize_repairs_ragged_rows_and_preserves_unknown_metadata():
    result = normalize_rectangular_table(
        {"rows": [["A"], ["B", "C"]], "custom": 7}
    )

    assert result["rows"] == [["A", ""], ["B", "C"]]
    assert [(cell["row"], cell["col"]) for cell in result["cells"]] == [
        (0, 0),
        (0, 1),
        (1, 0),
        (1, 1),
    ]
    assert result["custom"] == 7


def test_normalize_keeps_valid_merge_and_drops_covered_cell():
    result = normalize_rectangular_table({
        "rows": [["HEADER", ""], ["A", "B"]],
        "cells": [
            {"row": 0, "col": 0, "text": "HEADER", "row_span": 1, "col_span": 2},
            {"row": 0, "col": 1, "text": "covered", "row_span": 1, "col_span": 1},
        ],
    })

    assert result["rows"] == [["HEADER", ""], ["A", "B"]]
    assert [(cell["row"], cell["col"]) for cell in result["cells"]] == [
        (0, 0),
        (1, 0),
        (1, 1),
    ]
    assert result["cells"][0]["col_span"] == 2


def test_insert_row_above_moves_existing_cells_without_mutating_input():
    original = _table()
    before = copy.deepcopy(original)

    result = insert_row(original, 1)

    assert result["rows"] == [["A", "B"], ["", ""], ["C", "D"]]
    assert original == before


def test_insert_column_scales_old_widths_and_assigns_new_share():
    result = insert_column(_table(), 1)

    assert result["rows"] == [["A", "", "B"], ["C", "", "D"]]
    assert result["column_widths"] == pytest.approx([0.4, 1 / 3, 4 / 15])
    assert sum(result["column_widths"]) == pytest.approx(1.0)


def test_delete_multiple_rows_reindexes_remaining_cells():
    table = normalize_rectangular_table({
        "rows": [["A"], ["B"], ["C"], ["D"]]
    })

    result = delete_rows(table, [1, 2])

    assert result["rows"] == [["A"], ["D"]]
    assert [(cell["row"], cell["text"]) for cell in result["cells"]] == [
        (0, "A"),
        (1, "D"),
    ]


def test_delete_column_renormalizes_stored_widths():
    result = delete_columns(_table(), [0])

    assert result["rows"] == [["B"], ["D"]]
    assert result["column_widths"] == [1.0]


@pytest.mark.parametrize(
    ("operation", "indices"),
    [(delete_rows, [0, 1]), (delete_columns, [0, 1])],
)
def test_deleting_last_dimension_is_rejected(operation, indices):
    with pytest.raises(TableStructureError, match="최소 1개") as error:
        operation(_table(), indices)

    assert error.value.code == "minimum_table_size"


def test_structural_change_through_merged_region_is_rejected():
    table = {
        "rows": [["AB", ""], ["C", "D"]],
        "cells": [
            {"row": 0, "col": 0, "text": "AB", "row_span": 1, "col_span": 2},
            {"row": 1, "col": 0, "text": "C", "row_span": 1, "col_span": 1},
            {"row": 1, "col": 1, "text": "D", "row_span": 1, "col_span": 1},
        ],
    }

    with pytest.raises(TableStructureError) as error:
        insert_column(table, 1)

    assert error.value.code == "merged_region_conflict"

    with pytest.raises(TableStructureError) as error:
        delete_rows(table, [0])

    assert error.value.code == "merged_region_conflict"


def test_merge_rectangle_combines_text_and_keeps_exact_backup():
    result = merge_cells(_table(), 0, 0, 1, 1)
    origin = result["cells"][0]

    assert result["rows"] == [["A\nB\nC\nD", ""], ["", ""]]
    assert origin["row_span"] == 2
    assert origin["col_span"] == 2
    assert origin["merge_backup"] == [
        {"row": 0, "col": 0, "text": "A"},
        {"row": 0, "col": 1, "text": "B"},
        {"row": 1, "col": 0, "text": "C"},
        {"row": 1, "col": 1, "text": "D"},
    ]


def test_split_restores_original_cell_text_from_backup():
    result = split_cell(merge_cells(_table(), 0, 0, 1, 1), 0, 0)

    assert result["rows"] == [["A", "B"], ["C", "D"]]
    assert all(
        cell["row_span"] == cell["col_span"] == 1
        for cell in result["cells"]
    )


def test_split_without_backup_keeps_text_only_in_origin():
    table = {
        "rows": [["HEADER", ""]],
        "cells": [
            {"row": 0, "col": 0, "text": "HEADER", "row_span": 1, "col_span": 2}
        ],
    }

    assert split_cell(table, 0, 0)["rows"] == [["HEADER", ""]]


def test_merge_rejects_single_cell_and_partial_existing_merge():
    with pytest.raises(TableStructureError) as single:
        merge_cells(_table(), 0, 0, 0, 0)
    assert single.value.code == "merge_requires_multiple_cells"

    merged = merge_cells(_table(), 0, 0, 0, 1)
    with pytest.raises(TableStructureError) as overlap:
        merge_cells(merged, 0, 1, 1, 1)
    assert overlap.value.code == "merged_region_conflict"


def test_split_requires_merged_origin():
    with pytest.raises(TableStructureError) as error:
        split_cell(_table(), 0, 0)
    assert error.value.code == "split_requires_merged_origin"


def test_header_pixel_widths_are_saved_as_manual_ratios():
    result = set_manual_column_widths(_table(), [180, 60])

    assert result["column_widths"] == pytest.approx([0.75, 0.25])
    assert result["layout"]["width_mode"] == "manual"


def test_auto_mode_keeps_width_metadata_but_marks_it_non_authoritative():
    manual = set_manual_column_widths(_table(), [180, 60])
    result = set_auto_width_mode(manual)

    assert result["column_widths"] == pytest.approx([0.75, 0.25])
    assert result["layout"]["width_mode"] == "auto"


@pytest.mark.parametrize("widths", ([100], [100, 0], ["bad", 10]))
def test_invalid_manual_header_widths_are_rejected(widths):
    with pytest.raises(TableStructureError) as error:
        set_manual_column_widths(_table(), widths)
    assert error.value.code == "invalid_column_widths"
