from __future__ import annotations

import hashlib
import time
from pathlib import Path

from src.document_source.model import (
    DiagnosticSeverity,
    DocumentImage,
    DocumentParagraph,
    DocumentRun,
    DocumentSection,
    DocumentSource,
    DocumentSourceAdapterInfo,
    DocumentSourceFormat,
    DocumentSourceResult,
    DocumentTable,
    DocumentTableCell,
    DocumentTableRow,
    SourceAttachment,
    SourceCoordinate,
    SourceDiagnostic,
    SourceProperty,
)
from src.document_source.signatures import probe_document_format
from src.parser.extractor import PageData, PDFExtractor


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _coord(page_number: int, bbox=None) -> SourceCoordinate:
    if bbox and len(bbox) >= 4:
        x0, y0, x1, y1 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        return SourceCoordinate(
            part="page",
            page_number=page_number,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            unit="pt",
        )
    return SourceCoordinate(part="page", page_number=page_number, unit="pt")


def _paragraph(text: str, page_number: int) -> DocumentParagraph:
    return DocumentParagraph(
        runs=(DocumentRun(text=text, coordinate=_coord(page_number)),),
        coordinate=_coord(page_number),
    )


class PdfSourceAdapter:
    def __init__(self) -> None:
        self._info = DocumentSourceAdapterInfo(
            backend_name="pdf-extractor",
            backend_version="existing-src.parser.extractor",
            supported_formats=(DocumentSourceFormat.PDF,),
            capabilities=("text", "tables", "images"),
            limitations=("no-question-parse", "no-db", "pdf-page-as-section"),
        )

    def probe(self, path: str):
        return probe_document_format(path)

    def close(self) -> None:
        return None

    def from_pages(
        self,
        source_identifier: str,
        pages: list,
        *,
        source_bytes: int,
        source_sha256: str,
    ) -> DocumentSourceResult:
        diagnostics: list[SourceDiagnostic] = []
        sections: list[DocumentSection] = []
        attachments: list[SourceAttachment] = []
        for page in pages:
            number = int(getattr(page, "number", 1) or 1)
            blocks: list = []
            structured = getattr(page, "structured_page", None)
            if structured is not None and getattr(structured, "lines", ()):
                for line in structured.lines:
                    blocks.append(_paragraph(line.text, number))
            else:
                text = getattr(page, "text", "") or ""
                for line in text.splitlines() or [text]:
                    blocks.append(_paragraph(line, number))
                diagnostics.append(
                    SourceDiagnostic(
                        code="PDF_ADAPTER_TEXT_ONLY_PAGE",
                        severity=DiagnosticSeverity.WARNING,
                        message="page mapped from extractor text only",
                    )
                )
            for table in getattr(page, "tables", []) or []:
                rows_data = getattr(table, "rows", []) or []
                table_rows = []
                for r_i, row in enumerate(rows_data):
                    cells = []
                    for c_i, value in enumerate(row):
                        cells.append(
                            DocumentTableCell(
                                row=r_i,
                                column=c_i,
                                row_span=1,
                                column_span=1,
                                paragraphs=(_paragraph(str(value), number),),
                            )
                        )
                    table_rows.append(DocumentTableRow(row_index=r_i, cells=tuple(cells)))
                col_count = max((len(r) for r in rows_data), default=0)
                blocks.append(
                    DocumentTable(
                        table_id=f"p{number}-t{len(table_rows)}",
                        row_count=len(rows_data),
                        column_count=col_count,
                        rows=tuple(table_rows),
                    )
                )
            for index, image in enumerate(getattr(page, "image_infos", []) or []):
                att_id = f"p{number}-a{index}"
                img_path = getattr(image, "path", None)
                sha = "0" * 64
                byte_size = 0
                if img_path:
                    p = Path(img_path)
                    if p.is_file():
                        byte_size, sha = _sha256_file(p)
                attachments.append(
                    SourceAttachment(
                        attachment_id=att_id,
                        media_type="image/png",
                        byte_size=byte_size,
                        sha256=sha,
                        local_reference=img_path,
                    )
                )
                blocks.append(
                    DocumentImage(
                        image_id=f"p{number}-i{index}",
                        attachment_id=att_id,
                        media_type="image/png",
                        coordinate=_coord(number, getattr(image, "bbox", None)),
                    )
                )
            width = height = None
            if structured is not None:
                width = float(getattr(structured, "width", 0) or 0) or None
                height = float(getattr(structured, "height", 0) or 0) or None
            sections.append(
                DocumentSection(
                    section_id=f"page-{number}",
                    blocks=tuple(blocks),
                    page_width=width,
                    page_height=height,
                    properties=(SourceProperty(name="pdf_page", value=True),),
                    coordinate=_coord(number),
                )
            )
        document = DocumentSource(
            source_format=DocumentSourceFormat.PDF,
            source_identifier=source_identifier,
            source_bytes=source_bytes,
            source_sha256=source_sha256,
            backend_info=self._info,
            sections=tuple(sections),
            master_pages=(),
            attachments=tuple(attachments),
            metadata=(),
            diagnostics=tuple(diagnostics),
        )
        return DocumentSourceResult(
            document=document,
            diagnostics=tuple(diagnostics),
            adapter_info=self._info,
            elapsed_seconds=0.0,
            source_sha256=source_sha256,
            success=True,
        )

    def parse(self, path: str, options=None) -> DocumentSourceResult:
        started = time.perf_counter()
        p = Path(path)
        probe = self.probe(path)
        size, digest = _sha256_file(p)
        if probe.source_format is not DocumentSourceFormat.PDF:
            return DocumentSourceResult(
                document=None,
                diagnostics=probe.diagnostics
                + (
                    SourceDiagnostic(
                        code="SOURCE_SIGNATURE_UNKNOWN",
                        severity=DiagnosticSeverity.ERROR,
                        message="not a PDF",
                    ),
                ),
                adapter_info=self._info,
                elapsed_seconds=time.perf_counter() - started,
                source_sha256=digest,
                success=False,
            )
        extractor = PDFExtractor(output_dir=str(p.parent / "_eg_extract_unused"))
        try:
            if p.suffix.lower() == ".pdf":
                content = extractor.extract(str(p))
            else:
                content = extractor._extract_standard_pdf(p)
            pages = list(content.pages)
        except Exception:
            return DocumentSourceResult(
                document=None,
                diagnostics=(
                    SourceDiagnostic(
                        code="PDF_ADAPTER_EXTRACT_FAILED",
                        severity=DiagnosticSeverity.ERROR,
                        message="PDF extraction failed",
                    ),
                ),
                adapter_info=self._info,
                elapsed_seconds=time.perf_counter() - started,
                source_sha256=digest,
                success=False,
            )
        result = self.from_pages(str(p), pages, source_bytes=size, source_sha256=digest)
        return DocumentSourceResult(
            document=result.document,
            diagnostics=result.diagnostics + probe.diagnostics,
            adapter_info=self._info,
            elapsed_seconds=time.perf_counter() - started,
            source_sha256=digest,
            success=result.success,
        )
