import os
from types import MappingProxyType

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.choice_markers import CIRCLED_NUMBER_STYLE, LEGACY_KOREAN_STYLE
from src.gui.interface.settings import SettingsDialog
from src.gui.main import MENU_ROUTE_KEYS, apply_menu_pack
from src.gui.menu_language import MenuLanguagePack


APP = QApplication.instance() or QApplication([])


def _pack(locale, display_name, strings=None):
    return MenuLanguagePack(
        locale=locale,
        display_name=display_name,
        version=1,
        strings=MappingProxyType(strings or {}),
    )


class _NavigationItemStub:
    def __init__(self):
        self._text = ""

    def setText(self, text):
        self._text = text

    def text(self):
        return self._text


class _NavigationStub:
    def __init__(self, route_keys):
        self.items = {route_key: _NavigationItemStub() for route_key in route_keys}

    def widget(self, route_key):
        return self.items.get(route_key)


def test_settings_dialog_lists_packs_and_returns_selected_locale():
    dialog = SettingsDialog(
        packs={"ko": _pack("ko", "한국어"), "en": _pack("en", "English")},
        current_locale="ko",
        warnings=[],
    )

    assert [
        dialog.languageCombo.itemData(index)
        for index in range(dialog.languageCombo.count())
    ] == ["ko", "en"]
    dialog.languageCombo.setCurrentIndex(1)
    assert dialog.selected_locale() == "en"
    assert dialog.windowTitle() == "설정"

    dialog.deleteLater()
    APP.processEvents()


def test_settings_dialog_shows_pack_warning_without_disabling_selection():
    dialog = SettingsDialog(
        packs={"ko": _pack("ko", "한국어"), "en": _pack("en", "English")},
        current_locale="ko",
        warnings=["broken.json: JSON 오류"],
    )

    assert dialog.warningLabel.isVisibleTo(dialog)
    assert "broken.json" in dialog.warningLabel.text()
    assert dialog.applyButton.isEnabled()

    dialog.deleteLater()
    APP.processEvents()


def test_settings_dialog_lists_choice_marker_styles_and_returns_selection():
    dialog = SettingsDialog(
        packs={"ko": _pack("ko", "한국어"), "en": _pack("en", "English")},
        current_locale="ko",
        warnings=[],
        current_choice_marker_style=CIRCLED_NUMBER_STYLE,
    )

    assert [
        dialog.choiceMarkerCombo.itemData(index)
        for index in range(dialog.choiceMarkerCombo.count())
    ] == [LEGACY_KOREAN_STYLE, CIRCLED_NUMBER_STYLE]
    assert dialog.selected_choice_marker_style() == CIRCLED_NUMBER_STYLE
    assert "① ② ③ ④" in dialog.choiceMarkerCombo.currentText()

    dialog.choiceMarkerCombo.setCurrentIndex(0)
    assert dialog.selected_choice_marker_style() == LEGACY_KOREAN_STYLE

    dialog.deleteLater()
    APP.processEvents()


def test_apply_menu_pack_updates_existing_navigation_items_only():
    navigation = _NavigationStub(MENU_ROUTE_KEYS)
    english = _pack(
        "en",
        "English",
        {
            "menu.home": "Home",
            "menu.question_management": "Question Management",
            "menu.practice": "Practice",
            "menu.export": "Export Exam",
            "menu.import": "Import Questions",
            "menu.question_bank_connections": "Question Bank Connections",
            "menu.codex": "Codex",
            "menu.settings": "Settings",
        },
    )

    apply_menu_pack(navigation, english)

    assert navigation.widget("HomeInterface").text() == "Home"
    assert navigation.widget("DbMountInterface").text() == "Question Bank Connections"
    assert navigation.widget("CodexToggle").text() == "Codex"
    assert navigation.widget("Settings").text() == "Settings"

