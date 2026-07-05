from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.db_mount_prototype.exam_move import (  # noqa: E402
    ExamMoveConflict,
    apply_exam_move,
    dry_run_exam_move,
)


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _plan_payload(plan):
    return {
        **asdict(plan),
        "issues": [asdict(issue) for issue in plan.issues],
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move one exam between mounted exam-bank DB files.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("dry-run", "apply"):
        command = subparsers.add_parser(name)
        command.add_argument("--from-db", required=True, help="Source SQLite DB path")
        command.add_argument("--to-db", required=True, help="Target SQLite DB path")
        command.add_argument("--exam-code", required=True, help="Exam code to move")
    subparsers.choices["apply"].add_argument(
        "--no-backup",
        action="store_true",
        help="Skip source/target backups before applying the move",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.command == "dry-run":
        plan = dry_run_exam_move(args.from_db, args.to_db, args.exam_code)
        _print_json(_plan_payload(plan))
        return 0 if plan.can_apply else 2

    if args.command == "apply":
        try:
            result = apply_exam_move(
                args.from_db,
                args.to_db,
                args.exam_code,
                backup=not args.no_backup,
            )
        except ExamMoveConflict as exc:
            _print_json({"moved": False, "error": str(exc)})
            return 2
        _print_json({
            "moved": result.moved,
            "target_exam_id": result.target_exam_id,
            "source_backup": result.source_backup,
            "target_backup": result.target_backup,
            "plan": _plan_payload(result.plan),
        })
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

