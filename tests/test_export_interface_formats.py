import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from src.gui.export_formats import FORMAT_DOCX, FORMAT_HWPX
from src.gui.interface.export import ExportInterface
from src.exporter.hwpx import HwpxCompileError, HwpxExportResult
from tests.test_export_interface import _MultiExamRepository

APP = QApplication.instance() or QApplication([])


class _CountingBuilder:
    def __init__(self):
        self.calls = []

    def build(self, **kwargs):
        self.calls.append(kwargs)
        return {"document": True, "kwargs": kwargs}


class _DocxExporter:
    def __init__(self):
        self.calls = []
        self.warnings = []
        self.choice_marker_style = None
        self.table_render_mode = "auto"

    def set_choice_marker_style(self, style):
        self.choice_marker_style = style

    def set_table_render_mode(self, mode):
        self.table_render_mode = mode

    def export_document(self, document, file_path):
        self.calls.append((document, str(file_path)))
        Path(file_path).write_bytes(b"PK\x03\x04docx")
        if getattr(self, "emit_table_warning", False):
            self.warnings = ["table-fallback"]


class _HwpxCompiler:
    def __init__(self, *, choice_marker_style="legacy"):
        self.choice_marker_style = choice_marker_style
        self.calls = []
        self.fail_code = None
        self.result_warnings = ()
        self.fallback_count = 0

    def export_document(self, document, file_path):
        self.calls.append((document, str(file_path)))
        if self.fail_code:
            raise HwpxCompileError(self.fail_code, "controlled failure")
        Path(file_path).write_bytes(b"PK\x03\x04hwpx")
        return HwpxExportResult(
            output_path=Path(file_path),
            output_bytes=4,
            package_sha256="a" * 64,
            semantic_digest="b" * 64,
            warnings=self.result_warnings,
            section_count=1,
            question_count=1,
            table_count=0,
            image_count=0,
            fallback_count=self.fallback_count,
        )


class _ExportRepository(_MultiExamRepository):
    def get_questions_with_choices(self, **kwargs):
        return [
            {
                "id": 1,
                "year": 2025,
                "question_text": "문항",
                "image_path": None,
                "choices": [{"number": 1, "text": "A"}],
                "correct_answer": 1,
                "question_type": "objective",
            }
        ]


def _widget():
    return ExportInterface(repository=_ExportRepository())


def test_selector_defaults_to_docx_and_exposes_stable_keys():
    widget = _widget()
    assert widget.titleLabel.text() == "시험지 내보내기"
    assert widget.formatLabel.text() == "출력 형식"
    assert widget.outputFormatFilter.currentData() == FORMAT_DOCX
    keys = [widget.outputFormatFilter.itemData(i) for i in range(widget.outputFormatFilter.count())]
    assert keys == [FORMAT_DOCX, FORMAT_HWPX]
    assert widget.btnExport.text() == "DOCX 시험지 저장"
    widget.deleteLater()
    APP.processEvents()


def test_button_text_and_dialog_follow_selected_format(monkeypatch):
    widget = _widget()
    seen = {}

    def fake_dialog(_parent, title, _filename, selected_filter):
        seen["title"] = title
        seen["filter"] = selected_filter
        return ("", "")

    monkeypatch.setattr("src.gui.interface.export.QFileDialog.getSaveFileName", fake_dialog)
    widget.outputFormatFilter.setCurrentIndex(1)
    widget._export_state["format"] = FORMAT_HWPX
    assert widget.btnExport.text() == "HWPX 시험지 저장"
    widget.btnExport.click()
    assert seen["title"] == "HWPX 시험지 저장"
    assert "hwpx" in seen["filter"].lower()
    widget.deleteLater()
    APP.processEvents()


def test_docx_route_builds_once_and_does_not_call_hwpx(monkeypatch, tmp_path):
    widget = _widget()
    builder = _CountingBuilder()
    docx = _DocxExporter()
    factory_calls = []
    widget.document_builder = builder
    widget.exporter = docx
    widget.hwpx_compiler_factory = lambda: factory_calls.append("created") or _HwpxCompiler()
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "out"), "Word 문서 (*.docx)"),
    )
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **_k: None)
    widget.export_exam()
    assert len(builder.calls) == 1
    assert len(docx.calls) == 1
    assert factory_calls == []
    widget.deleteLater()
    APP.processEvents()


def test_hwpx_route_builds_once_and_does_not_call_docx(monkeypatch, tmp_path):
    widget = _widget()
    builder = _CountingBuilder()
    docx = _DocxExporter()
    compiler = _HwpxCompiler()
    widget.document_builder = builder
    widget.exporter = docx
    widget._hwpx_compiler = compiler
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **_k: None)
    document = builder.build(title="t", questions=[], sections=None, shuffle_choices=False)
    widget._render_selected(document, str(tmp_path / "out.hwpx"), FORMAT_HWPX)
    assert len(builder.calls) == 1
    assert len(compiler.calls) == 1
    assert docx.calls == []
    widget.deleteLater()
    APP.processEvents()


def test_cancel_has_zero_side_effects(monkeypatch):
    widget = _widget()
    builder = _CountingBuilder()
    docx = _DocxExporter()
    widget.document_builder = builder
    widget.exporter = docx
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: ("", ""),
    )
    bars = []
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **k: bars.append("success"))
    monkeypatch.setattr("src.gui.interface.export.InfoBar.error", lambda **k: bars.append("error"))
    widget.export_exam()
    assert builder.calls == []
    assert docx.calls == []
    assert bars == []
    widget.deleteLater()
    APP.processEvents()


def test_conflicting_suffix_blocks_before_builder(monkeypatch, tmp_path):
    widget = _widget()
    builder = _CountingBuilder()
    widget.document_builder = builder
    widget.outputFormatFilter.setCurrentIndex(1)
    widget._export_state["format"] = FORMAT_HWPX
    monkeypatch.setattr(widget, "_selected_output_format", lambda: FORMAT_HWPX)
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "exam.docx"), "x"),
    )
    warned = []
    monkeypatch.setattr("src.gui.interface.export.InfoBar.warning", lambda **k: warned.append(k))
    widget.export_exam()
    assert builder.calls == []
    assert warned
    widget.deleteLater()
    APP.processEvents()


def test_unknown_suffix_blocks_before_builder(monkeypatch, tmp_path):
    widget = _widget()
    builder = _CountingBuilder()
    widget.document_builder = builder
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "exam.txt"), "x"),
    )
    warned = []
    monkeypatch.setattr("src.gui.interface.export.InfoBar.warning", lambda **k: warned.append(k))
    widget.export_exam()
    assert builder.calls == []
    assert warned
    widget.deleteLater()
    APP.processEvents()


def test_no_legacy_export_method_on_production_route():
    source = Path(__file__).resolve().parents[1] / "src" / "gui" / "interface" / "export.py"
    text = source.read_text(encoding="utf-8")
    assert 'hasattr(self.exporter, "export_document")' not in text
    assert "self.exporter.export(" not in text


def test_same_examdocument_kwargs_across_routes(monkeypatch, tmp_path):
    widget = _widget()
    builder = _CountingBuilder()
    docx = _DocxExporter()
    compiler = _HwpxCompiler()
    widget.document_builder = builder
    widget.exporter = docx
    widget.hwpx_compiler_factory = lambda: compiler
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **_k: None)
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "a"), "x"),
    )
    widget.export_exam()
    widget.outputFormatFilter.setCurrentIndex(1)
    widget._export_state["format"] = FORMAT_HWPX
    monkeypatch.setattr(widget, "_selected_output_format", lambda: FORMAT_HWPX)
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "b"), "x"),
    )
    widget.export_exam()
    assert len(builder.calls) == 2
    left = dict(builder.calls[0])
    right = dict(builder.calls[1])
    left.pop("title", None)
    right.pop("title", None)
    assert left == right
    widget.deleteLater()
    APP.processEvents()


def test_hwpx_warning_and_failure_feedback(monkeypatch, tmp_path):
    widget = _widget()
    compiler = _HwpxCompiler()
    compiler.result_warnings = ("HWPX_TABLE_TEXT_FALLBACK",)
    compiler.fallback_count = 1
    widget._hwpx_compiler = compiler
    bars = []
    monkeypatch.setattr("src.gui.interface.export.InfoBar.warning", lambda **k: bars.append(("warning", k)))
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **k: bars.append(("success", k)))
    monkeypatch.setattr("src.gui.interface.export.InfoBar.error", lambda **k: bars.append(("error", k)))
    widget._render_selected(object(), str(tmp_path / "warn.hwpx"), FORMAT_HWPX)
    assert bars[0][0] == "warning"
    assert "경고" in bars[0][1]["title"]
    compiler.fail_code = "HWPX_REQUIRED_IMAGE_MISSING"
    try:
        widget._render_selected(object(), str(tmp_path / "fail.hwpx"), FORMAT_HWPX)
        raised = False
    except HwpxCompileError as exc:
        raised = exc.code == "HWPX_REQUIRED_IMAGE_MISSING"
    assert raised
    widget.btnExport.setEnabled(True)
    assert widget.btnExport.isEnabled()
    widget.deleteLater()
    APP.processEvents()


def test_format_switch_preserves_selection_and_does_not_export():
    widget = _widget()
    exam = widget.examFilter.currentData()
    shuffle = widget.shuffleChoices.isChecked()
    widget.outputFormatFilter.setCurrentIndex(1)
    widget._export_state["format"] = FORMAT_HWPX
    widget.outputFormatFilter.setCurrentIndex(0)
    widget._output_format = FORMAT_DOCX
    assert widget.examFilter.currentData() == exam
    assert widget.shuffleChoices.isChecked() == shuffle
    widget.deleteLater()
    APP.processEvents()


def test_choice_marker_style_reaches_hwpx_compiler():
    widget = _widget()
    captured = {}

    def factory():
        compiler = _HwpxCompiler(choice_marker_style=widget.choice_marker_style)
        captured["compiler"] = compiler
        return compiler

    widget.hwpx_compiler_factory = factory
    widget._hwpx_compiler = None
    widget.set_choice_marker_style("circled_number")
    compiler = widget._get_hwpx_compiler()
    assert compiler.choice_marker_style == widget.choice_marker_style
    widget.deleteLater()
    APP.processEvents()


def test_docx_warning_regression_still_uses_table_fallback_copy(monkeypatch, tmp_path):
    widget = _widget()
    widget.document_builder = _CountingBuilder()
    docx = _DocxExporter()
    docx.emit_table_warning = True
    widget.exporter = docx
    bars = []
    monkeypatch.setattr("src.gui.interface.export.InfoBar.warning", lambda **k: bars.append(k))
    monkeypatch.setattr("src.gui.interface.export.InfoBar.success", lambda **k: bars.append(k))
    monkeypatch.setattr(
        "src.gui.interface.export.QFileDialog.getSaveFileName",
        lambda *_a, **_k: (str(tmp_path / "docx"), "x"),
    )
    widget.export_exam()
    assert bars[0]["title"] == "내보내기 완료 · 표 폴백 적용"
    widget.deleteLater()
    APP.processEvents()
