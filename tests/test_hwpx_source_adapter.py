from __future__ import annotations

import json
from pathlib import Path

from src.document_source.adapters.hwpx import HwpxSourceAdapter
from src.document_source.adapters.hwpx_mapping import map_hwpx_document
from src.document_source.model import (
    DocumentSourceFormat,
    DocumentTable,
    SourceAttachment,
)
from src.document_source.signatures import probe_document_format
from tests.hwpx_fixture_factory import (
    hx1_minimal,
    hx4_table,
    hx5_image,
    hx8_malformed,
    mapper_payload_hx1,
    mapper_payload_table,
)


def test_mapper_sections_paragraphs_runs_unicode() -> None:
    doc = map_hwpx_document(
        payload=mapper_payload_hx1(),
        source_identifier="hx1",
        source_bytes=10,
        source_sha256="a" * 64,
        backend_version="0.2.1",
    )
    assert doc.source_format is DocumentSourceFormat.HWPX
    assert len(doc.sections) == 1
    paras = [b for b in doc.sections[0].blocks if getattr(b, "runs", None) is not None]
    assert len(paras) == 2
    assert paras[0].runs[0].text == "EGHX1-KO-한글"
    assert paras[0].text.endswith("#@$%")
    assert paras[1].text == "EGHX1-P2-second"


def test_mapper_table_topology_and_spans() -> None:
    doc = map_hwpx_document(
        payload=mapper_payload_table(),
        source_identifier="tbl",
        source_bytes=10,
        source_sha256="b" * 64,
        backend_version="0.2.1",
    )
    tables = [b for b in doc.sections[0].blocks if isinstance(b, DocumentTable)]
    assert len(tables) == 1
    table = tables[0]
    assert table.row_count == 2
    assert table.column_count == 2
    merged = [c for row in table.rows for c in row.cells if c.column_span == 2]
    assert merged and merged[0].row == 1


def test_mapper_no_backend_object_leakage() -> None:
    class Forbidden:
        pass

    payload = mapper_payload_hx1()
    doc = map_hwpx_document(
        payload=payload,
        source_identifier="hx1",
        source_bytes=10,
        source_sha256="c" * 64,
        backend_version="0.2.1",
    )
    blob = json.dumps(
        {
            "ids": [s.section_id for s in doc.sections],
            "diag": [d.code for d in doc.diagnostics],
        }
    )
    assert "hwpxkit" not in blob
    assert Forbidden not in type(doc).mro()


def test_probe_verified_hwpx(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.HWPX
    assert HwpxSourceAdapter().probe(str(path)).source_format is DocumentSourceFormat.HWPX


def test_generic_zip_rejected(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    import zipfile

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("hello.txt", "hi")
    result = HwpxSourceAdapter().parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_SIGNATURE_INVALID" for d in result.diagnostics)


def test_pdf_rejected(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    result = HwpxSourceAdapter().parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_SIGNATURE_INVALID" for d in result.diagnostics)


class _Doc:
    version = "5.1.0.0"
    section_count = 1
    warnings: list[str] = []

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_json(self) -> str:
        return json.dumps(self._payload)

    def diagnostic_report(self) -> dict:
        return {"items": [], "summary": {"total": 0}}


def test_injected_backend_parse_and_source_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)
    before = path.read_bytes()
    payload = mapper_payload_hx1()

    class Backend:
        def parse_file(self, given: str):
            assert given == str(path)
            return _Doc(payload)

    adapter = HwpxSourceAdapter(backend_loader=lambda: Backend(), version_loader=lambda: "0.2.1")
    result = adapter.parse(str(path))
    assert result.success is True
    assert result.document is not None
    assert result.document.sections[0].blocks
    assert path.read_bytes() == before
    assert list(path.parent.glob("*")) == [path]
    adapter.close()
    adapter.close()
    again = adapter.parse(str(path))
    assert again.success is True


def test_parse_exception_normalized(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)

    class Backend:
        def parse_file(self, _given: str):
            raise ValueError("boom")

    result = HwpxSourceAdapter(backend_loader=lambda: Backend(), version_loader=lambda: "0.2.1").parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_PARSE_FAILED" for d in result.diagnostics)


def test_malformed_json_normalized(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)

    class Bad:
        warnings: list[str] = []

        def parse_file(self, _given: str):
            return self

        def to_json(self) -> str:
            return "{not-json"

        def diagnostic_report(self) -> dict:
            return {"items": []}

    result = HwpxSourceAdapter(backend_loader=lambda: Bad(), version_loader=lambda: "0.2.1").parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_JSON_INVALID" for d in result.diagnostics)


def test_backend_warnings_not_silent(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)
    payload = mapper_payload_hx1()

    class WarnDoc(_Doc):
        warnings = ["stale"]

        def diagnostic_report(self) -> dict:
            return {
                "items": [
                    {
                        "severity": "Unsupported",
                        "category": "UnsupportedAttribute",
                        "message": "x",
                        "context": {},
                    }
                ],
                "summary": {"total": 1},
            }

    class Backend:
        def parse_file(self, _given: str):
            return WarnDoc(payload)

    result = HwpxSourceAdapter(backend_loader=lambda: Backend(), version_loader=lambda: "0.2.1").parse(str(path))
    assert result.success is True
    codes = {d.code for d in result.diagnostics}
    assert "HWPX_BACKEND_WARNING" in codes


def test_image_attachment_resolution(tmp_path: Path) -> None:
    path = tmp_path / "img.hwpx"
    hx5_image(path)
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"][0]["paragraphs"].append(
        {
            "para_header": {"instance_id": 9},
            "records": [{"type": "hwpx_image", "binary_item_ref": "image1", "brightness": 0, "contrast": 0, "effect": "REAL_PIC", "alpha": 0}],
        }
    )
    payload["bin_data"]["items"] = [{"index": 0, "name": "image1", "data": ""}]

    class Backend:
        def parse_file(self, _given: str):
            return _Doc(payload)

    result = HwpxSourceAdapter(backend_loader=lambda: Backend(), version_loader=lambda: "0.2.1").parse(str(path))
    assert result.success is True
    assert result.document is not None
    assert result.document.attachments
    assert all(isinstance(a, SourceAttachment) for a in result.document.attachments)


def test_hx4_package_probe(tmp_path: Path) -> None:
    path = tmp_path / "t.hwpx"
    hx4_table(path)
    assert probe_document_format(path).source_format is DocumentSourceFormat.HWPX


def test_wrong_mimetype_rejected(tmp_path: Path) -> None:
    path = tmp_path / "w.hwpx"
    hx8_malformed(path, "wrong_mimetype")
    result = HwpxSourceAdapter().parse(str(path))
    assert result.success is False
