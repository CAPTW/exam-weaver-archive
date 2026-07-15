import json
from pathlib import Path

import pytest

from src.gui.menu_language import (
    MENU_KEYS,
    discover_menu_language_packs,
    load_menu_locale,
    menu_text,
    save_menu_locale,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_builtin_menu_packs_supply_every_known_key():
    packs, warnings = discover_menu_language_packs(PROJECT_ROOT)

    assert warnings == []
    assert set(packs) >= {"ko", "en"}
    for key in MENU_KEYS:
        assert packs["ko"].strings[key]
        assert packs["en"].strings[key]


def test_external_pack_uses_korean_fallback_and_ignores_unknown_keys(tmp_path):
    pack_dir = tmp_path / "data" / "language_packs" / "menu"
    pack_dir.mkdir(parents=True)
    (pack_dir / "ja.json").write_text(
        json.dumps(
            {
                "locale": "ja",
                "display_name": "日本語",
                "version": 1,
                "strings": {
                    "menu.home": "ホーム",
                    "unknown": "ignored",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packs, warnings = discover_menu_language_packs(tmp_path)

    assert warnings == []
    assert menu_text(packs["ja"], "menu.home") == "ホーム"
    assert menu_text(packs["ja"], "menu.export") == "시험지 출력"
    assert "unknown" not in packs["ja"].strings


def test_broken_external_pack_is_excluded_without_blocking_startup(tmp_path):
    pack_dir = tmp_path / "data" / "language_packs" / "menu"
    pack_dir.mkdir(parents=True)
    (pack_dir / "broken.json").write_text("{", encoding="utf-8")

    packs, warnings = discover_menu_language_packs(tmp_path)

    assert set(packs) >= {"ko", "en"}
    assert any("broken.json" in warning for warning in warnings)


def test_pack_with_invalid_metadata_is_excluded(tmp_path):
    pack_dir = tmp_path / "data" / "language_packs" / "menu"
    pack_dir.mkdir(parents=True)
    (pack_dir / "unsafe.json").write_text(
        json.dumps(
            {
                "locale": "../unsafe",
                "display_name": "Unsafe",
                "version": 1,
                "strings": {"menu.home": "Unsafe"},
            }
        ),
        encoding="utf-8",
    )

    packs, warnings = discover_menu_language_packs(tmp_path)

    assert "../unsafe" not in packs
    assert any("unsafe.json" in warning for warning in warnings)


def test_menu_locale_setting_round_trips_and_unknown_value_falls_back(tmp_path):
    save_menu_locale(tmp_path, "en", {"ko", "en"})
    assert load_menu_locale(tmp_path, {"ko", "en"}) == "en"

    settings = tmp_path / "data" / "app_settings.json"
    settings.write_text('{"menu_locale":"xx"}', encoding="utf-8")

    assert load_menu_locale(tmp_path, {"ko", "en"}) == "ko"


def test_save_menu_locale_rejects_unknown_value(tmp_path):
    with pytest.raises(ValueError, match="지원하지 않는 메뉴 언어"):
        save_menu_locale(tmp_path, "xx", {"ko", "en"})

