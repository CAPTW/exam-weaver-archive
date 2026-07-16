# View Block One-Cell Table Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert every real `<보기>` block into an editable one-cell table across parsing, editing, existing database migration, and DOCX export.

**Architecture:** A focused `view_table` module owns marker recognition, last-block splitting, schema-v2 table creation, idempotence, and restoration. The parser and editor consume that contract, while a separate staging migrator copies and validates SQLite databases before an optional atomic replacement.

**Tech Stack:** Python 3.11, PyQt5/qfluentwidgets, SQLite, python-docx/OpenXML, pytest

## Global Constraints

- The last recognized `<보기>` marker starts the table; earlier reference markers remain in the question text.
- The marker and all following text become one cell in one row.
- Existing spans, tables, unknown JSON fields, answers, choices, images, and question identities must remain unchanged.
- Conversion must be idempotent.
- Deleting an editor table must restore its text at the resolved anchor.
- Existing databases are changed only through a validated staging copy and backup.
- Do not stage, commit, or push the untracked `exam_bank.maritime_domain.20260705_175510.examdb.zip`.
- Do not push Git changes until the user explicitly requests publication.

---

### Task 1: Shared `<보기>` block contract

**Files:**
- Create: `src/parser/view_table.py`
- Create: `tests/test_view_table.py`

**Interfaces:**
- Produces: `promote_view_block(text: str, format_json: object = None) -> tuple[str, str | None, bool]`, `add_one_cell_table(text: str, format_json: object, cell_text: str, offset: int, reason: str = "manual_editor") -> str`, and `remove_table_and_restore(text: str, format_json: object, table_id: str) -> tuple[str, str | None, bool]`.
- Consumes: `parse_format_payload`, `normalize_table_spec`, `resolve_table_anchor`, and `serialize_format_payload` from `src/parser/table_format.py`.

- [ ] **Step 1: Write failing marker, payload, and restoration tests**

```python
def test_last_view_marker_becomes_one_cell_table():
    text, encoded, changed = promote_view_block(
        "다음 <보기>에서 옳은 것은? <보기> ① A ② B"
    )
    payload = json.loads(encoded)
    assert changed is True
    assert text == "다음 <보기>에서 옳은 것은?"
    assert payload["tables"][0]["rows"] == [["<보기>\n① A ② B"]]
    assert payload["tables"][0]["anchor"]["offset"] == len(text)

def test_promotion_is_idempotent():
    first_text, first_json, _ = promote_view_block("질문? <보기> ㄱ. A")
    second_text, second_json, changed = promote_view_block(first_text, first_json)
    assert changed is False
    assert (second_text, second_json) == (first_text, first_json)

def test_remove_restores_cell_at_anchor():
    text, encoded, _ = promote_view_block("질문? <보기> ① A")
    restored, encoded, removed = remove_table_and_restore(text, encoded, "view-table-1")
    assert removed is True
    assert restored == "질문?\n<보기>\n① A"
    assert not json.loads(encoded).get("tables")
```

- [ ] **Step 2: Run `pytest tests/test_view_table.py -q`**

Expected: FAIL because `src.parser.view_table` does not exist.

- [ ] **Step 3: Implement the minimal shared converter**

```python
VIEW_MARKER_RE = re.compile(
    r"(?:<|＜|〈|《|\[|【)\s*보\s*기\s*(?:>|＞|〉|》|\]|】)"
)

def promote_view_block(text, format_json=None):
    value = str(text or "")
    matches = list(VIEW_MARKER_RE.finditer(value))
    if not matches or not value[matches[-1].end():].strip():
        return value, serialize_format_payload(parse_format_payload(format_json)), False
    marker = matches[-1]
    prefix = value[:marker.start()].rstrip()
    cell_text = marker.group(0).strip() + "\n" + value[marker.end():].strip()
    return prefix, add_one_cell_table(prefix, format_json, cell_text, len(prefix), "explicit_view_marker"), True
```

Create a normalized one-cell `cells` entry, unique `view-table-N` ID, native render mode, `source.kind = "view_block_text"`, score `1.0`, and 24-character anchor contexts. Treat an existing table with `source.kind == "view_block_text"` as already promoted. Restoration removes only the requested table and inserts its single cell with newline-safe spacing at `resolve_table_anchor`.

- [ ] **Step 4: Run `pytest tests/test_view_table.py -q`**

Expected: PASS.

---

### Task 2: Parser integration

**Files:**
- Modify: `src/parser/question.py:288-320`
- Modify: `tests/test_question_parser_cover.py`

**Interfaces:**
- Consumes: `promote_view_block` from Task 1.
- Produces: parsed `Question.text` without flattened view content and `Question.format_json` with a native one-cell table.

- [ ] **Step 1: Add a failing parser regression test**

```python
def test_parser_promotes_last_view_block_to_one_cell_table():
    questions = QuestionParser("3급항해사(상선)")._parse_page(
        "1. 다음 <보기>에서 옳은 것은? <보기> ㄱ. A ㄴ. B\n㉮ 1 ㉯ 2 ㉴ 3 ㉵ 4",
        1,
        [],
    )
    question = questions[0]
    payload = json.loads(question.format_json)
    assert question.text == "다음 <보기>에서 옳은 것은?"
    assert payload["tables"][0]["rows"] == [["<보기>\nㄱ. A ㄴ. B"]]
```

- [ ] **Step 2: Run the single parser test**

Expected: FAIL because the flattened `<보기>` block remains in `question.text`.

- [ ] **Step 3: Apply the converter after format construction**

```python
q_text, q_format_json, _ = promote_view_block(
    formatted_question.text,
    q_format_json,
)
questions.append(Question(number=q_num, text=q_text, format_json=q_format_json, ...))
```

Keep geometric-table removal before this call so a view block already represented by an extracted table cannot be duplicated.

- [ ] **Step 4: Run `pytest tests/test_question_parser_cover.py tests/test_parser_2025.py -q`**

Expected: PASS.

---

### Task 3: Editor auto-promotion and table lifecycle controls

**Files:**
- Modify: `src/gui/interface/editor.py:1-520`
- Modify: `tests/test_editor_table_format.py`
- Modify: `tests/test_editor_layout.py`

**Interfaces:**
- Consumes: all three functions from Task 1.
- Produces: always-visible `btnAddQuestionTable`, dynamic table cards, `_add_question_table()`, `_delete_table(owner, table_id, confirm=True)`, and `_rebuild_table_cards()`.

- [ ] **Step 1: Add failing editor tests**

```python
def test_plain_view_question_is_promoted_when_editor_opens():
    data = _editor_data()
    data["question_text"] = "질문? <보기> ① A ② B"
    data["question_format_json"] = None
    editor = QuestionEditor(question_data=data, subject_options=SUBJECTS)
    saved = editor.get_data()
    assert saved["question_text"] == "질문?"
    assert json.loads(saved["question_format_json"])["tables"][0]["rows"][0][0].startswith("<보기>")

def test_selected_question_text_moves_into_new_table():
    editor = QuestionEditor(question_data=_editor_data(), subject_options=SUBJECTS)
    editor.questionText.setPlainText("질문 앞 선택 내용 뒤")
    cursor = editor.questionText.textCursor()
    cursor.setPosition(5)
    cursor.setPosition(10, cursor.KeepAnchor)
    editor.questionText.setTextCursor(cursor)
    editor._add_question_table()
    saved = editor.get_data()
    assert "선택 내용" not in saved["question_text"]
    assert json.loads(saved["question_format_json"])["tables"][-1]["rows"] == [["선택 내용"]]

def test_deleting_table_restores_cell_text():
    editor = QuestionEditor(question_data=_view_editor_data(), subject_options=SUBJECTS)
    assert editor._delete_table("question", "view-table-1", confirm=False)
    saved = editor.get_data()
    assert "<보기>" in saved["question_text"]
    assert not json.loads(saved["question_format_json"]).get("tables")
```

- [ ] **Step 2: Run focused editor tests**

Expected: FAIL because add/delete/rebuild controls do not exist and plain text is not promoted.

- [ ] **Step 3: Auto-promote before creating the question text widget**

```python
promoted_text, promoted_json, _ = promote_view_block(
    self.question_data.get("question_text", ""),
    self.question_data.get("question_format_json"),
)
self.question_data["question_text"] = promoted_text
self.question_data["question_format_json"] = promoted_json
```

- [ ] **Step 4: Make the table section dynamic and add the toolbar action**

Create `btnAddQuestionTable = PushButton("발문 표 추가")`, place it after the underline/overline buttons, and keep the table section visible even when no cards exist. `_rebuild_table_cards()` must remove old card widgets with `deleteLater()`, recreate cards from current payloads, show a compact one-cell preview, and include `구조 보기`, `표 편집`, `표 삭제`, and render-mode controls.

- [ ] **Step 5: Implement add and lossless delete**

```python
def _add_question_table(self):
    cursor = self.questionText.textCursor()
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    cell_text = cursor.selectedText().replace("\u2029", "\n") or "<보기>\n"
    if cursor.hasSelection():
        cursor.removeSelectedText()
    self.question_data["question_format_json"] = add_one_cell_table(
        self.questionText.toPlainText(),
        self.question_data.get("question_format_json"),
        cell_text,
        start,
    )
    self._rebuild_table_cards()
```

For deletion, use `remove_table_and_restore`, update the owner text widget and owner format payload, then rebuild cards. The UI path asks for confirmation; tests call `confirm=False`.

- [ ] **Step 6: Run `pytest tests/test_editor_table_format.py tests/test_editor_layout.py -q`**

Expected: PASS.

---

### Task 4: Safe SQLite staging migration

**Files:**
- Create: `src/database/view_table_migration.py`
- Create: `scripts/promote_view_tables.py`
- Create: `tests/test_view_table_migration.py`

**Interfaces:**
- Produces: `build_view_table_staging(source_db: Path, staging_db: Path) -> ViewTableMigrationReport`, `validate_view_table_staging(source_db: Path, staging_db: Path) -> ViewTableMigrationReport`, and `replace_with_view_table_staging(source_db: Path, staging_db: Path, backup_dir: Path) -> ViewTableReplacementReceipt`.
- Consumes: `promote_view_block` from Task 1.

- [ ] **Step 1: Write failing staging, invariance, idempotence, and replacement tests**

```python
def test_staging_promotes_only_view_questions_and_preserves_other_columns(tmp_path):
    source = make_exam_db(tmp_path / "source.db", view_rows=2, normal_rows=1)
    report = build_view_table_staging(source, tmp_path / "staging.db")
    assert report.eligible_questions == 2
    assert report.promoted_questions == 2
    assert report.integrity_ok and report.foreign_keys_ok
    assert report.non_target_mismatches == 0

def test_migration_is_idempotent(tmp_path):
    source = make_exam_db(tmp_path / "source.db", view_rows=1)
    first = build_view_table_staging(source, tmp_path / "first.db")
    second = build_view_table_staging(first.staging_db, tmp_path / "second.db")
    assert second.promoted_questions == 0

def test_replacement_creates_valid_backup(tmp_path):
    source = make_exam_db(tmp_path / "source.db", view_rows=1)
    report = build_view_table_staging(source, tmp_path / "staging.db")
    receipt = replace_with_view_table_staging(source, report.staging_db, tmp_path / "backups")
    assert receipt.backup_path.is_file()
    assert receipt.mounted_sha256 == receipt.staging_sha256
```

- [ ] **Step 2: Run `pytest tests/test_view_table_migration.py -q`**

Expected: FAIL because the migration module does not exist.

- [ ] **Step 3: Implement backup-based staging and validation**

Use SQLite `Connection.backup()` to create staging, `BEGIN IMMEDIATE` for updates, and `PRAGMA integrity_check` / `foreign_key_check`. Compare table row counts and every question column except `question_text` and `question_format_json`; compare every `question_choices` row byte-for-byte. Reconstruct each promoted source row from the staging prefix plus the stored one-cell text and require normalized equality with the original.

- [ ] **Step 4: Implement fail-closed replacement and CLI**

```python
if args.replace:
    receipt = replace_with_view_table_staging(
        Path(args.db),
        Path(args.staging_db),
        Path(args.backup_dir),
    )
```

The replacement function revalidates staging, creates a timestamped SQLite backup, copies staging to a sibling temporary file, checks its hash and integrity, and uses `os.replace`. Write a JSON report containing counts, paths, and SHA-256 values.

- [ ] **Step 5: Run migration tests**

Expected: PASS.

---

### Task 5: DOCX regression and actual database rollout

**Files:**
- Modify: `tests/test_docx_exporter.py`
- Runtime output only: `tmp/view_table_migration_*/`
- Runtime backup only: `data/backups/`
- Runtime database only: `data/exam_bank.db`

**Interfaces:**
- Consumes: the existing `DocxExporter` anchored-table path and Task 4 CLI.
- Produces: verified one-cell DOCX output and a migrated current database.

- [ ] **Step 1: Add a failing/no-regression OpenXML test**

```python
def test_promoted_view_block_exports_once_as_one_cell_table(tmp_path):
    text, encoded, _ = promote_view_block("질문? <보기> ① A ② B")
    output = tmp_path / "view.docx"
    DocxExporter().export("보기 표", [_question(text, encoded)], str(output))
    document = Document(output)
    assert len(document.tables) == 1
    assert len(document.tables[0].rows) == 1
    assert len(document.tables[0].columns) == 1
    all_text = "\n".join(p.text for p in document.paragraphs) + document.tables[0].cell(0, 0).text
    assert all_text.count("<보기>") == 1
```

- [ ] **Step 2: Run the DOCX test and confirm current anchored rendering behavior**

Expected: PASS after Tasks 1–2; if it fails, fix only the anchored native-table fallback needed for this behavior and rerun.

- [ ] **Step 3: Run focused and complete automated tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_view_table.py tests/test_question_parser_cover.py tests/test_editor_table_format.py tests/test_view_table_migration.py tests/test_docx_exporter.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests PASS with no collection errors.

- [ ] **Step 4: Build and inspect the real staging database without replacement**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\promote_view_tables.py --db data\exam_bank.db --staging-db tmp\view_table_migration\exam_bank.staging.db --report tmp\view_table_migration\report.json
```

Expected report values: `eligible_questions = 75`, `promoted_questions = 75`, `non_target_mismatches = 0`, `integrity_ok = true`, and `foreign_keys_ok = true`.

- [ ] **Step 5: Verify idempotence against the real staging DB**

Run the same command with the first staging DB as `--db` and a second staging path. Expected: `promoted_questions = 0` and all validation fields remain successful.

- [ ] **Step 6: Replace the current database with backup and smoke-test repository reads**

Run:

```powershell
.\.venv\Scripts\python.exe scripts\promote_view_tables.py --db data\exam_bank.db --staging-db tmp\view_table_migration\exam_bank.staging.db --report tmp\view_table_migration\replacement.json --backup-dir data\backups --replace
.\.venv\Scripts\python.exe scripts\validate_table_payloads.py --db data\exam_bank.db
```

Expected: backup path exists, mounted/staging hashes match, 75 native-ready view tables are present, and the repository can read the migrated questions.

- [ ] **Step 7: Review worktree scope**

Run `git status --short` and `git diff --check`. Expected: only planned source/tests/docs changes plus the pre-existing untracked ZIP; ignored runtime DB, backup, report, and staging artifacts must not be staged.
