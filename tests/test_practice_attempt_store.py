from __future__ import annotations

import importlib
import json
import sqlite3


def test_practice_attempt_store_persists_snapshot_answers_and_subject_results(tmp_path):
    practice_attempts = importlib.import_module("src.database.practice_attempts")
    store = practice_attempts.PracticeAttemptStore(tmp_path / "workspace.db")
    questions = [
        {
            "id": "source::7",
            "mounted_subject_code": "source::navigation",
            "subject_name": "항해학",
            "question_text": "발문",
            "correct_answer": 2,
            "choices": [
                {"number": 1, "text": "가"},
                {"number": 2, "text": "나"},
            ],
        }
    ]

    attempt_id = store.create_attempt(
        mount_id="source",
        mount_label="원본 DB",
        exam_code="source::해양경찰 항해학",
        exam_name="해양경찰 항해학",
        questions=questions,
    )
    result = {
        "total": 1,
        "correct": 1,
        "score": 100.0,
        "details": [
            {
                "question": questions[0],
                "selected": 2,
                "correct_answer": 2,
                "is_correct": True,
            }
        ],
        "subject_stats": {
            "source::navigation": {
                "subject": "항해학",
                "total": 1,
                "correct": 1,
            }
        },
    }

    store.complete_attempt(attempt_id, result=result, duration_seconds=12)

    with sqlite3.connect(tmp_path / "workspace.db") as conn:
        assert conn.execute(
            "SELECT status, total_questions, correct_count, score, "
            "time_spent_seconds FROM practice_attempts"
        ).fetchone() == ("completed", 1, 1, 100.0, 12)
        question_row = conn.execute(
            "SELECT source_question_id, source_subject_id, selected_answer, "
            "correct_answer, is_correct, question_snapshot_json "
            "FROM practice_attempt_questions"
        ).fetchone()
        assert question_row[:5] == ("source::7", "source::navigation", 2, 2, 1)
        assert json.loads(question_row[5])["question_text"] == "발문"
        assert conn.execute(
            "SELECT source_subject_id, total_questions, correct_count, score "
            "FROM practice_attempt_subject_results"
        ).fetchone() == ("source::navigation", 1, 1, 100.0)
