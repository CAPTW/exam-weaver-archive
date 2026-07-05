import os
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.practice import (
    CHOICE_CORRECT_STYLE,
    CHOICE_WRONG_STYLE,
    GRADING_MODE_EXAM_END,
    GRADING_MODE_INSTANT,
    PracticeInterface,
    evaluate_answers,
    save_practice_result,
)


APP = QApplication.instance() or QApplication([])


def _select_subject(widget, subject_code, count):
    for row in widget.subjectSelectionRows:
        if row["code"] == subject_code:
            row["checkbox"].setChecked(True)
            row["count_spin"].setValue(count)
            return
    raise AssertionError(f"subject not found: {subject_code}")


def test_evaluate_answers_scores_by_question_and_subject(sample_question, repo, sample_metadata):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(exam_code="3급기관사", limit=1)[0]

    result = evaluate_answers([question], {question["id"]: 2})

    assert result["total"] == 1
    assert result["correct"] == 1
    assert result["score"] == 100.0
    assert result["details"][0]["is_correct"] is True


def test_save_practice_result_records_overall_and_subject_rows(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(exam_code="3급기관사", limit=1)[0]
    with repo._get_connection() as conn:
        exam_id = conn.execute("SELECT id FROM exams WHERE code = ?", ("3급기관사",)).fetchone()[0]
        mock_exam_id = conn.execute(
            "INSERT INTO mock_exams (exam_id, name) VALUES (?, ?)",
            (exam_id, "GUI 풀이 테스트"),
        ).lastrowid

    result = save_practice_result(repo, mock_exam_id, [question], {question["id"]: 2}, 7)

    assert result["score"] == 100.0
    with sqlite3.connect(repo.db_path) as conn:
        rows = conn.execute(
            """
            SELECT exam_subject_id, total_questions, correct_count, score, time_spent_seconds
            FROM exam_results
            WHERE mock_exam_id = ?
            ORDER BY exam_subject_id IS NULL DESC, exam_subject_id ASC
            """,
            (mock_exam_id,),
        ).fetchall()

    assert rows[0] == (None, 1, 1, 100.0, 7)
    assert rows[1][0] is not None
    assert rows[1][1:] == (1, 1, 100.0, 7)


def test_practice_interface_starts_click_grades_and_shows_result(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    widget = PracticeInterface(repo.db_path)
    _select_subject(widget, "engine1", 1)

    widget.start_quiz()
    assert widget.stack.currentWidget() == widget.quizPage
    assert len(widget.questions) == 1

    widget.select_answer(2)
    widget.submit_exam()

    assert widget.stack.currentWidget() == widget.resultPage
    assert "1 / 1" in widget.resultSummaryLabel.text()
    assert widget.resultTable.rowCount() == 1

    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_exams").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mock_exam_questions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM exam_results").fetchone()[0] == 2

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_defaults_to_end_of_exam_grading(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    widget = PracticeInterface(repo.db_path)
    _select_subject(widget, "engine1", 1)

    assert widget._selected_grading_mode() == GRADING_MODE_EXAM_END

    widget.start_quiz()
    widget.select_answer(1)

    assert widget.feedbackLabel.text() == ""
    assert widget.revealed_question_ids == set()

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_hides_seed_exams_when_database_has_no_questions(repo):
    widget = PracticeInterface(repo.db_path)

    assert widget.examFilter.count() == 0
    assert widget.subjectSelectionTable.rowCount() == 0
    assert widget.subjectSelectionRows == []

    widget.deleteLater()
    APP.processEvents()


def test_practice_interface_instant_mode_reveals_and_locks_answer(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    widget = PracticeInterface(repo.db_path)
    _select_subject(widget, "engine1", 1)
    widget.gradingModeCombo.setCurrentIndex(
        widget.gradingModeCombo.findData(GRADING_MODE_INSTANT)
    )

    widget.start_quiz()
    question_id = widget.questions[0]["id"]
    widget.select_answer(1)

    assert question_id in widget.revealed_question_ids
    assert "오답입니다" in widget.feedbackLabel.text()
    assert CHOICE_WRONG_STYLE in widget.choiceGroup.button(1).styleSheet()
    assert CHOICE_CORRECT_STYLE in widget.choiceGroup.button(2).styleSheet()

    widget.select_answer(2)
    assert widget.answers[question_id] == 1

    widget.deleteLater()
    APP.processEvents()
