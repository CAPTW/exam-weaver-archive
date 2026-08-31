from __future__ import annotations

from pathlib import Path

FORMAT_DOCX = "docx"
FORMAT_HWPX = "hwpx"
DEFAULT_FORMAT = FORMAT_DOCX

_BUTTON = {
    FORMAT_DOCX: "DOCX 시험지 저장",
    FORMAT_HWPX: "HWPX 시험지 저장",
}
_TITLE = {
    FORMAT_DOCX: "DOCX 시험지 저장",
    FORMAT_HWPX: "HWPX 시험지 저장",
}
_FILTER = {
    FORMAT_DOCX: "Word 문서 (*.docx)",
    FORMAT_HWPX: "한글 표준 문서 (*.hwpx)",
}
_WARNINGS = {
    "HWPX_UNSUPPORTED_FORMATTING_AS_TEXT": "지원하지 않는 서식을 일반 텍스트로 표시했습니다.",
    "HWPX_EQUATION_TEXT_FALLBACK": "수식/윗줄을 보이는 텍스트로 대체했습니다.",
    "HWPX_TABLE_IMAGE_FALLBACK": "복잡한 표를 원본 이미지로 대체했습니다.",
    "HWPX_TABLE_TEXT_FALLBACK": "복잡한 표를 보이는 텍스트로 대체했습니다.",
    "HWPX_IMAGE_CONVERTED_TO_PNG": "이미지를 PNG로 변환해 포함했습니다.",
    "HWPX_ANSWER_KEY_CONTINUATION": "정답표를 이어서 만들었습니다.",
    "HWPX_OPTIONAL_METADATA_UNAVAILABLE": "일부 선택 메타데이터를 생략했습니다.",
}
_ERRORS = {
    "HWPX_REQUIRED_IMAGE_MISSING": "필수 이미지가 없어 HWPX를 만들지 못했습니다.",
    "HWPX_INVALID_OUTPUT_PATH": "저장 경로가 올바르지 않습니다.",
    "HWPX_TABLE_TOPOLOGY_INVALID": "표 구조가 올바르지 않아 HWPX를 만들지 못했습니다.",
    "HWPX_EXTENSION_MISMATCH": "HWPX 저장에는 .hwpx 확장자가 필요합니다.",
    "DOCX_EXTENSION_MISMATCH": "DOCX 저장에는 .docx 확장자가 필요합니다.",
    "HWPX_EXTENSION_UNSUPPORTED": "선택한 HWPX 형식은 .hwpx 파일만 저장합니다.",
    "DOCX_EXTENSION_UNSUPPORTED": "선택한 DOCX 형식은 .docx 파일만 저장합니다.",
}
_KNOWN = {".docx", ".hwpx", ".pdf", ".txt", ".hwp", ".doc"}


def button_text(fmt: str) -> str:
    return _BUTTON[fmt]


def dialog_title(fmt: str) -> str:
    return _TITLE[fmt]


def dialog_filter(fmt: str) -> str:
    return _FILTER[fmt]


def default_suffix(fmt: str) -> str:
    return f".{fmt}"


def normalize_save_path(path: str | Path, fmt: str) -> tuple[str | None, str | None]:
    candidate = Path(path)
    suffix = candidate.suffix.lower()
    expected = default_suffix(fmt)
    if suffix == "":
        return str(candidate.with_suffix(expected)), None
    if suffix == expected:
        return str(candidate), None
    if suffix in {".docx", ".hwpx"} and suffix != expected:
        return None, f"{fmt.upper()}_EXTENSION_MISMATCH"
    if suffix in _KNOWN or suffix.startswith("."):
        return None, f"{fmt.upper()}_EXTENSION_UNSUPPORTED"
    return None, f"{fmt.upper()}_EXTENSION_UNSUPPORTED"


def warning_summary(codes: list[str] | tuple[str, ...], fallback_count: int = 0) -> str:
    items = list(codes)
    shown = items[:3]
    lines = [_WARNINGS.get(code, code) + f" ({code})" for code in shown]
    remaining = len(items) - len(shown)
    if remaining > 0:
        lines.append(f"외 {remaining}건")
    if fallback_count:
        lines.append(f"대체 출력 {fallback_count}건")
    return " · ".join(lines) if lines else ""


def error_message(code: str) -> str:
    return f"{_ERRORS.get(code, 'HWPX 내보내기에 실패했습니다.')} ({code})"
