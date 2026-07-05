# COMCBT Crawl Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crawl public COMCBT exam posts slowly, parse teacher PDFs into the local question bank with near-zero manual correction, and support grouped "set questions" in DB, selection, quiz, editor, and export UI.

**Architecture:** Keep crawling, parsing, normalization, validation, and DB import as separate stages with JSON artifacts between stages. Treat a "question group" as a first-class entity so one shared passage/image can own multiple child questions without duplicating the passage or splitting the set during random exam generation.

**Tech Stack:** Python stdlib `urllib`/`html.parser` for low-speed crawling, PyMuPDF for PDF text/image extraction, SQLite schema migrations, existing `ExamRepository`, `QuestionValidator`, PyQt UI, pytest.

---

## Target File Structure

- Create `src/web_import/comcbt_inventory.py`: board/document discovery and crawl manifest generation.
- Modify `src/web_import/comcbt.py`: keep current HTTP client and single-document parser, move shared code only if the file becomes too large.
- Create `src/web_import/comcbt_pdf.py`: PDF parser focused on teacher/student PDF layout, including set-passage detection and image crop mapping.
- Create `src/web_import/models.py`: dataclasses for crawl manifests, parsed questions, parsed groups, parse diagnostics.
- Create `src/web_import/importer.py`: DB import service that upserts exams, subjects, groups, questions, choices, source metadata.
- Create `scripts/comcbt_crawl.py`: keep current CLI, add phase commands.
- Modify `src/database/schema.sql`: add source and group tables without breaking existing questions.
- Modify `src/database/repository.py`: read/write group-aware question records.
- Modify `src/database/validator.py`: add group consistency checks and web-source quality checks.
- Modify `src/quiz/selection.py` or current selection module: select grouped questions atomically.
- Modify PyQt quiz/editor/export screens under `src/gui/`: render shared passage once and grouped child questions beneath it.
- Add tests under `tests/test_comcbt_*.py`, `tests/test_question_groups.py`, `tests/test_question_selection.py`, `tests/test_database_validator.py`.

---

## Data Model Decision

### New Tables

Add source metadata so imports are traceable and idempotent:

```sql
CREATE TABLE IF NOT EXISTS question_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    source_url TEXT NOT NULL,
    document_id TEXT,
    attachment_url TEXT,
    attachment_filename TEXT,
    content_hash TEXT NOT NULL,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, source_url, content_hash)
);
```

Add group/passages for set questions:

```sql
CREATE TABLE IF NOT EXISTS question_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_subject_id INTEGER NOT NULL REFERENCES exam_subjects(id),
    year INTEGER NOT NULL,
    session INTEGER NOT NULL,
    group_number INTEGER NOT NULL,
    group_type TEXT NOT NULL DEFAULT 'passage',
    shared_text TEXT,
    shared_image_path TEXT,
    source_id INTEGER REFERENCES question_sources(id),
    source_page INTEGER,
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_subject_id, year, session, group_number)
);
```

Link questions to groups without requiring all old rows to change:

```sql
ALTER TABLE questions ADD COLUMN group_id INTEGER REFERENCES question_groups(id);
ALTER TABLE questions ADD COLUMN group_order INTEGER;
ALTER TABLE questions ADD COLUMN source_id INTEGER REFERENCES question_sources(id);
ALTER TABLE questions ADD COLUMN source_question_id TEXT;
```

Existing rows remain valid with `group_id IS NULL`.

### Set Question Semantics

- A group contains shared passage/image/table/context.
- Child questions retain their own question text, choices, answer, and image if any.
- Selection unit is group-aware:
  - Standalone question counts as 1.
  - Set group counts as the number of child questions.
  - Random generation must never select only part of a group unless the user explicitly enables "set 분리 허용".
- Export order must keep child questions contiguous.
- Editor must allow editing shared passage once, then child questions below it.

---

## UI/UX Placement For Set Questions

### Quiz Screen

- Render shared passage in a fixed top panel only while the current question belongs to that group.
- Below it, render child question stem and choices normally.
- Add compact group progress text: `공통지문 3문항 중 1번`.
- In one-question mode, keep the passage visible when moving among child questions.
- In OMR/list mode, render the shared passage once, followed by Q1-Qn cards.
- If shared passage is long, make only the passage panel scrollable; choices remain close to the child question.

### Editor Screen

- Left list:
  - Standalone rows: `2025-1 Q12`
  - Group rows: `공통지문 G03 (Q12-Q14)` expandable to children.
- Detail panel:
  - Group tab: shared passage, shared image, source URL, diagnostics.
  - Question tab: child stem, choices, answer.
- Warnings:
  - "그룹 내 일부 문항만 정답 없음"
  - "공통 이미지 없음"
  - "그룹 선택 시 3문항으로 계산됨"

### Export/Print

- DOCX/PDF export must print:
  - `[공통지문]` block once
  - child question numbers below
  - answer table still lists each child question separately.

---

## Phase 0: Safety And Source Policy

### Task 0.1: Crawl Guardrails

**Files:**
- Modify: `src/web_import/comcbt.py`
- Test: `tests/test_comcbt_import.py`

- [ ] Keep `SlowHttpClient` default delay at 2 seconds.
- [ ] Keep robots.txt check enabled.
- [ ] Add `--max-docs`, `--max-boards`, `--since-year`, `--until-year`, and `--dry-run` defaults to every batch command.
- [ ] Store only fetched artifacts under `tmp/comcbt_*` until `--apply` is passed.
- [ ] Never crawl URLs containing blocked query parameters from robots.txt such as `search_target=`, `order_type=`, `sort_index=`, `act=dispMemberFindAccount`, `listStyle=`, `selected_date=`, `entry=`, `?l=`, `&l=`, `?m=`, `&m=`.

**Validation:**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_comcbt_import.py
```

Expected: all tests pass.

---

## Phase 1: Complete Inventory Without Downloading PDFs

### Task 1.1: Board Inventory

**Files:**
- Create: `src/web_import/comcbt_inventory.py`
- Modify: `scripts/comcbt_crawl.py`
- Test: `tests/test_comcbt_inventory.py`

- [ ] Fetch `https://www.comcbt.com/cbt/index2.php?hack_number=29`.
- [ ] Extract all `/xe/{mid}` exam board links.
- [ ] Normalize each board as:

```json
{
  "provider": "comcbt",
  "exam_name": "9급 국가직 공무원 건축계획",
  "mid": "wc",
  "board_url": "https://www.comcbt.com/xe/wc"
}
```

- [ ] Deduplicate by `mid`.
- [ ] Write `data/import_manifests/comcbt_boards.json`.

**Validation:**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 2 inventory --output data\import_manifests\comcbt_boards.json
```

Expected: JSON contains hundreds of board entries, no duplicate `mid`.

### Task 1.2: Document Inventory

**Files:**
- Modify: `src/web_import/comcbt_inventory.py`
- Modify: `scripts/comcbt_crawl.py`
- Test: `tests/test_comcbt_inventory.py`

- [ ] For each board URL, fetch only page 1 first.
- [ ] Extract document URLs matching `/xe/{mid}/{document_srl}` and titles containing `기출문제` or `CBT`.
- [ ] Parse year/date/session from titles.
- [ ] Write one manifest row per document:

```json
{
  "exam_name": "9급 국가직 공무원 건축계획",
  "mid": "wc",
  "document_srl": "8837719",
  "document_url": "https://www.comcbt.com/xe/wc/8837719",
  "year": 2025,
  "session": 1,
  "status": "discovered"
}
```

- [ ] Do not follow pagination globally until page 1 behavior is verified.

**Validation:**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 2 board --board-url https://www.comcbt.com/xe/wc --output tmp\wc_docs.json
```

Expected: known document `8837719` appears.

### Task 1.3: Pagination Expansion

**Files:**
- Modify: `src/web_import/comcbt_inventory.py`
- Test: `tests/test_comcbt_inventory.py`

- [ ] Detect board pagination only through allowed `/xe/{mid}/page/{n}` or canonical page links if present.
- [ ] Stop when a page returns no new `document_srl`.
- [ ] Cap default pages per board to 3 unless `--all-pages` is provided.
- [ ] Store crawl stats: requested URLs, new docs, duplicate docs, failures.

**Validation:**

Run with a small cap:

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 2 crawl-docs --max-boards 3 --max-pages 2 --dry-run
```

Expected: manifest is produced without PDF downloads.

---

## Phase 2: Attachment Manifest

### Task 2.1: Document Page Attachment Extraction

**Files:**
- Modify: `src/web_import/comcbt.py`
- Test: `tests/test_comcbt_import.py`

- [ ] Fetch each document page.
- [ ] Extract attachments where link includes `procFileDownload`.
- [ ] Classify by filename:
  - `교사용`: answer-included source, primary parser input.
  - `학생용`: question-only source, fallback for cleaner images.
  - unknown PDF/HWP: retained but not imported automatically.
- [ ] Prefer teacher PDF over teacher HWP, because PyMuPDF is already available and PDF extraction is deterministic.

**Validation:**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 2 parse-doc --url https://www.comcbt.com/xe/wc/8837719
```

Expected: selected file name contains `(교사용).pdf`.

### Task 2.2: Attachment Hashing

**Files:**
- Modify: `src/web_import/importer.py`
- Test: `tests/test_comcbt_importer.py`

- [ ] Hash each downloaded attachment with SHA-256.
- [ ] Store `provider`, `document_url`, `attachment_url`, `filename`, `hash`, `fetched_at`.
- [ ] Skip import when the same provider/document/hash already exists unless `--force` is passed.

---

## Phase 3: High-Accuracy PDF Parsing

### Task 3.1: Text Layout Parser

**Files:**
- Create: `src/web_import/comcbt_pdf.py`
- Test: `tests/test_comcbt_pdf.py`

- [ ] Extract per-page lines with PyMuPDF `page.get_text("dict")` so bbox is available.
- [ ] Drop repeated headers and footer marketing lines.
- [ ] Split question blocks on `^\d{1,3}\.`.
- [ ] Split choices on `①②③④❶❷❸❹`.
- [ ] Use filled symbols `❶❷❸❹` as primary answer signal.
- [ ] Use trailing answer table as secondary answer signal.
- [ ] Fail document import if filled-symbol answer and answer-table answer disagree.

**Accuracy target:** 100% question count and 100% answer count for a document, otherwise document status becomes `needs_review`, not imported.

### Task 3.2: Visual Question Detection

**Files:**
- Modify: `src/web_import/comcbt_pdf.py`
- Test: `tests/test_comcbt_pdf.py`

- [ ] Mark a visual question when:
  - any choice text is empty after a choice symbol;
  - question text contains `그림`, `도표`, `그래프`, `다음과 같은`, `다음 조건`;
  - PyMuPDF detects embedded images inside the question block bbox.
- [ ] Crop the full question block for visual questions.
- [ ] For image-only choices, set choice text to `[이미지 선지]` and keep question crop in `question.image_path`.

**Rationale:** Exact per-choice crop can be added later. Full-block crop avoids losing context and prevents manual correction.

### Task 3.3: Set Passage Detection

**Files:**
- Modify: `src/web_import/comcbt_pdf.py`
- Create: `tests/fixtures/comcbt_set_question_text.txt`
- Test: `tests/test_comcbt_set_questions.py`

- [ ] Detect shared passage blocks before question starts using patterns:
  - `[공통]`, `[공통지문]`, `다음 글을 읽고`, `다음 자료를 보고`, `다음 지문을 읽고`, `다음은 .* 물음에 답하시오`, `[문제 \d+~\d+]`.
- [ ] Detect range markers:

```python
RANGE_RE = re.compile(r"(?:문제|문항)?\s*(\d{1,3})\s*[~∼-]\s*(\d{1,3})")
```

- [ ] Attach the shared passage to all questions in the range.
- [ ] If no explicit range exists, attach the passage to following questions until the next passage marker or subject break.
- [ ] Store parse diagnostics:
  - `group_detected`
  - `group_range`
  - `group_child_count`
  - `ambiguous_group_range`

**Import rule:** Ambiguous set groups can be parsed to JSON but are not DB-imported until validator accepts them.

### Task 3.4: Generic Subject Strategy

**Files:**
- Modify: `src/web_import/comcbt_pdf.py`
- Test: `tests/test_comcbt_pdf.py`

- [ ] Use document title as `exam_type`.
- [ ] Use explicit `N과목 : ...` line as `subject_name` when present.
- [ ] If no subject line exists, use title-derived final token or `과목 구분 없음`.
- [ ] Do not assume 25 questions per subject.

---

## Phase 4: Validation Gate Before DB Import

### Task 4.1: Document-Level Quality Score

**Files:**
- Create: `src/web_import/quality.py`
- Test: `tests/test_comcbt_quality.py`

- [ ] A document is `importable` only when:
  - question count >= 1;
  - every question has 4 choices;
  - every question has a correct answer in 1..4;
  - no blank question text;
  - no blank choice text except `[이미지 선지]`;
  - group ranges are internally consistent;
  - image-required questions have a generated crop or embedded image path;
  - validator has no blocking errors.
- [ ] Write `parse_report.json` for every document.
- [ ] Write `needs_review.json` for rejected documents.

### Task 4.2: Cross-Source Consistency

**Files:**
- Modify: `src/web_import/quality.py`
- Test: `tests/test_comcbt_quality.py`

- [ ] Compare teacher PDF and student PDF when both exist:
  - question count must match;
  - normalized question number sequence must match;
  - image-required question numbers must match.
- [ ] Teacher PDF remains authority for answers.
- [ ] Student PDF can supply cleaner image crops only if question alignment is exact.

---

## Phase 5: DB Import

### Task 5.1: Group-Aware Importer

**Files:**
- Create: `src/web_import/importer.py`
- Modify: `src/database/repository.py`
- Test: `tests/test_comcbt_importer.py`

- [ ] Upsert exam by `exam_type`.
- [ ] Upsert subject by normalized subject name.
- [ ] Insert or reuse `question_sources`.
- [ ] Insert `question_groups` first.
- [ ] Insert child questions with `group_id` and `group_order`.
- [ ] Use uniqueness key:
  - standalone: `(exam_subject_id, year, session, question_number)`
  - grouped child: same key plus group metadata, because question number remains the visible number.
- [ ] On re-import with same content hash, do not create duplicate questions.

### Task 5.2: Source Traceability In UI

**Files:**
- Modify: editor detail UI under `src/gui/`
- Test: GUI-adjacent unit tests if available.

- [ ] Show source provider and URL in editor read-only metadata.
- [ ] Add "원문 열기" action for source URL.
- [ ] Add "첨부 파일명" display when imported from COMCBT.

---

## Phase 6: Selection And Exam Generation

### Task 6.1: Group-Aware Random Selection

**Files:**
- Modify: `src/quiz/selection.py` or current selection code.
- Test: `tests/test_question_selection.py`

- [ ] Build selection candidates as units:
  - `{type: "single", question_ids: [id], count: 1}`
  - `{type: "group", group_id: id, question_ids: [...], count: n}`
- [ ] When requested count is 25, fill by unit count.
- [ ] If a group would exceed requested count:
  - default: skip it and try another unit;
  - if strict fill is impossible, show a message with available count.
- [ ] Preserve child order by `group_order`.

### Task 6.2: Export Numbering

**Files:**
- Modify: `src/exporter/`
- Test: `tests/test_docx_exporter.py`

- [ ] Print shared passage once.
- [ ] Number child questions continuously according to generated exam order.
- [ ] Keep answer key mapping to rendered question numbers.

---

## Phase 7: UI Rendering For Set Questions

### Task 7.1: Quiz Rendering

**Files:**
- Modify: quiz UI files under `src/gui/`
- Test: `tests/test_editor_layout.py` or new UI layout test.

- [ ] Add shared passage panel above child question.
- [ ] Add group progress label.
- [ ] Keep answer controls unchanged.
- [ ] In review mode, show group passage once and child answer statuses below.

### Task 7.2: Editor Rendering

**Files:**
- Modify: editor UI files under `src/gui/`
- Test: `tests/test_editor_layout.py`

- [ ] Add expandable group rows in question list.
- [ ] Allow editing shared passage text.
- [ ] Allow replacing shared image.
- [ ] Validate child count and answer completeness before saving.

---

## Phase 8: Batch Crawl Execution

### Task 8.1: Pilot Batch

**Command:**

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 3 crawl-docs --max-boards 5 --max-pages 1 --dry-run
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 3 parse-manifest --manifest tmp\comcbt_manifest.json --max-docs 20
```

**Gate:**

- Importable rate must be >= 95%.
- No document with answer mismatch is imported.
- All failed documents must have machine-readable diagnostics.

### Task 8.2: Category Batch

**Command:**

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 3 parse-manifest --manifest data\import_manifests\comcbt_docs.json --exam-filter "건축" --apply
```

**Gate:**

- Validate DB after each category:

```powershell
.\.venv\Scripts\python.exe scripts\repair_db_text.py --db data\exam_bank.db
.\.venv\Scripts\python.exe -m pytest tests\test_comcbt_import.py tests\test_question_selection.py tests\test_database_validator.py
```

### Task 8.3: Full Batch

**Command:**

```powershell
.\.venv\Scripts\python.exe scripts\comcbt_crawl.py --delay 5 parse-manifest --manifest data\import_manifests\comcbt_docs.json --apply --resume
```

**Gate:**

- Run in resumable batches.
- Create DB backup before each batch.
- Stop batch automatically if importable rate drops below 90% for the latest 50 documents.

---

## Accuracy Strategy

1. Prefer teacher PDF because answer is visually embedded with filled symbols and answer table.
2. Use two independent answer signals where possible.
3. Reject, do not guess, when answer signals disagree.
4. Crop visual question blocks instead of trying to OCR diagram text.
5. Treat set passages as group records, not duplicated text.
6. Keep every import source URL/hash so bad imports can be traced and re-run.
7. Make DB import idempotent and resumable.
8. Batch by category and stop on quality regression.

---

## Self-Review

- Spec coverage: crawling, parsing, DB import, set-question UI/UX, and high-accuracy validation are covered.
- Placeholder scan: no implementation task relies on unspecified manual correction.
- Type consistency: `question_groups`, `group_id`, `group_order`, `question_sources`, and parser dataclasses are consistently named across phases.

