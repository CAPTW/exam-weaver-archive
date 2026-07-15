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
from src.parser.offline_sources import (
    DocumentRole,
    OfflineParseResult,
    RejectedOfflineQuestion,
)
from src.parser.question import Choice, Question


def _question(number: int, *, answer: int = 1, placeholder: bool = False) -> Question:
    symbols = ("㉮", "㉯", "㉴", "㉵")
    choices = [
        Choice(
            number=index,
            symbol=symbols[index - 1],
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


def test_applies_exact_source_repairs_transactionally_to_staging_database(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "staging.db"
    _database(database, [_question(1)])
    repairs = tmp_path / "repairs.json"
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "subject": "항해",
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 1,
                        "repaired_stem": "원문에서 확인한 발문은?",
                        "repaired_choices": ["갑", "을", "병", "정"],
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = apply_audited_repairs(database, repairs)

    assert result.applied_records == 1
    with sqlite3.connect(database) as connection:
        question_id, stem = connection.execute(
            "SELECT id, question_text FROM questions"
        ).fetchone()
        choices = [
            row[0]
            for row in connection.execute(
                "SELECT choice_text FROM question_choices "
                "WHERE question_id = ? ORDER BY choice_number",
                (question_id,),
            )
        ]
    assert stem == "원문에서 확인한 발문은?"
    assert choices == ["갑", "을", "병", "정"]


def test_applies_legacy_repairs_by_exam_and_subject_code_with_missing_page(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "legacy.db"
    _database(database, [_question(1)])
    with sqlite3.connect(database) as connection:
        question_id, subject_code, exam_code = connection.execute(
            """
            SELECT q.id, s.code, e.code
            FROM questions q
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN subjects s ON s.id = es.subject_id
            JOIN exams e ON e.id = es.exam_id
            """
        ).fetchone()
        connection.execute(
            "UPDATE questions SET source_page = NULL WHERE id = ?", (question_id,)
        )
        other_exam_id = connection.execute(
            "INSERT INTO exams (code, name) VALUES ('다른시험', '다른 시험')"
        ).lastrowid
        subject_id = connection.execute(
            "SELECT id FROM subjects WHERE code = ?", (subject_code,)
        ).fetchone()[0]
        other_exam_subject_id = connection.execute(
            """
            INSERT INTO exam_subjects (exam_id, subject_id, display_order)
            VALUES (?, ?, 1)
            """,
            (other_exam_id, subject_id),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO questions (
                exam_subject_id, year, session, question_number,
                question_text, correct_answer, source_page
            ) VALUES (?, 2024, 2, 1, '다른 시험의 같은 번호', 1, NULL)
            """,
            (other_exam_subject_id,),
        )

    repairs = tmp_path / "repairs.json"
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "exam_code": exam_code,
                        "subject_code": subject_code,
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 33,
                        "repaired_stem": "원문으로 복구한 발문",
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = apply_audited_repairs(database, repairs)

    assert result.applied_records == 1
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT question_text, source_page FROM questions ORDER BY id"
        ).fetchall()
    assert rows == [("원문으로 복구한 발문", 33), ("다른 시험의 같은 번호", None)]


def test_builds_maritime_repair_bundle_from_partial_exact_source_fields(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "legacy.db"
    _database(database, [_question(1)])
    with sqlite3.connect(database) as connection:
        question_id = connection.execute("SELECT id FROM questions").fetchone()[0]
    audit = tmp_path / "navigation.json"
    audit.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": question_id,
                        "status": "confirmed",
                        "source_filename": "2024/source.pdf",
                        "source_page": 7,
                        "exact_source_value": {
                            "question_text": "원문 발문",
                            "choice_2": "원문 둘째 선지",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "bundle.json"

    payload = build_bundle(database, [audit], output)

    assert payload["repairs"] == [
        {
            "exam_code": "해경",
            "subject_code": "navigation",
            "year": 2024,
            "session": 2,
            "question_number": 1,
            "source_page": 7,
            "expected_current_source_page": 1,
            "source_pdf_relative_path": "2024/source.pdf",
            "repaired_stem": "원문 발문",
            "repaired_choices": ["선지 1", "원문 둘째 선지", "선지 3", "선지 4"],
            "confidence": "exact_source",
        }
    ]
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_exact_source_repairs_correct_audited_source_page_idempotently(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "wrong-source-page.db"
    _database(database, [_question(1)])
    repairs = tmp_path / "source-page-repairs.json"
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "subject": "항해",
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 13,
                        "expected_current_source_page": 1,
                        "repaired_stem": "원문 발문",
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = apply_audited_repairs(database, repairs)
    second = apply_audited_repairs(database, repairs)

    assert first.changed_source_pages == 1
    assert second.changed_source_pages == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT source_page FROM questions").fetchone()[0] == 13


def test_exact_source_repairs_restore_missing_choice_rows(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "missing-choice.db"
    _database(database, [_question(1)])
    with sqlite3.connect(database) as connection:
        question_id = connection.execute("SELECT id FROM questions").fetchone()[0]
        connection.execute(
            "DELETE FROM question_choices WHERE question_id = ? AND choice_number = 1",
            (question_id,),
        )
    repairs = tmp_path / "repairs.json"
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "subject": "항해",
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 1,
                        "repaired_choices": ["원문 1", "원문 2", "원문 3", "원문 4"],
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    apply_audited_repairs(database, repairs)

    with sqlite3.connect(database) as connection:
        choices = connection.execute(
            """
            SELECT choice_number, choice_symbol, choice_text
            FROM question_choices WHERE question_id = ? ORDER BY choice_number
            """,
            (question_id,),
        ).fetchall()
    assert choices == [
        (1, "㉮", "원문 1"),
        (2, "㉯", "원문 2"),
        (3, "㉴", "원문 3"),
        (4, "㉵", "원문 4"),
    ]


def test_exact_source_repairs_restore_image_only_choice_rows(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "missing-image-choices.db"
    _database(database, [_question(1)])
    with sqlite3.connect(database) as connection:
        question_id = connection.execute("SELECT id FROM questions").fetchone()[0]
        connection.execute(
            "DELETE FROM question_choices WHERE question_id = ?", (question_id,)
        )
    repairs = tmp_path / "image-repairs.json"
    image_paths = [f"data/extracted/repairs/q1_choice_{number}.png" for number in range(1, 5)]
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "subject": "항해",
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 1,
                        "repaired_choices": ["", "", "", ""],
                        "repaired_choice_image_paths": image_paths,
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    apply_audited_repairs(database, repairs)

    with sqlite3.connect(database) as connection:
        choices = connection.execute(
            """
            SELECT choice_number, choice_text, choice_image_path
            FROM question_choices WHERE question_id = ? ORDER BY choice_number
            """,
            (question_id,),
        ).fetchall()
    assert choices == [
        (number, "", image_paths[number - 1]) for number in range(1, 5)
    ]


def test_builds_maritime_bundle_for_image_only_choices(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "legacy-images.db"
    _database(database, [_question(1)])
    with sqlite3.connect(database) as connection:
        question_id = connection.execute("SELECT id FROM questions").fetchone()[0]
        connection.execute(
            "DELETE FROM question_choices WHERE question_id = ?", (question_id,)
        )
    image_paths = [f"data/extracted/repairs/q1_choice_{number}.png" for number in range(1, 5)]
    audit = tmp_path / "image-audit.json"
    audit.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": question_id,
                        "status": "confirmed",
                        "source_filename": "2024/source.pdf",
                        "source_page": 7,
                        "exact_source_value": {"choice_image_paths": image_paths},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_bundle(database, [audit], tmp_path / "bundle.json")

    repair = payload["repairs"][0]
    assert repair["repaired_choices"] == ["", "", "", ""]
    assert repair["repaired_choice_image_paths"] == image_paths


def test_exact_source_repairs_restore_question_image(tmp_path):
    from src.database.ocr_repairs import apply_audited_repairs

    database = tmp_path / "question-image.db"
    _database(database, [_question(1)])
    repairs = tmp_path / "question-image-repairs.json"
    image_path = "data/extracted/images/ocr_repairs/1/question.png"
    repairs.write_text(
        json.dumps(
            {
                "repairs": [
                    {
                        "subject": "항해",
                        "year": 2024,
                        "session": 2,
                        "question_number": 1,
                        "source_page": 1,
                        "repaired_question_image_path": image_path,
                        "confidence": "exact_source",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = apply_audited_repairs(database, repairs)

    assert result.changed_question_images == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT has_image, image_path FROM questions"
        ).fetchone() == (1, image_path)


def test_builds_maritime_bundle_with_question_image(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "legacy-question-image.db"
    _database(database, [_question(1)])
    image_path = "data/extracted/images/ocr_repairs/1/question.png"
    audit = tmp_path / "question-image-audit.json"
    audit.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": 1,
                        "status": "confirmed",
                        "source_filename": "2024/source.pdf",
                        "source_page": 7,
                        "exact_source_value": {
                            "question_image_path": image_path,
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_bundle(database, [audit], tmp_path / "bundle.json")

    assert payload["repairs"][0]["repaired_question_image_path"] == image_path


def test_builds_maritime_bundle_from_nested_visual_audit_schema(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "nested-visual-audit.db"
    _database(database, [_question(1)])
    audit = tmp_path / "nested-visual-audit.json"
    audit.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": 1,
                        "status": "confirmed",
                        "source_evidence": {
                            "source_pdf": "E:/corpus/0. 기출문제 모음/2019/source.pdf",
                            "source_page": 7,
                        },
                        "exact_source_value": {
                            "question_text": "원문 발문",
                            "choices": [
                                {"choice_number": number, "choice_text": f"원문 {number}"}
                                for number in range(1, 5)
                            ],
                            "choice_image_crops": [
                                {
                                    "choice_number": number,
                                    "path": f"data/extracted/repairs/choice_{number}.png",
                                }
                                for number in range(1, 5)
                            ],
                            "source_figure_crop": "data/extracted/repairs/question.png",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_bundle(database, [audit], tmp_path / "bundle.json")

    repair = payload["repairs"][0]
    assert repair["source_pdf_relative_path"] == "2019/source.pdf"
    assert repair["source_page"] == 7
    assert repair["repaired_stem"] == "원문 발문"
    assert repair["repaired_choices"] == ["원문 1", "원문 2", "원문 3", "원문 4"]
    assert repair["repaired_choice_image_paths"] == [
        f"data/extracted/repairs/choice_{number}.png" for number in range(1, 5)
    ]
    assert repair["repaired_question_image_path"] == "data/extracted/repairs/question.png"


def test_maritime_bundle_merges_compatible_duplicate_audits(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "duplicate-audits.db"
    _database(database, [_question(1)])
    common = {
        "id": 1,
        "status": "confirmed",
        "source_filename": "2024/source.pdf",
        "source_page": 1,
    }
    stem_audit = tmp_path / "stem.json"
    stem_audit.write_text(
        json.dumps(
            {
                "records": [
                    {**common, "exact_source_value": {"question_text": "정확 발문"}}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    choice_audit = tmp_path / "choices.json"
    choice_audit.write_text(
        json.dumps(
            {
                "records": [
                    {**common, "exact_source_value": {"choices": ["가", "나", "다", "라"]}}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    spacing_audit = tmp_path / "spacing.json"
    spacing_audit.write_text(
        json.dumps(
            {
                "records": [
                    {**common, "exact_source_value": {"question_text": "정확   발문"}}
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = build_bundle(
        database,
        [stem_audit, spacing_audit, choice_audit],
        tmp_path / "bundle.json",
    )

    assert len(payload["repairs"]) == 1
    assert payload["repairs"][0]["repaired_stem"] == "정확 발문"
    assert payload["repairs"][0]["repaired_choices"] == ["가", "나", "다", "라"]


def test_maritime_bundle_rejects_conflicting_duplicate_audits(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "conflicting-audits.db"
    _database(database, [_question(1)])
    audits = []
    for index, stem in enumerate(("원문 A", "원문 B"), start=1):
        audit = tmp_path / f"audit-{index}.json"
        audit.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "id": 1,
                            "status": "confirmed",
                            "source_filename": "2024/source.pdf",
                            "source_page": 1,
                            "exact_source_value": {"question_text": stem},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        audits.append(audit)

    with pytest.raises(ValueError, match="conflicting duplicate audited repair"):
        build_bundle(database, audits, tmp_path / "bundle.json")


def test_maritime_bundle_can_explicitly_prefer_later_direct_source_audit(tmp_path):
    from scripts.build_maritime_source_repairs import build_bundle

    database = tmp_path / "superseding-audits.db"
    _database(database, [_question(1)])
    audits = []
    for index, stem in enumerate(("이전 감사값", "재대조한 원문"), start=1):
        audit = tmp_path / f"audit-{index}.json"
        audit.write_text(
            json.dumps(
                {
                    "records": [
                        {
                            "id": 1,
                            "status": "confirmed",
                            "source_filename": "2024/source.pdf",
                            "source_page": 1,
                            "exact_source_value": {"question_text": stem},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        audits.append(audit)

    payload = build_bundle(
        database,
        audits,
        tmp_path / "bundle.json",
        prefer_later_audit=True,
    )

    assert payload["repairs"][0]["repaired_stem"] == "재대조한 원문"


def test_registered_provider_reuses_preparsed_source_pages(tmp_path):
    from src.database.staging import _registered_parser_from_cache

    source = tmp_path / "questions.pdf"
    cached = object()
    calls = []

    def fallback(path, metadata):
        calls.append((path, metadata))
        return object()

    parser = _registered_parser_from_cache(
        {str(source.resolve()): cached}, fallback
    )

    assert parser(source, {"subject_name": "해사영어"}) is cached
    assert calls == []


def test_build_inventories_documents_writes_reports_schema_and_provenance(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    question_pdf = root / "2024_해경_항해_문제.pdf"
    answer_pdf = root / "2024_해경_항해_정답.pdf"
    notice_pdf = root / "2024_해양경찰_채용시험_공고.pdf"
    for path in (question_pdf, answer_pdf, notice_pdf):
        path.write_bytes(path.name.encode("utf-8"))
    auxiliary_pdfs = (
        root / "tmp" / "reference.pdf",
        root / "output" / "pdf" / "generated-study-guide.pdf",
        root / "references" / "source_pdfs" / "supporting-reference.pdf",
    )
    for auxiliary_pdf in auxiliary_pdfs:
        auxiliary_pdf.parent.mkdir(parents=True, exist_ok=True)
        auxiliary_pdf.write_bytes(b"not part of the registered corpus")

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
        "quarantine_json",
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
        conn.execute("UPDATE question_sources SET provider = 'evil' WHERE id = ?", (rows[0][1],))

    tampered = validate_staging_database(summary.staging_db, summary.expected_sets)
    assert tampered.valid is False
    assert "provenance_mismatch" in tampered.error_codes


def test_validation_checks_expected_numbers_answers_placeholders_and_provenance(tmp_path):
    staging_db = tmp_path / "staging.db"
    _database(staging_db, [_question(1, answer=1, placeholder=True)], provenance=False)
    with sqlite3.connect(staging_db) as conn:
        conn.execute("UPDATE questions SET correct_answer = 0")

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


def test_staging_quality_gate_blocks_persisted_ocr_corruption(tmp_path):
    staging_db = tmp_path / "staging.db"
    _database(staging_db, [_question(1)])
    with sqlite3.connect(staging_db) as connection:
        connection.execute(
            "UPDATE questions SET question_text = ? WHERE question_number = 1",
            ("깨진 0卜 문장",),
        )

    report = validate_staging_database(staging_db, [_expected(1)])

    assert report.valid is False
    assert "quality_gate_findings" in report.error_codes
    assert report.quality_findings[0].issue_codes == ("ocr_noise_text",)


def test_build_records_rejected_candidate_details_and_report(tmp_path, monkeypatch):
    from src.database import staging

    root = tmp_path / "pdfs"
    root.mkdir()
    question_pdf = root / "2024_해경_항해_문제.pdf"
    question_pdf.write_bytes(b"synthetic")
    accepted = ParsedOfflineQuestion(
        1,
        "정상 발문",
        ["하나", "둘", "셋", "넷"],
        1,
        1.0,
        (),
    )
    rejected_question = ParsedOfflineQuestion(
        2,
        "격리 발문",
        ["깨진 선지→ →", "둘", "셋", "넷"],
        3,
        0.95,
        ("source_text_repair",),
    )
    monkeypatch.setattr(
        staging,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(
            path=path,
            role=DocumentRole.QUESTION,
            metadata=MappingProxyType(dict(metadata)),
            questions=(accepted,),
            rejected=(
                RejectedOfflineQuestion(rejected_question, ("suspicious_choice",)),
            ),
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
    monkeypatch.setattr(staging, "_resolve_answer_key", lambda *_args: ({1: 1}, None))

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=None,
    )

    with sqlite3.connect(summary.staging_db) as connection:
        row = connection.execute(
            "SELECT reason_codes_json, stem, source_page, choices_json "
            "FROM offline_rebuild_quarantine"
        ).fetchone()
    assert json.loads(row[0]) == ["suspicious_choice"]
    assert row[1:3] == ("격리 발문", 3)
    assert json.loads(row[3])[0] == "깨진 선지→ →"
    payload = json.loads(
        summary.report_paths["quarantine_json"].read_text(encoding="utf-8")
    )
    assert payload["parser_rejections"][0]["reason_codes"] == ["suspicious_choice"]
    assert payload["parser_rejections"][0]["question_number"] == 2


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


def test_replacement_preserves_integrity_valid_legacy_mounted_database(tmp_path):
    mounted = tmp_path / "legacy-mounted.db"
    connection = sqlite3.connect(mounted)
    try:
        connection.execute("CREATE TABLE legacy_state (value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_state VALUES ('이전 사용자 데이터')")
        connection.commit()
    finally:
        connection.close()
    staging_db = tmp_path / "staging.db"
    _database(staging_db, [_question(1)])

    receipt = replace_mounted_database(
        staging_db,
        mounted,
        tmp_path / "backups",
        tmp_path / "receipt.json",
        allow_synthetic_rebuild=True,
    )

    with sqlite3.connect(receipt.backup_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT value FROM legacy_state").fetchone()[0] == "이전 사용자 데이터"
    assert ExamRepository(str(mounted)).search_questions(limit=1)[0]["question_text"] == "1번 문제"


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
    question.exam_type = "해양경찰 경찰직 기관학"
    question.subject_name = "기관학"
    question.year = 2020
    question.session = 1
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
    assert summary.expected_sets[0].require_answers is False
    validation = validate_staging_database(summary.staging_db, summary.expected_sets)
    assert validation.valid is True
    assert validation.sets[0].missing_answers == ()
    findings = QuestionValidator(ExamRepository(str(summary.staging_db))).scan()
    assert all(
        issue["code"] != "invalid_correct_answer"
        for finding in findings
        for issue in finding["issues"]
    )


def test_answer_required_registered_set_builds_with_matching_provenance(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    source = root / "required_문제.pdf"
    answer = root / "required_정답.pdf"
    source.write_bytes(b"question")
    answer.write_bytes(b"answer")
    question = _question(1)
    question.exam_type = "해경"
    question.subject_name = "항해"
    question.year = 2024
    question.session = 1

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=InventoryContract(2, 1, 1, 0),
        registered_set_provider=lambda *_args: (
            RegisteredExamSet(
                ExpectedExamSet("해경", "항해", 2024, 1, (1,)),
                (question,),
                source,
                answer,
            ),
        ),
    )

    validation = validate_staging_database(summary.staging_db, summary.expected_sets)
    assert validation.valid is True
    assert validation.sets[0].missing_answers == ()


def test_answer_required_set_accepts_explicit_source_unavailable_question(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    source = root / "truncated_문제.pdf"
    answer = root / "truncated_정답.pdf"
    source.write_bytes(b"question")
    answer.write_bytes(b"answer")
    question = _question(1)
    question.correct_answer = 0
    question.answer_available = False
    question.tags = "#source_unavailable_choices,#answer_missing_in_source"

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=InventoryContract(2, 1, 1, 0),
        registered_set_provider=lambda *_args: (
            RegisteredExamSet(
                ExpectedExamSet("해경", "항해", 2024, 2, (1,)),
                (question,),
                source,
                answer,
            ),
        ),
    )

    validation = validate_staging_database(summary.staging_db, summary.expected_sets)

    assert validation.valid is True
    assert validation.sets[0].missing_answers == ()


def test_answer_required_registered_set_accepts_official_all_choices_answer(tmp_path):
    root = tmp_path / "pdfs"
    root.mkdir()
    source = root / "all-correct_문제.pdf"
    answer = root / "all-correct_정답.pdf"
    source.write_bytes(b"question")
    answer.write_bytes(b"answer")
    question = _question(1, answer=-1)

    summary = build_staging_database(
        root,
        tmp_path / "staging.db",
        tmp_path / "reports",
        inventory_contract=InventoryContract(2, 1, 1, 0),
        registered_set_provider=lambda *_args: (
            RegisteredExamSet(
                ExpectedExamSet("해경", "항해", 2024, 2, (1,)),
                (question,),
                source,
                answer,
            ),
        ),
    )

    validation = validate_staging_database(summary.staging_db, summary.expected_sets)
    assert validation.valid is True
    assert validation.sets[0].missing_answers == ()
    assert summary.answer_count == 1
    with sqlite3.connect(summary.staging_db) as connection:
        assert connection.execute(
            "SELECT correct_answer, answer_available FROM questions"
        ).fetchone() == (-1, 1)


def test_native_2023_specs_are_explicit_distinct_official_associations():
    assert {spec.subject_name for spec in STANDALONE_SPECS} == {"물리", "항해"}
    assert {spec.exam_type for spec in STANDALONE_SPECS} == {"해양경찰 일반직 9급"}
    assert {(spec.year, spec.session) for spec in STANDALONE_SPECS} == {(2023, 2)}
    assert len({spec.answer_filename for spec in STANDALONE_SPECS}) == 2
    assert len({spec.official_key for spec in STANDALONE_SPECS}) == 2


def test_standalone_explanation_answer_key_supports_split_answer_marker():
    from src.database.staging import _parse_explanation_answer_key

    lines = [
        "1. 【정답】 ④",
        "해설 문장",
        "2. 【정답】",
        "①",
        "① 첫 번째 선지 해설",
        "3. 【정답】 ②",
    ]

    assert _parse_explanation_answer_key(lines, (1, 2, 3)) == {
        1: 4,
        2: 1,
        3: 2,
    }


def test_standalone_subject_table_selects_exact_subject_from_multi_subject_key():
    from src.database.staging import _parse_subject_answer_table

    lines = [
        "□ 항해술",
        "1 ③ 2 ① 3 ④",
        "□ 항해",
        "1 ① 2 ③ 3 ②",
        "□ 선박기관",
        "1 ④ 2 ④ 3 ④",
    ]

    assert _parse_subject_answer_table(lines, "항해", (1, 2, 3)) == {
        1: 1,
        2: 3,
        3: 2,
    }


def test_standalone_subject_table_rejects_conflicting_duplicate_subject_sections():
    from src.database.staging import _parse_subject_answer_table

    lines = [
        "□ 항해",
        "1 ① 2 ③ 3 ②",
        "[다른 직렬]",
        "□ 항해",
        "1 ① 2 ④ 3 ②",
    ]

    assert _parse_subject_answer_table(lines, "항해", (1, 2, 3)) == {}


def test_real_provider_preflight_enumerates_registered_contract_without_ocr():
    report = registered_provider_preflight()

    assert report["set_count"] == 135
    assert report["question_count"] == 3280
    assert report["engineering_no_answer_sets"] == 1
    assert report["required_answer_sets"] == 134
    assert report["standalone_sets"] == 2
    assert report["missing_answer_associations"] == 0


def test_registered_answer_path_treats_bracketed_filename_as_literal(tmp_path):
    from src.database.staging import _registered_answer_path

    answer_name = "[기출정답]해사법규(24년-13년).pdf"
    answer_dir = tmp_path / "정답안"
    answer_dir.mkdir()
    expected = answer_dir / answer_name
    expected.write_bytes(b"answer")
    module = SimpleNamespace(
        __name__="scripts.import_maritime_law_pdf",
        ANSWER_FILENAMES={"archive": answer_name},
        ANSWER_KEYS={"archive": ["archive-key"]},
    )

    actual = _registered_answer_path(
        module, {"answer_key": "archive-key"}, 1, tmp_path,
    )

    assert actual == expected


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

    def provider(*_args):
        events.append("provider")
        return ()

    with pytest.raises(ValueError, match="preflight"):
        build_staging_database(
            root,
            tmp_path / "staging.db",
            tmp_path / "reports",
            registered_set_provider=provider,
        )

    assert events == []
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
