# public exam PDF Import Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce unresolved PDFs from `T:\내 드라이브\[공부] 시험자료` by turning recoverable `blocked_no_text`, `skipped_answer_secondary`, and `blocked_quality` cases into validated DB imports while preserving the existing Exam-Subject-Year-session duplicate gate.

**Architecture:** Keep `scripts/import_public_exam_pdf_folder.py` as the importer, but add a recovery audit layer and targeted parsers instead of relaxing quality gates globally. The recovery process first deduplicates inventory rows, classifies failure causes, then reprocesses only recoverable cohorts through improved extraction, answer pairing, and quality checks.

**Tech Stack:** Python 3, PyMuPDF (`fitz`), SQLite, existing `ComcbtPdfParser`, existing `ComcbtImportService`, pytest.

---

## File Structure

- Modify: `scripts/import_public_exam_pdf_folder.py`
  - Add audit-friendly failure notes.
  - Improve `blocked_no_text` fallback extraction.
  - Improve answer-file pairing and answer-primary promotion.
  - Add targeted reprocess list support.
- Create: `scripts/audit_public_exam_import_blocks.py`
  - Deduplicate `01_pdf_inventory.csv`.
  - Classify failure causes by root category, role, raw text availability, and review error.
  - Write phase CSVs for reprocessing.
- Create: `tests/test_public_exam_import_recovery.py`
  - Unit tests for role detection, answer pairing, answer-primary promotion, and deduped inventory logic.
- Output: `outputs/public_exam_pdf_import_20260704_recovery/`
  - Store audit CSVs, reprocess logs, and final summaries.

---

### Task 1: Build A Reliable Failure Audit

**Files:**
- Create: `scripts/audit_public_exam_import_blocks.py`
- Test: `tests/test_public_exam_import_recovery.py`

- [x] **Step 1: Write tests for deduped inventory and status grouping**

```python
from scripts.audit_public_exam_import_blocks import dedupe_inventory_rows, status_counts


def test_dedupe_inventory_rows_keeps_last_non_blank_status():
    rows = [
        {"relative_path": "A.pdf", "status": "blocked_no_text"},
        {"relative_path": "A.pdf", "status": ""},
        {"relative_path": "A.pdf", "status": "blocked_quality"},
        {"relative_path": "B.pdf", "status": ""},
    ]

    deduped = dedupe_inventory_rows(rows)

    assert deduped["A.pdf"]["status"] == "blocked_quality"
    assert deduped["B.pdf"]["status"] == ""


def test_status_counts_uses_deduped_rows():
    rows = [
        {"relative_path": "A.pdf", "status": "blocked_no_text"},
        {"relative_path": "A.pdf", "status": "skipped_answer_secondary"},
        {"relative_path": "B.pdf", "status": "blocked_no_text"},
    ]

    assert status_counts(rows) == {
        "skipped_answer_secondary": 1,
        "blocked_no_text": 1,
    }
```

- [x] **Step 2: Run the tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_public_exam_import_recovery.py -q
```

Expected: FAIL because `scripts.audit_public_exam_import_blocks` does not exist.

- [x] **Step 3: Implement the audit script**

Implement:

```python
def dedupe_inventory_rows(rows):
    latest = {}
    for row in rows:
        rel = row.get("relative_path")
        if not rel:
            continue
        if not row.get("status"):
            latest.setdefault(rel, row)
        else:
            latest[rel] = row
    return latest


def status_counts(rows):
    from collections import Counter
    deduped = dedupe_inventory_rows(rows)
    return dict(Counter(row.get("status") or "<blank>" for row in deduped.values()))
```

Add CLI:

```powershell
.\.venv\Scripts\python.exe scripts\audit_public_exam_import_blocks.py `
  --inventory outputs\public_exam_pdf_import_20260703\01_pdf_inventory.csv `
  --review-dir outputs\public_exam_pdf_import_20260703\review_payloads `
  --output-dir outputs\public_exam_pdf_import_20260704_recovery\audit
```

Expected outputs:
- `status_summary.json`
- `blocked_no_text_sample.csv`
- `blocked_quality_error_summary.csv`
- `answer_secondary_without_primary.csv`
- `reprocess_candidates_phase1.csv`

- [x] **Step 4: Run tests and audit command**

Expected:
- Tests PASS.
- Audit files are written.
- Candidate counts are non-zero or explicitly zero with reason.

---

### Task 2: Split `blocked_no_text` Into Recoverable And OCR-Required

**Files:**
- Modify: `scripts/audit_public_exam_import_blocks.py`
- Modify: `scripts/import_public_exam_pdf_folder.py`
- Test: `tests/test_public_exam_import_recovery.py`

- [x] **Step 1: Write tests for raw-text recoverability classification**

```python
from scripts.audit_public_exam_import_blocks import classify_no_text_case


def test_classify_no_text_case_marks_text_start_failure():
    assert classify_no_text_case(
        raw_text_length=5000,
        clean_text_length=0,
        image_count=0,
        question_marker_count=20,
    ) == "text_start_detection_failed"


def test_classify_no_text_case_marks_ocr_required():
    assert classify_no_text_case(
        raw_text_length=0,
        clean_text_length=0,
        image_count=12,
        question_marker_count=0,
    ) == "ocr_required"
```

- [x] **Step 2: Add raw PDF probe to audit**

For each `blocked_no_text` sample, collect:
- `raw_text_length`
- `raw_question_marker_count`
- `page_count`
- `image_count`
- `cause`

Use PyMuPDF:

```python
with fitz.open(path) as doc:
    raw_text = "\n".join(page.get_text("text") for page in doc)
    image_count = sum(len(page.get_images(full=True)) for page in doc)
```

- [x] **Step 3: Improve fallback extraction in importer**

In `clean_pdf_text`, when `EXAM_START_RE` fails but raw page text has question markers:
- Include dense pages where `question_count >= 1 and choice_count >= 4`.
- Use page text lines in reading order.
- Mark note `fallback_question_marker_pages`.

- [x] **Step 4: Reprocess only recoverable `blocked_no_text` candidates**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\import_public_exam_pdf_folder.py `
  "T:\내 드라이브\[공부] 시험자료" `
  --output-dir outputs\public_exam_pdf_import_20260704_recovery\phase1 `
  --apply --skip-backup `
  --reprocess-list outputs\public_exam_pdf_import_20260704_recovery\audit\reprocess_candidates_phase1.csv `
  --log-every 50
```

Expected:
- Some previous `blocked_no_text` rows move to `imported`, `skipped_existing_key`, or `blocked_quality`.
- True image-only rows remain excluded with `ocr_required`.

---

### Task 3: Recover Primary-Missing Answer-Only Sets

**Files:**
- Modify: `scripts/import_public_exam_pdf_folder.py`
- Test: `tests/test_public_exam_import_recovery.py`

- [x] **Step 1: Write tests for answer-only primary promotion**

```python
from pathlib import Path
from scripts.import_public_exam_pdf_folder import should_promote_answer_pdf


def test_promote_answer_pdf_when_no_matching_question_pdf_exists(tmp_path):
    answer = tmp_path / "2025_해경_한국사_정답_123.pdf"
    answer.write_text("x", encoding="utf-8")

    assert should_promote_answer_pdf(answer, "정답") is True


def test_do_not_promote_answer_pdf_when_question_pdf_exists(tmp_path):
    question = tmp_path / "2025_해경_한국사_자료_122.pdf"
    answer = tmp_path / "2025_해경_한국사_정답_123.pdf"
    question.write_text("x", encoding="utf-8")
    answer.write_text("x", encoding="utf-8")

    assert should_promote_answer_pdf(answer, "정답") is False
```

- [x] **Step 2: Implement answer-primary promotion**

Rules:
- If a file is answerish but no matching `자료/문제` PDF exists, process it as primary.
- If the answer PDF contains both questions and answer table, parse and import.
- If it only contains answer table, keep `skipped_answer_secondary`.

- [x] **Step 3: Run targeted reprocess**

Use `answer_secondary_without_primary.csv` from Task 1.

Expected:
- Some answer-only sets become importable.
- Pure answer sheets remain skipped.

---

### Task 4: Fix `blocked_quality` By Error Class

**Files:**
- Modify: `scripts/import_public_exam_pdf_folder.py`
- Test: `tests/test_public_exam_import_recovery.py`

- [x] **Step 1: Summarize review payload errors**

Audit should count:
- `invalid_correct_answer`
- `choice_count`
- `question_numbers_not_contiguous`
- `answer_key_count_mismatch`
- `ambiguous_group_range`
- `missing_question_image`

- [x] **Step 2: Add tests for the top two actual error classes**

Write tests only after the audit identifies the top two error classes. Use short extracted-line fixtures copied from `review_payloads`, not synthetic guesses.

- [x] **Step 3: Patch only the matching parser logic**

Examples:
- For `answer_key_count_mismatch`, improve answer table row-token merging.
- For `choice_count`, improve inline-choice splitting and table-choice splitting.
- For `question_numbers_not_contiguous`, handle page headers, duplicate UI lists, or missing dot-space forms.

- [x] **Step 4: Reprocess `blocked_quality` candidates**

Expected:
- Recover only rows with all questions, choices, and valid answer keys.
- Ambiguous or image-dependent rows remain in review queue.

---

### Task 5: Strengthen Duplicate-Key Normalization

**Files:**
- Modify: `scripts/import_public_exam_pdf_folder.py`
- Test: `tests/test_public_exam_import_recovery.py`

- [x] **Step 1: Write tests for common alias keys**

```python
from scripts.import_public_exam_pdf_folder import ExamKey, candidate_key_aliases


def test_candidate_alias_for_haegyeong_1cha():
    aliases = candidate_key_aliases(ExamKey("해경 1차", "항해술", 2020, 1))
    assert any(alias.exam_type == "해경" and alias.session == 1 for alias in aliases)


def test_candidate_alias_for_public_job_subject_embedded_exam():
    aliases = candidate_key_aliases(ExamKey("국가직 9급", "한국사", 2024, 1))
    assert any("9급 국가직 공무원 한국사" in alias.exam_type for alias in aliases)
```

- [x] **Step 2: Add alias rules**

Add rules for:
- `해경 1차/2차/3차` -> `해경` with matching session.
- `국가직 7급(2차)` -> `국가직 7급` session 2.
- `지방직/서울시/국회직/법원직` embedded subject forms.

- [ ] **Step 3: Rerun precheck on unresolved candidates**

Expected:
- More rows become `skipped_existing_key_precheck`.
- DB avoids duplicate imports.

Progress on 2026-07-04 continuation:
- Added `--reprocess-status` so unresolved candidates can be filtered directly from `deduped_inventory.csv`.
- Partial `blocked_no_text` reprocess produced `skipped_existing_key_precheck: 23` before the long dry-run was stopped to avoid duplicate writes after timeout.

---

### Task 6: Final Reprocess And Verification

**Files:**
- Output: `outputs/public_exam_pdf_import_20260704_recovery/final_summary.json`

- [ ] **Step 1: Create DB backup**

Run:

```powershell
Copy-Item data\exam_bank.db outputs\public_exam_pdf_import_20260704_recovery\db_backups\exam_bank.before_recovery.db
```

- [ ] **Step 2: Run all targeted reprocess phases**

Run importer with:
- `phase1` recoverable no-text candidates
- `phase2` answer-primary candidates
- `phase4` fixed quality candidates

- [x] **Step 3: Verify DB**

Run:

```powershell
.\.venv\Scripts\python.exe - <<'PY'
import sqlite3
con = sqlite3.connect('data/exam_bank.db')
cur = con.cursor()
print(cur.execute('pragma integrity_check').fetchone()[0])
print(cur.execute("select count(*) from questions q join question_sources s on q.source_id=s.id where s.provider='public_exam_pdf'").fetchone()[0])
PY
```

Expected:
- `ok`
- `public_exam_pdf` question count remains `20`; no DB apply was performed because remaining candidates were duplicate/listing/image-answer/missing-answer-key limited.

- [x] **Step 4: Run regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\test_public_exam_import_recovery.py `
  tests\test_repository.py::test_save_questions_preserves_fifth_choice `
  tests\test_comcbt_pdf.py::test_tail_answer_key_parses_repeated_number_answer_row_pairs -q
```

Expected: PASS.

Actual:
- `34 passed`

---

### Task 7: Continue Blocked/Skipped Triage

**Files:**
- Modified: `scripts/import_public_exam_pdf_folder.py`
- Modified: `tests/test_public_exam_import_recovery.py`
- Outputs:
  - `outputs/public_exam_pdf_import_20260704_recovery/phase5_no_text_classifier_probe100_preprobe_dryrun`
  - `outputs/public_exam_pdf_import_20260704_recovery/phase5_no_text_classifier_probe100_offset100_preprobe_dryrun`
  - `outputs/public_exam_pdf_import_20260704_recovery/phase5_no_text_classifier_probe100_offset200_preprobe_dryrun`
  - `outputs/public_exam_pdf_import_20260704_recovery/phase5_blocked_no_text_first500_preprobe_dryrun`

- [x] **Step 1: Split listing/non-exam pages out of `blocked_no_text`**

Added conservative raw-text probe classification:
- `skipped_non_exam_listing` for public exam listing/search pages with no choice markers.
- `blocked_no_text` remains for OCR/empty/text-start-failure cases.

- [x] **Step 2: Add fast pre-probe for high-volume listing pages**

Pre-probe is limited to `자료` PDFs with `과목 구분 없음`, reducing expensive layout parsing for clear listing pages.

- [x] **Step 3: Add reprocess-list status filter**

`--reprocess-status blocked_no_text` now filters existing inventory CSVs without creating separate candidate files.

- [x] **Step 4: Reprocess samples and partial batch**

Results:
- 100-row sample: `skipped_non_exam_listing: 97`, `blocked_quality: 2`, `skipped_answer_secondary: 1`.
- Offset 100 sample: `skipped_non_exam_listing: 96`, `blocked_quality: 3`, `skipped_answer_secondary: 1`.
- Offset 200 sample: `skipped_non_exam_listing: 96`, `blocked_quality: 3`, `skipped_answer_secondary: 1`.
- Unique across those sample outputs: `skipped_non_exam_listing: 99`, `blocked_quality: 4`, `skipped_answer_secondary: 1`.
- Partial first-500 run before timeout cleanup: unique `skipped_non_exam_listing: 66`, `skipped_existing_key_precheck: 23`, `blocked_quality: 74`.

- [x] **Step 5: Clarify remaining quality block reason**

Added `answer_key_missing` when parsed questions have no usable answer key. Representative blocked rows have answer-pair PDFs that contain continuation question text and OMR answer images/links, not text answer tables, so they remain unsafe for DB import without OCR or manual answer extraction.

---

## Self-Review

- Spec coverage: Addresses all unresolved buckets: `blocked_no_text`, `skipped_answer_secondary`, duplicate-key skips, and `blocked_quality`.
- Placeholder scan: No TODO/TBD placeholders; each task has commands and expected outcomes.
- Type consistency: Uses existing `ExamKey`, `PdfTextLine`, `ComcbtParsedExam`, and importer CLI conventions.
