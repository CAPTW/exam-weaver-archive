# Keyword-based hashtag tagger for questions.

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional


_TAG_RULES = [
    ("#이미지", [r"그림", r"도표", r"그래프", r"사진", r"\bfig\.?\b", r"\bdiagram\b", r"\bchart\b", r"\bgraph\b"]),
    ("#계산", [r"계산", r"구하", r"산출", r"값", r"비율", r"속력", r"rpm", r"토크", r"압력", r"온도", r"효율", r"유량"]),
    ("#법규", [r"법규", r"규정", r"규칙", r"조항", r"법령", r"시행령", r"시행규칙", r"기준"]),
    ("#안전", [r"안전", r"사고", r"위험", r"주의", r"비상", r"화재", r"재해", r"응급"]),
    ("#정비", [r"정비", r"점검", r"수리", r"교체", r"오버홀"]),
    ("#항해", [r"항해", r"침로", r"선위", r"방위", r"레이더", r"레이다", r"gps", r"해도", r"좌표", r"위도", r"경도"]),
    ("#기관", [r"기관", r"엔진", r"디젤", r"보일러", r"터빈", r"연료", r"윤활", r"냉각", r"펌프", r"피스톤", r"밸브"]),
    ("#전기", [r"전기", r"전압", r"전류", r"회로", r"저항", r"발전기", r"모터", r"배터리", r"변압기"]),
    ("#화물", [r"화물", r"적재", r"하역", r"적하", r"복원", r"흘수", r"톤수", r"밸러스트", r"\bcargo\b"]),
    ("#통신", [r"통신", r"무전", r"\bvhf\b", r"mayday", r"pan-?pan", r"securite"]),
    ("#기상", [r"기상", r"바람", r"파고", r"기온", r"기압", r"해류", r"조류"]),
]

_COMPILED_RULES = [
    (tag, [re.compile(p, re.IGNORECASE) for p in patterns]) for tag, patterns in _TAG_RULES
]


def _normalize_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower()


def _clean_tag(tag: str) -> Optional[str]:
    if not tag:
        return None
    tag = tag.strip()
    if not tag:
        return None
    if not tag.startswith("#"):
        tag = "#" + tag
    tag = re.sub(r"[\\s/()\\[\\]{}<>]+", "", tag)
    return tag


def _choices_to_text(choices: Optional[Iterable]) -> str:
    if not choices:
        return ""
    parts = []
    for c in choices:
        if isinstance(c, dict):
            parts.append(c.get("choice_text", "") or "")
        else:
            parts.append(getattr(c, "text", "") or str(c))
    return " ".join(p for p in parts if p)


def build_tags(
    question_text: Optional[str],
    choices: Optional[Iterable] = None,
    subject_name: Optional[str] = None,
    exam_type: Optional[str] = None,
    has_image: bool = False,
) -> str:
    """Return comma-separated hashtag string based on keywords and metadata."""
    tags = []

    def add(tag: Optional[str]) -> None:
        if not tag:
            return
        if tag not in tags:
            tags.append(tag)

    add(_clean_tag(exam_type) if exam_type else None)
    add(_clean_tag(subject_name) if subject_name else None)
    if has_image:
        add("#이미지")

    blob = " ".join(
        t for t in (
            _normalize_text(question_text),
            _normalize_text(_choices_to_text(choices)),
        ) if t
    )

    if blob:
        for tag, patterns in _COMPILED_RULES:
            if any(p.search(blob) for p in patterns):
                add(tag)

    return ", ".join(tags)
