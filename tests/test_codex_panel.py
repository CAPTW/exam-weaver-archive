import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.codex_panel import (
    CodexInterface,
    apply_hidden_codex_process_patch,
    prepare_panel_codex_home,
    progress_message_for_event_method,
)


APP = QApplication.instance() or QApplication([])


def test_codex_panel_defaults_to_read_only_and_denies_approval_requests(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)

    assert widget._selected_sandbox_mode() == "read-only"
    assert widget._selected_approval_mode() == "deny-all"
    assert widget.thread_id is None
    assert widget.side_panel is True
    assert widget.collapseButton.text() == "접기"
    assert widget.loginButton.text() == "로그인"

    widget.deleteLater()
    APP.processEvents()


def test_codex_panel_keeps_model_optional(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)

    assert widget._selected_model() == "gpt-5.3-codex-spark"
    assert widget._selected_model_supports_images() is False

    widget.modelCombo.setCurrentIndex(1)
    assert widget._selected_model() == "gpt-5.4-mini"
    assert widget._selected_model_supports_images() is True

    widget.deleteLater()
    APP.processEvents()


def test_codex_panel_tracks_attached_images(tmp_path):
    image = tmp_path / "question.png"
    image.write_bytes(b"fake")
    widget = CodexInterface(tmp_path, side_panel=True)

    widget._add_image_path(str(image))
    widget._add_image_path(str(image))

    assert widget.image_paths == [str(image.resolve())]
    assert "1" in widget.imageStatusLabel.text()

    widget.clear_images()
    assert widget.image_paths == []
    assert widget.imageStatusLabel.text() == "이미지 없음"

    widget.deleteLater()
    APP.processEvents()


def test_codex_panel_uses_compact_side_panel_controls(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)

    assert widget.attachImageButton.text() == "이미지"
    assert widget.pasteImageButton.text() == "붙여넣기"
    assert widget.attachImageButton.height() <= 32
    assert widget.sendButton.minimumWidth() >= 64
    assert widget.progressView.maximumHeight() <= 72

    widget.deleteLater()
    APP.processEvents()


def test_progress_messages_are_safe_status_updates():
    assert progress_message_for_event_method("item/agentMessage/delta") == "답변을 작성하고 있습니다."
    assert progress_message_for_event_method("item/reasoning/started") == "요청을 분석하고 있습니다."
    assert progress_message_for_event_method("turn/completed") is None


def test_prepare_panel_codex_home_writes_minimal_config_and_copies_auth(tmp_path):
    source_home = tmp_path / "source_codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text('{"auth_mode":"chatgpt"}', encoding="utf-8")

    panel_home = prepare_panel_codex_home(tmp_path / "project", source_home)

    assert panel_home == tmp_path / "project" / "data" / "codex_panel_home"
    assert (panel_home / "auth.json").read_text(encoding="utf-8") == '{"auth_mode":"chatgpt"}'
    config = (panel_home / "config.toml").read_text(encoding="utf-8")
    assert 'cli_auth_credentials_store = "file"' in config
    assert 'trust_level = "trusted"' in config
    assert "agents" not in config


def test_hidden_codex_process_patch_is_idempotent():
    apply_hidden_codex_process_patch()
    apply_hidden_codex_process_patch()
