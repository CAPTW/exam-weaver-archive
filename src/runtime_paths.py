"""Runtime paths shared by source and packaged executions."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional


FACTORY_DB_NAME = "seed_exam_bank.db"
USER_DB_NAME = "exam_bank.db"


def get_base_dir() -> Path:
    """Return the repo root in source mode and the exe folder in frozen mode."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_data_dir(base_dir: Optional[str | Path] = None) -> Path:
    return Path(base_dir).resolve() / "data" if base_dir else get_base_dir() / "data"


def get_factory_db_path(base_dir: Optional[str | Path] = None) -> Path:
    return get_data_dir(base_dir) / FACTORY_DB_NAME


def get_user_db_path(base_dir: Optional[str | Path] = None) -> Path:
    return get_data_dir(base_dir) / USER_DB_NAME


def ensure_user_database(base_dir: Optional[str | Path] = None) -> Path:
    """Create the writable user DB from the packaged factory DB when needed."""
    data_dir = get_data_dir(base_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    user_db = data_dir / USER_DB_NAME
    factory_db = data_dir / FACTORY_DB_NAME
    if not user_db.exists() and factory_db.exists():
        shutil.copy2(factory_db, user_db)
    return user_db


def get_clipboard_image_dir(base_dir: Optional[str | Path] = None) -> Path:
    return get_data_dir(base_dir) / "clipboard_images"
