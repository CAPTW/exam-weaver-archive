"""Build and validate an offline-exam staging DB; replace only on explicit request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database.staging import (  # noqa: E402
    ReplacementError,
    build_staging_database,
    replace_mounted_database,
    validate_staging_database,
)


DEFAULT_ROOT = Path(r"E:\1. 인천해사고\2. 수업 관련\8. 학생 진로 상담\해경")
DEFAULT_REPORT_DIR = ROOT / "outputs" / "offline_rebuild"
DEFAULT_STAGING_DB = DEFAULT_REPORT_DIR / "offline_exam_staging.db"
DEFAULT_MOUNTED_DB = ROOT / "data" / "domain_dbs" / "exam_bank.Maritime.db"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(DEFAULT_ROOT), help="Offline PDF root")
    parser.add_argument(
        "--staging-db", default=str(DEFAULT_STAGING_DB), help="Fresh staging SQLite path"
    )
    parser.add_argument(
        "--report-dir", default=str(DEFAULT_REPORT_DIR), help="Inventory and validation report directory"
    )
    parser.add_argument(
        "--mounted-db", default=str(DEFAULT_MOUNTED_DB), help="Mounted DB replaced only with --replace"
    )
    parser.add_argument(
        "--backup-dir", default="", help="Backup directory (defaults beside mounted DB)"
    )
    parser.add_argument(
        "--receipt", default="", help="Replacement receipt JSON path (defaults in report dir)"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="After successful validation, back up and atomically replace the mounted DB",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = Path(args.root)
    staging_db = Path(args.staging_db)
    report_dir = Path(args.report_dir)
    mounted_db = Path(args.mounted_db)

    summary = build_staging_database(root, staging_db, report_dir)
    validation = validate_staging_database(staging_db, summary.expected_sets)
    report_dir.mkdir(parents=True, exist_ok=True)
    validation_path = report_dir / "validation.json"
    validation_path.write_text(
        json.dumps(validation.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"mode={'replace' if args.replace else 'dry-run'}")
    print(f"staging={staging_db.resolve()}")
    print(f"validation={validation_path.resolve()}")
    print(f"valid={validation.valid}")
    if not validation.valid:
        print("errors=" + ",".join(validation.error_codes))
        return 2
    if not args.replace:
        print("mounted database unchanged; pass --replace to replace it")
        return 0

    backup_dir = Path(args.backup_dir) if args.backup_dir else mounted_db.parent / "backups"
    receipt_path = Path(args.receipt) if args.receipt else report_dir / "replacement_receipt.json"
    try:
        receipt = replace_mounted_database(
            staging_db,
            mounted_db,
            backup_dir,
            receipt_path,
        )
    except ReplacementError as exc:
        print(f"replacement failed: {exc}", file=sys.stderr)
        return 3
    if receipt is not None:
        print(f"backup={receipt.backup_path}")
        print(f"receipt={receipt.receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
