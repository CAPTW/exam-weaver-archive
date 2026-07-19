from pathlib import Path

from src.gui import main as gui_main


class _MicaWindowStub:
    def __init__(self):
        self.enabled = True

    def setMicaEffectEnabled(self, enabled):
        self.enabled = enabled


def test_main_window_default_size_leaves_room_for_export_controls():
    assert gui_main.DEFAULT_WINDOW_SIZE[0] >= 1500
    assert gui_main.DEFAULT_WINDOW_SIZE[1] >= 860


def test_initial_window_size_respects_125_percent_work_area():
    assert gui_main.calculate_initial_window_size(
        gui_main.DEFAULT_WINDOW_SIZE,
        (1536, 826),
    ) == (1500, 794)


def test_initial_window_size_keeps_default_on_roomy_screen():
    assert gui_main.calculate_initial_window_size(
        gui_main.DEFAULT_WINDOW_SIZE,
        (1920, 1032),
    ) == gui_main.DEFAULT_WINDOW_SIZE


def test_app_title_is_declared_for_exam_bank_admin():
    assert gui_main.APP_TITLE == "기출문제 문제은행 관리자"


def test_app_icon_asset_is_declared_and_available():
    icon_path = Path(gui_main.get_app_icon_path())

    assert gui_main.APP_ICON_FILENAME == "exam_generator_icon.ico"
    assert gui_main.APP_USER_MODEL_ID == "CAPTW.ExamWeaverArchive.QuestionBankManager"
    assert icon_path.exists()
    assert icon_path.suffix == ".ico"
    assert icon_path.read_bytes()[:4] == b"\x00\x00\x01\x00"


def test_windows_taskbar_app_id_is_declared_before_qapplication():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)" in source
    assert source.index("_set_windows_app_user_model_id()") < source.index("QApplication(sys.argv)")


def test_codex_panel_is_attached_as_sidecar():
    assert hasattr(gui_main.MainWindow, "init_codex_sidecar")
    assert hasattr(gui_main.MainWindow, "toggle_codex_sidecar")
    assert hasattr(gui_main.MainWindow, "set_codex_sidecar_expanded")
    assert hasattr(gui_main.MainWindow, "activate_right_sidecar")
    assert hasattr(gui_main.MainWindow, "set_right_sidecar_page")
    assert hasattr(gui_main.MainWindow, "set_right_sidecar_section_expanded")
    assert hasattr(gui_main.MainWindow, "set_right_sidecar_expanded")


def test_explanation_and_codex_share_one_labelled_vertical_splitter():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "QSplitter" in source
    assert "Qt.Orientation.Vertical" in source
    assert 'external_explanation_host=True' in source
    assert 'self.explanation_sidecar_button = PushButton(' in source
    assert 'self.codex_toggle_button = PushButton("Codex"' in source
    assert 'self.right_sidecar_splitter.addWidget(self.explanation_sidecar_panel)' in source
    assert 'self.right_sidecar_splitter.addWidget(self.codex_interface)' in source
    assert 'self.right_sidecar_splitter.setChildrenCollapsible(False)' in source
    assert 'self.activate_right_sidecar("explanation")' in source


class _VisibilityStub:
    def __init__(self):
        self.visible = True

    def setVisible(self, visible):
        self.visible = bool(visible)


class _ButtonStub:
    def __init__(self):
        self.checked = False
        self.tooltip = ""

    def setChecked(self, checked):
        self.checked = bool(checked)

    def setToolTip(self, tooltip):
        self.tooltip = tooltip


class _SplitterStub(_VisibilityStub):
    def __init__(self):
        super().__init__()
        self.current_sizes = [0, 600]

    def sizes(self):
        return list(self.current_sizes)

    def height(self):
        return 800

    def setSizes(self, sizes):
        self.current_sizes = list(sizes)


class _ContainerStub:
    def __init__(self):
        self.maximum_width = None

    def setMaximumWidth(self, width):
        self.maximum_width = width


class _SidecarStateHarness:
    set_right_sidecar_section_expanded = (
        gui_main.MainWindow.set_right_sidecar_section_expanded
    )
    _sync_right_sidecar_state = gui_main.MainWindow._sync_right_sidecar_state
    _ensure_right_sidecar_split = gui_main.MainWindow._ensure_right_sidecar_split

    def __init__(self):
        self.right_sidecar_page = "codex"
        self.right_sidecar_sections = {"explanation": False, "codex": True}
        self.explanation_sidecar_panel = _VisibilityStub()
        self.codex_interface = _VisibilityStub()
        self.right_sidecar_splitter = _SplitterStub()
        self.explanation_sidecar_button = _ButtonStub()
        self.codex_toggle_button = _ButtonStub()
        self.codex_sidecar_container = _ContainerStub()


def test_explanation_and_codex_sections_can_be_expanded_together(monkeypatch):
    monkeypatch.setattr(gui_main.QTimer, "singleShot", lambda _delay, callback: callback())
    host = _SidecarStateHarness()

    host.set_right_sidecar_section_expanded("explanation", True)
    assert host.explanation_sidecar_panel.visible is True
    assert host.codex_interface.visible is True
    assert host.explanation_sidecar_button.checked is True
    assert host.codex_toggle_button.checked is True
    assert host.right_sidecar_expanded is True
    assert min(host.right_sidecar_splitter.current_sizes) > 0

    host.set_right_sidecar_section_expanded("codex", False)
    assert host.explanation_sidecar_panel.visible is True
    assert host.codex_interface.visible is False
    assert host.right_sidecar_expanded is True

    host.set_right_sidecar_section_expanded("explanation", False)
    assert host.right_sidecar_splitter.visible is False
    assert host.codex_sidecar_container.maximum_width == gui_main.RIGHT_SIDECAR_RAIL_WIDTH


def test_practice_interface_is_registered_in_main_window():
    assert "PracticeInterface" in gui_main.PracticeInterface.__name__


def test_main_window_passes_and_refreshes_question_repository_for_practice():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "self.practice_interface = PracticeInterface(" in source
    assert "repository=question_repository" in source
    assert "choice_marker_style=self.choice_marker_style" in source
    assert "self.practice_interface.set_repository(repository)" in source


def test_main_window_passes_and_refreshes_question_repository_for_export():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "self.export_interface = ExportInterface(" in source
    assert "repository=question_repository" in source
    assert "choice_marker_style=self.choice_marker_style" in source
    assert "self.export_interface.set_repository(repository)" in source


def test_main_window_declares_mock_exam_export_navigation_copy():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert 'self.export_interface, FIF.PRINT, "모의고사 출력"' in source


def test_codex_toggle_navigation_is_declared():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "CodexToggle" in source
    assert "codex_sidecar_container" in source
    assert "Codex 패널 펼치기" in source
    assert "기출문제 문제은행 관리자" in source


def test_opaque_background_fallback_disables_mica():
    window = _MicaWindowStub()

    gui_main.apply_opaque_background_fallback(window)

    assert window.enabled is False


def test_main_window_settings_action_loads_saves_and_applies_menu_locale():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "discover_menu_language_packs" in source
    assert "load_menu_locale" in source
    assert "save_menu_locale" in source
    assert "onClick=self.open_settings" in source
    assert "apply_menu_pack(self.navigationInterface" in source


def test_main_window_loads_and_applies_choice_marker_style_to_feature_interfaces():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "load_choice_marker_style" in source
    assert "save_choice_marker_style" in source
    assert "current_choice_marker_style=self.choice_marker_style" in source
    assert "self.browser_interface.set_choice_marker_style(style)" in source
    assert "self.practice_interface.set_choice_marker_style(style)" in source
    assert "self.export_interface.set_choice_marker_style(style)" in source


def test_main_window_applies_opaque_background_fallback_at_startup():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    constructor_start = source.index("class MainWindow(FluentWindow):")
    init_window_start = source.index("    def init_window(self):", constructor_start)
    constructor = source[constructor_start:init_window_start]

    assert "apply_opaque_background_fallback(self)" in constructor
