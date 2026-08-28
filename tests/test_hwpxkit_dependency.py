from __future__ import annotations

from pathlib import Path

from src.document_source import probe_document_format
from src.document_source.adapters.hwpx import EXPECTED_HWPXKIT_VERSION, HwpxSourceAdapter


def test_requirements_pin_is_exact() -> None:
    text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "hwpxkit==0.2.1" in text
    assert EXPECTED_HWPXKIT_VERSION == "0.2.1"


def test_public_package_import_does_not_load_hwpxkit() -> None:
    import sys

    assert "hwpxkit" not in sys.modules
    import src.document_source as ds

    assert ds.probe_document_format is probe_document_format
    assert "hwpxkit" not in sys.modules


def test_adapter_module_import_does_not_load_hwpxkit() -> None:
    import sys

    sys.modules.pop("hwpxkit", None)
    from src.document_source.adapters import hwpx as hwpx_mod

    assert hwpx_mod.EXPECTED_HWPXKIT_VERSION == "0.2.1"
    assert "hwpxkit" not in sys.modules


def test_absent_backend_returns_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "doc.hwpx"
    from tests.hwpx_fixture_factory import hx1_minimal

    hx1_minimal(path)

    def loader():
        raise ImportError("simulated missing hwpxkit")

    result = HwpxSourceAdapter(backend_loader=loader).parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_BACKEND_UNAVAILABLE" for d in result.diagnostics)


def test_wrong_version_fails_closed(tmp_path: Path) -> None:
    from tests.hwpx_fixture_factory import hx1_minimal

    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)

    class Fake:
        __version__ = "9.9.9"

        def parse_file(self, _path):
            raise AssertionError("must not parse")

    result = HwpxSourceAdapter(backend_loader=lambda: Fake(), version_loader=lambda: "9.9.9").parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_BACKEND_VERSION_MISMATCH" for d in result.diagnostics)


def test_native_import_failure_normalized(tmp_path: Path) -> None:
    from tests.hwpx_fixture_factory import hx1_minimal

    path = tmp_path / "doc.hwpx"
    hx1_minimal(path)
    result = HwpxSourceAdapter(backend_loader=lambda: (_ for _ in ()).throw(OSError("pyd"))).parse(str(path))
    assert result.success is False
    assert any(d.code == "HWPX_BACKEND_IMPORT_FAILED" for d in result.diagnostics)


def test_runtime_exact_version_when_available() -> None:
    adapter = HwpxSourceAdapter()
    try:
        info = adapter._load_backend()  # noqa: SLF001
    except Exception:
        info = None
    if info is None:
        return
    backend, version = info
    assert version == "0.2.1"
    assert backend is not None
