"""Verify that every bundled exact-source OCR repair is present in a database."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.parser.aligned_choice_table import build_aligned_choice_payloads  # noqa: E402
from src.parser.view_table import promote_view_block  # noqa: E402

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
            has_exam_identity = repair.get("year") is not None and repair.get(
                "session"
            ) is not None
            if has_exam_identity:
                identity_filter = (
                    "q.year = ? AND q.session = ? AND q.question_number = ?"
                )
                identity_params = (
                    int(repair["year"]),
                    int(repair["session"]),
                    int(repair["question_number"]),
                )
            else:
                identity_filter = "q.id = ? AND q.question_number = ?"
                identity_params = (
                    int(repair.get("question_id", 0) or 0),
                    int(repair["question_number"]),
                )
            rows = connection.execute(
                f"""
                SELECT q.id, q.question_text, q.question_format_json,
                       q.source_page, q.has_image, q.image_path, qs.source_url
                FROM questions q
                JOIN exam_subjects es ON es.id = q.exam_subject_id
                JOIN subjects s ON s.id = es.subject_id
                LEFT JOIN question_sources qs ON qs.id = q.source_id
                WHERE s.name_ko = ? AND {identity_filter}
                """,
                (repair["subject"], *identity_params),
            ).fetchall()
            identity = {
                key: repair.get(key)
                for key in (
                    "question_id",
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
            if int(row["source_page"] or 0) != int(repair["source_page"]):
                mismatches.append(
                    {
                        **identity,
                        "question_id": int(row["id"]),
                        "field": "source_page",
                        "expected": int(repair["source_page"]),
                        "actual": row["source_page"],
                    }
                )
            if not has_exam_identity:
                database_source = Path(
                    unquote(urlparse(str(row["source_url"] or "")).path)
                ).name.casefold()
                expected_source = Path(
                    str(repair["source_pdf_relative_path"]).replace("\\", "/")
                ).name.casefold()
                if database_source != expected_source:
                    mismatches.append(
                        {
                            **identity,
                            "question_id": int(row["id"]),
                            "field": "source_document",
                            "expected": expected_source,
                            "actual": database_source,
                        }
                    )
            expected_stem = repair.get("repaired_stem")
            if expected_stem is not None:
                promoted_text, promoted_format, promoted = promote_view_block(
                    str(expected_stem)
                )
                plain_match = row["question_text"] == expected_stem
                promoted_match = (
                    promoted
                    and row["question_text"] == promoted_text
                    and row["question_format_json"] == promoted_format
                )
                if not plain_match and not promoted_match:
                    mismatches.append(
                        {
                            **identity,
                            "question_id": int(row["id"]),
                            "field": "stem",
                            "expected": expected_stem,
                            "expected_promoted_text": promoted_text,
                            "actual": row["question_text"],
                            "actual_format": row["question_format_json"],
                        }
                    )
            expected_choices = repair.get("repaired_choices")
            expected_choice_overrides = repair.get("repaired_choice_overrides")
            expected_choice_fields = repair.get("repaired_choice_fields")
            expected_formats = None
            if expected_choice_fields is not None:
                expected_choices, expected_formats = build_aligned_choice_payloads(
                    expected_choice_fields
                )
            if expected_choices is not None:
                stored_choices = [
                    (str(choice[0]), choice[1])
                    for choice in connection.execute(
                        """
                        SELECT choice_text, choice_format_json FROM question_choices
                        WHERE question_id = ? ORDER BY choice_number
                        """,
                        (int(row["id"]),),
                    )
                ]
                choices = [choice[0] for choice in stored_choices]
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
                if expected_formats is not None:
                    actual_formats = [choice[1] for choice in stored_choices]
                    if actual_formats != expected_formats:
                        mismatches.append(
                            {
                                **identity,
                                "question_id": int(row["id"]),
                                "field": "choice_formats",
                                "expected": expected_formats,
                                "actual": actual_formats,
                            }
                        )
            elif expected_choice_overrides is not None:
                choices = {
                    str(choice[0]): str(choice[1])
                    for choice in connection.execute(
                        """
                        SELECT choice_number, choice_text FROM question_choices
                        WHERE question_id = ? ORDER BY choice_number
                        """,
                        (int(row["id"]),),
                    )
                }
                for number, expected in expected_choice_overrides.items():
                    actual = choices.get(str(number))
                    if actual != str(expected):
                        mismatches.append(
                            {
                                **identity,
                                "question_id": int(row["id"]),
                                "field": f"choice_{number}",
                                "expected": str(expected),
                                "actual": actual,
                            }
                        )
            expected_question_image = repair.get("repaired_question_image_path")
            if expected_question_image is not None:
                expected_question_image = str(expected_question_image)
                image_file = ROOT / expected_question_image
                if (
                    int(row["has_image"] or 0) != 1
                    or row["image_path"] != expected_question_image
                    or not image_file.is_file()
                ):
                    mismatches.append(
                        {
                            **identity,
                            "question_id": int(row["id"]),
                            "field": "question_image",
                            "expected": expected_question_image,
                            "actual": row["image_path"],
                            "file_exists": image_file.is_file(),
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
