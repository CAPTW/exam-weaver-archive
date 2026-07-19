import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QApplication, QDialog
from qfluentwidgets import PushButton

from src.gui.interface.editor import QuestionEditor
from src.gui.table_preview import ReadOnlyTablePreview, TablePreviewCard


APP = QApplication.instance() or QApplication([])


def _editor_data():
    return {
        "year": 2024,
        "session": 1,
        "question_number": 1,
        "subject_code": "engine1",
        "exam_code": "4급기관사",
        "question_text": "다음 표를 보고 답하시오",
        "question_format_json": json.dumps({
            "schema_version": 2,
            "tables": [{
                "id": "table-1",
                "anchor": {
                    "offset": 8,
                    "before_context": "다음 표를 보고",
                    "after_context": "답하시오",
                },
                "rows": [["구분", "값"], ["A", "10"]],
                "source": {"image_path": "data/table_images/table.png", "sha256": "abc123"},
                "confidence": {"score": .95, "reasons": ["native_grid"]},
                "render_mode": "auto",
            }],
        }, ensure_ascii=False),
        "correct_answer": 1,
        "choices": [
            {"choice_number": 1, "choice_text": "A"},
            {"choice_number": 2, "choice_text": "B"},
            {"choice_number": 3, "choice_text": "C"},
            {"choice_number": 4, "choice_text": "D"},
        ],
    }


def _plain_editor_data(question_text="일반 발문"):
    data = _editor_data()
    data["question_text"] = question_text
    data["question_format_json"] = None
    return data


def test_saving_text_keeps_table_source_and_recovers_anchor():
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    editor.questionText.setPlainText("완전히 수정된 발문")

    saved = editor.get_data()
    payload = json.loads(saved["question_format_json"])

    assert payload["tables"][0]["source"]["sha256"] == "abc123"
    assert payload["tables"][0]["rows"][1] == ["A", "10"]
    assert payload["tables"][0]["anchor"]["offset"] == len("완전히 수정된 발문")
    editor.deleteLater()
    APP.processEvents()


def test_table_card_changes_per_table_render_mode():
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    combo = editor.tableRenderModeCombos[("question", "table-1")]
    combo.setCurrentIndex(combo.findData("image"))
    payload = json.loads(editor.get_data()["question_format_json"])

    assert editor.tableCardsWidget.isHidden() is False
    assert payload["tables"][0]["render_mode"] == "image"
    editor.deleteLater()
    APP.processEvents()


def test_table_structure_edit_updates_rows_and_cells_without_losing_source():
    editor = QuestionEditor(
        question_data=_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    editor._update_table_rows(
        "question",
        "table-1",
        [["구분", "수정값"], ["B", "20"]],
    )
    payload = json.loads(editor.get_data()["question_format_json"])
    table = payload["tables"][0]

    assert table["rows"] == [["구분", "수정값"], ["B", "20"]]
    assert [cell["text"] for cell in table["cells"]] == ["구분", "수정값", "B", "20"]
    assert table["source"]["sha256"] == "abc123"
    editor.deleteLater()
    APP.processEvents()


def test_replacing_table_spec_keeps_source_anchor_and_unknown_metadata():
    data = _editor_data()
    payload = json.loads(data["question_format_json"])
    payload["tables"][0]["custom_table"] = {"keep": True}
    data["question_format_json"] = json.dumps(payload, ensure_ascii=False)
    editor = QuestionEditor(
        question_data=data,
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    replacement = {
        "rows": [["A", "B"], ["C", "D"]],
        "cells": [],
        "column_widths": [0.3, 0.7],
        "layout": {"width_mode": "manual"},
    }

    editor._replace_table_spec("question", "table-1", replacement)

    table = json.loads(editor.question_data["question_format_json"])["tables"][0]
    assert table["id"] == "table-1"
    assert table["source"]["sha256"] == "abc123"
    assert table["anchor"]["offset"] == 8
    assert table["custom_table"] == {"keep": True}
    assert table["rows"] == [["A", "B"], ["C", "D"]]
    assert table["layout"]["width_mode"] == "manual"
    editor.deleteLater()
    APP.processEvents()


def test_plain_view_question_is_promoted_when_editor_opens():
    editor = QuestionEditor(
        question_data=_plain_editor_data("질문? <보기> ① A ② B"),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    saved = editor.get_data()
    payload = json.loads(saved["question_format_json"])

    assert saved["question_text"] == "질문?"
    assert payload["tables"][0]["rows"] == [["<보기>\n① A ② B"]]
    assert editor.tableCardsLayout.count() == 1
    editor.deleteLater()
    APP.processEvents()


def test_table_add_control_is_visible_without_existing_tables():
    editor = QuestionEditor(
        question_data=_plain_editor_data(),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    assert editor.btnAddQuestionTable.isVisibleTo(editor) is True
    assert editor.tableSectionLabel.isVisibleTo(editor) is True
    editor.deleteLater()
    APP.processEvents()


def test_selected_question_text_moves_into_new_table():
    editor = QuestionEditor(
        question_data=_plain_editor_data("질문 앞 선택 내용 뒤"),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    cursor = editor.questionText.textCursor()
    start = editor.questionText.toPlainText().index("선택 내용")
    cursor.setPosition(start)
    cursor.setPosition(start + len("선택 내용"), QTextCursor.KeepAnchor)
    editor.questionText.setTextCursor(cursor)

    editor._add_question_table()
    saved = editor.get_data()
    payload = json.loads(saved["question_format_json"])

    assert "선택 내용" not in saved["question_text"]
    assert payload["tables"][-1]["rows"] == [["선택 내용"]]
    assert payload["tables"][-1]["anchor"]["offset"] == start
    editor.deleteLater()
    APP.processEvents()


def test_add_without_selection_creates_empty_view_table_at_cursor():
    editor = QuestionEditor(
        question_data=_plain_editor_data("질문 뒤"),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )
    cursor = editor.questionText.textCursor()
    cursor.setPosition(2)
    editor.questionText.setTextCursor(cursor)

    editor._add_question_table()
    table = json.loads(editor.get_data()["question_format_json"])["tables"][0]

    assert table["rows"] == [["<보기>\n"]]
    assert table["anchor"]["offset"] == 2
    editor.deleteLater()
    APP.processEvents()


def test_deleting_table_restores_cell_text_and_removes_card():
    editor = QuestionEditor(
        question_data=_plain_editor_data("질문? <보기> ① A"),
        subject_options=[{"code": "engine1", "name_ko": "기관1"}],
    )

    assert editor._delete_table("question", "view-table-1", confirm=False) is True
    saved = editor.get_data()

    assert saved["question_text"] == "질문?\n<보기>\n① A"
    assert saved["question_format_json"] is None
    assert editor.tableCardsLayout.count() == 0
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_uses_visual_preview_instead_of_flat_structure_row():
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


def test_accepting_table_editor_replaces_payload_and_refreshes_preview(monkeypatch):
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

    monkeypatch.setattr(
        "src.gui.interface.editor.TableEditorDialog",
        AcceptedDialog,
    )
    editor._edit_table_structure("question", "table-1")

    card = editor.tablePreviewCards[("question", "table-1")]
    table = json.loads(editor.question_data["question_format_json"])["tables"][0]
    assert table["rows"] == [["변경", "완료"]]
    assert table["source"]["sha256"] == "abc123"
    assert card.preview.item(0, 0).text() == "변경"
    editor.deleteLater()
    APP.processEvents()


def test_canceling_table_editor_keeps_payload_unchanged(monkeypatch):
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

    monkeypatch.setattr(
        "src.gui.interface.editor.TableEditorDialog",
        RejectedDialog,
    )
    editor._edit_table_structure("question", "table-1")

    assert editor.question_data["question_format_json"] == before
    editor.deleteLater()
    APP.processEvents()


def test_source_compare_opens_table_editor_with_source_panel_requested(monkeypatch):
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

    monkeypatch.setattr(
        "src.gui.interface.editor.TableEditorDialog",
        SourceDialog,
    )
    editor._compare_table_source("question", "table-1")

    assert requested == [True]
    editor.deleteLater()
    APP.processEvents()


def test_large_visual_preview_is_bounded_and_bottom_actions_remain_visible():
    data = _editor_data()
    data["question_format_json"] = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "large",
            "rows": [
                [f"R{row}C{column}" for column in range(6)]
                for row in range(12)
            ],
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
    assert editor.saveButton.isVisibleTo(editor) is True
    editor.deleteLater()
    APP.processEvents()
