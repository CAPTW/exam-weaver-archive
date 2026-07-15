"""Safe, menu-only language packs and portable UI settings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Collection, Mapping


MENU_KEYS = (
    "menu.home",
    "menu.question_management",
    "menu.practice",
    "menu.export",
    "menu.import",
    "menu.question_bank_connections",
    "menu.codex",
    "menu.settings",
)

KOREAN_MENU_STRINGS = MappingProxyType(
    {
        "menu.home": "홈",
        "menu.question_management": "문제 관리",
        "menu.practice": "문제 풀이",
        "menu.export": "시험지 출력",
        "menu.import": "문제 가져오기",
        "menu.question_bank_connections": "문제은행 연결 관리",
        "menu.codex": "Codex",
        "menu.settings": "설정",
    }
)

ENGLISH_MENU_STRINGS = MappingProxyType(
    {
        "menu.home": "Home",
        "menu.question_management": "Question Management",
        "menu.practice": "Practice",
        "menu.export": "Export Exam",
        "menu.import": "Import Questions",
        "menu.question_bank_connections": "Question Bank Connections",
        "menu.codex": "Codex",
        "menu.settings": "Settings",
    }
)

_LOCALE_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*$")


@dataclass(frozen=True)
class MenuLanguagePack:
    locale: str
    display_name: str
    version: int
    strings: Mapping[str, str]


def _pack(locale: str, display_name: str, strings: Mapping[str, str]):
    return MenuLanguagePack(
        locale=locale,
        display_name=display_name,
        version=1,
        strings=MappingProxyType(dict(strings)),
    )


def _default_packs() -> dict[str, MenuLanguagePack]:
    return {
        "ko": _pack("ko", "한국어", KOREAN_MENU_STRINGS),
        "en": _pack("en", "English", ENGLISH_MENU_STRINGS),
    }


def menu_text(pack: MenuLanguagePack, key: str) -> str:
    """Return a validated menu string with a per-key Korean fallback."""
    value = pack.strings.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return KOREAN_MENU_STRINGS[key]


def _load_pack(path: Path) -> MenuLanguagePack:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("최상위 값은 객체여야 합니다")

    locale = payload.get("locale")
    display_name = payload.get("display_name")
    version = payload.get("version")
    strings = payload.get("strings")
    if not isinstance(locale, str) or not _LOCALE_PATTERN.fullmatch(locale):
        raise ValueError("locale 형식이 올바르지 않습니다")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("display_name이 비어 있습니다")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("version은 1 이상의 정수여야 합니다")
    if not isinstance(strings, dict):
        raise ValueError("strings는 객체여야 합니다")

    safe_strings = {
        key: value.strip()
        for key, value in strings.items()
        if key in MENU_KEYS and isinstance(value, str) and value.strip()
    }
    return MenuLanguagePack(
        locale=locale,
        display_name=display_name.strip(),
        version=version,
        strings=MappingProxyType(safe_strings),
    )


def discover_menu_language_packs(
    base_dir: str | Path,
) -> tuple[dict[str, MenuLanguagePack], list[str]]:
    """Discover bundled and user packs without allowing pack code execution."""
    base_path = Path(base_dir).resolve()
    packs = _default_packs()
    warnings: list[str] = []
    locations = (
        base_path / "assets" / "language_packs" / "menu",
        base_path / "data" / "language_packs" / "menu",
    )
    seen_paths: set[Path] = set()

    for directory in locations:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            resolved = path.resolve()
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            try:
                pack = _load_pack(path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                warnings.append(f"{path.name}: {exc}")
                continue
            packs[pack.locale] = pack

    return packs, warnings


def _settings_path(base_dir: str | Path) -> Path:
    return Path(base_dir).resolve() / "data" / "app_settings.json"


def load_menu_locale(
    base_dir: str | Path,
    available_locales: Collection[str],
) -> str:
    """Load a saved locale, returning Korean for missing or invalid settings."""
    available = set(available_locales)
    path = _settings_path(base_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "ko"
    if not isinstance(payload, dict):
        return "ko"
    locale = payload.get("menu_locale")
    return locale if isinstance(locale, str) and locale in available else "ko"


def save_menu_locale(
    base_dir: str | Path,
    locale: str,
    available_locales: Collection[str],
) -> Path:
    """Atomically persist a validated locale in the portable data directory."""
    if locale not in set(available_locales):
        raise ValueError(f"지원하지 않는 메뉴 언어입니다: {locale}")

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
    payload["menu_locale"] = locale

    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target

