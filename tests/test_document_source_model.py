from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.document_source import (
    DiagnosticSeverity,
    DocumentField,
    DocumentFormatProbe,
    DocumentImage,
    DocumentLayoutBreak,
    DocumentMasterPage,
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
    LayoutBreakKind,
    ProbeConfidence,
    SourceAttachment,
    SourceCoordinate,
    SourceDiagnostic,
    SourceProperty,
)


ROOT = Path(__file__).resolve().parents[1]


def _coord(**kwargs) -> SourceCoordinate:
    defaults = {
        "part": "page",
        "page_number": 1,
        "char_start": 0,
        "char_end": 1,
        "x0": 0.0,
        "y0": 0.0,
        "x1": 1.0,
        "y1": 1.0,
        "unit": "pt",
        "properties": (),
    }
    defaults.update(kwargs)
    return SourceCoordinate(**defaults)


def _run(text: str = "hello") -> DocumentRun:
    return DocumentRun(text=text, coordinate=_coord(), properties=())


def _para(text: str = "hello") -> DocumentParagraph:
    run = _run(text)
    return DocumentParagraph(runs=(run,), coordinate=_coord(), properties=())


def test_dataclasses_are_frozen_and_slotted() -> None:
    run = _run()
    with pytest.raises(FrozenInstanceError):
        run.text = "nope"  # type: ignore[misc]
    assert hasattr(run, "__slots__")


def test_tuple_collections_not_lists() -> None:
    para = _para()
    assert isinstance(para.runs, tuple)
    src = DocumentSource(
        source_format=DocumentSourceFormat.PDF,
        source_identifier="doc.pdf",
        source_bytes=10,
        source_sha256="a" * 64,
        backend_info=DocumentSourceAdapterInfo(
            backend_name="pdf",
            backend_version="test",
            supported_formats=(DocumentSourceFormat.PDF,),
            capabilities=(),
            limitations=(),
        ),
        sections=(
            DocumentSection(
                section_id="s1",
                blocks=(_para(),),
                properties=(),
            ),
        ),
        master_pages=(),
        attachments=(),
        metadata=(),
        diagnostics=(),
    )
    assert isinstance(src.sections, tuple)
    hash(src)


def test_invalid_coordinates_rejected() -> None:
    with pytest.raises(ValueError):
        _coord(page_number=0)
    with pytest.raises(ValueError):
        _coord(char_start=-1)
    with pytest.raises(ValueError):
        _coord(char_end=0, char_start=2)
    with pytest.raises(ValueError):
        _coord(x1=0.0, x0=1.0)
    with pytest.raises(ValueError):
        _coord(unit="")


def test_table_topology_and_overlap_rejected() -> None:
    cell = DocumentTableCell(
        row=0,
        column=0,
        row_span=1,
        column_span=1,
        paragraphs=(_para("a"),),
        properties=(),
    )
    table = DocumentTable(
        table_id="t1",
        row_count=1,
        column_count=1,
        rows=(DocumentTableRow(row_index=0, cells=(cell,), properties=()),),
        properties=(),
    )
    assert table.row_count == 1
    overlap = DocumentTableCell(
        row=0,
        column=0,
        row_span=1,
        column_span=1,
        paragraphs=(_para("b"),),
        properties=(),
    )
    with pytest.raises(ValueError):
        DocumentTable(
            table_id="t2",
            row_count=1,
            column_count=1,
            rows=(
                DocumentTableRow(row_index=0, cells=(cell, overlap), properties=()),
            ),
            properties=(),
        )
    with pytest.raises(ValueError):
        DocumentTableCell(
            row=-1,
            column=0,
            row_span=1,
            column_span=1,
            paragraphs=(),
            properties=(),
        )


def test_image_attachment_must_resolve() -> None:
    image = DocumentImage(
        image_id="i1",
        attachment_id="missing",
        media_type="image/png",
        properties=(),
    )
    with pytest.raises(ValueError):
        DocumentSource(
            source_format=DocumentSourceFormat.PDF,
            source_identifier="x",
            source_bytes=1,
            source_sha256="b" * 64,
            backend_info=DocumentSourceAdapterInfo(
                backend_name="pdf",
                backend_version="t",
                supported_formats=(DocumentSourceFormat.PDF,),
                capabilities=(),
                limitations=(),
            ),
            sections=(
                DocumentSection(section_id="s1", blocks=(image,), properties=()),
            ),
            master_pages=(),
            attachments=(),
            metadata=(),
            diagnostics=(),
        )


def test_paragraph_text_is_deterministic() -> None:
    para = DocumentParagraph(
        runs=(_run("ab"), _run("cd")),
        coordinate=_coord(),
        properties=(),
    )
    assert para.text == "abcd"


def test_diagnostics_and_backend_properties_isolated() -> None:
    diag = SourceDiagnostic(
        code="PDF_ADAPTER_TEXT_ONLY_PAGE",
        severity=DiagnosticSeverity.WARNING,
        message="text only",
        properties=(SourceProperty(name="backend", value="pdf"),),
    )
    src = DocumentSource(
        source_format=DocumentSourceFormat.PDF,
        source_identifier="x",
        source_bytes=1,
        source_sha256="c" * 64,
        backend_info=DocumentSourceAdapterInfo(
            backend_name="pdf",
            backend_version="t",
            supported_formats=(DocumentSourceFormat.PDF,),
            capabilities=(),
            limitations=(),
        ),
        sections=(DocumentSection(section_id="s1", blocks=(_para(),), properties=()),),
        master_pages=(),
        attachments=(),
        metadata=(),
        diagnostics=(diag,),
    )
    assert src.diagnostics[0].code == "PDF_ADAPTER_TEXT_ONLY_PAGE"
    assert isinstance(src.diagnostics[0].properties[0].value, str)


def test_model_modules_stdlib_only() -> None:
    forbidden = {
        "fitz",
        "pymupdf",
        "PIL",
        "PyQt5",
        "sqlite3",
        "hwpxkit",
        "hwp_hwpx_parser",
        "hwpx",
        "olefile",
        "docx",
        "src.parser",
        "src.exporter",
        "src.gui",
        "src.database",
    }
    for rel in (
        "src/document_source/model.py",
        "src/document_source/cfb.py",
        "src/document_source/signatures.py",
        "src/document_source/adapters/base.py",
    ):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
                imported.add(node.module)
        assert not (imported & forbidden), rel


def test_probe_and_result_types_exist() -> None:
    probe = DocumentFormatProbe(
        source_format=DocumentSourceFormat.UNKNOWN,
        confidence=ProbeConfidence.UNKNOWN,
        diagnostics=(),
        extension_mismatch=False,
    )
    assert probe.source_format is DocumentSourceFormat.UNKNOWN
    result = DocumentSourceResult(
        document=None,
        diagnostics=(),
        adapter_info=DocumentSourceAdapterInfo(
            backend_name="none",
            backend_version="0",
            supported_formats=(),
            capabilities=(),
            limitations=(),
        ),
        elapsed_seconds=0.0,
        source_sha256="d" * 64,
        success=False,
    )
    assert result.success is False
    assert LayoutBreakKind.PAGE.value == "PAGE"
    _ = DocumentField(field_type="text", text="", properties=())
    _ = DocumentLayoutBreak(kind=LayoutBreakKind.PAGE, properties=())
    _ = DocumentMasterPage(master_page_id="m1", kind="ODD", blocks=(), properties=())
    _ = SourceAttachment(
        attachment_id="a1",
        media_type="image/png",
        byte_size=1,
        sha256="e" * 64,
        properties=(),
    )
