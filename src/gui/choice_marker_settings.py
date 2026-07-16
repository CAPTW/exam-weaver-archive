"""Persistence for the app-wide objective-choice marker preference."""

from __future__ import annotations

import json
from pathlib import Path

from ..choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    SUPPORTED_CHOICE_MARKER_STYLES,
    normalize_choice_marker_style,
)


def _settings_path(base_dir: str | Path) -> Path:
    return Path(base_dir).resolve() / "data" / "app_settings.json"


def load_choice_marker_style(base_dir: str | Path) -> str:
    """Load the saved style or return the backward-compatible default."""
    try:
        payload = json.loads(_settings_path(base_dir).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return DEFAULT_CHOICE_MARKER_STYLE
    if not isinstance(payload, dict):
        return DEFAULT_CHOICE_MARKER_STYLE
    return normalize_choice_marker_style(payload.get("choice_marker_style"))


def save_choice_marker_style(base_dir: str | Path, style: str) -> Path:
    """Atomically save a validated style while preserving other app settings."""
    if style not in SUPPORTED_CHOICE_MARKER_STYLES:
        raise ValueError(f"지원하지 않는 선지 번호 표시 방식입니다: {style}")

    target = _settings_path(base_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload.update(existing)
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    payload["choice_marker_style"] = style

    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
