from pathlib import Path

def _docx_exporter():
    from src.exporter.docx import DocxExporter

    return DocxExporter


def test_export_interface_constructs_builder_and_docx_export_document():
    source = inspect_export_source()
    assert "self.document_builder = ExamDocumentBuilder()" in source
    assert "export_document" in source
    assert hasattr(_docx_exporter(), "export_document")


def test_export_interface_keeps_docx_copy_and_has_no_hwpx_selector():
    source = inspect_export_source()
    assert "모의고사 출력 (DOCX)" in source
    assert "DOCX 시험지 저장" in source
    assert "DOCX 문서 (*.docx)" in source
    assert "HwpxExporter" not in source
    assert "QComboBox" in source


def inspect_export_source():
    return (
        Path(__file__).resolve().parents[1] / "src" / "gui" / "interface" / "export.py"
    ).read_text(encoding="utf-8")
