"""Fail-closed staging, validation, and replacement for offline exam databases."""

from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlparse

from src.database.repository import ExamRepository
from src.parser.offline_sources import (
    DocumentRole,
    classify_offline_document,
    parse_offline_question_pdf,
)
from src.parser.question import Choice, Question


PLACEHOLDER_TEXT = "원문 보기 참조"
CHOICE_SYMBOLS = ("㉮", "㉯", "㉴", "㉵", "⑤")
REQUIRED_SCHEMA: Mapping[str, frozenset[str]] = {
    "exams": frozenset({"id", "code", "name"}),
    "subjects": frozenset({"id", "code", "name_ko"}),
    "exam_subjects": frozenset({"id", "exam_id", "subject_id"}),
    "question_sources": frozenset({"id", "provider", "source_url", "content_hash"}),
    "questions": frozenset(
        {
            "id",
            "exam_subject_id",
            "year",
            "session",
            "question_number",
            "question_text",
            "correct_answer",
            "source_id",
        }
    ),
    "question_choices": frozenset(
        {"id", "question_id", "choice_number", "choice_symbol", "choice_text"}
    ),
}


@dataclass(frozen=True)
class InventoryContract:
    total: int
    question: int
    answer: int
    notice: int
    unknown: int = 0

    def mismatches(self, counts: Mapping[str, int]) -> tuple[str, ...]:
        expected = asdict(self)
        return tuple(
            f"{key}: expected={value} actual={int(counts.get(key, 0))}"
            for key, value in expected.items()
            if int(counts.get(key, 0)) != value
        )


STRICT_CORPUS_INVENTORY = InventoryContract(30, 12, 15, 3, 0)
STRICT_EXPECTED_SET_COUNT = 135
STRICT_EXPECTED_QUESTION_COUNT = 3280


@dataclass(frozen=True)
class ExpectedExamSet:
    exam_type: str
    subject_name: str
    year: int
    session: int
    question_numbers: tuple[int, ...]
    require_answers: bool = True
    require_provenance: bool = True

    def __post_init__(self) -> None:
        normalized = tuple(sorted({int(number) for number in self.question_numbers}))
        object.__setattr__(self, "question_numbers", normalized)

    @property
    def key(self) -> tuple[str, str, int, int]:
        return (self.exam_type, self.subject_name, self.year, self.session)

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["question_numbers"] = list(self.question_numbers)
        return value


@dataclass(frozen=True)
class RegisteredExamSet:
    """Trusted provider output; coverage is registered independently of parser output."""

    expected: ExpectedExamSet
    questions: tuple[Question, ...]
    source_path: Path
    answer_path: Path
    rejected_count: int = 0


@dataclass(frozen=True)
class ExamSetValidation:
    expected: ExpectedExamSet
    actual_numbers: tuple[int, ...]
    missing_numbers: tuple[int, ...]
    unexpected_numbers: tuple[int, ...]
    missing_answers: tuple[int, ...]
    missing_provenance: tuple[int, ...]

    @property
    def valid(self) -> bool:
        return not (
            self.missing_numbers
            or self.unexpected_numbers
            or self.missing_answers
            or self.missing_provenance
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected.to_dict(),
            "actual_numbers": list(self.actual_numbers),
            "missing_numbers": list(self.missing_numbers),
            "unexpected_numbers": list(self.unexpected_numbers),
            "missing_answers": list(self.missing_answers),
            "missing_provenance": list(self.missing_provenance),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class ValidationReport:
    path: Path
    valid: bool
    integrity_check: str
    schema_valid: bool
    foreign_key_errors: tuple[tuple[object, ...], ...] = ()
    placeholder_count: int = 0
    duplicate_count: int = 0
    missing_provenance_count: int = 0
    counts: Mapping[str, int] = field(default_factory=dict)
    sets: tuple[ExamSetValidation, ...] = ()
    error_codes: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.valid

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "valid": self.valid,
            "integrity_check": self.integrity_check,
            "schema_valid": self.schema_valid,
            "foreign_key_errors": [list(row) for row in self.foreign_key_errors],
            "placeholder_count": self.placeholder_count,
            "duplicate_count": self.duplicate_count,
            "missing_provenance_count": self.missing_provenance_count,
            "counts": dict(self.counts),
            "sets": [item.to_dict() for item in self.sets],
            "error_codes": list(self.error_codes),
            "details": list(self.details),
        }


@dataclass(frozen=True)
class RebuildSummary:
    root: Path
    staging_db: Path
    inventory_counts: Mapping[str, int]
    question_count: int
    answer_count: int
    rejected_count: int
    expected_sets: tuple[ExpectedExamSet, ...]
    report_paths: Mapping[str, Path]
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "staging_db": str(self.staging_db),
            "inventory_counts": dict(self.inventory_counts),
            "question_count": self.question_count,
            "answer_count": self.answer_count,
            "rejected_count": self.rejected_count,
            "expected_sets": [item.to_dict() for item in self.expected_sets],
            "report_paths": {key: str(value) for key, value in self.report_paths.items()},
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class ReplacementReceipt:
    replaced_at: str
    staging_path: Path
    mounted_path: Path
    backup_path: Path
    receipt_path: Path
    previous_sha256: str
    backup_sha256: str
    staging_sha256: str
    mounted_sha256: str
    counts: Mapping[str, int]
    validation: ValidationReport

    def to_dict(self) -> dict[str, object]:
        return {
            "replaced_at": self.replaced_at,
            "staging_path": str(self.staging_path),
            "mounted_path": str(self.mounted_path),
            "backup_path": str(self.backup_path),
            "receipt_path": str(self.receipt_path),
            "previous_sha256": self.previous_sha256,
            "backup_sha256": self.backup_sha256,
            "staging_sha256": self.staging_sha256,
            "mounted_sha256": self.mounted_sha256,
            "counts": dict(self.counts),
            "validation": self.validation.to_dict(),
        }


class ReplacementError(RuntimeError):
    """Raised when validation or replacement cannot complete safely."""


def validate_rebuild_paths(
    staging: str | Path,
    mounted: str | Path,
    backup_dir: str | Path,
    receipt_path: str | Path,
) -> None:
    """Reject destructive path aliases before a staging file can be unlinked."""

    aliases = {
        "staging": Path(staging).resolve(),
        "mounted": Path(mounted).resolve(),
        "backup": Path(backup_dir).resolve(),
        "receipt": Path(receipt_path).resolve(),
    }
    names = tuple(aliases)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if aliases[left] == aliases[right]:
                raise ReplacementError(
                    f"path alias: {left} and {right} resolve to {aliases[left]}"
                )


def build_staging_database(
    root: str | Path,
    staging_db: str | Path,
    report_dir: str | Path,
    *,
    inventory_contract: InventoryContract | None = STRICT_CORPUS_INVENTORY,
    registered_set_provider: Callable[
        [Path, Path, Sequence[Mapping[str, object]]], Sequence[RegisteredExamSet]
    ]
    | None = None,
) -> RebuildSummary:
    """Inventory PDFs and build a new database without touching a mounted DB."""

    source_root = Path(root).resolve()
    database_path = Path(staging_db).resolve()
    reports = Path(report_dir).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"offline PDF root does not exist: {source_root}")

    inventory: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    pdf_paths = sorted(
        (path for path in source_root.rglob("*") if path.is_file() and path.suffix.casefold() == ".pdf"),
        key=lambda path: str(path.relative_to(source_root)).casefold(),
    )
    for path in pdf_paths:
        role = classify_offline_document(path)
        digest = _sha256_file(path)
        relative_path = str(path.relative_to(source_root))
        inventory.append(
            {
                "relative_path": relative_path,
                "role": role.value,
                "sha256": digest,
                "size": path.stat().st_size,
            }
        )
        counts[role.value] += 1

    for role in DocumentRole:
        counts.setdefault(role.value, 0)
    counts["total"] = len(inventory)
    if inventory_contract is not None:
        mismatches = inventory_contract.mismatches(counts)
        if mismatches:
            raise ValueError("offline corpus inventory mismatch: " + "; ".join(mismatches))

    database_path.parent.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()

    repository = ExamRepository(str(database_path))
    repository.init_database()
    _initialize_rebuild_schema(database_path)
    _write_inventory(database_path, inventory)

    expected_by_key: dict[tuple[str, str, int, int], set[int]] = {}
    rejected_count = 0
    errors: list[str] = []
    if inventory_contract is not None:
        provider = registered_set_provider or _build_registered_corpus_sets
        registered_sets = tuple(provider(source_root, reports, inventory))
        if not registered_sets:
            raise ValueError("registered corpus provider returned no expected exam sets")
        if inventory_contract == STRICT_CORPUS_INVENTORY:
            registered_question_count = sum(
                len(item.expected.question_numbers) for item in registered_sets
            )
            if (
                len(registered_sets) != STRICT_EXPECTED_SET_COUNT
                or registered_question_count != STRICT_EXPECTED_QUESTION_COUNT
            ):
                raise ValueError(
                    "registered corpus coverage mismatch: "
                    f"sets={len(registered_sets)}/{STRICT_EXPECTED_SET_COUNT} "
                    f"questions={registered_question_count}/{STRICT_EXPECTED_QUESTION_COUNT}"
                )
        for registered in registered_sets:
            expected = registered.expected
            if not expected.question_numbers:
                raise ValueError(f"registered set has empty coverage: {expected.key}")
            _persist_registered_set(database_path, repository, registered, inventory)
            if registered.rejected_count:
                _record_set_rejections(database_path, expected, registered.rejected_count)
            expected_by_key.setdefault(expected.key, set()).update(expected.question_numbers)
            rejected_count += registered.rejected_count

    for row, path in zip(inventory, pdf_paths):
        if inventory_contract is not None:
            continue
        if row["role"] != DocumentRole.QUESTION.value:
            continue
        try:
            metadata = _infer_document_metadata(path, source_root)
            parsed = parse_offline_question_pdf(path, metadata)
            expected_count = metadata.get("expected_question_count")
            if not isinstance(expected_count, int) or expected_count < 1:
                raise ValueError("question coverage is not registered independently")
            expected_numbers = tuple(range(1, expected_count + 1))
            answer_key, answer_path = _resolve_answer_key(
                path, source_root, metadata, expected_numbers
            )
            questions = [
                Question(
                    number=item.number,
                    text=item.stem,
                    choices=[
                        Choice(
                            number=index,
                            symbol=CHOICE_SYMBOLS[index - 1],
                            text=text,
                        )
                        for index, text in enumerate(item.choices, start=1)
                    ],
                    correct_answer=int(answer_key.get(item.number, 0)),
                    source_page=item.source_page,
                    subject_name=str(metadata["subject_name"]),
                    year=int(metadata["year"]),
                    session=int(metadata["session"]),
                    exam_type=str(metadata["exam_type"]),
                )
                for item in parsed.questions
            ]
            source_id = _insert_question_source(
                database_path,
                path,
                str(metadata.get("document_id", path.stem)),
                str(row["sha256"]),
                answer_path,
            )
            repository.save_questions(
                questions,
                SimpleNamespace(
                    year=int(metadata["year"]),
                    session=int(metadata["session"]),
                    exam_type=str(metadata["exam_type"]),
                ),
            )
            _attach_provenance(database_path, metadata, expected_numbers, source_id)
            key = (
                str(metadata["exam_type"]),
                str(metadata["subject_name"]),
                int(metadata["year"]),
                int(metadata["session"]),
            )
            expected_by_key.setdefault(key, set()).update(expected_numbers)
            rejected_count += len(parsed.rejected)
            _mark_document_build(
                database_path,
                str(row["relative_path"]),
                parsed_question_count=len(parsed.questions),
            )
        except Exception as exc:  # keep the staging artifact inspectable and fail validation later
            message = f"{path.relative_to(source_root)}: {type(exc).__name__}: {exc}"
            errors.append(message)
            _mark_document_build(
                database_path,
                str(row["relative_path"]),
                parsed_question_count=0,
                build_error=message,
            )

    expected_sets = tuple(
        ExpectedExamSet(*key, tuple(sorted(numbers)))
        for key, numbers in sorted(expected_by_key.items())
    )
    _store_expected_sets(database_path, expected_sets)
    database_counts = _database_counts(database_path)

    report_paths = {
        "inventory_json": reports / "inventory.json",
        "inventory_csv": reports / "inventory.csv",
        "rebuild_json": reports / "rebuild_summary.json",
        "validation_json": reports / "validation.json",
        "validation_csv": reports / "validation_sets.csv",
    }
    _write_json(report_paths["inventory_json"], {"counts": dict(counts), "documents": inventory})
    _write_inventory_csv(report_paths["inventory_csv"], inventory)
    summary = RebuildSummary(
        root=source_root,
        staging_db=database_path,
        inventory_counts={key: counts[key] for key in ("question", "answer", "notice", "unknown", "total")},
        question_count=database_counts.get("questions", 0),
        answer_count=_valid_answer_count(database_path),
        rejected_count=rejected_count,
        expected_sets=expected_sets,
        report_paths=report_paths,
        errors=tuple(errors),
    )
    _write_json(report_paths["rebuild_json"], summary.to_dict())
    validation = validate_staging_database(database_path, expected_sets)
    _write_json(report_paths["validation_json"], validation.to_dict())
    _write_validation_csv(report_paths["validation_csv"], validation.sets)
    return summary


def validate_staging_database(
    path: str | Path,
    expected_sets: Iterable[ExpectedExamSet | Mapping[str, object]],
) -> ValidationReport:
    """Validate SQLite, application schema, and every explicitly expected set."""

    database_path = Path(path).resolve()
    normalized_sets = tuple(_coerce_expected_set(item) for item in expected_sets)
    errors: list[str] = []
    details: list[str] = []
    if not database_path.is_file():
        return ValidationReport(
            path=database_path,
            valid=False,
            integrity_check="missing",
            schema_valid=False,
            error_codes=("missing_database",),
            details=(f"database does not exist: {database_path}",),
        )

    try:
        with _readonly_connection(database_path) as connection:
            integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
            integrity = "; ".join(str(row[0]) for row in integrity_rows) or "unknown"
            if integrity != "ok":
                errors.append("sqlite_integrity")
            foreign_key_errors = tuple(
                tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
            )
            if foreign_key_errors:
                errors.append("foreign_keys")
            schema_valid, schema_details = _validate_application_schema(connection)
            if not schema_valid:
                errors.append("application_schema")
                details.extend(schema_details)
            if not schema_valid:
                return ValidationReport(
                    path=database_path,
                    valid=False,
                    integrity_check=integrity,
                    schema_valid=False,
                    foreign_key_errors=foreign_key_errors,
                    error_codes=tuple(dict.fromkeys(errors)),
                    details=tuple(details),
                )

            placeholder_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM question_choices WHERE choice_text LIKE ?",
                    (f"%{PLACEHOLDER_TEXT}%",),
                ).fetchone()[0]
            )
            if placeholder_count:
                errors.append("placeholder_choices")
            duplicate_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT exam_subject_id, year, session, question_number
                        FROM questions
                        GROUP BY exam_subject_id, year, session, question_number
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]
            )
            if duplicate_count:
                errors.append("duplicate_questions")
            invalid_structure_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM questions q
                    WHERE TRIM(COALESCE(q.question_text, '')) = ''
                       OR (SELECT COUNT(*) FROM question_choices c WHERE c.question_id = q.id) NOT IN (4, 5)
                       OR (SELECT COUNT(*) FROM question_choices c WHERE c.question_id = q.id AND TRIM(COALESCE(c.choice_text, '')) = '') > 0
                       OR (SELECT MIN(choice_number) FROM question_choices c WHERE c.question_id = q.id) != 1
                       OR (SELECT MAX(choice_number) FROM question_choices c WHERE c.question_id = q.id)
                          != (SELECT COUNT(*) FROM question_choices c WHERE c.question_id = q.id)
                       OR (SELECT COUNT(DISTINCT choice_number) FROM question_choices c WHERE c.question_id = q.id)
                          != (SELECT COUNT(*) FROM question_choices c WHERE c.question_id = q.id)
                    """
                ).fetchone()[0]
            )
            if invalid_structure_count:
                errors.append("invalid_question_structure")

            rebuild_inventory_exists = connection.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'offline_rebuild_documents'
                """
            ).fetchone()
            if rebuild_inventory_exists:
                unparsed_question_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM offline_rebuild_documents
                        WHERE role = ? AND (parsed_question_count = 0 OR build_error IS NOT NULL)
                        """,
                        (DocumentRole.QUESTION.value,),
                    ).fetchone()[0]
                )
                if unparsed_question_count:
                    errors.append("unparsed_question_documents")
                inventory_rows = connection.execute(
                    "SELECT relative_path, role, sha256 FROM offline_rebuild_documents"
                ).fetchall()
                inventory_by_name = {
                    Path(str(row[0])).name: (str(row[1]), str(row[2]))
                    for row in inventory_rows
                }
                provenance_rows = connection.execute(
                    """
                    SELECT DISTINCT qs.source_url, qs.content_hash,
                           qs.attachment_url, qs.attachment_filename
                    FROM questions q
                    JOIN question_sources qs ON qs.id = q.source_id
                    """
                ).fetchall()
                provenance_mismatch = False
                for source_url, content_hash, attachment_url, attachment_filename in provenance_rows:
                    source_name = _url_filename(str(source_url or ""))
                    source_inventory = inventory_by_name.get(source_name)
                    answer_name = _url_filename(str(attachment_url or ""))
                    answer_inventory = inventory_by_name.get(answer_name)
                    if (
                        source_inventory is None
                        or source_inventory[0] != DocumentRole.QUESTION.value
                        or source_inventory[1] != str(content_hash or "")
                        or answer_inventory is None
                        or answer_inventory[0] != DocumentRole.ANSWER.value
                        or answer_name != str(attachment_filename or "")
                    ):
                        provenance_mismatch = True
                        break
                if provenance_mismatch:
                    errors.append("provenance_mismatch")
                rejection_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='offline_rebuild_rejections'"
                ).fetchone()
                if rejection_table and int(
                    connection.execute(
                        "SELECT COALESCE(SUM(rejected_count), 0) FROM offline_rebuild_rejections"
                    ).fetchone()[0]
                ):
                    errors.append("rejected_candidates")

            set_reports = tuple(
                _validate_expected_set(connection, expected) for expected in normalized_sets
            )
            if any(item.missing_numbers or item.unexpected_numbers for item in set_reports):
                errors.append("missing_question_numbers")
            if any(item.missing_answers for item in set_reports):
                errors.append("missing_answers")
            if any(item.missing_provenance for item in set_reports):
                errors.append("missing_provenance")
            missing_provenance_count = sum(
                len(item.missing_provenance) for item in set_reports
            )
            counts = _database_counts_from_connection(connection)
    except sqlite3.DatabaseError as exc:
        return ValidationReport(
            path=database_path,
            valid=False,
            integrity_check="error",
            schema_valid=False,
            error_codes=("sqlite_error",),
            details=(str(exc),),
        )

    unique_errors = tuple(dict.fromkeys(errors))
    return ValidationReport(
        path=database_path,
        valid=not unique_errors,
        integrity_check=integrity,
        schema_valid=True,
        foreign_key_errors=foreign_key_errors,
        placeholder_count=placeholder_count,
        duplicate_count=duplicate_count,
        missing_provenance_count=missing_provenance_count,
        counts=counts,
        sets=set_reports,
        error_codes=unique_errors,
        details=tuple(details),
    )


def replace_mounted_database(
    staging: str | Path,
    mounted: str | Path,
    backup_dir: str | Path,
    receipt_path: str | Path,
) -> ReplacementReceipt:
    """Validate, back up, and atomically replace a mounted database."""

    staging_path = Path(staging).resolve()
    mounted_path = Path(mounted).resolve()
    backups = Path(backup_dir).resolve()
    receipt_file = Path(receipt_path).resolve()
    if not mounted_path.is_file():
        raise ReplacementError(f"mounted database does not exist: {mounted_path}")
    validate_rebuild_paths(staging_path, mounted_path, backups, receipt_file)

    expected_sets = _load_expected_sets(staging_path)
    validation = validate_staging_database(staging_path, expected_sets)
    if not validation.valid:
        raise ReplacementError(
            "staging validation failed: " + ", ".join(validation.error_codes)
        )

    previous_hash = _sha256_file(mounted_path)
    staging_hash = _sha256_file(staging_path)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    backups.mkdir(parents=True, exist_ok=True)
    backup_path = backups / f"{mounted_path.stem}.{stamp}{mounted_path.suffix}"
    if backup_path in {staging_path, mounted_path, receipt_file} or backup_path.exists():
        raise ReplacementError(f"path alias or collision for backup: {backup_path}")
    _backup_sqlite_database(mounted_path, backup_path)
    _validate_backup_database(backup_path)
    backup_hash = _sha256_file(backup_path)

    mounted_path.parent.mkdir(parents=True, exist_ok=True)
    replacement_temp = mounted_path.with_name(f".{mounted_path.name}.{stamp}.replacement.tmp")
    rollback_temp = mounted_path.with_name(f".{mounted_path.name}.{stamp}.rollback.tmp")
    replaced = False
    try:
        shutil.copy2(staging_path, replacement_temp)
        _fsync_file(replacement_temp)
        copied_validation = validate_staging_database(replacement_temp, expected_sets)
        if not copied_validation.valid:
            raise ReplacementError(
                "replacement copy validation failed: " + ", ".join(copied_validation.error_codes)
            )
        # Repository methods historically used sqlite's transaction context
        # manager, which commits but does not explicitly close. Collect any
        # unreachable connection objects before Windows performs the rename.
        gc.collect()
        _atomic_replace(replacement_temp, mounted_path)
        replaced = True
        mounted_validation = validate_staging_database(mounted_path, expected_sets)
        if not mounted_validation.valid:
            raise ReplacementError(
                "mounted smoke validation failed: " + ", ".join(mounted_validation.error_codes)
            )
        mounted_hash = _sha256_file(mounted_path)
        if mounted_hash != staging_hash:
            raise ReplacementError("mounted database hash differs from validated staging hash")
        _smoke_mounted_repository(mounted_path)

        receipt = ReplacementReceipt(
            replaced_at=datetime.now(timezone.utc).isoformat(),
            staging_path=staging_path,
            mounted_path=mounted_path,
            backup_path=backup_path,
            receipt_path=receipt_file,
            previous_sha256=previous_hash,
            backup_sha256=backup_hash,
            staging_sha256=staging_hash,
            mounted_sha256=mounted_hash,
            counts=validation.counts,
            validation=validation,
        )
        _write_json_atomic(receipt_file, receipt.to_dict())
        return receipt
    except Exception as exc:
        if replaced:
            try:
                shutil.copy2(backup_path, rollback_temp)
                _fsync_file(rollback_temp)
                _atomic_replace(rollback_temp, mounted_path)
            except Exception as rollback_exc:
                raise ReplacementError(
                    f"{exc}; rollback also failed: {rollback_exc}"
                ) from rollback_exc
        if isinstance(exc, ReplacementError):
            raise
        raise ReplacementError(str(exc)) from exc
    finally:
        for temp_path in (replacement_temp, rollback_temp):
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def _initialize_rebuild_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS offline_rebuild_documents (
                relative_path TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,
                parsed_question_count INTEGER NOT NULL DEFAULT 0,
                build_error TEXT
            );
            CREATE TABLE IF NOT EXISTS offline_rebuild_expected_sets (
                exam_type TEXT NOT NULL,
                subject_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                session INTEGER NOT NULL,
                question_numbers_json TEXT NOT NULL,
                require_answers INTEGER NOT NULL,
                require_provenance INTEGER NOT NULL,
                PRIMARY KEY (exam_type, subject_name, year, session)
            );
            CREATE TABLE IF NOT EXISTS offline_rebuild_rejections (
                exam_type TEXT NOT NULL, subject_name TEXT NOT NULL,
                year INTEGER NOT NULL, session INTEGER NOT NULL,
                rejected_count INTEGER NOT NULL,
                PRIMARY KEY (exam_type, subject_name, year, session)
            );
            """
        )


def _record_set_rejections(path: Path, expected: ExpectedExamSet, count: int) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO offline_rebuild_rejections VALUES (?, ?, ?, ?, ?)",
            (*expected.key, int(count)),
        )


def _persist_registered_set(
    database_path: Path,
    repository: ExamRepository,
    registered: RegisteredExamSet,
    inventory: Sequence[Mapping[str, object]],
) -> None:
    source = registered.source_path.resolve()
    answer = registered.answer_path.resolve()
    source_row = next(
        (row for row in inventory if Path(str(row["relative_path"])).name == source.name), None
    )
    answer_row = next(
        (row for row in inventory if Path(str(row["relative_path"])).name == answer.name), None
    )
    if source_row is None or source_row.get("role") != DocumentRole.QUESTION.value:
        raise ValueError(f"registered source is absent from question inventory: {source}")
    if answer_row is None or answer_row.get("role") != DocumentRole.ANSWER.value:
        raise ValueError(f"registered answer is absent from answer inventory: {answer}")
    expected = registered.expected
    metadata = {
        "exam_type": expected.exam_type,
        "subject_name": expected.subject_name,
        "year": expected.year,
        "session": expected.session,
    }
    source_id = _insert_question_source(
        database_path,
        source,
        source.stem,
        str(source_row["sha256"]),
        answer,
    )
    repository.save_questions(
        list(registered.questions),
        SimpleNamespace(year=expected.year, session=expected.session, exam_type=expected.exam_type),
    )
    _attach_provenance(database_path, metadata, expected.question_numbers, source_id)
    _mark_document_build(
        database_path,
        str(source_row["relative_path"]),
        parsed_question_count=len(registered.questions),
        build_error=None,
    )


def _build_registered_corpus_sets(
    root: Path,
    report_dir: Path,
    inventory: Sequence[Mapping[str, object]],
) -> Sequence[RegisteredExamSet]:
    """Run the registered Ronpark subject builders plus native-2023 adapters."""

    question_paths = [
        root / str(row["relative_path"])
        for row in inventory
        if row["role"] == DocumentRole.QUESTION.value
    ]
    page_records: list[dict[str, object]] = []
    native_paths: list[Path] = []
    for path in question_paths:
        if path.name in {"2023 2차 - 물리.pdf", "2023 2차 - 항해.pdf"}:
            native_paths.append(path)
            continue
        parsed = parse_offline_question_pdf(path, {"probe": {"role": "question"}})
        for page in parsed.structured_pages:
            text_value = "\n".join(
                " ".join(str(word.text) for word in line.words) for line in page.lines
            )
            page_records.append(
                {
                    "filename": path.name,
                    "pdf_id": path.stem,
                    "page": page.number,
                    "text": text_value,
                    "source_path": str(path),
                }
            )

    from scripts import import_maritime_english_pdf as maritime_english
    from scripts import import_maritime_law_pdf as maritime_law
    from scripts import import_police_engineering_pdf as police_engineering
    from scripts import import_police_navigation_pdf as police_navigation

    modules = (maritime_law, maritime_english, police_navigation, police_engineering)
    registered: list[RegisteredExamSet] = []
    for module in modules:
        if hasattr(module, "KNOWN_GROUPS"):
            filenames = set(module.KNOWN_GROUPS)
            records = [row for row in page_records if row["filename"] in filenames]
        else:
            records = [row for row in page_records if "해사영어" in str(row["filename"])]
        if not records:
            continue
        source_paths = [Path(str(row["source_path"])) for row in records]
        input_dir = Path(os.path.commonpath([str(path.parent) for path in source_paths]))
        module_report = report_dir / f"provider_{module.__name__.split('.')[-1]}"
        module_report.mkdir(parents=True, exist_ok=True)
        if module is police_engineering:
            original_gate = module.require_complete_offline_set

            def engineering_gate(questions, *, expected_numbers, answers, rejected_count, choice_counts):
                if answers and all(int(answer) == 0 for answer in answers):
                    expected_values = tuple(int(number) for number in expected_numbers)
                    if set(questions) != set(expected_values) or rejected_count:
                        raise ValueError("registered no-answer engineering set is incomplete")
                    if any(int(choice_counts.get(number, 0)) not in (4, 5) for number in expected_values):
                        raise ValueError("registered no-answer engineering set has invalid choices")
                    return
                original_gate(
                    questions,
                    expected_numbers=expected_numbers,
                    answers=answers,
                    rejected_count=rejected_count,
                    choice_counts=choice_counts,
                )

            module.require_complete_offline_set = engineering_gate
            try:
                parsed_items, _summary = module.build_questions(records, module_report, input_dir)
            finally:
                module.require_complete_offline_set = original_gate
        else:
            parsed_items, _summary = module.build_questions(records, module_report, input_dir)
        groups = module.build_groups(records)
        sessions = module.build_session_map(groups)
        items_by_group: dict[int, list[object]] = {}
        for item in parsed_items:
            items_by_group.setdefault(int(item.group_index), []).append(item)
        for group_index, group in enumerate(groups, start=1):
            items = items_by_group.get(group_index, [])
            expected_count = int(group.get("question_count") or (20 if module is maritime_english else 0))
            answer_path = _registered_answer_path(module, group, group_index, root)
            source_path = Path(str(group["pages"][0]["source_path"]))
            expected = ExpectedExamSet(
                module.EXAM_CODE,
                module.SUBJECT_NAME,
                int(group["year"]),
                int(sessions[group_index]),
                tuple(range(1, expected_count + 1)),
                require_answers=not (
                    module is police_engineering
                    and str(group.get("answer_key") or "") in module.NO_SOURCE_ANSWER_KEYS
                ),
            )
            registered.append(
                RegisteredExamSet(
                    expected,
                    tuple(item.question for item in items),
                    source_path,
                    answer_path,
                )
            )

    for path in native_paths:
        metadata = _infer_document_metadata(path, root)
        expected_count = metadata.get("expected_question_count")
        if not isinstance(expected_count, int) or expected_count < 1:
            raise ValueError(f"native 2023 coverage is not registered: {path.name}")
        parsed = parse_offline_question_pdf(path, metadata)
        expected_numbers = tuple(range(1, expected_count + 1))
        answers, answer_path = _resolve_answer_key(path, root, metadata, expected_numbers)
        if answer_path is None:
            raise ValueError(f"native 2023 answer association missing: {path.name}")
        questions = tuple(
            Question(
                item.number,
                item.stem,
                [Choice(index, CHOICE_SYMBOLS[index - 1], text) for index, text in enumerate(item.choices, 1)],
                int(answers.get(item.number, 0)),
                source_page=item.source_page,
                subject_name=str(metadata["subject_name"]),
                year=int(metadata["year"]),
                session=int(metadata["session"]),
                exam_type=str(metadata["exam_type"]),
            )
            for item in parsed.questions
        )
        registered.append(
            RegisteredExamSet(
                ExpectedExamSet(
                    str(metadata["exam_type"]), str(metadata["subject_name"]),
                    int(metadata["year"]), int(metadata["session"]), expected_numbers,
                ),
                questions,
                path,
                answer_path,
                len(parsed.rejected),
            )
        )
    return registered


def _registered_answer_path(module: object, group: Mapping[str, object], group_index: int, root: Path) -> Path:
    filenames = getattr(module, "ANSWER_FILENAMES")
    bucket: str | None = None
    answer_key = str(group.get("answer_key") or "")
    answer_keys = getattr(module, "ANSWER_KEYS", {})
    for candidate, keys in answer_keys.items():
        if answer_key in keys:
            bucket = candidate
            break
    if bucket is None and "english" in str(getattr(module, "__name__", "")):
        bucket = "recent_2025_h2" if group_index == 1 else (
            "recent_2024_h2_2025_h1" if group_index <= 4 else "archive_2024_2013"
        )
    if bucket is None:
        raise ValueError(f"registered answer association missing for group {group_index}")
    matches = list(root.rglob(str(filenames[bucket])))
    if len(matches) != 1:
        raise ValueError(f"registered answer file missing or ambiguous: {filenames[bucket]}")
    return matches[0]


def _write_inventory(path: Path, inventory: Sequence[Mapping[str, object]]) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO offline_rebuild_documents (relative_path, role, sha256, size)
            VALUES (?, ?, ?, ?)
            """,
            [
                (row["relative_path"], row["role"], row["sha256"], row["size"])
                for row in inventory
            ],
        )


def _mark_document_build(
    path: Path,
    relative_path: str,
    *,
    parsed_question_count: int,
    build_error: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            UPDATE offline_rebuild_documents
            SET parsed_question_count = ?, build_error = ?
            WHERE relative_path = ?
            """,
            (parsed_question_count, build_error, relative_path),
        )


def _infer_document_metadata(path: Path, root: Path) -> dict[str, object]:
    from scripts.import_public_exam_pdf_folder import infer_meta

    metadata = infer_meta(path, root)
    return {
        "exam_type": metadata.exam_type,
        "subject_name": metadata.subject_name,
        "year": metadata.year,
        "session": metadata.session,
        "document_id": metadata.document_id,
        "expected_question_count": metadata.expected_question_count,
        "probe": {"role": metadata.role},
    }


def _resolve_answer_key(
    question_path: Path,
    root: Path,
    metadata: Mapping[str, object],
    expected_numbers: Sequence[int],
) -> tuple[dict[int, int], Path | None]:
    from scripts.import_public_exam_pdf_folder import (
        clean_pdf_text,
        expand_parser_lines,
        find_answer_pair,
        infer_meta,
        parse_gong_answer_key,
        replace_boundary_markers,
    )

    importer_metadata = infer_meta(question_path, root)
    answer_path = find_answer_pair(question_path, importer_metadata)
    if answer_path is None:
        return {}, None
    answer_text = clean_pdf_text(answer_path)
    answer_lines = replace_boundary_markers(
        expand_parser_lines(answer_text.lines), str(metadata["subject_name"])
    )
    return parse_gong_answer_key(answer_lines, list(expected_numbers)), answer_path


def _insert_question_source(
    database_path: Path,
    question_path: Path,
    document_id: str,
    content_hash: str,
    answer_path: Path | None,
) -> int:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO question_sources (
                provider, source_url, document_id, attachment_url,
                attachment_filename, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "offline_pdf",
                question_path.resolve().as_uri(),
                document_id,
                answer_path.resolve().as_uri() if answer_path else None,
                answer_path.name if answer_path else question_path.name,
                content_hash,
            ),
        )
        row = connection.execute(
            """
            SELECT id FROM question_sources
            WHERE provider = 'offline_pdf' AND source_url = ? AND content_hash = ?
            """,
            (question_path.resolve().as_uri(), content_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"failed to register source provenance: {question_path}")
        return int(row[0])


def _attach_provenance(
    database_path: Path,
    metadata: Mapping[str, object],
    question_numbers: Sequence[int],
    source_id: int,
) -> None:
    if not question_numbers:
        return
    placeholders = ",".join("?" for _ in question_numbers)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            f"""
            UPDATE questions
            SET source_id = ?
            WHERE id IN (
                SELECT q.id
                FROM questions q
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN exams e ON es.exam_id = e.id
                JOIN subjects s ON es.subject_id = s.id
                WHERE e.code = ? AND s.name_ko = ? AND q.year = ? AND q.session = ?
                  AND q.question_number IN ({placeholders})
            )
            """,
            (
                source_id,
                str(metadata["exam_type"]),
                str(metadata["subject_name"]),
                int(metadata["year"]),
                int(metadata["session"]),
                *question_numbers,
            ),
        )


def _store_expected_sets(path: Path, expected_sets: Sequence[ExpectedExamSet]) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO offline_rebuild_expected_sets (
                exam_type, subject_name, year, session, question_numbers_json,
                require_answers, require_provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.exam_type,
                    item.subject_name,
                    item.year,
                    item.session,
                    json.dumps(item.question_numbers),
                    int(item.require_answers),
                    int(item.require_provenance),
                )
                for item in expected_sets
            ],
        )


def _load_expected_sets(path: Path) -> tuple[ExpectedExamSet, ...]:
    try:
        with _readonly_connection(path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'offline_rebuild_expected_sets'"
            ).fetchone()
            if not exists:
                return ()
            rows = connection.execute(
                """
                SELECT exam_type, subject_name, year, session, question_numbers_json,
                       require_answers, require_provenance
                FROM offline_rebuild_expected_sets
                ORDER BY exam_type, subject_name, year, session
                """
            ).fetchall()
    except sqlite3.DatabaseError:
        return ()
    return tuple(
        ExpectedExamSet(
            exam_type=str(row[0]),
            subject_name=str(row[1]),
            year=int(row[2]),
            session=int(row[3]),
            question_numbers=tuple(json.loads(row[4])),
            require_answers=bool(row[5]),
            require_provenance=bool(row[6]),
        )
        for row in rows
    )


def _coerce_expected_set(value: ExpectedExamSet | Mapping[str, object]) -> ExpectedExamSet:
    if isinstance(value, ExpectedExamSet):
        return value
    raw_numbers = value.get("question_numbers", value.get("expected_numbers"))
    if raw_numbers is None:
        count = int(value.get("expected_count", 0))
        raw_numbers = range(1, count + 1)
    return ExpectedExamSet(
        exam_type=str(value.get("exam_type", value.get("exam", ""))),
        subject_name=str(value.get("subject_name", value.get("subject", ""))),
        year=int(value["year"]),
        session=int(value["session"]),
        question_numbers=tuple(int(number) for number in raw_numbers),  # type: ignore[arg-type]
        require_answers=bool(value.get("require_answers", True)),
        require_provenance=bool(value.get("require_provenance", True)),
    )


def _validate_expected_set(
    connection: sqlite3.Connection, expected: ExpectedExamSet
) -> ExamSetValidation:
    rows = connection.execute(
        """
        SELECT q.question_number, q.correct_answer, q.source_id,
               COUNT(qc.id) AS choice_count
        FROM questions q
        JOIN exam_subjects es ON q.exam_subject_id = es.id
        JOIN exams e ON es.exam_id = e.id
        JOIN subjects s ON es.subject_id = s.id
        LEFT JOIN question_choices qc ON qc.question_id = q.id
        WHERE e.code = ? AND s.name_ko = ? AND q.year = ? AND q.session = ?
        GROUP BY q.id, q.question_number, q.correct_answer, q.source_id
        ORDER BY q.question_number
        """,
        expected.key,
    ).fetchall()
    actual = tuple(int(row[0]) for row in rows)
    expected_numbers = set(expected.question_numbers)
    actual_numbers = set(actual)
    by_number = {int(row[0]): row for row in rows}
    missing_answers = tuple(
        number
        for number in expected.question_numbers
        if expected.require_answers
        and (
            number not in by_number
            or not isinstance(by_number[number][1], int)
            or int(by_number[number][1]) < 1
            or int(by_number[number][1]) > int(by_number[number][3])
        )
    )
    missing_provenance = tuple(
        number
        for number in expected.question_numbers
        if expected.require_provenance
        and number in by_number
        and by_number[number][2] is None
    )
    return ExamSetValidation(
        expected=expected,
        actual_numbers=actual,
        missing_numbers=tuple(sorted(expected_numbers - actual_numbers)),
        unexpected_numbers=tuple(sorted(actual_numbers - expected_numbers)),
        missing_answers=missing_answers,
        missing_provenance=missing_provenance,
    )


def _validate_application_schema(
    connection: sqlite3.Connection,
) -> tuple[bool, tuple[str, ...]]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    details: list[str] = []
    for table, required_columns in REQUIRED_SCHEMA.items():
        if table not in tables:
            details.append(f"missing table: {table}")
            continue
        columns = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing = sorted(required_columns - columns)
        if missing:
            details.append(f"missing columns in {table}: {', '.join(missing)}")
    return not details, tuple(details)


def _database_counts(path: Path) -> dict[str, int]:
    with _readonly_connection(path) as connection:
        return _database_counts_from_connection(connection)


def _database_counts_from_connection(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("exams", "subjects", "exam_subjects", "question_sources", "questions", "question_choices")
    }


def _valid_answer_count(path: Path) -> int:
    with _readonly_connection(path) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM questions WHERE correct_answer BETWEEN 1 AND 5"
            ).fetchone()[0]
        )


@contextmanager
def _readonly_connection(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        yield connection
    finally:
        connection.close()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _url_filename(value: str) -> str:
    parsed = urlparse(value)
    raw_path = parsed.path if parsed.scheme else value
    return Path(unquote(raw_path.replace("\\", "/"))).name


def _fsync_file(path: Path) -> None:
    # Windows' CRT rejects fsync on some read-only descriptors.
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _backup_sqlite_database(source: Path, destination: Path) -> None:
    """Create a transactionally consistent snapshot, including committed WAL pages."""

    source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    _fsync_file(destination)


def _validate_backup_database(path: Path) -> None:
    """Verify snapshot transport without applying new-staging content policy to legacy data."""

    with _readonly_connection(path) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        schema_valid, details = _validate_application_schema(connection)
    if integrity != "ok" or foreign_keys or not schema_valid:
        raise ReplacementError(
            f"backup validation failed: integrity={integrity} "
            f"foreign_keys={len(foreign_keys)} schema={details}"
        )


def _smoke_mounted_repository(database_path: Path) -> None:
    """Exercise the production mounted-repository adapter through a temporary manifest."""

    from experiments.db_mount_prototype.mount_repo import (
        MountedDatabase,
        MountedExamRepository,
        write_manifest,
    )

    with tempfile.TemporaryDirectory(prefix="offline-mounted-smoke-") as raw_dir:
        manifest = Path(raw_dir) / "mount_manifest.json"
        write_manifest(
            manifest,
            [MountedDatabase(id="staging_smoke", label="Staging Smoke", path=database_path)],
        )
        repository = MountedExamRepository(manifest)
        rows = repository.search_questions(limit=1)
        expected_count = _database_counts(database_path).get("questions", 0)
        if expected_count and not rows:
            raise ReplacementError("mounted repository smoke query returned no questions")


def _atomic_replace(source: Path, target: Path) -> None:
    """Retry only transient Windows sharing violations; each attempt stays atomic."""

    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _write_inventory_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["relative_path", "role", "sha256", "size"])
        writer.writeheader()
        writer.writerows(rows)


def _write_validation_csv(path: Path, rows: Sequence[ExamSetValidation]) -> None:
    fieldnames = [
        "exam_type",
        "subject_name",
        "year",
        "session",
        "valid",
        "actual_numbers",
        "missing_numbers",
        "unexpected_numbers",
        "missing_answers",
        "missing_provenance",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "exam_type": row.expected.exam_type,
                    "subject_name": row.expected.subject_name,
                    "year": row.expected.year,
                    "session": row.expected.session,
                    "valid": row.valid,
                    "actual_numbers": json.dumps(row.actual_numbers),
                    "missing_numbers": json.dumps(row.missing_numbers),
                    "unexpected_numbers": json.dumps(row.unexpected_numbers),
                    "missing_answers": json.dumps(row.missing_answers),
                    "missing_provenance": json.dumps(row.missing_provenance),
                }
            )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
