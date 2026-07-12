# Structured PDF Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared position-aware offline exam parser, reparse the coast-guard PDF folder into a validated staging database, and atomically replace the mounted Maritime database.

**Architecture:** Preserve word/line coordinates from native extraction and WinRT OCR, then classify semantic blocks before constructing questions. Subject importers become adapters around the common parser, and a separate staging/replacement command prevents low-confidence content from reaching the mounted database.

**Tech Stack:** Python 3.12, PyMuPDF, WinRT OCR, SQLite, pytest

## Global Constraints

- Input PDF root is `E:\1. 인천해사고\2. 수업 관련\8. 학생 진로 상담\해경`.
- PDFs, OCR caches, generated reports containing source content, database files, and database backups must not be committed.
- No generic `원문 보기 참조` choices may be written to staging.
- `㉠`–`㉭` are proposition labels; `①`–`⑤` are final-choice labels.
- A failed exam-set validation leaves `data/domain_dbs/exam_bank.Maritime.db` unchanged.
- Replacement requires a timestamped backup, SQLite integrity check, application schema validation, atomic `os.replace`, and a receipt.
- Golden Q8 must preserve all four propositions and produce choices `44`, `46`, `48`, `50` with no footer leakage.

---

### Task 1: Structured page extraction

**Files:**
- Create: `src/parser/layout.py`
- Modify: `src/parser/extractor.py`
- Test: `tests/test_pdf_structured_layout.py`

**Interfaces:**
- Produces `LayoutWord(text, bbox, confidence, column)`, `LayoutLine(words, bbox, page, column)`, `StructuredPage(number, width, height, kind, lines, images)`, and `PDFExtractor.extract_structured_page(page, page_number)`.

- [ ] Write failing tests using synthetic words for one-column, two-column, mixed single-column, and repeated fake-text-layer pages. Assert normalized coordinates, per-page column assignment, and stable line order.
- [ ] Run `python -m pytest tests/test_pdf_structured_layout.py -v`; expect import or assertion failures because the layout module does not exist.
- [ ] Implement frozen dataclasses, coordinate scaling, line grouping, per-page gutter/divider detection, body-density classification, and native/WinRT adapters. Keep existing `PageData.text` behavior for compatibility.
- [ ] Run `python -m pytest tests/test_pdf_structured_layout.py tests/test_pdf_text_ordering.py -v`; expect all passing.
- [ ] Commit `feat: preserve structured PDF layout`.

### Task 2: Common semantic question parser and quality gate

**Files:**
- Create: `src/parser/offline_exam.py`
- Create: `src/parser/offline_quality.py`
- Test: `tests/test_offline_exam_parser.py`

**Interfaces:**
- Consumes `list[StructuredPage]`.
- Produces `ParsedOfflineQuestion(number, stem, choices, source_page, confidence, diagnostics)` through `OfflineExamParser.parse_pages(pages)`.
- Produces `QualityResult(importable, reason_codes)` through `validate_offline_question(question)`.

- [ ] Write failing tests for explicit ①–④ choices, `<보기>` ㉠–㉣ preservation, OCR-damaged same-baseline four-cell recovery, footer removal, next-question boundary, and rejection of placeholders/contaminated choices.
- [ ] Include the exact Q8 structured-token fixture: stem propositions ㉠–㉣ and bottom row at four x positions yielding `44/46/48/50` despite damaged marker text.
- [ ] Run `python -m pytest tests/test_offline_exam_parser.py -v`; expect missing-module failure.
- [ ] Implement document noise roles, question regions, proposition blocks, explicit choices, coordinate-row recovery, diagnostics, confidence, and fail-closed validation.
- [ ] Run `python -m pytest tests/test_offline_exam_parser.py -v`; expect all passing.
- [ ] Commit `feat: add shared offline exam parser`.

### Task 3: Subject adapters and role inventory

**Files:**
- Create: `src/parser/offline_sources.py`
- Modify: `scripts/import_maritime_law_pdf.py`
- Modify: `scripts/import_maritime_english_pdf.py`
- Modify: `scripts/import_police_navigation_pdf.py`
- Modify: `scripts/import_police_engineering_pdf.py`
- Modify: `scripts/import_public_exam_pdf_folder.py`
- Test: `tests/test_offline_source_adapters.py`

**Interfaces:**
- Produces `classify_offline_document(path, probe) -> DocumentRole` and `parse_offline_question_pdf(path, metadata) -> OfflineParseResult`.
- Importers consume common questions and add only source metadata, exam grouping, topic tags, and answer associations.

- [ ] Write failing tests classifying 12 question papers, 15 answer/explanation files, and 3 notices from filenames and probes; assert notices never become question candidates.
- [ ] Write tests proving all four subject adapters call the shared parser and never synthesize generic choices.
- [ ] Run `python -m pytest tests/test_offline_source_adapters.py -v`; expect failures before adapter implementation.
- [ ] Implement the inventory/adapter module, connect OCR-required handling in the public importer, and replace duplicated splitter calls in the four subject importers.
- [ ] Run `python -m pytest tests/test_offline_source_adapters.py tests/test_public_exam_import_recovery.py -v`; expect all passing.
- [ ] Commit `refactor: unify offline subject importers`.

### Task 4: Staging validation and atomic replacement

**Files:**
- Create: `scripts/rebuild_offline_exam_db.py`
- Create: `src/database/staging.py`
- Test: `tests/test_offline_db_rebuild.py`

**Interfaces:**
- Produces `build_staging_database(root, staging_db, report_dir) -> RebuildSummary`.
- Produces `validate_staging_database(path, expected_sets) -> ValidationReport`.
- Produces `replace_mounted_database(staging, mounted, backup_dir, receipt_path) -> ReplacementReceipt`.

- [ ] Write failing tests for inventory counts, zero placeholders, per-set number/answer coverage, SQLite integrity, rollback on validation failure, backup creation, atomic replacement, receipt hashes, and mounted repository readability.
- [ ] Run `python -m pytest tests/test_offline_db_rebuild.py -v`; expect missing-module failures.
- [ ] Implement dry-run-by-default CLI with explicit `--replace`, staging schema initialization, provenance writes, validation reports, backup, atomic replacement, and receipt.
- [ ] Run `python -m pytest tests/test_offline_db_rebuild.py tests/test_database_validator.py tests/test_db_mount_prototype.py -v`; expect all passing.
- [ ] Commit `feat: rebuild mounted DB through staging`.

### Task 5: Real corpus reparse, regression, integration, and publish

**Files:**
- Generated and ignored: `outputs/offline_rebuild_20260713/**`
- Generated and ignored: `data/domain_dbs/backups/**`
- Modified runtime data: `data/domain_dbs/exam_bank.Maritime.db`

**Interfaces:**
- Consumes Tasks 1–4.
- Produces a validated staging DB, backup, replacement receipt, and pushed source branch/main commit.

- [ ] Run the rebuild without replacement against all 30 PDFs and inspect inventory, set validation, placeholder count, review queue, and Q8 golden output.
- [ ] If required sets fail, improve parser only through new failing regression tests, rerun focused tests, then rerun the corpus.
- [ ] When all required validation passes, run with `--replace`; verify backup and receipt, `PRAGMA integrity_check`, mounted repository search, Q8 content, and per-subject counts.
- [ ] Run `python -m pytest tests -q`; expect zero failures.
- [ ] Run `git diff --check`, inspect `git status -sb`, and ensure only source/tests/docs are tracked.
- [ ] Commit any final test-backed changes, fast-forward `main`, rerun the complete suite, and push `origin main`.
