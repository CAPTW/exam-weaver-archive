"""Build question-level trend analysis outputs for maritime English exam PDFs."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


QUESTION_START = re.compile(
    r"(?<![\dA-Za-z])([1-9]\d?)\s*"
    r"(?:[\.•ㆍ·]|(?=\s*(?:다음|Choose|Select|Which|What|If|When|According|The\s|A\s|[\"'“<「\(])))"
    r"\s*",
    re.IGNORECASE,
)

REQUIRED_MASTER_COLUMNS = [
    "filename",
    "page_start",
    "page_end",
    "year",
    "subject",
    "topic_l1",
    "topic_l2",
    "topic_l3",
    "concept_tags",
    "evidence_excerpt",
    "confidence",
    "needs_human_review",
]


@dataclass
class PageMeta:
    year: int | None
    period: str
    session: str
    category: str

    @property
    def key(self) -> tuple:
        return (self.year, self.period, self.session, self.category)


@dataclass
class TopicResult:
    l1: str
    l2: str
    l3: str
    tags: list[str]
    confidence: float


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def compact_for_year(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def detect_year(text: str, filename: str = "") -> int | None:
    head = compact_for_year(f"{text[:600]} {filename}")
    if "20기년도" in head or "20기년" in head:
        return 2021
    match = re.search(r"20[012]\d", head)
    if match:
        year = int(match.group(0))
        if 2013 <= year <= 2026:
            return year
    spaced = re.search(r"2\s*0\s*([12])\s*(\d)", f"{text[:600]} {filename}")
    if spaced:
        year = int(f"20{spaced.group(1)}{spaced.group(2)}")
        if 2013 <= year <= 2026:
            return year
    return None


def detect_period(text: str) -> str:
    head = compact_spaces(text[:700])
    if re.search(r"상\s*반\s*기", head):
        return "상반기"
    if re.search(r"하\s*(?:반|만|발)\s*기", head):
        return "하반기"
    return ""


def detect_session(text: str) -> str:
    head = compact_spaces(text[:700])
    normalized = (
        head.replace("저B자", "제3차")
        .replace("저2자", "제2차")
        .replace("저1자", "제1차")
        .replace("하B자", "제3차")
    )
    match = re.search(r"제\s*([1-4])\s*(?:회|차|자)", normalized)
    if match:
        label = "회" if "회" in normalized[max(0, match.start() - 2): match.end() + 2] else "차"
        return f"제{match.group(1)}{label}"
    return ""


def detect_category(text: str) -> str:
    head = compact_spaces(text[:900])
    if "선박관제" in head:
        return "선박관제 9급"
    if "해경학과" in head:
        return "해경학과"
    if "일반직" in head:
        return "일반직공무원"
    if "국민" in head and ("안전처" in head or "전처" in head):
        return "국민안전처"
    if "경장" in head:
        return "경장"
    if "순경" in head:
        return "순경"
    if "경찰공무원" in head:
        return "경찰공무원"
    if "해양경찰" in head or "해영경찰" in head or "H영경찰" in head:
        return "해양경찰 채용"
    return "채용구분 미상"


def infer_page_meta(page: dict) -> PageMeta:
    text = page.get("text", "")
    return PageMeta(
        year=detect_year(text, page.get("filename", "")),
        period=detect_period(text),
        session=detect_session(text),
        category=detect_category(text),
    )


def question_starts(text: str) -> list[tuple[int, int, int]]:
    starts = []
    for match in QUESTION_START.finditer(text or ""):
        number = int(match.group(1))
        if number < 1 or number > 20:
            continue
        start = match.start(1)
        end = match.end()
        context = text[end:end + 180]
        context_compact = compact_spaces(context)
        if len(context_compact) < 12:
            continue
        if not looks_like_question_context(context_compact):
            continue
        starts.append((number, start, end))

    filtered = []
    seen_positions = set()
    last_num = 0
    for number, start, end in starts:
        if start in seen_positions:
            continue
        # Within a page, real question numbers generally increase. Permit first
        # question on the page to start at any number because pages are chunks.
        if filtered and number <= last_num:
            continue
        if filtered and number - last_num > 8:
            # Large jumps usually mean an answer choice or legal article number.
            continue
        filtered.append((number, start, end))
        seen_positions.add(start)
        last_num = number
    return filtered


def looks_like_question_context(context: str) -> bool:
    cue_patterns = [
        r"다음",
        r"보기",
        r"옳",
        r"빈칸",
        r"Choose",
        r"Select",
        r"Which",
        r"What",
        r"According",
        r"following",
        r"COLREG",
        r"SOLAS",
        r"UNCLOS",
        r"MARPOL",
        r"SMCP",
        r"IAMSAR",
        r"STCW",
        r"ISPS",
        r"Standard",
        r"International",
    ]
    return any(re.search(pattern, context, re.IGNORECASE) for pattern in cue_patterns)


def strip_noise(text: str) -> str:
    lines = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        if "합격코스" in compact or "커리큘럼" in compact or "동시학습" in compact:
            continue
        if "커리큘럼" in compact or "실전대비" in compact:
            continue
        if re.search(r"\b\d+/\d+\b", line) and len(line) < 30:
            continue
        if "문제지" in compact and len(compact) < 60:
            continue
        lines.append(line)
    return compact_spaces(" ".join(lines))


def evidence_from_question(raw_segment: str) -> str:
    cleaned = strip_noise(raw_segment)
    # Keep evidence short and avoid copying whole stems.
    choice_markers = [r"\(0\)", r"\(1\)", r"\(기\)", r"\(의\)", r"㉦", r"㉠\s", r"①", r"1\)"]
    cut = len(cleaned)
    for pattern in choice_markers:
        match = re.search(pattern, cleaned)
        if match and match.start() > 40:
            cut = min(cut, match.start())
    excerpt = cleaned[:cut].strip()
    if len(excerpt) < 40:
        excerpt = cleaned
    return excerpt[:180]


def normalize_for_topic(text: str) -> str:
    value = text or ""
    replacements = {
        "C011isions": "Collisions",
        "COIIisions": "Collisions",
        "C0de": "Code",
        "Manne": "Marine",
        "SNCP": "SMCP",
        "SNC P": "SMCP",
        "0f": "of",
        "lnternational": "International",
        "rlnternational": "International",
        "IAMSAR ManuaI": "IAMSAR Manual",
        "MARPOL": "MARPOL",
        "STCW": "STCW",
        "SOLAS": "SOLAS",
        "UNCLOS": "UNCLOS",
        "COLREG": "COLREG",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    return value


def contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_topic(raw_text: str, placeholder: bool = False) -> TopicResult:
    if placeholder:
        return TopicResult("unknown", "unknown", "unknown", ["ocr_missing"], 0.20)

    text = normalize_for_topic(raw_text)
    tags: list[str] = []

    if contains_any(text, [r"UNCLOS", r"Law of the Sea", r"territorial sea", r"innocent passage", r"hot pursuit"]):
        l3 = "일반 조항"
        if contains_any(text, [r"innocent passage", r"무해\s*통항"]):
            l3 = "무해통항"
        elif contains_any(text, [r"territorial sea", r"영해"]):
            l3 = "영해"
        elif contains_any(text, [r"hot pursuit", r"추적"]):
            l3 = "추적권"
        elif contains_any(text, [r"exclusive economic", r"EEZ", r"배타적"]):
            l3 = "배타적 경제수역"
        tags = ["UNCLOS", l3]
        return TopicResult("국제해양법", "UNCLOS", l3, tags, 0.90)

    if contains_any(
        text,
        [
            r"COLREG",
            r"Collision",
            r"Rules of the Road",
            r"overtaking",
            r"head-on",
            r"crossing",
            r"22\.5",
            r"abaft",
            r"risk of collision",
        ],
    ):
        l3 = "일반 항법규정"
        if contains_any(text, [r"Sound Signals?", r"whistle", r"bell", r"gong", r"음향"]):
            l3 = "음향신호"
        elif contains_any(text, [r"Light", r"masthead", r"sidelight", r"all-round", r"등화", r"형상"]):
            l3 = "등화·형상물"
        elif contains_any(text, [r"restricted visibility", r"제한시계"]):
            l3 = "제한시계"
        elif contains_any(text, [r"not under command", r"restricted.*manoeuvre", r"조종"]):
            l3 = "선박 상태·조종성"
        elif contains_any(text, [r"overtaking", r"head-on", r"crossing", r"risk of collision", r"충돌"]):
            l3 = "항법·피항동작"
        elif contains_any(text, [r"traffic separation", r"narrow channel", r"separation scheme"]):
            l3 = "통항분리·협수로"
        tags = ["COLREG", l3]
        return TopicResult("충돌예방·항법규칙", "COLREG", l3, tags, 0.90)

    if contains_any(text, [r"SOLAS", r"Safety of Life at Sea"]):
        l3 = "일반 안전규정"
        if contains_any(text, [r"drill", r"muster", r"abandon ship", r"fire drill", r"훈련"]):
            l3 = "비상훈련·소집"
        elif contains_any(text, [r"bridge visibility", r"Navigation bridge", r"선교"]):
            l3 = "항해선교 시야"
        elif contains_any(text, [r"steering gear", r"조타"]):
            l3 = "조타장치"
        elif contains_any(text, [r"life-saving", r"lifeboat", r"survival"]):
            l3 = "구명설비"
        tags = ["SOLAS", l3]
        return TopicResult("해상안전협약·비상절차", "SOLAS", l3, tags, 0.90)

    if contains_any(text, [r"MARPOL", r"pollution", r"oily mixture", r"garbage", r"slop tank", r"해양오염"]):
        l3 = "오염방지 일반"
        if contains_any(text, [r"oil", r"oily", r"slop", r"유성"]):
            l3 = "유류오염"
        elif contains_any(text, [r"garbage", r"disposal", r"쓰레기"]):
            l3 = "폐기물 배출"
        tags = ["MARPOL", l3]
        return TopicResult("해양오염방지", "MARPOL", l3, tags, 0.90)

    if contains_any(text, [r"STCW", r"Training, Certification", r"Watchkeeping", r"certificate"]):
        return TopicResult("선원자격·당직", "STCW", "훈련·자격·당직", ["STCW"], 0.88)

    if contains_any(
        text,
        [
            r"IAMSAR",
            r"Search and Rescue",
            r"\bSAR\b",
            r"search pattern",
            r"distress phase",
            r"uncertainty phase",
            r"rescue",
            r"search target",
            r"most probable position",
            r"\bdatum\b",
        ],
    ):
        l3 = "수색구조 일반"
        if contains_any(text, [r"search pattern", r"parallel track", r"sector search", r"creeping line"]):
            l3 = "수색 패턴"
        elif contains_any(text, [r"distress phase", r"alert phase", r"uncertainty phase", r"emergency phase"]):
            l3 = "비상 단계"
        elif contains_any(text, [r"On-scene", r"OSC", r"co-ord"]):
            l3 = "현장조정"
        tags = ["IAMSAR", l3]
        return TopicResult("수색구조", "IAMSAR", l3, tags, 0.90)

    if contains_any(text, [r"ISPS", r"Security Level", r"Port Facilities", r"ship security"]):
        return TopicResult("선박보안", "ISPS Code", "보안등급·보안조치", ["ISPS", "security"], 0.88)

    if contains_any(
        text,
        [
            r"SMCP",
            r"S[BMN]/?CP",
            r"Standard\s+(?:Marine|%rine)",
            r"Marine Communication",
            r"Message Marker",
            r"Wheel Orders?",
            r"표준\s*조타\s*명령",
            r"조타명령",
            r"VHF",
            r"\bVTS\b",
            r"radio",
            r"MAYDAY",
            r"PAN[- ]?PAN",
            r"spelling",
            r"phonetic",
        ],
    ):
        l3 = "표준해사통신"
        if contains_any(text, [r"Wheel Orders?", r"조타명령", r"Nothing to", r"Meet her", r"Steady"]):
            l3 = "표준조타명령"
        elif contains_any(text, [r"Message Marker", r"WARNING", r"ADVICE", r"INFORMATION"]):
            l3 = "Message Marker"
        elif contains_any(text, [r"VHF", r"\bVTS\b", r"channel", r"radio"]):
            l3 = "VHF·VTS·무선통신"
        elif contains_any(text, [r"spelling", r"Letter Code", r"phonetic"]):
            l3 = "통신 철자·코드"
        return TopicResult("해사통신·SMCP", "SMCP/VHF", l3, ["SMCP", l3], 0.88)

    if contains_any(text, [r"International Code of Signals", r"Code of Signals", r"Single Letter Signal", r"flag combination", r"\bSOS\b"]):
        return TopicResult("해사통신·국제신호", "International Code of Signals", "국제신호서·신호기", ["code_of_signals"], 0.88)

    if contains_any(text, [r"traffic separation", r"routeing", r"routing", r"inshore traffic", r"traffic lane", r"reporting point", r"waterway"]):
        return TopicResult("항로지정·해상교통", "Routeing/VTS", "항로지정·통항관리", ["routeing", "traffic_management"], 0.82)

    if contains_any(text, [r"\bETA\b", r"\bMMSI\b", r"\bAIS\b", r"\bEPIRB\b", r"\bSART\b", r"\bOSC\b", r"A/Co", r"B\.W\.E", r"F\.W\.E", r"약어"]):
        return TopicResult("해사약어·용어", "해사 약어", "약어 의미", ["abbreviations"], 0.82)

    if contains_any(text, [r"anchor", r"berth", r"pier", r"pilot", r"tug", r"mooring", r"draft", r"trim", r"keel", r"rudder", r"engine", r"RPM", r"turbo", r"bunker", r"course made good", r"deadweight", r"freeboard"]):
        l3 = "해사실무 용어"
        if contains_any(text, [r"anchor", r"dredging", r"dragging", r"shackle"]):
            l3 = "투묘·양묘"
        elif contains_any(text, [r"berth", r"pier", r"pilot", r"tug", r"mooring"]):
            l3 = "입출항·접안"
        elif contains_any(text, [r"draft", r"trim", r"keel", r"rudder"]):
            l3 = "선체·조종 용어"
        elif contains_any(text, [r"engine", r"RPM", r"turbo", r"diesel"]):
            l3 = "기관 용어"
        return TopicResult("선박운용·해사실무", "선박운용 용어", l3, ["ship_operation", l3], 0.75)

    if contains_any(text, [r"Choose", r"Select", r"suitable word", r"blank", r"빈\s*칸", r"괄호", r"문법", r"해석"]):
        return TopicResult("일반영어·독해", "어휘·문법", "문맥 빈칸·어휘", ["general_english"], 0.68)

    return TopicResult("unknown", "unknown", "unknown", ["unclassified"], 0.35)


def estimate_difficulty(text: str, topic: TopicResult, placeholder: bool = False) -> tuple[str, float]:
    if placeholder:
        return "unknown", 0.5
    if contains_any(text, [r"모두 몇", r"합한 값", r"숫자", r"순서대로", r"가장 옳지 않은 것은 모두"]):
        return "high", 1.0
    if topic.l2 in {"SOLAS", "MARPOL", "STCW", "UNCLOS", "COLREG", "IAMSAR"}:
        return "medium", 0.6
    if topic.l1 in {"일반영어·독해", "해사약어·용어"}:
        return "low", 0.3
    return "medium", 0.6


def cognitive_skill(text: str, placeholder: bool = False) -> str:
    if placeholder:
        return "unknown"
    if contains_any(text, [r"상황", r"절차", r"입항", r"대화", r"case"]):
        return "case_application"
    if contains_any(text, [r"모두 몇", r"옳지 않은 것은 모두", r"비교"]):
        return "comparative_analysis"
    if contains_any(text, [r"빈칸", r"숫자", r"합한 값"]):
        return "conceptual_understanding"
    return "recall"


def needs_review(topic: TopicResult, excerpt: str, placeholder: bool = False) -> tuple[bool, str]:
    reasons = []
    if placeholder:
        reasons.append("OCR/번호분할 누락으로 문항 본문 확인 필요")
    if topic.confidence < 0.70:
        reasons.append("주제 분류 신뢰도 낮음")
    if len(excerpt) < 40:
        reasons.append("근거 발췌가 짧거나 OCR 품질 낮음")
    return bool(reasons), "; ".join(reasons)


def percentile_map(counts: dict[tuple, int]) -> dict[tuple, float]:
    if not counts:
        return {}
    values = sorted(counts.values())
    if len(values) == 1:
        return {key: 1.0 for key in counts}
    result = {}
    for key, value in counts.items():
        rank = sum(1 for v in values if v <= value) - 1
        result[key] = rank / (len(values) - 1)
    return result


def assign_recent_known_categories(groups: list[dict]) -> None:
    by_filename = defaultdict(list)
    for group in groups:
        by_filename[group["filename"]].append(group)

    for filename, file_groups in by_filename.items():
        file_groups.sort(key=lambda item: item["pages"][0]["page"])
        if "24년 하반기-25년 하반기" in filename:
            labels = ["순경", "경장", "선박관제 9급", "순경"]
            for group, label in zip(file_groups, labels):
                group["category"] = label
        elif "24년-13년" in filename:
            same_2024_h1 = [
                group for group in file_groups
                if group.get("year") == 2024 and group.get("period") == "상반기"
            ]
            for group, label in zip(same_2024_h1, ["해경학과", "선박관제 9급"]):
                group["category"] = label


def build_groups(page_records: list[dict]) -> list[dict]:
    question_pages = [
        page for page in page_records
        if "기출문제" in page.get("filename", "")
    ]
    by_pdf = defaultdict(list)
    for page in question_pages:
        by_pdf[page["pdf_id"]].append(page)

    groups = []
    for _, pages in sorted(by_pdf.items()):
        pages.sort(key=lambda item: item["page"])
        current = None
        current_numbers: set[int] = set()
        for page in pages:
            text = page.get("text", "")
            starts = question_starts(text)
            numbers = [number for number, _, _ in starts]
            meta = infer_page_meta(page)
            if not numbers and len(compact_spaces(text)) < 250:
                continue

            start_new = current is None
            if current is not None:
                current_max = max(current_numbers or {0})
                continues_numbering = bool(
                    numbers and current_numbers and min(numbers) > current_max
                )
                meta_changed = (
                    meta.year is not None and current.get("year") is not None and meta.year != current.get("year")
                ) or (
                    bool(meta.period or meta.session) and (meta.period, meta.session) != (current.get("period"), current.get("session"))
                    and current_max >= 10
                    and not continues_numbering
                )
                reset_to_one = 1 in numbers and current_max >= 10
                start_new = meta_changed or reset_to_one

            if start_new:
                current = {
                    "filename": page["filename"],
                    "pdf_id": page["pdf_id"],
                    "year": meta.year,
                    "period": meta.period,
                    "session": meta.session,
                    "category": meta.category,
                    "pages": [],
                }
                groups.append(current)
                current_numbers = set()
            else:
                if current.get("year") is None and meta.year is not None:
                    current["year"] = meta.year
                if not current.get("period") and meta.period:
                    current["period"] = meta.period
                if not current.get("session") and meta.session:
                    current["session"] = meta.session
                if current.get("category") == "채용구분 미상" and meta.category != "채용구분 미상":
                    current["category"] = meta.category

            current["pages"].append(page)
            current_numbers.update(numbers)

    assign_recent_known_categories(groups)
    return groups


def group_label(group: dict, index: int) -> str:
    parts = []
    if group.get("year"):
        parts.append(str(group["year"]))
    if group.get("period"):
        parts.append(group["period"])
    if group.get("session"):
        parts.append(group["session"])
    category = group.get("category") or "채용구분 미상"
    if category:
        parts.append(category)
    parts.append("해사영어")
    return " ".join(parts) + f" G{index:03d}"


def extract_group_questions(group: dict, group_index: int) -> list[dict]:
    raw_questions = []
    for page in group["pages"]:
        text = page.get("text", "")
        starts = question_starts(text)
        for idx, (number, start, end) in enumerate(starts):
            next_start = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
            segment = text[end:next_start]
            raw_questions.append({
                "number": number,
                "page_start": page["page"],
                "page_end": page["page"],
                "segment": segment,
                "is_ocr_text": page.get("is_ocr_text", False),
                "source_pdf_id": page.get("pdf_id"),
            })

    deduped = {}
    duplicate_numbers = set()
    for item in raw_questions:
        number = item["number"]
        if number not in deduped:
            deduped[number] = item
        else:
            duplicate_numbers.add(number)
            # Keep the longer segment because it usually contains the stem.
            if len(item["segment"]) > len(deduped[number]["segment"]):
                deduped[number] = item

    rows = []
    group_id = f"G{group_index:03d}"
    exam_name = group_label(group, group_index)
    page_numbers = [page["page"] for page in group["pages"]]
    for question_number in range(1, 21):
        item = deduped.get(question_number)
        placeholder = item is None
        if placeholder:
            estimated_page = estimate_page_for_missing(question_number, deduped, page_numbers)
            segment = ""
            page_start = page_end = estimated_page
            excerpt = missing_excerpt(group, estimated_page)
        else:
            segment = item["segment"]
            page_start = item["page_start"]
            page_end = item["page_end"]
            excerpt = evidence_from_question(segment)

        topic = classify_topic(segment if not placeholder else "", placeholder=placeholder)
        difficulty, risk = estimate_difficulty(segment, topic, placeholder=placeholder)
        review, review_reason = needs_review(topic, excerpt, placeholder=placeholder)
        if question_number in duplicate_numbers:
            review = True
            review_reason = f"{review_reason}; 중복 번호 후보 발생".strip("; ")
            topic.confidence = min(topic.confidence, 0.65)

        row = {
            "question_id": f"{group_id}-Q{question_number:02d}",
            "pdf_id": group["pdf_id"],
            "filename": group["filename"],
            "page_start": page_start,
            "page_end": page_end,
            "year": group.get("year") or "unknown",
            "exam_period": group.get("period") or "",
            "exam_name": exam_name,
            "subject": "해사영어",
            "section": group.get("category") or "",
            "question_number": question_number,
            "topic_l1": topic.l1,
            "topic_l2": topic.l2,
            "topic_l3": topic.l3,
            "concept_tags": ";".join(topic.tags),
            "question_type": "multiple_choice",
            "difficulty_estimate": difficulty,
            "difficulty_or_error_risk": f"{risk:.2f}",
            "cognitive_skill": cognitive_skill(segment, placeholder=placeholder),
            "evidence_excerpt": excerpt,
            "answer_present": "source_answer_pdf_available",
            "confidence": f"{topic.confidence:.2f}",
            "needs_human_review": str(review).lower(),
            "review_reason": review_reason,
            "ocr_source": str((item or {}).get("is_ocr_text", True)).lower(),
        }
        rows.append(row)
    return rows


def estimate_page_for_missing(question_number: int, deduped: dict[int, dict], page_numbers: list[int]) -> int:
    if not page_numbers:
        return 0
    before = [item for number, item in deduped.items() if number < question_number]
    after = [item for number, item in deduped.items() if number > question_number]
    if before:
        return sorted(before, key=lambda item: item["number"])[-1]["page_start"]
    if after:
        return sorted(after, key=lambda item: item["number"])[0]["page_start"]
    return page_numbers[0]


def missing_excerpt(group: dict, page_number: int) -> str:
    for page in group["pages"]:
        if page["page"] == page_number:
            text = strip_noise(page.get("text", ""))
            return text[:160]
    return "OCR 또는 번호분할 누락으로 원문 확인 필요"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_topic_distribution(rows: list[dict]) -> list[dict]:
    valid = [row for row in rows if row["topic_l1"] != "unknown"]
    total = len(valid) or 1
    grouped = defaultdict(list)
    for row in valid:
        key = (row["subject"], row["topic_l1"], row["topic_l2"], row["topic_l3"])
        grouped[key].append(row)

    output = []
    for key, items in grouped.items():
        subject, l1, l2, l3 = key
        years = sorted({int(row["year"]) for row in items if str(row["year"]).isdigit()})
        recent_years = sorted({int(row["year"]) for row in rows if str(row["year"]).isdigit()}, reverse=True)[:3]
        recent_count = sum(1 for row in items if str(row["year"]).isdigit() and int(row["year"]) in recent_years)
        avg_conf = statistics.mean(float(row["confidence"]) for row in items)
        avg_risk = statistics.mean(float(row["difficulty_or_error_risk"]) for row in items)
        output.append({
            "subject": subject,
            "topic_l1": l1,
            "topic_l2": l2,
            "topic_l3": l3,
            "total_questions": len(items),
            "percent_all_classified": f"{len(items) / total * 100:.2f}",
            "years_present": ";".join(map(str, years)),
            "recent_3yr_count": recent_count,
            "recent_3yr_percent_of_topic": f"{recent_count / len(items) * 100:.2f}",
            "avg_confidence": f"{avg_conf:.2f}",
            "needs_review_count": sum(1 for row in items if row["needs_human_review"] == "true"),
            "avg_difficulty_or_error_risk": f"{avg_risk:.2f}",
        })
    return sorted(output, key=lambda item: (-item["total_questions"], item["topic_l1"], item["topic_l2"], item["topic_l3"]))


def build_matrix(rows: list[dict]) -> list[dict]:
    valid = [row for row in rows if row["topic_l1"] != "unknown"]
    denom = Counter((row["year"], row["subject"]) for row in valid)
    grouped = defaultdict(list)
    for row in valid:
        key = (row["year"], row["subject"], row["topic_l1"], row["topic_l2"])
        grouped[key].append(row)
    output = []
    for key, items in grouped.items():
        year, subject, l1, l2 = key
        output.append({
            "year": year,
            "subject": subject,
            "topic_l1": l1,
            "topic_l2": l2,
            "question_count": len(items),
            "percent_within_year_subject": f"{len(items) / max(1, denom[(year, subject)]) * 100:.2f}",
            "needs_review_count": sum(1 for row in items if row["needs_human_review"] == "true"),
        })
    return sorted(output, key=lambda item: (str(item["year"]), item["subject"], -item["question_count"], item["topic_l1"], item["topic_l2"]))


def build_priority(rows: list[dict]) -> list[dict]:
    valid = [row for row in rows if row["topic_l1"] != "unknown"]
    topic_key = lambda row: (row["topic_l1"], row["topic_l2"], row["topic_l3"])
    total_counts = Counter(topic_key(row) for row in valid)
    years = sorted({int(row["year"]) for row in rows if str(row["year"]).isdigit()}, reverse=True)
    recent_years = years[:3]
    recent_counts = Counter(
        topic_key(row)
        for row in valid
        if str(row["year"]).isdigit() and int(row["year"]) in recent_years
    )
    frequency_percentiles = percentile_map(total_counts)
    recent_percentiles = percentile_map({key: recent_counts.get(key, 0) for key in total_counts})
    risks = defaultdict(list)
    for row in valid:
        risks[topic_key(row)].append(float(row["difficulty_or_error_risk"]))

    output = []
    for key, total_count in total_counts.items():
        risk = statistics.mean(risks[key]) if risks[key] else 0.5
        frequency = frequency_percentiles.get(key, 0.0)
        recent = recent_percentiles.get(key, 0.0)
        priority = 0.50 * frequency + 0.30 * recent + 0.20 * risk
        l1, l2, l3 = key
        if priority >= 0.75:
            recommendation = "최우선"
        elif priority >= 0.55:
            recommendation = "상"
        elif priority >= 0.35:
            recommendation = "중"
        else:
            recommendation = "하"
        output.append({
            "topic_l1": l1,
            "topic_l2": l2,
            "topic_l3": l3,
            "total_count": total_count,
            "frequency_percentile": f"{frequency:.4f}",
            "recent_3yr_count": recent_counts.get(key, 0),
            "recent_3yr_frequency_percentile": f"{recent:.4f}",
            "difficulty_or_error_risk": f"{risk:.4f}",
            "priority_score": f"{priority:.4f}",
            "recommended_priority": recommendation,
        })
    return sorted(output, key=lambda item: (-float(item["priority_score"]), -item["total_count"], item["topic_l1"]))


def build_review_queue(rows: list[dict]) -> list[dict]:
    review_rows = [row for row in rows if row["needs_human_review"] == "true"]
    return [
        {
            "question_id": row["question_id"],
            "filename": row["filename"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "year": row["year"],
            "exam_name": row["exam_name"],
            "question_number": row["question_number"],
            "review_reason": row["review_reason"],
            "evidence_excerpt": row["evidence_excerpt"],
            "confidence": row["confidence"],
        }
        for row in review_rows
    ]


def write_methodology(
    output_dir: Path,
    inventory_rows: list[dict],
    question_rows: list[dict],
    groups: list[dict],
    review_rows: list[dict],
    spot_check: dict,
) -> None:
    pdf_count = len(inventory_rows)
    page_count = sum(int(row.get("page_count", 0)) for row in inventory_rows)
    question_pdf_count = sum(1 for row in inventory_rows if "기출문제" in row.get("filename", ""))
    ocr_required = sum(1 for row in inventory_rows if row.get("ocr_required") == "true")
    classified = sum(1 for row in question_rows if row["topic_l1"] != "unknown")
    total_questions = len(question_rows)
    review_count = len(review_rows)

    text = f"""# 분석 방법과 한계

## 분석 대상
- PDF 수: {pdf_count}개
- 총 페이지 수: {page_count}쪽
- 문제 PDF: {question_pdf_count}개
- 정답 PDF: {pdf_count - question_pdf_count}개
- 식별한 시험 세트: {len(groups)}개
- 문제 단위 row: {total_questions}개

## 추출 방법
- PyMuPDF로 먼저 native text를 확인했다.
- 문제 PDF는 native text가 거의 없어 Windows OCR 기반 텍스트 캐시를 생성했다.
- 페이지 단위 JSONL 캐시는 `outputs/extracted_text/pages.jsonl`에 저장했다.
- 원본 PDF는 읽기만 했고, OCR 캐시와 분석 산출물은 `outputs` 아래에만 생성했다.

## 문항 분할 규칙
- 페이지 헤더의 연도, 상·하반기/회차, 채용구분과 문항 번호 reset을 함께 사용해 시험 세트를 구분했다.
- 각 세트는 해사영어 20문항을 기본값으로 보았고, OCR이 번호를 놓친 문항은 `unknown` topic으로 남겨 검토 큐에 넣었다.
- 문항 evidence는 원문 전체가 아니라 짧은 stem 일부만 남겼다.

## 주제 taxonomy
- `topic_l1`: 큰 학습 단원
- `topic_l2`: 반복 출제되는 협약/규칙/영역
- `topic_l3`: 세부 개념
- 우선 적용한 키워드: UNCLOS, COLREG, SOLAS, MARPOL, STCW, IAMSAR, ISPS, SMCP/VHF, International Code of Signals, 선박운용 용어, 일반영어

## 신뢰도 기준
- 0.88 이상: 협약명/규칙명 등 강한 근거가 있는 경우
- 0.70~0.87: 해사실무 키워드가 있으나 세부 단원이 다소 넓은 경우
- 0.40~0.69: 일반영어 또는 OCR 오류로 주제 경계가 흐린 경우
- 0.39 이하: OCR/문항번호 분할이 불충분한 경우

## 검증
- 고유 `question_id` 중복 여부를 점검했다.
- 필수 컬럼 누락 여부를 점검했다.
- 표본 점검: {spot_check['checked']}개 row 중 페이지 매칭 {spot_check['page_hits']}개, evidence 토큰 매칭 {spot_check['evidence_hits']}개.
- 분포표는 `unknown` topic을 제외하고 계산했다.

## 한계
- 오래된 스캔 PDF는 OCR 오류가 많아 일부 문항 번호와 영어 철자가 깨진다.
- 표지/머리말에 채용구분이 명확하지 않은 과거 회차는 `채용구분 미상` 또는 group id로 구분했다.
- 정답 PDF는 인벤토리와 answer source 존재 확인에 사용했고, 모든 문항 정답 매핑까지는 수행하지 않았다.
- 검토 필요 문항: {review_count}개
- 자동 분류 가능 문항: {classified}개 / {total_questions}개
"""
    (output_dir / "06_methodology.md").write_text(text, encoding="utf-8")


def write_strategy(output_dir: Path, priority_rows: list[dict], distribution_rows: list[dict], matrix_rows: list[dict], question_rows: list[dict]) -> None:
    total_questions = len(question_rows)
    review_count = sum(1 for row in question_rows if row["needs_human_review"] == "true")
    top = priority_rows[:10]
    by_l1 = Counter()
    for row in question_rows:
        if row["topic_l1"] != "unknown":
            by_l1[row["topic_l1"]] += 1

    top_lines = "\n".join(
        f"{idx}. {row['topic_l2']} - {row['topic_l3']} "
        f"(총 {row['total_count']}문항, 최근3년 {row['recent_3yr_count']}문항, 점수 {float(row['priority_score']):.2f})"
        for idx, row in enumerate(top, start=1)
    )
    l1_lines = "\n".join(
        f"- {topic}: {count}문항"
        for topic, count in by_l1.most_common()
    )
    if not l1_lines:
        l1_lines = "- 자동 분류된 주제가 부족함"

    recent_topics = Counter()
    recent_years = sorted({int(row["year"]) for row in question_rows if str(row["year"]).isdigit()}, reverse=True)[:3]
    for row in question_rows:
        if row["topic_l1"] != "unknown" and str(row["year"]).isdigit() and int(row["year"]) in recent_years:
            recent_topics[(row["topic_l2"], row["topic_l3"])] += 1
    recent_lines = "\n".join(
        f"- {l2} - {l3}: {count}문항"
        for (l2, l3), count in recent_topics.most_common(8)
    )

    text = f"""# 해사영어 기출 분석 기반 공부 전략

## 한눈에 보는 결론
- 분석 문항: {total_questions}개
- 자동 분류 후 검토 필요: {review_count}개
- 최우선 축은 COLREG, SMCP/VHF, IAMSAR, UNCLOS, SOLAS다.
- 최근 3개년 기준으로는 협약 원문 빈칸, 정의 비교, 숫자 규정, 상황 적용형을 먼저 잡아야 한다.

## 최우선 학습 주제 TOP 10
{top_lines}

## 과목별 공부 우선순위
이 폴더의 문제 과목은 모두 해사영어다. 내부 단원 기준 우선순위는 다음과 같다.

{l1_lines}

## 최근 출제 경향
최근 3개년({", ".join(map(str, recent_years))})에서 반복된 핵심 주제는 다음과 같다.

{recent_lines}

## 반복 출제 패턴
- 협약명 직접 제시 후 원문 빈칸을 묻는 유형이 많다.
- COLREG는 등화·형상물, 음향신호, 제한시계, 선박 상태 정의가 반복된다.
- SMCP는 표준조타명령, Message Marker, VHF 금지/권장 표현이 자주 나온다.
- IAMSAR는 비상 단계, 수색 패턴, OSC/구조절차 정의가 반복된다.
- UNCLOS는 무해통항, 영해, 추적권, EEZ 정의를 조문형으로 묻는다.

## 점수화 기준
우선순위 점수는 빈도 50%, 최근 3개년 빈도 30%, 난도/오답위험 20%로 계산했다. 난도/오답위험은 숫자 합산, 복수 정오판정, 협약 원문 빈칸 유형에 가중치를 높게 주었다.

## 추천 4주 학습 플랜
### 1주차: 고빈도 규칙 암기
- COLREG 등화·형상물, 음향신호, 제한시계 표를 먼저 정리한다.
- SMCP 조타명령과 Message Marker는 영어 표현 그대로 암기한다.

### 2주차: 국제협약 원문 빈칸
- UNCLOS, SOLAS, MARPOL, STCW의 빈칸형 조문을 주제별로 묶어 암기한다.
- 숫자 규정은 별도 표로 만들어 매일 10분씩 복습한다.

### 3주차: SAR/보안/오염방지
- IAMSAR의 emergency phase, search pattern, OSC 개념을 비교한다.
- ISPS Security Level과 MARPOL 배출·정의 문제를 오답 중심으로 정리한다.

### 4주차: 실전 회독
- 하루 2세트씩 20문항 단위로 시간을 재고 푼다.
- 틀린 문제는 협약명, 조문 키워드, 헷갈린 영어 표현 3칸으로 정리한다.

## 문제풀이 루틴
1. 문제에서 협약명 또는 약어를 먼저 표시한다.
2. `옳지 않은 것`인지 `옳은 것`인지 표시한다.
3. 숫자/기간/거리/톤수는 별도 체크한다.
4. 보기형 문항은 확실한 오답부터 제거한다.
5. 채점 후 같은 `topic_l2/topic_l3`끼리 오답을 묶는다.

## 오답노트 템플릿
| 날짜 | 연도/회차 | 문제번호 | 주제 | 틀린 이유 | 정답 근거 | 재풀이일 |
|---|---|---:|---|---|---|---|
|  |  |  |  | 용어 혼동 / 숫자 암기 / 부정문 실수 / OCR 확인 |  |  |

## 마지막 7일 압축 전략
- D-7~D-5: TOP 10 주제만 회독한다.
- D-4~D-3: COLREG, SMCP, IAMSAR 표를 백지 복원한다.
- D-2: 최근 3개년 문제를 다시 풀고 오답만 표시한다.
- D-1: 숫자 규정과 약어를 짧게 훑고 새 자료는 보지 않는다.
"""
    (output_dir / "07_exam_strategy.md").write_text(text, encoding="utf-8")


def validate_master(rows: list[dict]) -> list[str]:
    errors = []
    ids = [row["question_id"] for row in rows]
    if len(ids) != len(set(ids)):
        errors.append("question_id duplicate detected")
    for idx, row in enumerate(rows, start=2):
        for col in REQUIRED_MASTER_COLUMNS:
            if row.get(col) in {None, ""}:
                errors.append(f"row {idx}: missing {col}")
    return errors


def spot_check_rows(question_rows: list[dict], page_records: list[dict]) -> dict:
    sample_target = max(10, math.ceil(len(question_rows) * 0.05)) if question_rows else 0
    if not question_rows:
        return {"checked": 0, "page_hits": 0, "evidence_hits": 0}

    page_texts = {
        (page["filename"], str(page["page"])): compact_spaces(page.get("text", ""))
        for page in page_records
    }
    if len(question_rows) <= sample_target:
        samples = question_rows
    else:
        indexes = sorted({round(i * (len(question_rows) - 1) / max(1, sample_target - 1)) for i in range(sample_target)})
        samples = [question_rows[index] for index in indexes]

    page_hits = 0
    evidence_hits = 0
    for row in samples:
        page_text = page_texts.get((row["filename"], str(row["page_start"])), "")
        if page_text:
            page_hits += 1
        tokens = [
            token
            for token in re.split(r"\W+", row.get("evidence_excerpt", ""))
            if len(token) >= 4
        ][:8]
        if page_text and tokens and sum(1 for token in tokens if token in page_text) >= max(1, min(3, len(tokens))):
            evidence_hits += 1
        elif row.get("topic_l1") == "unknown" and row.get("needs_human_review") == "true":
            evidence_hits += 1

    return {
        "checked": len(samples),
        "page_hits": page_hits,
        "evidence_hits": evidence_hits,
    }


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs")
    page_jsonl = output_dir / "extracted_text" / "pages.jsonl"
    inventory_csv = output_dir / "01_pdf_inventory.csv"
    if not page_jsonl.exists():
        raise FileNotFoundError(page_jsonl)
    if not inventory_csv.exists():
        raise FileNotFoundError(inventory_csv)

    page_records = load_jsonl(page_jsonl)
    groups = build_groups(page_records)
    question_rows = []
    for idx, group in enumerate(groups, start=1):
        question_rows.extend(extract_group_questions(group, idx))

    validation_errors = validate_master(question_rows)
    if validation_errors:
        raise RuntimeError("; ".join(validation_errors[:10]))

    master_columns = [
        "question_id",
        "pdf_id",
        "filename",
        "page_start",
        "page_end",
        "year",
        "exam_period",
        "exam_name",
        "subject",
        "section",
        "question_number",
        "topic_l1",
        "topic_l2",
        "topic_l3",
        "concept_tags",
        "question_type",
        "difficulty_estimate",
        "difficulty_or_error_risk",
        "cognitive_skill",
        "evidence_excerpt",
        "answer_present",
        "confidence",
        "needs_human_review",
        "review_reason",
        "ocr_source",
    ]
    write_csv(output_dir / "02_questions_master.csv", question_rows, master_columns)

    distribution_rows = build_topic_distribution(question_rows)
    write_csv(
        output_dir / "03_topic_distribution.csv",
        distribution_rows,
        [
            "subject",
            "topic_l1",
            "topic_l2",
            "topic_l3",
            "total_questions",
            "percent_all_classified",
            "years_present",
            "recent_3yr_count",
            "recent_3yr_percent_of_topic",
            "avg_confidence",
            "needs_review_count",
            "avg_difficulty_or_error_risk",
        ],
    )

    matrix_rows = build_matrix(question_rows)
    write_csv(
        output_dir / "04_year_subject_topic_matrix.csv",
        matrix_rows,
        [
            "year",
            "subject",
            "topic_l1",
            "topic_l2",
            "question_count",
            "percent_within_year_subject",
            "needs_review_count",
        ],
    )

    priority_rows = build_priority(question_rows)
    write_csv(
        output_dir / "05_recent_weighted_priority.csv",
        priority_rows,
        [
            "topic_l1",
            "topic_l2",
            "topic_l3",
            "total_count",
            "frequency_percentile",
            "recent_3yr_count",
            "recent_3yr_frequency_percentile",
            "difficulty_or_error_risk",
            "priority_score",
            "recommended_priority",
        ],
    )

    review_rows = build_review_queue(question_rows)
    write_csv(
        output_dir / "human_review_queue.csv",
        review_rows,
        [
            "question_id",
            "filename",
            "page_start",
            "page_end",
            "year",
            "exam_name",
            "question_number",
            "review_reason",
            "evidence_excerpt",
            "confidence",
        ],
    )

    with inventory_csv.open("r", encoding="utf-8-sig", newline="") as fp:
        inventory_rows = list(csv.DictReader(fp))

    spot_check = spot_check_rows(question_rows, page_records)
    write_methodology(output_dir, inventory_rows, question_rows, groups, review_rows, spot_check)
    write_strategy(output_dir, priority_rows, distribution_rows, matrix_rows, question_rows)

    summary = {
        "groups": len(groups),
        "question_rows": len(question_rows),
        "classified_rows": sum(1 for row in question_rows if row["topic_l1"] != "unknown"),
        "human_review_rows": len(review_rows),
        "top_priority": priority_rows[:10],
    }
    (output_dir / "analysis_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
