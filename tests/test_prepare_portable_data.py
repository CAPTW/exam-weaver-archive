import sqlite3
import json
from pathlib import Path

import pytest

from scripts.prepare_portable_data import prepare_portable_data
from src.runtime_paths import FACTORY_DB_NAME, USER_DB_NAME


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe"
    b"\x02\xfeA\xe2U\xcd\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_minimal_db(path: Path, question_image: str, choice_image: str):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY,
                image_path TEXT,
                question_format_json TEXT
            );
            CREATE TABLE question_choices (
                id INTEGER PRIMARY KEY,
                choice_image_path TEXT,
                choice_format_json TEXT
            );
            """,
        )
        conn.execute(
            "INSERT INTO questions (id, image_path) VALUES (1, ?)",
            (question_image,),
        )
        conn.execute(
            "INSERT INTO question_choices (id, choice_image_path) VALUES (1, ?)",
            (choice_image,),
        )


def test_prepare_portable_data_copies_factory_user_db_and_rewrites_images(tmp_path):
    repo_root = tmp_path / "repo"
    relative_image = repo_root / "data" / "extracted" / "question.png"
    absolute_image = tmp_path / "absolute-choice.png"
    relative_image.parent.mkdir(parents=True)
    relative_image.write_bytes(PNG_1X1)
    absolute_image.write_bytes(PNG_1X1 + b"choice")

    source_db = tmp_path / "source.db"
    _create_minimal_db(
        source_db,
        "data/extracted/question.png",
        str(absolute_image),
    )

    target_data = tmp_path / "dist" / "ExamGenerator" / "data"
    manifest = prepare_portable_data(source_db, target_data, repo_root)

    assert (target_data / FACTORY_DB_NAME).exists()
    assert (target_data / USER_DB_NAME).exists()
    assert manifest["updated_image_refs"] == 2
    assert manifest["copied_images"] == 2

    for db_name in (FACTORY_DB_NAME, USER_DB_NAME):
        with sqlite3.connect(target_data / db_name) as conn:
            question_path = conn.execute("SELECT image_path FROM questions").fetchone()[0]
            choice_path = conn.execute("SELECT choice_image_path FROM question_choices").fetchone()[0]

        assert question_path.startswith("data/portable_images/")
        assert choice_path.startswith("data/portable_images/")
        assert not Path(question_path).is_absolute()
        assert not Path(choice_path).is_absolute()
        assert (target_data.parent / question_path).exists()
        assert (target_data.parent / choice_path).exists()


def test_prepare_portable_data_fails_on_missing_image_by_default(tmp_path):
    source_db = tmp_path / "source.db"
    _create_minimal_db(source_db, "missing-question.png", "")

    with pytest.raises(RuntimeError, match="Missing 1 image"):
        prepare_portable_data(source_db, tmp_path / "data", tmp_path)


def test_prepare_portable_data_rewrites_table_images_inside_format_json(tmp_path):
    repo_root = tmp_path / "repo"
    table_image = repo_root / "data" / "table_images" / "table.png"
    table_image.parent.mkdir(parents=True)
    table_image.write_bytes(PNG_1X1 + b"table")
    source_db = tmp_path / "source.db"
    _create_minimal_db(source_db, "", "")
    payload = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "table-1",
            "rows": [["A"]],
            "source": {"image_path": "data/table_images/table.png"},
        }],
    })
    with sqlite3.connect(source_db) as conn:
        conn.execute("UPDATE questions SET question_format_json = ?", (payload,))
        conn.execute("UPDATE question_choices SET choice_format_json = ?", (payload,))

    target_data = tmp_path / "dist" / "ExamGenerator" / "data"
    manifest = prepare_portable_data(source_db, target_data, repo_root)

    assert manifest["table_image_refs"] == 2
    assert manifest["updated_table_image_refs"] == 2
    assert manifest["copied_images"] == 1
    with sqlite3.connect(target_data / FACTORY_DB_NAME) as conn:
        question_json = conn.execute(
            "SELECT question_format_json FROM questions"
        ).fetchone()[0]
        choice_json = conn.execute(
            "SELECT choice_format_json FROM question_choices"
        ).fetchone()[0]
    for encoded in (question_json, choice_json):
        rewritten = json.loads(encoded)["tables"][0]["source"]["image_path"]
        assert rewritten.startswith("data/portable_images/")
        assert (target_data.parent / rewritten).is_file()


def test_prepare_portable_data_reports_missing_table_image(tmp_path):
    source_db = tmp_path / "source.db"
    _create_minimal_db(source_db, "", "")
    payload = json.dumps({
        "tables": [{"rows": [["A"]], "source": {"image_path": "missing-table.png"}}]
    })
    with sqlite3.connect(source_db) as conn:
        conn.execute("UPDATE questions SET question_format_json = ?", (payload,))

    with pytest.raises(RuntimeError, match="Missing 1 image"):
        prepare_portable_data(source_db, tmp_path / "data", tmp_path)
