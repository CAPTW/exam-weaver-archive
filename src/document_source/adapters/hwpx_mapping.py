from __future__ import annotations

from src.document_source.adapters.hwpx_package import PackageSupplement
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentField,
    DocumentImage,
    DocumentMasterPage,
    DocumentParagraph,
    DocumentRun,
    DocumentSection,
    DocumentSource,
    DocumentSourceAdapterInfo,
    DocumentSourceFormat,
    DocumentTable,
    DocumentTableCell,
    DocumentTableRow,
    SourceAttachment,
    SourceCoordinate,
    SourceDiagnostic,
    SourceProperty,
)

_SHAPE_CACHE_NOTE = "char-shape-id"


def _props(*pairs: tuple[str, object]) -> tuple[SourceProperty, ...]:
    out: list[SourceProperty] = []
    for name, value in pairs:
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out.append(SourceProperty(name, value))
    return tuple(out)


def _coord(*, part: str | None = None, block_id: str | None = None, extra: tuple[SourceProperty, ...] = ()) -> SourceCoordinate:
    return SourceCoordinate(part=part, block_id=block_id, properties=extra)


def _diag(code: str, message: str, severity: DiagnosticSeverity = DiagnosticSeverity.WARNING) -> SourceDiagnostic:
    return SourceDiagnostic(code=code, severity=severity, message=message, backend="hwpxkit")


def _shape_props(char_shapes: list, shape_id: object) -> tuple[SourceProperty, ...]:
    try:
        idx = int(shape_id)
    except (TypeError, ValueError):
        return ()
    if idx < 0 or idx >= len(char_shapes):
        return ()
    attrs = (char_shapes[idx] or {}).get("attributes") or {}
    return _props(
        ("char_shape_id", idx),
        ("bold", bool(attrs.get("bold"))),
        ("italic", bool(attrs.get("italic"))),
        ("underline", int(attrs.get("underline_type") or 0)),
        ("strike", bool(attrs.get("strikethrough"))),
    )


def _paragraph_from_text_record(record: dict, char_shapes: list, part: str, para_id: str) -> tuple[DocumentParagraph, list[SourceDiagnostic]]:
    diags: list[SourceDiagnostic] = []
    runs_payload = record.get("runs")
    runs: list[DocumentRun] = []
    if isinstance(runs_payload, list) and runs_payload:
        offset = 0
        for i, item in enumerate(runs_payload):
            text = str((item or {}).get("text") or "")
            shape_id = (item or {}).get("char_shape_id")
            runs.append(
                DocumentRun(
                    text=text,
                    coordinate=_coord(
                        part=part,
                        block_id=f"{para_id}/run-{i}",
                        extra=_props(("char_start", offset), ("char_end", offset + len(text))),
                    ),
                    properties=_shape_props(char_shapes, shape_id),
                )
            )
            offset += len(text)
    else:
        text = str(record.get("text") or "")
        runs.append(DocumentRun(text=text, coordinate=_coord(part=part, block_id=f"{para_id}/run-0")))
        diags.append(_diag("HWPX_RUN_FIDELITY_UNAVAILABLE", "run structure absent; paragraph text retained"))
    return (
        DocumentParagraph(
            runs=tuple(runs),
            coordinate=_coord(part=part, block_id=para_id),
            properties=_props(("para_id", para_id)),
        ),
        diags,
    )


def _table_from_record(record: dict, char_shapes: list, part: str, table_id: str) -> tuple[DocumentTable | None, list[SourceDiagnostic]]:
    table = record.get("table") or {}
    attrs = table.get("attributes") or {}
    row_count = int(attrs.get("row_count") or 0)
    column_count = int(attrs.get("col_count") or 0)
    cells_payload = table.get("cells") or []
    if row_count < 1 or column_count < 1:
        return None, [_diag("HWPX_TABLE_TOPOLOGY_INVALID", "invalid table size", DiagnosticSeverity.ERROR)]
    rows_map: dict[int, list[DocumentTableCell]] = {i: [] for i in range(row_count)}
    diags: list[SourceDiagnostic] = []
    for raw in cells_payload:
        cell_attrs = (raw or {}).get("cell_attributes") or {}
        row = int(cell_attrs.get("row_address") or 0)
        col = int(cell_attrs.get("col_address") or 0)
        row_span = int(cell_attrs.get("row_span") or 1)
        col_span = int(cell_attrs.get("col_span") or 1)
        nested: list[DocumentParagraph] = []
        for pi, para in enumerate((raw or {}).get("paragraphs") or []):
            for rec in (para or {}).get("records") or []:
                if rec.get("type") == "para_text":
                    paragraph, extra = _paragraph_from_text_record(rec, char_shapes, part, f"{table_id}/r{row}c{col}/p{pi}")
                    nested.append(paragraph)
                    diags.extend(extra)
        if row not in rows_map:
            diags.append(_diag("HWPX_TABLE_TOPOLOGY_INVALID", f"row {row} out of range", DiagnosticSeverity.ERROR))
            continue
        rows_map[row].append(
            DocumentTableCell(
                row=row,
                column=col,
                row_span=row_span,
                column_span=col_span,
                paragraphs=tuple(nested),
                coordinate=_coord(part=part, block_id=f"{table_id}/r{row}c{col}"),
            )
        )
    rows = tuple(DocumentTableRow(row_index=i, cells=tuple(rows_map[i])) for i in range(row_count))
    try:
        built = DocumentTable(
            table_id=table_id,
            row_count=row_count,
            column_count=column_count,
            rows=rows,
            coordinate=_coord(part=part, block_id=table_id),
        )
    except ValueError as exc:
        return None, [_diag("HWPX_TABLE_TOPOLOGY_INVALID", str(exc), DiagnosticSeverity.ERROR)]
    return built, diags


def map_hwpx_document(
    *,
    payload: dict,
    source_identifier: str,
    source_bytes: int,
    source_sha256: str,
    backend_version: str,
    package: PackageSupplement | None = None,
    backend_diagnostics: list[dict] | None = None,
    backend_warnings: list[str] | None = None,
) -> DocumentSource:
    if not isinstance(payload, dict) or "body_text" not in payload:
        raise ValueError("schema")
    char_shapes = list(((payload.get("doc_info") or {}).get("char_shapes")) or [])
    diagnostics: list[SourceDiagnostic] = []
    attachments: list[SourceAttachment] = []
    attachment_ids: set[str] = set()
    media_by_stem: dict[str, object] = {}
    layout_by_part = {layout.part: layout for layout in package.section_layouts} if package is not None else {}
    if package is not None:
        for item in package.media:
            stem = Pathish(item.part)
            attachments.append(
                SourceAttachment(
                    attachment_id=stem,
                    media_type=item.media_type,
                    byte_size=item.byte_size,
                    sha256=item.sha256,
                    local_reference=item.part,
                    properties=_props(("package_part", item.part)),
                )
            )
            attachment_ids.add(stem)
            media_by_stem[stem] = item
            media_by_stem[item.part] = item
    sections: list[DocumentSection] = []
    body_sections = ((payload.get("body_text") or {}).get("sections")) or []
    if not body_sections:
        diagnostics.append(_diag("HWPX_SCHEMA_UNSUPPORTED", "no sections", DiagnosticSeverity.ERROR))
    for section in body_sections:
        index = int(section.get("index") or 0)
        part = f"Contents/section{index}.xml"
        blocks = []
        for pi, para in enumerate(section.get("paragraphs") or []):
            para_id = str((para.get("para_header") or {}).get("instance_id") or f"p-{index}-{pi}")
            records = para.get("records")
            if not isinstance(records, list):
                diagnostics.append(_diag("HWPX_BLOCK_ORDER_UNPROVEN", f"paragraph {para_id} records missing"))
                continue
            for rec in records:
                rtype = rec.get("type")
                if rtype == "para_line_seg":
                    continue
                if rtype == "para_text":
                    paragraph, extra = _paragraph_from_text_record(rec, char_shapes, part, para_id)
                    blocks.append(paragraph)
                    diagnostics.extend(extra)
                elif rtype == "table":
                    table, extra = _table_from_record(rec, char_shapes, part, f"table-{para_id}")
                    diagnostics.extend(extra)
                    if table is not None:
                        blocks.append(table)
                elif rtype == "hwpx_image":
                    ref = str(rec.get("binary_item_ref") or "")
                    att_id = Pathish(ref) if ref else f"image-{para_id}"
                    media = media_by_stem.get(att_id) or media_by_stem.get(ref)
                    if att_id not in attachment_ids:
                        diagnostics.append(_diag("HWPX_ATTACHMENT_UNRESOLVED", f"image {att_id} not in package media"))
                        raw_items = ((payload.get("bin_data") or {}).get("items")) or []
                        match = next((it for it in raw_items if str(it.get("name") or it.get("index")) in {ref, att_id}), None)
                        if match is not None:
                            attachments.append(
                                SourceAttachment(
                                    attachment_id=att_id,
                                    media_type="application/octet-stream",
                                    byte_size=0,
                                    sha256="0" * 64,
                                    local_reference=ref,
                                    properties=_props(("unresolved", True)),
                                )
                            )
                            attachment_ids.add(att_id)
                        else:
                            continue
                    blocks.append(
                        DocumentImage(
                            image_id=f"img-{para_id}",
                            attachment_id=att_id,
                            media_type=media.media_type if media is not None else "application/octet-stream",
                            coordinate=_coord(part=part, block_id=f"img-{para_id}"),
                            properties=_props(("binary_item_ref", ref)),
                        )
                    )
                else:
                    blocks.append(
                        DocumentField(
                            field_type=str(rtype or "unknown"),
                            text="",
                            coordinate=_coord(part=part, block_id=f"field-{para_id}"),
                            properties=_props(("record_type", str(rtype))),
                        )
                    )
                    diagnostics.append(_diag("HWPX_UNSUPPORTED_CONTROL", f"unsupported record {rtype}"))
        layout = layout_by_part.get(part)
        page_width = float(layout.page_width) if layout and layout.page_width is not None else None
        page_height = float(layout.page_height) if layout and layout.page_height is not None else None
        column_count = layout.column_count if layout else None
        column_gap = float(layout.column_gap) if layout and layout.column_gap is not None else None
        if layout is None:
            diagnostics.append(_diag("HWPX_SECTION_LAYOUT_UNAVAILABLE", f"layout unavailable for {part}"))
        sections.append(
            DocumentSection(
                section_id=f"section-{index}",
                blocks=tuple(blocks),
                page_width=page_width,
                page_height=page_height,
                column_count=column_count,
                column_gap=column_gap,
                coordinate=_coord(part=part, block_id=f"section-{index}"),
                properties=_props(
                    ("margin_left", layout.margin_left if layout else None),
                    ("margin_right", layout.margin_right if layout else None),
                    ("margin_top", layout.margin_top if layout else None),
                    ("margin_bottom", layout.margin_bottom if layout else None),
                    ("unit", "hwpunit"),
                ),
            )
        )
    master_pages = []
    if package is not None:
        for master in package.master_pages:
            master_pages.append(
                DocumentMasterPage(
                    master_page_id=master.master_page_id,
                    kind=master.kind,
                    blocks=(),
                    properties=_props(("package_part", master.part)),
                )
            )
        if not master_pages:
            diagnostics.append(_diag("HWPX_MASTER_PAGE_UNAVAILABLE", "no master-page parts"))
    for item in backend_diagnostics or []:
        diagnostics.append(
            _diag(
                "HWPX_BACKEND_WARNING",
                str(item.get("category") or item.get("severity") or "backend"),
                DiagnosticSeverity.WARNING,
            )
        )
    for warning in backend_warnings or []:
        diagnostics.append(_diag("HWPX_BACKEND_WARNING", "backend warning present"))
    header = payload.get("file_header") or {}
    info = DocumentSourceAdapterInfo(
        backend_name="hwpxkit",
        backend_version=backend_version,
        supported_formats=(DocumentSourceFormat.HWPX,),
        capabilities=("sections", "paragraphs", "runs", "tables", "images", "diagnostics"),
        limitations=("no-exam-domain", "no-db", "no-gui", "no-export", "master-page-identity-only"),
    )
    return DocumentSource(
        source_format=DocumentSourceFormat.HWPX,
        source_identifier=source_identifier,
        source_bytes=source_bytes,
        source_sha256=source_sha256,
        backend_info=info,
        sections=tuple(sections),
        master_pages=tuple(master_pages),
        attachments=tuple(attachments),
        metadata=_props(("hwpx_version", header.get("version")), ("backend", "hwpxkit")),
        diagnostics=tuple(diagnostics),
    )


def Pathish(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
