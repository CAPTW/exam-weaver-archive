"""Shared, context-free checks for residual OCR and parser text corruption."""

from __future__ import annotations

import re


OCR_NOISE_PATTERN = re.compile(
    r"(?:0[卜ㅏ]|(?<![A-Za-z])[O0]h(?![A-Za-z])|[卜入人]{2,}|으\s*(?:9|느|그)|으\s+거|"
    r"[가-힣A-Za-z][卜入人][가-힣A-Za-z]|[튢飇恤喬盞])"
)
BROKEN_UNIT_PATTERN = re.compile(
    r"\[(?:0/해|Ⅵ|H기|시|외|P비|kg되|넣디|Q|\(\)|\))"
)


def text_quality_issue_codes(text: str) -> tuple[str, ...]:
    """Return stable issue codes for corruption that should not be guessed away."""

    value = str(text or "")
    codes: list[str] = []
    if OCR_NOISE_PATTERN.search(value):
        codes.append("ocr_noise")
    if BROKEN_UNIT_PATTERN.search(value):
        codes.append("broken_unit")
    if has_unbalanced_delimiters(value):
        codes.append("unbalanced_delimiter")
    return tuple(codes)


def has_unbalanced_delimiters(text: str) -> bool:
    """Detect unbalanced round/square brackets while allowing common labels."""

    value = str(text or "")
    if not value:
        return False

    paren_depth = 0
    extra_close = 0
    for index, char in enumerate(value):
        if char == "(":
            paren_depth += 1
        elif char == ")":
            if paren_depth:
                paren_depth -= 1
            elif not re.search(
                r"(?:\d+|(?:Ex|Example|Fig|No)\.)\s*$",
                value[:index],
                re.IGNORECASE,
            ):
                extra_close += 1
    return paren_depth != 0 or extra_close != 0 or value.count("[") != value.count("]")
