import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import QApplication

from src.gui.interface.editor import QuestionEditor


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
