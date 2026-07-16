import json

from src.choice_markers import (
    CIRCLED_NUMBER_STYLE,
    DEFAULT_CHOICE_MARKER_STYLE,
)
from src.gui.choice_marker_settings import (
    load_choice_marker_style,
    save_choice_marker_style,
)


def test_choice_marker_setting_round_trips_and_preserves_other_settings(tmp_path):
    settings = tmp_path / "data" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"menu_locale": "en", "future_setting": True}),
        encoding="utf-8",
    )

    save_choice_marker_style(tmp_path, CIRCLED_NUMBER_STYLE)

    assert load_choice_marker_style(tmp_path) == CIRCLED_NUMBER_STYLE
    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "menu_locale": "en",
        "future_setting": True,
        "choice_marker_style": CIRCLED_NUMBER_STYLE,
    }


def test_missing_broken_or_unknown_choice_marker_setting_uses_default(tmp_path):
    assert load_choice_marker_style(tmp_path) == DEFAULT_CHOICE_MARKER_STYLE

    settings = tmp_path / "data" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{", encoding="utf-8")
    assert load_choice_marker_style(tmp_path) == DEFAULT_CHOICE_MARKER_STYLE

    settings.write_text(
        json.dumps({"choice_marker_style": "unknown"}),
        encoding="utf-8",
    )
    assert load_choice_marker_style(tmp_path) == DEFAULT_CHOICE_MARKER_STYLE


def test_save_choice_marker_style_rejects_unknown_style(tmp_path):
    try:
        save_choice_marker_style(tmp_path, "unknown")
    except ValueError as exc:
        assert "지원하지 않는 선지 번호 표시 방식" in str(exc)
    else:
        raise AssertionError("unknown style must be rejected")
