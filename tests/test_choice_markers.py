from src.choice_markers import (
    CIRCLED_NUMBER_STYLE,
    DEFAULT_CHOICE_MARKER_STYLE,
    LEGACY_KOREAN_STYLE,
    choice_marker,
    normalize_choice_marker_style,
)


def test_legacy_style_preserves_existing_four_choice_markers():
    assert [choice_marker(number, LEGACY_KOREAN_STYLE) for number in range(1, 5)] == [
        "㉮",
        "㉯",
        "㉴",
        "㉵",
    ]


def test_circled_number_style_formats_all_editor_choice_numbers():
    assert [choice_marker(number, CIRCLED_NUMBER_STYLE) for number in range(1, 11)] == [
        "①",
        "②",
        "③",
        "④",
        "⑤",
        "⑥",
        "⑦",
        "⑧",
        "⑨",
        "⑩",
    ]


def test_invalid_style_falls_back_to_legacy_style():
    assert normalize_choice_marker_style("unknown") == DEFAULT_CHOICE_MARKER_STYLE
    assert choice_marker(1, "unknown") == "㉮"


def test_invalid_or_unsupported_number_uses_safe_fallback():
    assert choice_marker(None, CIRCLED_NUMBER_STYLE, fallback="원본") == "원본"
    assert choice_marker(11, CIRCLED_NUMBER_STYLE) == "11"
