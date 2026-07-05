from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.db_mount_prototype.domain_split import (  # noqa: E402
    split_database_by_domain,
    write_plan,
    write_single_snapshot_manifest,
)
from experiments.db_mount_prototype.mount_repo import MountedExamRepository  # noqa: E402


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the experimental DB mount prototype.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest", help="Create a one-mount manifest for a snapshot DB.")
    manifest.add_argument("--snapshot", required=True)
    manifest.add_argument("--out", default="experiments/db_mount_prototype/mount_manifest.local.json")
    manifest.add_argument("--id", default="main")
    manifest.add_argument("--label", default="Main snapshot")

    status = subparsers.add_parser("status", help="Validate mounts and show aggregate counts.")
    status.add_argument("--manifest", required=True)

    search = subparsers.add_parser("search", help="Smoke-test mounted question search.")
    search.add_argument("--manifest", required=True)
    search.add_argument("--exam-code")
    search.add_argument("--subject-code")
    search.add_argument("--year", type=int)
    search.add_argument("--search-text")
    search.add_argument("--limit", type=int, default=5)

    plan = subparsers.add_parser("plan", help="Classify exams and write a dry-run split plan.")
    plan.add_argument("--db", default="data/exam_bank.db")
    plan.add_argument("--out", default="tmp/db_mount_domain_plan.json")

    split = subparsers.add_parser("split", help="Split a DB into domain DBs.")
    split.add_argument("--db", default="data/exam_bank.db")
    split.add_argument("--out-dir", default="data/domain_dbs")
    split.add_argument("--domain", action="append", dest="domains")
    split.add_argument("--overwrite", action="store_true")
    split.add_argument("--manifest-out", default="data/domain_dbs/mount_manifest.json")
    split.add_argument("--apply", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "manifest":
        out = write_single_snapshot_manifest(
            args.snapshot,
            args.out,
            mount_id=args.id,
            label=args.label,
        )
        print(f"wrote mount manifest: {out}")
        return 0

    if args.command == "status":
        repo = MountedExamRepository(args.manifest)
        repo.validate_mounts()
        _print_json(repo.get_statistics())
        return 0

    if args.command == "search":
        repo = MountedExamRepository(args.manifest)
        rows = repo.get_questions_with_choices(
            exam_code=args.exam_code,
            subject_code=args.subject_code,
            year=args.year,
            search_text=args.search_text,
            limit=args.limit,
        )
        _print_json({
            "count": len(rows),
            "questions": [
                {
                    "id": row["id"],
                    "mount_id": row["mount_id"],
                    "exam_code": row.get("exam_code"),
                    "subject_code": row.get("subject_code"),
                    "year": row.get("year"),
                    "session": row.get("session"),
                    "question_number": row.get("question_number"),
                    "choice_count": len(row.get("choices") or []),
                    "question_text": row.get("question_text"),
                }
                for row in rows
            ],
        })
        return 0

    if args.command == "plan":
        out = write_plan(args.db, args.out)
        print(f"wrote domain plan: {out}")
        return 0

    if args.command == "split":
        if not args.apply:
            out = write_plan(args.db, Path(args.out_dir) / "domain_split_plan.json")
            print(f"dry-run only; wrote plan: {out}")
            print("pass --apply to create domain DB files")
            return 0
        result = split_database_by_domain(
            args.db,
            args.out_dir,
            domains=args.domains,
            overwrite=args.overwrite,
            manifest_out=args.manifest_out,
        )
        _print_json(result)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

