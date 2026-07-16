"""Shared, context-free checks for residual OCR and parser text corruption."""

from __future__ import annotations

import re


OCR_NOISE_PATTERN = re.compile(
    r"(?:다읔|디음|오으\s*것|0[卜ㅏ]|(?<![A-Za-z])[O0]h(?![A-Za-z])|[卜入人]{2,}|으\s*(?:9|느|그)|으\s+거|"
    r"[가-힣A-Za-z][卜入人][가-힣A-Za-z]|[튢飇恤喬盞]|"
    r"\}[~=`^|\s]*[O0]\s*[가-힣ㄱ-ㅎㅏ-ㅣ]|"
    r"(?<![A-Za-z])r(?=[가-힣]{2,}법\])|[己呑粼訃])"
)
BROKEN_UNIT_PATTERN = re.compile(
    r"\[(?:0/해|Ⅵ|H기|시|외|P비|kg되|넣디|Q|\(\)|\))"
)
ENGLISH_OCR_CONFUSABLE_PATTERN = re.compile(
    r"(?:\b(?:t0|0f|A11|011e|S0011)\b|"
    r"\b[A-Za-z]{1,12}[01]+[A-Za-z][A-Za-z01]*\b|"
    r"\b[A-Za-z][A-Za-z01]*[01]+[A-Za-z]{1,12}\b|"
    r"(?<=[A-Za-z])[㈜ⅰ-ⅹ殂盞飇恤喬訃粼](?=[A-Za-z]))"
)
VALID_CJK_ANNOTATION_PATTERN = re.compile(r"[（(][一-龥]{1,16}[)）]")
VALID_CJK_PARTY_PATTERN = re.compile(
    r"(?<![0-9A-Za-z가-힣一-龥])[甲乙丙丁]"
    r"(?=(?:(?:선장|경장|씨|어선|소유자|사업자|회사))?"
    r"(?:에게서|에게|은|는|이|가|을|를|의|과|와|도|만)?"
    r"(?:\s|[,.!?·:;)]|$))"
)
CJK_PATTERN = re.compile(r"[一-龥]")


def has_intrusive_cjk_ocr(text: str) -> bool:
    """Detect CJK glyphs injected into Korean/English OCR prose.

    Maritime questions legitimately retain short Hanja annotations such as
    ``수상(水上)`` and party labels such as ``甲``.  Other CJK glyphs embedded
    directly in prose, or mixed-script parentheticals such as
    ``(匁k害通航)``, are high-confidence scan corruption.
    """

    value = VALID_CJK_ANNOTATION_PATTERN.sub("", str(text or ""))
    value = VALID_CJK_PARTY_PATTERN.sub("", value)
    return bool(CJK_PATTERN.search(value))


def text_quality_issue_codes(text: str) -> tuple[str, ...]:
    """Return stable issue codes for corruption that should not be guessed away."""

    value = str(text or "")
    codes: list[str] = []
    if (
        OCR_NOISE_PATTERN.search(value)
        or ENGLISH_OCR_CONFUSABLE_PATTERN.search(value)
        or has_intrusive_cjk_ocr(value)
    ):
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
                r"(?:^|[^0-9A-Za-z가-힣])(?:[A-Za-z]|[ivxIVX]{1,4}|\d+|(?:Ex|Example|Fig|No)\.)\s*$",
                value[:index],
                re.IGNORECASE,
            ):
                extra_close += 1
    return paren_depth != 0 or extra_close != 0 or value.count("[") != value.count("]")
