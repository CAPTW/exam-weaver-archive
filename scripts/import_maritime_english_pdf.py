"""Import offline maritime English PDF questions into the SQLite question bank.

The offline PDFs are OCR-heavy and the answer sheets use circled numerals inside
image tables. This importer reuses the page cache and trend-analysis grouping
logic, then applies a small image-table parser for answer keys.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import fitz
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_maritime_english_pdfs import (  # noqa: E402
    build_groups,
    classify_topic,
    group_label,
    load_jsonl,
    question_starts,
    strip_noise,
)
from src.database.repository import ExamRepository  # noqa: E402
from src.parser.question import Choice, Question, QuestionParser  # noqa: E402
from src.web_import.importer import QuestionSource, QuestionSourceRegistry, sha256_file, utc_timestamp  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("outputs/maritime_english_pdf_20260701")
EXAM_CODE = "해양경찰 해사영어"
SUBJECT_NAME = "해사영어"
ANSWER_FILENAMES = {
    "recent_2025_h2": "[기출정답]해사영어(25년 하반기).pdf",
    "recent_2024_h2_2025_h1": "[기출정답]해사영어(24년 하반기-25년 상반기).pdf",
    "archive_2024_2013": "[기출정답]해사영어(24년-13년).pdf",
}
GENERIC_CHOICES = [
    "① 원문 보기 참조",
    "② 원문 보기 참조",
    "③ 원문 보기 참조",
    "④ 원문 보기 참조",
]


@dataclass
class ParsedQuestion:
    question: Question
    group_index: int
    group_label: str
    source_pdf_id: str
    source_filename: str
    source_path: str
    source_question_id: str
    topic_tags: list[str]
    parser_tags: list[str]


class CircledAnswerTableReader:
    """Read answer tables that contain circled 1-4 numerals."""

    chars = {1: "①", 2: "②", 3: "③", 4: "④"}
    font_paths = [
        Path(r"C:\Windows\Fonts\batang.ttc"),
        Path(r"C:\Windows\Fonts\HANBatang.TTF"),
        Path(r"C:\Windows\Fonts\UnBatang.ttf"),
        Path(r"C:\Windows\Fonts\times.ttf"),
        Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path(r"C:\Windows\Fonts\seguisym.ttf"),
    ]

    def __init__(self) -> None:
        self.templates = self._build_templates()

    def read_pdf(self, pdf_path: Path) -> list[list[int]]:
        tables: list[list[int]] = []
        doc = fitz.open(pdf_path)
        try:
            for page_index in range(doc.page_count):
                page = doc[page_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                for box in self._table_boxes(image):
                    tables.append(self._answers_for_best_layout(image, box))
        finally:
            doc.close()
        return tables

    def _build_templates(self) -> list[tuple[int, list[list[int]]]]:
        templates: list[tuple[int, list[list[int]]]] = []
        for font_path in self.font_paths:
            if not font_path.exists():
                continue
            for size in range(34, 61, 2):
                try:
                    font = ImageFont.truetype(str(font_path), size)
                except OSError:
                    continue
                for value, char in self.chars.items():
                    canvas = Image.new("L", (100, 100), 255)
                    draw = ImageDraw.Draw(canvas)
                    bbox = draw.textbbox((0, 0), char, font=font)
                    x = (100 - (bbox[2] - bbox[0])) / 2 - bbox[0]
                    y = (100 - (bbox[3] - bbox[1])) / 2 - bbox[1]
                    draw.text((x, y), char, font=font, fill=0)
                    normalized = self._normalize_binary(canvas)
                    if normalized:
                        templates.append((value, normalized))
        return templates

    @staticmethod
    def _normalize_binary(image: Image.Image, size: int = 64) -> list[list[int]] | None:
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        coords = []
        for y in range(height):
            for x in range(width):
                if x < width * 0.08 or x > width * 0.92 or y < height * 0.05 or y > height * 0.95:
                    continue
                if pixels[x, y] < 185:
                    coords.append((x, y))
        if not coords:
            return None

        x0 = min(x for x, _ in coords)
        x1 = max(x for x, _ in coords)
        y0 = min(y for _, y in coords)
        y1 = max(y for _, y in coords)
        side = max(x1 - x0 + 1, y1 - y0 + 1) + 8
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        crop = gray.crop((
            int(round(cx - side / 2)),
            int(round(cy - side / 2)),
            int(round(cx + side / 2)),
            int(round(cy + side / 2)),
        ))
        canvas = Image.new("L", (side, side), 255)
        canvas.paste(crop, (0, 0))
        normalized = canvas.resize((size, size), Image.Resampling.LANCZOS)
        norm_pixels = normalized.load()
        return [
            [1 if norm_pixels[x, y] < 185 else 0 for x in range(size)]
            for y in range(size)
        ]

    @staticmethod
    def _binary_distance(left: list[list[int]] | None, right: list[list[int]] | None) -> float:
        if left is None or right is None:
            return 999.0
        diff = 0
        total = 0
        for y in range(len(left)):
            for x in range(len(left[0])):
                if left[y][x] != right[y][x]:
                    diff += 1
                if left[y][x] or right[y][x]:
                    total += 1
        return diff / max(1, total)

    def _classify_crop(self, crop: Image.Image) -> tuple[float, int]:
        normalized = self._normalize_binary(crop)
        best = min(
            (self._binary_distance(normalized, template), value)
            for value, template in self.templates
        )
        return best

    @staticmethod
    def _horizontal_lines(gray: Image.Image) -> list[dict]:
        width, height = gray.size
        pixels = gray.load()
        candidates = []
        for y in range(height):
            xs = [x for x in range(width) if pixels[x, y] < 180]
            if not xs:
                continue
            span = max(xs) - min(xs) + 1
            if span > width * 0.70 and len(xs) > 250:
                candidates.append((y, len(xs), min(xs), max(xs)))

        grouped = []
        current = []
        previous_y = None
        for item in candidates:
            y = item[0]
            if previous_y is None or y - previous_y <= 3:
                current.append(item)
            else:
                grouped.append(current)
                current = [item]
            previous_y = y
        if current:
            grouped.append(current)

        lines = []
        for group in grouped:
            best = max(group, key=lambda item: item[1])
            lines.append({
                "y": round(sum(item[0] for item in group) / len(group)),
                "count": best[1],
                "x0": best[2],
                "x1": best[3],
            })
        return lines

    def _table_boxes(self, image: Image.Image) -> list[tuple[int, int, int, int, int]]:
        lines = self._horizontal_lines(image.convert("L"))
        high = [line for line in lines if line["count"] > 1000]
        boxes: list[tuple[int, int, int, int, int]] = []
        index = 0

        while index < len(high):
            top = high[index]
            candidates = [
                line
                for line in high[index + 1:]
                if 120 <= line["y"] - top["y"] <= 340
            ]
            if not candidates:
                index += 1
                continue

            scored = []
            for bottom in candidates:
                half = (top["y"] + bottom["y"]) / 2
                mids = [
                    line
                    for line in lines
                    if top["y"] + 20 < line["y"] < bottom["y"] - 20
                ]
                close_mid = min(mids, key=lambda line: abs(line["y"] - half)) if mids else None
                mid_y = close_mid["y"] if close_mid and abs(close_mid["y"] - half) <= 35 else round(half)
                box = (
                    top["y"],
                    mid_y,
                    bottom["y"],
                    min(top["x0"], bottom["x0"]),
                    max(top["x1"], bottom["x1"]),
                )
                _, scores = self._answers_for_layout(image, box, "pair")
                scored.append((self._layout_score(scores), box, bottom))

            _, best_box, best_bottom = min(scored, key=lambda item: item[0])
            boxes.append(best_box)
            while index < len(high) and high[index]["y"] <= best_bottom["y"]:
                index += 1

        return boxes

    @staticmethod
    def _layout_score(scores: list[float]) -> float:
        return sum(1 for score in scores if score > 0.6) * 10 + sum(min(score, 1.0) for score in scores) / len(scores)

    def _answers_for_best_layout(self, image: Image.Image, box: tuple[int, int, int, int, int]) -> list[int]:
        pair_answers, pair_scores = self._answers_for_layout(image, box, "pair")
        single_answers, single_scores = self._answers_for_layout(image, box, "single")
        if self._layout_score(single_scores) < self._layout_score(pair_scores):
            return [0 if score > 0.65 else value for value, score in zip(single_answers, single_scores)]
        return pair_answers

    def _answers_for_layout(
        self,
        image: Image.Image,
        box: tuple[int, int, int, int, int],
        layout: str,
    ) -> tuple[list[int], list[float]]:
        top, mid, bottom, x0, x1 = box
        cell = (x1 - x0) / 20
        answers = []
        scores = []

        if layout == "single":
            y_center = (mid + bottom) / 2
            positions = [(x0 + (question_number - 0.5) * cell, y_center) for question_number in range(1, 21)]
        else:
            positions = []
            for question_number in range(1, 21):
                row = 0 if question_number <= 10 else 1
                pos = (question_number - 1) % 10
                col = pos * 2 + 1
                x_center = x0 + (col + 0.5) * cell
                y_center = (top + mid) / 2 if row == 0 else (mid + bottom) / 2
                positions.append((x_center, y_center))

        for x_center, y_center in positions:
            score, value = self._classify_crop(
                image.crop((
                    int(x_center - 30),
                    int(y_center - 30),
                    int(x_center + 30),
                    int(y_center + 30),
                ))
            )
            answers.append(value)
            scores.append(score)
        return answers, scores


QUESTION_CUE_RE = re.compile(
    r"(?:것은\??|고르시오\.?|Select|Choose|blank\.?|무엇인가\??|몇\s*개\s*인가\??|일치하지 않는 것은\??)",
    re.IGNORECASE,
)
CHOICE_MARKER_RE = re.compile(
    r"(?:①|②|③|④|[㉠-㉵]|\([0O1Il기나다라마바사아의피쇠]\)?|(?<!\d)[1-4][\)\.]\s)"
)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_noise(value or "")).strip()


def split_question_and_choices(segment: str) -> tuple[str, list[str], list[str]]:
    text = compact_text(segment)
    if not text:
        return "", [], ["blank_segment"]

    markers = [match for match in CHOICE_MARKER_RE.finditer(text) if match.start() > 10]
    if len(markers) >= 4:
        best = None
        for index in range(len(markers) - 3):
            seq = markers[index:index + 4]
            score = _choice_sequence_score(text, seq)
            if best is None or score > best[0]:
                best = (score, seq)
        if best and best[0] > -100:
            seq = best[1]
            choices = []
            for index, marker in enumerate(seq):
                end = seq[index + 1].start() if index + 1 < len(seq) else len(text)
                choices.append(text[marker.end():end].strip())
            if len(choices) == 4 and all(choices):
                return text[:seq[0].start()].strip(), choices, []

    count_match = re.search(r"(없음|\d+개)\s+(없음|\d+개)\s+(없음|\d+개)\s+(없음|\d+개)\s*$", text)
    if count_match:
        return text[:count_match.start()].strip(), list(count_match.groups()), []

    return text, GENERIC_CHOICES.copy(), ["choice_split_review"]


def _choice_sequence_score(text: str, seq: list[re.Match]) -> float:
    first = seq[0].start()
    chunks = []
    for index, marker in enumerate(seq):
        end = seq[index + 1].start() if index + 1 < len(seq) else len(text)
        chunks.append(text[marker.end():end].strip())
    if any(not chunk for chunk in chunks):
        return -999

    score = first / 10_000
    cues = list(QUESTION_CUE_RE.finditer(text[:first]))
    if cues:
        score += 50
        score -= min(100, first - cues[-1].end()) * 0.1
    if first < len(text) * 0.25:
        score -= 20
    if max(len(chunk) for chunk in chunks) > 800:
        score -= 20
    if sum(1 for chunk in chunks if len(chunk) > 8) >= 3:
        score += 20
    return score


def build_segment_map(group: dict, parser: QuestionParser) -> dict[int, tuple[str, int]]:
    candidates: dict[int, tuple[str, int, int]] = {}

    def add_candidate(number: int, segment: str, page_number: int) -> None:
        if not 1 <= number <= 20:
            return
        quality = len(compact_text(segment))
        if quality == 0:
            return
        current = candidates.get(number)
        if current is None or quality > current[2]:
            candidates[number] = (segment, page_number, quality)

    for page in group["pages"]:
        text = page.get("text", "")
        starts = [(number, start, end) for number, start, end in question_starts(text)]
        starts.extend(
            (int(match.group(1)), match.start(), match.end())
            for match in parser._find_question_starts(text, allow_subject_reset=False)
        )
        starts = sorted(starts, key=lambda item: item[1])
        unique_starts = []
        for number, start, end in starts:
            if not 1 <= number <= 20:
                continue
            if any(existing_number == number and abs(existing_start - start) < 8 for existing_number, existing_start, _ in unique_starts):
                continue
            unique_starts.append((number, start, end))

        for index, (number, _, end) in enumerate(unique_starts):
            next_start = unique_starts[index + 1][1] if index + 1 < len(unique_starts) else len(text)
            add_candidate(number, text[end:next_start], page["page"])

        for parsed in parser._parse_page(text, page["page"], [], allow_subject_reset=False):
            segment = parsed.text + " " + " ".join(f"{choice.symbol} {choice.text}" for choice in parsed.choices)
            add_candidate(parsed.number, segment, page["page"])

    recover_numbered_segments(candidates)
    return {number: (segment, page) for number, (segment, page, _) in candidates.items()}


def recover_numbered_segments(candidates: dict[int, tuple[str, int, int]]) -> None:
    """Split missed question starts embedded in the previous OCR segment."""
    for missing in range(1, 21):
        if missing in candidates:
            continue
        previous_numbers = [number for number in candidates if number < missing]
        if not previous_numbers:
            continue
        previous = max(previous_numbers)
        segment, page_number, _ = candidates[previous]
        match = re.search(rf"(?m)(?<!\d){missing}\s*[\.\u2022]\s*(?=\S)", segment)
        if match is None and missing >= 10:
            # OCR sometimes drops the leading "1" in 17/18/19 at a line start.
            match = re.search(rf"(?m)^\s*{missing % 10}\s*[\.\u2022]\s*(?=\S)", segment)
        if match is None or match.start() < 40:
            continue
        before = segment[:match.start()].strip()
        after = segment[match.end():].strip()
        if len(compact_text(after)) < 30:
            continue
        candidates[previous] = (before, page_number, len(compact_text(before)))
        candidates[missing] = (after, page_number, len(compact_text(after)))


def read_analysis_rows(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "02_questions_master.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["question_id"]: row for row in csv.DictReader(handle)}


def build_answer_map(input_dir: Path) -> dict[int, list[int]]:
    reader = CircledAnswerTableReader()
    one = reader.read_pdf(input_dir / ANSWER_FILENAMES["recent_2025_h2"])
    recent = reader.read_pdf(input_dir / ANSWER_FILENAMES["recent_2024_h2_2025_h1"])
    archive = reader.read_pdf(input_dir / ANSWER_FILENAMES["archive_2024_2013"])

    if len(one) != 1:
        raise RuntimeError(f"Expected 1 table in 2025 H2 answer PDF, got {len(one)}")
    if len(recent) != 3:
        raise RuntimeError(f"Expected 3 tables in 2024 H2-2025 H1 answer PDF, got {len(recent)}")
    if len(archive) != 26:
        raise RuntimeError(f"Expected 26 tables in 2024-2013 answer PDF, got {len(archive)}")

    answer_map = {1: one[0]}
    for offset, answers in enumerate(recent, start=2):
        answer_map[offset] = answers
    for offset, answers in enumerate(archive, start=5):
        answer_map[offset] = answers
    return answer_map


def build_session_map(groups: list[dict]) -> dict[int, int]:
    per_year: dict[int, int] = {}
    sessions: dict[int, int] = {}
    for index, group in enumerate(groups, start=1):
        year = int(group.get("year") or 0)
        per_year[year] = per_year.get(year, 0) + 1
        sessions[index] = per_year[year]
    return sessions


def build_questions(
    page_records: list[dict],
    output_dir: Path,
    input_dir: Path,
) -> tuple[list[ParsedQuestion], dict]:
    groups = build_groups(page_records)
    if len(groups) != 30:
        raise RuntimeError(f"Expected 30 question groups, got {len(groups)}")

    analysis_rows = read_analysis_rows(output_dir)
    answer_map = build_answer_map(input_dir)
    session_map = build_session_map(groups)
    parser = QuestionParser(EXAM_CODE)

    parsed_questions: list[ParsedQuestion] = []
    skipped_missing = []
    choice_review = 0
    no_answer = 0

    for group_index, group in enumerate(groups, start=1):
        segments = build_segment_map(group, parser)
        answers = answer_map.get(group_index)
        if not answers or len(answers) != 20:
            raise RuntimeError(f"Missing 20-answer key for group G{group_index:03d}")

        label = group_label(group, group_index)
        year = int(group.get("year") or 0)
        session = session_map[group_index]
        source_paths = {page.get("source_path", "") for page in group["pages"] if page.get("source_path")}
        source_path = sorted(source_paths)[0] if source_paths else ""

        for question_number in range(1, 21):
            segment_info = segments.get(question_number)
            if segment_info is None:
                skipped_missing.append(f"G{group_index:03d}-Q{question_number:02d}")
                continue

            segment, page_number = segment_info
            question_text, choice_texts, parser_tags = split_question_and_choices(segment)
            if not question_text:
                skipped_missing.append(f"G{group_index:03d}-Q{question_number:02d}")
                continue
            if "choice_split_review" in parser_tags:
                choice_review += 1

            row = analysis_rows.get(f"G{group_index:03d}-Q{question_number:02d}", {})
            topic = classify_topic(segment)
            topic_tags = [
                "해양경찰",
                "외부자료",
                f"G{group_index:03d}",
                str(group.get("period") or "").strip(),
                str(group.get("category") or "").strip(),
                topic.l1,
                topic.l2,
                topic.l3,
            ]
            topic_tags.extend((row.get("concept_tags") or "").split(";"))
            topic_tags = [tag for tag in dict.fromkeys(tag for tag in topic_tags if tag and tag != "unknown")]

            correct_answer = int(answers[question_number - 1])
            if correct_answer == 0:
                no_answer += 1
                parser_tags.append("answer_missing_in_source")

            choices = [
                Choice(number=index, symbol=f"{index}", text=text)
                for index, text in enumerate(choice_texts[:4], start=1)
            ]
            while len(choices) < 4:
                index = len(choices) + 1
                choices.append(Choice(number=index, symbol=f"{index}", text=GENERIC_CHOICES[index - 1]))

            question = Question(
                number=question_number,
                text=question_text,
                choices=choices,
                correct_answer=correct_answer,
                has_image=False,
                source_page=page_number,
                subject_name=SUBJECT_NAME,
                year=year,
                session=session,
                exam_type=EXAM_CODE,
            )
            parsed_questions.append(ParsedQuestion(
                question=question,
                group_index=group_index,
                group_label=label,
                source_pdf_id=str(group.get("pdf_id") or ""),
                source_filename=str(group.get("filename") or ""),
                source_path=source_path,
                source_question_id=f"G{group_index:03d}-Q{question_number:02d}",
                topic_tags=topic_tags,
                parser_tags=parser_tags,
            ))

    summary = {
        "groups": len(groups),
        "answer_groups": len(answer_map),
        "parsed_questions": len(parsed_questions),
        "skipped_missing_text": skipped_missing,
        "choice_split_review": choice_review,
        "answer_missing_in_source": no_answer,
    }
    return parsed_questions, summary


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.before_maritime_english_pdf_{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


def grouped(parsed_questions: Iterable[ParsedQuestion]) -> dict[int, list[ParsedQuestion]]:
    result: dict[int, list[ParsedQuestion]] = {}
    for item in parsed_questions:
        result.setdefault(item.group_index, []).append(item)
    return result


def import_into_db(db_path: Path, parsed_questions: list[ParsedQuestion], apply: bool) -> dict:
    if not apply:
        return {"db": str(db_path), "status": "dry_run", "saved": 0, "backup": None}
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    backup = backup_database(db_path)
    repo = ExamRepository(str(db_path))
    repo.init_database()
    registry = QuestionSourceRegistry(db_path)
    saved_total = 0

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        for group_index, items in grouped(parsed_questions).items():
            first = items[0]
            source = make_source(first)
            registration = registry.register_on(conn, source)
            metadata = SimpleNamespace(
                year=first.question.year,
                session=first.question.session,
                exam_type=EXAM_CODE,
            )
            saved_total += repo.save_questions([item.question for item in items], metadata, conn=conn)
            attach_metadata(conn, items, registration.source_id)
        conn.commit()

    return {"db": str(db_path), "status": "imported", "saved": saved_total, "backup": str(backup)}


def make_source(item: ParsedQuestion) -> QuestionSource:
    source_path = Path(item.source_path)
    if source_path.exists():
        content_hash = hashlib.sha256((sha256_file(source_path) + f":G{item.group_index:03d}").encode("utf-8")).hexdigest()
    else:
        content_hash = hashlib.sha256((item.source_filename + f":G{item.group_index:03d}").encode("utf-8")).hexdigest()
    return QuestionSource(
        provider="offline_pdf",
        source_url=str(source_path),
        document_id=f"G{item.group_index:03d}",
        attachment_url=None,
        attachment_filename=item.source_filename,
        content_hash=content_hash,
        fetched_at=utc_timestamp(),
    )


def attach_metadata(conn: sqlite3.Connection, items: list[ParsedQuestion], source_id: int) -> None:
    for item in items:
        row = conn.execute(
            """
            SELECT q.id, q.tags, q.exam_subject_id
            FROM questions q
            JOIN exam_subjects es ON es.id = q.exam_subject_id
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            WHERE e.code = ?
              AND s.name_ko = ?
              AND q.year = ?
              AND q.session = ?
              AND q.question_number = ?
            """,
            (
                EXAM_CODE,
                SUBJECT_NAME,
                item.question.year,
                item.question.session,
                item.question.number,
            ),
        ).fetchone()
        if row is None:
            continue

        tags = merge_tags(row["tags"], item.topic_tags, item.parser_tags)
        conn.execute(
            """
            UPDATE questions
            SET source_id = ?,
                source_question_id = ?,
                tags = ?
            WHERE id = ?
            """,
            (source_id, item.source_question_id, tags, row["id"]),
        )
        conn.execute(
            "UPDATE exam_subjects SET questions_count = 20 WHERE id = ?",
            (row["exam_subject_id"],),
        )


def merge_tags(existing: str | None, topic_tags: list[str], parser_tags: list[str]) -> str:
    tags = []
    for raw in list((existing or "").split(",")) + topic_tags + parser_tags:
        tag = str(raw or "").strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + re.sub(r"[\s/(){}\[\]<>]+", "", tag)
        if tag not in tags:
            tags.append(tag)
    return ", ".join(tags)


def load_page_records(output_dir: Path) -> list[dict]:
    jsonl = output_dir / "extracted_text" / "pages.jsonl"
    if not jsonl.exists():
        raise FileNotFoundError(jsonl)
    return load_jsonl(jsonl)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="Folder containing the offline maritime English PDFs.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Folder containing extracted_text/pages.jsonl.")
    parser.add_argument("--db", type=Path, action="append", default=None, help="Target SQLite DB. Repeat for multiple DBs.")
    parser.add_argument("--apply", action="store_true", help="Write to DB. Without this flag, only validate and summarize.")
    parser.add_argument("--summary-out", type=Path, default=None, help="Optional JSON summary path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_paths = args.db or [Path("data/exam_bank.db")]
    page_records = load_page_records(args.output_dir)
    parsed_questions, summary = build_questions(page_records, args.output_dir, args.input_dir)

    db_results = [import_into_db(path, parsed_questions, args.apply) for path in db_paths]
    summary["db_results"] = db_results
    summary["apply"] = bool(args.apply)

    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
