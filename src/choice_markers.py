"""Presentation-only markers for objective-choice numbers."""

from __future__ import annotations

from types import MappingProxyType


LEGACY_KOREAN_STYLE = "legacy_korean"
CIRCLED_NUMBER_STYLE = "circled_number"
DEFAULT_CHOICE_MARKER_STYLE = LEGACY_KOREAN_STYLE
SUPPORTED_CHOICE_MARKER_STYLES = frozenset(
    {LEGACY_KOREAN_STYLE, CIRCLED_NUMBER_STYLE}
)

CHOICE_MARKER_STYLE_LABELS = MappingProxyType(
    {
        LEGACY_KOREAN_STYLE: "한글 원문자 (㉮ ㉯ ㉴ ㉵)",
        CIRCLED_NUMBER_STYLE: "숫자 원문자 (① ② ③ ④)",
    }
)

_MARKERS = MappingProxyType(
    {
        LEGACY_KOREAN_STYLE: MappingProxyType(
            {1: "㉮", 2: "㉯", 3: "㉴", 4: "㉵", 5: "⑤"}
        ),
        CIRCLED_NUMBER_STYLE: MappingProxyType(
            dict(enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1))
        ),
    }
)


def normalize_choice_marker_style(style: object) -> str:
    """Return a supported style, falling back to the legacy presentation."""
    if isinstance(style, str) and style in SUPPORTED_CHOICE_MARKER_STYLES:
        return style
    return DEFAULT_CHOICE_MARKER_STYLE


def choice_marker(
    number: object,
    style: object = DEFAULT_CHOICE_MARKER_STYLE,
    fallback: str = "",
) -> str:
    """Format a semantic choice number without changing stored DB symbols."""
    try:
        normalized_number = int(number)
    except (TypeError, ValueError):
        return str(fallback or "")

    markers = _MARKERS[normalize_choice_marker_style(style)]
    return markers.get(normalized_number, str(fallback or normalized_number))
