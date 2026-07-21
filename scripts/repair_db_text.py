"""Audit and conservatively repair rich text in one local exam-bank DB."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database.text_repair import (  # noqa: E402
    AuditSummary,
    TextChange,
    TextFinding,
    apply_changes,
    collect_changes,
    collect_findings,
    collect_surface_counts,
    repair_embedded_format_text,
    repair_text_and_format,
)
from src.parser.text_quality import (  # noqa: E402
    has_unbalanced_delimiters,
)


def write_report(
    output_dir: Path,
    db_path: Path,
    applied: bool,
    backup_path: Path | None,
    summary: AuditSummary,
    skipped_format_rows: list[TextChange],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    blocked = [
        item
        for item in summary.findings
        if item.severity == "blocked_quality"
    ]
    review = [
        item
        for item in summary.findings
        if item.severity == "needs_source_review"
    ]
    report = {
        "db_path": str(db_path),
        "applied": applied,
        "backup_path": str(backup_path) if backup_path else None,
        "surface_counts": dict(summary.surface_counts),
        "change_count": len(summary.changes),
        "skipped_format_row_count": len(skipped_format_rows),
        "blocked_quality_count": len(blocked),
        "needs_source_review_count": len(review),
        "changes": [asdict(change) for change in summary.changes],
        "skipped_format_rows": [
            asdict(change) for change in skipped_format_rows
        ],
        "findings": [asdict(item) for item in summary.findings],
    }
    json_path = output_dir / "db_text_repair_report.json"
    markdown_path = output_dir / "db_text_repair_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
        f"- Surface counts: `{report['surface_counts']}`",
        f"- Conservative changes: `{report['change_count']}`",
        f"- Skipped formatted rows: `{report['skipped_format_row_count']}`",
        f"- Blocking findings: `{report['blocked_quality_count']}`",
        f"- Source-review findings: `{report['needs_source_review_count']}`",
        "",
        "## Changes (first 50)",
        "",
    ]
    for change in report["changes"][:50]:
        lines.extend(_render_change(change))
    lines.extend(["", "## Findings (first 100)", ""])
    for item in report["findings"][:100]:
        metadata = item.get("metadata") or {}
        lines.append(
            f"- `{item['severity']}/{item['category']}` "
            f"{item['table']}#{item['row_id']} `{item['field_path']}` "
            f"{metadata.get('exam_code', '')} "
            f"{metadata.get('subject_name', '')} "
            f"{metadata.get('year', '')}-{metadata.get('session', '')} "
            f"Q{metadata.get('question_number', '')}"
        )
        lines.append(f"  - {compact(item['text'])}")
        if metadata.get("source_url"):
            lines.append(
                f"  - source: {metadata['source_url']} "
                f"page {metadata.get('source_page', '')}"
            )
    lines.append("")
    return "\n".join(lines)


def _render_change(change: dict[str, Any]) -> list[str]:
    metadata = change.get("metadata") or {}
    return [
        (
            f"- {change['table']}#{change['row_id']} "
            f"{metadata.get('exam_code', '')} "
            f"{metadata.get('subject_name', '')} "
            f"{metadata.get('year', '')}-{metadata.get('session', '')} "
            f"Q{metadata.get('question_number', '')}"
        ),
        f"  - before: {compact(change['before'])}",
        f"  - after: {compact(change['after'])}",
    ]


def compact(text: str, limit: int = 220) -> str:
    value = " ".join(str(text or "").split())
    if len(value) > limit:
        return value[: limit - 1] + "…"
    return value


def default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "tmp" / f"db_text_repair_{timestamp}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=str(PROJECT_ROOT / "data" / "exam_bank.db"),
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to the DB.",
    )
    parser.add_argument(
        "--confusables-only",
        action="store_true",
        help="Repair only source-confirmed OCR character confusions.",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db).resolve()
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else default_output_dir()
    )
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    backup_path = None
    if args.apply:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(
            f"{db_path.stem}_before_text_repair_{timestamp}{db_path.suffix}"
        )
        shutil.copy2(db_path, backup_path)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    preview_connection: sqlite3.Connection | None = None
    try:
        changes, skipped = collect_changes(
            connection,
            confusables_only=args.confusables_only,
        )
        if args.apply:
            if changes:
                apply_changes(connection, changes)
            audited_connection = connection
        else:
            preview_connection = sqlite3.connect(":memory:")
            preview_connection.row_factory = sqlite3.Row
            connection.backup(preview_connection)
            if changes:
                apply_changes(preview_connection, changes)
            audited_connection = preview_connection
        summary = AuditSummary(
            surface_counts=collect_surface_counts(audited_connection),
            changes=tuple(changes),
            findings=tuple(collect_findings(audited_connection)),
        )
    finally:
        if preview_connection is not None:
            preview_connection.close()
        connection.close()

    report = write_report(
        output_dir,
        db_path,
        args.apply,
        backup_path,
        summary,
        skipped,
    )
    print(json.dumps({
        "applied": args.apply,
        "backup_path": str(backup_path) if backup_path else None,
        "surface_counts": dict(summary.surface_counts),
        "change_count": len(summary.changes),
        "skipped_format_row_count": len(skipped),
        "blocked_quality_count": sum(
            item.severity == "blocked_quality"
            for item in summary.findings
        ),
        "needs_source_review_count": sum(
            item.severity == "needs_source_review"
            for item in summary.findings
        ),
        "json_report": report["json_report"],
        "markdown_report": report["markdown_report"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
