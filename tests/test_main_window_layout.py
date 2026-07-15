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


def test_practice_interface_is_registered_in_main_window():
    assert "PracticeInterface" in gui_main.PracticeInterface.__name__


def test_main_window_passes_and_refreshes_question_repository_for_practice():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert (
        "PracticeInterface(self.db_path, self, repository=question_repository)"
        in source
    )
    assert "self.practice_interface.set_repository(repository)" in source


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


def test_main_window_applies_opaque_background_fallback_at_startup():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    constructor_start = source.index("class MainWindow(FluentWindow):")
    init_window_start = source.index("    def init_window(self):", constructor_start)
    constructor = source[constructor_start:init_window_start]

    assert "apply_opaque_background_fallback(self)" in constructor
