# Mounted Question Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Question Management aggregate all enabled mounted databases and route edits, explanation changes, and deletions to each question's owning database.

**Architecture:** Extend `MountedExamRepository` into the repository facade required by `BrowserInterface` and `QuestionValidator`. `MainWindow` selects that facade when the manifest is valid, retains the application-DB fallback, and refreshes the browser after persisted mount changes.

**Tech Stack:** Python 3, SQLite, PyQt5, qfluentwidgets, pytest

## Global Constraints

- Mounted writes require `mount_id::local_id`; never retry a failed mounted write against the application DB.
- The manifest `read_only` flag does not block Question Management customization.
- Disabled mounts cannot appear or receive writes.
- Missing, invalid, or empty manifests preserve single-database behavior.
- Preserve the untracked `exam_bank.maritime_domain.20260705_175510.examdb.zip`.

## File map

- `experiments/db_mount_prototype/mount_repo.py`: aggregate read correctness and write routing.
- `src/gui/interface/browser.py`: repository injection, mount labels, namespaced IDs, and write errors.
- `src/gui/interface/db_mount.py`: persisted-change signal.
- `src/gui/main.py`: repository selection, fallback, and refresh wiring.
- `tests/test_db_mount_prototype.py`: facade tests.
- `tests/test_mounted_browser.py`: mounted GUI tests.
- Existing browser, explanation, mount-interface, and main-window tests: compatibility coverage.

---

### Task 1: Mounted repository write routing

**Files:**
- Modify: `experiments/db_mount_prototype/mount_repo.py`
- Modify: `tests/test_db_mount_prototype.py`

**Interfaces:**
- Consumes: local-ID write methods on `ExamRepository`.
- Produces: `update_question(question_id, data)`, `update_question_explanation(question_id, explanation)`, `delete_question(question_id)`, and `delete_questions(question_ids)` on `MountedExamRepository`.

- [ ] **Step 1: Write failing direct-write tests**

Create two mounted DBs, mark one `read_only=True`, and use real repositories to assert:

```python
assert mounted.update_question("first::1", {**fields, "question_text": "수정됨"})
assert ExamRepository(str(first_db)).get_question(1)["question_text"] == "수정됨"
assert ExamRepository(str(second_db)).get_question(1)["question_text"] != "수정됨"
assert mounted.update_question_explanation("first::1", "사용자 해설")
assert ExamRepository(str(first_db)).get_question(1)["explanation"] == "사용자 해설"
assert mounted.delete_question("first::1")
assert ExamRepository(str(first_db)).get_question(1) is None
assert ExamRepository(str(second_db)).get_question(1) is not None
```

Add multi-mount bulk deletion and rejection cases for raw, unknown, disabled, and malformed IDs. Assert rejection leaves every DB unchanged.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_db_mount_prototype.py -k "write or delete or explanation" -v`

Expected: FAIL because mounted write methods are absent.

- [ ] **Step 3: Implement strict routing**

Add a resolver equivalent to:

```python
def _write_target(self, question_id):
    mount_id, local_id = split_namespaced_value(question_id)
    if mount_id is None:
        raise ValueError("mounted writes require a namespaced question id")
    mount = self._mounts_by_id.get(mount_id)
    if mount is None:
        raise ValueError(f"unknown or disabled mount: {mount_id}")
    try:
        return mount, int(local_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid local question id: {local_id}") from exc
```

Create an `ExamRepository(str(mount.path))` for writes regardless of `read_only`. Resolve every bulk ID before grouping and deleting, preventing partial deletion from invalid input. Let permission and SQLite exceptions propagate.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_db_mount_prototype.py tests/test_repository.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add -- experiments/db_mount_prototype/mount_repo.py tests/test_db_mount_prototype.py
git commit -m "feat: route mounted question writes"
```

### Task 2: Aggregate limit and lookup correctness

**Files:**
- Modify: `experiments/db_mount_prototype/mount_repo.py`
- Modify: `tests/test_db_mount_prototype.py`

**Interfaces:**
- Produces globally sorted/limited search results and fully namespaced lookup results.

- [ ] **Step 1: Write a failing global-limit test**

Put an older question in the first mount and a newer question in the second:

```python
rows = mounted.search_questions(limit=1)
assert len(rows) == 1
assert rows[0]["question_text"] == "newest"
assert rows[0]["id"].startswith("second::")
```

Extend lookup assertions for `mounted_exam_code`, `mounted_subject_code`, `mount_label`, and namespaced choice IDs.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_db_mount_prototype.py -k "global_limit or get_question" -v`

Expected: global limit fails because it is currently applied inside each mount query.

- [ ] **Step 3: Implement global limit**

Call `_search_questions_one(..., limit=None)` for each selected mount, merge, sort using `_question_sort_key`, and apply `questions[:limit]` only after sorting. Attach choices only for that final set.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/test_db_mount_prototype.py -v`

Expected: PASS.

```powershell
git add -- experiments/db_mount_prototype/mount_repo.py tests/test_db_mount_prototype.py
git commit -m "fix: apply mounted search limits globally"
```

### Task 3: Repository-driven Question Management UI

**Files:**
- Modify: `src/gui/interface/browser.py`
- Create: `tests/test_mounted_browser.py`
- Modify: `tests/test_browser_filters.py`
- Modify: `tests/test_explanation_workflow.py`

**Interfaces:**
- Consumes either repository facade.
- Produces `BrowserInterface(db_path=None, parent=None, repository=None)` and `set_repository(repository)`.

- [ ] **Step 1: Write failing mounted GUI tests**

Construct `BrowserInterface(repository=MountedExamRepository(manifest))`. Assert both mounts render with mount labels, filter values are namespaced, and `selected_question_ids()` returns `first::1` rather than coercing to `int`. Save an explanation to `second::1` and verify only the second file changes.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_mounted_browser.py tests/test_browser_filters.py tests/test_explanation_workflow.py -v`

Expected: FAIL because the browser constructs `ExamRepository` and coerces selected IDs.

- [ ] **Step 3: Inject and replace repositories**

Use this construction contract:

```python
def __init__(self, db_path=None, parent=None, repository=None):
    super().__init__(parent)
    if repository is None:
        if db_path is None:
            raise ValueError("db_path or repository is required")
        repository = ExamRepository(db_path)
    self.repo = repository
    self.validator = QuestionValidator(repository)
```

`set_repository` replaces `repo` and `validator`, clears explanation state and filter combos, then reloads. Preserve original ID types in checkbox properties and actions. Show `mount_label` in question info and in exam/subject option labels when present.

Wrap mounted write calls in `OSError`, `sqlite3.Error`, and `ValueError` handling. Show the mount label plus error text and never change repositories or retry.

- [ ] **Step 4: Verify GREEN and commit**

Run: `pytest tests/test_mounted_browser.py tests/test_browser_filters.py tests/test_explanation_workflow.py -v`

Expected: PASS.

```powershell
git add -- src/gui/interface/browser.py tests/test_mounted_browser.py tests/test_browser_filters.py tests/test_explanation_workflow.py
git commit -m "feat: manage mounted questions in browser"
```

### Task 4: Mount lifecycle refresh and safe fallback

**Files:**
- Modify: `src/gui/interface/db_mount.py`
- Modify: `src/gui/main.py`
- Modify: `tests/test_db_mount_interface.py`
- Modify: `tests/test_main_window_layout.py`
- Modify: `tests/test_mounted_browser.py`

**Interfaces:**
- Consumes `BrowserInterface.set_repository` and `MountedExamRepository`.
- Produces `DbMountInterface.mountsChanged = pyqtSignal()` and `MainWindow.refresh_question_repository()`.

- [ ] **Step 1: Write failing lifecycle tests**

Use `QSignalSpy` to assert saved selection, import, creation, and rename each emit once after persistence; unsaved checkbox changes emit zero times. Assert a valid manifest selects `MountedExamRepository`, while a removed/corrupt/empty manifest selects queryable `ExamRepository` fallback.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_db_mount_interface.py tests/test_main_window_layout.py tests/test_mounted_browser.py -k "signal or refresh or fallback" -v`

Expected: FAIL because the signal and refresh method are absent.

- [ ] **Step 3: Emit only persisted changes**

Declare `mountsChanged = pyqtSignal()` and emit after successful `save_mount_selection`, `_rename_mount`, `_create_user_database`, and `_import_database`. Do not emit from `refresh_mounts()`.

- [ ] **Step 4: Select and refresh repositories**

Implement equivalent logic:

```python
def _question_repository(self):
    manifest = Path(BASE_DIR) / "data" / "domain_dbs" / "mount_manifest.json"
    if manifest.exists():
        try:
            repo = MountedExamRepository(manifest)
            repo.init_database()
            return repo, None
        except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
            return ExamRepository(self.db_path), str(exc)
    return ExamRepository(self.db_path), None
```

Construct the browser with this repository, connect `mountsChanged` to `refresh_question_repository`, and show one mount-load error when falling back from invalid configuration.

- [ ] **Step 5: Verify GREEN and commit**

Run: `pytest tests/test_db_mount_interface.py tests/test_main_window_layout.py tests/test_mounted_browser.py -v`

Expected: PASS.

```powershell
git add -- src/gui/interface/db_mount.py src/gui/main.py tests/test_db_mount_interface.py tests/test_main_window_layout.py tests/test_mounted_browser.py
git commit -m "feat: refresh browser after mount changes"
```

### Task 5: Full verification

**Files:** Verify only.

- [ ] **Step 1: Run all tests**

Run: `pytest -q`

Expected: zero failures.

- [ ] **Step 2: Run offscreen GUI smoke check**

Run: `python -c "import os; os.environ['QT_QPA_PLATFORM']='offscreen'; from PyQt5.QtWidgets import QApplication; from src.gui.main import MainWindow; app=QApplication([]); window=MainWindow(); print(type(window.browser_interface.repo).__name__); window.close()"`

Expected: exit code 0 and a repository class name.

- [ ] **Step 3: Inspect final scope**

Run: `git status --short` and `git diff --stat 1e75fcf..HEAD`.

Expected: planned files only, plus the pre-existing untracked exam DB package.
