"""Build a reproducible exact-source repair bundle for the maritime exam DB."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "exam_bank.db"
DEFAULT_OUTPUT = ROOT / "src" / "parser" / "maritime_source_repairs.json"


def _iter_confirmed_records(payload: object) -> Iterable[Mapping[str, object]]:
    if isinstance(payload, list):
        collections = [payload]
    elif isinstance(payload, Mapping):
        collections = [
            value
            for key in ("records", "confirmed_repairs", "repairs")
            if isinstance((value := payload.get(key)), list)
        ]
    else:
        collections = []
    for collection in collections:
        for raw in collection:
            if not isinstance(raw, Mapping):
                continue
            status = str(raw.get("status", "") or "").casefold()
            confidence = str(raw.get("confidence", "") or "").casefold()
            has_exact_value = isinstance(raw.get("exact_source_value"), Mapping)
            if status not in {"confirmed", "exact_source"} and confidence != "exact_source":
                continue
            if has_exact_value or raw.get("repaired_stem") is not None or raw.get("repaired_choices") is not None:
                yield raw


def _question_row(connection: sqlite3.Connection, question_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT q.id, e.code AS exam_code, s.code AS subject_code,
               q.year, q.session, q.question_number, q.question_text,
               q.source_page
        FROM questions q
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        WHERE q.id = ?
        """,
        (question_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"audited question does not exist: id={question_id}")
    return row


def _validate_natural_key(raw: Mapping[str, object], row: sqlite3.Row) -> None:
    natural_key = raw.get("natural_key")
    if not isinstance(natural_key, Mapping):
        return
    expected = {
        "exam_code": str(row["exam_code"]),
        "subject_code": str(row["subject_code"]),
        "year": int(row["year"]),
        "session": int(row["session"]),
        "question_number": int(row["question_number"]),
    }
    for key, expected_value in expected.items():
        if key not in natural_key:
            continue
        actual = natural_key[key]
        if str(actual) != str(expected_value):
            raise ValueError(
                f"audited natural key mismatch for id={row['id']}: "
                f"{key}={actual!r}, database={expected_value!r}"
            )


def _exact_values(
    raw: Mapping[str, object],
) -> tuple[object, object, dict[int, str], object, object]:
    exact = raw.get("exact_source_value")
    exact_mapping = exact if isinstance(exact, Mapping) else {}
    stem = exact_mapping.get("question_text", exact_mapping.get("stem"))
    if stem is None:
        stem = raw.get("repaired_stem")
    choices = exact_mapping.get("choices", raw.get("repaired_choices"))
    partial: dict[int, str] = {}
    for key, value in exact_mapping.items():
        key_text = str(key)
        if key_text.startswith("choice_") and key_text[7:].isdigit():
            partial[int(key_text[7:])] = str(value)
    choice_images = exact_mapping.get(
        "choice_image_paths", raw.get("repaired_choice_image_paths")
    )
    if isinstance(choices, list) and choices and all(
        isinstance(value, Mapping) for value in choices
    ):
        ordered_choices = sorted(
            choices,
            key=lambda value: int(value.get("choice_number", 0) or 0),
        )
        choices = [str(value.get("choice_text", "") or "") for value in ordered_choices]
        if choice_images is None and any(
            value.get("choice_image_path") for value in ordered_choices
        ):
            choice_images = [value.get("choice_image_path") for value in ordered_choices]
    if choice_images is None:
        choice_crops = exact_mapping.get("choice_image_crops")
        if isinstance(choice_crops, list):
            ordered_crops = sorted(
                (
                    value for value in choice_crops
                    if isinstance(value, Mapping)
                ),
                key=lambda value: int(value.get("choice_number", 0) or 0),
            )
            if ordered_crops:
                choice_images = [value.get("path") for value in ordered_crops]
    question_image = exact_mapping.get(
        "question_image_path",
        exact_mapping.get(
            "source_figure_crop", raw.get("repaired_question_image_path")
        ),
    )
    return stem, choices, partial, choice_images, question_image


def _portable_source_path(value: object) -> str:
    source = str(value or "").replace("\\", "/")
    marker = "/0. 기출문제 모음/"
    if marker in source:
        return source.split(marker, 1)[1]
    return source


def _materialize_audit_image(
    value: object,
    *,
    question_id: int,
    target_name: str,
) -> str:
    """Copy ignored audit crops into the stable runtime image tree."""
    portable = _portable_source_path(value).strip()
    if not portable:
        return ""
    source = Path(portable)
    if not source.is_absolute():
        source = ROOT / source
    try:
        relative_source = source.resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return portable
    if relative_source.parts[:2] != ("outputs", "symbol_audit") or not source.is_file():
        return portable
    target = ROOT / "data" / "extracted" / "images" / "ocr_repairs" / str(question_id) / target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target.relative_to(ROOT).as_posix()


def _merge_compatible_record(
    current: dict[str, object],
    incoming: dict[str, object],
    question_id: int,
    *,
    prefer_incoming: bool = False,
) -> dict[str, object]:
    def normalized(value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"\s+", " ", value).strip()
        if isinstance(value, list):
            return [normalized(item) for item in value]
        return value

    merged = dict(current)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
        elif merged[key] != value and normalized(merged[key]) != normalized(value):
            if prefer_incoming:
                merged[key] = value
                continue
            raise ValueError(
                "conflicting duplicate audited repair: "
                f"id={question_id}: field={key}: "
                f"first={merged[key]!r}, next={value!r}"
            )
    return merged


def build_bundle(
    database: str | Path,
    audits: list[Path],
    output: str | Path,
    *,
    prefer_later_audit: bool = False,
) -> dict[str, object]:
    database_path = Path(database).resolve()
    output_path = Path(output)
    repairs_by_question_id: dict[int, dict[str, object]] = {}
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        for audit in audits:
            payload = json.loads(Path(audit).read_text(encoding="utf-8"))
            for raw in _iter_confirmed_records(payload):
                question_id = int(
                    raw.get("question_id", raw.get("id", raw.get("legacy_id", 0)))
                    or 0
                )
                if question_id < 1:
                    raise ValueError(f"confirmed repair is missing question id: {audit}: {raw!r}")
                row = _question_row(connection, question_id)
                _validate_natural_key(raw, row)
                source_evidence = raw.get("source_evidence")
                evidence = source_evidence if isinstance(source_evidence, Mapping) else {}
                source_page = int(
                    raw.get("source_page", evidence.get("source_page", 0)) or 0
                )
                source = _portable_source_path(
                    raw.get(
                        "source_filename",
                        raw.get(
                            "source_pdf_relative_path",
                            evidence.get("source_pdf", evidence.get("source_filename", "")),
                        ),
                    )
                    or ""
                )
                if source_page < 1 or not source:
                    raise ValueError(f"invalid source evidence: id={question_id}")

                (
                    stem,
                    audited_choices,
                    partial_choices,
                    audited_choice_images,
                    audited_question_image,
                ) = _exact_values(raw)
                repaired_question_image: str | None = None
                if audited_question_image is not None:
                    repaired_question_image = _materialize_audit_image(
                        audited_question_image,
                        question_id=question_id,
                        target_name="question.png",
                    )
                    if not repaired_question_image:
                        raise ValueError(
                            f"invalid exact question image: id={question_id}"
                        )
                repaired_choice_images: list[str | None] | None = None
                if audited_choice_images is not None:
                    if (
                        not isinstance(audited_choice_images, list)
                        or len(audited_choice_images) not in (4, 5)
                    ):
                        raise ValueError(f"invalid exact choice images: id={question_id}")
                    repaired_choice_images = [
                        _materialize_audit_image(
                            value,
                            question_id=question_id,
                            target_name=f"choice_{index}.png",
                        )
                        if value is not None and str(value).strip()
                        else None
                        for index, value in enumerate(audited_choice_images, start=1)
                    ]
                repaired_choices: list[str] | None = None
                if audited_choices is not None:
                    if (
                        not isinstance(audited_choices, list)
                        or len(audited_choices) not in (4, 5)
                        or (
                            repaired_choice_images is not None
                            and len(repaired_choice_images) != len(audited_choices)
                        )
                    ):
                        raise ValueError(f"invalid exact choices: id={question_id}")
                    repaired_choices = [str(value) for value in audited_choices]
                elif partial_choices:
                    current_rows = connection.execute(
                            """
                            SELECT choice_number, choice_text FROM question_choices
                            WHERE question_id = ? ORDER BY choice_number
                            """,
                            (question_id,),
                        ).fetchall()
                    target_count = (
                        len(repaired_choice_images)
                        if repaired_choice_images is not None
                        else len(current_rows)
                    )
                    if target_count not in (4, 5):
                        raise ValueError(f"invalid database choice structure: id={question_id}")
                    current_choices = ["" for _ in range(target_count)]
                    for choice_number, choice_text in current_rows:
                        if 1 <= int(choice_number) <= target_count:
                            current_choices[int(choice_number) - 1] = str(choice_text)
                    for number, value in partial_choices.items():
                        if number < 1 or number > len(current_choices):
                            raise ValueError(f"invalid exact choice number: id={question_id}: {number}")
                        if not value.strip():
                            raise ValueError(f"empty exact choice value: id={question_id}: {number}")
                        current_choices[number - 1] = value
                    repaired_choices = current_choices
                elif repaired_choice_images is not None:
                    repaired_choices = ["" for _ in repaired_choice_images]
                    for choice_number, choice_text in connection.execute(
                        """
                        SELECT choice_number, choice_text FROM question_choices
                        WHERE question_id = ? ORDER BY choice_number
                        """,
                        (question_id,),
                    ):
                        if 1 <= int(choice_number) <= len(repaired_choices):
                            repaired_choices[int(choice_number) - 1] = str(choice_text)
                if repaired_choices is not None:
                    images_for_validation = repaired_choice_images or [
                        None for _ in repaired_choices
                    ]
                    if any(
                        not text.strip() and not image_path
                        for text, image_path in zip(
                            repaired_choices, images_for_validation
                        )
                    ):
                        raise ValueError(
                            f"exact choice has neither text nor image: id={question_id}"
                        )
                if (
                    stem is None
                    and repaired_choices is None
                    and repaired_question_image is None
                ):
                    raise ValueError(f"empty exact repair: id={question_id}")

                record: dict[str, object] = {
                    "exam_code": str(row["exam_code"]),
                    "subject_code": str(row["subject_code"]),
                    "year": int(row["year"]),
                    "session": int(row["session"]),
                    "question_number": int(row["question_number"]),
                    "source_page": source_page,
                    "source_pdf_relative_path": source,
                }
                if (
                    row["source_page"] is not None
                    and int(row["source_page"]) != source_page
                ):
                    record["expected_current_source_page"] = int(
                        row["source_page"]
                    )
                if stem is not None:
                    record["repaired_stem"] = str(stem)
                if repaired_choices is not None:
                    record["repaired_choices"] = repaired_choices
                if repaired_question_image is not None:
                    record["repaired_question_image_path"] = repaired_question_image
                if repaired_choice_images is not None:
                    record["repaired_choice_image_paths"] = repaired_choice_images
                record["confidence"] = "exact_source"
                current = repairs_by_question_id.get(question_id)
                repairs_by_question_id[question_id] = (
                    record
                    if current is None
                    else _merge_compatible_record(
                        current,
                        record,
                        question_id,
                        prefer_incoming=prefer_later_audit,
                    )
                )

    repairs = list(repairs_by_question_id.values())
    repairs.sort(
        key=lambda item: (
            str(item["exam_code"]),
            str(item["subject_code"]),
            int(item["year"]),
            int(item["session"]),
            int(item["question_number"]),
        )
    )
    result: dict[str, object] = {
        "schema_version": 1,
        "generated_from": [str(Path(path).as_posix()) for path in audits],
        "repairs": repairs,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audits", nargs="+", type=Path)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--prefer-later-audit",
        action="store_true",
        help=(
            "Explicitly let a later direct-source audit supersede conflicting "
            "fields from an earlier audit."
        ),
    )
    args = parser.parse_args()
    payload = build_bundle(
        args.database,
        args.audits,
        args.output,
        prefer_later_audit=args.prefer_later_audit,
    )
    print(json.dumps({"output": str(args.output), "repairs": len(payload["repairs"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
