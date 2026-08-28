from __future__ import annotations

from pathlib import Path


def test_spec_collects_hwpxkit_and_license() -> None:
    spec = Path("ExamGenerator.spec").read_text(encoding="utf-8")
    assert "collect_all('hwpxkit')" in spec or 'collect_all("hwpxkit")' in spec
    assert "third_party_licenses/hwpxkit-MIT.txt" in spec.replace("\\", "/")


def test_license_notice_files_exist() -> None:
    notice = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    license_text = Path("third_party_licenses/hwpxkit-MIT.txt").read_text(encoding="utf-8")
    assert "hwpxkit" in notice
    assert "0.2.1" in notice
    assert "Han-taz/hwpx-rust" in notice
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 kevin" in license_text
