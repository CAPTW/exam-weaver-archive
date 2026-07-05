"""Low-speed crawler and parser for public comcbt.com exam posts."""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib import parse, robotparser
from urllib.request import Request, urlopen

from src.web_import.comcbt_pdf import (
    CHOICE_RE,
    CHOICE_SYMBOLS,
    FILLED_CIRCLED,
    OPEN_CIRCLED,
    OPEN_SYMBOL_BY_NUMBER,
    QUESTION_START_RE,
    RANGE_RE,
    SUBJECT_LINE_RE,
    TAIL_MARKERS,
    ComcbtParseError,
    ComcbtPdfParser,
    PdfImageBox,
    PdfTextLine,
    dedupe_choices,
    exam_type_from_title,
    extract_document_layout,
    extract_page_layout,
    extract_page_lines,
    infer_year_from_text,
    locate_question_spans,
    needs_visual_context,
    normalize_pdf_lines,
    parse_answer_key,
    parse_question_block,
    split_parse_events,
    split_question_blocks,
    subject_from_title,
)
from src.web_import.models import (
    ComcbtAttachment,
    ComcbtDocument,
    ComcbtExamBoard,
    ComcbtParsedExam,
    ComcbtParseResult,
    ComcbtQuestionGroup,
)


COMCBT_BASE_URL = "https://www.comcbt.com"
COMCBT_CANONICAL_SCHEME = "https"
COMCBT_CANONICAL_HOST = "www.comcbt.com"
DEFAULT_USER_AGENT = "ExamGeneratorBot/0.1 (+local educational import tool)"
BLOCKED_CRAWL_PATTERNS = (
    "search_target=",
    "order_type=",
    "sort_index=",
    "act=dispMemberFindAccount",
    "listStyle=",
    "selected_date=",
    "entry=",
    "?l=",
    "&l=",
    "?m=",
    "&m=",
)


def canonical_document_url(url: str) -> str:
    parsed = parse.urlparse(url)
    if parsed.scheme != COMCBT_CANONICAL_SCHEME:
        raise ValueError(f"Expected canonical COMCBT document URL: {url}")
    if parsed.netloc.lower() != COMCBT_CANONICAL_HOST:
        raise ValueError(f"Expected canonical COMCBT document URL: {url}")
    if parsed.query or parsed.fragment:
        raise ValueError(f"Expected canonical COMCBT document URL without query or fragment: {url}")
    path = parsed.path.rstrip("/")
    match = re.fullmatch(r"/xe/([A-Za-z0-9_]+)/(\d+)", path)
    if not match:
        raise ValueError(f"Expected canonical COMCBT document URL /xe/{{mid}}/{{document_srl}}: {url}")
    return f"{COMCBT_BASE_URL}/xe/{match.group(1)}/{match.group(2)}"


def is_allowed_crawl_url(url: str) -> bool:
    parsed = parse.urlparse(url)
    if parsed.scheme != COMCBT_CANONICAL_SCHEME:
        return False
    if parsed.netloc.lower() != COMCBT_CANONICAL_HOST:
        return False
    return not any(pattern in url for pattern in BLOCKED_CRAWL_PATTERNS)


def assert_allowed_crawl_url(url: str) -> None:
    if not is_allowed_crawl_url(url):
        raise ValueError(f"Blocked COMCBT crawl URL pattern: {url}")


class SlowHttpClient:
    """Small stdlib-only HTTP client with robots.txt and request pacing."""

    def __init__(
        self,
        delay_seconds: float = 2.0,
        user_agent: str = DEFAULT_USER_AGENT,
        cache_dir: Optional[Path | str] = None,
        base_url: str = COMCBT_BASE_URL,
    ):
        self.delay_seconds = max(0.0, float(delay_seconds))
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.base_url = base_url.rstrip("/")
        self._last_request_at = 0.0
        self._robots = robotparser.RobotFileParser()
        self._robots.set_url(f"{self.base_url}/robots.txt")
        self._robots_loaded = False

    def fetch_text(self, url: str) -> str:
        data, _ = self.fetch_bytes(url)
        return data.decode("utf-8", "replace")

    def fetch_bytes(self, url: str) -> tuple[bytes, str]:
        absolute_url = parse.urljoin(self.base_url + "/", url)
        self._assert_allowed(absolute_url)
        cached = self._read_cache(absolute_url)
        if cached is not None:
            return cached, absolute_url

        self._wait()
        request = Request(absolute_url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=30) as response:
            data = response.read()
        self._write_cache(absolute_url, data)
        return data, absolute_url

    def download(self, url: str, destination: Path | str) -> Path:
        data, absolute_url = self.fetch_bytes(url)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def _assert_allowed(self, url: str) -> None:
        assert_allowed_crawl_url(url)
        self._ensure_robots_loaded()
        if self._robots is not None and not self._robots.can_fetch(self.user_agent, url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

    def _ensure_robots_loaded(self) -> None:
        if self._robots_loaded:
            return
        self._robots_loaded = True
        try:
            self._robots.read()
        except Exception:
            self._robots = None

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _cache_path(self, url: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.bin"

    def _read_cache(self, url: str) -> Optional[bytes]:
        path = self._cache_path(url)
        if path and path.exists():
            return path.read_bytes()
        return None

    def _write_cache(self, url: str, data: bytes) -> None:
        path = self._cache_path(url)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href")
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = normalize_space("".join(self._text_parts))
            self.links.append((self._href, text))
            self._href = None
            self._text_parts = []


class _MetadataExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title: Optional[str] = None
        self.og_title: Optional[str] = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        lower = tag.lower()
        if lower == "title":
            self._in_title = True
            self._title_parts = []
            return
        if lower != "meta":
            return
        attributes = {name.lower(): value for name, value in attrs}
        if attributes.get("property") == "og:title" and attributes.get("content"):
            self.og_title = normalize_space(attributes["content"] or "")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            self.title = normalize_space("".join(self._title_parts))


def normalize_space(value: str) -> str:
    value = html.unescape(value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def extract_links(html_text: str) -> list[tuple[str, str]]:
    parser = _LinkExtractor()
    parser.feed(html_text)
    return parser.links


def extract_title(html_text: str) -> str:
    parser = _MetadataExtractor()
    parser.feed(html_text)
    return parser.og_title or parser.title or ""


def discover_exam_boards(index_html: str, base_url: str = COMCBT_BASE_URL) -> list[ComcbtExamBoard]:
    """Return exam-board links from the CBT index page."""
    boards: dict[str, ComcbtExamBoard] = {}
    for href, text in extract_links(index_html):
        if not text or len(text) < 2:
            continue
        absolute_url = parse.urljoin(base_url, href)
        if not is_allowed_crawl_url(absolute_url):
            continue
        parsed = parse.urlparse(absolute_url)
        match = re.fullmatch(r"/xe/([A-Za-z0-9_]+)", parsed.path.rstrip("/"))
        if not match or parsed.query:
            continue
        mid = match.group(1)
        if mid in boards:
            continue
        if text in {"[다운로드]", "m.comcbt.com", "기출문제 안내"}:
            continue
        boards[mid] = ComcbtExamBoard(name=text, url=absolute_url, mid=mid)
    return list(boards.values())


def parse_board_documents(board_html: str, board_url: str) -> list[ComcbtDocument]:
    """Return document links from one XE board page."""
    board_mid = parse.urlparse(board_url).path.rstrip("/").split("/")[-1]
    documents: dict[str, ComcbtDocument] = {}
    for href, text in extract_links(board_html):
        if not text:
            continue
        absolute_url = parse.urljoin(board_url, href)
        if not is_allowed_crawl_url(absolute_url):
            continue
        parsed = parse.urlparse(absolute_url)
        match = re.fullmatch(rf"/xe/{re.escape(board_mid)}/(\d+)", parsed.path.rstrip("/"))
        if not match or parsed.query:
            continue
        if "기출문제" not in text and "CBT" not in text:
            continue
        document_srl = match.group(1)
        if document_srl in documents:
            continue
        documents[document_srl] = document_from_title(text, absolute_url, board_mid, document_srl)
    return list(documents.values())


def parse_document_page(document_html: str, document_url: str) -> tuple[ComcbtDocument, list[ComcbtAttachment]]:
    title = extract_title(document_html)
    canonical_url = canonical_document_url(document_url)
    parsed = parse.urlparse(canonical_url)
    parts = [part for part in parsed.path.split("/") if part]
    mid = parts[1] if len(parts) >= 3 and parts[0] == "xe" else ""
    document_srl = parts[2] if len(parts) >= 3 and parts[0] == "xe" else ""
    document = document_from_title(title, canonical_url, mid, document_srl)
    attachments = parse_attachments(document_html, canonical_url)
    return document, attachments


def is_file_download_url(url: str) -> bool:
    parsed = parse.urlparse(url)
    query = parse.parse_qs(parsed.query, keep_blank_values=True)
    return "procFileDownload" in query.get("act", [])


def parse_attachments(document_html: str, document_url: str) -> list[ComcbtAttachment]:
    attachments: dict[str, ComcbtAttachment] = {}
    for href, text in extract_links(document_html):
        absolute_url = parse.urljoin(document_url, href)
        decoded_url = html.unescape(absolute_url)
        if not is_allowed_crawl_url(decoded_url):
            continue
        if not is_file_download_url(decoded_url):
            continue
        filename = normalize_space(text)
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in {"pdf", "hwp", "hwpx", "zip"}:
            continue
        role = "unknown"
        if "교사용" in filename:
            role = "teacher"
        elif "학생용" in filename:
            role = "student"
        key = f"{role}:{filename}:{decoded_url}"
        attachments[key] = ComcbtAttachment(
            filename=filename,
            url=decoded_url,
            role=role,
            extension=extension,
        )
    return list(attachments.values())


def select_attachment(
    attachments: Iterable[ComcbtAttachment],
    role: str = "teacher",
    extension: str = "pdf",
) -> Optional[ComcbtAttachment]:
    preferred = [
        attachment for attachment in attachments
        if attachment.role == role and attachment.extension == extension
    ]
    if preferred:
        return preferred[0]
    fallback = [attachment for attachment in attachments if attachment.extension == extension]
    return fallback[0] if fallback else None


def document_from_title(
    title: str,
    url: str,
    mid: str,
    document_srl: str,
) -> ComcbtDocument:
    title = normalize_space(title)
    match = re.search(
        r"(?P<year>\d{4})년\s*(?P<month>\d{1,2})월\s*(?P<day>\d{1,2})일"
        r"(?:\((?P<session>\d+)회\))?",
        title,
    )
    year = month = day = session = None
    if match:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
        session = int(match.group("session") or 1)
    return ComcbtDocument(
        title=title,
        url=url,
        mid=mid,
        document_srl=document_srl,
        year=year,
        month=month,
        day=day,
        session=session,
    )


def parsed_exam_to_jsonable(parsed_exam: ComcbtParsedExam) -> dict:
    return {
        **parsed_exam.to_summary(),
        "questions": [
            {
                "number": question.number,
                "text": question.text,
                "correct_answer": question.correct_answer,
                "has_image": question.has_image,
                "image_path": question.image_path,
                "subject_name": question.subject_name,
                "group_id": question.group_id,
                "group_order": question.group_order,
                "shared_passage": question.shared_passage,
                "choices": [
                    {
                        "number": choice.number,
                        "symbol": choice.symbol,
                        "text": choice.text,
                        "image_path": choice.image_path,
                    }
                    for choice in question.choices
                ],
            }
            for question in parsed_exam.questions
        ],
    }


def write_json(path: Path | str, payload: dict | list) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path
