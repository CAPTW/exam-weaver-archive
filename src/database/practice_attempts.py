"""Portable practice-attempt persistence for mounted question sources."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence


_SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_mount_id TEXT NOT NULL,
    source_mount_label TEXT NOT NULL,
    source_exam_code TEXT NOT NULL,
    source_exam_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress',
    total_questions INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER,
    score REAL,
    time_spent_seconds INTEGER,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    CHECK (status IN ('in_progress', 'completed'))
);

CREATE TABLE IF NOT EXISTS practice_attempt_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES practice_attempts(id) ON DELETE CASCADE,
    source_question_id TEXT NOT NULL,
    source_subject_id TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    question_snapshot_json TEXT NOT NULL,
    selected_answer INTEGER,
    correct_answer INTEGER,
    is_correct BOOLEAN,
    UNIQUE(attempt_id, source_question_id)
);

CREATE TABLE IF NOT EXISTS practice_attempt_subject_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES practice_attempts(id) ON DELETE CASCADE,
    source_subject_id TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    total_questions INTEGER NOT NULL,
    correct_count INTEGER NOT NULL,
    score REAL NOT NULL,
    UNIQUE(attempt_id, source_subject_id)
);

CREATE INDEX IF NOT EXISTS idx_practice_attempt_questions_attempt
ON practice_attempt_questions(attempt_id, display_order);

CREATE INDEX IF NOT EXISTS idx_practice_attempt_subject_results_attempt
ON practice_attempt_subject_results(attempt_id);
"""


class PracticeAttemptStore:
    """Store a self-contained attempt without requiring source question rows."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()

    def create_attempt(
        self,
        *,
        mount_id: str,
        mount_label: str,
        exam_code: str,
        exam_name: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO practice_attempts (
                    source_mount_id,
                    source_mount_label,
                    source_exam_code,
                    source_exam_name,
                    total_questions
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (mount_id, mount_label, exam_code, exam_name, len(questions)),
            )
            attempt_id = int(cursor.lastrowid)
            for display_order, question in enumerate(questions, 1):
                connection.execute(
                    """
                    INSERT INTO practice_attempt_questions (
                        attempt_id,
                        source_question_id,
                        source_subject_id,
                        subject_name,
                        display_order,
                        question_snapshot_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        str(question.get("id") or ""),
                        self._subject_id(question),
                        str(question.get("subject_name") or ""),
                        display_order,
                        json.dumps(question, ensure_ascii=False, default=str),
                    ),
                )
        return attempt_id

    def complete_attempt(
        self,
        attempt_id: int,
        *,
        result: Mapping[str, Any],
        duration_seconds: int,
    ) -> None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM practice_attempts WHERE id = ?",
                (attempt_id,),
            ).fetchone()
            if existing is None:
                raise ValueError(f"Unknown practice attempt: {attempt_id}")

            for detail in result.get("details", []):
                question = detail.get("question") or {}
                cursor = connection.execute(
                    """
                    UPDATE practice_attempt_questions
                    SET selected_answer = ?, correct_answer = ?, is_correct = ?
                    WHERE attempt_id = ? AND source_question_id = ?
                    """,
                    (
                        detail.get("selected"),
                        detail.get("correct_answer"),
                        int(bool(detail.get("is_correct"))),
                        attempt_id,
                        str(question.get("id") or ""),
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        "Practice result references an unknown question: "
                        f"{question.get('id')}"
                    )

            connection.execute(
                "DELETE FROM practice_attempt_subject_results WHERE attempt_id = ?",
                (attempt_id,),
            )
            for subject_id, stats in (result.get("subject_stats") or {}).items():
                total = int(stats.get("total") or 0)
                correct = int(stats.get("correct") or 0)
                score = round((correct / total) * 100, 1) if total else 0.0
                connection.execute(
                    """
                    INSERT INTO practice_attempt_subject_results (
                        attempt_id,
                        source_subject_id,
                        subject_name,
                        total_questions,
                        correct_count,
                        score
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        str(subject_id or ""),
                        str(stats.get("subject") or ""),
                        total,
                        correct,
                        score,
                    ),
                )

            connection.execute(
                """
                UPDATE practice_attempts
                SET status = 'completed',
                    total_questions = ?,
                    correct_count = ?,
                    score = ?,
                    time_spent_seconds = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    int(result.get("total") or 0),
                    int(result.get("correct") or 0),
                    float(result.get("score") or 0.0),
                    int(duration_seconds),
                    attempt_id,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA)
        return connection

    @staticmethod
    def _subject_id(question: Mapping[str, Any]) -> str:
        value = (
            question.get("mounted_subject_code")
            or question.get("subject_code")
            or question.get("exam_subject_id")
            or ""
        )
        return str(value)
