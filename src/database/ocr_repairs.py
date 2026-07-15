"""Transactional application of source-confirmed OCR repairs to a staging DB."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OcrRepairResult:
    exact_records: int
    applied_records: int
    changed_stems: int
    changed_choice_sets: int


def apply_audited_repairs(
    database: str | Path,
    repairs_path: str | Path,
) -> OcrRepairResult:
    """Apply every exact-source record or roll the complete transaction back."""

    database_path = Path(database).resolve()
    payload = json.loads(Path(repairs_path).read_text(encoding="utf-8"))
    exact = [
        item
        for item in payload.get("repairs", [])
        if item.get("confidence") == "exact_source"
    ]
    applied_records = 0
    changed_stems = 0
    changed_choice_sets = 0
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for repair in exact:
            rows = connection.execute(
                """
                SELECT q.id, q.question_text, q.source_page
                FROM questions q
                JOIN exam_subjects es ON es.id = q.exam_subject_id
                JOIN subjects s ON s.id = es.subject_id
                WHERE s.name_ko = ? AND q.year = ? AND q.session = ?
                  AND q.question_number = ?
                """,
                (
                    str(repair["subject"]),
                    int(repair["year"]),
                    int(repair["session"]),
                    int(repair["question_number"]),
                ),
            ).fetchall()
            identity = (
                repair["subject"],
                repair["year"],
                repair["session"],
                repair["question_number"],
            )
            if len(rows) != 1:
                raise ValueError(
                    f"audited repair identity is not unique: {identity!r}: {len(rows)}"
                )
            question_id, current_stem, source_page = rows[0]
            if int(source_page or 0) != int(repair["source_page"]):
                raise ValueError(
                    "audited repair source page mismatch: "
                    f"{identity!r}: database={source_page!r} "
                    f"audit={repair['source_page']!r}"
                )

            repaired_stem = repair.get("repaired_stem")
            if repaired_stem is not None and str(current_stem) != str(repaired_stem):
                connection.execute(
                    "UPDATE questions SET question_text = ? WHERE id = ?",
                    (str(repaired_stem), int(question_id)),
                )
                changed_stems += 1

            repaired_choices = repair.get("repaired_choices")
            if repaired_choices is not None:
                if not isinstance(repaired_choices, list) or len(repaired_choices) not in (
                    4,
                    5,
                ):
                    raise ValueError(f"invalid audited choices: {identity!r}")
                rows = connection.execute(
                    """
                    SELECT choice_number, choice_text FROM question_choices
                    WHERE question_id = ? ORDER BY choice_number
                    """,
                    (int(question_id),),
                ).fetchall()
                if [int(row[0]) for row in rows] != list(
                    range(1, len(repaired_choices) + 1)
                ):
                    raise ValueError(
                        f"audited repair choice structure mismatch: {identity!r}"
                    )
                expected = [str(value) for value in repaired_choices]
                if [str(row[1]) for row in rows] != expected:
                    connection.executemany(
                        """
                        UPDATE question_choices SET choice_text = ?
                        WHERE question_id = ? AND choice_number = ?
                        """,
                        [
                            (text, int(question_id), number)
                            for number, text in enumerate(expected, start=1)
                        ],
                    )
                    changed_choice_sets += 1
            applied_records += 1

        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("integrity_check failed after OCR repairs")

    return OcrRepairResult(
        exact_records=len(exact),
        applied_records=applied_records,
        changed_stems=changed_stems,
        changed_choice_sets=changed_choice_sets,
    )
