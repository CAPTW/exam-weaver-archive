"""Build question-level trend analysis outputs for offline maritime law PDFs."""

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
    r"(?:[\.•ㆍ·]|(?=\s*(?:다음|「|<|〈|보기)))"
    r"\s*",
    re.IGNORECASE,
)

SUBJECT_NAME = "해사법규"

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


@dataclass
class TopicResult:
    l1: str
    l2: str
    l3: str
    tags: list[str]
    confidence: float


@dataclass(frozen=True)
class KnownGroup:
    year: int
    period: str
    session_label: str
    category: str
    question_count: int

    @property
    def answer_key(self) -> str:
        parts = [str(self.year), self.period, self.session_label, self.category]
        return "|".join(part for part in parts if part)


KNOWN_GROUPS: dict[str, list[KnownGroup]] = {
    "[기출문제]해사법규(24년 하반기-25년 하반기).pdf": [
        KnownGroup(2025, "하반기", "", "순경", 20),
        KnownGroup(2025, "하반기", "", "경위", 40),
        KnownGroup(2025, "상반기", "", "순경", 20),
        KnownGroup(2025, "승진", "", "경장", 40),
        KnownGroup(2025, "승진", "", "경사", 40),
        KnownGroup(2024, "하반기", "", "순경", 20),
        KnownGroup(2024, "하반기", "", "경위", 40),
    ],
    "[기출문제]해사법규(24년-21년 경장).pdf": [
        KnownGroup(2024, "승진", "", "경장", 40),
        KnownGroup(2024, "승진", "", "경사", 40),
        KnownGroup(2023, "승진", "", "경장", 40),
        KnownGroup(2023, "승진", "", "경사", 40),
        KnownGroup(2023, "", "제3차", "순경", 20),
        KnownGroup(2023, "", "제3차", "간부후보", 40),
        KnownGroup(2022, "승진", "", "경장", 40),
        KnownGroup(2022, "승진", "", "경사", 40),
        KnownGroup(2022, "", "제2차", "순경", 20),
        KnownGroup(2022, "", "제2차", "간부후보", 40),
        KnownGroup(2021, "하반기", "", "순경·공채", 20),
        KnownGroup(2021, "승진", "", "경장", 40),
    ],
    "[기출문제]해사법규(21년 경사-13년).pdf": [
        KnownGroup(2021, "승진", "", "경사", 40),
        KnownGroup(2021, "상반기", "", "순경", 20),
        KnownGroup(2021, "상반기", "", "선박항해(7급)", 20),
        KnownGroup(2020, "승진", "", "경장", 40),
        KnownGroup(2020, "승진", "", "경사", 40),
        KnownGroup(2020, "", "제3차", "순경", 20),
        KnownGroup(2020, "", "제1차", "순경", 20),
        KnownGroup(2019, "승진", "", "경장", 40),
        KnownGroup(2019, "승진", "", "경사", 40),
        KnownGroup(2019, "", "제3차", "순경", 20),
        KnownGroup(2019, "", "제1차", "순경", 20),
        KnownGroup(2018, "승진", "", "경장", 40),
        KnownGroup(2018, "승진", "", "경사", 40),
        KnownGroup(2018, "", "제3차", "순경", 20),
        KnownGroup(2018, "", "제2차", "순경", 20),
        KnownGroup(2018, "", "제1차", "순경", 20),
        KnownGroup(2017, "", "제2차", "순경", 20),
        KnownGroup(2017, "", "제1차", "순경", 20),
        KnownGroup(2016, "", "제3차", "순경", 20),
        KnownGroup(2016, "", "제2차", "순경", 20),
        KnownGroup(2015, "", "제3차", "순경", 20),
        KnownGroup(2015, "", "제2차", "순경", 20),
        KnownGroup(2014, "하반기", "", "순경", 20),
        KnownGroup(2014, "", "제1회", "순경", 20),
        KnownGroup(2013, "", "제2차", "순경", 20),
        KnownGroup(2013, "", "제1회", "순경·경정", 20),
    ],
    "[기출문제]해사법규(26년 승진).pdf": [
        KnownGroup(2026, "승진", "", "경사", 40),
    ],
}

KNOWN_PAGE_RANGES: dict[str, list[tuple[int, int]]] = {
    "[기출문제]해사법규(24년 하반기-25년 하반기).pdf": [
        (1, 5), (6, 13), (14, 17), (18, 25), (26, 33), (34, 37), (38, 45),
    ],
    "[기출문제]해사법규(24년-21년 경장).pdf": [
        (2, 8), (9, 16), (17, 23), (24, 30), (31, 33), (34, 40),
        (41, 46), (47, 53), (54, 57), (58, 65), (66, 69), (70, 75),
    ],
    "[기출문제]해사법규(21년 경사-13년).pdf": [
        (2, 7), (8, 11), (12, 15), (16, 20), (21, 26), (27, 31),
        (32, 34), (35, 39), (40, 44), (45, 47), (48, 50),
        (51, 55), (56, 61), (62, 65), (66, 69), (70, 72),
        (78, 80), (81, 83), (84, 86), (87, 89), (90, 92), (93, 95),
        (96, 98), (99, 101), (102, 103), (104, 105),
    ],
    "[기출문제]해사법규(26년 승진).pdf": [(1, 6)],
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compact_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def compact_for_year(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def detect_year(text: str, filename: str = "") -> int | None:
    head = compact_for_year(f"{text[:700]} {filename}")
    if "20기년도" in head or "20기년" in head:
        return 2021
    match = re.search(r"20[012]\d", head)
    if match:
        year = int(match.group(0))
        if 2013 <= year <= 2026:
            return year
    spaced = re.search(r"2\s*0\s*([12])\s*(\d)", f"{text[:700]} {filename}")
    if spaced:
        year = int(f"20{spaced.group(1)}{spaced.group(2)}")
        if 2013 <= year <= 2026:
            return year
    return None


def detect_period(text: str) -> str:
    head = compact_spaces(text[:900])
    if re.search(r"승\s*진", head):
        return "승진"
    if re.search(r"상\s*반\s*기", head):
        return "상반기"
    if re.search(r"하\s*(?:반|만|발)\s*기", head):
        return "하반기"
    return ""


def detect_session(text: str) -> str:
    head = compact_spaces(text[:900])
    normalized = (
        head.replace("저B자", "제3차")
        .replace("3大卜", "3차")
        .replace("2大卜", "2차")
        .replace("1大卜", "1차")
        .replace("저2자", "제2차")
        .replace("저1자", "제1차")
    )
    match = re.search(r"제\s*([1-4])\s*(?:회|차|자)", normalized)
    if match:
        label = "회" if "회" in normalized[max(0, match.start() - 2): match.end() + 2] else "차"
        return f"제{match.group(1)}{label}"
    return ""


def detect_category(text: str) -> str:
    head = compact_spaces(text[:1100])
    if "간부" in head:
        return "간부후보"
    if "선박항해" in head or "7급" in head:
        return "선박항해(7급)"
    if "경위" in head or "경위공" in head:
        return "경위"
    if "경장" in head:
        return "경장"
    if "경사" in head:
        return "경사"
    if "순경" in head:
        return "순경"
    if "일반직" in head:
        return "일반직공무원"
    if "경찰공무원" in head or "해양경찰" in head or "해영경찰" in head:
        return "해양경찰"
    return "채용구분 미상"


def infer_page_meta(page: dict) -> PageMeta:
    text = page.get("text", "")
    return PageMeta(
        year=detect_year(text, page.get("filename", "")),
        period=detect_period(text),
        session=detect_session(text),
        category=detect_category(text),
    )


def looks_like_law_question_context(context: str) -> bool:
    if re.match(r"(?:해\s*사\s*법\s*규|매사법규|혜사법규|사\s*법규)\b", context):
        return False
    cues = [
        r"다음",
        r"보기",
        r"옳",
        r"틀린",
        r"해당",
        r"무엇",
        r"몇\s*개",
        r"괄호",
        r"빈칸",
        r"설명",
        r"내용",
        r"법",
        r"시행령",
        r"시행규칙",
        r"「",
    ]
    return any(re.search(pattern, context) for pattern in cues)


def question_start_candidates(text: str, max_question_number: int = 40) -> list[tuple[int, int, int]]:
    starts = []
    for match in QUESTION_START.finditer(text or ""):
        number = int(match.group(1))
        if not 1 <= number <= max_question_number:
            continue
        start = match.start(1)
        end = match.end()
        context = compact_spaces((text or "")[end:end + 180])
        if len(context) < 8:
            continue
        if not looks_like_law_question_context(context):
            continue
        starts.append((number, start, end))
    return starts


def question_starts(text: str, max_question_number: int = 40) -> list[tuple[int, int, int]]:
    filtered = []
    last_num = 0
    for number, start, end in question_start_candidates(text, max_question_number):
        if filtered and number <= last_num:
            continue
        if filtered and number - last_num > 12:
            continue
        filtered.append((number, start, end))
        last_num = number
    return filtered


def strip_noise(text: str) -> str:
    lines = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        compact = re.sub(r"\s+", "", line)
        if "합격코스" in compact or "커리큘럼" in compact or "동시학습" in compact:
            continue
        if "커리큘럼" in compact or "실전대비" in compact:
            continue
        if re.search(r"\b\d+/\d+\b", line) and len(line) < 40:
            continue
        if "문제지" in compact and len(compact) < 80:
            continue
        lines.append(line)
    return compact_spaces(" ".join(lines))


def evidence_from_question(raw_segment: str) -> str:
    cleaned = strip_noise(raw_segment)
    markers = [r"㉠", r"㉡", r"㉢", r"㉣", r"①", r"②", r"③", r"④", r"\b[1-4]\)"]
    cut = len(cleaned)
    for pattern in markers:
        match = re.search(pattern, cleaned)
        if match and match.start() > 40:
            cut = min(cut, match.start())
    excerpt = cleaned[:cut].strip()
    if len(excerpt) < 40:
        excerpt = cleaned
    return excerpt[:180]


def contains_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_topic(raw_text: str, placeholder: bool = False) -> TopicResult:
    if placeholder:
        return TopicResult("unknown", "unknown", "unknown", ["ocr_missing"], 0.20)

    text = raw_text or ""
    rules: list[tuple[list[str], TopicResult]] = [
        ([r"해양경비법", r"해양경찰법", r"경비수역", r"해상검문검색", r"공용화기", r"경비세력"],
         TopicResult("해양경찰 작용법", "해양경찰법·해양경비법", "직무·권한·경비활동", ["해양경찰법", "해양경비법"], 0.92)),
        ([r"수색.?구조", r"수상에서의 수색", r"수난", r"구조본부", r"수상구조사", r"긴급피난"],
         TopicResult("수난구호·수색구조", "수상구조법", "구조본부·긴급피난·수상구조사", ["수색구조", "수상구조"], 0.92)),
        ([r"수상레저", r"동력수상레저", r"조종면허", r"수상레저기구"],
         TopicResult("수상레저·연안안전", "수상레저안전법", "조종면허·기구·사업·안전의무", ["수상레저"], 0.92)),
        ([r"연안사고", r"연안체험", r"연안순찰"],
         TopicResult("수상레저·연안안전", "연안사고예방법", "연안체험활동·출입통제", ["연안사고"], 0.90)),
        ([r"선박의 입항", r"출항", r"무역항", r"우선피항선", r"정박지", r"계류"],
         TopicResult("항만·입출항", "선박입출항법", "무역항 항법·입출항·우선피항", ["선박입출항법"], 0.92)),
        ([r"항만운송", r"항만법", r"항만시설", r"검수사", r"검량사", r"항만하역"],
         TopicResult("항만·입출항", "항만법·항만운송사업법", "항만시설·항만운송관련사업", ["항만법", "항만운송"], 0.90)),
        ([r"해상교통안전법", r"해사안전법", r"해사안전기본법", r"교통안전특정해역", r"항법", r"해상교통안전진단", r"출항통제"],
         TopicResult("해상교통·항법", "해상교통안전법·해사안전", "항법·교통안전·출항통제", ["해상교통안전", "해사안전"], 0.90)),
        ([r"선박교통관제", r"관제대상", r"관제통신", r"VTS", r"해상교통관제"],
         TopicResult("해상교통·항법", "선박교통관제법", "관제대상·관제통신·VTS", ["선박교통관제"], 0.90)),
        ([r"선박안전법", r"선박검사", r"임시승선자", r"만재흘수선", r"선박위치발신"],
         TopicResult("선박·선원", "선박안전법", "검사·설비·임시승선자", ["선박안전"], 0.92)),
        ([r"선박직원법", r"자격", r"승무기준", r"면허"],
         TopicResult("선박·선원", "선박직원법", "자격·면허·승무기준", ["선박직원", "자격"], 0.92)),
        ([r"선원법", r"선장", r"선원", r"해원", r"생리휴식", r"소년선원"],
         TopicResult("선박·선원", "선원법", "선장 권한·선원근로·승무", ["선원법"], 0.90)),
        ([r"선박법", r"선적항", r"한국선박", r"소형선박", r"선박국적"],
         TopicResult("선박·선원", "선박법", "선박 등록·국적·소형선박", ["선박법"], 0.90)),
        ([r"해양환경관리법", r"해양오염", r"방제", r"오염물질", r"유해액체물질", r"폐기물"],
         TopicResult("해양환경·오염방제", "해양환경관리법", "오염방제·배출규제·감시원", ["해양환경", "오염방제"], 0.92)),
        ([r"어선법", r"어선안전조업", r"조업자제해역", r"특정해역", r"어선위치"],
         TopicResult("어선·어업·수산", "어선법·어선안전조업법", "어선검사·위치통지·조업해역", ["어선", "안전조업"], 0.92)),
        ([r"수산업법", r"어업권", r"면허어업", r"허가어업", r"양식업"],
         TopicResult("어선·어업·수산", "수산업법", "면허·허가·어업권", ["수산업"], 0.90)),
        ([r"낚시", r"낚시어선", r"가공미끼"],
         TopicResult("어선·어업·수산", "낚시관리법", "낚시어선업·안전운항·미끼 기준", ["낚시관리"], 0.90)),
        ([r"어촌.?어항", r"어항시설", r"어항개발"],
         TopicResult("어선·어업·수산", "어촌어항법", "어항시설·어항개발·금지행위", ["어촌어항"], 0.88)),
        ([r"영해", r"접속수역", r"배타적 경제수역", r"대륙붕", r"무해통항", r"직선기선"],
         TopicResult("해양영토·국제해양법", "영해·EEZ·대륙붕", "무해통항·기선·관할해역", ["영해", "EEZ"], 0.90)),
        ([r"해양사고", r"해양심판", r"조사관", r"특별조사부"],
         TopicResult("해양사고 조사", "해양사고조사심판법", "조사·심판·특별조사", ["해양사고"], 0.88)),
        ([r"유선", r"도선 사업법", r"유.?도선"],
         TopicResult("해상운송·사업", "유선 및 도선 사업법", "면허·신고·안전검사·영업제한", ["유선도선"], 0.88)),
        ([r"도선법", r"도선사", r"강제도선", r"도선구"],
         TopicResult("해상운송·사업", "도선법", "도선사 면허·강제도선", ["도선법"], 0.88)),
        ([r"해운법", r"해상여객", r"해상화물", r"승선권", r"여객명부"],
         TopicResult("해상운송·사업", "해운법", "해운업·여객운송·승선권", ["해운법"], 0.86)),
    ]
    for patterns, result in rules:
        if contains_any(text, patterns):
            return result
    return TopicResult("unknown", "unknown", "unknown", ["unclassified"], 0.35)


def estimate_difficulty(text: str, topic: TopicResult, placeholder: bool = False) -> tuple[str, float]:
    if placeholder:
        return "unknown", 0.5
    if contains_any(text, [r"모두 몇", r"합", r"숫자", r"순서대로", r"가장 옳지 않은 것은 모두", r"벌칙", r"과태료"]):
        return "high", 1.0
    if topic.l1 in {"해양영토·국제해양법", "해상교통·항법", "해양환경·오염방제"}:
        return "medium", 0.6
    return "medium", 0.6


def cognitive_skill(text: str, placeholder: bool = False) -> str:
    if placeholder:
        return "unknown"
    if contains_any(text, [r"사례", r"상황", r"조치", r"명령", r"허가", r"신고"]):
        return "case_application"
    if contains_any(text, [r"모두 몇", r"옳지 않은 것은 모두", r"비교", r"합"]):
        return "comparative_analysis"
    if contains_any(text, [r"괄호", r"숫자", r"순서"]):
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


def known_group_for(group: dict, order_in_file: int) -> KnownGroup | None:
    known = KNOWN_GROUPS.get(group.get("filename", ""))
    if not known or order_in_file > len(known):
        return None
    return known[order_in_file - 1]


def apply_known_group_metadata(groups: list[dict]) -> None:
    by_filename_counter: dict[str, int] = defaultdict(int)
    for group in groups:
        filename = group.get("filename", "")
        by_filename_counter[filename] += 1
        known = known_group_for(group, by_filename_counter[filename])
        if not known:
            group["question_count"] = 40 if group.get("max_question_number", 0) > 20 else 20
            group["answer_key"] = ""
            continue
        group["year"] = known.year
        group["period"] = known.period
        group["session"] = known.session_label
        group["category"] = known.category
        group["question_count"] = known.question_count
        group["answer_key"] = known.answer_key


def build_groups(page_records: list[dict]) -> list[dict]:
    question_pages = [page for page in page_records if "기출문제" in page.get("filename", "")]
    by_pdf = defaultdict(list)
    for page in question_pages:
        by_pdf[page["pdf_id"]].append(page)

    groups = []
    for _, pages in sorted(by_pdf.items()):
        pages.sort(key=lambda item: item["page"])
        filename = pages[0].get("filename", "") if pages else ""
        if filename in KNOWN_PAGE_RANGES:
            known_groups = KNOWN_GROUPS[filename]
            for idx, (start_page, end_page) in enumerate(KNOWN_PAGE_RANGES[filename], start=1):
                selected = [page for page in pages if start_page <= int(page["page"]) <= end_page]
                if not selected:
                    continue
                known = known_groups[idx - 1]
                groups.append({
                    "filename": filename,
                    "pdf_id": selected[0]["pdf_id"],
                    "year": known.year,
                    "period": known.period,
                    "session": known.session_label,
                    "category": known.category,
                    "pages": selected,
                    "max_question_number": known.question_count,
                    "question_count": known.question_count,
                    "answer_key": known.answer_key,
                })
            continue

        current = None
        current_numbers: set[int] = set()
        for page in pages:
            text = page.get("text", "")
            starts = question_starts(text, 40)
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
                    bool(meta.period or meta.session)
                    and (meta.period, meta.session) != (current.get("period"), current.get("session"))
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
                    "max_question_number": 0,
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
            current["max_question_number"] = max(current.get("max_question_number", 0), max(numbers or [0]))

    apply_known_group_metadata(groups)
    return groups


def group_label(group: dict, index: int) -> str:
    parts = []
    if group.get("year"):
        parts.append(str(group["year"]))
    if group.get("period"):
        parts.append(str(group["period"]))
    if group.get("session"):
        parts.append(str(group["session"]))
    if group.get("category"):
        parts.append(str(group["category"]))
    parts.append(SUBJECT_NAME)
    return " ".join(parts) + f" G{index:03d}"


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
            return strip_noise(page.get("text", ""))[:160]
    return "OCR 또는 번호분할 누락으로 원문 확인 필요"


def recover_numbered_segments(candidates: dict[int, tuple[str, int, int]], max_question_number: int) -> None:
    for missing in range(1, max_question_number + 1):
        if missing in candidates:
            continue
        previous_numbers = [number for number in candidates if number < missing]
        if not previous_numbers:
            continue
        previous = max(previous_numbers)
        segment, page_number, _ = candidates[previous]
        match = re.search(rf"(?m)(?<!\d){missing}\s*[\.\u2022ㆍ·]\s*(?=\S)", segment)
        if match is None:
            match = re.search(rf"(?m)(?<!\d){missing}\s+(?=(?:다음|「|<|〈))", segment)
        if match is None or match.start() < 40:
            continue
        before = segment[:match.start()].strip()
        after = segment[match.end():].strip()
        if len(compact_spaces(after)) < 30:
            continue
        candidates[previous] = (before, page_number, len(compact_spaces(before)))
        candidates[missing] = (after, page_number, len(compact_spaces(after)))


def segment_map_for_group(group: dict) -> dict[int, tuple[str, int]]:
    max_question_number = int(group.get("question_count") or 20)
    candidates: dict[int, tuple[str, int, int]] = {}

    def add(number: int, segment: str, page_number: int) -> None:
        if not 1 <= number <= max_question_number:
            return
        quality = len(compact_spaces(segment))
        if quality < 20:
            return
        current = candidates.get(number)
        if current is None or quality > current[2]:
            candidates[number] = (segment, page_number, quality)

    for page in group["pages"]:
        text = page.get("text", "")
        starts = question_start_candidates(text, max_question_number)
        starts = sorted(starts, key=lambda item: item[1])
        for idx, (number, _, end) in enumerate(starts):
            next_start = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
            add(number, text[end:next_start], page["page"])

    recover_numbered_segments(candidates, max_question_number)
    return {number: (segment, page) for number, (segment, page, _) in candidates.items()}


def extract_group_questions(group: dict, group_index: int) -> list[dict]:
    segments = segment_map_for_group(group)
    rows = []
    group_id = f"G{group_index:03d}"
    exam_name = group_label(group, group_index)
    page_numbers = [page["page"] for page in group["pages"]]
    max_question_number = int(group.get("question_count") or 20)
    duplicate_numbers = set()

    for question_number in range(1, max_question_number + 1):
        item = segments.get(question_number)
        placeholder = item is None
        if placeholder:
            page_start = page_end = estimate_page_for_missing(question_number, {}, page_numbers)
            segment = ""
            excerpt = missing_excerpt(group, page_start)
        else:
            segment, page_start = item
            page_end = page_start
            excerpt = evidence_from_question(segment)

        topic = classify_topic(segment, placeholder=placeholder)
        difficulty, risk = estimate_difficulty(segment, topic, placeholder=placeholder)
        review, review_reason = needs_review(topic, excerpt, placeholder=placeholder)
        if question_number in duplicate_numbers:
            review = True
            review_reason = f"{review_reason}; 중복 번호 후보 발생".strip("; ")
            topic.confidence = min(topic.confidence, 0.65)

        rows.append({
            "question_id": f"{group_id}-Q{question_number:02d}",
            "pdf_id": group["pdf_id"],
            "filename": group["filename"],
            "page_start": page_start,
            "page_end": page_end,
            "year": group.get("year") or "unknown",
            "exam_period": group.get("period") or "",
            "exam_name": exam_name,
            "subject": SUBJECT_NAME,
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
            "ocr_source": "true",
            "answer_key": group.get("answer_key", ""),
        })
    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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


def build_topic_distribution(rows: list[dict]) -> list[dict]:
    valid = [row for row in rows if row["topic_l1"] != "unknown"]
    total = len(valid) or 1
    grouped = defaultdict(list)
    for row in valid:
        grouped[(row["subject"], row["topic_l1"], row["topic_l2"], row["topic_l3"])].append(row)
    output = []
    recent_years = sorted({int(row["year"]) for row in rows if str(row["year"]).isdigit()}, reverse=True)[:3]
    for (subject, l1, l2, l3), items in grouped.items():
        years = sorted({int(row["year"]) for row in items if str(row["year"]).isdigit()})
        recent_count = sum(1 for row in items if str(row["year"]).isdigit() and int(row["year"]) in recent_years)
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
            "avg_confidence": f"{statistics.mean(float(row['confidence']) for row in items):.2f}",
            "needs_review_count": sum(1 for row in items if row["needs_human_review"] == "true"),
            "avg_difficulty_or_error_risk": f"{statistics.mean(float(row['difficulty_or_error_risk']) for row in items):.2f}",
        })
    return sorted(output, key=lambda item: (-item["total_questions"], item["topic_l1"], item["topic_l2"]))


def build_matrix(rows: list[dict]) -> list[dict]:
    valid = [row for row in rows if row["topic_l1"] != "unknown"]
    denom = Counter((row["year"], row["subject"]) for row in valid)
    grouped = defaultdict(list)
    for row in valid:
        grouped[(row["year"], row["subject"], row["topic_l1"], row["topic_l2"])].append(row)
    output = []
    for (year, subject, l1, l2), items in grouped.items():
        output.append({
            "year": year,
            "subject": subject,
            "topic_l1": l1,
            "topic_l2": l2,
            "question_count": len(items),
            "percent_within_year_subject": f"{len(items) / max(1, denom[(year, subject)]) * 100:.2f}",
            "needs_review_count": sum(1 for row in items if row["needs_human_review"] == "true"),
        })
    return sorted(output, key=lambda item: (str(item["year"]), -item["question_count"], item["topic_l1"]))


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
            "recommended_priority": "최우선" if priority >= 0.75 else "상" if priority >= 0.55 else "중" if priority >= 0.35 else "하",
        })
    return sorted(output, key=lambda item: (-float(item["priority_score"]), -item["total_count"], item["topic_l1"]))


def build_review_queue(rows: list[dict]) -> list[dict]:
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
        for row in rows
        if row["needs_human_review"] == "true"
    ]


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
    page_texts = {(page["filename"], str(page["page"])): compact_spaces(page.get("text", "")) for page in page_records}
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
        tokens = [token for token in re.split(r"\W+", row.get("evidence_excerpt", "")) if len(token) >= 4][:8]
        if page_text and tokens and sum(1 for token in tokens if token in page_text) >= max(1, min(3, len(tokens))):
            evidence_hits += 1
        elif row.get("topic_l1") == "unknown" and row.get("needs_human_review") == "true":
            evidence_hits += 1
    return {"checked": len(samples), "page_hits": page_hits, "evidence_hits": evidence_hits}


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
    text = f"""# 분석 방법과 한계

## 분석 대상
- PDF 수: {pdf_count}개
- 총 페이지 수: {page_count}쪽
- 문제 PDF: {question_pdf_count}개
- 정답 PDF: {pdf_count - question_pdf_count}개
- OCR 필요 PDF: {ocr_required}개
- 식별한 시험 세트: {len(groups)}개
- 문제 단위 row: {total_questions}개

## 추출과 Parsing 개선
- 페이지 native text가 짧고 이미지가 있는 PDF는 OCR fallback을 사용했다.
- 해사법규는 20문항 채용시험과 40문항 승진/경위/간부후보 시험이 섞여 있어 세트별 문항 수를 별도로 관리했다.
- 머리말의 과목번호가 `1.`처럼 인식되는 경우를 제외하고, 실제 1번 문항 재시작을 기준으로 오래된 묶음 PDF를 재분할했다.
- 정답표는 이미지 표의 실선 경계와 중앙 숫자 인식으로 읽되, 복수정답/전원정답은 DB 정수 정답으로 단정하지 않도록 검토 태그를 남긴다.

## 주제 Taxonomy
- 해양경찰 작용법, 수난구호·수색구조, 수상레저·연안안전, 항만·입출항, 해상교통·항법, 선박·선원, 해양환경·오염방제, 어선·어업·수산, 해양영토·국제해양법, 해양사고 조사, 해상운송·사업으로 분류했다.

## 검증
- 고유 `question_id` 중복 여부와 필수 컬럼 누락 여부를 점검했다.
- 표본 점검: {spot_check['checked']}개 row 중 페이지 매칭 {spot_check['page_hits']}개, evidence 토큰 매칭 {spot_check['evidence_hits']}개.
- 분포표는 `unknown` topic을 제외하고 계산했다.

## 한계
- 오래된 스캔 PDF는 OCR의 2단 편집 순서가 섞이는 페이지가 있어 일부 선지 분할은 검토가 필요하다.
- 검토 필요 문항: {len(review_rows)}개
- 자동 분류 가능 문항: {classified}개 / {total_questions}개
"""
    (output_dir / "06_methodology.md").write_text(text, encoding="utf-8")


def write_strategy(output_dir: Path, priority_rows: list[dict], question_rows: list[dict]) -> None:
    total_questions = len(question_rows)
    review_count = sum(1 for row in question_rows if row["needs_human_review"] == "true")
    top = priority_rows[:10]
    by_l1 = Counter(row["topic_l1"] for row in question_rows if row["topic_l1"] != "unknown")
    top_lines = "\n".join(
        f"{idx}. {row['topic_l2']} - {row['topic_l3']} "
        f"(총 {row['total_count']}문항, 최근3년 {row['recent_3yr_count']}문항, 점수 {float(row['priority_score']):.2f})"
        for idx, row in enumerate(top, start=1)
    )
    l1_lines = "\n".join(f"- {topic}: {count}문항" for topic, count in by_l1.most_common())
    recent_years = sorted({int(row["year"]) for row in question_rows if str(row["year"]).isdigit()}, reverse=True)[:3]

    text = f"""# 해사법규 기출 분석 기반 공부 전략

## 한눈에 보는 결론
- 분석 문항: {total_questions}개
- 자동 분류 후 검토 필요: {review_count}개
- 최근 3개년({", ".join(map(str, recent_years))})은 해양경찰 작용법, 해상교통·항법, 수난구호, 수상레저, 어선·수산 법령 비중이 높다.
- 40문항 승진형은 숫자·기간·권한 주체를 묻는 문항이 많아 조문 비교표가 필요하다.

## 최우선 학습 주제 TOP 10
{top_lines}

## 대단원별 출제량
{l1_lines}

## 추천 공부 순서
1. 해양경찰법·해양경비법: 직무, 해상검문검색, 장비·무기 사용, 경비수역.
2. 해상교통안전법·선박입출항법: 항법, 출항통제, 우선피항선, 무역항 항행규칙.
3. 수상구조법·수상레저안전법: 구조본부, 긴급피난, 조종면허, 안전의무.
4. 선박안전법·선박직원법·선원법: 검사, 자격·면허, 선장 권한, 선원근로.
5. 어선법·어선안전조업법·수산업법·낚시관리법: 위치통지, 조업해역, 면허·허가, 낚시어선.

## 4주 루틴
- 1주차: 해양경찰 작용법과 수난구호 조문을 표로 정리한다.
- 2주차: 해상교통·입출항·항만 법령의 주체/권한/벌칙을 비교한다.
- 3주차: 선박·선원·어선·수산 법령의 숫자 규정을 반복 암기한다.
- 4주차: 최근 3개년 20문항/40문항 세트를 시간 제한으로 풀고 오답을 법령별로 묶는다.

## 오답노트 템플릿
| 날짜 | 연도/구분 | 문제번호 | 법령 | 틀린 이유 | 정답 근거 | 재풀이일 |
|---|---|---:|---|---|---|---|
|  |  |  |  | 주체 혼동 / 숫자 암기 / 부정문 실수 / OCR 확인 |  |  |
"""
    (output_dir / "07_exam_strategy.md").write_text(text, encoding="utf-8")


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/maritime_law_pdf_20260702")
    page_jsonl = output_dir / "extracted_text" / "pages.jsonl"
    inventory_csv = output_dir / "01_pdf_inventory.csv"
    page_records = load_jsonl(page_jsonl)
    groups = build_groups(page_records)

    expected = sum(len(items) for items in KNOWN_GROUPS.values())
    if len(groups) != expected:
        by_file = Counter(group["filename"] for group in groups)
        raise RuntimeError(f"Expected {expected} law groups, got {len(groups)}: {dict(by_file)}")

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
        "answer_key",
    ]
    write_csv(output_dir / "02_questions_master.csv", question_rows, master_columns)

    distribution_rows = build_topic_distribution(question_rows)
    write_csv(output_dir / "03_topic_distribution.csv", distribution_rows, [
        "subject", "topic_l1", "topic_l2", "topic_l3", "total_questions",
        "percent_all_classified", "years_present", "recent_3yr_count",
        "recent_3yr_percent_of_topic", "avg_confidence", "needs_review_count",
        "avg_difficulty_or_error_risk",
    ])
    matrix_rows = build_matrix(question_rows)
    write_csv(output_dir / "04_year_subject_topic_matrix.csv", matrix_rows, [
        "year", "subject", "topic_l1", "topic_l2", "question_count",
        "percent_within_year_subject", "needs_review_count",
    ])
    priority_rows = build_priority(question_rows)
    write_csv(output_dir / "05_recent_weighted_priority.csv", priority_rows, [
        "topic_l1", "topic_l2", "topic_l3", "total_count", "frequency_percentile",
        "recent_3yr_count", "recent_3yr_frequency_percentile",
        "difficulty_or_error_risk", "priority_score", "recommended_priority",
    ])
    review_rows = build_review_queue(question_rows)
    write_csv(output_dir / "human_review_queue.csv", review_rows, [
        "question_id", "filename", "page_start", "page_end", "year",
        "exam_name", "question_number", "review_reason", "evidence_excerpt", "confidence",
    ])

    with inventory_csv.open("r", encoding="utf-8-sig", newline="") as fp:
        inventory_rows = list(csv.DictReader(fp))
    spot_check = spot_check_rows(question_rows, page_records)
    write_methodology(output_dir, inventory_rows, question_rows, groups, review_rows, spot_check)
    write_strategy(output_dir, priority_rows, question_rows)

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
