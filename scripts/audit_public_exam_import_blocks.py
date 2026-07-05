"""Audit unresolved public exam PDF import rows and prepare recovery cohorts."""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter, defaultdict, deque
from pathlib import Path, PureWindowsPath
from typing import Iterable

try:
    import fitz
except Exception:  # pragma: no cover - reported in probe output.
    fitz = None  # type: ignore[assignment]


DEFAULT_ROOT = Path(r"T:\내 드라이브\[공부] 시험자료")
QUESTION_ROLE_MARKERS = {"자료", "문제", "문제지"}
ANSWER_ROLE_MARKERS = {"정답", "답", "답안", "해설"}
QUESTION_MARKER_RE = re.compile(r"(?m)(?:^|\s)(\d{1,3})\s*\.(?!\d)")
CHOICE_MARKER_RE = re.compile(r"[①②③④⑤❶❷❸❹❺]")


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def read_inventory(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def dedupe_inventory_rows(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows):
        relative_path = row.get("relative_path") or ""
        if not relative_path:
            continue
        copied = dict(row)
        copied["_inventory_index"] = str(index)
        if copied.get("status"):
            latest[relative_path] = copied
        else:
            latest.setdefault(relative_path, copied)
    return latest


def status_counts(rows: Iterable[dict[str, str]]) -> dict[str, int]:
    deduped = dedupe_inventory_rows(rows)
    counts = Counter(row.get("status") or "<blank>" for row in deduped.values())
    return dict(counts)


def role_marker_for_part(part: str) -> str:
    value = normalize_space(part)
    for marker in sorted(ANSWER_ROLE_MARKERS, key=len, reverse=True):
        if value.startswith(marker) or marker in value:
            return marker
    for marker in sorted(QUESTION_ROLE_MARKERS, key=len, reverse=True):
        if value == marker or value.startswith(f"{marker}(") or value.startswith(f"{marker}["):
            return marker
    return ""


def classify_roleish(relative_path: str) -> str:
    stem = path_from_relative(relative_path).stem
    parts = [part for part in stem.split("_") if part]
    markers = [role_marker_for_part(part) for part in parts]
    if any(marker in ANSWER_ROLE_MARKERS for marker in markers):
        return "answerish"
    if any(marker in QUESTION_ROLE_MARKERS for marker in markers):
        return "questionish"
    if any(marker in stem for marker in ANSWER_ROLE_MARKERS):
        return "answerish"
    if any(marker in stem for marker in QUESTION_ROLE_MARKERS):
        return "questionish"
    return "unknown"


def classify_no_text_case(
    *,
    raw_text_length: int,
    clean_text_length: int,
    image_count: int,
    question_marker_count: int,
    choice_marker_count: int = 0,
) -> str:
    if clean_text_length > 0:
        return "has_clean_text"
    if raw_text_length == 0 and image_count > 0:
        return "ocr_required"
    if raw_text_length == 0 and image_count == 0:
        return "empty_or_unreadable_pdf"
    if question_marker_count >= 1 and choice_marker_count >= 4:
        return "text_start_detection_failed"
    if question_marker_count >= 5 and choice_marker_count == 0:
        return "listing_or_non_exam_page"
    if raw_text_length >= 500:
        return "text_non_exam_or_answer_only"
    return "unknown_no_text"


def path_from_relative(relative_path: str) -> PureWindowsPath:
    return PureWindowsPath(relative_path.replace("/", "\\"))


def top_category(relative_path: str) -> str:
    parts = path_from_relative(relative_path).parts
    return parts[0] if len(parts) > 1 else ""


def resolve_pdf_path(root: Path, row: dict[str, str]) -> Path:
    raw_path = row.get("path") or ""
    if raw_path and Path(raw_path).exists():
        return Path(raw_path)
    return root / path_from_relative(row.get("relative_path") or "")


def probe_pdf(path: Path) -> dict[str, str | int]:
    if fitz is None:
        return {
            "path_exists": str(path.exists()).lower(),
            "probe_error": "PyMuPDF is not importable",
            "page_count": 0,
            "raw_text_length": 0,
            "raw_question_marker_count": 0,
            "raw_choice_marker_count": 0,
            "image_count": 0,
            "cause": "unknown_no_text",
        }
    if not path.exists():
        return {
            "path_exists": "false",
            "probe_error": "PDF path does not exist",
            "page_count": 0,
            "raw_text_length": 0,
            "raw_question_marker_count": 0,
            "raw_choice_marker_count": 0,
            "image_count": 0,
            "cause": "missing_file",
        }

    try:
        raw_pages: list[str] = []
        image_count = 0
        with fitz.open(path) as doc:
            for page in doc:
                raw_pages.append(page.get_text("text") or "")
                image_count += len(page.get_images(full=True))
            page_count = doc.page_count
        raw_text = "\n".join(raw_pages)
        compact_text = normalize_space(raw_text)
        question_count = len(QUESTION_MARKER_RE.findall(raw_text))
        choice_count = len(CHOICE_MARKER_RE.findall(raw_text))
        return {
            "path_exists": "true",
            "probe_error": "",
            "page_count": page_count,
            "raw_text_length": len(compact_text),
            "raw_question_marker_count": question_count,
            "raw_choice_marker_count": choice_count,
            "image_count": image_count,
            "cause": classify_no_text_case(
                raw_text_length=len(compact_text),
                clean_text_length=0,
                image_count=image_count,
                question_marker_count=question_count,
                choice_marker_count=choice_count,
            ),
        }
    except Exception as exc:  # pragma: no cover - depends on damaged PDFs.
        return {
            "path_exists": "true",
            "probe_error": f"{type(exc).__name__}: {exc}",
            "page_count": 0,
            "raw_text_length": 0,
            "raw_question_marker_count": 0,
            "raw_choice_marker_count": 0,
            "image_count": 0,
            "cause": "unreadable_pdf",
        }


def balanced_sample(rows: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    if limit <= 0 or len(rows) <= limit:
        return rows
    grouped: dict[str, deque[dict[str, str]]] = defaultdict(deque)
    for row in rows:
        grouped[top_category(row.get("relative_path") or "")].append(row)

    selected: list[dict[str, str]] = []
    group_names = sorted(grouped)
    while len(selected) < limit and group_names:
        next_group_names: list[str] = []
        for group_name in group_names:
            queue = grouped[group_name]
            if queue and len(selected) < limit:
                selected.append(queue.popleft())
            if queue:
                next_group_names.append(group_name)
        group_names = next_group_names
    return selected


def load_review_errors(review_dir: Path | None) -> dict[str, list[str]]:
    if not review_dir or not review_dir.exists():
        return {}
    errors_by_relative_path: dict[str, list[str]] = defaultdict(list)
    for payload_path in sorted(review_dir.glob("*.json")):
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        relative_path = str(meta.get("relative_path") or "")
        if not relative_path:
            absolute_path = str(meta.get("path") or "")
            relative_path = absolute_path
        errors = payload.get("errors") if isinstance(payload, dict) else []
        if isinstance(errors, list):
            errors_by_relative_path[relative_path].extend(str(error) for error in errors)
    return dict(errors_by_relative_path)


def error_class(error: str) -> str:
    value = normalize_space(error)
    lower = value.lower()
    if "correct_answer" in lower or "correct answer" in lower or "정답" in value:
        if "mismatch" in lower or "count" in lower or "개수" in value:
            return "answer_key_count_mismatch"
        return "invalid_correct_answer"
    if "answer" in lower and ("mismatch" in lower or "count" in lower):
        return "answer_key_count_mismatch"
    if "choice" in lower or "선택지" in value or "보기" in value:
        return "choice_count"
    if "contiguous" in lower or "연속" in value:
        return "question_numbers_not_contiguous"
    if "ambiguous" in lower or "range" in lower:
        return "ambiguous_group_range"
    if "image" in lower or "이미지" in value:
        return "missing_question_image"
    if ":" in value:
        return value.split(":", 1)[0][:80]
    return value[:80] or "<blank>"


def filename_prefix_before_role(stem: str, role_markers: set[str]) -> str:
    parts = stem.split("_")
    for index, part in enumerate(parts):
        marker = role_marker_for_part(part)
        if marker in role_markers:
            return "_".join(parts[:index])
    return ""


def build_directory_index(rows: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        relative_path = row.get("relative_path") or ""
        if not relative_path:
            continue
        path = path_from_relative(relative_path)
        index[str(path.parent)].append(relative_path)
    return dict(index)


def matching_primary_relatives(
    answer_relative_path: str,
    directory_index: dict[str, list[str]],
) -> list[str]:
    answer_path = path_from_relative(answer_relative_path)
    prefix = filename_prefix_before_role(answer_path.stem, ANSWER_ROLE_MARKERS)
    if not prefix:
        return []
    matches: list[str] = []
    for candidate in directory_index.get(str(answer_path.parent), []):
        if candidate == answer_relative_path:
            continue
        candidate_stem = path_from_relative(candidate).stem
        if not candidate_stem.startswith(f"{prefix}_"):
            continue
        candidate_role_prefix = filename_prefix_before_role(candidate_stem, QUESTION_ROLE_MARKERS)
        if candidate_role_prefix == prefix:
            matches.append(candidate)
    return sorted(matches)


def answer_secondary_links(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    rows_by_relative = dedupe_inventory_rows(rows)
    deduped_rows = list(rows_by_relative.values())
    directory_index = build_directory_index(deduped_rows)
    links: list[dict[str, str]] = []
    covered_statuses = {
        "imported",
        "dry_run_importable",
        "skipped_existing_key",
        "skipped_existing_key_precheck",
    }
    for row in deduped_rows:
        if row.get("status") != "skipped_answer_secondary":
            continue
        relative_path = row.get("relative_path") or ""
        primaries = matching_primary_relatives(relative_path, directory_index)
        primary_statuses = [rows_by_relative.get(primary, {}).get("status", "") for primary in primaries]
        if not primaries:
            resolution = "no_matching_primary"
        elif any(status in covered_statuses for status in primary_statuses):
            resolution = "covered_by_primary"
        elif any(status.startswith("blocked") for status in primary_statuses):
            resolution = "primary_blocked"
        elif any(not status for status in primary_statuses):
            resolution = "primary_blank_or_unprocessed"
        else:
            resolution = "primary_not_imported"
        links.append(
            {
                "relative_path": relative_path,
                "filename": row.get("filename") or path_from_relative(relative_path).name,
                "primary_candidates": ";".join(primaries),
                "primary_statuses": ";".join(primary_statuses),
                "resolution": resolution,
                "exam_type": row.get("inferred_exam") or "",
                "subject_name": row.get("inferred_subject") or "",
                "year": row.get("inferred_year") or "",
                "session": row.get("session") or "",
            }
        )
    return links


def enrich_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    enriched: list[dict[str, str]] = []
    for row in rows:
        copied = dict(row)
        copied["roleish"] = classify_roleish(copied.get("relative_path") or "")
        copied["top_category"] = top_category(copied.get("relative_path") or "")
        enriched.append(copied)
    return enriched


def counter_rows(counter: Counter[tuple[str, ...]], fields: list[str]) -> list[dict[str, str | int]]:
    output: list[dict[str, str | int]] = []
    for key, count in counter.most_common():
        row = {field: value for field, value in zip(fields, key)}
        row["count"] = count
        output.append(row)
    return output


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str] | None = None) -> None:
    row_list = list(rows)
    if fieldnames is None:
        fieldnames = sorted({key for row in row_list for key in row})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(row_list)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_audit(args: argparse.Namespace) -> dict:
    root = Path(args.root)
    inventory_path = Path(args.inventory)
    review_dir = Path(args.review_dir) if args.review_dir else None
    output_dir = Path(args.output_dir)

    raw_rows = read_inventory(inventory_path)
    deduped_map = dedupe_inventory_rows(raw_rows)
    deduped_rows = enrich_rows(deduped_map.values())
    errors_by_relative_path = load_review_errors(review_dir)

    status_counter = Counter(row.get("status") or "<blank>" for row in deduped_rows)
    status_role_counter = Counter(
        (row.get("status") or "<blank>", row.get("roleish") or "unknown") for row in deduped_rows
    )
    status_top_counter = Counter(
        (row.get("status") or "<blank>", row.get("top_category") or "") for row in deduped_rows
    )

    write_csv(output_dir / "deduped_inventory.csv", deduped_rows)
    write_csv(
        output_dir / "status_role_summary.csv",
        counter_rows(status_role_counter, ["status", "roleish"]),
        ["status", "roleish", "count"],
    )
    write_csv(
        output_dir / "status_top_category_summary.csv",
        counter_rows(status_top_counter, ["status", "top_category"]),
        ["status", "top_category", "count"],
    )

    probe_statuses = [] if args.no_probe else args.probe_status or ["blocked_no_text"]
    probe_rows: list[dict[str, str]] = []
    for status in probe_statuses:
        candidates = [row for row in deduped_rows if row.get("status") == status]
        if args.probe_sample_offset:
            offset = args.probe_sample_offset % len(candidates) if candidates else 0
            candidates = candidates[offset:] + candidates[:offset]
        probe_rows.extend(balanced_sample(candidates, args.probe_limit_per_status))

    probed_rows: list[dict[str, str | int]] = []
    reprocess_candidates: list[dict[str, str | int]] = []
    probe_started_at = time.monotonic()
    for row in probe_rows:
        if args.probe_time_budget_seconds and time.monotonic() - probe_started_at > args.probe_time_budget_seconds:
            break
        pdf_path = resolve_pdf_path(root, row)
        probe = probe_pdf(pdf_path)
        output_row: dict[str, str | int] = {
            "relative_path": row.get("relative_path") or "",
            "filename": row.get("filename") or path_from_relative(row.get("relative_path") or "").name,
            "status": row.get("status") or "",
            "top_category": row.get("top_category") or "",
            "roleish": row.get("roleish") or "",
            "inferred_exam": row.get("inferred_exam") or "",
            "inferred_subject": row.get("inferred_subject") or "",
            "inferred_year": row.get("inferred_year") or "",
            "session": row.get("session") or "",
            "notes": row.get("notes") or "",
            "absolute_path": str(pdf_path),
            **probe,
        }
        probed_rows.append(output_row)
        if output_row.get("status") == "blocked_no_text" and output_row.get("cause") == "text_start_detection_failed":
            reprocess_candidates.append(output_row)

    write_csv(output_dir / "blocked_no_text_sample.csv", probed_rows)
    write_csv(
        output_dir / "reprocess_candidates_phase1.csv",
        reprocess_candidates,
        [
            "relative_path",
            "filename",
            "status",
            "cause",
            "raw_text_length",
            "raw_question_marker_count",
            "raw_choice_marker_count",
            "image_count",
            "absolute_path",
            "top_category",
            "roleish",
            "inferred_exam",
            "inferred_subject",
            "inferred_year",
            "session",
            "notes",
        ],
    )

    quality_rows = [row for row in deduped_rows if row.get("status") == "blocked_quality"]
    quality_error_counter: Counter[tuple[str, str]] = Counter()
    quality_error_details: list[dict[str, str]] = []
    for row in quality_rows:
        relative_path = row.get("relative_path") or ""
        errors = errors_by_relative_path.get(relative_path) or [
            value for value in (row.get("notes") or "").split(";") if value.strip()
        ]
        if not errors:
            errors = ["<no_error_payload>"]
        for error in errors:
            klass = error_class(error)
            quality_error_counter[(klass, normalize_space(error)[:300])] += 1
            quality_error_details.append(
                {
                    "relative_path": relative_path,
                    "filename": row.get("filename") or "",
                    "top_category": row.get("top_category") or "",
                    "roleish": row.get("roleish") or "",
                    "error_class": klass,
                    "error": normalize_space(error),
                }
            )

    write_csv(
        output_dir / "blocked_quality_error_summary.csv",
        [
            {"error_class": klass, "error": error, "count": count}
            for (klass, error), count in quality_error_counter.most_common()
        ],
        ["error_class", "error", "count"],
    )
    write_csv(
        output_dir / "blocked_quality_error_details.csv",
        quality_error_details,
        ["relative_path", "filename", "top_category", "roleish", "error_class", "error"],
    )

    links = answer_secondary_links(deduped_rows)
    write_csv(
        output_dir / "answer_secondary_primary_links.csv",
        links,
        [
            "relative_path",
            "filename",
            "primary_candidates",
            "primary_statuses",
            "resolution",
            "exam_type",
            "subject_name",
            "year",
            "session",
        ],
    )
    write_csv(
        output_dir / "answer_secondary_without_primary.csv",
        [row for row in links if row["resolution"] != "covered_by_primary"],
        [
            "relative_path",
            "filename",
            "primary_candidates",
            "primary_statuses",
            "resolution",
            "exam_type",
            "subject_name",
            "year",
            "session",
        ],
    )

    no_text_causes = Counter(str(row.get("cause") or "") for row in probed_rows if row.get("status") == "blocked_no_text")
    summary = {
        "inventory": str(inventory_path),
        "review_dir": str(review_dir or ""),
        "output_dir": str(output_dir),
        "raw_row_count": len(raw_rows),
        "deduped_row_count": len(deduped_rows),
        "status_counts": dict(status_counter),
        "probed_row_count": len(probed_rows),
        "blocked_no_text_probe_causes": dict(no_text_causes),
        "phase1_reprocess_candidate_count": len(reprocess_candidates),
        "blocked_quality_error_class_counts": dict(
            Counter(klass for klass, _ in quality_error_counter.elements())
        ),
        "answer_secondary_resolution_counts": dict(Counter(row["resolution"] for row in links)),
    }
    write_json(output_dir / "status_summary.json", summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Existing 01_pdf_inventory.csv")
    parser.add_argument("--review-dir", default="", help="Existing review_payloads directory")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Root folder used for relative PDF paths")
    parser.add_argument("--output-dir", required=True, help="Directory to write audit reports")
    parser.add_argument(
        "--probe-status",
        action="append",
        default=None,
        help="Status to probe with PyMuPDF. Repeatable. Defaults to blocked_no_text.",
    )
    parser.add_argument(
        "--probe-limit-per-status",
        type=int,
        default=500,
        help="Balanced probe sample per status. Use 0 to probe all rows for that status.",
    )
    parser.add_argument("--probe-sample-offset", type=int, default=0, help="Rotate status rows before balanced sampling")
    parser.add_argument("--probe-time-budget-seconds", type=int, default=0, help="Stop probing after this many seconds")
    parser.add_argument("--no-probe", action="store_true", help="Skip PyMuPDF probing and only aggregate CSV/JSON data")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = run_audit(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
