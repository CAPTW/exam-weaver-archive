from pathlib import Path

from src.gui.export_formats import (
    DEFAULT_FORMAT,
    FORMAT_DOCX,
    FORMAT_HWPX,
    button_text,
    dialog_filter,
    dialog_title,
    error_message,
    normalize_save_path,
    warning_summary,
)


def test_default_format_is_docx():
    assert DEFAULT_FORMAT == FORMAT_DOCX == "docx"
    assert FORMAT_HWPX == "hwpx"


def test_dialog_and_button_contracts():
    assert button_text(FORMAT_DOCX) == "DOCX 시험지 저장"
    assert button_text(FORMAT_HWPX) == "HWPX 시험지 저장"
    assert dialog_title(FORMAT_DOCX) == "DOCX 시험지 저장"
    assert dialog_title(FORMAT_HWPX) == "HWPX 시험지 저장"
    assert dialog_filter(FORMAT_DOCX) == "Word 문서 (*.docx)"
    assert dialog_filter(FORMAT_HWPX) == "한글 표준 문서 (*.hwpx)"


def test_normalize_appends_suffix_when_missing():
    path, error = normalize_save_path("exam", FORMAT_HWPX)
    assert error is None
    assert error is None
    assert Path(path).suffix.lower() == ".hwpx"


def test_normalize_accepts_correct_suffix_case_insensitive():
    path, error = normalize_save_path("Exam.HWPX", FORMAT_HWPX)
    assert error is None
    assert path.endswith(".HWPX") or path.lower().endswith(".hwpx")


def test_normalize_rejects_conflicting_suffix():
    path, error = normalize_save_path("exam.docx", FORMAT_HWPX)
    assert path is None
    assert error == "HWPX_EXTENSION_MISMATCH"
    path, error = normalize_save_path("exam.hwpx", FORMAT_DOCX)
    assert path is None
    assert error == "DOCX_EXTENSION_MISMATCH"


def test_normalize_rejects_unknown_suffix():
    path, error = normalize_save_path("exam.txt", FORMAT_HWPX)
    assert path is None
    assert error == "HWPX_EXTENSION_UNSUPPORTED"
    path, error = normalize_save_path("exam.pdf", FORMAT_DOCX)
    assert path is None
    assert error == "DOCX_EXTENSION_UNSUPPORTED"


def test_warning_and_error_localization_keeps_unknown_codes():
    text = warning_summary(["HWPX_EQUATION_TEXT_FALLBACK", "UNKNOWN_CODE"], fallback_count=1)
    assert "HWPX_EQUATION_TEXT_FALLBACK" in text or "수식" in text
    assert "UNKNOWN_CODE" in text
    assert "HWPX_REQUIRED_IMAGE_MISSING" in error_message("HWPX_REQUIRED_IMAGE_MISSING")
