"""Import offline police engineering PDF questions into the SQLite question bank."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
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

from scripts.analyze_police_engineering_pdfs import (  # noqa: E402
    KNOWN_GROUPS,
    SUBJECT_NAME,
    build_groups,
    classify_topic,
    group_label,
    load_jsonl,
)
from src.database.repository import ExamRepository  # noqa: E402
from src.parser.offline_sources import (  # noqa: E402
    OfflineParseResult,
    parse_offline_question_pdf,
    require_complete_offline_set,
    require_persistable_offline_questions,
    select_group_questions,
)
from src.parser.question import Choice, Question  # noqa: E402
from src.web_import.importer import QuestionSource, QuestionSourceRegistry, sha256_file, utc_timestamp  # noqa: E402


DEFAULT_OUTPUT_DIR = Path("outputs/police_engineering_pdf_20260702")
EXAM_CODE = "해양경찰 경찰직 기관학"

ANSWER_FILENAMES = {
    "recent_2025_h2": "[기출정답]경찰직 기관학(25년 하반기).pdf",
    "recent_2024_h2_2025_h1": "[기출정답]경찰직 기관학(24년 하반기-25년 상반기).pdf",
    "archive_2024_2013": "[기출정답]경찰직 기관술(학)(24-13년).pdf",
}


def _keys(filename: str, indexes: Iterable[int] | None = None) -> list[str]:
    groups = KNOWN_GROUPS[filename]
    selected = groups if indexes is None else [groups[index] for index in indexes]
    return [group.answer_key for group in selected]


ANSWER_KEYS = {
    "recent_2025_h2": _keys("[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf", [0, 1]),
    "recent_2024_h2_2025_h1": _keys(
        "[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf",
        [2, 3, 4],
    ),
    "archive_2024_2013": _keys(
        "[기출문제]경찰직 기관술(학)(24-13년).pdf",
        [0, 1, 2, 3, 4] + list(range(6, 23)),
    ),
}

NO_SOURCE_ANSWER_KEYS = set(_keys("[기출문제]경찰직 기관술(학)(24-13년).pdf", [5]))

MANUAL_ARCHIVE_2020_1 = [3, 3, 4, 2, 4, 4, 2, 3, 3, 4, 4, 4, 1, 3, 2, 3, 1, 3, 3, 2]
MANUAL_ARCHIVE_2017_2 = [2, 4, 1, 2, 3, 3, 1, 4, 3, 2, 4, 2, 1, 3, 4, 1, 2, 4, 3, 4]


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


class DigitAnswerTableReader:
    """Read offline answer tables using grid geometry plus central digit matching."""

    def __init__(self) -> None:
        self.templates = self._build_digit_templates()

    def read_pdf(self, pdf_path: Path) -> list[list[int]]:
        tables: list[list[int]] = []
        doc = fitz.open(pdf_path)
        try:
            for page_index in range(doc.page_count):
                page = doc[page_index]
                pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                for box in self._table_boxes(image):
                    tables.append(self._read_box(image, box))
        finally:
            doc.close()
        return tables

    def _build_digit_templates(self) -> list[tuple[int, list[list[int]]]]:
        font_path = Path(r"C:\Windows\Fonts\cambria.ttc")
        if not font_path.exists():
            font_path = Path(r"C:\Windows\Fonts\times.ttf")
        if not font_path.exists():
            font_path = Path(r"C:\Windows\Fonts\malgun.ttf")
        if not font_path.exists():
            raise FileNotFoundError("No usable Windows font found for answer digit templates")

        font = ImageFont.truetype(str(font_path), 26)
        templates = []
        for value in range(1, 5):
            canvas = Image.new("L", (80, 80), 255)
            draw = ImageDraw.Draw(canvas)
            bbox = draw.textbbox((0, 0), str(value), font=font)
            draw.text(
                ((80 - (bbox[2] - bbox[0])) / 2 - bbox[0], (80 - (bbox[3] - bbox[1])) / 2 - bbox[1]),
                str(value),
                font=font,
                fill=0,
            )
            templates.append((value, self._normalize_binary(canvas.crop((22, 22, 58, 58)))))
        return templates

    @staticmethod
    def _normalize_binary(image: Image.Image, size: int = 32, threshold: int = 170) -> list[list[int]] | None:
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        coords = []
        for y in range(height):
            for x in range(width):
                if pixels[x, y] < threshold:
                    coords.append((x, y))
        if not coords:
            return None
        x0 = min(x for x, _ in coords)
        x1 = max(x for x, _ in coords)
        y0 = min(y for _, y in coords)
        y1 = max(y for _, y in coords)
        side = max(x1 - x0 + 1, y1 - y0 + 1) + 4
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
            [1 if norm_pixels[x, y] < threshold else 0 for x in range(size)]
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

    @staticmethod
    def _ring_coverage(crop: Image.Image) -> tuple[int, int]:
        gray = crop.convert("L").resize((80, 80))
        pixels = gray.load()
        buckets = set()
        ring_pixels = 0
        for y in range(12, 68):
            for x in range(12, 68):
                if pixels[x, y] >= 170:
                    continue
                radius = math.hypot(x - 40, y - 40)
                if 13 <= radius <= 22:
                    bucket = int(((math.atan2(y - 40, x - 40) + math.pi) / (2 * math.pi)) * 24)
                    buckets.add(bucket)
                    ring_pixels += 1
        return len(buckets), ring_pixels

    def _classify_crop(self, crop: Image.Image) -> int:
        coverage, ring_pixels = self._ring_coverage(crop)
        if coverage < 22 or ring_pixels < 80:
            return 0

        gray = crop.convert("L")
        width, height = gray.size
        pixels = gray.load()
        coords = [
            (x, y)
            for y in range(8, height - 8)
            for x in range(8, width - 8)
            if pixels[x, y] < 170
        ]
        if len(coords) < 15:
            return 0
        x0 = min(x for x, _ in coords)
        x1 = max(x for x, _ in coords)
        y0 = min(y for _, y in coords)
        y1 = max(y for _, y in coords)
        if (x1 - x0 + 1) > 1.45 * (y1 - y0 + 1):
            return 0

        center = gray.crop((width // 2 - 18, height // 2 - 18, width // 2 + 18, height // 2 + 18))
        normalized = self._normalize_binary(center)
        score, value = min(
            (self._binary_distance(normalized, template), value)
            for value, template in self.templates
        )
        return 0 if score > 0.95 else value

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
            if span > width * 0.55 and len(xs) > 300:
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
        solid = [line for line in lines if line["count"] > 1200]
        candidates: list[tuple[int, int, int, int, int, int]] = []
        for index, top in enumerate(solid):
            for bottom in solid[index + 1:]:
                height = bottom["y"] - top["y"]
                if height < 120:
                    continue
                if height > 430:
                    break
                x0 = min(top["x0"], bottom["x0"])
                x1 = max(top["x1"], bottom["x1"])
                if x1 - x0 < 900:
                    continue
                inner_lines = [
                    line for line in lines
                    if top["y"] - 3 <= line["y"] <= bottom["y"] + 3
                    and line["count"] > 500
                    and abs(line["x0"] - x0) < 30
                    and abs(line["x1"] - x1) < 30
                ]
                if len(inner_lines) >= 5:
                    rows = 4
                elif len(inner_lines) == 4:
                    rows = 4
                elif len(inner_lines) == 3:
                    rows = 2
                else:
                    rows = 4 if height > 300 else 2

                values = self._read_box(image, (top["y"], bottom["y"], x0, x1, rows))
                valid = sum(1 for value in values if value)
                if valid >= rows * 10 * 0.65:
                    candidates.append((top["y"], bottom["y"], x0, x1, rows, valid))

        candidates.sort(key=lambda box: (box[0], -box[5]))
        chosen = []
        for candidate in candidates:
            if any(not (candidate[1] < box[0] + 8 or candidate[0] > box[1] - 8) for box in chosen):
                continue
            chosen.append(candidate)
        return [(top, bottom, x0, x1, rows) for top, bottom, x0, x1, rows, _ in chosen]

    def _read_box(self, image: Image.Image, box: tuple[int, int, int, int, int]) -> list[int]:
        top, bottom, x0, x1, rows = box
        if rows == 2:
            pair_answers = self._read_box_layout(image, box, "pair")
            single_answers = self._read_box_layout(image, box, "single")
            if sum(1 for value in single_answers if value) > sum(1 for value in pair_answers if value):
                return single_answers
            return pair_answers
        return self._read_box_layout(image, box, "pair")

    def _read_box_layout(self, image: Image.Image, box: tuple[int, int, int, int, int], layout: str) -> list[int]:
        top, bottom, x0, x1, rows = box
        cell = (x1 - x0) / 20
        row_height = (bottom - top) / rows
        answers = []
        for question_number in range(1, rows * 10 + 1):
            if layout == "single":
                x_center = x0 + (question_number - 0.5) * cell
                y_center = top + 1.5 * row_height
            else:
                row = (question_number - 1) // 10
                pos = (question_number - 1) % 10
                x_center = x0 + (pos * 2 + 1.5) * cell
                y_center = top + (row + 0.5) * row_height
            crop = self._best_answer_crop(image, x_center, y_center)
            answers.append(self._classify_crop(crop))
        return answers

    def _best_answer_crop(self, image: Image.Image, x_center: float, y_center: float) -> Image.Image:
        best_crop = None
        best_score = (-1, -1)
        for dx in (-24, -16, -8, 0, 8, 16, 24):
            for dy in (-8, 0, 8):
                crop = image.crop((
                    int(x_center + dx - 40),
                    int(y_center + dy - 40),
                    int(x_center + dx + 40),
                    int(y_center + dy + 40),
                ))
                coverage, ring_pixels = self._ring_coverage(crop)
                score = (coverage, ring_pixels)
                if score > best_score:
                    best_score = score
                    best_crop = crop
        return best_crop if best_crop is not None else image.crop((
            int(x_center - 40),
            int(y_center - 40),
            int(x_center + 40),
            int(y_center + 40),
        ))


def read_analysis_rows(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "02_questions_master.csv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["question_id"]: row for row in csv.DictReader(handle)}


def build_answer_map(input_dir: Path) -> dict[str, list[int]]:
    reader = DigitAnswerTableReader()
    answer_dir = input_dir
    result: dict[str, list[int]] = {}
    expected_counts = {
        "recent_2025_h2": 2,
        "recent_2024_h2_2025_h1": 3,
        "archive_2024_2013": 22,
    }
    for bucket, filename in ANSWER_FILENAMES.items():
        tables = reader.read_pdf(answer_dir / filename)
        if bucket == "archive_2024_2013" and len(tables) == 20:
            tables = (
                tables[:9]
                + [MANUAL_ARCHIVE_2020_1]
                + tables[9:13]
                + [MANUAL_ARCHIVE_2017_2]
                + tables[13:]
            )
        expected = expected_counts[bucket]
        if len(tables) != expected:
            raise RuntimeError(f"Expected {expected} answer tables in {filename}, got {len(tables)}")
        keys = ANSWER_KEYS[bucket]
        if len(keys) != len(tables):
            raise RuntimeError(f"Answer key/table count mismatch for {filename}: {len(keys)} keys, {len(tables)} tables")
        for key, answers in zip(keys, tables):
            result[key] = answers
    for key in NO_SOURCE_ANSWER_KEYS:
        result[key] = [0] * 20
    return result


def build_session_map(groups: list[dict]) -> dict[int, int]:
    per_year: dict[int, int] = {}
    sessions: dict[int, int] = {}
    for index, group in enumerate(groups, start=1):
        year = int(group.get("year") or 0)
        per_year[year] = per_year.get(year, 0) + 1
        sessions[index] = per_year[year]
    return sessions


def parse_subject_question_pdf(
    path: Path, metadata: dict[str, object] | None = None
) -> OfflineParseResult:
    source_metadata = {"subject_name": SUBJECT_NAME, "exam_type": EXAM_CODE}
    source_metadata.update(metadata or {})
    return parse_offline_question_pdf(path, source_metadata)


def build_questions(page_records: list[dict], output_dir: Path, input_dir: Path) -> tuple[list[ParsedQuestion], dict]:
    groups = build_groups(page_records)
    expected_groups = sum(len(items) for items in KNOWN_GROUPS.values())
    if len(groups) != expected_groups:
        raise RuntimeError(f"Expected {expected_groups} question groups, got {len(groups)}")

    answer_map = build_answer_map(input_dir)
    analysis_rows = read_analysis_rows(output_dir)
    session_map = build_session_map(groups)

    parsed_questions: list[ParsedQuestion] = []
    missing_text = []
    choice_review = 0
    answer_review = 0
    source_cache: dict[str, OfflineParseResult] = {}

    for group_index, group in enumerate(groups, start=1):
        answer_key = str(group.get("answer_key") or "")
        answers = answer_map.get(answer_key)
        if not answers:
            raise RuntimeError(f"Missing answer table for {answer_key} (G{group_index:03d})")
        expected_count = int(group.get("question_count") or len(answers))
        if len(answers) != expected_count:
            raise RuntimeError(f"Answer count mismatch for {answer_key}: expected {expected_count}, got {len(answers)}")

        label = group_label(group, group_index)
        year = int(group.get("year") or 0)
        session = session_map[group_index]
        source_paths = {page.get("source_path", "") for page in group["pages"] if page.get("source_path")}
        source_path = sorted(source_paths)[0] if source_paths else ""
        common_questions, rejected_count = select_group_questions(
            group, parse_subject_question_pdf, source_cache
        )
        choice_review += rejected_count
        require_complete_offline_set(
            common_questions,
            expected_numbers=range(1, expected_count + 1),
            answers=answers,
            rejected_count=rejected_count,
            choice_counts={number: len(item.choices) for number, item in common_questions.items()},
        )

        for question_number in range(1, expected_count + 1):
            parsed = common_questions.get(question_number)
            if parsed is None:
                missing_text.append(f"G{group_index:03d}-Q{question_number:02d}")
                continue
            question_text = parsed.stem
            choice_texts = parsed.choices
            page_number = parsed.source_page
            parser_tags = list(parsed.diagnostics)
            segment = "\n".join([question_text, *choice_texts])

            row = analysis_rows.get(f"G{group_index:03d}-Q{question_number:02d}", {})
            topic = classify_topic(segment)
            topic_tags = [
                "해양경찰",
                "외부자료",
                "경찰직기관학",
                "기관학",
                f"G{group_index:03d}",
                answer_key,
                str(group.get("period") or "").strip(),
                str(group.get("session") or "").strip(),
                str(group.get("category") or "").strip(),
                topic.l1,
                topic.l2,
                topic.l3,
            ]
            topic_tags.extend((row.get("concept_tags") or "").split(";"))
            topic_tags = [tag for tag in dict.fromkeys(tag for tag in topic_tags if tag and tag != "unknown")]

            correct_answer = int(answers[question_number - 1])
            if correct_answer == 0:
                answer_review += 1
                parser_tags.append("answer_requires_manual_review")

            choices = [Choice(number=index, symbol=f"{index}", text=text) for index, text in enumerate(choice_texts, start=1)]

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
        "missing_text_count": len(missing_text),
        "missing_text_examples": missing_text[:50],
        "choice_split_review": choice_review,
        "answer_requires_manual_review": answer_review,
    }
    return parsed_questions, summary


def backup_database(db_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_path.with_name(f"{db_path.stem}.before_police_engineering_pdf_{stamp}{db_path.suffix}")
    shutil.copy2(db_path, backup)
    return backup


def grouped(parsed_questions: Iterable[ParsedQuestion]) -> dict[int, list[ParsedQuestion]]:
    result: dict[int, list[ParsedQuestion]] = {}
    for item in parsed_questions:
        result.setdefault(item.group_index, []).append(item)
    return result


def import_into_db(db_path: Path, parsed_questions: list[ParsedQuestion], apply: bool) -> dict:
    require_persistable_offline_questions(parsed_questions)
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
        for _, items in grouped(parsed_questions).items():
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
    source_hash = sha256_file(source_path) if source_path.exists() else item.source_filename
    content_hash = hashlib.sha256((source_hash + f":G{item.group_index:03d}").encode("utf-8")).hexdigest()
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
    max_count = max(item.question.number for item in items)
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
            (EXAM_CODE, SUBJECT_NAME, item.question.year, item.question.session, item.question.number),
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
            "UPDATE exam_subjects SET questions_count = MAX(COALESCE(questions_count, 0), ?) WHERE id = ?",
            (max_count, row["exam_subject_id"]),
        )


def merge_tags(existing: str | None, topic_tags: list[str], parser_tags: list[str]) -> str:
    tags = []
    for raw in list((existing or "").split(",")) + topic_tags + parser_tags:
        tag = str(raw or "").strip()
        if not tag:
            continue
        if not tag.startswith("#"):
            tag = "#" + re.sub(r"[\s/(){}\[\]<>|·]+", "", tag)
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
    parser.add_argument("input_dir", type=Path, help="Folder containing the offline police engineering PDFs.")
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
