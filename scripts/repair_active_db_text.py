"""Dry-run or atomically repair the four active local exam databases."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.database.source_review import (  # noqa: E402
    attach_legacy_maritime_sources,
    render_source_evidence,
)
from src.database.text_repair_batch import (  # noqa: E402
    PreparedDatabaseRepair,
    RepairTarget,
    commit_repair_batch,
    prepare_repair_batch,
)


TARGETS = (
    (
        "maritime_all",
        Path("data/domain_dbs/exam_bank.maritime_all.db"),
    ),
    (
        "user_workspace",
        Path("data/domain_dbs/exam_bank.user_workspace.db"),
    ),
    (
        "Maritime",
        Path("data/domain_dbs/exam_bank.Maritime.db"),
    ),
    ("legacy_exam_bank", Path("data/exam_bank.db")),
)
DEFAULT_REPAIR_REGISTRIES = (
    PROJECT_ROOT / "src" / "parser" / "offline_source_repairs.json",
    PROJECT_ROOT / "src" / "parser" / "maritime_source_repairs.json",
)


def active_targets(root: Path) -> tuple[RepairTarget, ...]:
    resolved_root = root.resolve()
    targets = tuple(
        RepairTarget(name, (resolved_root / relative).resolve())
        for name, relative in TARGETS
    )
    missing = [
        str(target.mounted_path)
        for target in targets
        if not target.mounted_path.is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "missing active databases: " + ", ".join(missing)
        )
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit and repair all active exam DB rich text.",
    )
    parser.add_argument("--root", default=str(PROJECT_ROOT))
    parser.add_argument(
        "--repairs",
        action="append",
        default=None,
        help=(
            "Source-confirmed repair registry. Repeat to apply multiple "
            "registries; both bundled registries are used by default."
        ),
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--legacy-source-root",
        default=None,
        help=(
            "Directory containing the 2018/ and 2019/ legacy maritime "
            "source PDFs used to enrich source-review evidence."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Atomically replace all four DBs after validation.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    repairs = tuple(
        Path(value).resolve()
        for value in (args.repairs or DEFAULT_REPAIR_REGISTRIES)
    )
    missing_repairs = [path for path in repairs if not path.is_file()]
    if missing_repairs:
        raise FileNotFoundError(missing_repairs[0])
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else _default_output_dir()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    prepared = prepare_repair_batch(
        active_targets(root),
        repairs,
        output_dir / "staging",
    )
    if args.legacy_source_root:
        source_root = Path(args.legacy_source_root).resolve()
        prepared = tuple(
            replace(
                item,
                audit=replace(
                    item.audit,
                    findings=attach_legacy_maritime_sources(
                        item.audit.findings,
                        source_root,
                    ),
                ),
            )
            for item in prepared
        )
    review_findings = [
        finding
        for item in prepared
        for finding in item.audit.findings
        if finding.severity == "needs_source_review"
    ]
    evidence = render_source_evidence(
        review_findings,
        output_dir / "source_evidence",
    )

    receipt: dict[str, object] | None = None
    if args.apply:
        receipt = commit_repair_batch(
            prepared,
            output_dir / "backups",
            output_dir / "receipt.json",
        )
    report = _build_report(
        prepared,
        mode="apply" if args.apply else "dry-run",
        evidence=[item.to_dict() for item in evidence],
        receipt=receipt,
    )
    _write_reports(output_dir, report)
    print(json.dumps({
        "mode": report["mode"],
        "status": report["status"],
        "database_count": len(report["databases"]),
        "change_count": sum(
            int(item["change_count"])
            for item in report["databases"]
        ),
        "blocked_quality_count": sum(
            int(item["blocked_quality_count"])
            for item in report["databases"]
        ),
        "needs_source_review_count": sum(
            int(item["needs_source_review_count"])
            for item in report["databases"]
        ),
        "summary_json": str(output_dir / "summary.json"),
        "summary_markdown": str(output_dir / "summary.md"),
    }, ensure_ascii=False, indent=2))
    return 0


def _build_report(
    prepared: Sequence[PreparedDatabaseRepair],
    *,
    mode: str,
    evidence: list[dict[str, object]],
    receipt: dict[str, object] | None,
) -> dict[str, object]:
    receipt_targets = {
        str(item["name"]): item
        for item in ((receipt or {}).get("targets") or [])
    }
    databases: list[dict[str, object]] = []
    for item in prepared:
        blocked = [
            finding
            for finding in item.audit.findings
            if finding.severity == "blocked_quality"
        ]
        review = [
            finding
            for finding in item.audit.findings
            if finding.severity == "needs_source_review"
        ]
        receipt_item = receipt_targets.get(item.target.name, {})
        database = {
            "name": item.target.name,
            "mounted_path": str(item.target.mounted_path),
            "staging_path": str(item.staging_path),
            "applied": mode == "apply",
            "backup_path": receipt_item.get("backup_path"),
            "before_sha256": item.original_sha256,
            "staging_sha256": item.staging_sha256,
            "after_sha256": receipt_item.get("after_sha256"),
            "surface_counts": dict(item.audit.surface_counts),
            "change_count": len(item.audit.changes),
            "source_confirmed_change_count": (
                item.source_repair_result.changed_source_pages
                + item.source_repair_result.changed_stems
                + item.source_repair_result.changed_question_formats
                + item.source_repair_result.changed_question_images
                + item.source_repair_result.changed_choice_sets
            ),
            "blocked_quality_count": len(blocked),
            "needs_source_review_count": len(review),
            "changes": [
                asdict(change) for change in item.audit.changes
            ],
            "findings": [
                asdict(finding) for finding in item.audit.findings
            ],
            "source_repair_result": asdict(item.source_repair_result),
            "validation": asdict(item.validation),
        }
        databases.append(database)
    return {
        "mode": mode,
        "status": (
            str(receipt.get("status"))
            if receipt is not None
            else "prepared"
        ),
        "applied": mode == "apply",
        "databases": databases,
        "source_evidence": evidence,
        "receipt": receipt,
    }


def _write_reports(
    output_dir: Path,
    report: dict[str, object],
) -> None:
    for database in report["databases"]:
        _write_json(
            output_dir / f"{database['name']}_audit.json",
            database,
        )
    _write_json(output_dir / "summary.json", report)
    (output_dir / "summary.md").write_text(
        _render_markdown(report),
        encoding="utf-8",
    )


def _render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# Active DB Rich Text Repair Report",
        "",
        f"- Mode: `{report['mode']}`",
        f"- Status: `{report['status']}`",
        "",
        "| DB | Applied | Auto | Source | Blocked | Review | Integrity | Smoke |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for database in report["databases"]:
        validation = database["validation"]
        lines.append(
            f"| {database['name']} | {database['applied']} | "
            f"{database['change_count']} | "
            f"{database['source_confirmed_change_count']} | "
            f"{database['blocked_quality_count']} | "
            f"{database['needs_source_review_count']} | "
            f"{validation['integrity_check']} | "
            f"{validation['smoke_ok']} |"
        )
    for database in report["databases"]:
        lines.extend([
            "",
            f"## {database['name']}",
            "",
            f"- Mounted: `{database['mounted_path']}`",
            f"- Staging: `{database['staging_path']}`",
            f"- Backup: `{database['backup_path']}`",
            f"- Surface counts: `{database['surface_counts']}`",
            "",
            "### Changes (first 50)",
            "",
        ])
        for change in database["changes"][:50]:
            lines.append(
                f"- `{change['table']}#{change['row_id']}` "
                f"{_compact(change['before'])} → {_compact(change['after'])}"
            )
        lines.extend(["", "### Findings (first 100)", ""])
        for finding in database["findings"][:100]:
            metadata = finding.get("metadata") or {}
            lines.append(
                f"- `{finding['severity']}/{finding['category']}` "
                f"`{finding['field_path']}` {_compact(finding['text'])}"
            )
            if metadata.get("source_url"):
                lines.append(
                    f"  - source: {metadata['source_url']} "
                    f"page {metadata.get('source_page', '')}"
                )
    lines.extend(["", "## Source Evidence", ""])
    for item in report["source_evidence"]:
        lines.append(
            f"- `{item['status']}` {item['source_url']} "
            f"page {item['source_page']} → `{item['image_path']}`"
        )
    lines.append("")
    return "\n".join(lines)


def _compact(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _default_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PROJECT_ROOT / "tmp" / f"active_db_text_repair_{timestamp}"


if __name__ == "__main__":
    raise SystemExit(main())
