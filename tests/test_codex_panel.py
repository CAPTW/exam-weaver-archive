import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("EXAM_GENERATOR_DISABLE_WEBENGINE", "1")

from PyQt5.QtWidgets import QApplication

from src.gui.interface.codex_panel import (
    CodexInterface,
    ERROR_BLOCK_TITLE,
    SYSTEM_BLOCK_TITLE,
    USER_BLOCK_TITLE,
    apply_hidden_codex_process_patch,
    find_mathjax_script_path,
    mathjax_script_url,
    prepare_panel_codex_home,
    progress_message_for_event_method,
    render_codex_chat_html,
    render_codex_inline_html,
    render_codex_text_to_html,
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
    assert widget.newThreadButton.text() == "새 작업"

    widget.deleteLater()
    APP.processEvents()


def test_codex_panel_uses_korean_user_system_and_error_titles(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)

    widget._append_block(USER_BLOCK_TITLE, "질문")
    widget._append_block(SYSTEM_BLOCK_TITLE, "상태")
    widget._append_block(ERROR_BLOCK_TITLE, "실패")

    assert [block["title"] for block in widget._chat_blocks[-3:]] == [
        "사용자",
        "시스템",
        "오류",
    ]

    widget.deleteLater()
    APP.processEvents()


def test_full_codex_panel_labels_model_in_korean(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=False)

    assert widget.modelLabel.text() == "모델"

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


def test_codex_renderer_formats_math_symbols_and_code():
    html = render_codex_text_to_html(
        r"식은 \(V=\frac{IR}{2}\), \sqrt{GM}, \overline{AB}, \theta \leq 30^\circ 입니다."
    )

    assert "math-inline" in html
    assert "&frasl;" in html
    assert "√" in html
    assert "text-decoration: overline" in html
    assert "θ" in html
    assert "≤" in html
    assert "°" in html

    inline = render_codex_inline_html(r"`<tag>` and \(x<y\)")
    assert "<code>&lt;tag&gt;</code>" in inline
    assert "x&lt;y" in inline


def test_codex_renderer_builds_mathjax_document_and_preserves_safe_formula_html(tmp_path):
    script = tmp_path / "assets" / "mathjax" / "tex-mml-svg.js"
    script.parent.mkdir(parents=True)
    script.write_text("// mathjax", encoding="utf-8")

    assert find_mathjax_script_path(tmp_path) == script
    assert mathjax_script_url(tmp_path).startswith("file:///")

    document = render_codex_chat_html(
        [
            {
                "title": "Codex",
                "text": r"H<sub>2</sub>O, \(x^2 + y^2\), <script>alert(1)</script>",
            }
        ],
        math_mode="mathjax",
        mathjax_script_url=mathjax_script_url(tmp_path),
    )

    assert "MathJax-script" in document
    assert r"\(x^2 + y^2\)" in document
    assert "H<sub>2</sub>O" in document
    assert "<script>alert(1)</script>" not in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document


def test_codex_renderer_wraps_raw_latex_commands_for_mathjax():
    html = render_codex_text_to_html(
        r"\sqrt{GM}, \frac{1}{2}, \theta",
        math_mode="mathjax",
    )

    assert r"\(\sqrt{GM}\)" in html
    assert r"\(\frac{1}{2}\)" in html
    assert r"\(\theta\)" in html


def test_codex_panel_rerenders_split_streaming_math_delta(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)

    widget._append_block("Codex")
    widget._append_answer_delta(r"계산식: \sqrt")
    widget._append_answer_delta(r"{2} + \frac{1}{3}")

    plain_text = widget.chatView.toPlainText()
    assert "√2" in plain_text
    assert "1⁄3" in plain_text or "1/3" in plain_text

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
