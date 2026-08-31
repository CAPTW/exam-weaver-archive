"""Semantic `ExamDocument` to clean OWPML rendering."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..choice_markers import DEFAULT_CHOICE_MARKER_STYLE, choice_marker
from ..parser.aligned_choice_table import is_aligned_choice_format
from ..parser.question import ALL_CHOICES_CORRECT
from ..parser.table_format import (
    effective_table_render_mode,
    parse_format_payload,
    resolve_table_anchor,
    validate_table_spec,
)
from ..parser.table_structure import normalize_rectangular_table
from .exam_document import AnswerKeyEntry, ExamDocument, QuestionBlock, SharedPassageBlock
from .hwpx_package import (
    DeterministicIds,
    HwpxBuildError,
    MediaPart,
    StyleRegistry,
    StyleSpec,
    append_image_paragraph,
    append_paragraph,
    append_table_paragraph,
    clean_xml_text,
    deterministic_parts,
    new_section_root,
)
from .hwpx_profile import DEFAULT_HWPX_PROFILE, HwpxTemplateProfile
from .table_layout import fallback_table_layout, resolve_table_layout


WARNING_UNSUPPORTED_FORMATTING = "HWPX_UNSUPPORTED_FORMATTING_AS_TEXT"
WARNING_EQUATION_TEXT = "HWPX_EQUATION_TEXT_FALLBACK"
WARNING_TABLE_IMAGE = "HWPX_TABLE_IMAGE_FALLBACK"
WARNING_TABLE_TEXT = "HWPX_TABLE_TEXT_FALLBACK"
WARNING_IMAGE_CONVERTED = "HWPX_IMAGE_CONVERTED_TO_PNG"
WARNING_ANSWER_CONTINUATION = "HWPX_ANSWER_KEY_CONTINUATION"
WARNING_OPTIONAL_METADATA = "HWPX_OPTIONAL_METADATA_UNAVAILABLE"

SUPPORTED_SPAN_KEYS = {
    "start",
    "end",
    "underline",
    "bold",
    "italic",
    "superscript",
    "subscript",
    "font_size",
    "text_color",
    "latex",
}


@dataclass(frozen=True, slots=True)
class ExpectedTable:
    section_index: int
    row_count: int
    column_count: int
    cells_by_row: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class RenderManifest:
    semantic_digest: str
    paragraphs_by_section: tuple[tuple[str, ...], ...]
    tables: tuple[ExpectedTable, ...]
    image_references_by_section: tuple[int, ...]
    layout_columns: tuple[int, ...]
    layout_gaps: tuple[int, ...]
    semantic_section_count: int
    question_count: int
    answer_entry_count: int


@dataclass(frozen=True, slots=True)
class RenderedHwpx:
    parts: Mapping[str, bytes]
    warnings: tuple[str, ...]
    manifest: RenderManifest
    table_count: int
    image_count: int
    fallback_count: int


class SemanticRenderer:
    def __init__(
        self,
        *,
        profile: HwpxTemplateProfile = DEFAULT_HWPX_PROFILE,
        choice_marker_style: str = DEFAULT_CHOICE_MARKER_STYLE,
        strict: bool = True,
    ) -> None:
        self.profile = profile
        self.choice_marker_style = choice_marker_style
        self.strict = bool(strict)

    def render(self, document: ExamDocument) -> RenderedHwpx:
        self._ids = DeterministicIds()
        self._styles = StyleRegistry()
        self._warnings: list[str] = []
        self._media_by_digest: dict[str, MediaPart] = {}
        self._media: list[MediaPart] = []
        self._paragraphs: list[list[str]] = [[], []]
        self._expected_tables: list[ExpectedTable] = []
        self._image_refs: list[int] = [0, 0]
        self._table_count = 0
        self._fallback_count = 0
        self._semantic_media: list[str] = []

        cover = new_section_root(
            self.profile,
            self._ids,
            columns=self.profile.cover_columns,
            gap=0,
        )
        body = new_section_root(
            self.profile,
            self._ids,
            columns=self.profile.body_columns,
            gap=self.profile.body_column_gap,
        )
        sections = [cover, body]

        for title_line in document.title_lines:
            self._append_plain(cover, 0, str(title_line), style=self._styles.title, alignment="center", style_id=1)

        for exam_section in document.sections:
            if exam_section.title:
                self._append_plain(
                    body,
                    1,
                    str(exam_section.title),
                    style=self._styles.heading,
                    alignment="center",
                    style_id=2,
                )
            for block in exam_section.blocks:
                if isinstance(block, SharedPassageBlock):
                    self._render_shared_passage(body, block)
                elif isinstance(block, QuestionBlock):
                    self._render_question(body, block)
                else:
                    raise HwpxBuildError("HWPX_CONTENT_LOSS_UNRESOLVED", "unknown ExamDocument block")

        if document.include_answer_key and document.answer_key:
            answer = new_section_root(
                self.profile,
                self._ids,
                columns=self.profile.answer_key_layout_columns,
                gap=0,
                new_page=True,
            )
            sections.append(answer)
            self._paragraphs.append([])
            self._image_refs.append(0)
            self._render_answer_key(answer, document.answer_key)

        parts = deterministic_parts(
            styles=self._styles,
            profile=self.profile,
            sections=sections,
            media=self._media,
        )
        semantic_payload = self._semantic_payload(document)
        semantic_digest = hashlib.sha256(
            json.dumps(semantic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest = RenderManifest(
            semantic_digest=semantic_digest,
            paragraphs_by_section=tuple(tuple(values) for values in self._paragraphs),
            tables=tuple(self._expected_tables),
            image_references_by_section=tuple(self._image_refs),
            layout_columns=tuple(
                [self.profile.cover_columns, self.profile.body_columns]
                + ([self.profile.answer_key_layout_columns] if len(sections) == 3 else [])
            ),
            layout_gaps=tuple([0, self.profile.body_column_gap] + ([0] if len(sections) == 3 else [])),
            semantic_section_count=len(document.sections),
            question_count=sum(
                isinstance(block, QuestionBlock)
                for section in document.sections
                for block in section.blocks
            ),
            answer_entry_count=len(document.answer_key) if document.include_answer_key else 0,
        )
        return RenderedHwpx(
            parts=parts,
            warnings=tuple(self._warnings),
            manifest=manifest,
            table_count=self._table_count,
            image_count=len(self._media),
            fallback_count=self._fallback_count,
        )

    def _warn(self, code: str) -> None:
        if code not in self._warnings:
            self._warnings.append(code)

    def _append_runs(
        self,
        root,
        section_index: int,
        runs: Sequence[tuple[str, int]],
        *,
        alignment: str = "left",
        style_id: int = 0,
    ) -> None:
        visible = "".join(clean_xml_text(text) for text, _style in runs)
        append_paragraph(root, self._ids, runs, alignment=alignment, style_id=style_id)
        self._paragraphs[section_index].append(visible)

    def _append_plain(
        self,
        root,
        section_index: int,
        text: str,
        *,
        style: int | None = None,
        alignment: str = "left",
        style_id: int = 0,
    ) -> None:
        self._append_runs(
            root,
            section_index,
            ((clean_xml_text(text), self._styles.body if style is None else style),),
            alignment=alignment,
            style_id=style_id,
        )

    def _render_shared_passage(self, root, block: SharedPassageBlock) -> None:
        # Keep the visible label and value in one run.  The canonical readback
        # backend normalizes whitespace at individual run boundaries.
        self._append_plain(root, 1, f"[공통지문] {clean_xml_text(block.text)}")
        if block.image_path:
            self._append_image(root, 1, block.image_path)

    def _render_question(self, root, block: QuestionBlock) -> None:
        self._render_formatted_content(
            root,
            1,
            block.text,
            block.format_json,
            prefix=f"{block.display_number}. ",
            base_style=self._styles.body,
        )
        if block.image_path:
            self._append_image(root, 1, block.image_path)
        if block.question_type == "descriptive":
            if str(block.model_answer or "").strip():
                self._append_plain(root, 1, f"모범답안: {clean_xml_text(block.model_answer)}")
            return
        for choice in block.choices:
            marker = choice_marker(choice.number, self.choice_marker_style, fallback=choice.symbol)
            choice_text = "" if is_aligned_choice_format(choice.format_json) else str(choice.text or "")
            self._render_formatted_content(
                root,
                1,
                choice_text,
                choice.format_json,
                prefix=f"{marker} " if marker else "",
                base_style=self._styles.body,
            )
            if choice.image_path:
                self._append_image(root, 1, choice.image_path)

    def _render_formatted_content(
        self,
        root,
        section_index: int,
        text: object,
        format_json: object,
        *,
        prefix: str,
        base_style: int,
    ) -> None:
        visible_text = str(text or "")
        payload = parse_format_payload(format_json)
        anchored: list[tuple[int, int, dict]] = []
        for index, table in enumerate(payload.get("tables") or []):
            offset, _recovered = resolve_table_anchor(visible_text, table.get("anchor"))
            anchored.append((offset, index, table))
        anchored.sort(key=lambda item: (item[0], item[1]))
        cursor = 0
        prefix_value = prefix
        for offset, _index, table in anchored:
            offset = min(len(visible_text), max(cursor, offset))
            if offset > cursor or prefix_value:
                self._append_text_range(
                    root,
                    section_index,
                    visible_text,
                    payload,
                    cursor,
                    offset,
                    prefix=prefix_value,
                    base_style=base_style,
                )
                prefix_value = ""
            self._render_table(root, section_index, table)
            cursor = offset
        if cursor < len(visible_text) or (not anchored and (visible_text or prefix_value)):
            self._append_text_range(
                root,
                section_index,
                visible_text,
                payload,
                cursor,
                len(visible_text),
                prefix=prefix_value,
                base_style=base_style,
            )
        elif not anchored and not visible_text and prefix_value:
            self._append_plain(root, section_index, prefix_value.rstrip(), style=base_style)

    def _append_text_range(
        self,
        root,
        section_index: int,
        text: str,
        payload: Mapping[str, object],
        start: int,
        end: int,
        *,
        prefix: str,
        base_style: int,
    ) -> None:
        fragment = text[start:end]
        lines = fragment.split("\n")
        absolute_cursor = start
        prefix_value = prefix
        for line_index, line in enumerate(lines):
            line_start = absolute_cursor
            line_end = line_start + len(line)
            runs = self._styled_runs(text, payload.get("spans") or [], line_start, line_end, base_style)
            if prefix_value:
                if runs and runs[0][1] == base_style:
                    first_text, first_style = runs[0]
                    runs[0] = (prefix_value + first_text, first_style)
                else:
                    runs.insert(0, (prefix_value, base_style))
                prefix_value = ""
            self._append_runs(root, section_index, tuple(runs))
            absolute_cursor = line_end + (1 if line_index < len(lines) - 1 else 0)

    def _styled_runs(
        self,
        text: str,
        spans: Iterable[object],
        start: int,
        end: int,
        base_style: int,
    ) -> list[tuple[str, int]]:
        valid: list[tuple[int, int, Mapping[str, object]]] = []
        last_end = start
        for raw in spans:
            if not isinstance(raw, Mapping):
                continue
            try:
                span_start = max(start, int(raw.get("start")))
                span_end = min(end, int(raw.get("end")))
            except (TypeError, ValueError):
                continue
            if span_start >= span_end or span_start < last_end:
                continue
            valid.append((span_start, span_end, raw))
            last_end = span_end
        output: list[tuple[str, int]] = []
        cursor = start
        for span_start, span_end, options in valid:
            if span_start > cursor:
                output.append((clean_xml_text(text[cursor:span_start]), base_style))
            unknown = {key for key, value in options.items() if key not in SUPPORTED_SPAN_KEYS and value not in (None, False, "")}
            if unknown:
                self._warn(WARNING_UNSUPPORTED_FORMATTING)
            if options.get("latex"):
                self._warn(WARNING_EQUATION_TEXT)
            style = self._style_from_span(options)
            output.append((clean_xml_text(text[span_start:span_end]), self._styles.id_for(style)))
            cursor = span_end
        if cursor < end:
            output.append((clean_xml_text(text[cursor:end]), base_style))
        if not output:
            output.append((clean_xml_text(text[start:end]), base_style))
        return output

    def _style_from_span(self, options: Mapping[str, object]) -> StyleSpec:
        height = 1000
        if options.get("font_size") is not None:
            try:
                candidate = int(float(options["font_size"]))
                height = candidate * 100 if 1 <= candidate <= 100 else candidate
                if not 100 <= height <= 10000:
                    raise ValueError
            except (TypeError, ValueError):
                height = 1000
                self._warn(WARNING_UNSUPPORTED_FORMATTING)
        color = str(options.get("text_color") or "#000000").upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", color):
            color = "#000000"
            self._warn(WARNING_UNSUPPORTED_FORMATTING)
        return StyleSpec(
            height=height,
            text_color=color,
            bold=bool(options.get("bold")),
            italic=bool(options.get("italic")),
            underline=bool(options.get("underline")),
            superscript=bool(options.get("superscript")),
            subscript=bool(options.get("subscript")),
        )

    def _render_table(self, root, section_index: int, table: Mapping[str, object]) -> None:
        self._table_count += 1
        complexity = table.get("complexity") if isinstance(table.get("complexity"), Mapping) else {}
        complex_table = any(bool(value) for value in complexity.values())
        mode = "image" if complex_table else effective_table_render_mode(dict(table), "auto")
        source = table.get("source") if isinstance(table.get("source"), Mapping) else {}
        source_path = Path(str(source.get("image_path"))) if source.get("image_path") else None
        if mode == "image" and source_path is not None and source_path.is_file():
            media = self._register_image(source_path)
            append_image_paragraph(root, self._ids, media, max_width=22000)
            self._image_refs[section_index] += 1
            self._warn(WARNING_TABLE_IMAGE)
            self._fallback_count += 1
            return
        if mode == "image":
            normalized = self._normalized_table(table)
            rows = normalized.get("rows") or []
            if not rows:
                raise HwpxBuildError("HWPX_CONTENT_LOSS_UNRESOLVED", "complex table has no visible fallback")
            for row in rows:
                self._append_plain(root, section_index, " | ".join(str(cell or "") for cell in row), style=self._styles.table)
            self._warn(WARNING_TABLE_TEXT)
            self._fallback_count += 1
            return
        normalized = self._normalized_table(table)
        rows = normalized["rows"]
        row_count = len(rows)
        column_count = len(rows[0])
        try:
            layout = resolve_table_layout(normalized)
        except Exception:
            layout = fallback_table_layout(normalized)
        widths = [max(1, round(width * 7200 / 25.4)) for width in layout.column_widths_mm]
        append_table_paragraph(
            root,
            self._ids,
            self._styles,
            normalized["cells"],
            row_count=row_count,
            column_count=column_count,
            column_widths=widths,
        )
        cells_by_row = tuple(
            tuple(
                clean_xml_text(cell.get("text", ""))
                for cell in normalized["cells"]
                if int(cell["row"]) == row
            )
            for row in range(row_count)
        )
        self._expected_tables.append(ExpectedTable(section_index, row_count, column_count, cells_by_row))

    def _normalized_table(self, table: Mapping[str, object]) -> dict:
        errors = validate_table_spec(dict(table))
        if "cell_out_of_bounds" in errors:
            raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "table cell outside normalized bounds")
        raw_cells = [cell for cell in table.get("cells") or [] if isinstance(cell, Mapping)]
        occupied: set[tuple[int, int]] = set()
        for cell in raw_cells:
            try:
                row = int(cell.get("row", 0))
                column = int(cell.get("col", 0))
                row_span = max(1, int(cell.get("row_span", 1)))
                column_span = max(1, int(cell.get("col_span", 1)))
            except (TypeError, ValueError) as exc:
                raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "invalid table coordinate") from exc
            covered = {
                (covered_row, covered_column)
                for covered_row in range(row, row + row_span)
                for covered_column in range(column, column + column_span)
            }
            if covered & occupied:
                raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "overlapping table cells")
            occupied.update(covered)
        try:
            normalized = normalize_rectangular_table(dict(table))
        except Exception as exc:
            raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "unable to normalize table") from exc
        rows = normalized.get("rows") or []
        if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
            raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "table must be rectangular")
        return normalized

    def _append_image(self, root, section_index: int, image_path: object) -> None:
        media = self._register_image(Path(str(image_path)))
        append_image_paragraph(root, self._ids, media)
        self._image_refs[section_index] += 1

    def _register_image(self, path: Path) -> MediaPart:
        if not path.is_file():
            raise HwpxBuildError("HWPX_REQUIRED_IMAGE_MISSING", "required image does not exist")
        try:
            source_bytes = path.read_bytes()
            from PIL import Image

            with Image.open(io.BytesIO(source_bytes)) as image:
                image.load()
                width, height = image.size
                image_format = str(image.format or "").upper()
                if image_format in {"PNG", "JPEG", "BMP"}:
                    data = source_bytes
                    extension = {"PNG": "png", "JPEG": "jpg", "BMP": "bmp"}[image_format]
                    media_type = {"PNG": "image/png", "JPEG": "image/jpeg", "BMP": "image/bmp"}[image_format]
                else:
                    converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    stream = io.BytesIO()
                    converted.save(stream, format="PNG", optimize=False, compress_level=9)
                    data = stream.getvalue()
                    extension = "png"
                    media_type = "image/png"
                    self._warn(WARNING_IMAGE_CONVERTED)
        except HwpxBuildError:
            raise
        except Exception as exc:
            raise HwpxBuildError("HWPX_REQUIRED_IMAGE_MISSING", "required image is unreadable") from exc
        digest = hashlib.sha256(data).hexdigest()
        existing = self._media_by_digest.get(digest)
        if existing is not None:
            self._semantic_media.append(digest)
            return existing
        # The canonical adapter resolves picture references by the embedded
        # member stem, so the relationship id and deterministic media stem are
        # deliberately identical.
        identifier = digest[:24]
        item = MediaPart(
            identifier=identifier,
            member_name=f"BinData/{digest[:24]}.{extension}",
            media_type=media_type,
            data=data,
            pixel_width=width,
            pixel_height=height,
        )
        self._media_by_digest[digest] = item
        self._media.append(item)
        self._semantic_media.append(digest)
        return item

    def _render_answer_key(self, root, entries: Sequence[AnswerKeyEntry]) -> None:
        self._append_plain(root, 2, "Answer Key", style=self._styles.heading)
        chunk_size = self.profile.answer_key_entries_per_table
        if len(entries) > chunk_size:
            self._warn(WARNING_ANSWER_CONTINUATION)
        for chunk_start in range(0, len(entries), chunk_size):
            chunk = entries[chunk_start : chunk_start + chunk_size]
            cells: list[dict[str, object]] = []
            rows: list[list[str]] = [["번호", "정답"] * 4]
            for column in range(8):
                cells.append(
                    {
                        "row": 0,
                        "col": column,
                        "text": "번호" if column % 2 == 0 else "정답",
                        "row_span": 1,
                        "col_span": 1,
                        "horizontal_alignment": "center",
                        "vertical_alignment": "center",
                    }
                )
            for row in range(1, 12):
                visible_row: list[str] = []
                for pair in range(4):
                    index = (row - 1) * 4 + pair
                    if index < len(chunk):
                        entry = chunk[index]
                        number = str(entry.display_number)
                        answer = self._present_answer(entry)
                    else:
                        number = answer = ""
                    visible_row.extend((number, answer))
                    for offset, value in enumerate((number, answer)):
                        cells.append(
                            {
                                "row": row,
                                "col": pair * 2 + offset,
                                "text": value,
                                "row_span": 1,
                                "col_span": 1,
                                "horizontal_alignment": "center",
                                "vertical_alignment": "center",
                            }
                        )
                rows.append(visible_row)
            append_table_paragraph(
                root,
                self._ids,
                self._styles,
                cells,
                row_count=12,
                column_count=8,
                column_widths=[2400, 3600] * 4,
            )
            self._expected_tables.append(ExpectedTable(2, 12, 8, tuple(tuple(row) for row in rows)))
            self._table_count += 1

    def _present_answer(self, entry: AnswerKeyEntry) -> str:
        if entry.question_type == "descriptive":
            return "서술형"
        if entry.answer_available is False or entry.correct_answer is None:
            return "-"
        if entry.correct_answer == ALL_CHOICES_CORRECT:
            return "전원 정답"
        return choice_marker(entry.correct_answer, self.choice_marker_style, fallback=str(entry.correct_answer))

    def _semantic_payload(self, document: ExamDocument) -> dict[str, object]:
        semantic_sections = []
        for section in document.sections:
            blocks = []
            for block in section.blocks:
                if isinstance(block, SharedPassageBlock):
                    blocks.append(
                        {
                            "kind": "shared_passage",
                            "text": clean_xml_text(block.text),
                            "has_image": bool(block.image_path),
                        }
                    )
                elif isinstance(block, QuestionBlock):
                    blocks.append(
                        {
                            "kind": "question",
                            "display_number": block.display_number,
                            "question_type": block.question_type,
                            "text": clean_xml_text(block.text),
                            "has_image": bool(block.image_path),
                            "choices": [
                                {
                                    "number": choice.number,
                                    "symbol": clean_xml_text(choice.symbol),
                                    "text": clean_xml_text(choice.text),
                                    "has_image": bool(choice.image_path),
                                }
                                for choice in block.choices
                            ],
                            "model_answer": clean_xml_text(block.model_answer) if block.model_answer else None,
                        }
                    )
            semantic_sections.append({"title": clean_xml_text(section.title) if section.title else None, "blocks": blocks})
        return {
            "profile": self.profile.name,
            "title_lines": [clean_xml_text(value) for value in document.title_lines],
            "sections": semantic_sections,
            "answer_key": [
                {
                    "display_number": entry.display_number,
                    "question_type": entry.question_type,
                    "value": self._present_answer(entry),
                }
                for entry in document.answer_key
            ]
            if document.include_answer_key
            else [],
            "media_content_sha256_in_semantic_order": list(self._semantic_media),
        }
