from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from src.database.repository import ExamRepository
from src.database.validator import QuestionValidator
from src.database.staging import (
    ExpectedExamSet,
    InventoryContract,
    RegisteredExamSet,
    STANDALONE_SPECS,
    ReplacementError,
    build_staging_database,
    replace_mounted_database,
    validate_staging_database,
    registered_provider_preflight,
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
            "expected_question_count": 2,
        },
    )
    monkeypatch.setattr(
        staging,
        "_resolve_answer_key",
        lambda *_args, **_kwargs: ({1: 1, 2: 2}, answer_pdf),
    )

    staging_db = tmp_path / "build" / "staging.db"
    report_dir = tmp_path / "reports"
    summary = build_staging_database(root, staging_db, report_dir, inventory_contract=None)

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
            "expected_question_count": 1,
        },
    )
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({}, None))

    summary = build_staging_database(
        root, tmp_path / "staging.db", tmp_path / "reports", inventory_contract=None
    )
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
            "expected_question_count": 1,
        },
    )
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({1: 1}, None))

    summary = build_staging_database(
        root, tmp_path / "staging.db", tmp_path / "reports", inventory_contract=None
    )
    report = validate_staging_database(summary.staging_db, summary.expected_sets)

    assert summary.question_count == 1
    assert summary.errors
    assert report.valid is False
    assert "unparsed_question_documents" in report.error_codes


def test_expected_coverage_comes_from_registered_metadata_not_accepted_output(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    pdf = root / "trusted_문제.pdf"
    pdf.write_bytes(b"trusted")
    candidate = ParsedOfflineQuestion(1, "문제", ["하나", "둘", "셋", "넷"], 1, 1.0, ())
    monkeypatch.setattr(
        staging,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(
            path, DocumentRole.QUESTION, MappingProxyType(dict(metadata)), (candidate,), ()
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
            "expected_question_count": 2,
        },
    )
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({1: 1, 2: 2}, None))

    summary = build_staging_database(
        root, tmp_path / "staging.db", tmp_path / "reports", inventory_contract=None
    )
    report = validate_staging_database(summary.staging_db, summary.expected_sets)

    assert summary.expected_sets[0].question_numbers == (1, 2)
    assert report.valid is False
    assert report.sets[0].missing_numbers == (2,)


def test_registered_provider_preserves_repeated_question_numbers_across_sets(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    first_pdf = root / "first_문제.pdf"
    first_answer = root / "first_정답.pdf"
    second_answer = root / "second_정답.pdf"
    for path in (first_pdf, first_answer, second_answer):
        path.write_bytes(path.name.encode())

    def provider(_root, _reports, _inventory):
        first_question = _question(1)
        first_question.year = 2023
        first_question.session = 1
        second_question = _question(1)
        second_question.year = 2024
        second_question.session = 1
        return (
            RegisteredExamSet(
                ExpectedExamSet("해경", "항해", 2023, 1, (1,)),
                (first_question,),
                first_pdf,
                first_answer,
            ),
            RegisteredExamSet(
                ExpectedExamSet("해경", "항해", 2024, 1, (1,)),
                (second_question,),
                first_pdf,
                second_answer,
            ),
        )

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=InventoryContract(3, 1, 2, 0),
        registered_set_provider=provider,
    )

    with sqlite3.connect(summary.staging_db) as conn:
        assert conn.execute("SELECT question_number FROM questions ORDER BY year").fetchall() == [
            (1,),
            (1,),
        ]
        rows = conn.execute(
            """
            SELECT q.year, q.source_id, qs.attachment_filename
            FROM questions q JOIN question_sources qs ON qs.id = q.source_id
            ORDER BY q.year
            """
        ).fetchall()
        assert rows[0][1] != rows[1][1]
        assert [row[2] for row in rows] == [first_answer.name, second_answer.name]
        conn.execute(
            "UPDATE questions SET source_id = ? WHERE year = 2024",
            (rows[0][1],),
        )

    tampered = validate_staging_database(summary.staging_db, summary.expected_sets)
    assert tampered.valid is False
    assert "provenance_mismatch" in tampered.error_codes


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
            allow_synthetic_rebuild=True,
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
        allow_synthetic_rebuild=True,
    )

    assert receipt.backup_path.is_file()
    assert receipt.previous_sha256 == old_hash
    assert receipt.backup_sha256 == _sha256(receipt.backup_path)
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
            allow_synthetic_rebuild=True,
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


def test_strict_inventory_contract_rejects_partial_corpus_before_staging_write(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    (root / "one_문제.pdf").write_bytes(b"one")
    staging_db = tmp_path / "staging.db"
    staging_db.write_bytes(b"preserve me")

    with pytest.raises(ValueError, match="inventory mismatch"):
        build_staging_database(root, staging_db, tmp_path / "reports")

    assert staging_db.read_bytes() == b"preserve me"
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("alias", ["mounted", "staging", "backup"])
def test_replacement_rejects_receipt_path_aliases_before_writes(tmp_path, alias):
    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "staging.db"
    backup_dir = tmp_path / "backups"
    _database(mounted, [_question(1)])
    _database(staging_db, [_question(1)])
    before = mounted.read_bytes()
    aliases = {"mounted": mounted, "staging": staging_db, "backup": backup_dir}

    with pytest.raises(ReplacementError, match="alias"):
        replace_mounted_database(staging_db, mounted, backup_dir, aliases[alias])

    assert mounted.read_bytes() == before
    assert not backup_dir.exists()


def test_validation_rejects_nonblank_stem_choice_structure_and_sequence(tmp_path):
    path = tmp_path / "invalid-structure.db"
    _database(path, [_question(1)])
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE questions SET question_text = '   '")
        conn.execute(
            "UPDATE question_choices SET choice_text = '' WHERE choice_number = 2"
        )
        conn.execute(
            "UPDATE question_choices SET choice_number = 5 WHERE choice_number = 4"
        )

    report = validate_staging_database(path, [_expected(1)])

    assert report.valid is False
    assert "invalid_question_structure" in report.error_codes


def test_validation_rejects_provenance_not_matching_inventory(tmp_path):
    path = tmp_path / "provenance.db"
    _database(path, [_question(1)])
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE offline_rebuild_documents (
                relative_path TEXT PRIMARY KEY, role TEXT, sha256 TEXT, size INTEGER,
                parsed_question_count INTEGER DEFAULT 0, build_error TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO offline_rebuild_documents VALUES (?, ?, ?, 1, 1, NULL)",
            [
                ("question.pdf", "question", "b" * 64),
                ("answer.pdf", "answer", "c" * 64),
            ],
        )
        conn.execute(
            """
            UPDATE question_sources
            SET source_url = 'file:///wrong.pdf', content_hash = ?,
                attachment_url = 'file:///missing-answer.pdf',
                attachment_filename = 'missing-answer.pdf'
            """,
            ("d" * 64,),
        )

    report = validate_staging_database(path, [_expected(1)])

    assert report.valid is False
    assert "provenance_mismatch" in report.error_codes


def test_sqlite_backup_includes_committed_wal_rows(tmp_path):
    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "staging.db"
    _database(mounted, [_question(1)])
    _database(staging_db, [_question(1), _question(2)])
    writer = sqlite3.connect(mounted)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("UPDATE questions SET question_text = 'WAL 최신값'")
    writer.commit()
    try:
        with pytest.raises(ReplacementError, match="access|액세스|process|프로세스"):
            replace_mounted_database(
                staging_db, mounted, tmp_path / "backups", tmp_path / "receipt.json"
                , allow_synthetic_rebuild=True
            )
    finally:
        writer.close()

    backups = list((tmp_path / "backups").glob("*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT question_text FROM questions").fetchone()[0] == "WAL 최신값"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_no_source_answer_registered_set_uses_canonical_sentinel_and_explicit_state(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    source = root / "engineering_문제.pdf"
    source.write_bytes(b"question")
    question = _question(1)
    question.correct_answer = 0
    question.answer_available = False
    for choice, symbol in zip(question.choices, ("㉮", "㉯", "㉴", "㉵")):
        choice.symbol = symbol

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=InventoryContract(1, 1, 0, 0),
        registered_set_provider=lambda *_args: (
            RegisteredExamSet(
                ExpectedExamSet(
                    "해양경찰 경찰직 기관학",
                    "기관학",
                    2020,
                    1,
                    (1,),
                    require_answers=False,
                ),
                (question,),
                source,
                None,
            ),
        ),
    )

    with sqlite3.connect(summary.staging_db) as conn:
        assert conn.execute("SELECT correct_answer FROM questions").fetchone()[0] == 0
        assert conn.execute("SELECT answer_available FROM questions").fetchone()[0] == 0
        correct_answer_column = next(
            row for row in conn.execute("PRAGMA table_info(questions)") if row[1] == "correct_answer"
        )
        assert correct_answer_column[3] == 1
        assert conn.execute(
            "SELECT answer_state, answer_relative_path FROM offline_rebuild_set_provenance"
        ).fetchone() == ("not_required", None)
    findings = QuestionValidator(ExamRepository(str(summary.staging_db))).scan()
    assert all(
        issue["code"] != "invalid_correct_answer"
        for finding in findings
        for issue in finding["issues"]
    )


def test_native_2023_specs_are_explicit_distinct_official_associations():
    assert {spec.subject_name for spec in STANDALONE_SPECS} == {"물리", "항해"}
    assert {spec.exam_type for spec in STANDALONE_SPECS} == {"해양경찰 일반직 9급"}
    assert {(spec.year, spec.session) for spec in STANDALONE_SPECS} == {(2023, 2)}
    assert len({spec.answer_filename for spec in STANDALONE_SPECS}) == 2
    assert len({spec.official_key for spec in STANDALONE_SPECS}) == 2


def test_real_provider_preflight_enumerates_registered_contract_without_ocr():
    report = registered_provider_preflight()

    assert report["set_count"] == 135
    assert report["question_count"] == 3280
    assert report["engineering_no_answer_sets"] == 1
    assert report["standalone_sets"] == 2
    assert report["missing_answer_associations"] == 0


def test_production_build_runs_registration_preflight_before_provider_or_writes(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    for index in range(12):
        (root / f"q{index}_문제.pdf").write_bytes(b"q")
    for index in range(15):
        (root / f"a{index}_정답.pdf").write_bytes(b"a")
    for index in range(3):
        (root / f"n{index}_채용시험_공고.pdf").write_bytes(b"n")
    events = []

    def fail_preflight():
        events.append("preflight")
        raise RuntimeError("registration preflight failed")

    def provider(*_args):
        events.append("provider")
        return ()

    monkeypatch.setattr(staging, "registered_provider_preflight", fail_preflight)

    with pytest.raises(RuntimeError, match="preflight"):
        build_staging_database(
            root,
            tmp_path / "staging.db",
            tmp_path / "reports",
            registered_set_provider=provider,
        )

    assert events == ["preflight"]
    assert not (tmp_path / "staging.db").exists()


def test_plain_database_is_not_replaceable_without_explicit_synthetic_trust(tmp_path):
    mounted = tmp_path / "mounted.db"
    staging_db = tmp_path / "plain.db"
    _database(mounted, [_question(1)])
    _database(staging_db, [_question(1)])
    before = mounted.read_bytes()

    with pytest.raises(ReplacementError, match="rebuild metadata"):
        replace_mounted_database(
            staging_db, mounted, tmp_path / "backups", tmp_path / "receipt.json"
        )

    assert mounted.read_bytes() == before
    assert not (tmp_path / "backups").exists()
