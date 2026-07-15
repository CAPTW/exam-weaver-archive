"""Verify that every bundled exact-source OCR repair is present in a database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPAIRS = ROOT / "src" / "parser" / "offline_source_repairs.json"


def validate_database(
    database: Path, repairs_path: Path
) -> dict[str, object]:
    payload = json.loads(repairs_path.read_text(encoding="utf-8"))
    exact = [
        item
        for item in payload.get("repairs", [])
        if item.get("confidence") == "exact_source"
    ]
    mismatches: list[dict[str, object]] = []
    uri = database.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        for repair in exact:
            rows = connection.execute(
                """
                SELECT q.id, q.question_text
                FROM questions q
                JOIN exam_subjects es ON es.id = q.exam_subject_id
                JOIN subjects s ON s.id = es.subject_id
                WHERE s.name_ko = ? AND q.year = ? AND q.session = ?
                  AND q.question_number = ?
                """,
                (
                    repair["subject"],
                    int(repair["year"]),
                    int(repair["session"]),
                    int(repair["question_number"]),
                ),
            ).fetchall()
            identity = {
                key: repair[key]
                for key in (
                    "subject",
                    "year",
                    "session",
                    "question_number",
                    "source_page",
                )
            }
            if len(rows) != 1:
                mismatches.append(
                    {**identity, "field": "question", "actual_count": len(rows)}
                )
                continue
            row = rows[0]
            expected_stem = repair.get("repaired_stem")
            if expected_stem is not None and row["question_text"] != expected_stem:
                mismatches.append(
                    {
                        **identity,
                        "question_id": int(row["id"]),
                        "field": "stem",
                        "expected": expected_stem,
                        "actual": row["question_text"],
                    }
                )
            expected_choices = repair.get("repaired_choices")
            if expected_choices is not None:
                choices = [
                    str(choice[0])
                    for choice in connection.execute(
                        """
                        SELECT choice_text FROM question_choices
                        WHERE question_id = ? ORDER BY choice_number
                        """,
                        (int(row["id"]),),
                    )
                ]
                if choices != expected_choices:
                    mismatches.append(
                        {
                            **identity,
                            "question_id": int(row["id"]),
                            "field": "choices",
                            "expected": expected_choices,
                            "actual": choices,
                        }
                    )
    return {
        "database": str(database.resolve()),
        "repair_bundle": str(repairs_path.resolve()),
        "exact_repair_count": len(exact),
        "mismatch_count": len(mismatches),
        "valid": not mismatches,
        "mismatches": mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--repairs", type=Path, default=DEFAULT_REPAIRS)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate_database(args.database, args.repairs)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({key: report[key] for key in (
        "exact_repair_count", "mismatch_count", "valid"
    )}, ensure_ascii=False))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
