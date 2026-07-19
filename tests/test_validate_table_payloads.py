import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from scripts.validate_table_payloads import normalize_database, validate_database


def _database(path, question_format_json=None, choice_format_json=None):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE questions (id INTEGER PRIMARY KEY, question_format_json TEXT);
            CREATE TABLE question_choices (id INTEGER PRIMARY KEY, choice_format_json TEXT);
        """)
        conn.execute(
            "INSERT INTO questions (id, question_format_json) VALUES (1, ?)",
            (question_format_json,),
        )
        conn.execute(
            "INSERT INTO question_choices (id, choice_format_json) VALUES (1, ?)",
            (choice_format_json,),
        )


def test_validate_database_counts_native_image_and_legacy_tables(tmp_path):
    image = tmp_path / "table.png"
    image.write_bytes(b"table")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    native = json.dumps({
        "schema_version": 2,
        "tables": [{
            "rows": [["A"]],
            "cells": [{"row": 0, "col": 0, "text": "A"}],
            "source": {"image_path": "table.png", "sha256": digest},
            "confidence": {"score": .95},
        }],
    })
    legacy = json.dumps({"tables": [{"rows": [["B"]]}]})
    db_path = tmp_path / "bank.db"
    _database(db_path, native, legacy)

    report = validate_database(db_path, source_root=tmp_path)

    assert report["tables"] == 2
    assert report["native_ready"] == 1
    assert report["legacy_rows"] == 1
    assert report["errors"] == 0


def test_validate_database_reports_structural_errors_with_row_identity(tmp_path):
    invalid = json.dumps({
        "tables": [{
            "id": "bad-table",
            "rows": [["A"]],
            "cells": [{"row": 2, "col": 0, "text": "bad"}],
            "source": {"image_path": "missing.png"},
            "confidence": {"score": .2},
        }],
    })
    db_path = tmp_path / "bank.db"
    _database(db_path, invalid, None)

    report = validate_database(db_path, source_root=tmp_path)

    assert report["errors"] == 2
    assert {finding["code"] for finding in report["findings"]} == {
        "source_image_missing",
        "cell_out_of_bounds",
    }
    assert all(finding["row_id"] == 1 for finding in report["findings"])
    assert all(finding["table_id"] == "bad-table" for finding in report["findings"])


def test_normalize_database_creates_backup_and_upgrades_legacy_payload(tmp_path):
    db_path = tmp_path / "bank.db"
    _database(db_path, json.dumps({"tables": [{"rows": [["A"]]}]}), None)

    report = normalize_database(db_path, source_root=tmp_path)

    assert report["normalized_rows"] == 1
    assert report["backup_path"]
    assert (tmp_path / report["backup_path"].split("/")[-1]).is_file()
    with sqlite3.connect(db_path) as conn:
        payload = json.loads(
            conn.execute("SELECT question_format_json FROM questions").fetchone()[0]
        )
    assert payload["schema_version"] == 2
    assert payload["tables"][0]["id"] == "table-1"


def test_validator_script_runs_directly_from_repository_root(tmp_path):
    db_path = tmp_path / "bank.db"
    _database(db_path, None, None)
    script = Path(__file__).parents[1] / "scripts" / "validate_table_payloads.py"

    result = subprocess.run(
        [sys.executable, str(script), "--db", str(db_path)],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tables"] == 0


def test_normalize_database_leaves_non_table_format_payloads_unchanged(tmp_path):
    db_path = tmp_path / "bank.db"
    spans_only = json.dumps({"spans": [{"start": 0, "end": 1, "underline": True}]})
    _database(db_path, spans_only, None)

    report = normalize_database(db_path, source_root=tmp_path)

    assert report["normalized_rows"] == 0
    with sqlite3.connect(db_path) as conn:
        stored = conn.execute(
            "SELECT question_format_json FROM questions"
        ).fetchone()[0]
    assert stored == spans_only


def test_normalize_database_preserves_multicell_layout_and_merge_backup(tmp_path):
    payload = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "merged",
            "rows": [["AB", ""], ["C", "D"]],
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "text": "AB",
                    "row_span": 1,
                    "col_span": 2,
                    "merge_backup": [
                        {"row": 0, "col": 0, "text": "A"},
                        {"row": 0, "col": 1, "text": "B"},
                    ],
                },
                {"row": 1, "col": 0, "text": "C"},
                {"row": 1, "col": 1, "text": "D"},
            ],
            "column_widths": [0.3, 0.7],
            "layout": {"width_mode": "manual", "wide": False},
            "confidence": {"score": 1.0},
            "custom_table": {"keep": True},
        }],
    })
    db_path = tmp_path / "bank.db"
    _database(db_path, payload, None)

    normalize_database(db_path, source_root=tmp_path)

    with sqlite3.connect(db_path) as conn:
        stored = json.loads(
            conn.execute("SELECT question_format_json FROM questions").fetchone()[0]
        )["tables"][0]
    assert stored["layout"] == {"width_mode": "manual", "wide": False}
    assert stored["column_widths"] == [0.3, 0.7]
    assert stored["cells"][0]["merge_backup"][1]["text"] == "B"
    assert stored["custom_table"] == {"keep": True}


def test_normalize_database_preserves_editor_alignment_spans_and_widths(tmp_path):
    payload = json.dumps({
        "schema_version": 2,
        "tables": [{
            "id": "editor-table",
            "rows": [["AB", ""], ["C", "D"]],
            "cells": [
                {
                    "row": 0,
                    "col": 0,
                    "text": "AB",
                    "row_span": 1,
                    "col_span": 2,
                    "horizontal_alignment": "center",
                    "vertical_alignment": "top",
                },
                {"row": 1, "col": 0, "text": "C"},
                {"row": 1, "col": 1, "text": "D"},
            ],
            "column_widths": [0.4, 0.6],
            "layout": {"width_mode": "manual", "wide": False},
        }],
    }, ensure_ascii=False)
    db_path = tmp_path / "bank.db"
    _database(db_path, payload, None)

    normalize_database(db_path, source_root=tmp_path)

    with sqlite3.connect(db_path) as conn:
        table = json.loads(
            conn.execute(
                "SELECT question_format_json FROM questions"
            ).fetchone()[0]
        )["tables"][0]
    assert table["cells"][0]["col_span"] == 2
    assert table["cells"][0]["horizontal_alignment"] == "center"
    assert table["cells"][0]["vertical_alignment"] == "top"
    assert table["column_widths"] == [0.4, 0.6]
