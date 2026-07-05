"""Board and document inventory helpers for public comcbt.com pages."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable, Optional
from urllib import parse

from src.web_import.comcbt import (
    COMCBT_BASE_URL,
    SlowHttpClient,
    assert_allowed_crawl_url,
    document_from_title,
    extract_links,
    is_allowed_crawl_url,
    normalize_space,
)


COMCBT_INDEX_URL = f"{COMCBT_BASE_URL}/cbt/index2.php?hack_number=29"
PROVIDER = "comcbt"
DEFAULT_MAX_PAGES = 3

@dataclass(frozen=True)
class ComcbtBoardEntry:
    provider: str
    exam_name: str
    mid: str
    board_url: str


@dataclass(frozen=True)
class ComcbtDocumentEntry:
    provider: str
    exam_name: str
    mid: str
    board_url: str
    document_srl: str
    document_url: str
    title: str
    year: Optional[int]
    session: Optional[int]
    status: str = "discovered"


@dataclass
class CrawlStats:
    requested_urls: list[str]
    new_docs: int = 0
    duplicate_docs: int = 0
    failures: list[dict[str, str]] | None = None

    def __post_init__(self) -> None:
        if self.failures is None:
            self.failures = []

    def to_dict(self) -> dict:
        return {
            "requested_urls": self.requested_urls,
            "new_docs": self.new_docs,
            "duplicate_docs": self.duplicate_docs,
            "failures": self.failures or [],
        }


def board_entries_from_index_html(
    index_html: str,
    base_url: str = COMCBT_BASE_URL,
) -> list[ComcbtBoardEntry]:
    boards: dict[str, ComcbtBoardEntry] = {}
    for href, text in extract_links(index_html):
        exam_name = normalize_space(text)
        if not exam_name or len(exam_name) < 2:
            continue
        board_url = parse.urljoin(base_url, href)
        if not is_allowed_crawl_url(board_url):
            continue
        parsed = parse.urlparse(board_url)
        match = re.fullmatch(r"/xe/([A-Za-z0-9_]+)", parsed.path.rstrip("/"))
        if not match or parsed.query:
            continue
        if exam_name in {"[다운로드]", "m.comcbt.com", "기출문제 안내"}:
            continue
        mid = match.group(1)
        boards.setdefault(
            mid,
            ComcbtBoardEntry(
                provider=PROVIDER,
                exam_name=exam_name,
                mid=mid,
                board_url=parse.urlunparse(parsed._replace(query="", fragment="")),
            ),
        )
    return list(boards.values())


def document_entries_from_board_html(
    board_html: str,
    board: ComcbtBoardEntry,
) -> list[ComcbtDocumentEntry]:
    documents: dict[str, ComcbtDocumentEntry] = {}
    for href, text in extract_links(board_html):
        title = normalize_space(text)
        if "기출문제" not in title and "CBT" not in title:
            continue
        document_url = parse.urljoin(board.board_url + "/", href)
        if not is_allowed_crawl_url(document_url):
            continue
        parsed = parse.urlparse(document_url)
        match = re.fullmatch(rf"/xe/{re.escape(board.mid)}/(\d+)", parsed.path.rstrip("/"))
        if not match or parsed.query:
            continue
        document_srl = match.group(1)
        if document_srl in documents:
            continue
        document = document_from_title(
            title=title,
            url=parse.urlunparse(parsed._replace(query="", fragment="")),
            mid=board.mid,
            document_srl=document_srl,
        )
        documents[document_srl] = document_entry_from_document(document, board)
    return list(documents.values())


def document_entry_from_document(
    document: ComcbtDocument,
    board: ComcbtBoardEntry,
) -> ComcbtDocumentEntry:
    return ComcbtDocumentEntry(
        provider=PROVIDER,
        exam_name=board.exam_name,
        mid=board.mid,
        board_url=board.board_url,
        document_srl=document.document_srl,
        document_url=document.url,
        title=document.title,
        year=document.year,
        session=document.session,
        status="discovered",
    )


def discover_board_entries(
    client: SlowHttpClient,
    index_url: str = COMCBT_INDEX_URL,
    max_boards: Optional[int] = None,
) -> list[ComcbtBoardEntry]:
    assert_allowed_crawl_url(index_url)
    html = client.fetch_text(index_url)
    boards = board_entries_from_index_html(html)
    return boards[:max_boards] if max_boards is not None else boards


def discover_document_entries(
    client: SlowHttpClient,
    board: ComcbtBoardEntry,
    max_pages: int = 1,
    max_docs: Optional[int] = None,
) -> tuple[list[ComcbtDocumentEntry], CrawlStats]:
    stats = CrawlStats(requested_urls=[])
    documents: dict[str, ComcbtDocumentEntry] = {}
    page_urls = [board.board_url]
    queued = {board.board_url}
    page_index = 0

    while page_index < len(page_urls) and len(stats.requested_urls) < max_pages:
        page_url = page_urls[page_index]
        page_index += 1
        try:
            assert_allowed_crawl_url(page_url)
            stats.requested_urls.append(page_url)
            html = client.fetch_text(page_url)
        except Exception as exc:
            stats.failures.append({"url": page_url, "error": str(exc)})
            continue

        before = len(documents)
        for document in document_entries_from_board_html(html, board):
            if document.document_srl in documents:
                stats.duplicate_docs += 1
                continue
            documents[document.document_srl] = document
            stats.new_docs += 1
            if max_docs is not None and len(documents) >= max_docs:
                return list(documents.values()), stats

        if len(documents) == before and page_url != board.board_url:
            break

        for next_url in allowed_pagination_urls(html, board):
            if len(page_urls) >= max_pages:
                break
            if next_url not in queued:
                queued.add(next_url)
                page_urls.append(next_url)

    return list(documents.values()), stats


def allowed_pagination_urls(board_html: str, board: ComcbtBoardEntry) -> list[str]:
    pages: dict[int, str] = {}
    for href, _ in extract_links(board_html):
        url = parse.urljoin(board.board_url + "/", href)
        if not is_allowed_crawl_url(url):
            continue
        parsed = parse.urlparse(url)
        match = re.fullmatch(rf"/xe/{re.escape(board.mid)}/page/(\d+)", parsed.path.rstrip("/"))
        if not match or parsed.query:
            continue
        page_number = int(match.group(1))
        if page_number >= 1:
            pages[page_number] = parse.urlunparse(parsed._replace(query="", fragment=""))
    return [pages[number] for number in sorted(pages)]


def crawl_document_inventory(
    client: SlowHttpClient,
    index_url: str = COMCBT_INDEX_URL,
    max_boards: Optional[int] = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_docs: Optional[int] = None,
) -> dict:
    boards = discover_board_entries(client, index_url=index_url, max_boards=max_boards)
    manifest: list[ComcbtDocumentEntry] = []
    board_stats: dict[str, dict] = {}
    remaining_docs = max_docs

    for board in boards:
        if remaining_docs is not None and remaining_docs <= 0:
            break
        docs, stats = discover_document_entries(
            client=client,
            board=board,
            max_pages=max_pages,
            max_docs=remaining_docs,
        )
        manifest.extend(docs)
        board_stats[board.mid] = stats.to_dict()
        if remaining_docs is not None:
            remaining_docs -= len(docs)

    return {
        "provider": PROVIDER,
        "boards": [asdict(board) for board in boards],
        "documents": [asdict(document) for document in manifest],
        "stats": board_stats,
    }


def entries_to_jsonable(entries: Iterable[object]) -> list[dict]:
    return [asdict(entry) for entry in entries]
