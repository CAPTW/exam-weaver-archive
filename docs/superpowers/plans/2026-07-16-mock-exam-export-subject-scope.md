# Mock Exam Export Subject Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the Korean export workflow to `모의고사 출력` and let users apply one question count only to rows whose `사용` checkbox is already selected.

**Architecture:** Keep the existing `menu.export` route key and export request pipeline unchanged. Add one UI action and one bounded `ExportInterface` method that operates only on the existing `subjectSelectionRows` checkbox/spin references, while `_update_selection_summary()` owns both summary text and button enabled state.

**Tech Stack:** Python 3.14, PyQt5, QFluentWidgets, pytest, JSON menu packs

## Global Constraints

- Display `모의고사 출력` in the Korean menu and `모의고사 출력 (DOCX)` as the page title.
- Display `Mock Exam Export` in the bundled English menu pack.
- Keep the stable route key `menu.export` and external menu-pack compatibility.
- `전체 과목에 적용` continues to select every row and set every count.
- `선택한 과목에만 적용` changes only already-checked rows and never changes unchecked rows.
- Keep single-exam, multi-exam, year, hashtag, deduplication, and DOCX generation logic unchanged.
- Never stage or modify `exam_bank.maritime_domain.20260705_175510.examdb.zip`.

---

### Task 1: Rename the mock-exam export workflow

**Files:**
- Modify: `src/gui/menu_language.py`
- Modify: `assets/language_packs/menu/ko.json`
- Modify: `assets/language_packs/menu/en.json`
- Modify: `src/gui/main.py`
- Modify: `src/gui/interface/export.py`
- Test: `tests/test_menu_language.py`
- Test: `tests/test_main_window_layout.py`
- Test: `tests/test_export_interface.py`

**Interfaces:**
- Consumes: stable menu route `menu.export`
- Produces: Korean label `모의고사 출력`, English label `Mock Exam Export`, page title `모의고사 출력 (DOCX)`

- [x] **Step 1: Write failing copy tests**

Update the fallback test and add explicit bundled-pack and UI assertions:

```python
def test_builtin_export_menu_labels_use_mock_exam_wording():
    packs, warnings = discover_menu_language_packs(PROJECT_ROOT)

    assert warnings == []
    assert menu_text(packs["ko"], "menu.export") == "모의고사 출력"
    assert menu_text(packs["en"], "menu.export") == "Mock Exam Export"


def test_main_window_declares_mock_exam_export_navigation_copy():
    source = gui_main.__loader__.get_source(gui_main.__name__)

    assert 'self.export_interface, FIF.PRINT, "모의고사 출력"' in source


def test_export_interface_uses_mock_exam_title(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.titleLabel.text() == "모의고사 출력 (DOCX)"
```

Change the external fallback expectation to:

```python
assert menu_text(packs["ja"], "menu.export") == "모의고사 출력"
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_menu_language.py tests/test_main_window_layout.py tests/test_export_interface.py -q
```

Expected: failures show the old `시험지 출력`, `Export Exam`, and `시험지 출력 (DOCX)` strings.

- [x] **Step 3: Apply the new menu and page wording**

Use these exact values without changing the route key:

```python
# src/gui/menu_language.py Korean fallback
"menu.export": "모의고사 출력",

# src/gui/menu_language.py English fallback
"menu.export": "Mock Exam Export",

# src/gui/main.py navigation registration
self.export_interface, FIF.PRINT, "모의고사 출력",

# src/gui/interface/export.py
self.titleLabel = SubtitleLabel("모의고사 출력 (DOCX)", self)
```

Set the bundled JSON values to the same Korean and English strings.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the Task 1 command again.

Expected: all menu, main-window, and export-interface tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/menu_language.py assets/language_packs/menu/ko.json assets/language_packs/menu/en.json src/gui/main.py src/gui/interface/export.py tests/test_menu_language.py tests/test_main_window_layout.py tests/test_export_interface.py
git commit -m "feat: rename mock exam export workflow"
```

---

### Task 2: Apply the bulk count to selected subjects only

**Files:**
- Modify: `src/gui/interface/export.py`
- Test: `tests/test_export_interface.py`

**Interfaces:**
- Consumes: `ExportInterface.subjectSelectionRows: list[dict]`, `ExportInterface.allSubjectCountSpin`
- Produces: `ExportInterface.btnApplySelectedSubjects: PushButton`
- Produces: `ExportInterface._apply_selected_subject_count(count: int | bool | None = None) -> int`

- [x] **Step 1: Write failing behavior and enabled-state tests**

```python
def test_apply_selected_subject_count_changes_checked_rows_only():
    interface = ExportInterface.__new__(ExportInterface)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 1, checked=True),
        _subject_request('engine2', '기관2', 2, checked=False),
        _subject_request('engine3', '기관3', 3, checked=True),
    ]

    applied = interface._apply_selected_subject_count(25)

    assert applied == 2
    assert [row['checkbox'].isChecked() for row in interface.subjectSelectionRows] == [True, False, True]
    assert [row['count_spin'].value() for row in interface.subjectSelectionRows] == [25, 2, 25]


def test_apply_selected_subject_count_uses_spin_value_from_button_signal():
    interface = ExportInterface.__new__(ExportInterface)
    interface.allSubjectCountSpin = _Spin(12)
    interface.subjectSelectionRows = [
        _subject_request('engine1', '기관1', 1, checked=True),
        _subject_request('engine2', '기관2', 2, checked=False),
    ]

    assert interface._apply_selected_subject_count(False) == 1
    assert [row['count_spin'].value() for row in interface.subjectSelectionRows] == [12, 2]


def test_selected_subject_apply_button_tracks_checkbox_state(repo):
    interface = ExportInterface(repo.db_path)

    assert interface.btnApplySelectedSubjects.text() == "선택한 과목에만 적용"
    assert interface.btnApplySelectedSubjects.isEnabled() is False

    interface._add_subject_selection_row(
        {'code': 'engine1', 'name_ko': '기관1'},
        {'code': '3급기관사', 'name': '3급기관사'},
        False,
    )
    interface.subjectSelectionRows[0]['checkbox'].setChecked(True)
    APP.processEvents()
    assert interface.btnApplySelectedSubjects.isEnabled() is True
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_apply_selected_subject_count_changes_checked_rows_only tests/test_export_interface.py::test_apply_selected_subject_count_uses_spin_value_from_button_signal tests/test_export_interface.py::test_selected_subject_apply_button_tracks_checkbox_state -q
```

Expected: failures report the missing method and button.

- [x] **Step 3: Add the selected-subject button and minimal behavior**

Add the button beside the existing all-subject action:

```python
self.btnApplySelectedSubjects = PushButton("선택한 과목에만 적용", self)
self._apply_input_height(self.btnApplySelectedSubjects)
self.btnApplySelectedSubjects.setFixedWidth(190)
self.btnApplySelectedSubjects.setEnabled(False)
self.btnApplySelectedSubjects.clicked.connect(self._apply_selected_subject_count)
self.randomSubjectBulkLayout.addWidget(self.btnApplySelectedSubjects)
```

Implement the bounded mutation:

```python
def _apply_selected_subject_count(self, count=None):
    if count is None or isinstance(count, bool):
        count = int(self.allSubjectCountSpin.value())
    applied = 0
    for row in self.__dict__.get('subjectSelectionRows', []):
        checkbox = row.get('checkbox')
        count_spin = row.get('count_spin')
        if not checkbox or not checkbox.isChecked() or count_spin is None:
            continue
        count_spin.setValue(count)
        applied += 1
    self._update_selection_summary()
    return applied
```

At the end of `_update_selection_summary()`, synchronize enabled state without breaking `__new__` unit tests:

```python
button = self.__dict__.get('btnApplySelectedSubjects')
if button is not None:
    button.setEnabled(selected > 0)
```

- [x] **Step 4: Run selected-subject and existing bulk-action tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py -q
```

Expected: the new tests and existing `_apply_all_subject_count` regressions pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/interface/export.py tests/test_export_interface.py
git commit -m "feat: apply counts to selected export subjects"
```

---

### Task 3: Verify the integrated mock-exam export workflow

**Files:**
- Modify: `docs/superpowers/plans/2026-07-16-mock-exam-export-subject-scope.md`

**Interfaces:**
- Consumes: completed Task 1 and Task 2 UI behavior
- Produces: fresh automated and launcher verification evidence

- [x] **Step 1: Run formatting and focused copy audit checks**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest tests/test_gui_copy_audit.py tests/test_menu_language.py tests/test_main_window_layout.py tests/test_export_interface.py tests/test_launchers.py -q
```

Expected: no whitespace errors and all focused tests pass.

- [x] **Step 2: Run the complete regression suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: zero failures.

- [x] **Step 3: Launch the current source build**

Run `Run_Latest_App.bat`, wait for the `기출문제 문제은행 관리자` window to respond, and close only the processes started by this smoke check.

Expected: the app opens from local `main`; the Korean navigation and page title show `모의고사 출력`; the two subject-count actions are adjacent and the selected-only action is disabled until a subject is checked.

- [x] **Step 4: Mark this plan complete and commit verification metadata**

Change every completed checkbox in this file from `[ ]` to `[x]`, then run:

```powershell
git add -- docs/superpowers/plans/2026-07-16-mock-exam-export-subject-scope.md
git commit -m "test: verify mock exam export subject controls"
```

## Execution Evidence

- Focused copy, menu, layout, export, and launcher regressions: `62 passed`.
- Full isolated-worktree suite: `784 passed, 3 skipped, 36 warnings`.
- Source launcher: `기출문제 문제은행 관리자` window opened and remained responsive.
- Formatting audit: `git diff --check` reported no errors after implementation.
