"""Fail-closed staging migration for explicit Korean view-block tables."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Iterable

from ..parser.view_table import promote_view_block


@dataclass(frozen=True)
class ViewTableMigrationReport:
    source_db: Path
    staging_db: Path
    eligible_questions: int
    promoted_questions: int
    source_question_count: int
    staging_question_count: int
    source_choice_count: int
    staging_choice_count: int
    integrity_ok: bool
    foreign_keys_ok: bool
    non_target_mismatches: int
    promotion_mismatches: int

    @property
    def valid(self) -> bool:
        return all(
            (
                self.integrity_ok,
                self.foreign_keys_ok,
                self.source_question_count == self.staging_question_count,
                self.source_choice_count == self.staging_choice_count,
                self.promoted_questions == self.eligible_questions,
                self.non_target_mismatches == 0,
                self.promotion_mismatches == 0,
            )
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["source_db"] = str(self.source_db)
        payload["staging_db"] = str(self.staging_db)
        payload["valid"] = self.valid
        return payload


@dataclass(frozen=True)
class ViewTableReplacementReceipt:
    source_db: Path
    staging_db: Path
    backup_path: Path
    backup_sha256: str
    staging_sha256: str
    mounted_sha256: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        for key in ("source_db", "staging_db", "backup_path"):
            payload[key] = str(payload[key])
        return payload


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]


def _ordered_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: Iterable[str],
) -> list[tuple]:
    names = list(columns)
    if not names:
        return []
    order = "id" if "id" in names else "rowid"
    select = ", ".join(f'"{name}"' for name in names)
    return [
        tuple(row)
        for row in connection.execute(
            f'SELECT {select} FROM "{table}" ORDER BY "{order}"'
        ).fetchall()
    ]


def _mismatch_count(left: list[tuple], right: list[tuple]) -> int:
    sentinel = object()
    return sum(
        1
        for first, second in zip_longest(left, right, fillvalue=sentinel)
        if first != second
    )


def _copy_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with closing(_readonly_connection(source)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_replace(source: Path, target: Path) -> None:
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _health(path: Path) -> tuple[bool, bool]:
    with closing(_readonly_connection(path)) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    return bool(integrity and integrity[0] == "ok"), not foreign_keys


def build_view_table_staging(
    source_db: str | Path,
    staging_db: str | Path,
) -> ViewTableMigrationReport:
    """Copy a database and promote eligible question stems transactionally."""
    source = Path(source_db).resolve()
    staging = Path(staging_db).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == staging:
        raise ValueError("source and staging database paths must differ")
    _copy_sqlite(source, staging)

    with closing(sqlite3.connect(staging)) as connection:
        connection.row_factory = sqlite3.Row
        columns = _columns(connection, "questions")
        required = {"id", "question_text", "question_format_json"}
        if not required.issubset(columns):
            raise ValueError("questions table lacks view-table migration columns")
        rows = connection.execute(
            "SELECT id, question_text, question_format_json FROM questions ORDER BY id"
        ).fetchall()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for row in rows:
                text, encoded, changed = promote_view_block(
                    row["question_text"],
                    row["question_format_json"],
                )
                if not changed:
                    continue
                connection.execute(
                    "UPDATE questions SET question_text = ?, question_format_json = ? "
                    "WHERE id = ?",
                    (text, encoded, int(row["id"])),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return validate_view_table_staging(source, staging)


def validate_view_table_staging(
    source_db: str | Path,
    staging_db: str | Path,
) -> ViewTableMigrationReport:
    """Compare staging with its source and reject all unrelated changes."""
    source = Path(source_db).resolve()
    staging = Path(staging_db).resolve()
    if not source.is_file() or not staging.is_file():
        raise FileNotFoundError(source if not source.is_file() else staging)
    integrity_ok, foreign_keys_ok = _health(staging)

    with closing(_readonly_connection(source)) as source_connection:
        with closing(_readonly_connection(staging)) as staging_connection:
            source_columns = _columns(source_connection, "questions")
            staging_columns = _columns(staging_connection, "questions")
            if source_columns != staging_columns:
                raise ValueError("source and staging question schemas differ")
            source_questions = source_connection.execute(
                "SELECT id, question_text, question_format_json FROM questions ORDER BY id"
            ).fetchall()
            staging_questions = {
                int(row["id"]): row
                for row in staging_connection.execute(
                    "SELECT id, question_text, question_format_json FROM questions ORDER BY id"
                ).fetchall()
            }

            eligible = 0
            promoted = 0
            promotion_mismatches = 0
            for source_row in source_questions:
                expected_text, expected_json, changed = promote_view_block(
                    source_row["question_text"],
                    source_row["question_format_json"],
                )
                staging_row = staging_questions.get(int(source_row["id"]))
                if staging_row is None:
                    promotion_mismatches += 1
                    continue
                if changed:
                    eligible += 1
                    if (
                        staging_row["question_text"] == expected_text
                        and staging_row["question_format_json"] == expected_json
                    ):
                        promoted += 1
                    else:
                        promotion_mismatches += 1
                elif (
                    staging_row["question_text"] != source_row["question_text"]
                    or staging_row["question_format_json"]
                    != source_row["question_format_json"]
                ):
                    promotion_mismatches += 1

            non_target_columns = [
                name
                for name in source_columns
                if name not in {"question_text", "question_format_json"}
            ]
            non_target_mismatches = _mismatch_count(
                _ordered_rows(source_connection, "questions", non_target_columns),
                _ordered_rows(staging_connection, "questions", non_target_columns),
            )

            source_choice_count = 0
            staging_choice_count = 0
            source_has_choices = _table_exists(source_connection, "question_choices")
            staging_has_choices = _table_exists(staging_connection, "question_choices")
            if source_has_choices != staging_has_choices:
                non_target_mismatches += 1
            elif source_has_choices:
                choice_columns = _columns(source_connection, "question_choices")
                if choice_columns != _columns(staging_connection, "question_choices"):
                    non_target_mismatches += 1
                else:
                    source_choices = _ordered_rows(
                        source_connection,
                        "question_choices",
                        choice_columns,
                    )
                    staging_choices = _ordered_rows(
                        staging_connection,
                        "question_choices",
                        choice_columns,
                    )
                    source_choice_count = len(source_choices)
                    staging_choice_count = len(staging_choices)
                    non_target_mismatches += _mismatch_count(
                        source_choices,
                        staging_choices,
                    )

    return ViewTableMigrationReport(
        source_db=source,
        staging_db=staging,
        eligible_questions=eligible,
        promoted_questions=promoted,
        source_question_count=len(source_questions),
        staging_question_count=len(staging_questions),
        source_choice_count=source_choice_count,
        staging_choice_count=staging_choice_count,
        integrity_ok=integrity_ok,
        foreign_keys_ok=foreign_keys_ok,
        non_target_mismatches=non_target_mismatches,
        promotion_mismatches=promotion_mismatches,
    )


def replace_with_view_table_staging(
    source_db: str | Path,
    staging_db: str | Path,
    backup_dir: str | Path,
) -> ViewTableReplacementReceipt:
    """Back up and atomically replace a database only after exact validation."""
    source = Path(source_db).resolve()
    staging = Path(staging_db).resolve()
    backups = Path(backup_dir).resolve()
    if source == staging:
        raise ValueError("source and staging database paths must differ")
    report = validate_view_table_staging(source, staging)
    if not report.valid:
        raise ValueError("view-table staging validation failed")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backups.mkdir(parents=True, exist_ok=True)
    backup = backups / f"{source.stem}.pre_view_tables.{stamp}{source.suffix}"
    _copy_sqlite(source, backup)
    backup_sha256 = _sha256(backup)
    staging_sha256 = _sha256(staging)
    replacement = source.with_name(f".{source.name}.{stamp}.replacement.tmp")
    rollback = source.with_name(f".{source.name}.{stamp}.rollback.tmp")
    replaced = False
    try:
        shutil.copy2(staging, replacement)
        if _sha256(replacement) != staging_sha256 or not all(_health(replacement)):
            raise ValueError("replacement copy validation failed")
        _atomic_replace(replacement, source)
        replaced = True
        mounted_sha256 = _sha256(source)
        if mounted_sha256 != staging_sha256 or not all(_health(source)):
            raise ValueError("mounted database differs from validated staging")
    except Exception:
        if replaced:
            shutil.copy2(backup, rollback)
            _atomic_replace(rollback, source)
        raise
    finally:
        if replacement.exists():
            replacement.unlink()
        if rollback.exists():
            rollback.unlink()

    return ViewTableReplacementReceipt(
        source_db=source,
        staging_db=staging,
        backup_path=backup,
        backup_sha256=backup_sha256,
        staging_sha256=staging_sha256,
        mounted_sha256=mounted_sha256,
    )
