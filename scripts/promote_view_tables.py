"""Build, validate, and optionally install a one-cell `<보기>` table staging DB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.database.view_table_migration import (  # noqa: E402
    build_view_table_staging,
    replace_with_view_table_staging,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote explicit <보기> blocks through a validated staging DB."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--staging-db", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--backup-dir")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    source = Path(args.db).resolve()
    staging = Path(args.staging_db).resolve()
    report_path = Path(args.report).resolve()
    migration = build_view_table_staging(source, staging)
    payload = {"migration": migration.to_dict(), "replacement": None}
    if not migration.valid:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1

    if args.replace:
        backup_dir = (
            Path(args.backup_dir).resolve()
            if args.backup_dir
            else source.parent / "backups"
        )
        receipt = replace_with_view_table_staging(source, staging, backup_dir)
        payload["replacement"] = receipt.to_dict()

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
