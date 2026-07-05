from zipfile import ZipFile

import fitz

from src.parser.extractor import PDFExtractor


def _write_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_pdf_extractor_reads_zip_without_manifest_by_concatenating_pdfs(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    archive = tmp_path / "bundle.zip"
    _write_pdf(first, "first pdf page")
    _write_pdf(second, "second pdf page")

    with ZipFile(archive, "w") as zip_file:
        zip_file.write(first, "nested/first.pdf")
        zip_file.write(second, "second.pdf")

    content = PDFExtractor(str(tmp_path / "extract")).extract(str(archive))

    assert content.manifest["type"] == "pdf_zip"
    assert [page.text.strip() for page in content.pages] == ["first pdf page", "second pdf page"]
