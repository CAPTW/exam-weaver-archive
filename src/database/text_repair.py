"""Audit and conservatively repair every persisted rich-text surface."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Sequence

from src.parser.formatting import (
    has_suspicious_text_artifact,
    normalize_latex_text,
    repair_extracted_text_artifacts,
    repair_ocr_confusable_artifacts,
)
from src.parser.rich_text_quality import (
    RichTextInspection,
    inspect_rich_text,
)
from src.parser.text_quality import text_quality_issue_codes


FindingSeverity = Literal["blocked_quality", "needs_source_review"]


@dataclass(frozen=True)
class TextChange:
    table: str
    row_id: int
    field: str
    before: str
    after: str
    format_field: str | None = None
    format_before: str | None = None
    format_after: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    rule: str = "conservative_auto"


@dataclass(frozen=True)
class TextFinding:
    category: str
    severity: FindingSeverity
    table: str
    row_id: int
    question_id: int | None
    field_path: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditSummary:
    surface_counts: Mapping[str, int]
    changes: tuple[TextChange, ...]
    findings: tuple[TextFinding, ...]


@dataclass(frozen=True)
class _RichTextRecord:
    owner: Literal["question", "choice", "group"]
    table: str
    row_id: int
    question_id: int | None
    text: str
    format_json: str | None
    text_path: str
    format_path: str
    metadata: Mapping[str, object]

    def inspect(self) -> RichTextInspection:
        return inspect_rich_text(
            self.text,
            self.format_json,
            owner=self.owner,
            text_path=self.text_path,
            format_path=self.format_path,
            row_id=self.row_id,
            question_id=self.question_id,
            metadata=self.metadata,
        )


def repair_text_and_format(
    text: str,
    format_json: str | None,
    *,
    confusables_only: bool = False,
) -> tuple[str, str | None, bool]:
    """Return repaired plain text and format JSON without dropping layout."""

    repair = (
        repair_ocr_confusable_artifacts
        if confusables_only
        else repair_extracted_text_artifacts
    )
    repaired_format = repair_embedded_format_text(format_json, repair)
    normalized = str(text or "").replace("\r\n", "\n").replace(
        "\r", "\n"
    )
    repaired = "\n".join(repair(line) for line in normalized.split("\n"))
    if repaired_format and can_preserve_format_json(
        text, repaired, repaired_format
    ):
        return repaired, repaired_format, False
    if repaired_format:
        formatted = normalize_latex_text(repaired)
        return (
            formatted.text,
            replace_format_spans(repaired_format, formatted.spans),
            False,
        )
    if confusables_only:
        return repaired, None, False
    formatted = normalize_latex_text(repaired)
    next_format = None
    if formatted.spans:
        next_format = json.dumps(
            {"spans": formatted.spans}, ensure_ascii=False
        )
    return formatted.text, next_format, False


def repair_embedded_format_text(
    format_json: str | None,
    repair: Callable[[str], str],
) -> str | None:
    """Repair textual table payloads without discarding table structure."""

    if not format_json:
        return format_json
    try:
        payload = json.loads(format_json)
    except (TypeError, ValueError):
        return format_json
    if not isinstance(payload, dict):
        return format_json

    changed = False

    def repair_preserving_hard_breaks(value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        return "\n".join(repair(line) for line in normalized.split("\n"))

    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        rows = table.get("rows") or []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            for column_index, value in enumerate(row):
                if not isinstance(value, str):
                    continue
                repaired = repair_preserving_hard_breaks(value)
                if repaired != value:
                    rows[row_index][column_index] = repaired
                    changed = True
        for cell in table.get("cells") or []:
            if not isinstance(cell, dict) or not isinstance(
                cell.get("text"), str
            ):
                continue
            repaired = repair_preserving_hard_breaks(cell["text"])
            if repaired != cell["text"]:
                cell["text"] = repaired
                changed = True
    if not changed:
        return format_json
    return json.dumps(payload, ensure_ascii=False)


def replace_format_spans(
    format_json: str | None,
    spans: list[dict],
) -> str | None:
    """Replace top-level spans while retaining tables and layout metadata."""

    try:
        payload = json.loads(format_json) if format_json else {}
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if spans:
        payload["spans"] = spans
    else:
        payload.pop("spans", None)
    return json.dumps(payload, ensure_ascii=False) if payload else None


def can_preserve_format_json(
    before: str,
    after: str,
    format_json: str | None,
) -> bool:
    if not format_json:
        return True
    if len(before or "") != len(after or ""):
        return False
    try:
        payload = json.loads(format_json)
    except (TypeError, ValueError):
        return False
    spans = payload.get("spans") if isinstance(payload, dict) else []
    for span in spans or []:
        try:
            start = int(span.get("start"))
            end = int(span.get("end"))
        except (TypeError, ValueError, AttributeError):
            return False
        if start < 0 or end <= start or end > len(after or ""):
            return False
        if span.get("latex") and (after or "")[start:end] != span.get(
            "latex"
        ):
            return False
    return True


def collect_changes(
    connection: sqlite3.Connection,
    *,
    confusables_only: bool = False,
    protected_question_ids: Sequence[int] = (),
) -> tuple[list[TextChange], list[TextChange]]:
    """Collect high-confidence changes without mutating the database."""

    changes: list[TextChange] = []
    skipped: list[TextChange] = []
    protected = {int(value) for value in protected_question_ids}
    for record in _rich_text_records(connection):
        if (
            record.question_id is not None
            and record.question_id in protected
        ):
            continue
        if record.table == "question_groups":
            repair = (
                repair_ocr_confusable_artifacts
                if confusables_only
                else repair_extracted_text_artifacts
            )
            normalized = record.text.replace("\r\n", "\n").replace(
                "\r", "\n"
            )
            next_text = "\n".join(
                repair(line) for line in normalized.split("\n")
            )
            next_format = None
            was_skipped = False
        else:
            next_text, next_format, was_skipped = repair_text_and_format(
                record.text,
                record.format_json,
                confusables_only=confusables_only,
            )
        change = TextChange(
            table=record.table,
            row_id=record.row_id,
            field=record.text_path,
            before=record.text,
            after=next_text,
            format_field=(
                record.format_path
                if record.table != "question_groups"
                else None
            ),
            format_before=record.format_json,
            format_after=next_format,
            metadata=record.metadata,
        )
        if was_skipped:
            skipped.append(change)
        elif next_text != record.text or next_format != record.format_json:
            changes.append(change)
    return changes, skipped


def collect_surface_counts(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    counts = {
        "question_text": 0,
        "question_format_rows": 0,
        "question_format_cells": 0,
        "choice_text": 0,
        "choice_format_rows": 0,
        "choice_format_cells": 0,
        "shared_text": 0,
    }
    for record in _rich_text_records(connection):
        inspection = record.inspect()
        for surface in inspection.surfaces:
            if surface.path == "question_text":
                counts["question_text"] += 1
            elif surface.path == "choice_text":
                counts["choice_text"] += 1
            elif surface.path == "shared_text":
                counts["shared_text"] += 1
            elif surface.path.startswith("question_format_json"):
                key = (
                    "question_format_rows"
                    if ".rows[" in surface.path
                    else "question_format_cells"
                )
                counts[key] += 1
            elif surface.path.startswith("choice_format_json"):
                key = (
                    "choice_format_rows"
                    if ".rows[" in surface.path
                    else "choice_format_cells"
                )
                counts[key] += 1
    return counts


def collect_findings(
    connection: sqlite3.Connection,
) -> list[TextFinding]:
    """Return blocking and source-review findings for every display surface."""

    findings: list[TextFinding] = []
    for record in _rich_text_records(connection):
        inspection = record.inspect()
        for issue in inspection.issues:
            findings.append(
                _finding(
                    record,
                    issue.code,
                    "blocked_quality",
                    issue.path,
                    issue.text,
                )
            )
        for surface in inspection.surfaces:
            codes = text_quality_issue_codes(surface.text)
            for code in codes:
                category = {
                    "ocr_noise": "ocr_noise_text",
                    "broken_unit": "broken_unit_text",
                    "unbalanced_delimiter": "unbalanced_paren_or_bracket",
                    "damaged_list_marker": "damaged_list_marker",
                }[code]
                findings.append(
                    _finding(
                        record,
                        category,
                        "needs_source_review",
                        surface.path,
                        surface.text,
                    )
                )
            for category, check in _REVIEW_CHECKS:
                if category == "linebreak_remaining" and (
                    "_format_json.tables[" in surface.path
                ):
                    continue
                if check(surface.text):
                    findings.append(
                        _finding(
                            record,
                            category,
                            "needs_source_review",
                            surface.path,
                            surface.text,
                        )
                    )
    return findings


def apply_changes(
    connection: sqlite3.Connection,
    changes: Sequence[TextChange],
) -> None:
    """Apply changes transactionally only when every prior value matches."""

    with connection:
        for change in changes:
            if change.table == "questions":
                cursor = connection.execute(
                    """
                    UPDATE questions
                    SET question_text = ?, question_format_json = ?
                    WHERE id = ?
                      AND question_text = ?
                      AND question_format_json IS ?
                    """,
                    (
                        change.after,
                        change.format_after,
                        change.row_id,
                        change.before,
                        change.format_before,
                    ),
                )
            elif change.table == "question_choices":
                cursor = connection.execute(
                    """
                    UPDATE question_choices
                    SET choice_text = ?, choice_format_json = ?
                    WHERE id = ?
                      AND choice_text = ?
                      AND choice_format_json IS ?
                    """,
                    (
                        change.after,
                        change.format_after,
                        change.row_id,
                        change.before,
                        change.format_before,
                    ),
                )
            elif change.table == "question_groups":
                cursor = connection.execute(
                    """
                    UPDATE question_groups
                    SET shared_text = ?
                    WHERE id = ? AND shared_text = ?
                    """,
                    (change.after, change.row_id, change.before),
                )
            else:
                raise ValueError(
                    f"unsupported repair table: {change.table}"
                )
            if cursor.rowcount != 1:
                raise ValueError(
                    "expected current value mismatch: "
                    f"{change.table}#{change.row_id}"
                )


def _rich_text_records(
    connection: sqlite3.Connection,
) -> list[_RichTextRecord]:
    records: list[_RichTextRecord] = []
    for row in connection.execute(
        """
        SELECT
            q.id, q.question_text, q.question_format_json,
            q.year, q.session, q.question_number, q.source_page,
            e.code AS exam_code, s.name_ko AS subject_name,
            qs.source_url
        FROM questions q
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        LEFT JOIN question_sources qs ON qs.id = q.source_id
        ORDER BY q.id
        """
    ):
        metadata = _metadata(row)
        records.append(_RichTextRecord(
            owner="question",
            table="questions",
            row_id=int(row["id"]),
            question_id=int(row["id"]),
            text=str(row["question_text"] or ""),
            format_json=row["question_format_json"],
            text_path="question_text",
            format_path="question_format_json",
            metadata=metadata,
        ))
    for row in connection.execute(
        """
        SELECT
            c.id, c.question_id, c.choice_number, c.choice_symbol,
            c.choice_text, c.choice_format_json,
            q.year, q.session, q.question_number, q.source_page,
            e.code AS exam_code, s.name_ko AS subject_name,
            qs.source_url
        FROM question_choices c
        JOIN questions q ON q.id = c.question_id
        JOIN exam_subjects es ON es.id = q.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        LEFT JOIN question_sources qs ON qs.id = q.source_id
        ORDER BY c.id
        """
    ):
        metadata = _metadata(row)
        metadata.update({
            "choice_number": row["choice_number"],
            "choice_symbol": row["choice_symbol"],
            "question_id": row["question_id"],
        })
        records.append(_RichTextRecord(
            owner="choice",
            table="question_choices",
            row_id=int(row["id"]),
            question_id=int(row["question_id"]),
            text=str(row["choice_text"] or ""),
            format_json=row["choice_format_json"],
            text_path="choice_text",
            format_path="choice_format_json",
            metadata=metadata,
        ))
    for row in connection.execute(
        """
        SELECT
            g.id, g.shared_text, g.year, g.session,
            g.source_page, e.code AS exam_code,
            s.name_ko AS subject_name, qs.source_url
        FROM question_groups g
        JOIN exam_subjects es ON es.id = g.exam_subject_id
        JOIN exams e ON e.id = es.exam_id
        JOIN subjects s ON s.id = es.subject_id
        LEFT JOIN question_sources qs ON qs.id = g.source_id
        WHERE COALESCE(g.shared_text, '') <> ''
        ORDER BY g.id
        """
    ):
        metadata = {
            "exam_code": row["exam_code"],
            "subject_name": row["subject_name"],
            "year": row["year"],
            "session": row["session"],
            "question_number": None,
            "source_page": row["source_page"],
            "source_url": row["source_url"],
        }
        records.append(_RichTextRecord(
            owner="group",
            table="question_groups",
            row_id=int(row["id"]),
            question_id=None,
            text=str(row["shared_text"] or ""),
            format_json=None,
            text_path="shared_text",
            format_path="shared_format_json",
            metadata=metadata,
        ))
    return records


def _metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "exam_code": row["exam_code"],
        "subject_name": row["subject_name"],
        "year": row["year"],
        "session": row["session"],
        "question_number": row["question_number"],
        "source_page": row["source_page"],
        "source_url": row["source_url"],
    }


def _finding(
    record: _RichTextRecord,
    category: str,
    severity: FindingSeverity,
    path: str,
    text: str,
) -> TextFinding:
    return TextFinding(
        category=category,
        severity=severity,
        table=record.table,
        row_id=record.row_id,
        question_id=record.question_id,
        field_path=path,
        text=text,
        metadata=record.metadata,
    )


_REVIEW_CHECKS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("pua_remaining", lambda text: bool(re.search(r"[\ue000-\uf8ff]", text))),
    ("hwp_overbar_marker_review", lambda text: "¯" in text),
    ("linebreak_remaining", lambda text: bool(re.search(r"[\r\t]", text))),
    (
        "broken_variable_note_remaining",
        lambda text: bool(
            re.search(r"단\s+는\s+[^?()]+이다\?\s*\(\s*,", text)
        ),
    ),
    (
        "dangling_blank_reference",
        lambda text: bool(
            re.search(
                r"에서\s+에\s+(?:각각\s+)?알맞은|에서\s+에\s+각각",
                text,
            )
        ),
    ),
    (
        "quote_blank_order_suspect",
        lambda text: bool(re.search(r'"\s*\(\s+\)\s*\?', text)),
    ),
    (
        "number_unit_order_suspect",
        lambda text: bool(
            re.search(
                r"\b\d+\s+\d+\s*\[[^\]]+\]|\[[^\]]+\]\s+\d+\s+[가-힣]",
                text,
            )
        ),
    ),
    (
        "blank_unit_suspect",
        lambda text: bool(re.search(r"\[\s*\]\s*(?:Ω|Ω|℃|ℓ)?", text)),
    ),
    (
        "paren_question_order_suspect",
        lambda text: bool(re.search(r"\([^)]{1,60}\)\s+\?", text)),
    ),
    ("suspicious_text_artifact", has_suspicious_text_artifact),
)
