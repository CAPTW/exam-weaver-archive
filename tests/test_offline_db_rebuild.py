from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from src.database.repository import ExamRepository
from src.database.staging import (
    ExpectedExamSet,
    ReplacementError,
    build_staging_database,
    replace_mounted_database,
    validate_staging_database,
)
from src.parser.offline_exam import ParsedOfflineQuestion
from src.parser.offline_sources import DocumentRole, OfflineParseResult
from src.parser.question import Choice, Question


def _question(number: int, *, answer: int = 1, placeholder: bool = False) -> Question:
    choices = [
        Choice(
            number=index,
            symbol=str(index),
            text="원문 보기 참조" if placeholder and index == 1 else f"선지 {index}",
        )
        for index in range(1, 5)
    ]
    return Question(
        number=number,
        text=f"{number}번 문제",
        choices=choices,
        correct_answer=answer,
        source_page=number,
        subject_name="항해",
        year=2024,
        session=2,
        exam_type="해경",
    )


def _database(path: Path, questions: list[Question], *, provenance: bool = True) -> None:
    repo = ExamRepository(str(path))
    repo.init_database()
    repo.save_questions(
        questions,
        SimpleNamespace(year=2024, session=2, exam_type="해경"),
    )
    if provenance and questions:
        conn = sqlite3.connect(path)
        try:
            source_id = conn.execute(
                """
                INSERT INTO question_sources (
                    provider, source_url, document_id, attachment_filename, content_hash
                ) VALUES (?, ?, ?, ?, ?)
                """,
                ("offline_pdf", "file:///question.pdf", "question", "question.pdf", "a" * 64),
            ).lastrowid
            conn.execute("UPDATE questions SET source_id = ?", (source_id,))
            conn.commit()
        finally:
            conn.close()


def _expected(*numbers: int) -> ExpectedExamSet:
    return ExpectedExamSet(
        exam_type="해경",
        subject_name="항해",
        year=2024,
        session=2,
        question_numbers=tuple(numbers),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_inventories_documents_writes_reports_schema_and_provenance(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    question_pdf = root / "2024_해경_항해_문제.pdf"
    answer_pdf = root / "2024_해경_항해_정답.pdf"
    notice_pdf = root / "2024_해양경찰_채용시험_공고.pdf"
    for path in (question_pdf, answer_pdf, notice_pdf):
        path.write_bytes(path.name.encode("utf-8"))

    candidates = tuple(
        ParsedOfflineQuestion(
            number=number,
            stem=f"{number}번 문제",
            choices=["하나", "둘", "셋", "넷"],
            source_page=number,
            confidence=1.0,
            diagnostics=(),
        )
        for number in (1, 2)
    )

    def fake_parse(path, metadata):
        assert path == question_pdf
        return OfflineParseResult(
            path=path,
            role=DocumentRole.QUESTION,
            metadata=MappingProxyType(dict(metadata)),
            questions=candidates,
            rejected=(),
        )

    monkeypatch.setattr(staging, "parse_offline_question_pdf", fake_parse)
    monkeypatch.setattr(
        staging,
        "_infer_document_metadata",
        lambda path, _root: {
            "exam_type": "해경",
            "subject_name": "항해",
            "year": 2024,
            "session": 2,
            "document_id": path.stem,
        },
    )
    monkeypatch.setattr(
        staging,
        "_resolve_answer_key",
        lambda *_args, **_kwargs: ({1: 1, 2: 2}, answer_pdf),
    )

    staging_db = tmp_path / "build" / "staging.db"
    report_dir = tmp_path / "reports"
    summary = build_staging_database(root, staging_db, report_dir)

    assert summary.inventory_counts == {
        "question": 1,
        "answer": 1,
        "notice": 1,
        "unknown": 0,
        "total": 3,
    }
    assert summary.question_count == 2
    assert summary.answer_count == 2
    assert summary.rejected_count == 0
    assert summary.expected_sets == (_expected(1, 2),)
    assert set(summary.report_paths) == {
        "inventory_json",
        "inventory_csv",
        "rebuild_json",
        "validation_json",
        "validation_csv",
    }
    assert all(Path(path).is_file() for path in summary.report_paths.values())
    validation_payload = json.loads(
        summary.report_paths["validation_json"].read_text(encoding="utf-8")
    )
    assert validation_payload["valid"] is True
    assert "missing_numbers" in summary.report_paths["validation_csv"].read_text(
        encoding="utf-8-sig"
    )

    with sqlite3.connect(staging_db) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM offline_rebuild_documents").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions WHERE source_id IS NOT NULL").fetchone()[0] == 2

    report = validate_staging_database(staging_db, summary.expected_sets)
    assert report.valid is True
    assert report.placeholder_count == 0
    assert report.integrity_check == "ok"
    assert report.schema_valid is True


def test_inventoried_question_pdf_with_no_parsed_set_fails_closed(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    question_pdf = root / "2024_해경_항해_문제.pdf"
    question_pdf.write_bytes(b"synthetic")
    monkeypatch.setattr(
        staging,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(
            path=path,
            role=DocumentRole.QUESTION,
            metadata=MappingProxyType(dict(metadata)),
            questions=(),
            rejected=(),
        ),
    )
    monkeypatch.setattr(
        staging,
        "_infer_document_metadata",
        lambda path, _root: {
            "exam_type": "해경",
            "subject_name": "항해",
            "year": 2024,
            "session": 2,
            "document_id": path.stem,
        },
    )
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({}, None))

    summary = build_staging_database(root, tmp_path / "staging.db", tmp_path / "reports")
    report = validate_staging_database(summary.staging_db, summary.expected_sets)

    assert summary.inventory_counts["question"] == 1
    assert summary.question_count == 0
    assert report.valid is False
    assert "unparsed_question_documents" in report.error_codes


def test_one_failed_question_document_blocks_otherwise_valid_staging(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    good_pdf = root / "2024_해경_항해_문제.pdf"
    failed_pdf = root / "2024_해경_기관_문제.pdf"
    good_pdf.write_bytes(b"good")
    failed_pdf.write_bytes(b"failed")
    candidate = ParsedOfflineQuestion(1, "문제", ["하나", "둘", "셋", "넷"], 1, 1.0, ())

    def fake_parse(path, metadata):
        if path == failed_pdf:
            raise RuntimeError("parse failed")
        return OfflineParseResult(
            path=path,
            role=DocumentRole.QUESTION,
            metadata=MappingProxyType(dict(metadata)),
            questions=(candidate,),
            rejected=(),
        )

    monkeypatch.setattr(staging, "parse_offline_question_pdf", fake_parse)
    monkeypatch.setattr(
        staging,
        "_infer_document_metadata",
        lambda path, _root: {
            "exam_type": "해경",
            "subject_name": "기관" if path == failed_pdf else "항해",
            "year": 2024,
            "session": 2,
            "document_id": path.stem,
        },
    )
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({1: 1}, None))

    summary = build_staging_database(root, tmp_path / "staging.db", tmp_path / "reports")
    report = validate_staging_database(summary.staging_db, summary.expected_sets)

    assert summary.question_count == 1
    assert summary.errors
    assert report.valid is False
    assert "unparsed_question_documents" in report.error_codes


def test_validation_checks_expected_numbers_answers_placeholders_and_provenance(tmp_path):
    staging_db = tmp_path / "staging.db"
    _database(staging_db, [_question(1, answer=0, placeholder=True)], provenance=False)

    report = validate_staging_database(staging_db, [_expected(1, 2)])

    assert report.valid is False
    assert report.placeholder_count == 1
    assert report.missing_provenance_count == 1
    assert report.sets[0].missing_numbers == (2,)
    assert report.sets[0].missing_answers == (1, 2)
    assert {
        "placeholder_choices",
        "missing_question_numbers",
        "missing_answers",
        "missing_provenance",
    }.issubset(set(report.error_codes))


def test_validation_rejects_non_database_and_missing_application_schema(tmp_path):
    invalid = tmp_path / "invalid.db"
    invalid.write_text("not sqlite", encoding="utf-8")
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()

    invalid_report = validate_staging_database(invalid, [])
    empty_report = validate_staging_database(empty, [])

    assert invalid_report.valid is False
    assert "sqlite_error" in invalid_report.error_codes
    assert empty_report.valid is False
    assert empty_report.integrity_check == "ok"
    assert empty_report.schema_valid is False
    assert "application_schema" in empty_report.error_codes


def test_replacement_validation_failure_leaves_mounted_bytes_unchanged(tmp_path):
    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "staging.db"
    _database(mounted, [_question(1)])
    _database(staging_db, [_question(1, placeholder=True)])
    before = mounted.read_bytes()

    with pytest.raises(ReplacementError, match="validation"):
        replace_mounted_database(
            staging_db,
            mounted,
            tmp_path / "backups",
            tmp_path / "receipt.json",
        )

    assert mounted.read_bytes() == before
    assert not (tmp_path / "backups").exists()
    assert not (tmp_path / "receipt.json").exists()


def test_replacement_creates_backup_atomic_receipt_hashes_and_readable_mount(tmp_path):
    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "staging.db"
    _database(mounted, [_question(1)])
    conn = sqlite3.connect(mounted)
    try:
        conn.execute("UPDATE questions SET question_text = '이전 문제'")
        conn.commit()
    finally:
        conn.close()
    _database(staging_db, [_question(1), _question(2)])
    old_hash = _sha256(mounted)
    staging_hash = _sha256(staging_db)

    receipt_path = tmp_path / "receipts" / "replacement.json"
    receipt = replace_mounted_database(
        staging_db,
        mounted,
        tmp_path / "backups",
        receipt_path,
    )

    assert receipt.backup_path.is_file()
    assert _sha256(receipt.backup_path) == old_hash
    assert receipt.previous_sha256 == old_hash
    assert receipt.staging_sha256 == staging_hash
    assert receipt.mounted_sha256 == _sha256(mounted) == staging_hash
    assert receipt.counts["questions"] == 2
    assert receipt.counts["question_choices"] == 8
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["mounted_sha256"] == staging_hash
    assert [row["question_text"] for row in ExamRepository(str(mounted)).search_questions(limit=None)] == [
        "1번 문제",
        "2번 문제",
    ]


def test_atomic_replace_failure_leaves_mounted_unchanged_and_writes_no_receipt(tmp_path, monkeypatch):
    from src.database import staging

    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "staging.db"
    _database(mounted, [_question(1)])
    _database(staging_db, [_question(1), _question(2)])
    before = mounted.read_bytes()

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(staging.os, "replace", fail_replace)

    with pytest.raises(ReplacementError, match="simulated replace failure"):
        replace_mounted_database(
            staging_db,
            mounted,
            tmp_path / "backups",
            tmp_path / "receipt.json",
        )

    assert mounted.read_bytes() == before
    assert not (tmp_path / "receipt.json").exists()


def test_cli_is_dry_run_by_default_and_requires_explicit_replace(tmp_path, monkeypatch):
    from scripts import rebuild_offline_exam_db as cli

    root = tmp_path / "pdfs"
    root.mkdir()
    staging_db = tmp_path / "staging.db"
    mounted = tmp_path / "mounted.db"
    mounted.write_bytes(b"mounted remains")
    calls: list[str] = []
    summary = SimpleNamespace(expected_sets=(), to_dict=lambda: {})
    validation = SimpleNamespace(valid=True, to_dict=lambda: {"valid": True})

    monkeypatch.setattr(cli, "build_staging_database", lambda *_args: calls.append("build") or summary)
    monkeypatch.setattr(cli, "validate_staging_database", lambda *_args: calls.append("validate") or validation)
    monkeypatch.setattr(cli, "replace_mounted_database", lambda *_args: calls.append("replace"))

    common = [
        str(root),
        "--staging-db",
        str(staging_db),
        "--mounted-db",
        str(mounted),
        "--report-dir",
        str(tmp_path / "reports"),
    ]
    assert cli.main(common) == 0
    assert calls == ["build", "validate"]
    assert mounted.read_bytes() == b"mounted remains"

    calls.clear()
    assert cli.main([*common, "--replace"]) == 0
    assert calls == ["build", "validate", "replace"]
