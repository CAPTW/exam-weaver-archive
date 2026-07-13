from __future__ import annotations

import html
import os
import re
import shutil
import sys
import traceback
import uuid
import webbrowser
from pathlib import Path

from PyQt5.QtCore import Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)


CODEX_PANEL_INSTRUCTIONS = """
You are running inside the Exam Generator desktop app as an embedded Codex panel.
The working directory is this branched project copy. Keep answers concise and
ask before making broad changes unless the user explicitly requests edits.
Use Unicode symbols where they improve readability. For mathematical expressions,
prefer LaTeX delimiters such as \\( ... \\), \\[ ... \\], or $$ ... $$ so the app can
render formulas cleanly in the side panel.
""".strip()


SIDE_PANEL_FONT_POINT_SIZE = 9
SIDE_PANEL_BUTTON_HEIGHT = 30
SIDE_PANEL_PROMPT_MIN_HEIGHT = 84
SIDE_PANEL_PROMPT_MAX_HEIGHT = 118
PROGRESS_MESSAGES = [
    "요청을 분석하고 있습니다.",
    "프로젝트 문맥을 확인하고 있습니다.",
    "응답 이벤트를 기다리고 있습니다.",
]
CODEX_TEXT_FONT_FAMILY = '"Malgun Gothic", "Segoe UI", "Apple SD Gothic Neo", sans-serif'
CODEX_MATH_FONT_FAMILY = (
    '"Cambria Math", "STIX Two Math", "Segoe UI Symbol", '
    '"Noto Sans Math", "Malgun Gothic", serif'
)
CODEX_MONOSPACE_FONT_FAMILY = '"Cascadia Mono", Consolas, "D2Coding", monospace'
CODEX_CHAT_STYLES = f"""
body {{
    font-family: {CODEX_TEXT_FONT_FAMILY};
    font-size: 12px;
    line-height: 1.42;
    color: #222;
}}
.codex-message {{
    margin-bottom: 12px;
}}
.codex-title {{
    font-weight: 700;
    color: #2f5f8f;
    margin-bottom: 4px;
}}
.codex-body div {{
    margin: 2px 0;
}}
.math-inline {{
    font-family: {CODEX_MATH_FONT_FAMILY};
    background: #f5f7fb;
    border: 1px solid #e5e9f2;
    border-radius: 4px;
    padding: 1px 4px;
    white-space: nowrap;
}}
.math-display {{
    display: block;
    font-family: {CODEX_MATH_FONT_FAMILY};
    background: #f5f7fb;
    border: 1px solid #e5e9f2;
    border-radius: 5px;
    margin: 6px 0;
    padding: 6px 8px;
    text-align: center;
    font-size: 13px;
}}
.math-frac sup {{
    font-size: 80%;
    vertical-align: super;
}}
.math-frac sub {{
    font-size: 80%;
    vertical-align: sub;
}}
code {{
    font-family: {CODEX_MONOSPACE_FONT_FAMILY};
    background: #f4f4f4;
    border-radius: 3px;
    padding: 1px 3px;
}}
pre {{
    font-family: {CODEX_MONOSPACE_FONT_FAMILY};
    background: #f4f4f4;
    border: 1px solid #e1e1e1;
    border-radius: 5px;
    padding: 7px;
    white-space: pre-wrap;
}}
"""
LATEX_COMMAND_REPLACEMENTS = {
    r"\alpha": "α",
    r"\beta": "β",
    r"\gamma": "γ",
    r"\delta": "δ",
    r"\epsilon": "ε",
    r"\varepsilon": "ε",
    r"\zeta": "ζ",
    r"\eta": "η",
    r"\theta": "θ",
    r"\vartheta": "ϑ",
    r"\lambda": "λ",
    r"\mu": "μ",
    r"\nu": "ν",
    r"\xi": "ξ",
    r"\pi": "π",
    r"\rho": "ρ",
    r"\sigma": "σ",
    r"\tau": "τ",
    r"\phi": "φ",
    r"\varphi": "φ",
    r"\omega": "ω",
    r"\Delta": "Δ",
    r"\Theta": "Θ",
    r"\Lambda": "Λ",
    r"\Pi": "Π",
    r"\Sigma": "Σ",
    r"\Phi": "Φ",
    r"\Omega": "Ω",
    r"\times": "×",
    r"\cdot": "·",
    r"\div": "÷",
    r"\pm": "±",
    r"\mp": "∓",
    r"\le": "≤",
    r"\leq": "≤",
    r"\ge": "≥",
    r"\geq": "≥",
    r"\ne": "≠",
    r"\neq": "≠",
    r"\approx": "≈",
    r"\simeq": "≃",
    r"\propto": "∝",
    r"\infty": "∞",
    r"\therefore": "∴",
    r"\because": "∵",
    r"\degree": "°",
    r"\circ": "°",
    r"\sin": "sin",
    r"\cos": "cos",
    r"\tan": "tan",
    r"\log": "log",
    r"\ln": "ln",
    r"\min": "min",
    r"\max": "max",
}
LATEX_SPACE_COMMANDS = {r"\,", r"\;", r"\:", r"\quad", r"\qquad"}
DISPLAY_MATH_PATTERNS = (
    (r"\[", r"\]"),
    ("$$", "$$"),
)
MATHJAX_FILENAME = "tex-mml-svg.js"
MATHJAX_RELATIVE_PATH = ("assets", "mathjax", MATHJAX_FILENAME)
SAFE_HTML_TAGS = {
    "b",
    "br",
    "code",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "i",
    "li",
    "math",
    "mfrac",
    "mi",
    "mn",
    "mo",
    "mover",
    "mroot",
    "mrow",
    "msqrt",
    "msub",
    "msubsup",
    "msup",
    "mtext",
    "ol",
    "p",
    "semantics",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
SAFE_SELF_CLOSING_TAGS = {"br"}


def progress_message_for_event_method(method: str) -> str | None:
    method_lower = method.lower()
    if method == "item/agentMessage/delta":
        return "답변을 작성하고 있습니다."
    if "reasoning" in method_lower:
        return "요청을 분석하고 있습니다."
    if "exec" in method_lower or "command" in method_lower:
        return "명령 실행 상태를 확인하고 있습니다."
    if "patch" in method_lower or "file" in method_lower:
        return "파일 변경 이벤트를 확인하고 있습니다."
    if method.startswith("turn/") and method != "turn/completed":
        return "Codex 턴을 진행하고 있습니다."
    return None


def render_codex_chat_html(
    blocks: list[dict[str, str]],
    math_mode: str = "fallback",
    mathjax_script_url: str | None = None,
) -> str:
    messages = []
    for block in blocks:
        title = html.escape(block.get("title", ""), quote=False)
        body = render_codex_text_to_html(block.get("text", ""), math_mode=math_mode)
        messages.append(
            "\n".join(
                [
                    '<div class="codex-message">',
                    f'<div class="codex-title">{title}</div>',
                    f'<div class="codex-body">{body}</div>',
                    "</div>",
                ]
            )
        )
    body_html = "\n".join(messages)
    mathjax_head = ""
    if math_mode == "mathjax" and mathjax_script_url:
        script_url = html.escape(mathjax_script_url, quote=True)
        mathjax_head = f"""
<script>
window.MathJax = {{
  tex: {{
    inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
    displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
    processEscapes: true,
    processEnvironments: true
  }},
  options: {{
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
  }},
  svg: {{
    fontCache: 'local'
  }}
}};
</script>
<script id="MathJax-script" defer src="{script_url}"></script>
"""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{CODEX_CHAT_STYLES}</style>"
        f"{mathjax_head}"
        f"</head><body>{body_html}</body></html>"
    )


def render_codex_text_to_html(text: str, math_mode: str = "fallback") -> str:
    if not text:
        return ""

    lines = str(text).splitlines()
    rendered: list[str] = []
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            code_lines = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            code_html = html.escape("\n".join(code_lines), quote=False)
            rendered.append(f"<pre>{code_html}</pre>")
            continue

        display_math = _extract_display_math_line(stripped)
        if display_math is not None:
            if math_mode == "mathjax":
                rendered.append(f'<div class="mathjax-display">{html.escape(stripped, quote=False)}</div>')
            else:
                rendered.append(render_codex_math_html(display_math, display=True))
            index += 1
            continue

        if not stripped:
            rendered.append("<div><br /></div>")
            index += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            size = {1: 16, 2: 14, 3: 13}[level]
            rendered.append(
                f'<div style="font-weight:700; font-size:{size}px;">'
                f"{render_codex_inline_html(heading.group(2), math_mode=math_mode)}</div>"
            )
            index += 1
            continue

        bullet = re.match(r"^\s*[-*]\s+(.+)$", raw_line)
        if bullet:
            rendered.append(f"<div>• {render_codex_inline_html(bullet.group(1), math_mode=math_mode)}</div>")
            index += 1
            continue

        numbered = re.match(r"^\s*(\d+[.)])\s+(.+)$", raw_line)
        if numbered:
            rendered.append(
                f"<div>{html.escape(numbered.group(1), quote=False)} "
                f"{render_codex_inline_html(numbered.group(2), math_mode=math_mode)}</div>"
            )
            index += 1
            continue

        rendered.append(f"<div>{render_codex_inline_html(raw_line, math_mode=math_mode)}</div>")
        index += 1

    return "\n".join(rendered)


def render_codex_inline_html(text: str, math_mode: str = "fallback") -> str:
    value = str(text)
    parts: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "`":
            end = value.find("`", index + 1)
            if end != -1:
                code = html.escape(value[index + 1:end], quote=False)
                parts.append(f"<code>{code}</code>")
                index = end + 1
                continue

        math_span = _extract_inline_math_span(value, index)
        if math_span is not None:
            expression, end = math_span
            if math_mode == "mathjax":
                if _is_delimited_math_expression(expression):
                    parts.append(html.escape(expression, quote=False))
                else:
                    parts.append(r"\(" + html.escape(expression, quote=False) + r"\)")
            else:
                parts.append(render_codex_math_html(expression, display=False))
            index = end
            continue

        next_index = _next_inline_special_index(value, index + 1)
        if next_index == -1:
            next_index = len(value)
        if next_index <= index:
            next_index = index + 1
        parts.append(_escape_preserving_safe_html(value[index:next_index]))
        index = next_index

    return "".join(parts)


def render_codex_math_html(expression: str, display: bool = False) -> str:
    normalized = _strip_math_delimiters(str(expression or "").strip())
    class_name = "math-display" if display else "math-inline"
    return f'<span class="{class_name}">{_render_latex_math_inner(normalized)}</span>'


def _extract_display_math_line(line: str) -> str | None:
    for opener, closer in DISPLAY_MATH_PATTERNS:
        if line.startswith(opener) and line.endswith(closer) and len(line) > len(opener) + len(closer):
            return line[len(opener):-len(closer)]
    return None


def _is_delimited_math_expression(expression: str) -> bool:
    expression = str(expression or "").strip()
    return any(
        expression.startswith(opener) and expression.endswith(closer)
        for opener, closer in ((r"\(", r"\)"), (r"\[", r"\]"), ("$$", "$$"), ("$", "$"))
    )


def _extract_inline_math_span(text: str, start: int) -> tuple[str, int] | None:
    delimited_pairs = ((r"\(", r"\)"), (r"\[", r"\]"), ("$$", "$$"))
    for opener, closer in delimited_pairs:
        if text.startswith(opener, start):
            end = text.find(closer, start + len(opener))
            if end != -1:
                return text[start:end + len(closer)], end + len(closer)

    if text[start] == "$" and not text.startswith("$$", start):
        end = text.find("$", start + 1)
        if end != -1 and text[start + 1:end].strip():
            return text[start:end + 1], end + 1

    for command in (r"\sqrt", r"\frac", r"\overline", r"\bar"):
        if text.startswith(command, start):
            end = _latex_command_span_end(text, start)
            if end is not None:
                return text[start:end], end

    if text[start] == "\\":
        command, end = _read_latex_command(text, start)
        if command in LATEX_COMMAND_REPLACEMENTS:
            return command, end
    return None


def _next_inline_special_index(text: str, start: int) -> int:
    candidates = [
        text.find(token, start)
        for token in ("`", "\\", "$$", "$")
    ]
    candidates = [index for index in candidates if index != -1]
    return min(candidates) if candidates else -1


def _latex_command_span_end(text: str, start: int) -> int | None:
    if text.startswith(r"\frac", start):
        index = _skip_spaces(text, start + len(r"\frac"))
        first, index = _read_latex_group(text, index)
        index = _skip_spaces(text, index)
        second, index = _read_latex_group(text, index)
        return index if first and second else None

    for command in (r"\sqrt", r"\overline", r"\bar"):
        if text.startswith(command, start):
            index = _skip_spaces(text, start + len(command))
            if command == r"\sqrt" and index < len(text) and text[index] == "[":
                _, index = _read_delimited_group(text, index, "[", "]")
                index = _skip_spaces(text, index)
            group, index = _read_latex_group(text, index)
            return index if group else None
    return None


def _strip_math_delimiters(expression: str) -> str:
    pairs = ((r"\(", r"\)"), (r"\[", r"\]"), ("$$", "$$"), ("$", "$"))
    for opener, closer in pairs:
        if expression.startswith(opener) and expression.endswith(closer):
            return expression[len(opener):-len(closer)].strip()
    return expression


def _render_latex_math_inner(expression: str) -> str:
    value = expression.replace(r"\left", "").replace(r"\right", "")
    parts: list[str] = []
    index = 0
    while index < len(value):
        if value.startswith(r"\frac", index):
            next_index = _skip_spaces(value, index + len(r"\frac"))
            numerator, next_index = _read_latex_group(value, next_index)
            next_index = _skip_spaces(value, next_index)
            denominator, next_index = _read_latex_group(value, next_index)
            if numerator and denominator:
                parts.append(
                    '<span class="math-frac">'
                    f"<sup>{_render_latex_math_inner(numerator)}</sup>"
                    "&frasl;"
                    f"<sub>{_render_latex_math_inner(denominator)}</sub>"
                    "</span>"
                )
                index = next_index
                continue

        if value.startswith(r"\sqrt", index):
            next_index = _skip_spaces(value, index + len(r"\sqrt"))
            root = None
            if next_index < len(value) and value[next_index] == "[":
                root, next_index = _read_delimited_group(value, next_index, "[", "]")
                next_index = _skip_spaces(value, next_index)
            inner, next_index = _read_latex_group(value, next_index)
            if inner:
                root_html = f"<sup>{_render_latex_math_inner(root)}</sup>" if root else ""
                parts.append(f'{root_html}√<span class="math-radicand">{_render_latex_math_inner(inner)}</span>')
                index = next_index
                continue

        for command in (r"\overline", r"\bar"):
            if value.startswith(command, index):
                next_index = _skip_spaces(value, index + len(command))
                inner, next_index = _read_latex_group(value, next_index)
                if inner:
                    parts.append(
                        '<span style="text-decoration: overline;">'
                        f"{_render_latex_math_inner(inner)}</span>"
                    )
                    index = next_index
                    break
        else:
            if value[index] in ("^", "_"):
                tag = "sup" if value[index] == "^" else "sub"
                inner, next_index = _read_latex_group(value, index + 1)
                if inner:
                    parts.append(f"<{tag}>{_render_latex_math_inner(inner)}</{tag}>")
                    index = next_index
                    continue

            if value[index] == "\\":
                command, next_index = _read_latex_command(value, index)
                if command in LATEX_SPACE_COMMANDS:
                    parts.append(" ")
                elif command in LATEX_COMMAND_REPLACEMENTS:
                    parts.append(html.escape(LATEX_COMMAND_REPLACEMENTS[command], quote=False))
                elif len(command) > 1:
                    parts.append(html.escape(command[1:], quote=False))
                else:
                    parts.append("\\")
                index = next_index
                continue

            parts.append(html.escape(value[index], quote=False))
            index += 1
            continue
        continue

    return "".join(parts)


def _read_latex_command(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "\\":
        return "", start
    index = start + 1
    while index < len(text) and text[index].isalpha():
        index += 1
    if index == start + 1 and index < len(text):
        index += 1
    return text[start:index], index


def _read_latex_group(text: str, start: int) -> tuple[str, int]:
    if start >= len(text):
        return "", start
    if text[start] == "{":
        return _read_delimited_group(text, start, "{", "}")
    if text[start] == "\\":
        command, index = _read_latex_command(text, start)
        return command, index
    return text[start], start + 1


def _read_delimited_group(text: str, start: int, opener: str, closer: str) -> tuple[str, int]:
    if start >= len(text) or text[start] != opener:
        return "", start
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return text[start + 1:], len(text)


def _skip_spaces(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _escape_preserving_safe_html(text: str) -> str:
    if "<" not in text or ">" not in text:
        return html.escape(text, quote=False)

    output: list[str] = []
    last = 0
    tag_pattern = re.compile(r"<\s*(/?)\s*([a-zA-Z][\w:-]*)\b[^>]*?(/?)\s*>")
    for match in tag_pattern.finditer(text):
        output.append(html.escape(text[last:match.start()], quote=False))
        tag_name = match.group(2).lower()
        if tag_name in SAFE_HTML_TAGS:
            is_closing = bool(match.group(1))
            is_self_closing = bool(match.group(3)) or tag_name in SAFE_SELF_CLOSING_TAGS
            if is_closing:
                output.append(f"</{tag_name}>")
            elif is_self_closing:
                output.append(f"<{tag_name} />")
            else:
                output.append(f"<{tag_name}>")
        else:
            output.append(html.escape(match.group(0), quote=False))
        last = match.end()
    output.append(html.escape(text[last:], quote=False))
    return "".join(output)


def find_mathjax_script_path(base_dir: str | Path | None = None) -> Path | None:
    roots = []
    if base_dir:
        roots.append(Path(base_dir).resolve())
    roots.append(Path(getattr(sys, "_MEIPASS", Path.cwd())).resolve())
    roots.append(Path(__file__).resolve().parents[3])

    for root in roots:
        path = root.joinpath(*MATHJAX_RELATIVE_PATH)
        if path.exists():
            return path
    return None


def mathjax_script_url(base_dir: str | Path | None = None) -> str | None:
    script_path = find_mathjax_script_path(base_dir)
    return script_path.as_uri() if script_path else None


def should_use_webengine_chat_view() -> bool:
    return os.environ.get("EXAM_GENERATOR_DISABLE_WEBENGINE", "").lower() not in {
        "1",
        "true",
        "yes",
    }


QWEBENGINE_IMPORT_ERROR: Exception | None = None
QWebEngineSettings = None
QWebEngineView = None
if should_use_webengine_chat_view():
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView
    except Exception as exc:  # noqa: BLE001 - fallback to QTextEdit
        QWEBENGINE_IMPORT_ERROR = exc


def prepare_panel_codex_home(
    base_dir: str | Path,
    source_codex_home: str | Path | None = None,
) -> Path:
    base_path = Path(base_dir).resolve()
    panel_home = base_path / "data" / "codex_panel_home"
    panel_home.mkdir(parents=True, exist_ok=True)

    source_home = Path(source_codex_home).resolve() if source_codex_home else Path.home() / ".codex"
    source_auth = source_home / "auth.json"
    panel_auth = panel_home / "auth.json"
    if source_auth.exists() and (
        not panel_auth.exists()
        or source_auth.stat().st_mtime > panel_auth.stat().st_mtime
    ):
        shutil.copy2(source_auth, panel_auth)

    project_key = str(base_path).replace("\\", "\\\\").replace('"', '\\"')
    config_path = panel_home / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'cli_auth_credentials_store = "file"',
                "",
                f'[projects."{project_key}"]',
                'trust_level = "trusted"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return panel_home


class CodexChatView(QWidget):
    def __init__(self, base_dir: str | Path, parent=None):
        super().__init__(parent)
        self.base_dir = str(Path(base_dir).resolve())
        self._plain_text = ""
        self._math_mode = "fallback"
        self._mathjax_script_url = mathjax_script_url(self.base_dir)
        self._text_edit: QTextEdit | None = None
        self._web_view = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if self._mathjax_script_url and should_use_webengine_chat_view():
            if QWebEngineSettings is not None and QWebEngineView is not None:
                self._web_view = QWebEngineView(self)
                settings = self._web_view.settings()
                settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
                settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
                layout.addWidget(self._web_view)
                self._math_mode = "mathjax"

        if self._web_view is None:
            self._text_edit = QTextEdit(self)
            self._text_edit.setReadOnly(True)
            self._text_edit.setAcceptRichText(True)
            self._text_edit.document().setDefaultStyleSheet(CODEX_CHAT_STYLES)
            self._text_edit.setPlaceholderText("Codex 응답과 실행 상태가 여기에 표시됩니다.")
            layout.addWidget(self._text_edit)

    @property
    def math_mode(self) -> str:
        return self._math_mode

    def render_blocks(self, blocks: list[dict[str, str]]):
        self._plain_text = self._blocks_to_plain_text(blocks)
        document = render_codex_chat_html(
            blocks,
            math_mode=self._math_mode,
            mathjax_script_url=self._mathjax_script_url,
        )
        if self._web_view is not None:
            self._web_view.setHtml(document, QUrl.fromLocalFile(self.base_dir + os.sep))
            return

        if self._text_edit is None:
            return
        self._text_edit.setHtml(document)
        cursor = self._text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.ensureCursorVisible()

    def toPlainText(self) -> str:
        if self._text_edit is not None:
            return self._text_edit.toPlainText()
        return self._plain_text

    @staticmethod
    def _blocks_to_plain_text(blocks: list[dict[str, str]]) -> str:
        parts = []
        for block in blocks:
            title = block.get("title", "")
            text = block.get("text", "")
            parts.append(f"{title}\n{text}".strip())
        return "\n\n".join(part for part in parts if part)


def apply_hidden_codex_process_patch():
    if os.name != "nt":
        return

    import subprocess

    import openai_codex.client as codex_client

    if getattr(codex_client, "_exam_generator_hidden_popen", False):
        return

    real_popen = codex_client.subprocess.Popen

    def hidden_popen(*args, **kwargs):
        startupinfo = kwargs.get("startupinfo") or subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        return real_popen(*args, **kwargs)

    codex_client.subprocess.Popen = hidden_popen
    codex_client._exam_generator_hidden_popen = True


class CodexRunWorker(QThread):
    thread_ready = pyqtSignal(str)
    delta = pyqtSignal(str)
    progress = pyqtSignal(str)
    status = pyqtSignal(str)
    completed = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(
        self,
        prompt: str,
        cwd: str,
        thread_id: str | None,
        model: str | None,
        service_tier: str | None,
        sandbox_mode: str,
        approval_mode: str,
        image_paths: list[str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.prompt = prompt
        self.cwd = cwd
        self.thread_id = thread_id
        self.model = model
        self.service_tier = service_tier
        self.sandbox_mode = sandbox_mode
        self.approval_mode = approval_mode
        self.image_paths = list(image_paths or [])
        self._cancel_requested = False
        self._turn_handle = None
        self._progress_keys: set[str] = set()

    def interrupt(self):
        self._cancel_requested = True
        turn_handle = self._turn_handle
        if turn_handle is None:
            return
        try:
            turn_handle.interrupt()
            self.status.emit("중단 요청을 보냈습니다.")
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            self.status.emit(f"중단 요청 실패: {exc}")

    def _emit_progress_once(self, key: str, message: str):
        if key in self._progress_keys:
            return
        self._progress_keys.add(key)
        self.progress.emit(message)

    def run(self):
        try:
            from openai_codex import (
                ApprovalMode,
                Codex,
                CodexConfig,
                LocalImageInput,
                Sandbox,
                TextInput,
            )

            self.progress.emit("Codex 프로세스를 준비하고 있습니다.")
            apply_hidden_codex_process_patch()

            codex_home = prepare_panel_codex_home(self.cwd)
            sandbox = {
                "read-only": Sandbox.read_only,
                "workspace-write": Sandbox.workspace_write,
                "full-access": Sandbox.full_access,
            }.get(self.sandbox_mode, Sandbox.read_only)
            approval = {
                "deny-all": ApprovalMode.deny_all,
                "auto-review": ApprovalMode.auto_review,
            }.get(self.approval_mode, ApprovalMode.deny_all)

            config = CodexConfig(
                cwd=self.cwd,
                client_name="exam_generator_codex_panel",
                client_title="Exam Generator Codex Panel",
                client_version="0.1.0",
                env={"CODEX_HOME": str(codex_home)},
            )
            with Codex(config=config) as codex:
                self.status.emit("Codex 런타임을 시작했습니다.")
                self.progress.emit("Codex 런타임을 시작했습니다.")
                if self.thread_id:
                    thread = codex.thread_resume(
                        self.thread_id,
                        cwd=self.cwd,
                        model=self.model,
                        service_tier=self.service_tier,
                        sandbox=sandbox,
                        approval_mode=approval,
                    )
                else:
                    thread = codex.thread_start(
                        cwd=self.cwd,
                        model=self.model,
                        service_tier=self.service_tier,
                        sandbox=sandbox,
                        approval_mode=approval,
                        developer_instructions=CODEX_PANEL_INSTRUCTIONS,
                    )
                self.thread_ready.emit(thread.id)
                self.status.emit(f"Thread: {thread.id}")
                self.progress.emit("스레드를 준비했습니다.")

                turn_input = [TextInput(self.prompt)]
                turn_input.extend(LocalImageInput(path) for path in self.image_paths)
                self.progress.emit("요청을 Codex에 전달했습니다.")
                turn = thread.turn(
                    turn_input,
                    cwd=self.cwd,
                    model=self.model,
                    service_tier=self.service_tier,
                    sandbox=sandbox,
                    approval_mode=approval,
                )
                self._turn_handle = turn
                chunks: list[str] = []
                completed_status = None
                completed_error = None

                for event in turn.stream():
                    if self._cancel_requested:
                        break

                    progress_message = progress_message_for_event_method(event.method)
                    if progress_message:
                        self._emit_progress_once(event.method, progress_message)

                    if event.method == "item/agentMessage/delta":
                        text = getattr(event.payload, "delta", "")
                        if text:
                            chunks.append(text)
                            self.delta.emit(text)
                    elif event.method == "turn/completed":
                        completed_turn = getattr(event.payload, "turn", None)
                        completed_status = getattr(completed_turn, "status", None)
                        completed_error = getattr(completed_turn, "error", None)

                if self._cancel_requested:
                    self.completed.emit(thread.id, "".join(chunks).strip())
                    return

                status_value = getattr(completed_status, "value", completed_status)
                if status_value == "failed":
                    message = getattr(completed_error, "message", None) or "Codex turn failed."
                    raise RuntimeError(message)

                self.completed.emit(thread.id, "".join(chunks).strip())
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            traceback.print_exc()
            self.error.emit(str(exc))


class CodexStatusWorker(QThread):
    result = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, cwd: str, parent=None):
        super().__init__(parent)
        self.cwd = cwd

    def run(self):
        try:
            from openai_codex import Codex, CodexConfig

            apply_hidden_codex_process_patch()
            codex_home = prepare_panel_codex_home(self.cwd)
            config = CodexConfig(
                cwd=self.cwd,
                client_name="exam_generator_codex_panel",
                client_title="Exam Generator Codex Panel",
                client_version="0.1.0",
                env={"CODEX_HOME": str(codex_home)},
            )
            with Codex(config=config) as codex:
                account = codex.account(refresh_token=False)
                account_text = self._format_account(account)
                self.result.emit(account_text)
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            traceback.print_exc()
            self.error.emit(str(exc))

    @staticmethod
    def _format_account(account) -> str:
        dumped = account.model_dump(mode="json") if hasattr(account, "model_dump") else {}
        root = dumped.get("root") if isinstance(dumped, dict) else None
        if isinstance(root, dict):
            email = root.get("email") or root.get("userEmail")
            workspace = root.get("workspaceName") or root.get("workspace")
            if email and workspace:
                return f"{email} / {workspace}"
            if email:
                return str(email)
            if root.get("type"):
                return f"인증됨: {root['type']}"
        return "Codex 계정 정보를 읽었습니다."


class CodexLoginWorker(QThread):
    login_started = pyqtSignal(str, str)
    result = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, cwd: str, parent=None):
        super().__init__(parent)
        self.cwd = cwd

    def run(self):
        try:
            from openai_codex import Codex, CodexConfig

            apply_hidden_codex_process_patch()
            codex_home = prepare_panel_codex_home(self.cwd)
            config = CodexConfig(
                cwd=self.cwd,
                client_name="exam_generator_codex_panel",
                client_title="Exam Generator Codex Panel",
                client_version="0.1.0",
                env={"CODEX_HOME": str(codex_home)},
            )
            with Codex(config=config) as codex:
                login = codex.login_chatgpt_device_code()
                self.login_started.emit(login.verification_url, login.user_code)
                try:
                    webbrowser.open(login.verification_url)
                except Exception:
                    pass
                login.wait()
                account = codex.account(refresh_token=False)
                self.result.emit(CodexStatusWorker._format_account(account))
        except Exception as exc:  # noqa: BLE001 - surfaced to UI
            traceback.print_exc()
            self.error.emit(str(exc))


class CodexInterface(QWidget):
    collapse_requested = pyqtSignal()

    def __init__(self, base_dir: str | Path, parent=None, side_panel: bool = False):
        super().__init__(parent)
        self.base_dir = str(Path(base_dir).resolve())
        self.side_panel = side_panel
        self._chat_blocks: list[dict[str, str]] = []
        self.thread_id: str | None = None
        self.image_paths: list[str] = []
        self.worker: CodexRunWorker | None = None
        self.status_worker: CodexStatusWorker | None = None
        self.login_worker: CodexLoginWorker | None = None
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(2500)
        self.progress_timer.timeout.connect(self._append_progress_tick)
        self._progress_tick_index = 0
        self._answer_started = False
        self.setObjectName("CodexInterface")

        self.vBoxLayout = QVBoxLayout(self)
        self.init_ui()

    def init_ui(self):
        if self.side_panel:
            self.setMinimumWidth(340)
            self.setMaximumWidth(430)
            self.setStyleSheet(
                """
                CodexInterface { border-left: 1px solid rgba(0, 0, 0, 24); }
                CodexInterface QPushButton {
                    font-size: 12px;
                    padding-left: 6px;
                    padding-right: 6px;
                }
                CodexInterface QComboBox { font-size: 12px; }
                CodexInterface QTextEdit { font-size: 12px; }
                """
            )
            self.vBoxLayout.setContentsMargins(14, 14, 14, 14)
            self.vBoxLayout.setSpacing(8)
        else:
            self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
            self.vBoxLayout.setSpacing(12)

        header_layout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Codex", self)
        self.statusLabel = BodyLabel("대기 중", self)
        self.statusLabel.setTextColor(Qt.darkGray, Qt.white)
        header_layout.addWidget(self.titleLabel)
        header_layout.addStretch(1)
        header_layout.addWidget(self.statusLabel)
        if self.side_panel:
            self.collapseButton = PushButton("접기", self)
            self.collapseButton.setToolTip("Codex 패널 접기")
            self.collapseButton.setFixedSize(54, SIDE_PANEL_BUTTON_HEIGHT)
            self.collapseButton.clicked.connect(lambda: self.collapse_requested.emit())
            header_layout.addWidget(self.collapseButton)
        self.vBoxLayout.addLayout(header_layout)

        controls_layout = QVBoxLayout() if self.side_panel else QHBoxLayout()
        self.modelCombo = QComboBox(self)
        self._populate_model_combo()
        self._apply_combo_item_height(self.modelCombo)

        self.sandboxCombo = QComboBox(self)
        self.sandboxCombo.addItem("읽기 전용", "read-only")
        self.sandboxCombo.addItem("워크스페이스 쓰기", "workspace-write")
        self.sandboxCombo.addItem("전체 접근", "full-access")
        self._apply_combo_item_height(self.sandboxCombo)

        self.approvalCombo = QComboBox(self)
        self.approvalCombo.addItem("승인 요청 차단", "deny-all")
        self.approvalCombo.addItem("자동 검토", "auto-review")
        self._apply_combo_item_height(self.approvalCombo)

        self.checkStatusButton = PushButton("인증 확인", self)
        self.checkStatusButton.clicked.connect(self.check_status)

        self.loginButton = PushButton("로그인", self)
        self.loginButton.clicked.connect(self.login_codex)

        self.newThreadButton = PushButton("새 Thread", self)
        self.newThreadButton.clicked.connect(self.new_thread)

        if self.side_panel:
            option_row = QHBoxLayout()
            option_row.addWidget(self.sandboxCombo)
            option_row.addWidget(self.approvalCombo)

            button_row = QHBoxLayout()
            button_row.addWidget(self.checkStatusButton)
            button_row.addWidget(self.loginButton)
            button_row.addWidget(self.newThreadButton)

            controls_layout.addWidget(self.modelCombo)
            controls_layout.addLayout(option_row)
            controls_layout.addLayout(button_row)
        else:
            controls_layout.addWidget(BodyLabel("Model", self))
            controls_layout.addWidget(self.modelCombo)
            controls_layout.addWidget(self.sandboxCombo)
            controls_layout.addWidget(self.approvalCombo)
            controls_layout.addStretch(1)
            controls_layout.addWidget(self.checkStatusButton)
            controls_layout.addWidget(self.loginButton)
            controls_layout.addWidget(self.newThreadButton)
        self.vBoxLayout.addLayout(controls_layout)

        self.chatView = CodexChatView(self.base_dir, self)
        self.vBoxLayout.addWidget(self.chatView, 1)

        self.progressView = QTextEdit(self)
        self.progressView.setReadOnly(True)
        self.progressView.setPlaceholderText("진행 로그")
        self.progressView.setMinimumHeight(58 if self.side_panel else 70)
        self.progressView.setMaximumHeight(72 if self.side_panel else 90)
        self.vBoxLayout.addWidget(self.progressView)

        self.promptBox = QTextEdit(self)
        self.promptBox.setPlaceholderText("Codex에게 요청할 내용을 입력하세요.")
        self.promptBox.setMinimumHeight(SIDE_PANEL_PROMPT_MIN_HEIGHT if self.side_panel else 90)
        self.promptBox.setMaximumHeight(SIDE_PANEL_PROMPT_MAX_HEIGHT if self.side_panel else 150)
        self.vBoxLayout.addWidget(self.promptBox)

        image_layout = QHBoxLayout()
        self.imageStatusLabel = BodyLabel("이미지 없음", self)
        self.imageStatusLabel.setTextColor(Qt.darkGray, Qt.white)
        self.attachImageButton = PushButton("이미지" if self.side_panel else "이미지 추가", self)
        self.attachImageButton.setToolTip("이미지 파일 추가")
        self.attachImageButton.clicked.connect(self.attach_image)
        self.pasteImageButton = PushButton("붙여넣기" if self.side_panel else "클립보드", self)
        self.pasteImageButton.setToolTip("클립보드 이미지 붙여넣기")
        self.pasteImageButton.clicked.connect(self.attach_clipboard_image)
        self.clearImagesButton = PushButton("지우기", self)
        self.clearImagesButton.setToolTip("첨부 이미지 지우기")
        self.clearImagesButton.clicked.connect(self.clear_images)
        image_layout.addWidget(self.imageStatusLabel)
        image_layout.addStretch(1)
        image_layout.addWidget(self.attachImageButton)
        image_layout.addWidget(self.pasteImageButton)
        image_layout.addWidget(self.clearImagesButton)
        self.vBoxLayout.addLayout(image_layout)

        action_layout = QHBoxLayout()
        self.sendButton = PrimaryPushButton("보내기", self)
        self.sendButton.clicked.connect(self.send_prompt)
        self.stopButton = PushButton("중단", self)
        self.stopButton.setEnabled(False)
        self.stopButton.clicked.connect(self.stop_current_turn)
        action_layout.addStretch(1)
        action_layout.addWidget(self.stopButton)
        action_layout.addWidget(self.sendButton)
        self.vBoxLayout.addLayout(action_layout)

        if self.side_panel:
            self._apply_side_panel_compact_sizes()

    def _apply_combo_item_height(self, combo, height=44):
        view = combo.view()
        view.setStyleSheet(f"QListView::item {{ height: {height}px; }}")

    def _apply_font_size(self, widget, point_size=SIDE_PANEL_FONT_POINT_SIZE):
        font = widget.font()
        font.setPointSize(point_size)
        widget.setFont(font)

    def _apply_side_panel_compact_sizes(self):
        for widget in (
            self.statusLabel,
            self.imageStatusLabel,
            self.modelCombo,
            self.sandboxCombo,
            self.approvalCombo,
            self.chatView,
            self.progressView,
            self.promptBox,
            self.attachImageButton,
            self.pasteImageButton,
            self.clearImagesButton,
            self.stopButton,
            self.sendButton,
            self.checkStatusButton,
            self.loginButton,
            self.newThreadButton,
        ):
            self._apply_font_size(widget)

        if hasattr(self, "collapseButton"):
            self._apply_font_size(self.collapseButton)

        for combo in (self.modelCombo, self.sandboxCombo, self.approvalCombo):
            combo.setFixedHeight(32)
            self._apply_combo_item_height(combo, 34)

        button_widths = {
            self.attachImageButton: 58,
            self.pasteImageButton: 70,
            self.clearImagesButton: 54,
            self.stopButton: 56,
            self.sendButton: 64,
            self.checkStatusButton: 76,
            self.loginButton: 58,
            self.newThreadButton: 78,
        }
        for button, width in button_widths.items():
            button.setFixedHeight(SIDE_PANEL_BUTTON_HEIGHT)
            button.setMinimumWidth(width)

        self.imageStatusLabel.setMinimumWidth(64)
        self.imageStatusLabel.setMaximumWidth(78)

    def _populate_model_combo(self):
        self.modelCombo.clear()
        options = [
            (
                "GPT-5.3 Spark - 가장 빠름, 텍스트",
                {"model": "gpt-5.3-codex-spark", "service_tier": None, "image": False},
            ),
            (
                "GPT-5.4 Mini - 빠름, 이미지 가능",
                {"model": "gpt-5.4-mini", "service_tier": None, "image": True},
            ),
            (
                "GPT-5.4 Fast - 균형",
                {"model": "gpt-5.4", "service_tier": "priority", "image": True},
            ),
            (
                "GPT-5.5 Fast - 고성능",
                {"model": "gpt-5.5", "service_tier": "priority", "image": True},
            ),
            (
                "기본값 사용",
                {"model": None, "service_tier": None, "image": True},
            ),
        ]
        for label, data in options:
            self.modelCombo.addItem(label, data)

    def _selected_model(self) -> str | None:
        data = self.modelCombo.currentData()
        return data.get("model") if isinstance(data, dict) else None

    def _selected_service_tier(self) -> str | None:
        data = self.modelCombo.currentData()
        return data.get("service_tier") if isinstance(data, dict) else None

    def _selected_model_supports_images(self) -> bool:
        data = self.modelCombo.currentData()
        return bool(data.get("image", True)) if isinstance(data, dict) else True

    def _selected_sandbox_mode(self) -> str:
        return self.sandboxCombo.currentData() or "read-only"

    def _selected_approval_mode(self) -> str:
        return self.approvalCombo.currentData() or "deny-all"

    def send_prompt(self):
        prompt = self.promptBox.toPlainText().strip()
        if not prompt:
            InfoBar.warning(
                title="입력 없음",
                content="Codex에게 보낼 요청을 입력하세요.",
                parent=self,
                duration=2000,
            )
            return

        if self.worker is not None and self.worker.isRunning():
            InfoBar.warning(
                title="실행 중",
                content="현재 Codex 작업이 끝난 뒤 다시 보내세요.",
                parent=self,
                duration=2000,
            )
            return

        if self.image_paths and not self._selected_model_supports_images():
            InfoBar.error(
                title="이미지 모델 필요",
                content="이미지를 보낼 때는 GPT-5.4 Mini, GPT-5.4 Fast, GPT-5.5 Fast 중 하나를 선택하세요.",
                parent=self,
                duration=4000,
            )
            return

        self._append_block("You", prompt)
        if self.image_paths:
            names = ", ".join(Path(path).name for path in self.image_paths)
            self._append_text(f"\nImages: {names}")
        self._append_block("Codex")
        self.promptBox.clear()
        image_paths = list(self.image_paths)
        self.clear_images()
        self._begin_progress()
        self._set_running(True)

        self.worker = CodexRunWorker(
            prompt=prompt,
            cwd=self.base_dir,
            thread_id=self.thread_id,
            model=self._selected_model(),
            service_tier=self._selected_service_tier(),
            sandbox_mode=self._selected_sandbox_mode(),
            approval_mode=self._selected_approval_mode(),
            image_paths=image_paths,
            parent=self,
        )
        self.worker.thread_ready.connect(self._on_thread_ready)
        self.worker.delta.connect(self._append_answer_delta)
        self.worker.progress.connect(self._append_progress)
        self.worker.status.connect(self._set_status)
        self.worker.completed.connect(self._on_completed)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(lambda: self._set_running(False))
        self.worker.start()

    def stop_current_turn(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.interrupt()

    def new_thread(self):
        self.thread_id = None
        self._set_status("새 Thread 준비")
        self._append_block("System", "새 Codex Thread를 시작합니다.")

    def check_status(self):
        if self.status_worker is not None and self.status_worker.isRunning():
            return
        self.checkStatusButton.setEnabled(False)
        self._set_status("인증 상태 확인 중...")
        self.status_worker = CodexStatusWorker(self.base_dir, self)
        self.status_worker.result.connect(self._on_status_result)
        self.status_worker.error.connect(self._on_status_error)
        self.status_worker.finished.connect(lambda: self.checkStatusButton.setEnabled(True))
        self.status_worker.start()

    def login_codex(self):
        if self.login_worker is not None and self.login_worker.isRunning():
            return
        self.loginButton.setEnabled(False)
        self._set_status("Codex 로그인 준비 중...")
        self.login_worker = CodexLoginWorker(self.base_dir, self)
        self.login_worker.login_started.connect(self._on_login_started)
        self.login_worker.result.connect(self._on_login_result)
        self.login_worker.error.connect(self._on_login_error)
        self.login_worker.finished.connect(lambda: self.loginButton.setEnabled(True))
        self.login_worker.start()

    def attach_image(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Codex에 보낼 이미지 선택",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        for path in paths:
            self._add_image_path(path)

    def attach_clipboard_image(self):
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    self._add_image_path(url.toLocalFile())
            return

        image = clipboard.image()
        if image.isNull():
            InfoBar.warning(
                title="클립보드 이미지 없음",
                content="클립보드에 이미지나 이미지 파일이 없습니다.",
                parent=self,
                duration=2500,
            )
            return

        image_dir = Path(self.base_dir) / "data" / "codex_panel_images"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / f"clipboard-{uuid.uuid4()}.png"
        if image.save(str(image_path), "PNG"):
            self._add_image_path(str(image_path))
        else:
            InfoBar.error(
                title="이미지 저장 실패",
                content="클립보드 이미지를 파일로 저장하지 못했습니다.",
                parent=self,
                duration=3000,
            )

    def _add_image_path(self, path: str):
        resolved = str(Path(path).resolve())
        if resolved not in self.image_paths:
            self.image_paths.append(resolved)
        self._update_image_status()

    def clear_images(self):
        self.image_paths = []
        self._update_image_status()

    def _update_image_status(self):
        count = len(self.image_paths)
        if count == 0:
            self.imageStatusLabel.setText("이미지 없음")
        else:
            self.imageStatusLabel.setText(f"이미지 {count}개 첨부")

    def _on_thread_ready(self, thread_id: str):
        self.thread_id = thread_id

    def _on_completed(self, thread_id: str, _final_text: str):
        self.thread_id = thread_id
        self._end_progress("완료")
        self._append_text("\n")
        self._set_status("완료")

    def _on_error(self, message: str):
        self._end_progress("오류")
        self._append_block("Error", message)
        self._set_status("오류")
        InfoBar.error(
            title="Codex 오류",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
            parent=self,
        )

    def _on_status_result(self, message: str):
        self._set_status(message)
        InfoBar.success(
            title="Codex 인증",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3000,
            parent=self,
        )

    def _on_status_error(self, message: str):
        self._set_status("인증 확인 실패")
        InfoBar.error(
            title="Codex 인증 확인 실패",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=5000,
            parent=self,
        )

    def _on_login_started(self, verification_url: str, user_code: str):
        self._set_status("브라우저에서 Codex 로그인 진행 중")
        self._append_block(
            "System",
            f"Codex 로그인 페이지가 열렸습니다.\nURL: {verification_url}\nCode: {user_code}",
        )
        InfoBar.info(
            title="Codex 로그인",
            content=f"브라우저에서 코드를 입력하세요: {user_code}",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=10000,
            parent=self,
        )

    def _on_login_result(self, message: str):
        self._set_status(message)
        InfoBar.success(
            title="Codex 로그인 완료",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=3500,
            parent=self,
        )

    def _on_login_error(self, message: str):
        self._set_status("로그인 실패")
        InfoBar.error(
            title="Codex 로그인 실패",
            content=message,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP_RIGHT,
            duration=6000,
            parent=self,
        )

    def _set_running(self, running: bool):
        self.sendButton.setEnabled(not running)
        self.stopButton.setEnabled(running)
        if running:
            self._set_status("Codex 실행 중...")

    def _set_status(self, message: str):
        self.statusLabel.setText(message)

    def _append_block(self, title: str, text: str = ""):
        self._chat_blocks.append({"title": title, "text": text})
        self._render_chat()

    def _append_text(self, text: str):
        if not text:
            return
        if not self._chat_blocks:
            self._chat_blocks.append({"title": "System", "text": ""})
        self._chat_blocks[-1]["text"] += text
        self._render_chat()

    def _render_chat(self):
        self.chatView.render_blocks(self._chat_blocks)

    def _append_answer_delta(self, text: str):
        if not self._answer_started:
            self._answer_started = True
            self.progress_timer.stop()
            self._append_progress("응답을 수신하기 시작했습니다.")
        self._append_text(text)

    def _begin_progress(self):
        self.progressView.clear()
        self._answer_started = False
        self._progress_tick_index = 0
        self._append_progress("요청을 보냈습니다.")
        self.progress_timer.start()

    def _end_progress(self, message: str):
        self.progress_timer.stop()
        self._append_progress(message)

    def _append_progress_tick(self):
        message = PROGRESS_MESSAGES[self._progress_tick_index % len(PROGRESS_MESSAGES)]
        self._progress_tick_index += 1
        self._append_progress(message)

    def _append_progress(self, text: str):
        current_text = self.progressView.toPlainText()
        line = f"[진행] {text}"
        if current_text.splitlines()[-1:] == [line]:
            return
        cursor = self.progressView.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.progressView.setTextCursor(cursor)
        if current_text:
            self.progressView.insertPlainText("\n")
        self.progressView.insertPlainText(line)
        self.progressView.ensureCursorVisible()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.interrupt()
            self.worker.wait(1500)
        if self.status_worker is not None and self.status_worker.isRunning():
            self.status_worker.wait(1500)
        if self.login_worker is not None and self.login_worker.isRunning():
            self.login_worker.wait(1500)
        super().closeEvent(event)
