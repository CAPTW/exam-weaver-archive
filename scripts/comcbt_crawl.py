"""Inventory, parse, and optionally import public comcbt.com exam posts."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib import parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.web_import.comcbt import (
    COMCBT_BASE_URL,
    ComcbtAttachment,
    ComcbtDocument,
    ComcbtPdfParser,
    SlowHttpClient,
    canonical_document_url,
    parse_document_page,
    parsed_exam_to_jsonable,
    select_attachment,
    write_json,
)
from src.web_import.comcbt_inventory import (
    COMCBT_INDEX_URL,
    DEFAULT_MAX_PAGES,
    ComcbtBoardEntry,
    assert_allowed_crawl_url,
    crawl_document_inventory,
    discover_board_entries,
    discover_document_entries,
    entries_to_jsonable,
)
from src.web_import.importer import ComcbtImportService, QuestionSource, sha256_file, utc_timestamp


PROVIDER = "comcbt"


@dataclass(frozen=True)
class DownloadedAttachment:
    document: ComcbtDocument
    attachments: list[ComcbtAttachment]
    selected_attachment: ComcbtAttachment
    path: Path
    content_hash: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between uncached requests.")
    parser.add_argument("--cache-dir", default="tmp/comcbt_cache", help="HTTP response cache directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="List exam boards from the CBT index.")
    inventory.add_argument("--index-url", default=COMCBT_INDEX_URL)
    inventory.add_argument("--max-boards", type=int)
    inventory.add_argument("--output", default="tmp/comcbt_boards.json")

    board = subparsers.add_parser("board", help="List exam documents from one board.")
    board.add_argument("--board-url", required=True)
    board.add_argument("--exam-name", help="Exam name to include in document manifest rows.")
    board.add_argument("--max-docs", type=int)
    board.add_argument("--max-pages", type=int, default=1)
    board.add_argument("--output", default="tmp/comcbt_documents.json")

    crawl_docs = subparsers.add_parser("crawl-docs", help="Build a document manifest from multiple boards.")
    crawl_docs.add_argument("--index-url", default=COMCBT_INDEX_URL)
    crawl_docs.add_argument("--max-boards", type=int)
    crawl_docs.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    crawl_docs.add_argument("--max-docs", type=int)
    crawl_docs.add_argument("--dry-run", action="store_true")
    crawl_docs.add_argument("--output", default="tmp/comcbt_manifest.json")

    parse_doc = subparsers.add_parser("parse-doc", help="Download and parse one document's teacher PDF.")
    parse_doc.add_argument("--url", required=True, help="Document URL, e.g. https://www.comcbt.com/xe/wc/8837719")
    parse_doc.add_argument("--work-dir", default="tmp/comcbt_parse")
    parse_doc.add_argument("--output", default="tmp/comcbt_parsed_exam.json")
    parse_doc.add_argument("--role", default="teacher", choices=["teacher", "student", "unknown"])
    parse_doc.add_argument("--extension", default="pdf", choices=["pdf"])

    import_doc = subparsers.add_parser("import-doc", help="Parse one document and save to the local DB.")
    import_doc.add_argument("--url", required=True)
    import_doc.add_argument("--db", default="data/exam_bank.db")
    import_doc.add_argument("--work-dir", default="tmp/comcbt_import")
    import_doc.add_argument("--apply", action="store_true", help="Write to DB. Omit for dry-run.")
    import_doc.add_argument("--force", action="store_true", help="Import even when the source hash already exists.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = SlowHttpClient(delay_seconds=args.delay, cache_dir=args.cache_dir)

    if args.command == "inventory":
        boards = discover_board_entries(client, index_url=args.index_url, max_boards=args.max_boards)
        output = write_json(args.output, entries_to_jsonable(boards))
        print(f"boards={len(boards)} output={output}")
        return 0

    if args.command == "board":
        board = board_entry_from_url(args.board_url, args.exam_name)
        documents, stats = discover_document_entries(
            client=client,
            board=board,
            max_pages=args.max_pages,
            max_docs=args.max_docs,
        )
        output = write_json(args.output, entries_to_jsonable(documents))
        if stats.failures:
            print(f"documents={len(documents)} failures={len(stats.failures)} output={output}")
            return 1
        print(f"documents={len(documents)} output={output}")
        return 0

    if args.command == "crawl-docs":
        payload = crawl_document_inventory(
            client=client,
            index_url=args.index_url,
            max_boards=args.max_boards,
            max_pages=args.max_pages,
            max_docs=args.max_docs,
        )
        output = write_json(args.output, payload)
        print(
            f"dry_run={str(args.dry_run).lower()} "
            f"boards={len(payload['boards'])} documents={len(payload['documents'])} output={output}"
        )
        return 0

    if args.command == "parse-doc":
        parsed_exam = parse_one_document(
            client=client,
            url=args.url,
            work_dir=Path(args.work_dir),
            role=args.role,
            extension=args.extension,
        )
        output = write_json(args.output, parsed_exam_to_jsonable(parsed_exam))
        selected = parsed_exam.selected_attachment.filename if parsed_exam.selected_attachment else ""
        print(f"questions={len(parsed_exam.questions)} selected_attachment={selected} output={output}")
        return 0

    if args.command == "import-doc":
        downloaded = download_selected_attachment(
            client=client,
            url=args.url,
            work_dir=Path(args.work_dir),
            role="teacher",
            extension="pdf",
        )
        source = source_from_downloaded_attachment(downloaded)
        import_service = ComcbtImportService(args.db)

        parsed_exam = parse_downloaded_attachment(downloaded, Path(args.work_dir))
        output = Path(args.work_dir) / "parsed_exam.json"
        quality_report_path = Path(args.work_dir) / "quality_report.json"
        write_json(output, parsed_exam_to_jsonable(parsed_exam))
        if not args.apply:
            result = import_service.import_exam(
                parsed_exam=parsed_exam,
                source=source,
                quality_report_path=quality_report_path,
                apply=False,
            )
            print(
                "dry_run=true "
                f"status={result.status} importable={str(result.importable).lower()} "
                f"saved={result.saved} skipped={str(result.skipped).lower()} "
                f"quality_report={result.quality_report_path} "
                f"questions={len(parsed_exam.questions)} "
                f"selected_attachment={downloaded.selected_attachment.filename} "
                f"hash={downloaded.content_hash} parsed={output}"
            )
            return 0
        result = import_service.import_exam(
            parsed_exam=parsed_exam,
            source=source,
            force=args.force,
            quality_report_path=quality_report_path,
        )
        print(
            "dry_run=false "
            f"status={result.status} importable={str(result.importable).lower()} "
            f"saved={result.saved} skipped={str(result.skipped).lower()} "
            f"source_id={result.source_id} "
            f"source_existing={str(result.source_existing).lower()} "
            f"quality_report={result.quality_report_path} "
            f"selected_attachment={downloaded.selected_attachment.filename} "
            f"hash={downloaded.content_hash} parsed={output}"
        )
        return 0

    raise AssertionError(args.command)


def board_entry_from_url(board_url: str, exam_name: str | None = None) -> ComcbtBoardEntry:
    url = board_url.rstrip("/")
    assert_allowed_crawl_url(url)
    parsed = parse.urlparse(url)
    match = re.fullmatch(r"/xe/([A-Za-z0-9_]+)", parsed.path)
    if not match or parsed.query or parsed.fragment:
        raise ValueError(f"Expected canonical COMCBT board URL /xe/{{mid}}: {board_url}")
    mid = match.group(1)
    return ComcbtBoardEntry(
        provider="comcbt",
        exam_name=exam_name or mid,
        mid=mid,
        board_url=url,
    )


def parse_one_document(
    client: SlowHttpClient,
    url: str,
    work_dir: Path,
    role: str,
    extension: str,
):
    downloaded = download_selected_attachment(
        client=client,
        url=url,
        work_dir=work_dir,
        role=role,
        extension=extension,
    )
    return parse_downloaded_attachment(downloaded, work_dir)


def download_selected_attachment(
    client: SlowHttpClient,
    url: str,
    work_dir: Path,
    role: str,
    extension: str,
) -> DownloadedAttachment:
    url = canonical_document_url(url)
    html = client.fetch_text(url)
    document, attachments = parse_document_page(html, url)
    attachment = select_attachment(attachments, role=role, extension=extension)
    if not attachment:
        raise SystemExit(f"No {role} .{extension} attachment found: {url}")
    downloads_dir = work_dir / "downloads"
    safe_name = attachment.filename.replace("/", "_").replace("\\", "_")
    pdf_path = client.download(attachment.url, downloads_dir / safe_name)
    return DownloadedAttachment(
        document=document,
        attachments=attachments,
        selected_attachment=attachment,
        path=pdf_path,
        content_hash=sha256_file(pdf_path),
    )


def parse_downloaded_attachment(downloaded: DownloadedAttachment, work_dir: Path):
    image_dir = work_dir / "images"
    return ComcbtPdfParser().parse_pdf(
        pdf_path=downloaded.path,
        document=downloaded.document,
        attachments=downloaded.attachments,
        selected_attachment=downloaded.selected_attachment,
        image_dir=image_dir,
    )


def source_from_downloaded_attachment(downloaded: DownloadedAttachment) -> QuestionSource:
    return QuestionSource(
        provider=PROVIDER,
        source_url=downloaded.document.url,
        document_id=downloaded.document.document_srl or None,
        attachment_url=downloaded.selected_attachment.url,
        attachment_filename=downloaded.selected_attachment.filename,
        content_hash=downloaded.content_hash,
        fetched_at=utc_timestamp(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
