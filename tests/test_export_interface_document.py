from pathlib import Path

def _docx_exporter():
    from src.exporter.docx import DocxExporter

    return DocxExporter


def test_export_interface_constructs_builder_and_docx_export_document():
    source = inspect_export_source()
    assert "self.document_builder = ExamDocumentBuilder()" in source
    assert "export_document" in source
    assert hasattr(_docx_exporter(), "export_document")


def test_export_interface_exposes_docx_and_hwpx_selector_copy():
    source = inspect_export_source()
    assert "시험지 내보내기" in source
    from src.gui.export_formats import FORMAT_DOCX, FORMAT_HWPX, button_text

    assert "시험지 내보내기" in source
    assert button_text(FORMAT_DOCX) == "DOCX 시험지 저장"
    assert button_text(FORMAT_HWPX) == "HWPX 시험지 저장"
    assert "HwpxExporter" not in source
    assert "outputFormatFilter" in source


def inspect_export_source():
    return (
        Path(__file__).resolve().parents[1] / "src" / "gui" / "interface" / "export.py"
    ).read_text(encoding="utf-8")
