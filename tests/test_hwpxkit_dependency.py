from __future__ import annotations

from pathlib import Path

from src.document_source.adapters.hwpx import EXPECTED_HWPXKIT_VERSION, HwpxSourceAdapter


def test_requirements_pin_is_exact() -> None:
    text = Path("requirements.txt").read_text(encoding="utf-8")
    assert "hwpxkit==0.2.1" in text
    assert EXPECTED_HWPXKIT_VERSION == "0.2.1"


def test_public_package_import_does_not_load_hwpxkit() -> None:
    import json
    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    child_code = (
        "import json\n"
        "import sys\n"
        "def loaded():\n"
        "    return sorted(name for name in sys.modules "
        "if name == 'hwpxkit' or name.startswith('hwpxkit.'))\n"
        "before = loaded()\n"
        "import src.document_source\n"
        "after = loaded()\n"
        "print(json.dumps({'after': after, 'before': before}, "
        "sort_keys=True, separators=(',', ':')))\n"
        "raise SystemExit(0 if before == [] and after == [] else 1)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError("clean public-package import child timed out after 30 seconds") from exc

    diagnostics = (
        f"child returncode={completed.returncode}\n"
        f"stdout={completed.stdout!r}\n"
        f"stderr={completed.stderr!r}"
    )
    assert completed.returncode == 0, diagnostics
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"child did not emit deterministic JSON\n{diagnostics}") from exc
    assert payload == {"after": [], "before": []}, diagnostics


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
