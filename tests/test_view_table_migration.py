import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from src.database.view_table_migration import (
    build_view_table_staging,
    replace_with_view_table_staging,
    validate_view_table_staging,
)


def _make_exam_db(path: Path, view_rows=1, normal_rows=1) -> Path:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                question_text TEXT NOT NULL,
                question_format_json TEXT,
                correct_answer INTEGER,
                image_path TEXT,
                tags TEXT
            );
            CREATE TABLE question_choices (
                id INTEGER PRIMARY KEY,
                question_id INTEGER NOT NULL REFERENCES questions(id),
                choice_number INTEGER NOT NULL,
                choice_text TEXT NOT NULL
            );
            """
        )
        row_id = 1
        for number in range(view_rows):
            connection.execute(
                "INSERT INTO questions VALUES (?, ?, NULL, ?, ?, ?)",
                (
                    row_id,
                    f"질문 {number}? <보기> ① A ② B",
                    (number % 4) + 1,
                    f"image-{number}.png",
                    "#보기",
                ),
            )
            connection.execute(
                "INSERT INTO question_choices VALUES (?, ?, 1, ?)",
                (row_id, row_id, f"선지-{number}"),
            )
            row_id += 1
        for number in range(normal_rows):
            connection.execute(
                "INSERT INTO questions VALUES (?, ?, NULL, ?, NULL, ?)",
                (row_id, f"일반 질문 {number}?", 1, "#일반"),
            )
            connection.execute(
                "INSERT INTO question_choices VALUES (?, ?, 1, ?)",
                (row_id, row_id, f"일반 선지-{number}"),
            )
            row_id += 1
        connection.commit()
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_staging_promotes_only_view_questions_and_preserves_other_columns(tmp_path):
    source = _make_exam_db(tmp_path / "source.db", view_rows=2, normal_rows=1)
    staging = tmp_path / "staging.db"

    report = build_view_table_staging(source, staging)

    assert report.eligible_questions == 2
    assert report.promoted_questions == 2
    assert report.source_question_count == report.staging_question_count == 3
    assert report.source_choice_count == report.staging_choice_count == 3
    assert report.integrity_ok is True
    assert report.foreign_keys_ok is True
    assert report.non_target_mismatches == 0
    assert report.valid is True

    with sqlite3.connect(staging) as connection:
        rows = connection.execute(
            "SELECT question_text, question_format_json, correct_answer, image_path, tags "
            "FROM questions ORDER BY id"
        ).fetchall()
    assert rows[0][0] == "질문 0?"
    assert json.loads(rows[0][1])["tables"][0]["rows"] == [
        ["<보기>\n① A ② B"]
    ]
    assert rows[0][2:] == (1, "image-0.png", "#보기")
    assert rows[2] == ("일반 질문 0?", None, 1, None, "#일반")


def test_validate_rejects_tampered_non_target_question_column(tmp_path):
    source = _make_exam_db(tmp_path / "source.db")
    staging = tmp_path / "staging.db"
    build_view_table_staging(source, staging)
    with sqlite3.connect(staging) as connection:
        connection.execute("UPDATE questions SET correct_answer = 4 WHERE id = 1")

    report = validate_view_table_staging(source, staging)

    assert report.non_target_mismatches == 1
    assert report.valid is False


def test_validate_rejects_tampered_choice_row(tmp_path):
    source = _make_exam_db(tmp_path / "source.db")
    staging = tmp_path / "staging.db"
    build_view_table_staging(source, staging)
    with sqlite3.connect(staging) as connection:
        connection.execute(
            "UPDATE question_choices SET choice_text = '변조' WHERE id = 1"
        )

    report = validate_view_table_staging(source, staging)

    assert report.non_target_mismatches == 1
    assert report.valid is False


def test_migration_is_idempotent(tmp_path):
    source = _make_exam_db(tmp_path / "source.db", view_rows=2, normal_rows=0)
    first = build_view_table_staging(source, tmp_path / "first.db")

    second = build_view_table_staging(first.staging_db, tmp_path / "second.db")

    assert second.eligible_questions == 0
    assert second.promoted_questions == 0
    assert second.non_target_mismatches == 0
    assert second.valid is True


def test_replacement_creates_backup_and_matches_validated_staging(tmp_path):
    source = _make_exam_db(tmp_path / "source.db", view_rows=1, normal_rows=1)
    staging = tmp_path / "staging.db"
    report = build_view_table_staging(source, staging)
    staging_hash = _sha256(staging)

    receipt = replace_with_view_table_staging(
        source,
        report.staging_db,
        tmp_path / "backups",
    )

    assert receipt.backup_path.is_file()
    assert receipt.backup_sha256 == _sha256(receipt.backup_path)
    assert receipt.staging_sha256 == staging_hash
    assert receipt.mounted_sha256 == _sha256(source) == staging_hash
    with sqlite3.connect(receipt.backup_path) as backup_connection:
        assert backup_connection.execute(
            "SELECT question_text FROM questions WHERE id = 1"
        ).fetchone()[0] == "질문 0? <보기> ① A ② B"
    with sqlite3.connect(source) as connection:
        text, encoded = connection.execute(
            "SELECT question_text, question_format_json FROM questions WHERE id = 1"
        ).fetchone()
    assert text == "질문 0?"
    assert json.loads(encoded)["tables"][0]["source"]["kind"] == "view_block_text"


def test_replacement_refuses_invalid_staging_without_changing_source(tmp_path):
    source = _make_exam_db(tmp_path / "source.db")
    staging = tmp_path / "staging.db"
    build_view_table_staging(source, staging)
    with sqlite3.connect(staging) as connection:
        connection.execute("UPDATE questions SET tags = '#변조' WHERE id = 1")
    before = source.read_bytes()

    try:
        replace_with_view_table_staging(source, staging, tmp_path / "backups")
    except ValueError as exc:
        assert "validation" in str(exc).lower()
    else:
        raise AssertionError("invalid staging replacement must fail")

    assert source.read_bytes() == before
    assert not (tmp_path / "backups").exists()
