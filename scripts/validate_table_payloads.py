"""Validate and safely normalize hybrid table payloads in an exam database."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.parser.table_format import (
    effective_table_render_mode,
    parse_format_payload,
    serialize_format_payload,
    validate_table_spec,
)


FORMAT_COLUMNS = (
    ("questions", "question_format_json", "question_text"),
    ("question_choices", "choice_format_json", "choice_text"),
)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(
        row[1] == column
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    )


def _iter_payload_rows(conn: sqlite3.Connection):
    for table, column, text_column in FORMAT_COLUMNS:
        if not _column_exists(conn, table, column):
            continue
        has_text = _column_exists(conn, table, text_column)
        text_select = text_column if has_text else "''"
        query = (
            f"SELECT id, {column}, {text_select} FROM {table} "
            f"WHERE COALESCE({column}, '') <> ''"
        )
        for row_id, encoded, text in conn.execute(query).fetchall():
            yield table, column, int(row_id), encoded, str(text or "")


def validate_database(
    db_path: str | Path,
    source_root: Optional[str | Path] = None,
) -> dict:
    """Return a read-only quality report for both format JSON columns."""
    db_path = Path(db_path).resolve()
    source_root = Path(source_root).resolve() if source_root else db_path.parent
    report = {
        "database": str(db_path),
        "tables": 0,
        "native_ready": 0,
        "image_fallback": 0,
        "legacy_rows": 0,
        "warnings": 0,
        "errors": 0,
        "findings": [],
    }
    with sqlite3.connect(db_path) as conn:
        for table_name, column, row_id, encoded, owner_text in _iter_payload_rows(conn):
            try:
                raw_payload = json.loads(encoded)
            except (TypeError, ValueError, json.JSONDecodeError):
                report["errors"] += 1
                report["findings"].append({
                    "severity": "error",
                    "code": "invalid_format_json",
                    "table": table_name,
                    "column": column,
                    "row_id": row_id,
                    "table_id": None,
                })
                continue
            raw_tables = raw_payload.get("tables") if isinstance(raw_payload, dict) else []
            payload = parse_format_payload(raw_payload)
            for index, table_spec in enumerate(payload.get("tables") or []):
                report["tables"] += 1
                raw_table = (
                    raw_tables[index]
                    if isinstance(raw_tables, list) and index < len(raw_tables)
                    and isinstance(raw_tables[index], dict)
                    else {}
                )
                is_legacy = (
                    int(raw_payload.get("schema_version") or 1) < 2
                    and bool(raw_table.get("rows"))
                    and not raw_table.get("cells")
                    and not (raw_table.get("source") or {}).get("image_path")
                )
                if is_legacy:
                    report["legacy_rows"] += 1
                elif effective_table_render_mode(table_spec, "auto") == "native":
                    report["native_ready"] += 1
                else:
                    report["image_fallback"] += 1

                codes = validate_table_spec(
                    table_spec,
                    text=owner_text,
                    source_root=source_root,
                )
                for code in codes:
                    report["errors"] += 1
                    report["findings"].append({
                        "severity": "error",
                        "code": code,
                        "table": table_name,
                        "column": column,
                        "row_id": row_id,
                        "table_id": table_spec.get("id"),
                    })
                if (table_spec.get("complexity") or {}).get("has_duplicate_text_risk"):
                    report["warnings"] += 1
                    report["findings"].append({
                        "severity": "warning",
                        "code": "duplicate_text_risk",
                        "table": table_name,
                        "column": column,
                        "row_id": row_id,
                        "table_id": table_spec.get("id"),
                    })
    return report


def normalize_database(
    db_path: str | Path,
    source_root: Optional[str | Path] = None,
) -> dict:
    """Back up and transactionally normalize only structurally valid payload rows."""
    db_path = Path(db_path).resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.pre_table_v2.{timestamp}.bak")
    shutil.copy2(db_path, backup_path)
    normalized_rows = 0
    with sqlite3.connect(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = list(_iter_payload_rows(conn))
            for table_name, column, row_id, encoded, owner_text in rows:
                try:
                    raw_payload = json.loads(encoded)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(raw_payload, dict) or not raw_payload.get('tables'):
                    continue
                payload = parse_format_payload(encoded)
                errors = [
                    code
                    for table_spec in payload.get("tables") or []
                    for code in validate_table_spec(
                        table_spec,
                        text=owner_text,
                        source_root=Path(source_root).resolve() if source_root else db_path.parent,
                    )
                ]
                if errors:
                    continue
                normalized = serialize_format_payload(payload)
                if normalized != encoded:
                    conn.execute(
                        f"UPDATE {table_name} SET {column} = ? WHERE id = ?",
                        (normalized, row_id),
                    )
                    normalized_rows += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    report = validate_database(db_path, source_root=source_root)
    report["normalized_rows"] = normalized_rows
    report["backup_path"] = str(backup_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate hybrid table payloads.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--report")
    parser.add_argument("--normalize", action="store_true")
    args = parser.parse_args()

    if args.normalize:
        report = normalize_database(args.db, source_root=args.source_root)
    else:
        report = validate_database(args.db, source_root=args.source_root)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(encoded, encoding="utf-8")
    print(encoded)
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
