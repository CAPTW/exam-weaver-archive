from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from experiments.db_mount_prototype.exam_move import (
    ExamMoveConflict,
    apply_exam_move,
    dry_run_exam_move,
)
from src.database.repository import ExamRepository
from src.parser.question import Choice, Question
from src.quiz.generator import MockExamGenerator


def _question(number: int, text: str, *, exam_type="DIAT 정보통신상식", subject_name="컴퓨터 이해"):
    return Question(
        number=number,
        text=text,
        choices=[
            Choice(number=1, symbol="㉮", text="가"),
            Choice(number=2, symbol="㉯", text="나"),
            Choice(number=3, symbol="㉴", text="사"),
            Choice(number=4, symbol="㉵", text="아"),
        ],
        correct_answer=1,
        subject_name=subject_name,
        year=2024,
        session=41,
        exam_type=exam_type,
    )


def _save_questions(db_path, questions):
    repo = ExamRepository(str(db_path))
    repo.init_database()
    metadata = SimpleNamespace(year=2024, session=41, exam_type=questions[0].exam_type)
    repo.save_questions(questions, metadata)
    return repo


def _attach_source_and_group(db_path, exam_code="DIAT 정보통신상식"):
    with sqlite3.connect(db_path) as conn:
        source_id = conn.execute(
            """
            INSERT INTO question_sources (
                provider, source_url, content_hash
            ) VALUES (?, ?, ?)
            """,
            ("unit", f"https://example.test/{exam_code}", f"hash-{exam_code}"),
        ).lastrowid
        exam_subject_id = conn.execute(
            """
            SELECT es.id
            FROM exam_subjects es
            JOIN exams e ON e.id = es.exam_id
            WHERE e.code = ?
            """,
            (exam_code,),
        ).fetchone()[0]
        group_id = conn.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, group_type, shared_text, source_id
            ) VALUES (?, 2024, 41, 1, 'passage', '공통 지문', ?)
            """,
            (exam_subject_id, source_id),
        ).lastrowid
        conn.execute(
            """
            UPDATE questions
            SET source_id = ?, group_id = ?, group_order = 1
            WHERE exam_subject_id = ? AND question_number = 1
            """,
            (source_id, group_id, exam_subject_id),
        )
        conn.commit()


def test_move_exam_copies_closure_removes_source_and_keeps_mock_generation(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"
    _save_questions(source_db, [_question(1, "DIAT 공통 문항"), _question(2, "DIAT 단독 문항")])
    _attach_source_and_group(source_db)
    ExamRepository(str(target_db)).init_database()

    plan = dry_run_exam_move(source_db, target_db, "DIAT 정보통신상식")
    assert plan.can_apply is True
    assert plan.counts["questions"] == 2
    assert plan.counts["choices"] == 8
    assert plan.counts["groups"] == 1
    assert plan.counts["sources"] == 1

    result = apply_exam_move(source_db, target_db, "DIAT 정보통신상식", backup=False)
    assert result.moved is True
    assert result.target_exam_id is not None

    with sqlite3.connect(source_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM exams WHERE code = 'DIAT 정보통신상식'"
        ).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 0

    target_repo = ExamRepository(str(target_db))
    moved = target_repo.get_questions_with_choices(
        exam_code="DIAT 정보통신상식",
        limit=None,
    )
    assert [row["question_text"] for row in moved] == ["DIAT 공통 문항", "DIAT 단독 문항"]
    assert [len(row["choices"]) for row in moved] == [4, 4]
    assert moved[0]["group_shared_text"] == "공통 지문"

    subject_code = target_repo.get_subject_options("DIAT 정보통신상식")[0]["code"]
    mock_exam = MockExamGenerator(target_repo).create(
        "DIAT 정보통신상식",
        [subject_code],
        count=1,
    )
    assert mock_exam["total_questions"] == 1


def test_move_exam_blocks_target_exam_code_conflict_without_changes(tmp_path):
    source_db = tmp_path / "source.db"
    target_db = tmp_path / "target.db"
    _save_questions(source_db, [_question(1, "source DIAT")])
    _save_questions(target_db, [_question(1, "target DIAT")])

    plan = dry_run_exam_move(source_db, target_db, "DIAT 정보통신상식")
    assert plan.can_apply is False
    assert any(issue.code == "target_exam_exists" for issue in plan.issues)

    with pytest.raises(ExamMoveConflict):
        apply_exam_move(source_db, target_db, "DIAT 정보통신상식", backup=False)

    with sqlite3.connect(source_db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM questions"
        ).fetchone()[0] == 1
    with sqlite3.connect(target_db) as conn:
        assert conn.execute(
            "SELECT question_text FROM questions"
        ).fetchone()[0] == "target DIAT"
