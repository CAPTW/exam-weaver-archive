"""Source metadata helpers for idempotent web imports."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.database.repository import ExamRepository
from src.web_import.models import ComcbtParsedExam
from src.web_import.quality import (
    ParsedExamQualityReport,
    evaluate_parsed_exam,
    write_quality_report,
)


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _question_lookup_key(
    question: Any,
    parsed_exam: ComcbtParsedExam,
) -> tuple[str, str, int, int, int]:
    return (
        str(getattr(question, "exam_type", None) or parsed_exam.exam_type),
        str(getattr(question, "subject_name", None) or "미분류"),
        int(getattr(question, "year", None) or parsed_exam.year),
        int(getattr(question, "session", None) or parsed_exam.session),
        int(getattr(question, "number")),
    )


def _source_question_id(source: QuestionSource, question: Any) -> str:
    document_id = source.document_id or source.content_hash
    return f"{document_id}:{getattr(question, 'number')}"


def _group_number(group: Any, fallback: int) -> int:
    match = re.search(r"(\d+)$", str(getattr(group, "group_id", "") or ""))
    if match:
        return int(match.group(1))
    return fallback


def _questions_for_group(parsed_exam: ComcbtParsedExam, group: Any) -> list[Any]:
    parser_group_id = getattr(group, "group_id", None)
    questions = [
        question
        for question in parsed_exam.questions
        if getattr(question, "group_id", None) == parser_group_id
    ]
    if questions:
        return questions
    child_numbers = set(getattr(group, "child_numbers", None) or [])
    return [
        question
        for question in parsed_exam.questions
        if getattr(question, "number", None) in child_numbers
    ]


@dataclass(frozen=True)
class QuestionSource:
    provider: str
    source_url: str
    document_id: str | None
    attachment_url: str | None
    attachment_filename: str | None
    content_hash: str
    fetched_at: str

    @property
    def document_url(self) -> str:
        return self.source_url


@dataclass(frozen=True)
class SourceRegistration:
    source_id: int
    existing: bool


@dataclass(frozen=True)
class ComcbtImportResult:
    status: str
    importable: bool
    saved: int = 0
    skipped: bool = False
    source_id: int | None = None
    source_existing: bool = False
    quality_report: ParsedExamQualityReport | None = None
    quality_report_path: str | None = None

    @property
    def errors(self) -> list[str]:
        return self.quality_report.errors if self.quality_report else []

    @property
    def warnings(self) -> list[str]:
        return self.quality_report.warnings if self.quality_report else []


class ComcbtImportService:
    """Group-aware COMCBT DB importer with quality and duplicate gates."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.registry = QuestionSourceRegistry(db_path)

    def find_existing_source(self, source: QuestionSource) -> SourceRegistration | None:
        return self.registry.find_existing(source)

    def import_exam(
        self,
        parsed_exam: ComcbtParsedExam,
        source: QuestionSource,
        force: bool = False,
        quality_report_path: Path | str | None = None,
        apply: bool = True,
    ) -> ComcbtImportResult:
        repo = None
        if apply:
            repo = ExamRepository(str(self.db_path))
            repo.init_database()

        report = evaluate_parsed_exam(parsed_exam)
        written_report_path = None
        if quality_report_path is not None:
            written_report_path = str(write_quality_report(report, quality_report_path))

        if not apply:
            return ComcbtImportResult(
                status="dry_run",
                importable=report.importable,
                quality_report=report,
                quality_report_path=written_report_path,
            )

        if not report.importable:
            return ComcbtImportResult(
                status="blocked_quality",
                importable=False,
                quality_report=report,
                quality_report_path=written_report_path,
            )

        existing = self.registry.find_existing(source)
        if existing is not None and not force:
            return ComcbtImportResult(
                status="skipped_duplicate",
                importable=True,
                saved=0,
                skipped=True,
                source_id=existing.source_id,
                source_existing=True,
                quality_report=report,
                quality_report_path=written_report_path,
            )

        assert repo is not None
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if not force:
                existing = self.registry.find_existing_on(conn, source)
                if existing is not None:
                    return ComcbtImportResult(
                        status="skipped_duplicate",
                        importable=True,
                        saved=0,
                        skipped=True,
                        source_id=existing.source_id,
                        source_existing=True,
                        quality_report=report,
                        quality_report_path=written_report_path,
                    )

            registration = self.registry.register_on(conn, source)
            saved = repo.save_questions(parsed_exam.questions, parsed_exam.metadata, conn=conn)
            self._attach_import_metadata(
                conn=conn,
                parsed_exam=parsed_exam,
                source=source,
                source_id=registration.source_id,
            )

        return ComcbtImportResult(
            status="imported",
            importable=True,
            saved=saved,
            skipped=False,
            source_id=registration.source_id,
            source_existing=registration.existing,
            quality_report=report,
            quality_report_path=written_report_path,
        )

    def _attach_import_metadata(
        self,
        conn: sqlite3.Connection,
        parsed_exam: ComcbtParsedExam,
        source: QuestionSource,
        source_id: int,
    ) -> None:
        question_rows = self._load_saved_question_rows(conn, parsed_exam)
        group_db_ids = self._upsert_question_groups(
            conn=conn,
            parsed_exam=parsed_exam,
            source_id=source_id,
            question_rows=question_rows,
        )

        for question in parsed_exam.questions:
            row = question_rows.get(_question_lookup_key(question, parsed_exam))
            if row is None:
                continue
            parser_group_id = getattr(question, "group_id", None)
            db_group_id = group_db_ids.get(parser_group_id) if parser_group_id else None
            conn.execute(
                """
                UPDATE questions
                SET group_id = ?,
                    group_order = ?,
                    source_id = ?,
                    source_question_id = ?
                WHERE id = ?
                """,
                (
                    db_group_id,
                    getattr(question, "group_order", None),
                    source_id,
                    _source_question_id(source, question),
                    row["id"],
                ),
            )

    def _load_saved_question_rows(
        self,
        conn: sqlite3.Connection,
        parsed_exam: ComcbtParsedExam,
    ) -> dict[tuple[str, str, int, int, int], sqlite3.Row]:
        rows: dict[tuple[str, str, int, int, int], sqlite3.Row] = {}
        for question in parsed_exam.questions:
            exam_type, subject_name, year, session, number = _question_lookup_key(
                question,
                parsed_exam,
            )
            cursor = conn.execute(
                """
                SELECT q.id, q.exam_subject_id, q.question_number
                FROM questions q
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN exams e ON es.exam_id = e.id
                JOIN subjects s ON es.subject_id = s.id
                WHERE e.code = ?
                  AND (s.name_ko = ? OR s.code = ?)
                  AND q.year = ?
                  AND q.session = ?
                  AND q.question_number = ?
                """,
                (exam_type, subject_name, subject_name, year, session, number),
            )
            row = cursor.fetchone()
            if row is not None:
                rows[(exam_type, subject_name, year, session, number)] = row
        return rows

    def _upsert_question_groups(
        self,
        conn: sqlite3.Connection,
        parsed_exam: ComcbtParsedExam,
        source_id: int,
        question_rows: dict[tuple[str, str, int, int, int], sqlite3.Row],
    ) -> dict[str, int]:
        group_db_ids: dict[str, int] = {}
        for index, group in enumerate(parsed_exam.groups or [], start=1):
            parser_group_id = str(getattr(group, "group_id", "") or "")
            if not parser_group_id:
                continue
            child_questions = _questions_for_group(parsed_exam, group)
            if not child_questions:
                continue
            first_row = question_rows.get(_question_lookup_key(child_questions[0], parsed_exam))
            if first_row is None:
                continue
            group_number = _group_number(group, index)
            exam_subject_id = int(first_row["exam_subject_id"])
            year = int(getattr(child_questions[0], "year", None) or parsed_exam.year)
            session = int(getattr(child_questions[0], "session", None) or parsed_exam.session)

            conn.execute(
                """
                INSERT OR IGNORE INTO question_groups (
                    exam_subject_id,
                    year,
                    session,
                    group_number,
                    group_type,
                    shared_text,
                    shared_image_path,
                    source_id,
                    source_page,
                    tags
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    exam_subject_id,
                    year,
                    session,
                    group_number,
                    "shared_passage",
                    getattr(group, "text", None),
                    getattr(group, "shared_image_path", None),
                    source_id,
                    getattr(group, "source_page", None),
                    None,
                ),
            )
            conn.execute(
                """
                UPDATE question_groups
                SET group_type = ?,
                    shared_text = ?,
                    shared_image_path = ?,
                    source_id = ?,
                    source_page = ?,
                    tags = ?
                WHERE exam_subject_id = ?
                  AND year = ?
                  AND session = ?
                  AND group_number = ?
                """,
                (
                    "shared_passage",
                    getattr(group, "text", None),
                    getattr(group, "shared_image_path", None),
                    source_id,
                    getattr(group, "source_page", None),
                    None,
                    exam_subject_id,
                    year,
                    session,
                    group_number,
                ),
            )
            row = conn.execute(
                """
                SELECT id
                FROM question_groups
                WHERE exam_subject_id = ?
                  AND year = ?
                  AND session = ?
                  AND group_number = ?
                """,
                (exam_subject_id, year, session, group_number),
            ).fetchone()
            if row is not None:
                group_db_ids[parser_group_id] = int(row["id"])
        return group_db_ids


class QuestionSourceRegistry:
    """Small SQLite store for source traceability and duplicate detection."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def ensure_schema(self) -> None:
        self._ensure_parent_dir()
        with self._connect() as conn:
            self.ensure_schema_on(conn)

    def find_existing(self, source: QuestionSource) -> SourceRegistration | None:
        self._ensure_parent_dir()
        with self._connect() as conn:
            return self.find_existing_on(conn, source)

    def register(self, source: QuestionSource) -> SourceRegistration:
        self._ensure_parent_dir()
        with self._connect() as conn:
            return self.register_on(conn, source)

    def find_existing_on(
        self,
        conn: sqlite3.Connection,
        source: QuestionSource,
    ) -> SourceRegistration | None:
        self.ensure_schema_on(conn)
        row = self._select_existing(conn, source)
        if row is None:
            return None
        return SourceRegistration(source_id=row, existing=True)

    def register_on(
        self,
        conn: sqlite3.Connection,
        source: QuestionSource,
    ) -> SourceRegistration:
        self.ensure_schema_on(conn)
        existing_id = self._select_existing(conn, source)
        if existing_id is not None:
            return SourceRegistration(source_id=existing_id, existing=True)
        try:
            cursor = conn.execute(
                """
                INSERT INTO question_sources (
                    provider,
                    source_url,
                    document_id,
                    attachment_url,
                    attachment_filename,
                    content_hash,
                    fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.provider,
                    source.source_url,
                    source.document_id,
                    source.attachment_url,
                    source.attachment_filename,
                    source.content_hash,
                    source.fetched_at,
                ),
            )
            return SourceRegistration(source_id=int(cursor.lastrowid), existing=False)
        except sqlite3.IntegrityError:
            existing_id = self._select_existing(conn, source)
            if existing_id is None:
                raise
            return SourceRegistration(source_id=existing_id, existing=True)

    @staticmethod
    def ensure_schema_on(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS question_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                source_url TEXT NOT NULL,
                document_id TEXT,
                attachment_url TEXT,
                attachment_filename TEXT,
                content_hash TEXT NOT NULL,
                fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, source_url, content_hash)
            )
            """
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _ensure_parent_dir(self) -> None:
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _select_existing(conn: sqlite3.Connection, source: QuestionSource) -> int | None:
        cursor = conn.execute(
            """
            SELECT id
            FROM question_sources
            WHERE provider = ?
              AND source_url = ?
              AND content_hash = ?
            """,
            (source.provider, source.source_url, source.content_hash),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else None
