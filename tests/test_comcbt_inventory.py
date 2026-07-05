import json

import pytest

from scripts import comcbt_crawl
from src.web_import.comcbt_inventory import (
    ComcbtBoardEntry,
    allowed_pagination_urls,
    board_entries_from_index_html,
    crawl_document_inventory,
    document_entries_from_board_html,
    is_allowed_crawl_url,
)


INDEX_HTML = """
<a href="/xe/wc">9급 국가직 공무원 건축계획</a>
<a href="/xe/wc">9급 국가직 공무원 건축계획 중복</a>
<a href="/xe/ab">전기기사</a>
<a href="/xe/wc?search_target=title">검색 링크</a>
<a href="/xe/member?act=dispMemberFindAccount">계정 찾기</a>
"""

BOARD_HTML = """
<a href="/xe/wc/8837719">9급 국가직 공무원 건축계획 필기 기출문제 및 CBT 2025년 04월 05일(1회)</a>
<a href="/xe/wc/7786247">9급 국가직 공무원 건축계획 필기 기출문제 및 CBT 2024년 03월 23일(1회)</a>
<a href="/xe/wc/555?sort_index=readed_count">차단된 기출문제 CBT 2023년 01월 01일(1회)</a>
<a href="/xe/wc/page/2">2</a>
<a href="/xe/wc?listStyle=webzine">목록형</a>
"""

BOARD_PAGE_2_HTML = """
<a href="/xe/wc/7000000">9급 국가직 공무원 건축계획 필기 기출문제 및 CBT 2023년 04월 08일(1회)</a>
<a href="/xe/wc/page/3">3</a>
"""


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []
        self.downloaded = []

    def fetch_text(self, url):
        self.requested.append(url)
        return self.pages[url]

    def download(self, url, destination):
        self.downloaded.append((url, destination))
        raise AssertionError("inventory crawl must not download files")


def test_guardrail_blocks_robots_disallowed_query_patterns():
    blocked = [
        "https://www.comcbt.com/xe/wc?search_target=title",
        "https://www.comcbt.com/xe/wc?order_type=desc",
        "https://www.comcbt.com/xe/wc?sort_index=title",
        "https://www.comcbt.com/xe/member?act=dispMemberFindAccount",
        "https://www.comcbt.com/xe/wc?listStyle=list",
        "https://www.comcbt.com/xe/wc?selected_date=2026-06-29",
        "https://www.comcbt.com/xe/wc?entry=comment",
        "https://www.comcbt.com/xe/wc?l=ko",
        "https://www.comcbt.com/xe/wc?page=1&l=ko",
        "https://www.comcbt.com/xe/wc?m=1",
        "https://www.comcbt.com/xe/wc?page=1&m=1",
    ]

    assert all(not is_allowed_crawl_url(url) for url in blocked)
    assert is_allowed_crawl_url("https://www.comcbt.com/xe/wc/page/2")


def test_guardrail_requires_canonical_comcbt_https_host():
    blocked = [
        "http://www.comcbt.com/xe/wc",
        "https://evil.example/xe/wc",
        "https://m.comcbt.com/xe/wc",
        "ftp://www.comcbt.com/xe/wc",
    ]

    assert all(not is_allowed_crawl_url(url) for url in blocked)
    assert is_allowed_crawl_url("https://www.comcbt.com/xe/wc")


def test_board_entries_from_index_html_dedupes_by_mid_and_skips_blocked_links():
    html = INDEX_HTML + """
    <a href="//evil.example/xe/evil">오프사이트</a>
    <a href="http://www.comcbt.com/xe/http">HTTP 링크</a>
    """

    boards = board_entries_from_index_html(html)

    assert [board.mid for board in boards] == ["wc", "ab"]
    assert boards[0].provider == "comcbt"
    assert boards[0].exam_name == "9급 국가직 공무원 건축계획"
    assert boards[0].board_url == "https://www.comcbt.com/xe/wc"


def test_document_entries_from_board_html_include_manifest_fields_and_skip_blocked_links():
    board = ComcbtBoardEntry(
        provider="comcbt",
        exam_name="9급 국가직 공무원 건축계획",
        mid="wc",
        board_url="https://www.comcbt.com/xe/wc",
    )

    html = BOARD_HTML + """
    <a href="//evil.example/xe/wc/9999999">오프사이트 기출문제 CBT 2022년 01월 01일(1회)</a>
    <a href="http://www.comcbt.com/xe/wc/8888888">HTTP 기출문제 CBT 2022년 01월 01일(1회)</a>
    """

    documents = document_entries_from_board_html(html, board)

    assert [document.document_srl for document in documents] == ["8837719", "7786247"]
    assert documents[0].provider == "comcbt"
    assert documents[0].exam_name == "9급 국가직 공무원 건축계획"
    assert documents[0].document_url == "https://www.comcbt.com/xe/wc/8837719"
    assert documents[0].year == 2025
    assert documents[0].session == 1
    assert documents[0].status == "discovered"


def test_allowed_pagination_urls_only_accepts_canonical_page_paths():
    board = ComcbtBoardEntry("comcbt", "exam", "wc", "https://www.comcbt.com/xe/wc")
    html = """
    <a href="/xe/wc/page/3">3</a>
    <a href="/xe/wc/page/2">2</a>
    <a href="/xe/wc?page=2">blocked query page</a>
    <a href="/xe/wc/page/4?listStyle=list">blocked query page 4</a>
    <a href="//evil.example/xe/wc/page/5">off-site page 5</a>
    <a href="http://www.comcbt.com/xe/wc/page/6">HTTP page 6</a>
    """

    assert allowed_pagination_urls(html, board) == [
        "https://www.comcbt.com/xe/wc/page/2",
        "https://www.comcbt.com/xe/wc/page/3",
    ]


def test_board_entry_from_url_requires_exact_canonical_board_url():
    board = comcbt_crawl.board_entry_from_url("https://www.comcbt.com/xe/wc")

    assert board.mid == "wc"

    for url in [
        "https://evil.example/xe/wc",
        "http://www.comcbt.com/xe/wc",
        "https://www.comcbt.com/xe/wc/page/2",
        "https://www.comcbt.com/xe/wc?search_target=title",
    ]:
        with pytest.raises(ValueError):
            comcbt_crawl.board_entry_from_url(url)


def test_crawl_document_inventory_caps_boards_pages_docs_and_never_downloads():
    client = FakeClient({
        "https://www.comcbt.com/cbt/index2.php?hack_number=29": INDEX_HTML,
        "https://www.comcbt.com/xe/wc": BOARD_HTML,
        "https://www.comcbt.com/xe/wc/page/2": BOARD_PAGE_2_HTML,
    })

    payload = crawl_document_inventory(
        client=client,
        max_boards=1,
        max_pages=2,
        max_docs=3,
    )

    assert [board["mid"] for board in payload["boards"]] == ["wc"]
    assert [document["document_srl"] for document in payload["documents"]] == [
        "8837719",
        "7786247",
        "7000000",
    ]
    assert client.requested == [
        "https://www.comcbt.com/cbt/index2.php?hack_number=29",
        "https://www.comcbt.com/xe/wc",
        "https://www.comcbt.com/xe/wc/page/2",
    ]
    assert client.downloaded == []


def test_inventory_and_board_commands_write_manifest_rows(monkeypatch, tmp_path):
    class CliFakeClient:
        def __init__(self, delay_seconds, cache_dir):
            self.delay_seconds = delay_seconds
            self.cache_dir = cache_dir

        def fetch_text(self, url):
            if url.endswith("index2.php?hack_number=29"):
                return INDEX_HTML
            if url == "https://www.comcbt.com/xe/wc":
                return BOARD_HTML
            raise AssertionError(url)

    monkeypatch.setattr(comcbt_crawl, "SlowHttpClient", CliFakeClient)
    boards_output = tmp_path / "boards.json"
    docs_output = tmp_path / "docs.json"

    assert comcbt_crawl.main(["inventory", "--max-boards", "1", "--output", str(boards_output)]) == 0
    assert comcbt_crawl.main([
        "board",
        "--board-url",
        "https://www.comcbt.com/xe/wc",
        "--exam-name",
        "9급 국가직 공무원 건축계획",
        "--output",
        str(docs_output),
    ]) == 0

    boards = json.loads(boards_output.read_text(encoding="utf-8"))
    docs = json.loads(docs_output.read_text(encoding="utf-8"))
    assert boards[0]["mid"] == "wc"
    assert docs[0]["document_srl"] == "8837719"
    assert set(docs[0]) == {
        "provider",
        "exam_name",
        "mid",
        "board_url",
        "document_srl",
        "document_url",
        "title",
        "year",
        "session",
        "status",
    }
