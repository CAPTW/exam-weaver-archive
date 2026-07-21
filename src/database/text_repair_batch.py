"""Prepare and atomically commit a validated batch of DB text repairs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import gc
from contextlib import closing
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from src.database.ocr_repairs import OcrRepairResult, apply_audited_repairs
from src.database.repository import ExamRepository
from src.database.staging import REQUIRED_SCHEMA
from src.database.text_repair import (
    AuditSummary,
    apply_changes,
    collect_changes,
    collect_findings,
    collect_surface_counts,
)


@dataclass(frozen=True)
class RepairTarget:
    name: str
    mounted_path: Path


@dataclass(frozen=True)
class DatabaseRepairValidation:
    valid: bool
    integrity_check: str
    foreign_key_errors: tuple[tuple[object, ...], ...]
    schema_errors: tuple[str, ...]
    smoke_ok: bool
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class PreparedDatabaseRepair:
    target: RepairTarget
    staging_path: Path
    original_sha256: str
    staging_sha256: str
    audit: AuditSummary
    source_repair_result: OcrRepairResult
    validation: DatabaseRepairValidation


class BatchRepairError(RuntimeError):
    """Raised when preparation, replacement, or rollback is unsafe."""


def prepare_repair_batch(
    targets: Sequence[RepairTarget],
    repairs_path: str | Path | Sequence[str | Path],
    work_dir: str | Path,
) -> tuple[PreparedDatabaseRepair, ...]:
    """Build and validate every staging DB without changing any mount."""

    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    repair_paths = _normalize_repair_paths(repairs_path)
    prepared: list[PreparedDatabaseRepair] = []
    seen_targets: set[Path] = set()
    for target in targets:
        mounted = Path(target.mounted_path).resolve()
        if mounted in seen_targets:
            raise BatchRepairError(f"duplicate mounted database: {mounted}")
        seen_targets.add(mounted)
        if not mounted.is_file():
            raise BatchRepairError(
                f"mounted database does not exist: {mounted}"
            )

        staging_path = work / f"{target.name}.staging.db"
        _copy_sqlite_database(mounted, staging_path)
        source_result = _empty_ocr_repair_result()
        for repair_path in repair_paths:
            source_result = _sum_ocr_repair_results(
                source_result,
                apply_audited_repairs(
                    staging_path,
                    repair_path,
                    allow_unmatched=True,
                ),
            )
        with closing(sqlite3.connect(staging_path)) as connection:
            connection.row_factory = sqlite3.Row
            protected_question_ids = _protected_source_question_ids(
                connection,
                repair_paths,
            )
            changes, skipped = collect_changes(
                connection,
                confusables_only=True,
                protected_question_ids=protected_question_ids,
            )
            if skipped:
                raise BatchRepairError(
                    f"formatted repairs skipped for {target.name}: "
                    f"{len(skipped)}"
                )
            if changes:
                apply_changes(connection, changes)
            findings = tuple(collect_findings(connection))
            surface_counts = collect_surface_counts(connection)

        validation = _validate_repair_database(staging_path)
        blocked = tuple(
            finding
            for finding in findings
            if finding.severity == "blocked_quality"
        )
        if blocked or not validation.valid:
            codes = [finding.category for finding in blocked]
            codes.extend(validation.error_codes)
            raise BatchRepairError(
                f"{target.name}: " + ", ".join(dict.fromkeys(codes))
            )
        prepared.append(PreparedDatabaseRepair(
            target=RepairTarget(target.name, mounted),
            staging_path=staging_path,
            original_sha256=sha256_file(mounted),
            staging_sha256=sha256_file(staging_path),
            audit=AuditSummary(
                surface_counts=surface_counts,
                changes=tuple(changes),
                findings=findings,
            ),
            source_repair_result=source_result,
            validation=validation,
        ))
    return tuple(prepared)


def _normalize_repair_paths(
    repairs_path: str | Path | Sequence[str | Path],
) -> tuple[Path, ...]:
    values = (
        (repairs_path,)
        if isinstance(repairs_path, (str, Path))
        else tuple(repairs_path)
    )
    paths = tuple(Path(value).resolve() for value in values)
    if not paths:
        raise BatchRepairError("at least one repair registry is required")
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise BatchRepairError(
            "repair registry does not exist: " + ", ".join(missing)
        )
    return paths


def _empty_ocr_repair_result() -> OcrRepairResult:
    return OcrRepairResult(*(0 for _ in fields(OcrRepairResult)))


def _sum_ocr_repair_results(
    left: OcrRepairResult,
    right: OcrRepairResult,
) -> OcrRepairResult:
    return OcrRepairResult(*(
        int(getattr(left, item.name)) + int(getattr(right, item.name))
        for item in fields(OcrRepairResult)
    ))


def _protected_source_question_ids(
    connection: sqlite3.Connection,
    repair_paths: Sequence[Path],
) -> set[int]:
    """Resolve source-confirmed natural keys so auto repair cannot override them."""

    rows = connection.execute(
        """
        SELECT q.id, q.year, q.session, q.question_number,
               e.code AS exam_code, s.code AS subject_code,
               s.name_ko AS subject_name
        FROM questions q
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        """
    ).fetchall()
    by_id = {int(row["id"]): row for row in rows}
    by_codes: dict[tuple[object, ...], list[int]] = {}
    by_subject: dict[tuple[object, ...], list[int]] = {}
    for row in rows:
        suffix = (
            int(row["year"]),
            int(row["session"]),
            int(row["question_number"]),
        )
        by_codes.setdefault((
            str(row["exam_code"]),
            str(row["subject_code"]),
            *suffix,
        ), []).append(int(row["id"]))
        by_subject.setdefault((
            str(row["subject_name"]),
            *suffix,
        ), []).append(int(row["id"]))

    protected: set[int] = set()
    for repair_path in repair_paths:
        payload = json.loads(repair_path.read_text(encoding="utf-8"))
        for repair in payload.get("repairs", []):
            if repair.get("confidence") != "exact_source":
                continue
            has_exam_identity = (
                repair.get("year") is not None
                and repair.get("session") is not None
            )
            candidates: list[int]
            if has_exam_identity:
                suffix = (
                    int(repair["year"]),
                    int(repair["session"]),
                    int(repair["question_number"]),
                )
                exam_code = str(repair.get("exam_code") or "").strip()
                subject_code = str(
                    repair.get("subject_code") or ""
                ).strip()
                if exam_code and subject_code:
                    candidates = by_codes.get((
                        exam_code,
                        subject_code,
                        *suffix,
                    ), [])
                else:
                    candidates = by_subject.get((
                        str(repair.get("subject") or "").strip(),
                        *suffix,
                    ), [])
            else:
                question_id = int(repair.get("question_id") or 0)
                row = by_id.get(question_id)
                candidates = (
                    [question_id]
                    if row is not None
                    and int(row["question_number"])
                    == int(repair["question_number"])
                    else []
                )
            if len(candidates) > 1:
                raise BatchRepairError(
                    "source-confirmed repair identity is not unique: "
                    f"{repair_path}: {candidates}"
                )
            protected.update(candidates)
    return protected


def commit_repair_batch(
    prepared: Sequence[PreparedDatabaseRepair],
    backup_dir: str | Path,
    receipt_path: str | Path,
) -> dict[str, object]:
    """Replace all prepared DBs or restore every changed mount."""

    if not prepared:
        raise BatchRepairError("repair batch is empty")
    backups = _prepare_all_backups(
        prepared,
        Path(backup_dir).resolve(),
    )
    replacements = _prepare_all_replacement_copies(prepared)
    receipt_file = Path(receipt_path).resolve()
    try:
        gc.collect()
        for item in prepared:
            _atomic_replace(
                replacements[item.target.name],
                item.target.mounted_path,
            )
        for item in prepared:
            validation = _validate_repair_database(
                item.target.mounted_path
            )
            if not validation.valid:
                raise BatchRepairError(
                    "post-replacement validation failed: "
                    f"{item.target.name}: {validation.error_codes}"
                )
            if sha256_file(item.target.mounted_path) != item.staging_sha256:
                raise BatchRepairError(
                    f"post-replacement hash mismatch: {item.target.name}"
                )

        receipt: dict[str, object] = {
            "status": "applied",
            "targets": [
                {
                    "name": item.target.name,
                    "mounted_path": str(item.target.mounted_path),
                    "backup_path": str(backups[item.target.name]),
                    "before_sha256": item.original_sha256,
                    "after_sha256": sha256_file(
                        item.target.mounted_path
                    ),
                }
                for item in prepared
            ],
        }
        _write_json_atomic(receipt_file, receipt)
        return receipt
    except Exception as error:
        restore_errors: list[str] = []
        for item in prepared:
            try:
                current_hash = sha256_file(item.target.mounted_path)
            except OSError as hash_error:
                restore_errors.append(
                    f"{item.target.name} hash: {hash_error}"
                )
                current_hash = ""
            if current_hash != item.original_sha256:
                try:
                    _restore_backup(
                        backups[item.target.name],
                        item.target.mounted_path,
                    )
                except Exception as restore_error:
                    restore_errors.append(
                        f"{item.target.name}: {restore_error}"
                    )
        if restore_errors:
            raise BatchRepairError(
                f"{error}; rollback failed: {'; '.join(restore_errors)}"
            ) from error
        raise BatchRepairError(str(error)) from error
    finally:
        for replacement in replacements.values():
            replacement.unlink(missing_ok=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_repair_database(path: Path) -> DatabaseRepairValidation:
    integrity = "error"
    foreign_keys: tuple[tuple[object, ...], ...] = ()
    schema_errors: list[str] = []
    error_codes: list[str] = []
    try:
        with closing(_readonly_connection(path)) as connection:
            integrity = str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            if integrity != "ok":
                error_codes.append("sqlite_integrity")
            foreign_keys = tuple(
                tuple(row)
                for row in connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            )
            if foreign_keys:
                error_codes.append("foreign_key_check")
            schema_errors.extend(_schema_errors(connection))
            if schema_errors:
                error_codes.append("application_schema")
            connection.row_factory = sqlite3.Row
            blocked = [
                finding
                for finding in collect_findings(connection)
                if finding.severity == "blocked_quality"
            ]
            if blocked:
                error_codes.extend(
                    finding.category for finding in blocked
                )
    except (OSError, sqlite3.DatabaseError, ValueError):
        error_codes.append("database_read")

    smoke_ok = False
    if not error_codes:
        try:
            _smoke_repository(path)
            smoke_ok = True
        except (OSError, sqlite3.DatabaseError, ValueError, KeyError):
            error_codes.append("repository_smoke")
    return DatabaseRepairValidation(
        valid=not error_codes,
        integrity_check=integrity,
        foreign_key_errors=foreign_keys,
        schema_errors=tuple(schema_errors),
        smoke_ok=smoke_ok,
        error_codes=tuple(dict.fromkeys(error_codes)),
    )


def _schema_errors(connection: sqlite3.Connection) -> list[str]:
    errors: list[str] = []
    for table, required_columns in REQUIRED_SCHEMA.items():
        columns = {
            str(row[1])
            for row in connection.execute(
                f'PRAGMA table_info("{table}")'
            ).fetchall()
        }
        missing = sorted(required_columns - columns)
        if missing:
            errors.append(f"{table}: missing {','.join(missing)}")
    return errors


class _ReadOnlyRepairRepository(ExamRepository):
    def __init__(self, path: Path):
        super().__init__(str(path.resolve()))
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        path = Path(self.db_path).resolve()
        return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _smoke_repository(path: Path) -> None:
    repository = _ReadOnlyRepairRepository(path)
    statistics = repository.get_statistics()
    total = int(statistics.get("total_questions", 0) or 0)
    rows = repository.search_questions(limit=1)
    if total and not rows:
        raise ValueError("repository returned no row for non-empty DB")
    if rows and repository.get_question(int(rows[0]["id"])) is None:
        raise ValueError("repository could not reload sampled question")


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with closing(sqlite3.connect(source)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)
    _fsync_file(destination)


def _prepare_all_backups(
    prepared: Sequence[PreparedDatabaseRepair],
    backup_dir: Path,
) -> dict[str, Path]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups: dict[str, Path] = {}
    for item in prepared:
        backup = backup_dir / f"{item.target.name}.before.db"
        wal_path = item.target.mounted_path.with_name(
            item.target.mounted_path.name + "-wal"
        )
        if wal_path.is_file() and wal_path.stat().st_size:
            raise BatchRepairError(
                f"active WAL prevents byte-exact backup: {item.target.name}"
            )
        shutil.copy2(item.target.mounted_path, backup)
        _fsync_file(backup)
        if sha256_file(backup) != item.original_sha256:
            raise BatchRepairError(
                f"backup hash mismatch: {item.target.name}"
            )
        validation = _validate_repair_database(backup)
        if not validation.valid:
            raise BatchRepairError(
                f"backup validation failed: {item.target.name}"
            )
        backups[item.target.name] = backup
    return backups


def _prepare_all_replacement_copies(
    prepared: Sequence[PreparedDatabaseRepair],
) -> dict[str, Path]:
    replacements: dict[str, Path] = {}
    try:
        for item in prepared:
            replacement = item.target.mounted_path.with_name(
                f".{item.target.mounted_path.name}.{uuid4().hex}.replacement.tmp"
            )
            shutil.copy2(item.staging_path, replacement)
            _fsync_file(replacement)
            if sha256_file(replacement) != item.staging_sha256:
                raise BatchRepairError(
                    f"replacement copy hash mismatch: {item.target.name}"
                )
            replacements[item.target.name] = replacement
        return replacements
    except Exception:
        for replacement in replacements.values():
            replacement.unlink(missing_ok=True)
        raise


def _restore_backup(backup: Path, mounted: Path) -> None:
    validation = _validate_repair_database(backup)
    if not validation.valid:
        raise BatchRepairError(f"rollback backup is invalid: {backup}")
    rollback = mounted.with_name(
        f".{mounted.name}.{uuid4().hex}.rollback.tmp"
    )
    try:
        shutil.copy2(backup, rollback)
        _fsync_file(rollback)
        gc.collect()
        _atomic_replace(rollback, mounted)
    finally:
        rollback.unlink(missing_ok=True)


def _readonly_connection(path: Path):
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())


def _atomic_replace(source: Path, target: Path) -> None:
    os.replace(source, target)


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _fsync_file(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
