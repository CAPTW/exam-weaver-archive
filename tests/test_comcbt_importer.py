import hashlib
from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from scripts import comcbt_crawl
from src.database.repository import ExamRepository
from src.parser.question import Choice, Question
from src.web_import.importer import (
    ComcbtImportService,
    QuestionSource,
    QuestionSourceRegistry,
    sha256_file,
)
from src.web_import.models import ComcbtParsedExam, ComcbtQuestionGroup


def test_sha256_file_returns_expected_digest(tmp_path: Path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"abc")

    assert sha256_file(payload) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_question_source_registry_records_new_and_detects_existing(tmp_path: Path):
    registry = QuestionSourceRegistry(tmp_path / "exam.db")
    source = QuestionSource(
        provider="comcbt",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        document_id="8837719",
        attachment_url="https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1",
        attachment_filename="시험(교사용).pdf",
        content_hash="abc123",
        fetched_at="2026-06-29T00:00:00+00:00",
    )

    created = registry.register(source)
    existing = registry.register(replace(source, fetched_at="2026-06-29T00:01:00+00:00"))

    assert created.existing is False
    assert existing.existing is True
    assert existing.source_id == created.source_id


def test_repository_ignores_comcbt_group_metadata_fields(tmp_path: Path):
    db_path = tmp_path / "exam.db"
    repo = ExamRepository(str(db_path))
    repo.init_database()
    question = Question(
        number=1,
        text="공통지문 연결 문항",
        choices=[
            Choice(number=1, symbol="㉮", text="A"),
            Choice(number=2, symbol="㉯", text="B"),
            Choice(number=3, symbol="㉴", text="C"),
            Choice(number=4, symbol="㉵", text="D"),
        ],
        correct_answer=1,
        subject_name="자료 해석",
        year=2025,
        session=1,
        exam_type="Sample Exam",
        group_id="group-1",
        group_order=1,
        shared_passage="공통지문",
    )

    assert repo.save_questions([question], question) == 1


def _source() -> QuestionSource:
    return QuestionSource(
        provider="comcbt",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        document_id="8837719",
        attachment_url="https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1",
        attachment_filename="시험(교사용).pdf",
        content_hash="abc123",
        fetched_at="2026-06-29T00:00:00+00:00",
    )


def _grouped_exam() -> ComcbtParsedExam:
    group = ComcbtQuestionGroup(
        group_id="group-1",
        text="공통 지문",
        child_numbers=[1, 2],
        range_start=1,
        range_end=2,
        explicit_range=True,
        ambiguous_range=False,
        source_page=3,
    )
    questions = [
        Question(
            number=1,
            text="첫 번째 공통 문항",
            choices=[
                Choice(number=1, symbol="㉮", text="A"),
                Choice(number=2, symbol="㉯", text="B"),
                Choice(number=3, symbol="㉴", text="C"),
                Choice(number=4, symbol="㉵", text="D"),
            ],
            correct_answer=1,
            subject_name="자료 해석",
            year=2025,
            session=1,
            exam_type="Sample Exam",
            group_id="group-1",
            group_order=1,
            shared_passage="공통 지문",
            source_page=4,
        ),
        Question(
            number=2,
            text="두 번째 공통 문항",
            choices=[
                Choice(number=1, symbol="㉮", text="A"),
                Choice(number=2, symbol="㉯", text="B"),
                Choice(number=3, symbol="㉴", text="C"),
                Choice(number=4, symbol="㉵", text="D"),
            ],
            correct_answer=2,
            subject_name="자료 해석",
            year=2025,
            session=1,
            exam_type="Sample Exam",
            group_id="group-1",
            group_order=2,
            shared_passage="공통 지문",
            source_page=4,
        ),
    ]
    return ComcbtParsedExam(
        title="Sample",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        exam_type="Sample Exam",
        subject_name="자료 해석",
        year=2025,
        session=1,
        questions=questions,
        attachments=[],
        groups=[group],
        diagnostics={"invalid_group_range": False, "ambiguous_group_range": False},
    )


def test_import_service_inserts_source_group_questions_and_exposes_readback(tmp_path: Path):
    db_path = tmp_path / "exam.db"
    report_path = tmp_path / "quality.json"
    result = ComcbtImportService(db_path).import_exam(
        parsed_exam=_grouped_exam(),
        source=_source(),
        quality_report_path=report_path,
    )

    assert result.status == "imported"
    assert result.importable is True
    assert result.saved == 2
    assert result.skipped is False
    assert result.source_id is not None
    assert report_path.exists()

    repo = ExamRepository(str(db_path))
    questions = repo.get_questions_with_choices(
        exam_code="Sample Exam",
        year=2025,
        session=1,
        limit=None,
    )

    assert [question["question_number"] for question in questions] == [1, 2]
    assert questions[0]["source_id"] == result.source_id
    assert questions[0]["source_question_id"] == "8837719:1"
    assert questions[0]["group_order"] == 1
    assert questions[0]["group_shared_text"] == "공통 지문"
    assert questions[0]["shared_passage"] == "공통 지문"
    assert [choice["number"] for choice in questions[0]["choices"]] == [1, 2, 3, 4]

    detail = repo.get_question(questions[1]["id"])
    assert detail["source_question_id"] == "8837719:2"
    assert detail["group_order"] == 2
    assert detail["group_shared_text"] == "공통 지문"

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_choices").fetchone()[0] == 8


def test_import_service_skips_duplicate_source_without_duplicating_rows(tmp_path: Path):
    db_path = tmp_path / "exam.db"
    service = ComcbtImportService(db_path)
    first = service.import_exam(parsed_exam=_grouped_exam(), source=_source())
    second = service.import_exam(parsed_exam=_grouped_exam(), source=replace(_source(), fetched_at="2026-06-29T00:01:00+00:00"))

    assert first.status == "imported"
    assert second.status == "skipped_duplicate"
    assert second.skipped is True
    assert second.saved == 0
    assert second.source_id == first.source_id

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM question_choices").fetchone()[0] == 8


def test_import_service_rolls_back_source_and_questions_when_metadata_attach_fails(tmp_path: Path):
    db_path = tmp_path / "exam.db"

    class FailingAttachService(ComcbtImportService):
        def _attach_import_metadata(self, *args, **kwargs):
            raise RuntimeError("metadata attach failed")

    with pytest.raises(RuntimeError, match="metadata attach failed"):
        FailingAttachService(db_path).import_exam(
            parsed_exam=_grouped_exam(),
            source=_source(),
        )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM question_groups").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM question_choices").fetchone()[0] == 0


def test_import_doc_apply_skips_existing_source_without_force(monkeypatch, tmp_path: Path, capsys):
    document_url = "https://www.comcbt.com/xe/wc/8837719"
    attachment_url = "https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1"
    attachment_filename = "시험(교사용).pdf"
    pdf_bytes = b"%PDF fake duplicate"
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    db_path = tmp_path / "exam.db"
    QuestionSourceRegistry(db_path).register(
        QuestionSource(
            provider="comcbt",
            source_url=document_url,
            document_id="8837719",
            attachment_url=attachment_url,
            attachment_filename=attachment_filename,
            content_hash=content_hash,
            fetched_at="2026-06-29T00:00:00+00:00",
        )
    )
    import_calls = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_text(self, url: str) -> str:
            assert url == document_url
            return f"""
            <html>
              <head>
                <title>시험 필기 기출문제 및 CBT 2025년 04월 05일(1회)</title>
              </head>
              <body>
                <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">{attachment_filename}</a>
              </body>
            </html>
            """

        def download(self, url: str, destination: Path) -> Path:
            assert url == attachment_url
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(pdf_bytes)
            return destination

    class SpyImportService(ComcbtImportService):
        def find_existing_source(self, source):
            raise AssertionError("CLI must not bypass import_exam for duplicate skip")

        def import_exam(self, *args, **kwargs):
            import_calls.append((args, kwargs))
            return super().import_exam(*args, **kwargs)

    monkeypatch.setattr(comcbt_crawl, "SlowHttpClient", FakeHttpClient)
    monkeypatch.setattr(comcbt_crawl, "parse_downloaded_attachment", lambda downloaded, work_dir: _grouped_exam())
    monkeypatch.setattr(comcbt_crawl, "ComcbtImportService", SpyImportService)

    exit_code = comcbt_crawl.main([
        "--cache-dir",
        str(tmp_path / "cache"),
        "import-doc",
        "--url",
        document_url,
        "--db",
        str(db_path),
        "--work-dir",
        str(tmp_path / "work"),
        "--apply",
    ])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert len(import_calls) == 1
    assert "status=skipped_duplicate" in output
    assert "importable=true" in output
    assert "quality_report=skipped" not in output
    assert (tmp_path / "work" / "quality_report.json").exists()
    assert "skipped=true" in output
    assert "saved=0" in output
    assert f"hash={content_hash}" in output
    assert f"selected_attachment={attachment_filename}" in output


def test_import_doc_apply_non_duplicate_uses_import_service(monkeypatch, tmp_path: Path, capsys):
    document_url = "https://www.comcbt.com/xe/wc/8837719"
    attachment_url = "https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1"
    attachment_filename = "시험(교사용).pdf"
    pdf_bytes = b"%PDF fake new source"
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    db_path = tmp_path / "exam.db"
    import_calls = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_text(self, url: str) -> str:
            assert url == document_url
            return f"""
            <html>
              <head>
                <title>시험 필기 기출문제 및 CBT 2025년 04월 05일(1회)</title>
              </head>
              <body>
                <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">{attachment_filename}</a>
              </body>
            </html>
            """

        def download(self, url: str, destination: Path) -> Path:
            assert url == attachment_url
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(pdf_bytes)
            return destination

    class SpyImportService(ComcbtImportService):
        def import_exam(self, *args, **kwargs):
            import_calls.append((args, kwargs))
            return super().import_exam(*args, **kwargs)

    monkeypatch.setattr(comcbt_crawl, "SlowHttpClient", FakeHttpClient)
    monkeypatch.setattr(comcbt_crawl, "parse_downloaded_attachment", lambda downloaded, work_dir: _grouped_exam())
    monkeypatch.setattr(comcbt_crawl, "ComcbtImportService", SpyImportService)

    exit_code = comcbt_crawl.main([
        "--cache-dir",
        str(tmp_path / "cache"),
        "import-doc",
        "--url",
        document_url,
        "--db",
        str(db_path),
        "--work-dir",
        str(tmp_path / "work"),
        "--apply",
    ])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert len(import_calls) == 1
    assert "status=imported" in output
    assert "importable=true" in output
    assert "saved=2" in output
    assert "skipped=false" in output
    assert "quality_report=" in output
    assert (tmp_path / "work" / "quality_report.json").exists()
    assert f"hash={content_hash}" in output


def test_import_doc_trailing_slash_uses_canonical_source_url_for_duplicate_detection(
    monkeypatch,
    tmp_path: Path,
    capsys,
):
    canonical_document_url = "https://www.comcbt.com/xe/wc/8837719"
    attachment_url = "https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1"
    attachment_filename = "시험(교사용).pdf"
    pdf_bytes = b"%PDF same duplicate"
    content_hash = hashlib.sha256(pdf_bytes).hexdigest()
    db_path = tmp_path / "exam.db"
    QuestionSourceRegistry(db_path).register(
        QuestionSource(
            provider="comcbt",
            source_url=canonical_document_url,
            document_id="8837719",
            attachment_url=attachment_url,
            attachment_filename=attachment_filename,
            content_hash=content_hash,
            fetched_at="2026-06-29T00:00:00+00:00",
        )
    )
    import_calls = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_text(self, url: str) -> str:
            assert url == canonical_document_url
            return f"""
            <html>
              <head>
                <title>시험 필기 기출문제 및 CBT 2025년 04월 05일(1회)</title>
              </head>
              <body>
                <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">{attachment_filename}</a>
              </body>
            </html>
            """

        def download(self, url: str, destination: Path) -> Path:
            assert url == attachment_url
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(pdf_bytes)
            return destination

    class SpyImportService(ComcbtImportService):
        def import_exam(self, *args, **kwargs):
            import_calls.append((args, kwargs))
            return super().import_exam(*args, **kwargs)

    monkeypatch.setattr(comcbt_crawl, "SlowHttpClient", FakeHttpClient)
    monkeypatch.setattr(comcbt_crawl, "parse_downloaded_attachment", lambda downloaded, work_dir: _grouped_exam())
    monkeypatch.setattr(comcbt_crawl, "ComcbtImportService", SpyImportService)

    exit_code = comcbt_crawl.main([
        "--cache-dir",
        str(tmp_path / "cache"),
        "import-doc",
        "--url",
        canonical_document_url + "/",
        "--db",
        str(db_path),
        "--work-dir",
        str(tmp_path / "work"),
        "--apply",
    ])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert len(import_calls) == 1
    assert "status=skipped_duplicate" in output
    assert "importable=true" in output
    assert (tmp_path / "work" / "quality_report.json").exists()
    assert "skipped=true" in output
    assert f"hash={content_hash}" in output
