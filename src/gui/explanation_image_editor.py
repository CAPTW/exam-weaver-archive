"""Reusable single-image editor for question explanations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ImageLabel, PushButton

from ..explanation_images import ExplanationImageChange, ExplanationImageStore


class ExplanationImageEditor(QWidget):
    def __init__(
        self,
        parent=None,
        image_store: ExplanationImageStore | None = None,
    ):
        super().__init__(parent)
        self.store = image_store or ExplanationImageStore()
        self._attachment: dict[str, Any] | None = None
        self._candidate_path: str | None = None
        self._candidate_is_temporary = False
        self._action = "keep"

        self.preview = ImageLabel(self)
        self.preview.setScaledContents(True)
        self.preview.setBorderRadius(6, 6, 6, 6)
        self.preview.setVisible(False)
        self.preview.setFixedSize(0, 0)

        self.statusLabel = BodyLabel("이미지 없음", self)
        self.statusLabel.setWordWrap(True)

        self.selectButton = PushButton("이미지 선택", self)
        self.pasteButton = PushButton("붙여넣기", self)
        self.removeButton = PushButton("삭제", self)
        self.removeButton.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)
        button_layout.addWidget(self.selectButton)
        button_layout.addWidget(self.pasteButton)
        button_layout.addWidget(self.removeButton)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.statusLabel)
        layout.addLayout(button_layout)

        self.selectButton.clicked.connect(self.select_image)
        self.pasteButton.clicked.connect(self.paste_image)
        self.removeButton.clicked.connect(self.remove_image)

    def set_image_store(self, image_store: ExplanationImageStore | None) -> None:
        self.discard_pending()
        self._attachment = None
        self.store = image_store or ExplanationImageStore()
        self._show_saved_attachment()

    def set_attachment(self, attachment: Mapping[str, Any] | None) -> None:
        self.discard_pending()
        self._attachment = dict(attachment) if attachment else None
        self._action = "keep"
        self._show_saved_attachment()

    def set_candidate(
        self,
        source_path: str | Path,
        *,
        temporary: bool = False,
    ) -> None:
        source = self.store.validate_source(source_path)
        self._discard_temporary_candidate()
        self._candidate_path = str(source)
        self._candidate_is_temporary = bool(temporary)
        self._action = "replace"
        self._show_image(source, source.name)

    def image_change(self, force_copy: bool = False) -> ExplanationImageChange:
        if self._action == "replace" and self._candidate_path:
            return ExplanationImageChange.replace(self._candidate_path)
        if self._action == "remove":
            return ExplanationImageChange.remove()
        if force_copy and self._attachment:
            path = self.store.resolve(self._attachment.get("image_path"))
            if path.is_file() and not QImage(str(path)).isNull():
                return ExplanationImageChange.replace(path)
        return ExplanationImageChange.keep()

    def select_image(self, _checked=False) -> None:
        source_path, _ = QFileDialog.getOpenFileName(
            self,
            "해설 이미지 선택",
            "",
            "Images (*.png *.jpg *.jpeg)",
        )
        if not source_path:
            return
        try:
            self.set_candidate(source_path)
        except (OSError, ValueError) as exc:
            self.statusLabel.setText(str(exc))

    def paste_image(self, _checked=False) -> None:
        image = self._clipboard_image()
        if image is None or image.isNull():
            self.statusLabel.setText("클립보드에 이미지가 없습니다.")
            return
        try:
            candidate_path = self.store.save_clipboard_candidate(image)
            self.set_candidate(candidate_path, temporary=True)
        except (OSError, ValueError) as exc:
            self.statusLabel.setText(str(exc))

    def remove_image(self, _checked=False) -> None:
        had_image = bool(self._attachment or self._candidate_path)
        self._discard_temporary_candidate()
        self._candidate_path = None
        self._candidate_is_temporary = False
        self._action = "remove"
        self._hide_preview()
        self.statusLabel.setText("이미지 삭제 예정" if had_image else "이미지 없음")
        self.removeButton.setEnabled(False)

    def discard_pending(self) -> None:
        self._discard_temporary_candidate()
        self._candidate_path = None
        self._candidate_is_temporary = False
        self._action = "keep"
        if hasattr(self, "preview"):
            self._show_saved_attachment()

    def _discard_temporary_candidate(self) -> None:
        if self._candidate_is_temporary and self._candidate_path:
            self.store.discard_candidate(self._candidate_path)

    def _clipboard_image(self) -> QImage:
        clipboard = QApplication.clipboard()
        return clipboard.image() if clipboard is not None else QImage()

    def _show_saved_attachment(self) -> None:
        if not self._attachment:
            self._hide_preview()
            self.statusLabel.setText("이미지 없음")
            self.removeButton.setEnabled(False)
            return

        path = self.store.resolve(self._attachment.get("image_path"))
        if not path.is_file():
            self._hide_preview()
            self.statusLabel.setText("이미지 파일 없음")
            self.removeButton.setEnabled(True)
            return
        if QImage(str(path)).isNull():
            self._hide_preview()
            self.statusLabel.setText("이미지를 읽을 수 없음")
            self.removeButton.setEnabled(True)
            return
        self._show_image(path, path.name)

    def _show_image(self, path: Path, status: str) -> None:
        image = QImage(str(path))
        size = image.size().scaled(
            300,
            180,
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self.preview.setImage(str(path))
        self.preview.setFixedSize(size)
        self.preview.setVisible(True)
        self.statusLabel.setText(status)
        self.removeButton.setEnabled(True)

    def _hide_preview(self) -> None:
        self.preview.setVisible(False)
        self.preview.setFixedSize(0, 0)
