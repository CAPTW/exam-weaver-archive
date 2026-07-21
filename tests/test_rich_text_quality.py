import json

from src.parser.rich_text_quality import inspect_rich_text


def test_inspect_rich_text_enumerates_plain_rows_and_cells():
    payload = {
        "tables": [{
            "rows": [["㉠ Alpha", "㉡ Beta"]],
            "cells": [
                {"row": 0, "col": 0, "text": "㉠ Alpha"},
                {"row": 0, "col": 1, "text": "㉡ Beta"},
            ],
        }]
    }

    result = inspect_rich_text(
        "발문",
        json.dumps(payload, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
        row_id=7,
        question_id=7,
    )

    assert [surface.path for surface in result.surfaces] == [
        "question_text",
        "question_format_json.tables[0].rows[0][0]",
        "question_format_json.tables[0].rows[0][1]",
        "question_format_json.tables[0].cells[0].text",
        "question_format_json.tables[0].cells[1].text",
    ]
    assert result.issues == ()


def test_inspect_rich_text_rejects_invalid_json_and_rows_cells_divergence():
    invalid = inspect_rich_text(
        "발문",
        "[1, 2]",
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
    )
    assert [issue.code for issue in invalid.issues] == ["invalid_format_json"]

    divergent = inspect_rich_text(
        "발문",
        json.dumps({"tables": [{
            "rows": [["원본 A"]],
            "cells": [{"row": 0, "col": 0, "text": "원본 B"}],
        }]}, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
    )
    assert [issue.code for issue in divergent.issues] == [
        "rows_cells_divergence"
    ]
    assert (
        divergent.issues[0].path
        == "question_format_json.tables[0].cells[0].text"
    )


def test_inspect_rich_text_rejects_empty_or_unaddressable_cells():
    result = inspect_rich_text(
        "발문",
        json.dumps({"tables": [{
            "rows": [[""]],
            "cells": [{"row": "x", "col": 0, "text": "value"}],
        }]}, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
    )

    assert {issue.code for issue in result.issues} == {
        "empty_table_cell",
        "invalid_table_cell_coordinate",
    }
