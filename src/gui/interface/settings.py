"""Small Korean settings dialog for menu-only language selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from ..menu_language import MenuLanguagePack


class SettingsDialog(QDialog):
    def __init__(
        self,
        packs: Mapping[str, MenuLanguagePack],
        current_locale: str,
        warnings: Sequence[str],
        parent=None,
    ):
        super().__init__(parent)
        self.packs = dict(packs)
        self.setWindowTitle("설정")
        self.setMinimumWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(SubtitleLabel("설정", self))
        layout.addWidget(BodyLabel("메인 메뉴에 사용할 언어를 선택하세요.", self))

        self.languageLabel = BodyLabel("메뉴 언어", self)
        self.languageCombo = ComboBox(self)
        ordered_locales = [
            locale for locale in ("ko", "en") if locale in self.packs
        ]
        ordered_locales.extend(
            sorted(
                (locale for locale in self.packs if locale not in {"ko", "en"}),
                key=lambda locale: self.packs[locale].display_name.casefold(),
            )
        )
        for locale in ordered_locales:
            pack = self.packs[locale]
            self.languageCombo.addItem(pack.display_name, userData=locale)
        current_index = self.languageCombo.findData(current_locale)
        self.languageCombo.setCurrentIndex(max(current_index, 0))
        layout.addWidget(self.languageLabel)
        layout.addWidget(self.languageCombo)

        warning_text = "\n".join(str(warning) for warning in warnings if warning)
        self.warningLabel = BodyLabel(
            f"일부 언어 팩을 불러오지 못했습니다.\n{warning_text}" if warning_text else "",
            self,
        )
        self.warningLabel.setWordWrap(True)
        self.warningLabel.setVisible(bool(warning_text))
        if warning_text:
            self.warningLabel.setStyleSheet("color: #b85c00;")
        layout.addWidget(self.warningLabel)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.cancelButton = PushButton("취소", self)
        self.applyButton = PrimaryPushButton("적용", self)
        self.cancelButton.clicked.connect(self.reject)
        self.applyButton.clicked.connect(self.accept)
        button_layout.addWidget(self.cancelButton)
        button_layout.addWidget(self.applyButton)
        layout.addLayout(button_layout)

        self.setTabOrder(self.languageCombo, self.cancelButton)
        self.setTabOrder(self.cancelButton, self.applyButton)
        self.languageCombo.setFocus(Qt.FocusReason.OtherFocusReason)

    def selected_locale(self) -> str:
        return str(self.languageCombo.currentData() or "ko")
