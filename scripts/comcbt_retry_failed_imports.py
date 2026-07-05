"""Reparse and optionally import failed COMCBT bulk rows from local PDFs."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.web_import.comcbt import document_from_title, parsed_exam_to_jsonable, write_json  # noqa: E402
from src.web_import.comcbt_pdf import ComcbtParseError, ComcbtPdfParser  # noqa: E402
from src.web_import.importer import (  # noqa: E402
    ComcbtImportService,
    QuestionSource,
    sha256_file,
    utc_timestamp,
)
from src.web_import.quality import evaluate_parsed_exam, write_quality_report  # noqa: E402


DEFAULT_STATUSES = ("blocked_quality", "import_failed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-log", default="tmp/comcbt_stream_20260630/bulk_import.jsonl")
    parser.add_argument("--source-work-dir", default="tmp/comcbt_stream_20260630")
    parser.add_argument("--work-dir", default="tmp/comcbt_retry_failed")
    parser.add_argument("--db", default="data/exam_bank.db")
    parser.add_argument("--log", help="Retry JSONL log path. Defaults under --work-dir.")
    parser.add_argument("--summary", help="Retry summary JSON path. Defaults under --work-dir.")
    parser.add_argument("--statuses", nargs="+", default=list(DEFAULT_STATUSES))
    parser.add_argument("--apply", action="store_true", help="Write importable reparsed rows to DB.")
    parser.add_argument("--force", action="store_true", help="Import even when source hash already exists.")
    parser.add_argument("--resume", action="store_true", help="Skip URLs already present in the retry log.")
    parser.add_argument("--max-docs", type=int)
    parser.add_argument("--start-index", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_log = Path(args.source_log)
    source_work_dir = Path(args.source_work_dir)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    retry_log = Path(args.log) if args.log else work_dir / "retry_import.jsonl"
    summary_path = Path(args.summary) if args.summary else work_dir / "retry_summary.json"

    rows = load_latest_rows(source_log, set(args.statuses))
    processed = load_processed_urls(retry_log) if args.resume else set()
    parser = ComcbtPdfParser()
    import_service = ComcbtImportService(args.db)
    counts: Counter[str] = Counter()
    causes: Counter[str] = Counter()
    attempted = 0
    started_at = time.time()

    for source_index, row in enumerate(rows):
        if source_index < args.start_index:
            continue
        if args.max_docs is not None and attempted >= args.max_docs:
            break
        url = str(row.get("url") or "")
        if not url:
            continue
        if args.resume and url in processed:
            counts["resume_skipped"] += 1
            continue

        attempted += 1
        retry_row = retry_one(
            row=row,
            source_index=source_index,
            source_work_dir=source_work_dir,
            work_dir=work_dir,
            parser=parser,
            import_service=import_service,
            apply=args.apply,
            force=args.force,
        )
        append_jsonl(retry_log, retry_row)
        retry_status = str(retry_row.get("retry_status") or "unknown")
        cause = str(retry_row.get("cause") or "unknown")
        counts[retry_status] += 1
        causes[cause] += 1
        print(
            f"retry index={source_index} status={retry_status} cause={cause} "
            f"questions={retry_row.get('questions', 0)} saved={retry_row.get('saved', 0)} "
            f"url={url}",
            flush=True,
        )

    summary = {
        "apply": bool(args.apply),
        "source_log": str(source_log),
        "source_work_dir": str(source_work_dir),
        "work_dir": str(work_dir),
        "db": str(args.db),
        "statuses": list(args.statuses),
        "candidate_rows": len(rows),
        "attempted": attempted,
        "counts": dict(counts),
        "causes": dict(causes),
        "elapsed_seconds": round(time.time() - started_at, 3),
        "log": str(retry_log),
    }
    write_json(summary_path, summary)
    print(f"retry_complete attempted={attempted} summary={summary_path}")
    return 0


def retry_one(
    row: dict[str, Any],
    source_index: int,
    source_work_dir: Path,
    work_dir: Path,
    parser: ComcbtPdfParser,
    import_service: ComcbtImportService,
    apply: bool,
    force: bool,
) -> dict[str, Any]:
    url = str(row.get("url") or "")
    mid = str(row.get("mid") or "unknown")
    document_srl = str(row.get("document_srl") or source_index)
    output_dir = work_dir / safe_path_part(mid) / safe_path_part(document_srl)
    output_dir.mkdir(parents=True, exist_ok=True)
    retry_row: dict[str, Any] = {
        "source_index": source_index,
        "url": url,
        "document_srl": document_srl,
        "mid": mid,
        "title": row.get("title"),
        "old_status": row.get("status"),
        "old_errors": row.get("errors") or ([row.get("error")] if row.get("error") else []),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    pdf_path = find_downloaded_pdf(source_work_dir, row)
    if pdf_path is None:
        retry_row.update(
            retry_status="missing_pdf",
            cause="missing_local_pdf",
            error="No local teacher PDF found under source work dir",
        )
        return retry_row

    try:
        document = document_from_title(
            title=str(row.get("title") or ""),
            url=url,
            mid=mid,
            document_srl=document_srl,
        )
        parsed_exam = parser.parse_pdf(
            pdf_path=pdf_path,
            document=document,
            attachments=[],
            selected_attachment=None,
            image_dir=output_dir / "images",
        )
        parsed_path = output_dir / "parsed_exam.json"
        quality_report_path = output_dir / "quality_report.json"
        write_json(parsed_path, parsed_exam_to_jsonable(parsed_exam))
        report = evaluate_parsed_exam(parsed_exam)
        write_quality_report(report, quality_report_path)
        source = QuestionSource(
            provider="comcbt",
            source_url=url,
            document_id=document_srl,
            attachment_url=None,
            attachment_filename=str(row.get("selected_attachment") or pdf_path.name),
            content_hash=str(row.get("hash") or sha256_file(pdf_path)),
            fetched_at=utc_timestamp(),
        )
        result = import_service.import_exam(
            parsed_exam=parsed_exam,
            source=source,
            force=force,
            quality_report_path=quality_report_path,
            apply=apply,
        )
        cause = classify_quality_result(
            importable=report.importable,
            errors=report.errors,
            title=str(row.get("title") or ""),
            old_errors=retry_row["old_errors"],
        )
        retry_status = result.status if apply else ("recovered_importable" if report.importable else "still_blocked_quality")
        retry_row.update(
            retry_status=retry_status,
            cause=cause,
            importable=report.importable,
            saved=result.saved,
            skipped=result.skipped,
            source_id=result.source_id,
            source_existing=result.source_existing,
            questions=len(parsed_exam.questions),
            answers=sum(1 for question in parsed_exam.questions if question.correct_answer),
            groups=len(parsed_exam.groups),
            parsed=str(parsed_path),
            quality_report=str(quality_report_path),
            errors=report.errors,
            warnings=report.warnings,
            diagnostics=parsed_exam.diagnostics,
        )
        return retry_row
    except Exception as exc:
        retry_row.update(
            retry_status="parse_failed",
            cause=classify_exception(exc, str(row.get("title") or "")),
            error=str(exc),
            traceback=traceback.format_exc(limit=8),
        )
        return retry_row


def load_latest_rows(path: Path, statuses: set[str]) -> list[dict[str, Any]]:
    latest_by_url: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = row.get("url")
        if not url:
            continue
        latest_by_url[str(url)] = row
    return [
        row
        for row in latest_by_url.values()
        if (row.get("status") or row.get("retry_status")) in statuses
    ]


def load_processed_urls(path: Path) -> set[str]:
    if not path.exists():
        return set()
    processed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = row.get("url")
        if url:
            processed.add(str(url))
    return processed


def find_downloaded_pdf(source_work_dir: Path, row: dict[str, Any]) -> Path | None:
    mid = safe_path_part(str(row.get("mid") or "unknown"))
    document_srl = safe_path_part(str(row.get("document_srl") or ""))
    downloads_dir = source_work_dir / mid / document_srl / "downloads"
    pdfs = sorted(downloads_dir.glob("*.pdf"))
    if not pdfs:
        return None
    selected = str(row.get("selected_attachment") or "")
    if selected:
        for pdf in pdfs:
            if pdf.name == selected:
                return pdf
    return pdfs[0]


def classify_quality_result(
    importable: bool,
    errors: list[str],
    title: str,
    old_errors: list[str],
) -> str:
    if importable:
        return "parser_fixed_importable"
    if is_accounting_practical(title):
        return "accounting_practical_non_mc"
    codes = {error.split(":", 1)[0] for error in errors}
    old_codes = {str(error).split(":", 1)[0] for error in old_errors}
    if codes == {"missing_question_image"}:
        return "missing_required_image"
    if "question_count" in codes:
        return "no_questions_detected"
    if "invalid_correct_answer" in codes and "choice_count" not in codes and "수능" in title:
        return "answer_key_format_unsupported"
    if "invalid_group_range" in codes or "group_assignment_mismatch" in codes or "group_child_mismatch" in codes:
        return "group_parser_remaining"
    if "choice_count" in codes or "invalid_correct_answer" in codes:
        if "Multiple inline answers in one question" in old_codes:
            return "inline_answer_parser_partially_fixed"
        return "choice_or_answer_parser_remaining"
    if "ambiguous_group_range" in codes:
        return "ambiguous_set_question"
    return "quality_block_remaining"


def classify_exception(exc: Exception, title: str) -> str:
    if is_accounting_practical(title):
        return "accounting_practical_non_mc"
    message = str(exc)
    if isinstance(exc, ComcbtParseError) and "Multiple inline answers in one question" in message:
        return "inline_answer_marker_remaining"
    return "parse_exception_remaining"


def is_accounting_practical(title: str) -> bool:
    return any(token in title for token in ("FAT", "TAT", "전산회계", "전산세무"))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value))[:80]


if __name__ == "__main__":
    raise SystemExit(main())
