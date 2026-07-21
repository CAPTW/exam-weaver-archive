"""Repair high-confidence text artifacts in the local exam-bank DB."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parser.formatting import (
    has_suspicious_text_artifact,
    normalize_latex_text,
    repair_extracted_text_artifacts,
    repair_ocr_confusable_artifacts,
)
from src.parser.text_quality import (
    has_unbalanced_delimiters as _has_unbalanced_delimiters,
    text_quality_issue_codes,
)


@dataclass
class TextChange:
    table: str
    row_id: int
    field: str
    before: str
    after: str
    format_field: str | None = None
    format_before: str | None = None
    format_after: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class SuspiciousText:
    category: str
    table: str
    row_id: int
    field: str
    text: str
    metadata: dict[str, Any] | None = None


def repair_text_and_format(
    text: str,
    format_json: str | None,
    *,
    confusables_only: bool = False,
) -> tuple[str, str | None, bool]:
    """Return repaired text, format_json, and whether a format-json row was skipped."""
    repair = (
        repair_ocr_confusable_artifacts
        if confusables_only
        else repair_extracted_text_artifacts
    )
    repaired_format = repair_embedded_format_text(format_json, repair)
    if confusables_only:
        repaired = repair(text)
        if repaired == text:
            return text, repaired_format, False
        if not repaired_format:
            return repaired, None, False
        if can_preserve_format_json(text, repaired, repaired_format):
            return repaired, repaired_format, False
        formatted = normalize_latex_text(repaired)
        next_format = replace_format_spans(repaired_format, formatted.spans)
        return formatted.text, next_format, False

    if repaired_format:
        repaired = repair(text)
        if can_preserve_format_json(text, repaired, repaired_format):
            return repaired, repaired_format, False
        formatted = normalize_latex_text(repaired)
        next_format = replace_format_spans(repaired_format, formatted.spans)
        return formatted.text, next_format, False

    repaired = repair(text)
    formatted = normalize_latex_text(repaired)
    next_format = None
    if formatted.spans:
        next_format = json.dumps({"spans": formatted.spans}, ensure_ascii=False)
    return formatted.text, next_format, False


def repair_embedded_format_text(
    format_json: str | None,
    repair,
) -> str | None:
    """Repair textual table payloads without discarding table structure."""
    if not format_json:
        return format_json
    try:
        payload = json.loads(format_json)
    except (TypeError, ValueError):
        return format_json
    if not isinstance(payload, dict):
        return format_json

    changed = False

    def repair_preserving_hard_breaks(value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        return "\n".join(repair(line) for line in normalized.split("\n"))

    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") or []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            for column_index, value in enumerate(row):
                if not isinstance(value, str):
                    continue
                repaired = repair_preserving_hard_breaks(value)
                if repaired != value:
                    rows[row_index][column_index] = repaired
                    changed = True
        for cell in table.get("cells") or []:
            if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                continue
            repaired = repair_preserving_hard_breaks(cell["text"])
            if repaired != cell["text"]:
                cell["text"] = repaired
                changed = True
    if not changed:
        return format_json
    return json.dumps(payload, ensure_ascii=False)


def replace_format_spans(format_json: str | None, spans: list[dict]) -> str | None:
    """Replace rich-text spans while retaining tables and their layout metadata."""
    try:
        payload = json.loads(format_json) if format_json else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if spans:
        payload["spans"] = spans
    else:
        payload.pop("spans", None)
    return json.dumps(payload, ensure_ascii=False) if payload else None


def can_preserve_format_json(before: str, after: str, format_json: str | None) -> bool:
    if not format_json:
        return True
    if len(before or "") != len(after or ""):
        return False
    try:
        payload = json.loads(format_json)
    except (TypeError, ValueError):
        return False
    spans = payload.get("spans") if isinstance(payload, dict) else []
    for span in spans or []:
        try:
            start = int(span.get("start"))
            end = int(span.get("end"))
        except (TypeError, ValueError, AttributeError):
            return False
        if start < 0 or end <= start or end > len(after or ""):
            return False
        if span.get("latex") and (after or "")[start:end] != span.get("latex"):
            return False
    return True


def collect_changes(
    conn: sqlite3.Connection,
    *,
    confusables_only: bool = False,
) -> tuple[list[TextChange], list[TextChange]]:
    changes: list[TextChange] = []
    skipped_format_rows: list[TextChange] = []

    questions = conn.execute(
        """
        SELECT
            q.id, q.question_text, q.question_format_json,
            q.year, q.session, q.question_number,
            e.code AS exam_code, s.name_ko AS subject_name
        FROM questions q
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        ORDER BY q.id
        """
    ).fetchall()
    for row in questions:
        metadata = row_metadata(row)
        next_text, next_format, skipped = repair_text_and_format(
            row["question_text"] or "",
            row["question_format_json"],
            confusables_only=confusables_only,
        )
        if skipped and next_text != (row["question_text"] or ""):
            skipped_format_rows.append(
                TextChange(
                    table="questions",
                    row_id=row["id"],
                    field="question_text",
                    before=row["question_text"] or "",
                    after=next_text,
                    format_field="question_format_json",
                    format_before=row["question_format_json"],
                    format_after=row["question_format_json"],
                    metadata=metadata,
                )
            )
            continue
        if next_text != (row["question_text"] or "") or next_format != row["question_format_json"]:
            changes.append(
                TextChange(
                    table="questions",
                    row_id=row["id"],
                    field="question_text",
                    before=row["question_text"] or "",
                    after=next_text,
                    format_field="question_format_json",
                    format_before=row["question_format_json"],
                    format_after=next_format,
                    metadata=metadata,
                )
            )

    choices = conn.execute(
        """
        SELECT
            c.id, c.choice_text, c.choice_format_json, c.choice_symbol,
            q.id AS question_id, q.year, q.session, q.question_number,
            e.code AS exam_code, s.name_ko AS subject_name
        FROM question_choices c
        JOIN questions q ON q.id = c.question_id
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        ORDER BY c.id
        """
    ).fetchall()
    for row in choices:
        metadata = row_metadata(row)
        metadata["choice_symbol"] = row["choice_symbol"]
        metadata["question_id"] = row["question_id"]
        next_text, next_format, skipped = repair_text_and_format(
            row["choice_text"] or "",
            row["choice_format_json"],
            confusables_only=confusables_only,
        )
        if skipped and next_text != (row["choice_text"] or ""):
            skipped_format_rows.append(
                TextChange(
                    table="question_choices",
                    row_id=row["id"],
                    field="choice_text",
                    before=row["choice_text"] or "",
                    after=next_text,
                    format_field="choice_format_json",
                    format_before=row["choice_format_json"],
                    format_after=row["choice_format_json"],
                    metadata=metadata,
                )
            )
            continue
        if next_text != (row["choice_text"] or "") or next_format != row["choice_format_json"]:
            changes.append(
                TextChange(
                    table="question_choices",
                    row_id=row["id"],
                    field="choice_text",
                    before=row["choice_text"] or "",
                    after=next_text,
                    format_field="choice_format_json",
                    format_before=row["choice_format_json"],
                    format_after=next_format,
                    metadata=metadata,
                )
            )

    return changes, skipped_format_rows


def row_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "exam_code": row["exam_code"],
        "subject_name": row["subject_name"],
        "year": row["year"],
        "session": row["session"],
        "question_number": row["question_number"],
    }


def apply_changes(conn: sqlite3.Connection, changes: list[TextChange]) -> None:
    with conn:
        for change in changes:
            if change.table == "questions":
                conn.execute(
                    """
                    UPDATE questions
                    SET question_text = ?, question_format_json = ?
                    WHERE id = ?
                    """,
                    (change.after, change.format_after, change.row_id),
                )
            elif change.table == "question_choices":
                conn.execute(
                    """
                    UPDATE question_choices
                    SET choice_text = ?, choice_format_json = ?
                    WHERE id = ?
                    """,
                    (change.after, change.format_after, change.row_id),
                )


def collect_suspicious(conn: sqlite3.Connection) -> list[SuspiciousText]:
    suspicious: list[SuspiciousText] = []
    rows = []
    rows.extend(
        dict(row, table_name="questions", row_id=row["id"], field_name="question_text")
        for row in conn.execute(
            """
            SELECT
                q.id, q.question_text AS text, q.question_format_json,
                q.year, q.session, q.question_number,
                e.code AS exam_code, s.name_ko AS subject_name
            FROM questions q
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            """
        )
    )
    question_rows = conn.execute(
        """
        SELECT
            q.id, q.question_format_json, q.year, q.session, q.question_number,
            e.code AS exam_code, s.name_ko AS subject_name
        FROM questions q
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        WHERE q.question_format_json IS NOT NULL
        """
    ).fetchall()
    for row in question_rows:
        try:
            payload = json.loads(row["question_format_json"])
        except (TypeError, ValueError):
            continue
        for table_index, table in enumerate(payload.get("tables") or []):
            if not isinstance(table, dict):
                continue
            coordinates = set()
            for row_index, values in enumerate(table.get("rows") or []):
                if not isinstance(values, list):
                    continue
                for column_index, text in enumerate(values):
                    coordinates.add((row_index, column_index))
                    if not isinstance(text, str):
                        continue
                    rows.append({
                        "table_name": "questions",
                        "row_id": row["id"],
                        "field_name": (
                            f"question_format_json.tables[{table_index}]"
                            f".rows[{row_index}][{column_index}]"
                        ),
                        "text": text,
                        "year": row["year"],
                        "session": row["session"],
                        "question_number": row["question_number"],
                        "exam_code": row["exam_code"],
                        "subject_name": row["subject_name"],
                    })
            for cell_index, cell in enumerate(table.get("cells") or []):
                if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                    continue
                coordinate = (cell.get("row"), cell.get("col"))
                if coordinate in coordinates:
                    continue
                rows.append({
                    "table_name": "questions",
                    "row_id": row["id"],
                    "field_name": (
                        f"question_format_json.tables[{table_index}]"
                        f".cells[{cell_index}].text"
                    ),
                    "text": cell["text"],
                    "year": row["year"],
                    "session": row["session"],
                    "question_number": row["question_number"],
                    "exam_code": row["exam_code"],
                    "subject_name": row["subject_name"],
                })
    rows.extend(
        dict(row, table_name="question_choices", row_id=row["id"], field_name="choice_text")
        for row in conn.execute(
            """
            SELECT
                c.id, c.choice_text AS text, c.choice_symbol,
                q.id AS question_id, q.year, q.session, q.question_number,
                e.code AS exam_code, s.name_ko AS subject_name
            FROM question_choices c
            JOIN questions q ON q.id = c.question_id
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            """
        )
    )

    checks = [
        ("pua_remaining", lambda text: bool(re.search(r"[\ue000-\uf8ff]", text))),
        ("hwp_overbar_marker_review", lambda text: "¯" in text),
        # Newlines are meaningful in stems, legal excerpts, and editable
        # table cells.  Only carriage returns/tabs indicate unnormalised input.
        ("linebreak_remaining", lambda text: bool(re.search(r"[\r\t]", text))),
        ("broken_variable_note_remaining", lambda text: bool(re.search(r"단\s+는\s+[^?()]+이다\?\s*\(\s*,", text))),
        ("dangling_blank_reference", lambda text: bool(re.search(r"에서\s+에\s+(?:각각\s+)?알맞은|에서\s+에\s+각각", text))),
        ("quote_blank_order_suspect", lambda text: bool(re.search(r'"\s*\(\s+\)\s*\?', text))),
        ("number_unit_order_suspect", lambda text: bool(re.search(r"\b\d+\s+\d+\s*\[[^\]]+\]|\[[^\]]+\]\s+\d+\s+[가-힣]", text))),
        ("blank_unit_suspect", lambda text: bool(re.search(r"\[\s*\]\s*(?:Ω|Ω|℃|ℓ)?", text))),
        ("paren_question_order_suspect", lambda text: bool(re.search(r"\([^)]{1,60}\)\s+\?", text))),
        ("suspicious_text_artifact", has_suspicious_text_artifact),
        (
            "ocr_noise_text",
            lambda text: "ocr_noise" in text_quality_issue_codes(text),
        ),
        (
            "broken_unit_text",
            lambda text: "broken_unit" in text_quality_issue_codes(text),
        ),
        ("unbalanced_paren_or_bracket", has_unbalanced_delimiters),
    ]
    for row in rows:
        text = row["text"] or ""
        metadata = {
            "exam_code": row["exam_code"],
            "subject_name": row["subject_name"],
            "year": row["year"],
            "session": row["session"],
            "question_number": row["question_number"],
        }
        if "choice_symbol" in row.keys():
            metadata["choice_symbol"] = row["choice_symbol"]
            metadata["question_id"] = row["question_id"]
        for category, check in checks:
            if (
                category == "linebreak_remaining"
                and str(row["field_name"]).startswith("question_format_json.")
            ):
                # Line breaks are expected inside an editable table cell and
                # should not inflate the post-repair residual count.
                continue
            if check(text):
                suspicious.append(
                    SuspiciousText(
                        category=category,
                        table=row["table_name"],
                        row_id=row["row_id"],
                        field=row["field_name"],
                        text=text,
                        metadata=metadata,
                    )
                )
    return suspicious


def has_unbalanced_delimiters(text: str) -> bool:
    return _has_unbalanced_delimiters(text)


def write_report(
    output_dir: Path,
    db_path: Path,
    applied: bool,
    backup_path: Path | None,
    changes: list[TextChange],
    skipped_format_rows: list[TextChange],
    suspicious: list[SuspiciousText],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "db_path": str(db_path),
        "applied": applied,
        "backup_path": str(backup_path) if backup_path else None,
        "change_count": len(changes),
        "skipped_format_row_count": len(skipped_format_rows),
        "suspicious_count": len(suspicious),
        "changes": [asdict(change) for change in changes],
        "skipped_format_rows": [asdict(change) for change in skipped_format_rows],
        "suspicious": [asdict(item) for item in suspicious],
    }
    json_path = output_dir / "db_text_repair_report.json"
    markdown_path = output_dir / "db_text_repair_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    report["json_report"] = str(json_path)
    report["markdown_report"] = str(markdown_path)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DB Text Repair Report",
        "",
        f"- DB: `{report['db_path']}`",
        f"- Applied: `{report['applied']}`",
        f"- Backup: `{report['backup_path']}`",
        f"- Auto changes: `{report['change_count']}`",
        f"- Skipped formatted rows: `{report['skipped_format_row_count']}`",
        f"- Remaining suspicious findings: `{report['suspicious_count']}`",
        "",
        "## Auto Changes (first 50)",
        "",
    ]
    for change in report["changes"][:50]:
        lines.extend(render_change(change))
    lines.extend(["", "## Skipped Formatted Rows (first 50)", ""])
    for change in report["skipped_format_rows"][:50]:
        lines.extend(render_change(change))
    lines.extend(["", "## Remaining Suspicious Findings (first 100)", ""])
    for item in report["suspicious"][:100]:
        meta = item.get("metadata") or {}
        lines.append(
            f"- `{item['category']}` {item['table']}#{item['row_id']} "
            f"{meta.get('exam_code', '')} {meta.get('subject_name', '')} "
            f"{meta.get('year', '')}-{meta.get('session', '')} Q{meta.get('question_number', '')} "
            f"{meta.get('choice_symbol', '')}"
        )
        lines.append(f"  - {compact(item['text'])}")
    lines.append("")
    return "\n".join(lines)


def render_change(change: dict[str, Any]) -> list[str]:
    meta = change.get("metadata") or {}
    return [
        (
            f"- {change['table']}#{change['row_id']} "
            f"{meta.get('exam_code', '')} {meta.get('subject_name', '')} "
            f"{meta.get('year', '')}-{meta.get('session', '')} Q{meta.get('question_number', '')} "
            f"{meta.get('choice_symbol', '')}"
        ),
        f"  - before: {compact(change['before'])}",
        f"  - after: {compact(change['after'])}",
    ]


def compact(text: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "tmp" / f"db_text_repair_{timestamp}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(PROJECT_ROOT / "data" / "exam_bank.db"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--apply", action="store_true", help="Write changes to the DB.")
    parser.add_argument(
        "--confusables-only",
        action="store_true",
        help="Repair only source-confirmed OCR character confusions.",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else default_output_dir()
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    backup_path = None
    if args.apply:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(f"{db_path.stem}_before_text_repair_{timestamp}{db_path.suffix}")
        shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        changes, skipped_format_rows = collect_changes(
            conn,
            confusables_only=args.confusables_only,
        )
        if args.apply and changes:
            apply_changes(conn, changes)
        if args.apply:
            suspicious = collect_suspicious(conn)
        else:
            preview_conn = sqlite3.connect(":memory:")
            preview_conn.row_factory = sqlite3.Row
            try:
                conn.backup(preview_conn)
                if changes:
                    apply_changes(preview_conn, changes)
                suspicious = collect_suspicious(preview_conn)
            finally:
                preview_conn.close()
    finally:
        conn.close()

    report = write_report(
        output_dir,
        db_path,
        args.apply,
        backup_path,
        changes,
        skipped_format_rows,
        suspicious,
    )
    print(json.dumps({
        "applied": args.apply,
        "backup_path": str(backup_path) if backup_path else None,
        "change_count": len(changes),
        "skipped_format_row_count": len(skipped_format_rows),
        "suspicious_count": len(suspicious),
        "json_report": report["json_report"],
        "markdown_report": report["markdown_report"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
