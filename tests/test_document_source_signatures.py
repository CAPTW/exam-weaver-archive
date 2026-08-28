from __future__ import annotations

import zipfile
from pathlib import Path

from src.document_source.model import DocumentSourceFormat
from src.document_source.signatures import probe_document_format


def _minimal_hwpx_bytes() -> bytes:
    from io import BytesIO

    bio = BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("version.xml", "<hv:HCFVersion/>")
        z.writestr("META-INF/manifest.xml", "<manifest/>")
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("Contents/content.hpf", "<hpf/>")
        z.writestr("Contents/header.xml", "<header/>")
        z.writestr("Contents/section0.xml", "<section/>")
    return bio.getvalue()


def test_pdf_signature_ignores_extension(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.PDF
    assert probe.extension_mismatch is True


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    probe = probe_document_format(path)
    assert any(d.code == "SOURCE_FILE_EMPTY" for d in probe.diagnostics)


def test_unknown_bytes(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"XXXX????not-a-doc")
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.UNKNOWN
    assert any(d.code == "SOURCE_SIGNATURE_UNKNOWN" for d in probe.diagnostics)


def test_valid_minimal_hwpx(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    path.write_bytes(_minimal_hwpx_bytes())
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.HWPX


def test_generic_zip_is_not_hwpx(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("hello.txt", "hi")
    probe = probe_document_format(path)
    assert probe.source_format is not DocumentSourceFormat.HWPX
    assert any(d.code == "SOURCE_ZIP_NOT_HWPX" for d in probe.diagnostics)


def test_wrong_mimetype(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/zip")
        z.writestr("version.xml", "<hv/>")
        z.writestr("META-INF/manifest.xml", "<m/>")
        z.writestr("META-INF/container.xml", "<c/>")
        z.writestr("Contents/content.hpf", "<h/>")
        z.writestr("Contents/header.xml", "<h/>")
        z.writestr("Contents/section0.xml", "<s/>")
    probe = probe_document_format(path)
    assert probe.source_format is not DocumentSourceFormat.HWPX


def test_missing_required_part(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("version.xml", "<hv/>")
    probe = probe_document_format(path)
    assert any(d.code == "SOURCE_HWPX_REQUIRED_PART_MISSING" for d in probe.diagnostics)


def test_traversal_entry_rejected(tmp_path: Path) -> None:
    path = tmp_path / "doc.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("../escape.txt", "x")
        z.writestr("mimetype", "application/hwp+zip")
    probe = probe_document_format(path)
    assert any(
        d.code in {"SOURCE_HWPX_CONTAINER_MALFORMED", "SOURCE_ZIP_NOT_HWPX"}
        for d in probe.diagnostics
    )


def test_duplicate_entry_rejected(tmp_path: Path) -> None:
    from io import BytesIO

    bio = BytesIO()
    with zipfile.ZipFile(bio, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("mimetype", "application/hwp+zip")
    path = tmp_path / "dup.hwpx"
    path.write_bytes(bio.getvalue())
    probe = probe_document_format(path)
    assert probe.source_format is not DocumentSourceFormat.HWPX or any(
        d.code == "SOURCE_HWPX_CONTAINER_MALFORMED" for d in probe.diagnostics
    )
