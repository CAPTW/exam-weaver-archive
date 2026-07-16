"""Validate and bundle source-PDF OCR repair audit files for the parser."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = ROOT / "outputs" / "ocr_repair_audit"
DEFAULT_OUTPUT = ROOT / "src" / "parser" / "offline_source_repairs.json"
SUBJECT_BY_INPUT = {
    "engineering_repairs.json": "기관학",
    "navigation_repairs.json": "항해학",
}
ALLOWED_CONFIDENCE = {"exact_source", "unrecoverable"}


def _validated_records(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, object]] = []
    default_subject = str(
        payload.get("subject", SUBJECT_BY_INPUT.get(path.name, "")) or ""
    ).strip()
    for raw in payload.get("repairs", []):
        if not isinstance(raw, dict):
            raise ValueError(f"repair record is not an object: {path}")
        confidence = str(raw.get("confidence", ""))
        if confidence not in ALLOWED_CONFIDENCE:
            continue
        record = dict(raw)
        subject = str(record.get("subject", default_subject) or "").strip()
        if not subject:
            raise ValueError(f"missing subject: {path}: {record!r}")
        record["subject"] = subject
        source = str(record.get("source_pdf_relative_path", "") or "")
        page = int(record.get("source_page", 0) or 0)
        number = int(record.get("question_number", 0) or 0)
        if not source or page < 1 or number < 1:
            raise ValueError(f"invalid repair key: {path}: {record!r}")
        if confidence == "exact_source":
            stem = record.get("repaired_stem")
            choices = record.get("repaired_choices")
            choice_overrides = record.get("repaired_choice_overrides")
            question_image = record.get("repaired_question_image_path")
            if (
                stem is None
                and choices is None
                and choice_overrides is None
                and question_image is None
            ):
                raise ValueError(f"empty exact repair: {path}: {record!r}")
            if question_image is not None and not str(question_image).strip():
                raise ValueError(f"invalid exact question image: {path}: {record!r}")
            if choices is not None and choice_overrides is not None:
                raise ValueError(f"ambiguous audited choices: {path}: {record!r}")
            if choices is not None and (
                not isinstance(choices, list)
                or len(choices) not in (4, 5)
                or any(not str(value).strip() for value in choices)
            ):
                raise ValueError(f"invalid exact choices: {path}: {record!r}")
            if choice_overrides is not None and (
                not isinstance(choice_overrides, dict)
                or not choice_overrides
                or any(
                    not str(number).isdigit()
                    or int(number) not in range(1, 6)
                    or not str(value).strip()
                    for number, value in choice_overrides.items()
                )
            ):
                raise ValueError(f"invalid exact choice overrides: {path}: {record!r}")
        records.append(record)
    return records


def build_bundle(paths: list[Path], output: Path) -> dict[str, object]:
    repairs: list[dict[str, object]] = []
    seen: dict[tuple[str, int, int], int] = {}
    for path in paths:
        for record in _validated_records(path):
            source = Path(
                str(record["source_pdf_relative_path"]).replace("\\", "/")
            ).name.casefold()
            key = (
                source,
                int(record["source_page"]),
                int(record["question_number"]),
            )
            if key in seen:
                existing = repairs[seen[key]]
                for field, value in record.items():
                    if value is None:
                        continue
                    current = existing.get(field)
                    if current in (None, ""):
                        existing[field] = value
                        continue
                    if field == "source_pdf_relative_path":
                        if Path(str(current).replace("\\", "/")).name.casefold() == source:
                            continue
                    if field == "evidence_note" and str(value) != str(current):
                        existing[field] = f"{current} / {value}"
                        continue
                    if value != current:
                        raise ValueError(
                            f"conflicting duplicate repair field {field!r} "
                            f"for {key!r}: {current!r} != {value!r}"
                        )
                continue
            seen[key] = len(repairs)
            repairs.append(record)
    repairs.sort(
        key=lambda item: (
            str(item["subject"]),
            int(item.get("year", 0) or 0),
            int(item.get("session", 0) or 0),
            int(item["question_number"]),
        )
    )
    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_from": [
            str(path.resolve().relative_to(ROOT)) for path in paths
        ],
        "repairs": repairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        default=[
            DEFAULT_AUDIT_DIR / "engineering_repairs.json",
            DEFAULT_AUDIT_DIR / "navigation_repairs.json",
            DEFAULT_AUDIT_DIR / "navigation_2013_2019_assist.json",
            DEFAULT_AUDIT_DIR / "law_english_repairs.json",
            ROOT / "src" / "parser" / "audits" / "residual_maritime_repairs.json",
            ROOT / "src" / "parser" / "audits" / "recent_maritime_repairs.json",
            ROOT / "src" / "parser" / "audits" / "recent_maritime_repairs_2.json",
            ROOT / "src" / "parser" / "audits" / "recent_maritime_repairs_3.json",
            ROOT / "src" / "parser" / "audits" / "final_core_maritime_repairs.json",
            ROOT / "src" / "parser" / "audits" / "final_english_repairs.json",
            ROOT / "src" / "parser" / "audits" / "final_missing_image_repairs.json",
        ],
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    missing = [path for path in args.inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing audit inputs: {missing}")
    payload = build_bundle(args.inputs, args.output)
    print(f"output={args.output.resolve()}")
    print(f"repairs={len(payload['repairs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
