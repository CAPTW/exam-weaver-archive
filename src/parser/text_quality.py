"""Shared, context-free checks for residual OCR and parser text corruption."""

from __future__ import annotations

import re

from .formatting import ENGLISH_OCR_TOKEN_REPLACEMENTS, OCR_EXACT_PHRASE_REPLACEMENTS


OCR_NOISE_PATTERN = re.compile(
    r"(?:다읔|디음|다음°|오으\s*것|오은\s+거\s+은|0[卜ㅏ]|(?<![A-Za-z])[O0]h(?![A-Za-z])|[卜入人]{2,}|으\s*(?:9|느|그)|으\s+거|"
    r"[가-힣A-Za-z][卜入人][가-힣A-Za-z]|[튢飇恤喬盞]|"
    r"[가-힣]°[°。]?[가-힣]|(?<=[a-z])¯(?=[a-z])|"
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
COMPACT_ENGINEERING_FORMULA_PATTERN = re.compile(
    r"[A-Za-z0-9_+\-*/^().=\s]+"
)
KNOWN_ENGLISH_OCR_CONFUSABLE_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])(?:"
    + "|".join(
        re.escape(token)
        for token in sorted(ENGLISH_OCR_TOKEN_REPLACEMENTS, key=len, reverse=True)
    )
    + r")(?![0-9A-Za-z])"
)
KNOWN_OCR_PHRASE_PATTERN = re.compile(
    "|".join(
        re.escape(token)
        for token in sorted(OCR_EXACT_PHRASE_REPLACEMENTS, key=len, reverse=True)
    )
)
VALID_ROMAN_ANNOTATION_PATTERN = re.compile(
    r"(?<![0-9A-Za-z])[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ](?=(?:의)?(?:\s|[.,:;)\]」]|$))"
)
VALID_ROMAN_KOREAN_CONTEXT_PATTERN = re.compile(
    r"제[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+-\d+장|"
    r"(?:제|부속서\s*)[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+"
    r"(?=(?:장(?:의)?|에서(?:의)?|에|으로|의|상))|"
    r"(?<![0-9A-Za-z가-힣])[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]"
    r"(?=(?:에서(?:의)?|에|으로|에게|에는|에도|은|는|이|가|을|를|의|과|와|상|하))"
)
MIXED_ROMAN_OCR_PATTERN = re.compile(
    r"(?:[0-9A-Za-z가-힣*#()\\][ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ]"
    r"|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹ][0-9A-Za-z가-힣*#()\\])"
)
VALID_HANGUL_NUMBER_PATTERN = re.compile(
    r"제\d+(?=[가-힣])|"
    r"\d+(?:년|개월|일|시간|분|초|회|개|명|인|척|톤|미터|해리|단계|급|종)"
)
VALID_MIXED_SCRIPT_TERM_PATTERN = re.compile(
    r"(?:지진파의[SP]파|A1해역|A2해역|A3해역|A4해역)"
)
VALID_CJK_ANNOTATION_PATTERN = re.compile(
    r"[（(](?=[가-힣一-龥\s,·/]{1,32}[)）])"
    r"(?=[^()）]*[一-龥])[가-힣一-龥\s,·/]{1,32}[)）]"
)
VALID_CJK_PARTY_PATTERN = re.compile(
    r"(?<![0-9A-Za-z가-힣一-龥])[甲乙丙丁]"
    r"(?=(?:(?:선장|경장|씨|어선|소유자|사업자|회사))?"
    r"(?:에게서|에게|은|는|이|가|을|를|의|과|와|도|만)?"
    r"(?:\s|[,.!?·:;)]|$))"
)
CJK_PATTERN = re.compile(r"[一-龥]")
DAMAGED_LIST_MARKER_PATTERN = re.compile(
    r"(?m)^\s*@(?=\s*[A-Za-z가-힣])"
)
REPEATED_CIRCLED_NUMBER_OCR_PATTERN = re.compile(
    r"([①-⑳])(?:\s+\1)+"
)
COUNTING_LIST_PROMPT_PATTERN = re.compile(
    r"(?:모두|총)\s*몇\s*(?:개|가지|명|척)"
)
EXPLICIT_VIEW_PATTERN = re.compile(r"<\s*보\s*기\s*>")
VALID_LIST_MARKER_PATTERN = re.compile(
    r"(?<!\S)(?:"
    r"[ㄱ-ㅎ][.)]|[㉠-㉻Ⓐ-Ⓩⓐ-ⓩ①-⑳]|"
    r"\((?:[A-Za-z]|\d{1,2})\)|"
    r"[A-Ia-i][.)](?=\s)"
    r")"
)
MIN_STRUCTURED_LIST_COLONS = 4
MIN_VALID_LIST_MARKERS = 3


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
        or has_english_ocr_confusable(value)
        or KNOWN_ENGLISH_OCR_CONFUSABLE_PATTERN.search(value)
        or KNOWN_OCR_PHRASE_PATTERN.search(value)
        or has_mixed_roman_ocr(value)
        or has_intrusive_latin_digit_ocr(value)
        or has_intrusive_cjk_ocr(value)
        or REPEATED_CIRCLED_NUMBER_OCR_PATTERN.search(value)
    ):
        codes.append("ocr_noise")
    if BROKEN_UNIT_PATTERN.search(value):
        codes.append("broken_unit")
    if has_damaged_list_marker(value):
        codes.append("damaged_list_marker")
    if has_unbalanced_delimiters(value):
        codes.append("unbalanced_delimiter")
    return tuple(codes)


def has_english_ocr_confusable(text: str) -> bool:
    """Detect OCR-like digits in English words, excluding compact formulas."""

    value = str(text or "").strip()
    if (
        COMPACT_ENGINEERING_FORMULA_PATTERN.fullmatch(value)
        and re.search(r"[()+\-*/^=]", value)
        and re.search(r"\d", value)
    ):
        return False
    return bool(ENGLISH_OCR_CONFUSABLE_PATTERN.search(value))


def has_damaged_list_marker(text: str) -> bool:
    """Detect damaged or missing markers in a printed counting list.

    Besides the common OCR ``@`` substitution, scanned maritime questions can
    turn a whole ``ㄱ``-through-``ㅇ`` sequence into arbitrary letters, digits,
    and punctuation.  A counting prompt followed by several colon-delimited
    definitions must retain a recognizable marker sequence unless it is an
    explicit ``<보기>`` block.
    """

    value = str(text or "")
    if DAMAGED_LIST_MARKER_PATTERN.search(value):
        return True
    if (
        not COUNTING_LIST_PROMPT_PATTERN.search(value)
        or value.count(":") < MIN_STRUCTURED_LIST_COLONS
        or EXPLICIT_VIEW_PATTERN.search(value)
    ):
        return False
    return len(VALID_LIST_MARKER_PATTERN.findall(value)) < MIN_VALID_LIST_MARKERS


def has_mixed_roman_ocr(text: str) -> bool:
    """Detect Roman numeral glyphs embedded in OCR-corrupted word tokens."""

    value = VALID_ROMAN_KOREAN_CONTEXT_PATTERN.sub("", str(text or ""))
    value = VALID_ROMAN_ANNOTATION_PATTERN.sub("", value)
    return bool(MIXED_ROMAN_OCR_PATTERN.search(value))


def has_intrusive_latin_digit_ocr(text: str) -> bool:
    """Detect stray OCR ``0/1/I/L`` characters embedded in Korean words.

    Valid legal numbers, units, and domain labels are stripped first. This is
    deliberately narrower than a generic mixed-script check because maritime
    questions legitimately contain many formulas and alphanumeric identifiers.
    """

    value = VALID_HANGUL_NUMBER_PATTERN.sub("", str(text or ""))
    value = VALID_MIXED_SCRIPT_TERM_PATTERN.sub("", value)
    return bool(
        re.search(r"[가-힣](?:[01IL]|[A-Za-z]{1,3})[가-힣]", value)
        or re.search(r"[가-힣]\)(?:7b)(?=\s|[가-힣])", value)
    )


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
