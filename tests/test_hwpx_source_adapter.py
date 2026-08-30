from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.document_source.adapters.hwpx as hwpx_module
from src.document_source.adapters.hwpx import HwpxSourceAdapter
from src.document_source.adapters.hwpx_mapping import map_hwpx_document
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentImage,
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
    hx_multi_section_layouts,
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


def _parse_payload(path: Path, payload: dict):
    class Backend:
        def parse_file(self, _given: str):
            return _Doc(payload)

    return HwpxSourceAdapter(backend_loader=lambda: Backend(), version_loader=lambda: "0.2.1").parse(str(path))


def _section_property(section, name: str):
    return next(prop.value for prop in section.properties if prop.name == name)


@pytest.mark.parametrize(
    ("layouts", "expected_counts", "expected_gaps", "expected_widths", "expected_left_margins"),
    [
        (
            [
                {"page_width": 59528, "page_height": 84188, "column_count": 1, "column_gap": 0, "margin_left": 7001, "margin_right": 7002, "margin_top": 7003, "margin_bottom": 7004},
                {"page_width": 72852, "page_height": 103180, "column_count": 2, "column_gap": 2268, "margin_left": 8001, "margin_right": 8002, "margin_top": 8003, "margin_bottom": 8004},
            ],
            [1, 2],
            [0.0, 2268.0],
            [59528.0, 72852.0],
            [7001, 8001],
        ),
        (
            [
                {"page_width": 72852, "page_height": 103180, "column_count": 2, "column_gap": 2268, "margin_left": 8101, "margin_right": 8102, "margin_top": 8103, "margin_bottom": 8104},
                {"page_width": 59528, "page_height": 84188, "column_count": 1, "column_gap": 0, "margin_left": 7101, "margin_right": 7102, "margin_top": 7103, "margin_bottom": 7104},
            ],
            [2, 1],
            [2268.0, 0.0],
            [72852.0, 59528.0],
            [8101, 7101],
        ),
        (
            [
                {"page_width": 59528, "page_height": 84188, "column_count": 1, "column_gap": 111, "margin_left": 7201, "margin_right": 7202, "margin_top": 7203, "margin_bottom": 7204},
                {"page_width": 72852, "page_height": 103180, "column_count": 2, "column_gap": 222, "margin_left": 8201, "margin_right": 8202, "margin_top": 8203, "margin_bottom": 8204},
                {"page_width": 61200, "page_height": 90000, "column_count": 1, "column_gap": 333, "margin_left": 9201, "margin_right": 9202, "margin_top": 9203, "margin_bottom": 9204},
            ],
            [1, 2, 1],
            [111.0, 222.0, 333.0],
            [59528.0, 72852.0, 61200.0],
            [7201, 8201, 9201],
        ),
    ],
    ids=("L1-forward-with-local-properties", "L2-reverse-with-local-properties", "L3-alternating-with-local-properties"),
)
def test_section_layouts_are_bound_to_exact_source_sections(
    tmp_path: Path,
    layouts: list[dict[str, int]],
    expected_counts: list[int],
    expected_gaps: list[float],
    expected_widths: list[float],
    expected_left_margins: list[int],
) -> None:
    path = tmp_path / "layouts.hwpx"
    hx_multi_section_layouts(path, layouts)
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"] = [{"index": index, "paragraphs": []} for index in range(len(layouts))]

    result = _parse_payload(path, payload)

    assert result.success is True
    assert result.document is not None
    assert [section.section_id for section in result.document.sections] == [f"section-{index}" for index in range(len(layouts))]
    assert [section.column_count for section in result.document.sections] == expected_counts
    assert [section.column_gap for section in result.document.sections] == expected_gaps
    assert [section.page_width for section in result.document.sections] == expected_widths
    assert [_section_property(section, "margin_left") for section in result.document.sections] == expected_left_margins
    assert all(isinstance(section.properties, tuple) for section in result.document.sections)


def test_missing_section_layout_does_not_borrow_neighbor(tmp_path: Path) -> None:
    path = tmp_path / "missing-layout.hwpx"
    hx_multi_section_layouts(
        path,
        [
            {"page_width": 59528, "page_height": 84188, "column_count": 1, "column_gap": 0, "margin_left": 7001, "margin_right": 7002, "margin_top": 7003, "margin_bottom": 7004},
            {"page_width": 72852, "page_height": 103180, "column_count": 2, "column_gap": 2268, "margin_left": 8001, "margin_right": 8002, "margin_top": 8003, "margin_bottom": 8004},
        ],
    )
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"] = [{"index": index, "paragraphs": []} for index in range(3)]

    result = _parse_payload(path, payload)

    assert result.success is True
    assert result.document is not None
    assert [section.column_count for section in result.document.sections] == [1, 2, None]
    assert result.document.sections[2].page_width is None
    assert any(d.code == "HWPX_SECTION_LAYOUT_UNAVAILABLE" for d in result.diagnostics)


def test_empty_semantic_document_with_error_is_unsuccessful(tmp_path: Path) -> None:
    path = tmp_path / "empty-sections.hwpx"
    hx1_minimal(path)
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"] = []

    result = _parse_payload(path, payload)

    assert result.document is not None
    assert result.success is False
    assert any(d.code == "HWPX_SCHEMA_UNSUPPORTED" and d.severity is DiagnosticSeverity.ERROR for d in result.diagnostics)


def test_valid_document_with_semantic_error_is_unsuccessful(tmp_path: Path) -> None:
    path = tmp_path / "semantic-error.hwpx"
    hx1_minimal(path)
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"][0]["paragraphs"].append(
        {
            "para_header": {"instance_id": 99},
            "records": [{"type": "table", "table": {"attributes": {"row_count": 0, "col_count": 0}, "cells": []}}],
        }
    )

    result = _parse_payload(path, payload)

    assert result.document is not None
    assert result.document.sections[0].blocks
    assert result.success is False
    assert any(d.code == "HWPX_TABLE_TOPOLOGY_INVALID" and d.severity is DiagnosticSeverity.ERROR for d in result.diagnostics)


def test_source_size_cap_is_enforced_before_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "oversize.hwpx"
    path.write_bytes(b"xx")
    monkeypatch.setattr(hwpx_module, "MAX_SOURCE_BYTES", 1)

    def unexpected_hash(_path: Path):
        pytest.fail("oversize source was hashed before the size cap was enforced")

    monkeypatch.setattr(hwpx_module, "_hash_file", unexpected_hash)

    result = HwpxSourceAdapter().parse(str(path))

    assert result.success is False
    assert any(d.code == "HWPX_RESOURCE_LIMIT" for d in result.diagnostics)


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


def test_successful_parse_retains_probe_diagnostics(tmp_path: Path) -> None:
    path = tmp_path / "extension-mismatch.bin"
    hx1_minimal(path)

    result = _parse_payload(path, mapper_payload_hx1())

    assert result.success is True
    assert any(d.code == "SOURCE_EXTENSION_MISMATCH" and d.severity is DiagnosticSeverity.WARNING for d in result.diagnostics)


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


def test_mapped_image_uses_attachment_mime_type(tmp_path: Path) -> None:
    path = tmp_path / "img-mime.hwpx"
    hx5_image(path)
    payload = mapper_payload_hx1()
    payload["body_text"]["sections"][0]["paragraphs"].append(
        {
            "para_header": {"instance_id": 9},
            "records": [{"type": "hwpx_image", "binary_item_ref": "image1", "brightness": 0, "contrast": 0, "effect": "REAL_PIC", "alpha": 0}],
        }
    )
    payload["bin_data"]["items"] = [{"index": 0, "name": "image1", "data": ""}]

    result = _parse_payload(path, payload)

    assert result.success is True
    assert result.document is not None
    images = [block for section in result.document.sections for block in section.blocks if isinstance(block, DocumentImage)]
    assert [image.media_type for image in images] == ["image/png"]


def test_hx4_package_probe(tmp_path: Path) -> None:
    path = tmp_path / "t.hwpx"
    hx4_table(path)
    assert probe_document_format(path).source_format is DocumentSourceFormat.HWPX


def test_wrong_mimetype_rejected(tmp_path: Path) -> None:
    path = tmp_path / "w.hwpx"
    hx8_malformed(path, "wrong_mimetype")
    result = HwpxSourceAdapter().parse(str(path))
    assert result.success is False
