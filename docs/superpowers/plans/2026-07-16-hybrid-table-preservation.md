# Hybrid Table Preservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every detected exam table as both a source crop and editable structured data from parsing through database editing and DOCX export.

**Architecture:** Keep the existing database schema and upgrade `question_format_json` / `choice_format_json` in memory to schema version 2. A focused table-format module owns normalization, validation, anchor recovery, and render-mode decisions; the parser, editor, exporter, and portable-data builder consume that shared contract.

**Tech Stack:** Python 3.11, PyMuPDF, PyQt5/qfluentwidgets, python-docx/OpenXML, SQLite, pytest

## Global Constraints

- Existing version 1 payloads containing only `tables[*].rows` remain readable and exportable.
- Every newly detected table stores a source crop or an explicit `source.missing_reason`.
- `auto` renders native only when confidence is at least `0.90` and no complexity flag is true.
- A per-table non-`auto` mode overrides the document-level mode.
- Table asset paths stored in JSON are relative and portable.
- Mounted repository read/write routing remains unchanged; no new SQLite schema migration is introduced.
- Table failures produce warnings and fallbacks; they do not abort the complete DOCX export.
- Do not stage, commit, or push until the user explicitly requests Git publication.

---

### Task 1: Versioned table payload contract

**Files:**
- Create: `src/parser/table_format.py`
- Create: `tests/test_table_format.py`

**Interfaces:**
- Produces: `parse_format_payload(value: object) -> dict`, `serialize_format_payload(payload: dict) -> str | None`, `merge_format_spans(existing: object, spans: list[dict]) -> str | None`, `normalize_table_spec(table: object, index: int = 0) -> dict`, `resolve_table_anchor(text: str, anchor: object) -> tuple[int, bool]`, `effective_table_render_mode(table: dict, document_mode: str = "auto") -> str`, and `validate_table_spec(table: dict, text: str = "", page_size: tuple[float, float] | None = None) -> list[str]`.
- Consumes: JSON strings/dicts already stored in the two format columns.

- [ ] **Step 1: Write failing normalization, anchor, mode, and validation tests**

```python
def test_legacy_rows_are_upgraded_without_data_loss():
    payload = parse_format_payload('{"tables":[{"rows":[["구분","값"],["A","10"]]}]}')
    table = payload["tables"][0]
    assert payload["schema_version"] == 2
    assert table["id"] == "table-1"
    assert table["rows"][1] == ["A", "10"]
    assert table["render_mode"] == "auto"

def test_auto_render_mode_uses_confidence_and_complexity():
    table = normalize_table_spec({"rows": [["A"]], "confidence": {"score": .94}})
    assert effective_table_render_mode(table, "auto") == "native"
    table["complexity"]["has_formula"] = True
    assert effective_table_render_mode(table, "auto") == "image"

def test_context_recovers_stale_anchor():
    offset, recovered = resolve_table_anchor(
        "앞 문장이 늘어남 다음 표를 보고 옳은 것은",
        {"offset": 1, "before_context": "다음 표를 보고", "after_context": "옳은 것은"},
    )
    assert recovered is True
    assert offset == len("앞 문장이 늘어남 다음 표를 보고")
```

- [ ] **Step 2: Run `pytest tests/test_table_format.py -q` and verify import/test failures**

- [ ] **Step 3: Implement strict normalization and preservation**

```python
SCHEMA_VERSION = 2
AUTO_RENDER_THRESHOLD = 0.90
TABLE_RENDER_MODES = {"auto", "image", "native"}

def merge_format_spans(existing, spans):
    payload = parse_format_payload(existing)
    payload["spans"] = list(spans or [])
    if not payload["spans"]:
        payload.pop("spans", None)
    return serialize_format_payload(payload)
```

Implement `normalize_table_spec` so all listed schema fields have validated defaults, cell spans are positive integers, confidence is clamped to `[0, 1]`, and legacy rows remain intact. Implement anchor recovery in this order: valid offset, exact joined before/after context, before-context end, after-context start, end-of-text fallback. Validation returns stable error codes such as `source_image_missing`, `source_hash_mismatch`, `bbox_out_of_page`, `cell_out_of_bounds`, `anchor_unresolved`, and `low_confidence_without_source`.

- [ ] **Step 4: Run `pytest tests/test_table_format.py -q` and verify all tests pass**

---

### Task 2: Native PDF table structure and source crops

**Files:**
- Modify: `src/parser/extractor.py:153-158,430-505,5276-5306`
- Modify: `tests/test_parser_2025.py`
- Create: `tests/fixtures/table_preservation/native_table.pdf` through a deterministic test helper

**Interfaces:**
- Produces: enriched `TableData(rows, bbox, cells, column_widths, row_heights, source, confidence, complexity)`.
- Consumes: schema fields normalized by `src/parser/table_format.py`.

- [ ] **Step 1: Add a failing generated-PDF extraction test**

```python
def test_native_table_keeps_structure_and_source_crop(tmp_path):
    pdf_path = build_native_table_pdf(tmp_path / "native.pdf")
    pages = PDFExtractor(output_dir=tmp_path / "out").extract(str(pdf_path))
    table = pages[0].tables[0]
    assert table.rows == [["구분", "값"], ["A", "10"]]
    assert table.cells[0]["row"] == 0
    assert table.column_widths and abs(sum(table.column_widths) - 1.0) < .01
    assert Path(table.source["image_path"]).is_file()
    assert table.source["sha256"] == sha256_file(table.source["image_path"])
    assert table.confidence["score"] >= .90
```

- [ ] **Step 2: Run the single test and verify `TableData` lacks the new fields**

- [ ] **Step 3: Extend `TableData` with defaulted structured fields**

```python
@dataclass
class TableData:
    rows: List[List[str]]
    bbox: Optional[tuple] = None
    cells: List[dict] = field(default_factory=list)
    column_widths: List[float] = field(default_factory=list)
    row_heights: List[float] = field(default_factory=list)
    source: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    complexity: dict = field(default_factory=dict)
```

- [ ] **Step 4: Render and hash every native table crop**

Pass page number, source PDF path, and a `table_images` output directory into `_extract_text_tables`. Render `fitz.Rect(bbox)` at 216 DPI, write a deterministic SHA-256-based PNG name, and store relative-source metadata. When rendering fails, store `source.missing_reason` with the exception class name.

- [ ] **Step 5: Recover native geometry**

Convert PyMuPDF cell bboxes to row/column positions, infer row/column spans from covered grid intervals, calculate normalized widths/heights, and record `native_grid`, `all_words_assigned`, or failure reasons. Flag formulas, embedded images intersecting the bbox, rotated text, and non-rectangular/complex merges.

- [ ] **Step 6: Run native extraction tests plus `pytest tests/test_parser_2025.py -q`**

---

### Task 3: OCR grid tables and spatial ownership

**Files:**
- Create: `src/parser/table_detection.py`
- Modify: `src/parser/extractor.py:430-505`
- Modify: `src/parser/question.py:250-410`
- Create: `tests/test_table_detection.py`
- Modify: `tests/test_question_parser_cover.py`

**Interfaces:**
- Produces: `detect_ocr_tables(page, structured_page, image_dir, source_path, page_number) -> list[TableData]`, `assign_table_owner(table_bbox, question_regions) -> tuple[str, int] | None`, and anchored version 2 table specs.
- Consumes: `StructuredPage` word/line bboxes and `TableData` from Task 2.

- [ ] **Step 1: Write failing grid and ownership tests**

```python
def test_grid_detector_assigns_each_word_once(grid_page_fixture):
    tables = detect_ocr_tables(**grid_page_fixture)
    assert tables[0].rows == [["구분", "값"], ["A", "10"]]
    assigned = [cell["text"] for cell in tables[0].cells if cell["text"]]
    assert assigned == ["구분", "값", "A", "10"]

def test_choice_bbox_owns_intersecting_table():
    regions = {"question": (0, 0, 500, 300), "choices": {2: (0, 180, 500, 260)}}
    assert assign_table_owner((50, 195, 450, 245), regions) == ("choice", 2)
```

- [ ] **Step 2: Run focused tests and verify missing-module failures**

- [ ] **Step 3: Implement deterministic OCR grid detection**

Detect horizontal/vertical drawing segments, cluster coordinates within 3 points, build closed cells, and assign each structured word to the single cell containing its center. Calculate confidence from grid completeness, word assignment ratio, edge consistency, and empty/duplicate ratios. Borderless aligned text may form a table only when at least two rows and two columns repeat within coordinate tolerance, and receives at most `0.79` confidence.

- [ ] **Step 4: Replace string-only ownership with bbox-first ownership**

Build question and choice vertical regions from structured question/choice lines. Select the owner with the greatest intersection ratio; require exactly one owner above `0.50`. Use legacy cell-text matching only when structured coordinates are unavailable, and set confidence reason `legacy_text_match`.

- [ ] **Step 5: Remove duplicated table text and create anchors**

For spatially owned tables, remove the exact contiguous table-derived text from the owner text only when normalized cell text equals the candidate segment. Store the removed segment position as `anchor.offset` plus 24-character before/after contexts. If safe removal is impossible, keep text and set `complexity.has_duplicate_text_risk = true` so quality validation reports it.

- [ ] **Step 6: Run table detector and parser regression tests**

---

### Task 4: Editor preservation and table cards

**Files:**
- Modify: `src/gui/interface/editor.py:1-300,825-875,1030-1070`
- Modify: `tests/test_editor_layout.py`
- Create: `tests/test_editor_table_format.py`

**Interfaces:**
- Produces: table cards for question/choice owners, `QuestionEditor._update_table_spec(owner, table_id, changes)`, and saves merged schema version 2 payloads.
- Consumes: `merge_format_spans`, `resolve_table_anchor`, and normalized tables from Task 1.

- [ ] **Step 1: Add failing preservation tests**

```python
def test_saving_text_keeps_existing_table_payload(editor):
    editor.question_data["question_format_json"] = json.dumps(TABLE_PAYLOAD)
    editor.questionText.setPlainText("수정된 발문")
    _, saved = editor._question_text_and_format_json()
    payload = json.loads(saved)
    assert payload["tables"][0]["source"]["sha256"] == "abc123"
    assert payload["tables"][0]["anchor"]["offset"] == len("수정된 발문")
```

- [ ] **Step 2: Run the focused test and verify the current `_text_and_format_json` drops tables**

- [ ] **Step 3: Preserve non-span payload fields on save**

Replace the direct `json.dumps({'spans': spans})` return with `merge_format_spans(existing_format_json, spans)`, then recover each table anchor against normalized text. Preserve unknown top-level and table-level fields for forward compatibility.

- [ ] **Step 4: Add owner-specific table cards**

Render a compact card below the question editor and below each choice containing table id/status, source-image preview button, structure preview, edit button, per-table mode combo (`자동`, `원본 이미지`, `편집 가능한 표`), replace-source button, and restore-source button. Disable only actions whose required source/structure is absent.

- [ ] **Step 5: Add a modal structure editor**

Use `QTableWidget` to edit cell text and expose selected rectangular cell merge, horizontal alignment, and vertical alignment. Persist edits into `rows`, `cells`, and `render_mode`, while leaving `source` immutable except for explicit image replacement.

- [ ] **Step 6: Run `pytest tests/test_editor_layout.py tests/test_editor_table_format.py -q`**

---

### Task 5: Anchored DOCX rendering with three modes

**Files:**
- Modify: `src/exporter/docx.py:1-280,591-635`
- Modify: `tests/test_docx_exporter.py`

**Interfaces:**
- Produces: `DocxExporter(table_render_mode="auto")`, `set_table_render_mode(mode)`, `_render_format_blocks(container, text, format_json)`, `_add_native_table`, `_add_table_image`, and warning collection.
- Consumes: `effective_table_render_mode` and normalized schema version 2 tables.

- [ ] **Step 1: Add failing OpenXML tests for all modes and fallback**

```python
def test_auto_mode_uses_native_for_simple_high_confidence_table(tmp_path):
    output = export_one_table(tmp_path, confidence=.94, complex_table=False)
    with ZipFile(output) as package:
        xml = package.read("word/document.xml")
    assert b"<w:tbl" in xml
    assert b"word/media/" not in b"\n".join(package.namelist())

def test_image_mode_embeds_exact_source_crop(tmp_path):
    output, crop = export_image_table(tmp_path)
    with ZipFile(output) as package:
        media = package.read(next(name for name in package.namelist() if name.startswith("word/media/")))
    assert hashlib.sha256(media).digest() == hashlib.sha256(crop.read_bytes()).digest()
```

- [ ] **Step 2: Run focused tests and verify constructor/render failures**

- [ ] **Step 3: Split text at resolved anchors and render ordered blocks**

Sort normalized tables by resolved offset, write text preceding each anchor with existing span formatting, render the table, then write remaining text. Apply the same function to question stems and individual choices so tables keep their original owner and order.

- [ ] **Step 4: Implement native Word tables**

Build `rows x columns`, merge cells using `row_span`/`col_span`, apply normalized widths, row heights, horizontal/vertical alignment, borders, and shading. Preserve legacy `rows` as a simple `Table Grid` path. If a native render raises, append a warning and call image render.

- [ ] **Step 5: Implement exact image rendering and fallback chain**

Resolve relative paths against repository/app data roots. Insert the stored crop without recompression using `add_picture`. Image failure falls back to native; native failure falls back to image; rows-only data falls back to a simple table and records `legacy_rows_fallback`.

- [ ] **Step 6: Implement wide-table one-column sections**

When the requested width exceeds the active column width, insert continuous section breaks before and after the table, set the middle section to one column through `w:cols`, and restore the previous column count after the table.

- [ ] **Step 7: Run `pytest tests/test_docx_exporter.py -q`**

---

### Task 6: Export-screen document mode control

**Files:**
- Modify: `src/gui/interface/export.py:30-210,export_docx`
- Modify: `tests/test_export_interface.py`

**Interfaces:**
- Produces: `tableRenderModeFilter` with data values `auto`, `image`, `native` and passes the selected value to `DocxExporter`.
- Consumes: `DocxExporter.set_table_render_mode` from Task 5.

- [ ] **Step 1: Add a failing UI wiring test**

```python
def test_export_table_mode_is_forwarded(export_interface, monkeypatch):
    export_interface.tableRenderModeFilter.setCurrentIndex(
        export_interface.tableRenderModeFilter.findData("image")
    )
    assert export_interface._selected_table_render_mode() == "image"
```

- [ ] **Step 2: Add the `표 출력 방식` combo beneath choice shuffling**

Populate labels/data as `자동/auto`, `원본 이미지/image`, `편집 가능한 표/native`; default to auto and add a tooltip describing the 0.90 threshold and per-table override.

- [ ] **Step 3: Forward selection immediately before export and surface non-fatal warnings in an InfoBar**

- [ ] **Step 4: Run `pytest tests/test_export_interface.py -q`**

---

### Task 7: Portable JSON assets and staging quality gate

**Files:**
- Modify: `scripts/prepare_portable_data.py:1-145`
- Modify: `tests/test_prepare_portable_data.py`
- Create: `scripts/validate_table_payloads.py`
- Create: `tests/test_validate_table_payloads.py`

**Interfaces:**
- Produces: portable rewriting for both format JSON columns and `validate_database(db_path, source_root=None) -> dict`.
- Consumes: `parse_format_payload`, `serialize_format_payload`, and `validate_table_spec` from Task 1.

- [ ] **Step 1: Extend the test database fixture with both format JSON columns and table source images**

Assert copied table images use `data/portable_images/<sha256>.png`, both JSON columns are rewritten, shared images are copied once, and missing table assets follow `allow_missing_images` exactly like current question/choice images.

- [ ] **Step 2: Run the portable tests and verify table JSON paths remain unchanged**

- [ ] **Step 3: Implement JSON image-reference iteration and rewriting**

Select `id, question_format_json` from `questions` and `id, choice_format_json` from `question_choices` only when each column exists. Normalize the payload, copy every non-empty `tables[*].source.image_path`, update the JSON in the copied factory DB, and include table image counts/missing records in the manifest.

- [ ] **Step 4: Implement the read-only database validator**

Scan both format columns, validate source existence/hash, bbox, cells/spans, ownership marker, duplicate-text risk, anchor recovery, and low-confidence source presence. Return exact counters: `tables`, `native_ready`, `image_fallback`, `legacy_rows`, `warnings`, `errors`, plus row/table identifiers for every finding.

- [ ] **Step 5: Add staging application mode guarded by backup and transaction**

The script accepts `--db`, `--source-root`, `--report`, and optional `--normalize`. `--normalize` first creates `<db>.pre_table_v2.<timestamp>.bak`, starts one SQLite transaction, rewrites only payloads that validate without errors, rolls back on exception, and writes the JSON report before exit.

- [ ] **Step 6: Run portable and validator tests**

---

### Task 8: Integrated regression and real-data dry run

**Files:**
- Modify only if a failing regression demonstrates a defect in files from Tasks 1-7.

**Interfaces:**
- Consumes: all earlier task outputs.
- Produces: verified application behavior and a staging report; it does not replace a mounted database without a separate explicit user request identifying that database.

- [ ] **Step 1: Run focused table tests**

Run: `pytest tests/test_table_format.py tests/test_table_detection.py tests/test_editor_table_format.py tests/test_docx_exporter.py tests/test_export_interface.py tests/test_prepare_portable_data.py tests/test_validate_table_payloads.py -q`

Expected: all pass with no warnings introduced by the new tests.

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`

Expected: all existing and new tests pass.

- [ ] **Step 3: Run static and whitespace checks**

Run: `python -m compileall -q src scripts` and `git diff --check`

Expected: both exit with code 0.

- [ ] **Step 4: Validate a copied staging database when an application database is discoverable**

Copy the discovered writable application DB to a timestamped staging path, run `python scripts/validate_table_payloads.py --db <staging-db> --source-root <repo-root> --report <report.json> --normalize`, rerun without `--normalize`, and require zero structural errors. Never modify or replace the live/mounted DB during this implementation pass.

- [ ] **Step 5: Inspect Git scope**

Run `git status --short`, confirm the personal `exam_bank.maritime_domain.20260705_175510.examdb.zip` remains untracked and excluded, and report changed source/tests/docs plus exact verification counts.
