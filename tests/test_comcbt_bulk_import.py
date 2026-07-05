import json
from types import SimpleNamespace

from scripts import comcbt_bulk_import
from src.web_import.comcbt_inventory import ComcbtBoardEntry, ComcbtDocumentEntry


def _manifest(*urls):
    return {
        "provider": "comcbt",
        "boards": [],
        "documents": [
            {
                "provider": "comcbt",
                "exam_name": "sample exam",
                "mid": "wc",
                "board_url": "https://www.comcbt.com/xe/wc",
                "document_srl": str(index + 1),
                "document_url": url,
                "title": f"title {index + 1}",
                "year": 2025,
                "session": 1,
                "status": "discovered",
            }
            for index, url in enumerate(urls)
        ],
    }


def _patch_bulk_dependencies(monkeypatch, calls):
    class FakeClient:
        def __init__(self, delay_seconds, cache_dir):
            self.delay_seconds = delay_seconds
            self.cache_dir = cache_dir

    class FakeImportService:
        def __init__(self, db_path):
            self.db_path = db_path

        def import_exam(self, **kwargs):
            calls["imports"].append(kwargs)
            return SimpleNamespace(
                status="imported",
                importable=True,
                saved=1,
                skipped=False,
                source_id=7,
                source_existing=False,
                quality_report_path=str(kwargs["quality_report_path"]),
                errors=[],
                warnings=[],
            )

    def fake_download(client, url, work_dir, role, extension):
        calls["downloads"].append((url, str(work_dir), role, extension))
        return SimpleNamespace(
            document=SimpleNamespace(url=url, document_srl=url.rsplit("/", 1)[-1]),
            selected_attachment=SimpleNamespace(
                url=f"{url}/download",
                filename="teacher.pdf",
            ),
            attachments=[],
            path=work_dir / "teacher.pdf",
            content_hash=f"hash-{url.rsplit('/', 1)[-1]}",
        )

    monkeypatch.setattr(comcbt_bulk_import, "SlowHttpClient", FakeClient)
    monkeypatch.setattr(comcbt_bulk_import, "ComcbtImportService", FakeImportService)
    monkeypatch.setattr(comcbt_bulk_import, "download_selected_attachment", fake_download)
    monkeypatch.setattr(
        comcbt_bulk_import,
        "parse_downloaded_attachment",
        lambda downloaded, work_dir: SimpleNamespace(questions=[object()], groups=[]),
    )
    monkeypatch.setattr(
        comcbt_bulk_import,
        "source_from_downloaded_attachment",
        lambda downloaded: SimpleNamespace(source_url=downloaded.document.url),
    )
    monkeypatch.setattr(
        comcbt_bulk_import,
        "parsed_exam_to_jsonable",
        lambda parsed_exam: {"questions": len(parsed_exam.questions)},
    )


def test_bulk_import_crawls_manifest_and_writes_jsonl_log(monkeypatch, tmp_path):
    calls = {"downloads": [], "imports": []}
    _patch_bulk_dependencies(monkeypatch, calls)
    manifest = _manifest("https://www.comcbt.com/xe/wc/1")
    monkeypatch.setattr(comcbt_bulk_import, "crawl_document_inventory", lambda **_kwargs: manifest)

    manifest_path = tmp_path / "manifest.json"
    work_dir = tmp_path / "work"
    exit_code = comcbt_bulk_import.main([
        "--crawl",
        "--no-stream",
        "--apply",
        "--manifest",
        str(manifest_path),
        "--work-dir",
        str(work_dir),
        "--db",
        str(tmp_path / "exam.db"),
    ])

    assert exit_code == 0
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["documents"][0]["document_srl"] == "1"
    rows = [
        json.loads(line)
        for line in (work_dir / "bulk_import.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert rows[0]["status"] == "imported"
    assert rows[0]["saved"] == 1
    assert calls["downloads"][0][0] == "https://www.comcbt.com/xe/wc/1"
    assert calls["imports"][0]["apply"] is True


def test_bulk_import_streams_board_pages_and_imports_as_docs_are_discovered(monkeypatch, tmp_path):
    calls = {"downloads": [], "imports": [], "pages": []}
    _patch_bulk_dependencies(monkeypatch, calls)
    board = ComcbtBoardEntry(
        provider="comcbt",
        exam_name="sample exam",
        mid="wc",
        board_url="https://www.comcbt.com/xe/wc",
    )
    docs = {
        "page1": [
            ComcbtDocumentEntry(
                provider="comcbt",
                exam_name="sample exam",
                mid="wc",
                board_url="https://www.comcbt.com/xe/wc",
                document_srl="1",
                document_url="https://www.comcbt.com/xe/wc/1",
                title="first",
                year=2025,
                session=1,
            )
        ],
        "page2": [
            ComcbtDocumentEntry(
                provider="comcbt",
                exam_name="sample exam",
                mid="wc",
                board_url="https://www.comcbt.com/xe/wc",
                document_srl="2",
                document_url="https://www.comcbt.com/xe/wc/2",
                title="second",
                year=2025,
                session=1,
            )
        ],
    }

    class FakeStreamingClient:
        def __init__(self, delay_seconds, cache_dir):
            self.delay_seconds = delay_seconds
            self.cache_dir = cache_dir

        def fetch_text(self, url):
            calls["pages"].append(url)
            return "page2" if url.endswith("/page/2") else "page1"

    monkeypatch.setattr(comcbt_bulk_import, "SlowHttpClient", FakeStreamingClient)
    monkeypatch.setattr(comcbt_bulk_import, "discover_board_entries", lambda *_args, **_kwargs: [board])
    monkeypatch.setattr(
        comcbt_bulk_import,
        "document_entries_from_board_html",
        lambda html, _board: docs[html],
    )
    monkeypatch.setattr(
        comcbt_bulk_import,
        "allowed_pagination_urls",
        lambda html, _board: ["https://www.comcbt.com/xe/wc/page/2"] if html == "page1" else [],
    )

    manifest_path = tmp_path / "manifest.json"
    work_dir = tmp_path / "work"
    exit_code = comcbt_bulk_import.main([
        "--crawl",
        "--apply",
        "--max-pages",
        "2",
        "--manifest",
        str(manifest_path),
        "--work-dir",
        str(work_dir),
        "--db",
        str(tmp_path / "exam.db"),
    ])

    assert exit_code == 0
    assert calls["pages"] == [
        "https://www.comcbt.com/xe/wc",
        "https://www.comcbt.com/xe/wc/page/2",
    ]
    assert [download[0] for download in calls["downloads"]] == [
        "https://www.comcbt.com/xe/wc/1",
        "https://www.comcbt.com/xe/wc/2",
    ]
    progress_events = [
        json.loads(line)["event"]
        for line in (work_dir / "bulk_progress.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "board_start" in progress_events
    assert progress_events.count("page_done") == 2
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["documents"][1]["document_srl"] == "2"


def test_bulk_import_resume_skips_final_status_rows(monkeypatch, tmp_path):
    calls = {"downloads": [], "imports": []}
    _patch_bulk_dependencies(monkeypatch, calls)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _manifest(
                "https://www.comcbt.com/xe/wc/1",
                "https://www.comcbt.com/xe/wc/2",
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "bulk_import.jsonl").write_text(
        json.dumps(
            {"url": "https://www.comcbt.com/xe/wc/1", "status": "imported"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = comcbt_bulk_import.main([
        "--resume",
        "--apply",
        "--manifest",
        str(manifest_path),
        "--work-dir",
        str(work_dir),
        "--db",
        str(tmp_path / "exam.db"),
    ])

    assert exit_code == 0
    assert [download[0] for download in calls["downloads"]] == ["https://www.comcbt.com/xe/wc/2"]
    summary = json.loads((work_dir / "bulk_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["resume_skipped"] == 1
    assert summary["counts"]["imported"] == 1
