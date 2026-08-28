from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from src.document_source.adapters.pdf import PdfSourceAdapter
from src.document_source.model import DocumentSourceFormat, DiagnosticSeverity
from src.document_source.signatures import probe_document_format
from src.parser.extractor import ImageData, PageData, TableData


def _write_pdf(path: Path, pages: list[str]) -> None:
    # Minimal multi-page PDF using pypdf if available, else a one-page %PDF stub.
    try:
        from pypdf import PdfWriter
        from pypdf.generic import NameObject, NumberObject, DictionaryObject, ArrayObject, DecodedStreamObject

        writer = PdfWriter()
        for text in pages:
            writer.add_blank_page(width=72, height=72)
        writer.write(path)
        # Ensure %PDF header exists
        data = path.read_bytes()
        assert data.startswith(b"%PDF")
    except Exception:
        body = b"%PDF-1.4\n1 0 obj<< /Type /Catalog >>endobj\ntrailer<<>>\n%%EOF\n"
        path.write_bytes(body)


def test_pdf_probe_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"%PDF-1.7\n%%EOF\n")
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.PDF
    assert probe.extension_mismatch is True


def test_from_pages_preserves_order_and_hash() -> None:
    adapter = PdfSourceAdapter()
    pages = [
        PageData(number=1, text="first page"),
        PageData(number=2, text="second page"),
    ]
    identity = SimpleNamespace(
        identifier="synthetic.pdf",
        source_bytes=12,
        source_sha256="f" * 64,
    )
    result = adapter.from_pages(identity.identifier, pages, source_bytes=12, source_sha256="f" * 64)
    assert result.success
    assert result.document is not None
    assert [s.section_id for s in result.document.sections] == ["page-1", "page-2"]
    assert result.document.sections[0].blocks[0].text == "first page"
    assert result.document.source_sha256 == "f" * 64


def test_from_pages_maps_tables_and_images(tmp_path: Path) -> None:
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    page = PageData(
        number=1,
        text="hello",
        tables=[TableData(rows=[["a", "b"], ["c", "d"]])],
        image_infos=[ImageData(path=str(img), bbox=(0, 0, 10, 10))],
    )
    adapter = PdfSourceAdapter()
    result = adapter.from_pages("p.pdf", [page], source_bytes=1, source_sha256="1" * 64)
    assert result.document is not None
    tables = [b for b in result.document.sections[0].blocks if b.__class__.__name__ == "DocumentTable"]
    images = [b for b in result.document.sections[0].blocks if b.__class__.__name__ == "DocumentImage"]
    assert len(tables) == 1
    assert tables[0].row_count == 2
    assert len(images) == 1
    assert images[0].attachment_id in {a.attachment_id for a in result.document.attachments}


def test_text_only_diagnostic() -> None:
    adapter = PdfSourceAdapter()
    page = PageData(number=1, text="only")
    result = adapter.from_pages("p.pdf", [page], source_bytes=1, source_sha256="2" * 64)
    codes = {d.code for d in result.diagnostics}
    assert "PDF_ADAPTER_TEXT_ONLY_PAGE" in codes


def test_parse_real_pdf_does_not_call_question_parser(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "n.pdf"
    _write_pdf(pdf, ["hello"])
    called = {"q": False, "a": False, "db": False}

    import src.parser.question as question
    import src.parser.answer as answer

    monkeypatch.setattr(question, "QuestionParser", lambda *a, **k: called.__setitem__("q", True))
    monkeypatch.setattr(answer, "AnswerParser", lambda *a, **k: called.__setitem__("a", True))

    adapter = PdfSourceAdapter()
    result = adapter.parse(pdf)
    assert called["q"] is False
    assert called["a"] is False
    before = pdf.read_bytes()
    adapter.parse(pdf)
    assert pdf.read_bytes() == before
    assert result.adapter_info.backend_name == "pdf-extractor"


def test_extractor_exception_normalized(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "n.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    adapter = PdfSourceAdapter()

    def boom(self, path):
        raise RuntimeError("fitz exploded")

    monkeypatch.setattr("src.parser.extractor.PDFExtractor.extract", boom)
    result = adapter.parse(pdf)
    assert result.success is False
    assert result.document is None
    assert any(d.severity is DiagnosticSeverity.ERROR for d in result.diagnostics)
    assert "fitz" not in " ".join(d.message for d in result.diagnostics).lower()
