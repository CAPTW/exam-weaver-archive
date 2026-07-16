import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
