from src.gui import main as gui_main


def test_main_window_default_size_leaves_room_for_export_controls():
    assert gui_main.DEFAULT_WINDOW_SIZE[0] >= 1500
    assert gui_main.DEFAULT_WINDOW_SIZE[1] >= 860


def test_app_title_is_declared_for_exam_bank_admin():
    assert gui_main.APP_TITLE == "기출문제 문제은행 관리자"


def test_codex_panel_is_attached_as_sidecar():
    assert hasattr(gui_main.MainWindow, "init_codex_sidecar")
    assert hasattr(gui_main.MainWindow, "toggle_codex_sidecar")
    assert hasattr(gui_main.MainWindow, "set_codex_sidecar_expanded")


def test_practice_interface_is_registered_in_main_window():
    assert "PracticeInterface" in gui_main.PracticeInterface.__name__


def test_codex_toggle_navigation_is_declared():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert "CodexToggle" in source
    assert "codex_sidecar_container" in source
    assert "Codex 패널 펼치기" in source
    assert "기출문제 문제은행 관리자" in source
