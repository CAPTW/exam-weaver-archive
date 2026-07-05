import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.browser import BrowserInterface
from src.gui.interface.practice import GRADING_MODE_INSTANT, PracticeInterface


APP = QApplication.instance() or QApplication([])


def _select_subject(widget, subject_code, count):
    for row in widget.subjectSelectionRows:
        if row["code"] == subject_code:
            row["checkbox"].setChecked(True)
            row["count_spin"].setValue(count)
            return
    raise AssertionError(f"subject not found: {subject_code}")


def test_browser_explanation_sidecar_saves_question_explanation(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    widget = BrowserInterface(repo.db_path)

    widget.open_explanation(question["id"])
    assert widget.explanation_sidecar_expanded is True
    assert widget.current_explanation_question_id == question["id"]

    widget.explanationEditor.setPlainText("상세 해설 본문")
    widget.save_current_explanation()

    assert repo.get_question(question["id"])["explanation"] == "상세 해설 본문"

    widget.deleteLater()
    APP.processEvents()


def test_practice_revealed_answer_can_expand_saved_explanation(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    repo.update_question_explanation(question["id"], "정답은 출력 계산식으로 확인한다.")
    widget = PracticeInterface(repo.db_path)
    _select_subject(widget, "engine1", 1)
    widget.gradingModeCombo.setCurrentIndex(
        widget.gradingModeCombo.findData(GRADING_MODE_INSTANT)
    )

    widget.start_quiz()
    widget.select_answer(2)

    assert widget.explanationToggleButton.isHidden() is False
    assert widget.explanationBox.isHidden() is True

    widget.toggle_current_explanation()

    assert widget.explanationBox.isHidden() is False
    assert "출력 계산식" in widget.explanationBox.toPlainText()

    widget.deleteLater()
    APP.processEvents()
