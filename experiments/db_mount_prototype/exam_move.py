from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote


class ExamMoveError(RuntimeError):
    pass


class ExamMoveConflict(ExamMoveError):
    pass


@dataclass(frozen=True)
class ExamMoveIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class ExamMovePlan:
    source_db: str
    target_db: str
    exam_code: str
    can_apply: bool
    issues: List[ExamMoveIssue] = field(default_factory=list)
    source_exam_id: Optional[int] = None
    target_existing_exam_id: Optional[int] = None
    counts: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ExamMoveResult:
    moved: bool
    plan: ExamMovePlan
    target_exam_id: Optional[int] = None
    source_backup: Optional[str] = None
    target_backup: Optional[str] = None


@dataclass(frozen=True)
class ExamCopyResult:
    copied: bool
    plan: ExamMovePlan
    target_exam_id: Optional[int] = None
    target_backup: Optional[str] = None


REQUIRED_TABLES = {
    "exams",
    "subjects",
    "exam_subjects",
    "question_sources",
    "question_groups",
    "questions",
    "question_choices",
    "mock_exams",
    "mock_exam_questions",
    "exam_results",
}


def dry_run_exam_move(source_db: str | Path, target_db: str | Path, exam_code: str) -> ExamMovePlan:
    source = Path(source_db).resolve()
    target = Path(target_db).resolve()
    issues: List[ExamMoveIssue] = []
    counts: Dict[str, int] = {
        "exam_subjects": 0,
        "subjects": 0,
        "questions": 0,
        "choices": 0,
        "groups": 0,
        "sources": 0,
        "mock_exams_removed": 0,
    }
    source_exam_id = None
    target_existing_exam_id = None

    if source == target:
        issues.append(ExamMoveIssue("same_database", "source and target database are the same"))
    if not source.exists():
        issues.append(ExamMoveIssue("source_missing", f"source database not found: {source}"))
    if not target.exists():
        issues.append(ExamMoveIssue("target_missing", f"target database not found: {target}"))

    if not issues:
        try:
            with _connect(source) as conn:
                _require_schema(conn, "source")
                row = conn.execute(
                    "SELECT id FROM exams WHERE code = ?",
                    (exam_code,),
                ).fetchone()
                if row is None:
                    issues.append(ExamMoveIssue("source_exam_missing", f"exam not found in source: {exam_code}"))
                else:
                    source_exam_id = int(row["id"])
                    counts = _exam_counts(conn, source_exam_id)
                fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_errors:
                    issues.append(ExamMoveIssue(
                        "source_fk_errors",
                        f"source database has {len(fk_errors)} foreign key errors",
                    ))

            with _connect(target) as conn:
                _require_schema(conn, "target")
                row = conn.execute(
                    "SELECT id FROM exams WHERE code = ?",
                    (exam_code,),
                ).fetchone()
                if row is not None:
                    target_existing_exam_id = int(row["id"])
                    issues.append(ExamMoveIssue(
                        "target_exam_exists",
                        f"target already contains exam code: {exam_code}",
                    ))
                fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_errors:
                    issues.append(ExamMoveIssue(
                        "target_fk_errors",
                        f"target database has {len(fk_errors)} foreign key errors",
                    ))
        except sqlite3.Error as exc:
            issues.append(ExamMoveIssue("sqlite_error", str(exc)))

    return ExamMovePlan(
        source_db=str(source),
        target_db=str(target),
        exam_code=exam_code,
        can_apply=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        source_exam_id=source_exam_id,
        target_existing_exam_id=target_existing_exam_id,
        counts=counts,
    )


def apply_exam_move(
    source_db: str | Path,
    target_db: str | Path,
    exam_code: str,
    *,
    backup: bool = True,
) -> ExamMoveResult:
    plan = dry_run_exam_move(source_db, target_db, exam_code)
    if not plan.can_apply:
        raise ExamMoveConflict(_format_issues(plan.issues))

    source = Path(plan.source_db)
    target = Path(plan.target_db)
    source_backup = _backup_db(source, "source") if backup else None
    target_backup = _backup_db(target, "target") if backup else None

    conn = sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("ATTACH DATABASE ? AS tgt", (str(target),))
    try:
        conn.execute("BEGIN IMMEDIATE")
        target_exam_id = _copy_exam_closure(conn, int(plan.source_exam_id), exam_code)
        _delete_source_exam_closure(conn, int(plan.source_exam_id))

        source_fk_errors = conn.execute("PRAGMA main.foreign_key_check").fetchall()
        target_fk_errors = conn.execute("PRAGMA tgt.foreign_key_check").fetchall()
        if source_fk_errors or target_fk_errors:
            raise sqlite3.IntegrityError(
                f"foreign key errors after move: source={source_fk_errors[:5]}, target={target_fk_errors[:5]}"
            )
        source_integrity = conn.execute("PRAGMA main.integrity_check").fetchone()[0]
        target_integrity = conn.execute("PRAGMA tgt.integrity_check").fetchone()[0]
        if source_integrity != "ok" or target_integrity != "ok":
            raise sqlite3.IntegrityError(
                f"integrity_check after move: source={source_integrity}, target={target_integrity}"
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.execute("DETACH DATABASE tgt")
        except sqlite3.Error:
            pass
        conn.close()

    return ExamMoveResult(
        moved=True,
        plan=plan,
        target_exam_id=target_exam_id,
        source_backup=str(source_backup) if source_backup else None,
        target_backup=str(target_backup) if target_backup else None,
    )


def apply_exam_copy(
    source_db: str | Path,
    target_db: str | Path,
    exam_code: str,
    *,
    backup: bool = True,
) -> ExamCopyResult:
    plan = dry_run_exam_move(source_db, target_db, exam_code)
    if not plan.can_apply:
        raise ExamMoveConflict(_format_issues(plan.issues))

    source = Path(plan.source_db)
    target = Path(plan.target_db)
    target_backup = _backup_db(target, "target") if backup else None

    conn = sqlite3.connect(source)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("ATTACH DATABASE ? AS tgt", (str(target),))
    try:
        conn.execute("BEGIN")
        target_exam_id = _copy_exam_closure(conn, int(plan.source_exam_id), exam_code)

        target_fk_errors = conn.execute("PRAGMA tgt.foreign_key_check").fetchall()
        if target_fk_errors:
            raise sqlite3.IntegrityError(
                f"foreign key errors after copy: target={target_fk_errors[:5]}"
            )
        target_integrity = conn.execute("PRAGMA tgt.integrity_check").fetchone()[0]
        if target_integrity != "ok":
            raise sqlite3.IntegrityError(
                f"integrity_check after copy: target={target_integrity}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.execute("DETACH DATABASE tgt")
        except sqlite3.Error:
            pass
        conn.close()

    return ExamCopyResult(
        copied=True,
        plan=plan,
        target_exam_id=target_exam_id,
        target_backup=str(target_backup) if target_backup else None,
    )


def _copy_exam_closure(conn: sqlite3.Connection, source_exam_id: int, exam_code: str) -> int:
    exam = conn.execute(
        """
        SELECT id, code, name, is_domestic_only, created_at
        FROM main.exams
        WHERE id = ?
        """,
        (source_exam_id,),
    ).fetchone()
    if exam is None:
        raise ExamMoveError(f"source exam not found: {source_exam_id}")

    conn.execute(
        """
        INSERT INTO tgt.exams (code, name, is_domestic_only, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (exam["code"], exam["name"], exam["is_domestic_only"], exam["created_at"]),
    )
    target_exam_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    source_subject_ids = _subject_ids_for_exam(conn, source_exam_id)
    source_to_target_subject_id: Dict[int, int] = {}
    for subject in _rows_by_ids(conn, "main.subjects", source_subject_ids):
        existing = conn.execute(
            "SELECT id FROM tgt.subjects WHERE code = ?",
            (subject["code"],),
        ).fetchone()
        if existing:
            target_subject_id = int(existing["id"])
        else:
            conn.execute(
                """
                INSERT INTO tgt.subjects (code, name_ko, name_en, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (subject["code"], subject["name_ko"], subject["name_en"], subject["created_at"]),
            )
            target_subject_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        source_to_target_subject_id[int(subject["id"])] = target_subject_id

    source_to_target_exam_subject_id: Dict[int, int] = {}
    exam_subject_rows = conn.execute(
        """
        SELECT id, subject_id, display_order, questions_count
        FROM main.exam_subjects
        WHERE exam_id = ?
        ORDER BY display_order ASC, id ASC
        """,
        (source_exam_id,),
    ).fetchall()
    for row in exam_subject_rows:
        conn.execute(
            """
            INSERT INTO tgt.exam_subjects (exam_id, subject_id, display_order, questions_count)
            VALUES (?, ?, ?, ?)
            """,
            (
                target_exam_id,
                source_to_target_subject_id[int(row["subject_id"])],
                row["display_order"],
                row["questions_count"],
            ),
        )
        source_to_target_exam_subject_id[int(row["id"])] = int(
            conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        )

    source_ids = _source_ids_for_exam(conn, source_exam_id)
    source_to_target_source_id = _copy_question_sources(conn, source_ids)
    group_ids = _group_ids_for_exam(conn, source_exam_id)
    source_to_target_group_id = _copy_question_groups(
        conn,
        group_ids,
        source_to_target_exam_subject_id,
        source_to_target_source_id,
    )
    source_to_target_question_id = _copy_questions(
        conn,
        source_exam_id,
        source_to_target_exam_subject_id,
        source_to_target_group_id,
        source_to_target_source_id,
    )
    _copy_choices(conn, source_to_target_question_id)
    return target_exam_id


def _delete_source_exam_closure(conn: sqlite3.Connection, source_exam_id: int) -> None:
    exam_subject_ids = _exam_subject_ids_for_exam(conn, source_exam_id)
    subject_ids = _subject_ids_for_exam(conn, source_exam_id)
    question_ids = _question_ids_for_exam(conn, source_exam_id)
    group_ids = _group_ids_for_exam(conn, source_exam_id)
    source_ids = _source_ids_for_exam(conn, source_exam_id)
    mock_exam_ids = [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM main.mock_exams WHERE exam_id = ?",
            (source_exam_id,),
        ).fetchall()
    ]

    _delete_where_in(conn, "main.exam_results", "mock_exam_id", mock_exam_ids)
    _delete_where_in(conn, "main.exam_results", "exam_subject_id", exam_subject_ids)
    _delete_where_in(conn, "main.mock_exam_questions", "mock_exam_id", mock_exam_ids)
    _delete_where_in(conn, "main.mock_exam_questions", "question_id", question_ids)
    _delete_where_in(conn, "main.mock_exams", "id", mock_exam_ids)
    _delete_where_in(conn, "main.question_choices", "question_id", question_ids)
    _delete_where_in(conn, "main.questions", "id", question_ids)
    _delete_where_in(conn, "main.question_groups", "id", group_ids)
    _delete_where_in(conn, "main.exam_subjects", "id", exam_subject_ids)
    conn.execute("DELETE FROM main.exams WHERE id = ?", (source_exam_id,))

    if source_ids:
        placeholders = _placeholders(source_ids)
        conn.execute(
            f"""
            DELETE FROM main.question_sources
            WHERE id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM main.questions q WHERE q.source_id = question_sources.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM main.question_groups qg WHERE qg.source_id = question_sources.id
              )
            """,
            source_ids,
        )
    if subject_ids:
        placeholders = _placeholders(subject_ids)
        conn.execute(
            f"""
            DELETE FROM main.subjects
            WHERE id IN ({placeholders})
              AND NOT EXISTS (
                  SELECT 1 FROM main.exam_subjects es WHERE es.subject_id = subjects.id
              )
            """,
            subject_ids,
        )


def _copy_question_sources(conn: sqlite3.Connection, source_ids: List[int]) -> Dict[int, Optional[int]]:
    mapping: Dict[int, Optional[int]] = {}
    for source_id in source_ids:
        row = conn.execute(
            """
            SELECT id, provider, source_url, document_id, attachment_url,
                   attachment_filename, content_hash, fetched_at
            FROM main.question_sources
            WHERE id = ?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            provider = "legacy_missing_source"
            source_url = f"missing-source:{source_id}"
            content_hash = f"missing-source:{source_id}"
            existing = conn.execute(
                """
                SELECT id
                FROM tgt.question_sources
                WHERE provider = ? AND source_url = ? AND content_hash = ?
                """,
                (provider, source_url, content_hash),
            ).fetchone()
            if existing:
                mapping[source_id] = int(existing["id"])
                continue
            conn.execute(
                """
                INSERT INTO tgt.question_sources (
                    provider, source_url, document_id, attachment_url,
                    attachment_filename, content_hash, fetched_at
                ) VALUES (?, ?, NULL, NULL, NULL, ?, CURRENT_TIMESTAMP)
                """,
                (provider, source_url, content_hash),
            )
            mapping[source_id] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            continue

        existing = conn.execute(
            """
            SELECT id
            FROM tgt.question_sources
            WHERE provider = ? AND source_url = ? AND content_hash = ?
            """,
            (row["provider"], row["source_url"], row["content_hash"]),
        ).fetchone()
        if existing:
            mapping[source_id] = int(existing["id"])
            continue

        conn.execute(
            """
            INSERT INTO tgt.question_sources (
                provider, source_url, document_id, attachment_url,
                attachment_filename, content_hash, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["provider"],
                row["source_url"],
                row["document_id"],
                row["attachment_url"],
                row["attachment_filename"],
                row["content_hash"],
                row["fetched_at"],
            ),
        )
        mapping[source_id] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return mapping


def _copy_question_groups(
    conn: sqlite3.Connection,
    group_ids: List[int],
    exam_subject_map: Dict[int, int],
    source_map: Dict[int, Optional[int]],
) -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    for row in _rows_by_ids(conn, "main.question_groups", group_ids):
        conn.execute(
            """
            INSERT INTO tgt.question_groups (
                exam_subject_id, year, session, group_number, group_type,
                shared_text, shared_image_path, source_id, source_page, tags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_subject_map[int(row["exam_subject_id"])],
                row["year"],
                row["session"],
                row["group_number"],
                row["group_type"],
                row["shared_text"],
                row["shared_image_path"],
                _mapped_optional(source_map, row["source_id"]),
                row["source_page"],
                row["tags"],
                row["created_at"],
            ),
        )
        mapping[int(row["id"])] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return mapping


def _copy_questions(
    conn: sqlite3.Connection,
    source_exam_id: int,
    exam_subject_map: Dict[int, int],
    group_map: Dict[int, int],
    source_map: Dict[int, Optional[int]],
) -> Dict[int, int]:
    mapping: Dict[int, int] = {}
    rows = conn.execute(
        """
        SELECT
            q.id, q.exam_subject_id, q.year, q.session, q.question_number,
            q.question_text, q.question_format_json, q.has_image, q.image_path,
            q.correct_answer, q.source_page, q.tags, q.group_id, q.group_order,
            q.source_id, q.source_question_id, q.created_at
        FROM main.questions q
        JOIN main.exam_subjects es ON es.id = q.exam_subject_id
        WHERE es.exam_id = ?
        ORDER BY q.id ASC
        """,
        (source_exam_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO tgt.questions (
                exam_subject_id, year, session, question_number, question_text,
                question_format_json, has_image, image_path, correct_answer,
                source_page, tags, group_id, group_order, source_id,
                source_question_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exam_subject_map[int(row["exam_subject_id"])],
                row["year"],
                row["session"],
                row["question_number"],
                row["question_text"],
                row["question_format_json"],
                row["has_image"],
                row["image_path"],
                row["correct_answer"],
                row["source_page"],
                row["tags"],
                _mapped_optional(group_map, row["group_id"]),
                row["group_order"],
                _mapped_optional(source_map, row["source_id"]),
                row["source_question_id"],
                row["created_at"],
            ),
        )
        mapping[int(row["id"])] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    return mapping


def _copy_choices(conn: sqlite3.Connection, question_map: Dict[int, int]) -> None:
    if not question_map:
        return
    question_ids = sorted(question_map)
    placeholders = _placeholders(question_ids)
    rows = conn.execute(
        f"""
        SELECT question_id, choice_number, choice_symbol, choice_text,
               choice_format_json, choice_image_path
        FROM main.question_choices
        WHERE question_id IN ({placeholders})
        ORDER BY question_id ASC, choice_number ASC
        """,
        question_ids,
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            INSERT INTO tgt.question_choices (
                question_id, choice_number, choice_symbol, choice_text,
                choice_format_json, choice_image_path
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                question_map[int(row["question_id"])],
                row["choice_number"],
                row["choice_symbol"],
                row["choice_text"],
                row["choice_format_json"],
                row["choice_image_path"],
            ),
        )


def _exam_counts(conn: sqlite3.Connection, exam_id: int) -> Dict[str, int]:
    counts = {
        "exam_subjects": len(_exam_subject_ids_for_exam(conn, exam_id)),
        "subjects": len(_subject_ids_for_exam(conn, exam_id)),
        "questions": len(_question_ids_for_exam(conn, exam_id)),
        "groups": len(_group_ids_for_exam(conn, exam_id)),
        "sources": len(_source_ids_for_exam(conn, exam_id)),
        "mock_exams_removed": conn.execute(
            "SELECT COUNT(*) FROM mock_exams WHERE exam_id = ?",
            (exam_id,),
        ).fetchone()[0],
    }
    question_ids = _question_ids_for_exam(conn, exam_id)
    if question_ids:
        counts["choices"] = conn.execute(
            f"SELECT COUNT(*) FROM question_choices WHERE question_id IN ({_placeholders(question_ids)})",
            question_ids,
        ).fetchone()[0]
    else:
        counts["choices"] = 0
    return counts


def _exam_subject_ids_for_exam(conn: sqlite3.Connection, exam_id: int) -> List[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM main.exam_subjects WHERE exam_id = ? ORDER BY id",
            (exam_id,),
        ).fetchall()
    ]


def _subject_ids_for_exam(conn: sqlite3.Connection, exam_id: int) -> List[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            """
            SELECT DISTINCT subject_id AS id
            FROM main.exam_subjects
            WHERE exam_id = ?
            ORDER BY subject_id
            """,
            (exam_id,),
        ).fetchall()
    ]


def _question_ids_for_exam(conn: sqlite3.Connection, exam_id: int) -> List[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            """
            SELECT q.id
            FROM main.questions q
            JOIN main.exam_subjects es ON es.id = q.exam_subject_id
            WHERE es.exam_id = ?
            ORDER BY q.id
            """,
            (exam_id,),
        ).fetchall()
    ]


def _group_ids_for_exam(conn: sqlite3.Connection, exam_id: int) -> List[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            """
            SELECT DISTINCT id
            FROM (
                SELECT qg.id AS id
                FROM main.question_groups qg
                JOIN main.exam_subjects es ON es.id = qg.exam_subject_id
                WHERE es.exam_id = ?
                UNION
                SELECT q.group_id AS id
                FROM main.questions q
                JOIN main.exam_subjects es ON es.id = q.exam_subject_id
                WHERE es.exam_id = ? AND q.group_id IS NOT NULL
            )
            WHERE id IS NOT NULL
            ORDER BY id
            """,
            (exam_id, exam_id),
        ).fetchall()
    ]


def _source_ids_for_exam(conn: sqlite3.Connection, exam_id: int) -> List[int]:
    return [
        int(row["id"])
        for row in conn.execute(
            """
            SELECT DISTINCT id
            FROM (
                SELECT q.source_id AS id
                FROM main.questions q
                JOIN main.exam_subjects es ON es.id = q.exam_subject_id
                WHERE es.exam_id = ? AND q.source_id IS NOT NULL
                UNION
                SELECT qg.source_id AS id
                FROM main.question_groups qg
                JOIN main.exam_subjects es ON es.id = qg.exam_subject_id
                WHERE es.exam_id = ? AND qg.source_id IS NOT NULL
            )
            WHERE id IS NOT NULL
            ORDER BY id
            """,
            (exam_id, exam_id),
        ).fetchall()
    ]


def _rows_by_ids(conn: sqlite3.Connection, table_name: str, ids: List[int]) -> List[sqlite3.Row]:
    if not ids:
        return []
    return conn.execute(
        f"SELECT * FROM {table_name} WHERE id IN ({_placeholders(ids)}) ORDER BY id",
        ids,
    ).fetchall()


def _mapped_optional(mapping: Dict[int, Optional[int]], value: Any) -> Optional[int]:
    if value is None:
        return None
    return mapping.get(int(value))


def _delete_where_in(conn: sqlite3.Connection, table_name: str, column_name: str, ids: List[int]) -> None:
    if not ids:
        return
    conn.execute(
        f"DELETE FROM {table_name} WHERE {column_name} IN ({_placeholders(ids)})",
        ids,
    )


def _placeholders(values: Iterable[Any]) -> str:
    return ",".join(["?"] * len(list(values)))


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _require_schema(conn: sqlite3.Connection, label: str) -> None:
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        raise sqlite3.OperationalError(f"{label} database missing tables: {', '.join(missing)}")


def _backup_db(path: Path, role: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}.before_exam_move_{role}_{stamp}{path.suffix}")
    with sqlite3.connect(path) as source_conn:
        with sqlite3.connect(backup_path) as backup_conn:
            source_conn.backup(backup_conn, pages=1000)
    return backup_path


def _format_issues(issues: List[ExamMoveIssue]) -> str:
    return "; ".join(f"{issue.code}: {issue.message}" for issue in issues)


def sqlite_uri_readonly(path: str | Path) -> str:
    resolved = Path(path).resolve()
    quoted = quote(str(resolved).replace("\\", "/"), safe="/:")
    return f"file:{quoted}?mode=ro"
