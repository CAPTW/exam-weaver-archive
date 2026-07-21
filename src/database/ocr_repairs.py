"""Transactional application of source-confirmed OCR repairs to a staging DB."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from src.parser.aligned_choice_table import build_aligned_choice_payloads
from src.parser.offline_repairs import replace_single_view_text


CHOICE_SYMBOLS = ("㉮", "㉯", "㉴", "㉵", "⑤")


@dataclass(frozen=True)
class OcrRepairResult:
    exact_records: int
    applied_records: int
    changed_source_pages: int
    changed_stems: int
    changed_question_formats: int
    changed_question_images: int
    changed_choice_sets: int


def apply_audited_repairs(
    database: str | Path,
    repairs_path: str | Path,
    *,
    allow_unmatched: bool = False,
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
    changed_source_pages = 0
    changed_stems = 0
    changed_question_formats = 0
    changed_question_images = 0
    changed_choice_sets = 0
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for repair in exact:
            exam_code = str(repair.get("exam_code", "") or "").strip()
            subject_code = str(repair.get("subject_code", "") or "").strip()
            if bool(exam_code) != bool(subject_code):
                raise ValueError(
                    "audited repair requires both exam_code and subject_code"
                )
            if exam_code:
                subject_predicate = "e.code = ? AND s.code = ?"
                subject_params = (exam_code, subject_code)
                identity_subject = (exam_code, subject_code)
            else:
                subject = str(repair.get("subject", "") or "").strip()
                if not subject:
                    raise ValueError("audited repair is missing subject identity")
                subject_predicate = "s.name_ko = ?"
                subject_params = (subject,)
                identity_subject = (subject,)
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
                identity = (*identity_subject, *identity_params)
            else:
                question_id = int(repair.get("question_id", 0) or 0)
                audited_source = str(
                    repair.get("source_pdf_relative_path", "") or ""
                ).strip()
                if question_id < 1 or not audited_source:
                    raise ValueError(
                        "audited repair without year/session requires question_id "
                        "and source_pdf_relative_path"
                    )
                identity_filter = "q.id = ? AND q.question_number = ?"
                identity_params = (question_id, int(repair["question_number"]))
                identity = (*identity_subject, question_id, repair["question_number"])
            rows = connection.execute(
                f"""
                SELECT q.id, q.question_text, q.question_format_json,
                       q.source_page, qs.source_url
                FROM questions q
                JOIN exam_subjects es ON es.id = q.exam_subject_id
                JOIN subjects s ON s.id = es.subject_id
                JOIN exams e ON e.id = es.exam_id
                LEFT JOIN question_sources qs ON qs.id = q.source_id
                WHERE {subject_predicate} AND {identity_filter}
                """,
                (*subject_params, *identity_params),
            ).fetchall()
            if len(rows) == 0 and allow_unmatched:
                continue
            if len(rows) != 1:
                raise ValueError(
                    f"audited repair identity is not unique: {identity!r}: {len(rows)}"
                )
            (
                question_id,
                current_stem,
                current_question_format,
                source_page,
                source_url,
            ) = rows[0]
            if not has_exam_identity:
                database_source = Path(
                    unquote(urlparse(str(source_url or "")).path)
                ).name.casefold()
                audited_source = Path(
                    str(repair["source_pdf_relative_path"]).replace("\\", "/")
                ).name.casefold()
                if database_source != audited_source:
                    raise ValueError(
                        "audited repair source document mismatch: "
                        f"{identity!r}: database={database_source!r} "
                        f"audit={audited_source!r}"
                    )
            audited_source_page = int(repair["source_page"])
            source_page_matches = (
                source_page is not None
                and int(source_page) == audited_source_page
            )
            expected_current_page = repair.get("expected_current_source_page")
            source_page_is_audited_previous = (
                expected_current_page is not None
                and source_page is not None
                and int(source_page) == int(expected_current_page)
            )
            if (
                source_page is not None
                and not source_page_matches
                and not source_page_is_audited_previous
            ):
                raise ValueError(
                    "audited repair source page mismatch: "
                    f"{identity!r}: database={source_page!r} "
                    f"audit={repair['source_page']!r} "
                    f"expected_previous={expected_current_page!r}"
                )
            if not source_page_matches:
                connection.execute(
                    "UPDATE questions SET source_page = ? WHERE id = ?",
                    (audited_source_page, int(question_id)),
                )
                changed_source_pages += 1

            repaired_stem = repair.get("repaired_stem")
            target_stem = (
                str(repaired_stem)
                if repaired_stem is not None
                else str(current_stem)
            )
            expected_current_stem = repair.get("expected_current_stem")
            if (
                repaired_stem is not None
                and expected_current_stem is not None
                and not _matches_expected(
                    str(current_stem),
                    str(expected_current_stem),
                    target_stem,
                )
            ):
                raise ValueError(
                    "audited repair stem mismatch: "
                    f"{identity!r}: database={current_stem!r} "
                    f"expected={expected_current_stem!r} "
                    f"repaired={target_stem!r}"
                )

            target_question_format = current_question_format
            repaired_question_format = repair.get(
                "repaired_question_format_json"
            )
            repaired_view_text = repair.get("repaired_view_text")
            if (
                repaired_question_format is not None
                and repaired_view_text is not None
            ):
                raise ValueError(
                    f"ambiguous audited question format: {identity!r}"
                )
            if repaired_question_format is not None:
                repaired_format_object = _json_object(
                    repaired_question_format,
                    label="repaired_question_format_json",
                )
                current_format_object = (
                    _json_object(
                        current_question_format,
                        label="database question_format_json",
                    )
                    if current_question_format
                    else None
                )
                if "expected_current_question_format_json" in repair:
                    expected_format_object = _json_object(
                        repair["expected_current_question_format_json"],
                        label="expected_current_question_format_json",
                    )
                    if not _matches_expected(
                        current_format_object,
                        expected_format_object,
                        repaired_format_object,
                    ):
                        raise ValueError(
                            "audited repair question format mismatch: "
                            f"{identity!r}"
                        )
                target_question_format = json.dumps(
                    repaired_format_object,
                    ensure_ascii=False,
                )
            elif repaired_view_text is not None:
                target_question_format = replace_single_view_text(
                    current_question_format,
                    str(repaired_view_text),
                    expected_current_text=(
                        str(repair["expected_current_view_text"])
                        if "expected_current_view_text" in repair
                        else None
                    ),
                )
            elif repaired_stem is not None and str(current_stem) != target_stem:
                target_question_format = None

            stem_changed = str(current_stem) != target_stem
            format_changed = current_question_format != target_question_format
            if stem_changed or format_changed:
                connection.execute(
                    """
                    UPDATE questions
                    SET question_text = ?, question_format_json = ?
                    WHERE id = ?
                    """,
                    (
                        target_stem,
                        target_question_format,
                        int(question_id),
                    ),
                )
            if stem_changed:
                changed_stems += 1
            if format_changed:
                changed_question_formats += 1

            repaired_question_image = repair.get("repaired_question_image_path")
            if repaired_question_image is not None:
                repaired_question_image = str(repaired_question_image).strip()
                if not repaired_question_image:
                    raise ValueError(
                        f"invalid audited question image: {identity!r}"
                    )
                current_question_image = connection.execute(
                    "SELECT has_image, image_path FROM questions WHERE id = ?",
                    (int(question_id),),
                ).fetchone()
                if current_question_image != (1, repaired_question_image):
                    connection.execute(
                        "UPDATE questions SET has_image = 1, image_path = ? WHERE id = ?",
                        (repaired_question_image, int(question_id)),
                    )
                    changed_question_images += 1

            repaired_choices = repair.get("repaired_choices")
            repaired_choice_overrides = repair.get("repaired_choice_overrides")
            repaired_choice_fields = repair.get("repaired_choice_fields")
            if sum(
                value is not None
                for value in (
                    repaired_choices,
                    repaired_choice_overrides,
                    repaired_choice_fields,
                )
            ) > 1:
                raise ValueError(f"ambiguous audited choices: {identity!r}")
            repaired_choice_formats = None
            if repaired_choice_fields is not None:
                repaired_choices, repaired_choice_formats = (
                    build_aligned_choice_payloads(repaired_choice_fields)
                )
            if repaired_choices is not None:
                if not isinstance(repaired_choices, list) or len(repaired_choices) not in (
                    4,
                    5,
                ):
                    raise ValueError(f"invalid audited choices: {identity!r}")
                repaired_choice_images = repair.get("repaired_choice_image_paths")
                if repaired_choice_images is not None and (
                    not isinstance(repaired_choice_images, list)
                    or len(repaired_choice_images) != len(repaired_choices)
                ):
                    raise ValueError(f"invalid audited choice images: {identity!r}")
                rows = connection.execute(
                    """
                    SELECT choice_number, choice_text, choice_symbol,
                           choice_image_path, choice_format_json
                    FROM question_choices
                    WHERE question_id = ? ORDER BY choice_number
                    """,
                    (int(question_id),),
                ).fetchall()
                expected = [str(value) for value in repaired_choices]
                current_symbols = {int(row[0]): row[2] for row in rows}
                current_images = {int(row[0]): row[3] for row in rows}
                if repaired_choice_images is None:
                    expected_images = [
                        current_images.get(number)
                        for number in range(1, len(expected) + 1)
                    ]
                else:
                    expected_images = [
                        str(value) if value is not None and str(value).strip() else None
                        for value in repaired_choice_images
                    ]
                if any(
                    not text.strip() and not image_path
                    for text, image_path in zip(expected, expected_images)
                ):
                    raise ValueError(
                        f"audited choice has neither text nor image: {identity!r}"
                    )
                current_numbers = [int(row[0]) for row in rows]
                current_text = [str(row[1]) for row in rows]
                current_symbol_list = [row[2] for row in rows]
                current_image_list = [row[3] for row in rows]
                current_formats = [row[4] for row in rows]
                expected_numbers = list(range(1, len(expected) + 1))
                expected_symbols = [
                    current_symbols.get(number, CHOICE_SYMBOLS[number - 1])
                    for number in expected_numbers
                ]
                expected_formats = (
                    list(repaired_choice_formats)
                    if repaired_choice_formats is not None
                    else [None] * len(expected)
                )
                if (
                    current_numbers != expected_numbers
                    or current_text != expected
                    or current_symbol_list != expected_symbols
                    or current_image_list != expected_images
                    or current_formats != expected_formats
                ):
                    connection.execute(
                        """
                        DELETE FROM question_choices
                        WHERE question_id = ? AND choice_number > ?
                        """,
                        (int(question_id), len(expected)),
                    )
                    connection.executemany(
                        """
                        INSERT INTO question_choices (
                            question_id, choice_number, choice_symbol,
                            choice_text, choice_image_path, choice_format_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(question_id, choice_number) DO UPDATE SET
                            choice_symbol = excluded.choice_symbol,
                            choice_text = excluded.choice_text,
                            choice_image_path = excluded.choice_image_path,
                            choice_format_json = excluded.choice_format_json
                        """,
                        [
                            (
                                int(question_id),
                                number,
                                expected_symbols[number - 1],
                                text,
                                expected_images[number - 1],
                                expected_formats[number - 1],
                            )
                            for number, text in enumerate(expected, start=1)
                        ],
                    )
                    changed_choice_sets += 1
            elif repaired_choice_overrides is not None:
                if (
                    not isinstance(repaired_choice_overrides, dict)
                    or not repaired_choice_overrides
                ):
                    raise ValueError(f"invalid audited choice overrides: {identity!r}")
                current_choices = {
                    int(row[0]): str(row[1])
                    for row in connection.execute(
                        """
                        SELECT choice_number, choice_text
                        FROM question_choices
                        WHERE question_id = ? ORDER BY choice_number
                        """,
                        (int(question_id),),
                    )
                }
                updates: list[tuple[str, int, int]] = []
                for raw_number, raw_value in repaired_choice_overrides.items():
                    number = int(raw_number)
                    value = str(raw_value).strip()
                    if number not in current_choices or number not in range(1, 6) or not value:
                        raise ValueError(
                            f"invalid audited choice override: {identity!r}: {raw_number!r}"
                        )
                    if current_choices[number] != value:
                        updates.append((value, int(question_id), number))
                if updates:
                    connection.executemany(
                        """
                        UPDATE question_choices
                        SET choice_text = ?, choice_format_json = NULL
                        WHERE question_id = ? AND choice_number = ?
                        """,
                        updates,
                    )
                    changed_choice_sets += 1
            applied_records += 1

        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("integrity_check failed after OCR repairs")

    return OcrRepairResult(
        exact_records=len(exact),
        applied_records=applied_records,
        changed_source_pages=changed_source_pages,
        changed_stems=changed_stems,
        changed_question_formats=changed_question_formats,
        changed_question_images=changed_question_images,
        changed_choice_sets=changed_choice_sets,
    )


def _json_object(value: object, *, label: str) -> dict:
    try:
        payload = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a JSON object") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _matches_expected(
    current: object,
    expected: object,
    repaired: object,
) -> bool:
    return current == expected or current == repaired
