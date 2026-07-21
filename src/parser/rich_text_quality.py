"""Enumerate and structurally validate every displayed rich-text surface."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Mapping


Owner = Literal["question", "choice", "group"]


@dataclass(frozen=True)
class RichTextSurface:
    owner: Owner
    row_id: int | None
    question_id: int | None
    path: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RichTextIssue:
    code: str
    path: str
    text: str
    related_path: str | None = None


@dataclass(frozen=True)
class RichTextInspection:
    surfaces: tuple[RichTextSurface, ...]
    issues: tuple[RichTextIssue, ...]


def inspect_rich_text(
    text: str,
    format_json: str | None,
    *,
    owner: Owner,
    text_path: str,
    format_path: str,
    row_id: int | None = None,
    question_id: int | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RichTextInspection:
    """Return plain/table text surfaces and fail-closed structure findings."""

    context = dict(metadata or {})
    surfaces = [
        RichTextSurface(
            owner,
            row_id,
            question_id,
            text_path,
            str(text or ""),
            context,
        )
    ]
    issues: list[RichTextIssue] = []
    if format_json in (None, ""):
        return RichTextInspection(tuple(surfaces), ())

    try:
        payload = json.loads(str(format_json))
    except (TypeError, ValueError):
        return RichTextInspection(
            tuple(surfaces),
            (
                RichTextIssue(
                    "invalid_format_json",
                    format_path,
                    str(format_json),
                ),
            ),
        )
    if not isinstance(payload, dict):
        return RichTextInspection(
            tuple(surfaces),
            (
                RichTextIssue(
                    "invalid_format_json",
                    format_path,
                    str(format_json),
                ),
            ),
        )

    tables = payload.get("tables") or []
    if not isinstance(tables, list):
        return RichTextInspection(
            tuple(surfaces),
            (
                RichTextIssue(
                    "invalid_format_json",
                    f"{format_path}.tables",
                    str(tables),
                ),
            ),
        )

    for table_index, table in enumerate(tables):
        table_path = f"{format_path}.tables[{table_index}]"
        if not isinstance(table, dict):
            issues.append(
                RichTextIssue("invalid_format_json", table_path, str(table))
            )
            continue

        rows = table.get("rows") or []
        coordinates: dict[tuple[int, int], tuple[str, str]] = {}
        if not isinstance(rows, list):
            issues.append(
                RichTextIssue(
                    "invalid_format_json",
                    f"{table_path}.rows",
                    str(rows),
                )
            )
            rows = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list):
                issues.append(
                    RichTextIssue(
                        "invalid_format_json",
                        f"{table_path}.rows[{row_index}]",
                        str(row),
                    )
                )
                continue
            for column_index, value in enumerate(row):
                path = f"{table_path}.rows[{row_index}][{column_index}]"
                if not isinstance(value, str):
                    issues.append(
                        RichTextIssue("invalid_format_json", path, str(value))
                    )
                    continue
                surfaces.append(
                    RichTextSurface(
                        owner,
                        row_id,
                        question_id,
                        path,
                        value,
                        context,
                    )
                )
                coordinates[(row_index, column_index)] = (value, path)
                if not value.strip():
                    issues.append(RichTextIssue("empty_table_cell", path, value))

        cells = table.get("cells") or []
        if not isinstance(cells, list):
            issues.append(
                RichTextIssue(
                    "invalid_format_json",
                    f"{table_path}.cells",
                    str(cells),
                )
            )
            continue
        for cell_index, cell in enumerate(cells):
            path = f"{table_path}.cells[{cell_index}].text"
            if not isinstance(cell, dict) or not isinstance(
                cell.get("text"), str
            ):
                issues.append(
                    RichTextIssue("invalid_format_json", path, str(cell))
                )
                continue
            value = cell["text"]
            surfaces.append(
                RichTextSurface(
                    owner,
                    row_id,
                    question_id,
                    path,
                    value,
                    context,
                )
            )
            if not value.strip():
                issues.append(RichTextIssue("empty_table_cell", path, value))

            row_value = cell.get("row")
            column_value = cell.get("col")
            if not isinstance(row_value, int) or not isinstance(
                column_value, int
            ):
                issues.append(
                    RichTextIssue(
                        "invalid_table_cell_coordinate",
                        path,
                        value,
                    )
                )
                continue
            row_entry = coordinates.get((row_value, column_value))
            if row_entry is not None and row_entry[0] != value:
                issues.append(
                    RichTextIssue(
                        "rows_cells_divergence",
                        path,
                        value,
                        row_entry[1],
                    )
                )

    return RichTextInspection(tuple(surfaces), tuple(issues))
