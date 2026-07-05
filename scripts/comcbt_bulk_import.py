"""Bulk crawl and import public comcbt.com exam documents."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.comcbt_crawl import (  # noqa: E402
    download_selected_attachment,
    parse_downloaded_attachment,
    source_from_downloaded_attachment,
)
from src.web_import.comcbt import SlowHttpClient, parsed_exam_to_jsonable, write_json  # noqa: E402
from src.web_import.comcbt_inventory import (  # noqa: E402
    COMCBT_INDEX_URL,
    PROVIDER,
    allowed_pagination_urls,
    assert_allowed_crawl_url,
    crawl_document_inventory,
    discover_board_entries,
    document_entries_from_board_html,
)
from src.web_import.importer import ComcbtImportService  # noqa: E402


FINAL_STATUSES = {
    "imported",
    "skipped_duplicate",
    "blocked_quality",
    "dry_run",
    "no_attachment",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between uncached requests.")
    parser.add_argument("--cache-dir", default="tmp/comcbt_cache", help="HTTP response cache directory.")
    parser.add_argument("--db", default="data/exam_bank.db", help="Target SQLite database.")
    parser.add_argument("--work-dir", default="tmp/comcbt_bulk", help="Directory for PDFs, parse JSON, reports, and logs.")
    parser.add_argument("--manifest", default="tmp/comcbt_manifest_full.json", help="Document manifest path.")
    parser.add_argument("--log", help="JSONL progress log path. Defaults under --work-dir.")
    parser.add_argument("--progress-log", help="Board/page progress JSONL path. Defaults under --work-dir.")
    parser.add_argument("--summary", help="Summary JSON path. Defaults under --work-dir.")
    parser.add_argument("--apply", action="store_true", help="Write imports to DB. Omit for dry-run.")
    parser.add_argument("--force", action="store_true", help="Import even when source hash already exists.")
    parser.add_argument("--resume", action="store_true", help="Skip documents already recorded with final status.")
    parser.add_argument("--retry-failures", action="store_true", help="Retry failed rows when --resume is used.")
    parser.add_argument("--max-docs", type=int, help="Maximum documents to process/import from the manifest.")
    parser.add_argument("--start-index", type=int, default=0, help="Zero-based manifest document index to start from.")

    crawl = parser.add_argument_group("crawl manifest")
    crawl.add_argument("--crawl", action="store_true", help="Crawl a fresh manifest before importing.")
    crawl.add_argument(
        "--stream",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When crawling, import documents as each board/page is discovered.",
    )
    crawl.add_argument("--index-url", default=COMCBT_INDEX_URL)
    crawl.add_argument("--max-boards", type=int)
    crawl.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Maximum board pages per board when --crawl is used.",
    )
    crawl.add_argument(
        "--max-empty-pages",
        type=int,
        default=2,
        help="Stop a board after this many non-initial pages add no new documents.",
    )
    crawl.add_argument("--crawl-max-docs", type=int, help="Maximum documents to discover when --crawl is used.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log) if args.log else work_dir / "bulk_import.jsonl"
    progress_log_path = Path(args.progress_log) if args.progress_log else work_dir / "bulk_progress.jsonl"
    summary_path = Path(args.summary) if args.summary else work_dir / "bulk_summary.json"
    manifest_path = Path(args.manifest)
    client = SlowHttpClient(delay_seconds=args.delay, cache_dir=args.cache_dir)
    service = ComcbtImportService(args.db)

    if args.crawl and args.stream:
        summary = _stream_crawl_and_import(
            args=args,
            client=client,
            import_service=service,
            manifest_path=manifest_path,
            log_path=log_path,
            progress_log_path=progress_log_path,
        )
        write_json(summary_path, summary)
        print(f"bulk_complete attempted={summary['attempted']} summary={summary_path}")
        return 0

    if args.crawl:
        manifest = crawl_document_inventory(
            client=client,
            index_url=args.index_url,
            max_boards=args.max_boards,
            max_pages=args.max_pages,
            max_docs=args.crawl_max_docs,
        )
        write_json(manifest_path, manifest)
        print(
            f"crawl_complete boards={len(manifest['boards'])} "
            f"documents={len(manifest['documents'])} manifest={manifest_path}"
        )
    else:
        manifest = _read_json(manifest_path)

    documents = list(manifest.get("documents") or [])
    processed = _load_processed_urls(log_path, retry_failures=args.retry_failures) if args.resume else set()
    counts: dict[str, int] = {}
    started_at = time.time()
    attempted = 0

    for index, document in enumerate(documents):
        if index < args.start_index:
            continue
        if args.max_docs is not None and attempted >= args.max_docs:
            break
        url = document.get("document_url")
        if not url:
            continue
        if args.resume and url in processed:
            _increment(counts, "resume_skipped")
            continue

        attempted += 1
        row = _import_one_document(
            client=client,
            import_service=service,
            document=document,
            index=index,
            work_dir=work_dir,
            apply=args.apply,
            force=args.force,
        )
        _append_jsonl(log_path, row)
        status = str(row.get("status") or "unknown")
        _increment(counts, status)
        print(
            f"index={index} status={status} saved={row.get('saved', 0)} "
            f"questions={row.get('questions', 0)} url={url}",
            flush=True,
        )

    summary = {
        "apply": bool(args.apply),
        "manifest": str(manifest_path),
        "log": str(log_path),
        "db": str(args.db),
        "total_manifest_documents": len(documents),
        "attempted": attempted,
        "counts": counts,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }
    write_json(summary_path, summary)
    print(f"bulk_complete attempted={attempted} summary={summary_path}")
    return 0


def _stream_crawl_and_import(
    args: argparse.Namespace,
    client: SlowHttpClient,
    import_service: ComcbtImportService,
    manifest_path: Path,
    log_path: Path,
    progress_log_path: Path,
) -> dict[str, Any]:
    started_at = time.time()
    boards = discover_board_entries(
        client,
        index_url=args.index_url,
        max_boards=args.max_boards,
    )
    manifest = {
        "provider": PROVIDER,
        "boards": [asdict(board) for board in boards],
        "documents": [],
        "stats": {},
    }
    write_json(manifest_path, manifest)

    processed = _load_processed_urls(log_path, retry_failures=args.retry_failures) if args.resume else set()
    counts: dict[str, int] = {}
    seen_document_urls: set[str] = set()
    attempted = 0
    discovered = 0
    stop_all = False

    _append_progress(
        progress_log_path,
        {
            "event": "inventory_complete",
            "boards": len(boards),
            "manifest": str(manifest_path),
        },
    )
    print(
        f"inventory_complete boards={len(boards)} manifest={manifest_path}",
        flush=True,
    )

    for board_index, board in enumerate(boards):
        if stop_all:
            break
        board_stats = {
            "requested_urls": [],
            "new_docs": 0,
            "duplicate_docs": 0,
            "failures": [],
            "truncated": False,
        }
        _append_progress(
            progress_log_path,
            {
                "event": "board_start",
                "board_index": board_index,
                "total_boards": len(boards),
                "mid": board.mid,
                "exam_name": board.exam_name,
                "board_url": board.board_url,
            },
        )
        print(
            f"board_start {board_index + 1}/{len(boards)} mid={board.mid} exam={board.exam_name}",
            flush=True,
        )

        page_urls = [board.board_url]
        queued_urls = {board.board_url}
        page_index = 0
        empty_pages = 0

        while page_index < len(page_urls) and page_index < args.max_pages:
            page_url = page_urls[page_index]
            page_number = page_index + 1
            page_index += 1
            page_new_docs = 0
            page_duplicate_docs = 0

            try:
                assert_allowed_crawl_url(page_url)
                board_stats["requested_urls"].append(page_url)
                html = client.fetch_text(page_url)
            except Exception as exc:
                failure = {"url": page_url, "error": str(exc)}
                board_stats["failures"].append(failure)
                _append_progress(
                    progress_log_path,
                    {
                        "event": "page_failed",
                        "board_index": board_index,
                        "mid": board.mid,
                        "page_number": page_number,
                        "page_url": page_url,
                        "error": str(exc),
                    },
                )
                continue

            page_documents = document_entries_from_board_html(html, board)
            for document in page_documents:
                if args.crawl_max_docs is not None and discovered >= args.crawl_max_docs:
                    stop_all = True
                    break

                if document.document_url in seen_document_urls:
                    page_duplicate_docs += 1
                    board_stats["duplicate_docs"] += 1
                    continue

                seen_document_urls.add(document.document_url)
                document_row = asdict(document)
                manifest["documents"].append(document_row)
                discovered += 1
                page_new_docs += 1
                board_stats["new_docs"] += 1

                _append_progress(
                    progress_log_path,
                    {
                        "event": "document_discovered",
                        "board_index": board_index,
                        "mid": board.mid,
                        "document_index": discovered - 1,
                        "document_url": document.document_url,
                        "title": document.title,
                    },
                )

                if discovered - 1 < args.start_index:
                    continue
                if args.max_docs is not None and attempted >= args.max_docs:
                    stop_all = True
                    break
                if args.resume and document.document_url in processed:
                    _increment(counts, "resume_skipped")
                    _append_progress(
                        progress_log_path,
                        {
                            "event": "document_skipped_resume",
                            "board_index": board_index,
                            "mid": board.mid,
                            "document_url": document.document_url,
                        },
                    )
                    continue

                attempted += 1
                row = _import_one_document(
                    client=client,
                    import_service=import_service,
                    document=document_row,
                    index=discovered - 1,
                    work_dir=Path(args.work_dir),
                    apply=args.apply,
                    force=args.force,
                )
                _append_jsonl(log_path, row)
                status = str(row.get("status") or "unknown")
                _increment(counts, status)
                print(
                    f"doc index={discovered - 1} board={board_index + 1}/{len(boards)} "
                    f"status={status} saved={row.get('saved', 0)} "
                    f"questions={row.get('questions', 0)} url={document.document_url}",
                    flush=True,
                )

            for next_url in allowed_pagination_urls(html, board):
                if len(page_urls) >= args.max_pages:
                    break
                if next_url not in queued_urls:
                    queued_urls.add(next_url)
                    page_urls.append(next_url)

            if page_new_docs == 0 and page_url != board.board_url:
                empty_pages += 1
            else:
                empty_pages = 0

            _append_progress(
                progress_log_path,
                {
                    "event": "page_done",
                    "board_index": board_index,
                    "total_boards": len(boards),
                    "mid": board.mid,
                    "page_number": page_number,
                    "page_url": page_url,
                    "page_new_docs": page_new_docs,
                    "page_duplicate_docs": page_duplicate_docs,
                    "board_new_docs": board_stats["new_docs"],
                    "discovered": discovered,
                    "attempted": attempted,
                    "counts": counts,
                    "queued_pages": len(page_urls),
                    "elapsed_seconds": round(time.time() - started_at, 3),
                },
            )
            write_json(manifest_path, manifest)
            print(
                f"page_done board={board_index + 1}/{len(boards)} mid={board.mid} "
                f"page={page_number}/{args.max_pages} new_docs={page_new_docs} "
                f"discovered={discovered} attempted={attempted}",
                flush=True,
            )

            if empty_pages >= args.max_empty_pages:
                _append_progress(
                    progress_log_path,
                    {
                        "event": "board_empty_page_stop",
                        "board_index": board_index,
                        "mid": board.mid,
                        "empty_pages": empty_pages,
                    },
                )
                break
            if stop_all:
                break

        if page_index >= args.max_pages and page_index < len(page_urls):
            board_stats["truncated"] = True
            _append_progress(
                progress_log_path,
                {
                    "event": "board_page_cap_reached",
                    "board_index": board_index,
                    "mid": board.mid,
                    "max_pages": args.max_pages,
                    "queued_pages": len(page_urls),
                },
            )

        manifest["stats"][board.mid] = board_stats
        write_json(manifest_path, manifest)
        _append_progress(
            progress_log_path,
            {
                "event": "board_done",
                "board_index": board_index,
                "total_boards": len(boards),
                "mid": board.mid,
                "new_docs": board_stats["new_docs"],
                "requested_pages": len(board_stats["requested_urls"]),
                "discovered": discovered,
                "attempted": attempted,
                "counts": counts,
            },
        )
        print(
            f"board_done {board_index + 1}/{len(boards)} mid={board.mid} "
            f"pages={len(board_stats['requested_urls'])} new_docs={board_stats['new_docs']} "
            f"attempted={attempted}",
            flush=True,
        )

    return {
        "apply": bool(args.apply),
        "manifest": str(manifest_path),
        "log": str(log_path),
        "progress_log": str(progress_log_path),
        "db": str(args.db),
        "total_boards": len(boards),
        "total_manifest_documents": discovered,
        "attempted": attempted,
        "counts": counts,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }


def _import_one_document(
    client: SlowHttpClient,
    import_service: ComcbtImportService,
    document: dict[str, Any],
    index: int,
    work_dir: Path,
    apply: bool,
    force: bool,
) -> dict[str, Any]:
    url = document["document_url"]
    document_work_dir = work_dir / _safe_path_part(document.get("mid") or "unknown") / _safe_path_part(
        document.get("document_srl") or str(index)
    )
    row: dict[str, Any] = {
        "index": index,
        "url": url,
        "document_srl": document.get("document_srl"),
        "mid": document.get("mid"),
        "exam_name": document.get("exam_name"),
        "title": document.get("title"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        downloaded = download_selected_attachment(
            client=client,
            url=url,
            work_dir=document_work_dir,
            role="teacher",
            extension="pdf",
        )
    except SystemExit as exc:
        row.update({"status": "no_attachment", "error": str(exc)})
        return row
    except Exception as exc:
        row.update(_error_payload("download_failed", exc))
        return row

    try:
        parsed_exam = parse_downloaded_attachment(downloaded, document_work_dir)
        parsed_path = document_work_dir / "parsed_exam.json"
        quality_report_path = document_work_dir / "quality_report.json"
        write_json(parsed_path, parsed_exam_to_jsonable(parsed_exam))
        source = source_from_downloaded_attachment(downloaded)
        result = import_service.import_exam(
            parsed_exam=parsed_exam,
            source=source,
            force=force,
            quality_report_path=quality_report_path,
            apply=apply,
        )
        row.update(
            {
                "status": result.status,
                "importable": result.importable,
                "saved": result.saved,
                "skipped": result.skipped,
                "source_id": result.source_id,
                "source_existing": result.source_existing,
                "questions": len(parsed_exam.questions),
                "groups": len(parsed_exam.groups),
                "selected_attachment": downloaded.selected_attachment.filename,
                "hash": downloaded.content_hash,
                "parsed": str(parsed_path),
                "quality_report": result.quality_report_path,
                "errors": result.errors,
                "warnings": result.warnings,
            }
        )
        return row
    except Exception as exc:
        row.update(_error_payload("import_failed", exc))
        row.update(
            {
                "selected_attachment": downloaded.selected_attachment.filename,
                "hash": downloaded.content_hash,
            }
        )
        return row


def _load_processed_urls(log_path: Path, retry_failures: bool) -> set[str]:
    if not log_path.exists():
        return set()
    processed = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = row.get("status")
        url = row.get("url")
        if not url:
            continue
        if status in FINAL_STATUSES or (not retry_failures and status):
            processed.add(url)
    return processed


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _append_progress(path: Path, row: dict[str, Any]) -> None:
    event = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **row,
    }
    _append_jsonl(path, event)


def _increment(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value))[:80]


def _error_payload(status: str, exc: Exception) -> dict[str, Any]:
    return {
        "status": status,
        "error": str(exc),
        "traceback": traceback.format_exc(limit=8),
    }


if __name__ == "__main__":
    raise SystemExit(main())
