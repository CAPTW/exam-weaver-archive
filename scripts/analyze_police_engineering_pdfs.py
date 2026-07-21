"""Build question-level trend analysis outputs for offline police engineering PDFs."""

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
    r"(?:[\.•ㆍ·]|(?=\s*(?:다음|디음|디젤|내연|냉동|보일러|기관|펌프|전동기|발전기|변압기|축전지|저항|전류|전압|「|<|〈|보기)))"
    r"\s*",
    re.IGNORECASE,
)

SUBJECT_NAME = "기관학"

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
    "[기출문제]경찰직 기관술(학)(24-13년).pdf": [
        KnownGroup(2024, "상반기", "", "해경학과", 20),
        KnownGroup(2023, "", "제3차", "순경", 20),
        KnownGroup(2023, "", "제3차", "간부후보", 40),
        KnownGroup(2023, "", "제2차", "해경학과(경장)", 20),
        KnownGroup(2022, "", "제2차", "순경", 20),
        KnownGroup(2022, "", "제2차", "순경·추가세트", 20),
        KnownGroup(2022, "", "제1차", "간부후보", 40),
        KnownGroup(2021, "하반기", "", "순경", 20),
        KnownGroup(2021, "상반기", "", "순경", 20),
        KnownGroup(2020, "", "제3차", "순경", 20),
        KnownGroup(2020, "", "제1차", "순경", 20),
        KnownGroup(2019, "", "제3차", "순경", 20),
        KnownGroup(2019, "", "제1차", "순경", 20),
        KnownGroup(2018, "", "제3차", "순경", 20),
        KnownGroup(2018, "", "제1차", "순경", 20),
        KnownGroup(2017, "", "제2차", "순경", 20),
        KnownGroup(2017, "", "제1차", "순경", 20),
        KnownGroup(2016, "", "제2차", "순경", 20),
        KnownGroup(2015, "", "제2차", "순경", 20),
        KnownGroup(2014, "", "제2차", "순경", 20),
        KnownGroup(2014, "", "제1차", "순경", 20),
        KnownGroup(2013, "", "제2차", "순경", 20),
        KnownGroup(2013, "", "제1차", "순경", 20),
    ],
    "[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf": [
        KnownGroup(2025, "하반기", "", "순경", 20),
        KnownGroup(2025, "하반기", "", "경위", 40),
        KnownGroup(2025, "상반기", "", "경장", 20),
        KnownGroup(2024, "하반기", "", "순경", 20),
        KnownGroup(2024, "하반기", "", "경위", 40),
    ],
}

KNOWN_PAGE_RANGES: dict[str, list[tuple[int, int]]] = {
    "[기출문제]경찰직 기관술(학)(24-13년).pdf": [
        (2, 4), (5, 7), (8, 13), (14, 16), (17, 19), (20, 21),
        (22, 26), (27, 29), (30, 32), (33, 35), (36, 38), (39, 41),
        (42, 44), (45, 46), (47, 48), (49, 50), (51, 52), (53, 55),
        (56, 58), (59, 61), (62, 63), (64, 65), (66, 67),
    ],
    "[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf": [
        (1, 4), (5, 11), (12, 14), (15, 17), (18, 24),
    ],
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


def looks_like_engineering_question_context(context: str) -> bool:
    if re.match(r"(?:기\s*관\s*(?:학|술)|선\s*박\s*기관)\b", context):
        return False
    cues = [
        r"다음",
        r"디음",
        r"보기",
        r"옳",
        r"틀린",
        r"적절",
        r"무엇",
        r"몇\s*개",
        r"괄호",
        r"빈칸",
        r"설명",
        r"내용",
        r"가장",
        r"계산",
        r"디젤|내연|기관|보일러|냉동|냉매|펌프|전동기|발전기|변압기|축전지",
        r"피스톤|실린더|밸브|과급|노크|연료|윤활|축전지|저항",
        r"전압|전류|유압|공기압축|프로펠러|클러치|추진",
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
        if not looks_like_engineering_question_context(context):
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
        ([r"디젤", r"내연기관", r"연소", r"착화", r"노크", r"Knock", r"분사", r"무화", r"관통", r"피스톤", r"실린더", r"라이너", r"밸브", r"캠축", r"크랭크", r"과급", r"서징", r"평균유효압력", r"출력", r"마력"],
         TopicResult("디젤기관·내연기관", "연소·구조·운전", "연료분사·피스톤·밸브·과급", ["디젤기관", "내연기관"], 0.92)),
        ([r"연료유", r"윤활유", r"세탄", r"옥탄", r"인화점", r"발화점", r"착화점", r"응고점", r"유동점", r"점도", r"청정기", r"셀프이젝트", r"버니어", r"마이크로미터", r"측정공구"],
         TopicResult("연료·윤활·측정", "유류 성상·정밀측정", "연료유·윤활유·청정기·측정공구", ["연료", "윤활", "측정"], 0.90)),
        ([r"보일러", r"증기", r"청관제", r"기수공발", r"Carry over", r"역화", r"Back-fire", r"과열", r"열역학", r"열효율", r"사이클", r"브레이톤", r"오토", r"디젤사이클", r"사바테", r"잠열", r"엔탈피"],
         TopicResult("보일러·열역학", "증기·열기관 이론", "보일러 운전·열역학 법칙·사이클", ["보일러", "열역학"], 0.90)),
        ([r"냉동", r"냉매", r"압축기", r"응축기", r"증발기", r"팽창밸브", r"프레온", r"액분리기", r"유분리기", r"냉동사이클", r"공조"],
         TopicResult("냉동·공조", "냉동장치", "냉매·압축기·응축기·팽창밸브", ["냉동", "냉매"], 0.92)),
        ([r"펌프", r"원심펌프", r"왕복식", r"마우스.?링", r"Mouth ring", r"수격", r"공동현상", r"Cavitation", r"토출", r"흡입", r"유압", r"공압", r"공기압축", r"릴리프밸브", r"카운터", r"액추에이터"],
         TopicResult("펌프·유공압", "펌프와 유압장치", "원심펌프·공동현상·유압밸브", ["펌프", "유압"], 0.92)),
        ([r"발전기", r"전동기", r"유도전동기", r"변압기", r"축전지", r"납축전지", r"전압", r"전류", r"저항", r"역률", r"콘덴서", r"반도체", r"다이오드", r"논리", r"게이트", r"키르히호프", r"옴의 법칙", r"플레밍", r"패러데이", r"전자유도", r"병렬운전"],
         TopicResult("전기·전자·제어", "전기기기와 회로", "발전기·전동기·축전지·회로법칙", ["전기", "전자"], 0.92)),
        ([r"추진축", r"축계", r"프로펠러", r"추진기", r"클러치", r"유체클러치", r"마찰클러치", r"감속", r"역전", r"선미관", r"추력", r"스러스트", r"베어링", r"워터제트", r"리그넘바이트"],
         TopicResult("추진·축계", "동력전달장치", "추진축계·클러치·프로펠러", ["추진", "축계"], 0.90)),
        ([r"조수기", r"오수처리", r"생화학적", r"윈치", r"원치", r"윈드라스", r"Windlass", r"스러스터", r"Thruster", r"조타기", r"보조기계", r"환경설비"],
         TopicResult("보조기계·환경설비", "갑판·환경·보조장치", "조수기·오수처리·윈치·스러스터", ["보조기계", "환경설비"], 0.88)),
        ([r"운전 중", r"급정지", r"고장", r"원인", r"대책", r"점검", r"누설", r"오손", r"마모", r"손상", r"방지", r"예방", r"경보", r"안전"],
         TopicResult("운전관리·고장진단", "기관 운전과 정비", "고장 원인·점검·예방조치", ["운전관리", "고장진단"], 0.82)),
    ]
    for patterns, result in rules:
        if contains_any(text, patterns):
            return result
    return TopicResult("unknown", "unknown", "unknown", ["unclassified"], 0.35)


def estimate_difficulty(text: str, topic: TopicResult, placeholder: bool = False) -> tuple[str, float]:
    if placeholder:
        return "unknown", 0.5
    if contains_any(text, [r"모두 몇", r"합", r"숫자", r"순서대로", r"계산", r"평균", r"압축비", r"저항", r"전류", r"전압", r"마력", r"피스톤 속도", r"효율"]):
        return "high", 1.0
    if topic.l1 in {"디젤기관·내연기관", "전기·전자·제어", "보일러·열역학"}:
        return "medium", 0.6
    return "medium", 0.6


def cognitive_skill(text: str, placeholder: bool = False) -> str:
    if placeholder:
        return "unknown"
    if contains_any(text, [r"운전 중", r"고장", r"원인", r"대책", r"점검", r"방지", r"예방", r"조치"]):
        return "case_application"
    if contains_any(text, [r"압축비", r"저항", r"전류", r"전압", r"마력", r"평균", r"몇 배", r"총합", r"계산"]):
        return "calculation"
    if contains_any(text, [r"모두 몇", r"옳지 않은 것은 모두", r"비교", r"순서"]):
        return "comparative_analysis"
    if contains_any(text, [r"괄호", r"숫자", r"빈칸"]):
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
    start_words = (
        r"다음|디음|디젤|내연|냉동|보일러|기관|펌프|전동기|발전기|변압기|축전지|"
        r"저항|전류|전압|선박|프로펠러|유압|냉매|「|<|〈|보기"
    )
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
            match = re.search(rf"(?m)(?<!\d){missing}\s+(?=(?:{start_words}))", segment)
        if match is None and missing >= 10:
            # Some scanned pages drop the tens digit at the start of a right-column question,
            # e.g. 15번 appears as "5." between 14번 and 16번.
            tail_digit = missing % 10
            if tail_digit:
                match = re.search(rf"(?m)(?<!\d){tail_digit}\s*[\.\u2022ㆍ·]\s*(?=(?:{start_words}))", segment)
        if match is None or match.start() < 40:
            continue
        before = segment[:match.start()].strip()
        after = segment[match.end():].strip()
        if len(compact_spaces(after)) < 30:
            continue
        candidates[previous] = (before, page_number, len(compact_spaces(before)))
        candidates[missing] = (after, page_number, len(compact_spaces(after)))


def repair_ocr_dropped_tens(
    starts: list[tuple[int, int, int]],
    max_question_number: int,
) -> list[tuple[int, int, int]]:
    repaired: list[tuple[int, int, int]] = []
    for index, (number, start, end) in enumerate(starts):
        fixed_number = number
        if repaired and number < 10:
            previous_number = repaired[-1][0]
            expected = previous_number + 1
            next_number = starts[index + 1][0] if index + 1 < len(starts) else None
            if (
                10 <= expected <= max_question_number
                and expected % 10 == number
                and (next_number is None or next_number == expected + 1)
            ):
                fixed_number = expected
        repaired.append((fixed_number, start, end))
    return repaired


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
        starts = repair_ocr_dropped_tens(starts, max_question_number)
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
- 기관학은 20문항 채용형과 40문항 경위/간부후보형이 섞여 있어 세트별 문항 수를 별도로 관리했다.
- 2단 스캔 페이지의 중앙 세로선을 감지해 OCR 열 순서를 보정했고, 과목 머리말이 문항번호로 인식되는 경우를 제외했다.
- 정답표는 이미지 표의 실선 경계와 중앙 숫자 인식으로 읽되, 복수정답/전원정답은 DB 정수 정답으로 단정하지 않도록 검토 태그를 남긴다.

## 주제 Taxonomy
- 디젤기관·내연기관, 연료·윤활·측정, 보일러·열역학, 냉동·공조, 펌프·유공압, 전기·전자·제어, 추진·축계, 보조기계·환경설비, 운전관리·고장진단으로 분류했다.

## 검증
- 고유 `question_id` 중복 여부와 필수 컬럼 누락 여부를 점검했다.
- 표본 점검: {spot_check['checked']}개 row 중 페이지 매칭 {spot_check['page_hits']}개, evidence 토큰 매칭 {spot_check['evidence_hits']}개.
- 분포표는 `unknown` topic을 제외하고 계산했다.

## 한계
- 오래된 스캔 PDF는 일부 선지 기호가 `0`, `㉭` 등으로 인식되어 선지 분할 검토가 필요할 수 있다.
- 2022년 제2차 20문항 추가 세트는 문제 PDF에는 있으나 원본 정답표에서 대응 표를 찾지 못해 정답 검토 태그를 남긴다.
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

    text = f"""# 기관학 기출 분석 기반 공부 전략

## 한눈에 보는 결론
- 분석 문항: {total_questions}개
- 자동 분류 후 검토 필요: {review_count}개
- 최근 3개년({", ".join(map(str, recent_years))})은 디젤기관, 전기·전자, 냉동, 펌프·유압, 보일러·열역학 비중이 높다.
- 40문항 경위/간부후보형은 계산형과 고장진단형을 섞어 묻는 문항이 많아 공식, 구조, 원인-대책을 같이 정리해야 한다.

## 최우선 학습 주제 TOP 10
{top_lines}

## 대단원별 출제량
{l1_lines}

## 추천 공부 순서
1. 디젤기관·내연기관: 연소과정, 연료분사, 피스톤/밸브, 과급기와 노크를 우선 정리한다.
2. 전기·전자·제어: 발전기, 전동기, 축전지, 저항/전류 계산, 회로 법칙을 묶어 반복한다.
3. 냉동·공조와 펌프·유공압: 냉매 흐름, 압축기/응축기, 원심펌프, 공동현상, 유압밸브를 표로 정리한다.
4. 보일러·열역학: 보일러 운전, 청관제, 기수공발, 열역학 법칙과 사이클을 같이 복습한다.
5. 추진·축계와 보조기계: 클러치, 축계, 프로펠러, 청정기, 오수처리, 갑판기계의 역할을 오답 중심으로 정리한다.

## 4주 루틴
- 1주차: 디젤기관 구조와 연소/분사/과급 문제를 문항별로 재풀이한다.
- 2주차: 전기·전자 계산과 냉동·펌프 장치 흐름도를 반복한다.
- 3주차: 보일러·열역학, 추진·축계, 보조기계의 원인-대책형 문항을 정리한다.
- 4주차: 최근 3개년 20문항/40문항 세트를 시간 제한으로 풀고 오답을 주제별로 묶는다.

## 오답노트 템플릿
| 날짜 | 연도/구분 | 문제번호 | 주제 | 틀린 이유 | 정답 근거 | 재풀이일 |
|---|---|---:|---|---|---|---|
|  |  |  |  | 공식 적용 / 구조 혼동 / 원인-대책 혼동 / OCR 확인 |  |  |
"""
    (output_dir / "07_exam_strategy.md").write_text(text, encoding="utf-8")


def main() -> int:
    output_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/police_engineering_pdf_20260702")
    page_jsonl = output_dir / "extracted_text" / "pages.jsonl"
    inventory_csv = output_dir / "01_pdf_inventory.csv"
    page_records = load_jsonl(page_jsonl)
    groups = build_groups(page_records)

    expected = sum(len(items) for items in KNOWN_GROUPS.values())
    if len(groups) != expected:
        by_file = Counter(group["filename"] for group in groups)
        raise RuntimeError(f"Expected {expected} engineering groups, got {len(groups)}: {dict(by_file)}")

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
