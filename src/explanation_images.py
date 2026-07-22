"""Managed file lifecycle for question explanation images."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PyQt5.QtGui import QImage

from .runtime_paths import (
    get_base_dir,
    get_explanation_image_candidate_dir,
    get_explanation_image_dir,
)


@dataclass(frozen=True)
class ExplanationImageChange:
    action: Literal["keep", "remove", "replace"]
    source_path: str | None = None

    @classmethod
    def keep(cls) -> "ExplanationImageChange":
        return cls("keep")

    @classmethod
    def remove(cls) -> "ExplanationImageChange":
        return cls("remove")

    @classmethod
    def replace(cls, source_path: str | Path) -> "ExplanationImageChange":
        path = str(source_path or "").strip()
        if not path:
            raise ValueError("교체할 해설 이미지 경로가 필요합니다.")
        return cls("replace", path)


class ExplanationImageStore:
    allowed_suffixes = {".png", ".jpg", ".jpeg"}

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = (
            Path(base_dir).resolve() if base_dir is not None else get_base_dir().resolve()
        )
        self.image_dir = get_explanation_image_dir(self.base_dir).resolve()
        self.candidate_dir = get_explanation_image_candidate_dir().resolve()

    def resolve(self, stored_path: str | Path) -> Path:
        path = Path(str(stored_path or ""))
        if path.is_absolute():
            return path.resolve()
        return (self.base_dir / path).resolve()

    def validate_source(self, source_path: str | Path) -> Path:
        path = Path(source_path).resolve()
        if path.suffix.lower() not in self.allowed_suffixes:
            raise ValueError("해설 이미지는 PNG, JPG, JPEG만 사용할 수 있습니다.")
        if not path.is_file() or QImage(str(path)).isNull():
            raise ValueError("읽을 수 없는 이미지 파일입니다.")
        return path

    def import_file(self, source_path: str | Path) -> str:
        source = self.validate_source(source_path)
        self.image_dir.mkdir(parents=True, exist_ok=True)
        target = self.image_dir / f"{uuid.uuid4().hex}{source.suffix.lower()}"
        shutil.copy2(source, target)
        return target.relative_to(self.base_dir).as_posix()

    def save_clipboard_candidate(self, image: QImage) -> str:
        if image is None or image.isNull():
            raise ValueError("클립보드에 이미지가 없습니다.")
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        target = self.candidate_dir / f"{uuid.uuid4().hex}.png"
        if not image.save(str(target), "PNG"):
            raise OSError("클립보드 이미지를 임시 파일로 저장하지 못했습니다.")
        return str(target)

    @staticmethod
    def _is_within(path: Path, directory: Path) -> bool:
        try:
            path.resolve().relative_to(directory.resolve())
            return True
        except ValueError:
            return False

    def is_managed(self, stored_path: str | Path) -> bool:
        return self._is_within(self.resolve(stored_path), self.image_dir)

    def remove_managed(self, stored_path: str | Path) -> bool:
        path = self.resolve(stored_path)
        if not self._is_within(path, self.image_dir):
            return False
        path.unlink(missing_ok=True)
        return True

    def discard_candidate(self, candidate_path: str | Path) -> bool:
        path = Path(candidate_path).resolve()
        if not self._is_within(path, self.candidate_dir):
            return False
        path.unlink(missing_ok=True)
        return True
