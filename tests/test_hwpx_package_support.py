from __future__ import annotations

from pathlib import Path

import pytest

from src.document_source.adapters.hwpx_package import inspect_hwpx_package
from tests.hwpx_fixture_factory import hx1_minimal, hx3_multi_section, hx5_image, hx8_malformed


def test_page_and_column_from_section_xml(tmp_path: Path) -> None:
    path = tmp_path / "hx3.hwpx"
    hx3_multi_section(path)
    supp = inspect_hwpx_package(path)
    assert supp.page_width == 72852
    assert supp.page_height == 103180
    assert supp.column_count == 2
    assert supp.column_gap == 2268
    kinds = {m.kind for m in supp.master_pages}
    assert "EVEN" in kinds and "ODD" in kinds


def test_media_hashed_without_extractall(tmp_path: Path) -> None:
    path = tmp_path / "hx5.hwpx"
    hx5_image(path)
    supp = inspect_hwpx_package(path)
    assert len(supp.media) == 1
    assert supp.media[0].byte_size > 0
    assert len(supp.media[0].sha256) == 64
    assert supp.media[0].part.endswith("image1.png")


def test_traversal_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.hwpx"
    hx8_malformed(path, "traversal")
    with pytest.raises(ValueError, match="traversal"):
        inspect_hwpx_package(path)


def test_duplicate_rejected(tmp_path: Path) -> None:
    path = tmp_path / "dup.hwpx"
    hx8_malformed(path, "duplicate_path")
    with pytest.raises(ValueError, match="duplicate"):
        inspect_hwpx_package(path)


def test_oversize_rejected(tmp_path: Path) -> None:
    path = tmp_path / "huge.hwpx"
    hx8_malformed(path, "oversize_meta")
    with pytest.raises(ValueError, match="oversize"):
        inspect_hwpx_package(path)


def test_malformed_xml_bounded(tmp_path: Path) -> None:
    path = tmp_path / "xml.hwpx"
    hx8_malformed(path, "malformed_xml")
    with pytest.raises(ValueError):
        inspect_hwpx_package(path)


def test_source_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "hx1.hwpx"
    hx1_minimal(path)
    before = path.read_bytes()
    inspect_hwpx_package(path)
    assert path.read_bytes() == before
