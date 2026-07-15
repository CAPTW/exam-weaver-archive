# Mounted Practice Repository Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 문제 풀이 tab query every enabled Mounted DB while persisting Mounted practice attempts only in the writable `user_workspace` Mount.

**Architecture:** `PracticeInterface` consumes a repository through public practice APIs instead of opening SQLite connections. `ExamRepository` keeps the legacy mock-exam tables, while `MountedExamRepository` queries namespaced source rows and delegates portable attempt persistence to a focused `PracticeAttemptStore` attached to `user_workspace`.

**Tech Stack:** Python 3.14, PyQt5/qfluentwidgets, SQLite, pytest.

## Global Constraints

- Never write practice records or question changes to the source Mounted DB.
- Preserve `mount_id::local_id` identity across exam, subject, and question selections.
- Require a writable `user_workspace` Mount before starting a Mounted practice attempt.
- Preserve existing single-DB `mock_exams`, `mock_exam_questions`, and `exam_results` behavior.
- Defer Repository replacement while a quiz is active; apply it when returning to setup.
- Do not stage or modify `exam_bank.maritime_domain.20260705_175510.examdb.zip`.

---

### Task 1: Portable practice-attempt store

**Files:**
- Create: `src/database/practice_attempts.py`
- Create: `tests/test_practice_attempt_store.py`

**Interfaces:**
- Consumes: a writable SQLite path and question/result dictionaries produced by `PracticeInterface.evaluate_answers`.
- Produces: `PracticeAttemptStore(db_path)`, `create_attempt(...) -> int`, and `complete_attempt(...) -> None`.

- [ ] **Step 1: Write the failing storage test**

```python
def test_practice_attempt_store_persists_snapshot_answers_and_subject_results(tmp_path):
    store = PracticeAttemptStore(tmp_path / "workspace.db")
    questions = [{
        "id": "source::7",
        "mounted_subject_code": "source::navigation",
        "subject_name": "항해학",
        "question_text": "발문",
        "correct_answer": 2,
        "choices": [{"number": 1, "text": "가"}, {"number": 2, "text": "나"}],
    }]
    attempt_id = store.create_attempt(
        mount_id="source",
        mount_label="원본 DB",
        exam_code="source::해양경찰 항해학",
        exam_name="해양경찰 항해학",
        questions=questions,
    )
    result = {
        "total": 1,
        "correct": 1,
        "score": 100.0,
        "details": [{
            "question": questions[0],
            "selected": 2,
            "correct_answer": 2,
            "is_correct": True,
        }],
        "subject_stats": {
            "source::navigation": {"subject": "항해학", "total": 1, "correct": 1}
        },
    }
    store.complete_attempt(attempt_id, result=result, duration_seconds=12)

    with sqlite3.connect(tmp_path / "workspace.db") as conn:
        assert conn.execute(
            "SELECT status, total_questions, correct_count, score FROM practice_attempts"
        ).fetchone() == ("completed", 1, 1, 100.0)
        assert conn.execute(
            "SELECT source_question_id, selected_answer, is_correct "
            "FROM practice_attempt_questions"
        ).fetchone() == ("source::7", 2, 1)
        assert conn.execute(
            "SELECT source_subject_id, total_questions, correct_count "
            "FROM practice_attempt_subject_results"
        ).fetchone() == ("source::navigation", 1, 1)
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest -q tests/test_practice_attempt_store.py`

Expected: collection fails because `src.database.practice_attempts` does not exist.

- [ ] **Step 3: Implement the store and schema**

Create `PracticeAttemptStore` with these exact public signatures:

```python
class PracticeAttemptStore:
    def __init__(self, db_path: str | Path): ...

    def create_attempt(
        self,
        *,
        mount_id: str,
        mount_label: str,
        exam_code: str,
        exam_name: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> int: ...

    def complete_attempt(
        self,
        attempt_id: int,
        *,
        result: Mapping[str, Any],
        duration_seconds: int,
    ) -> None: ...
```

The constructor opens no long-lived connection. Each public method opens `sqlite3.connect(self.db_path)`, enables foreign keys, executes `CREATE TABLE IF NOT EXISTS` for `practice_attempts`, `practice_attempt_questions`, and `practice_attempt_subject_results`, and performs its writes in one connection transaction. Serialize the full question dictionary with `json.dumps(..., ensure_ascii=False, default=str)`.

- [ ] **Step 4: Run the storage tests and verify GREEN**

Run: `python -m pytest -q tests/test_practice_attempt_store.py`

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```powershell
git add src/database/practice_attempts.py tests/test_practice_attempt_store.py
git commit -m "feat: store portable practice attempts"
```

### Task 2: Public practice APIs on the single-DB Repository

**Files:**
- Modify: `src/database/repository.py`
- Modify: `src/gui/interface/practice.py`
- Modify: `tests/test_practice_interface.py`

**Interfaces:**
- Consumes: `evaluate_answers(questions, answers) -> dict`.
- Produces on `ExamRepository`: `first_exam_code_with_questions()`, `create_practice_attempt(...)`, and `complete_practice_attempt(...)`.

- [ ] **Step 1: Write failing API tests**

Add tests proving that `PracticeInterface` no longer needs `_get_connection()` and that the legacy tables receive the same rows:

```python
def test_exam_repository_public_practice_api_preserves_legacy_tables(repo, sample_metadata, sample_question):
    question = repo.get_questions_with_choices(exam_code="3급기관사", limit=1)[0]
    attempt_id = repo.create_practice_attempt(
        exam_code="3급기관사",
        exam_name="3급 기관사",
        questions=[question],
    )
    result = evaluate_answers([question], {question["id"]: question["correct_answer"]})
    repo.complete_practice_attempt(
        attempt_id,
        result=result,
        duration_seconds=7,
    )
    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_exams").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM mock_exam_questions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM exam_results").fetchone()[0] == 2
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m pytest -q tests/test_practice_interface.py::test_exam_repository_public_practice_api_preserves_legacy_tables`

Expected: FAIL with missing `create_practice_attempt`.

- [ ] **Step 3: Move direct SQL behind repository methods**

Implement:

```python
def first_exam_code_with_questions(self) -> Optional[str]: ...

def create_practice_attempt(
    self,
    *,
    exam_code: str,
    exam_name: str,
    questions: Sequence[Mapping[str, Any]],
) -> int: ...

def complete_practice_attempt(
    self,
    attempt_id: int,
    *,
    result: Mapping[str, Any],
    duration_seconds: int,
) -> None: ...
```

Move the SQL currently in `PracticeInterface._first_exam_code_with_questions`, `_create_mock_exam_record`, and `save_practice_result` into these methods without changing table semantics. Keep `save_practice_result` as a compatibility wrapper that evaluates answers, calls `repo.complete_practice_attempt`, and returns the result dictionary.

- [ ] **Step 4: Run single-DB practice tests and verify GREEN**

Run: `python -m pytest -q tests/test_practice_interface.py tests/test_explanation_workflow.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/database/repository.py src/gui/interface/practice.py tests/test_practice_interface.py
git commit -m "refactor: expose practice persistence API"
```

### Task 3: Mounted Repository routing to `user_workspace`

**Files:**
- Modify: `experiments/db_mount_prototype/mount_repo.py`
- Modify: `tests/test_db_mount_prototype.py`

**Interfaces:**
- Consumes: `PracticeAttemptStore` from Task 1 and the public practice signatures from Task 2.
- Produces: Mounted implementations that validate namespaced identities and never write the source Mount.

- [ ] **Step 1: Write failing Mounted persistence tests**

```python
def test_mounted_practice_attempt_is_saved_only_in_user_workspace(tmp_path):
    mounted, source_db, workspace_db = _make_mounted_repository_with_user_workspace(tmp_path)
    question = mounted.get_questions_with_choices(
        exam_code="maritime_all::3급기관사", limit=1
    )[0]
    source_before = source_db.read_bytes()
    attempt_id = mounted.create_practice_attempt(
        exam_code="maritime_all::3급기관사",
        exam_name="3급 기관사",
        questions=[question],
    )
    result = evaluate_answers([question], {question["id"]: question["correct_answer"]})
    mounted.complete_practice_attempt(attempt_id, result=result, duration_seconds=5)

    assert source_db.read_bytes() == source_before
    with sqlite3.connect(workspace_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM practice_attempts").fetchone()[0] == 1
        assert conn.execute(
            "SELECT source_question_id FROM practice_attempt_questions"
        ).fetchone()[0].startswith("maritime_all::")
```

Also add a test where no writable `user_workspace` exists and assert `create_practice_attempt` raises `ValueError` before any DB bytes change.

- [ ] **Step 2: Run the Mounted tests and verify RED**

Run: `python -m pytest -q tests/test_db_mount_prototype.py -k practice_attempt`

Expected: FAIL with missing Mounted practice methods.

- [ ] **Step 3: Implement Mounted practice methods**

Add `first_exam_code_with_questions()` returning the first code from `get_filter_options()["exams"]`. Define `@dataclass(frozen=True) class MountedPracticeAttempt` with `workspace_path: Path` and `attempt_id: int`. In `create_practice_attempt`, split the namespaced exam code, verify every question has the same `mount_id`, resolve `_manual_write_mount()`, call `PracticeAttemptStore(workspace.path).create_attempt(...)`, and return `MountedPracticeAttempt(workspace.path, attempt_id)`. `complete_practice_attempt` must require that token and reopen the exact workspace path recorded in it, so integer IDs from different workspace DBs cannot be confused.

Group Mounted subject statistics by `question.get("mounted_subject_code") or question.get("exam_subject_id")` so subject IDs remain namespaced.

- [ ] **Step 4: Run Mounted repository tests and verify GREEN**

Run: `python -m pytest -q tests/test_db_mount_prototype.py tests/test_practice_attempt_store.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add experiments/db_mount_prototype/mount_repo.py tests/test_db_mount_prototype.py
git commit -m "feat: route mounted practice results to workspace"
```

### Task 4: Repository-injected Practice UI

**Files:**
- Modify: `src/gui/interface/practice.py`
- Create: `tests/test_mounted_practice.py`
- Modify: `tests/test_practice_interface.py`

**Interfaces:**
- Consumes: common query and practice APIs from Tasks 2 and 3.
- Produces: `PracticeInterface(db_path=None, parent=None, repository=None)` and `set_repository(repository)`.

- [ ] **Step 1: Write failing UI tests**

```python
def test_practice_interface_lists_namespaced_mounted_exams(tmp_path):
    repository, _source_db, _workspace_db = _mounted_practice_fixture(tmp_path)
    widget = PracticeInterface(repository=repository)
    labels = [widget.examFilter.itemText(i) for i in range(widget.examFilter.count())]
    values = [widget.examFilter.itemData(i) for i in range(widget.examFilter.count())]
    assert any("Maritime ·" in label for label in labels)
    assert "maritime_all::3급기관사" in values

def test_practice_interface_defers_repository_swap_during_active_quiz(tmp_path):
    first, *_ = _mounted_practice_fixture(tmp_path)
    second, *_ = _second_mounted_practice_fixture(tmp_path)
    widget = PracticeInterface(repository=first)
    widget.questions = [{"id": "first::1"}]
    widget.set_repository(second)
    assert widget.repo is first
    widget.reset_to_setup()
    assert widget.repo is second
```

Add a submission failure test whose Repository raises from `complete_practice_attempt`; assert `results_revealed` remains false, the quiz page remains active, answers remain unchanged, and an error InfoBar is requested.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `python -m pytest -q tests/test_mounted_practice.py`

Expected: constructor rejects `repository=` or dropdown lacks Mounted labels.

- [ ] **Step 3: Implement injection, labels, and deferred refresh**

Use this constructor behavior:

```python
def __init__(self, db_path=None, parent=None, repository=None):
    super().__init__(parent)
    self.repo = repository or ExamRepository(db_path)
    self.pending_repository = None
```

`set_repository` immediately applies and calls `load_options()` only when `self.questions` is empty; otherwise it stores `pending_repository`. `reset_to_setup()` clears the active state, applies the pending Repository, rebuilds `QuestionValidator`, and reloads filters. Replace UI direct SQL with the public methods from Task 2. Format Mounted exam labels from `mount_label` and `local_code`; preserve existing labels for single DB rows. Wrap `complete_practice_attempt` in `submit_exam()` with the same UI error boundary used by `start_quiz`; on failure show `InfoBar.error`, leave the quiz state and answers untouched, and return before rendering results.

- [ ] **Step 4: Run all practice UI tests and verify GREEN**

Run: `python -m pytest -q tests/test_mounted_practice.py tests/test_practice_interface.py tests/test_explanation_workflow.py`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/gui/interface/practice.py tests/test_mounted_practice.py tests/test_practice_interface.py
git commit -m "feat: use mounted repository in practice tab"
```

### Task 5: MainWindow wiring and complete regression verification

**Files:**
- Modify: `src/gui/main.py`
- Modify: `tests/test_main_window_layout.py`
- Modify: `tests/test_mounted_practice.py`

**Interfaces:**
- Consumes: `PracticeInterface(repository=...)` and `set_repository(repository)` from Task 4.
- Produces: one Repository instance shared by problem management and problem practice, refreshed from `mountsChanged`.

- [ ] **Step 1: Write the failing MainWindow wiring test**

```python
def test_main_window_passes_and_refreshes_question_repository_for_practice():
    source = gui_main.__loader__.get_source(gui_main.__name__)
    assert "PracticeInterface(self.db_path, self, repository=question_repository)" in source
    assert "self.practice_interface.set_repository(repository)" in source
```

Add a read-only actual-manifest regression test that compares `MountedExamRepository.get_filter_options()` with `PracticeInterface(repository=mounted).examFilter` and asserts all Mounted exam codes are present.

- [ ] **Step 2: Run wiring tests and verify RED**

Run: `python -m pytest -q tests/test_main_window_layout.py tests/test_mounted_practice.py`

Expected: FAIL because MainWindow still constructs `PracticeInterface(self.db_path, self)` and refreshes only the browser.

- [ ] **Step 3: Wire the shared Repository**

Construct the practice interface with `repository=question_repository`, then call both `browser_interface.set_repository(repository)` and `practice_interface.set_repository(repository)` in `refresh_question_repository()`.

- [ ] **Step 4: Run targeted regression tests**

Run: `python -m pytest -q tests/test_main_window_layout.py tests/test_mounted_practice.py tests/test_practice_interface.py tests/test_db_mount_prototype.py tests/test_practice_attempt_store.py`

Expected: all tests pass.

- [ ] **Step 5: Run source-tree verification**

Run: `python -m pytest -q`

Expected: all tests pass with only existing Pillow deprecation warnings.

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 6: Commit the integration**

```powershell
git add src/gui/main.py tests/test_main_window_layout.py tests/test_mounted_practice.py
git commit -m "feat: refresh mounted practice repository"
```
