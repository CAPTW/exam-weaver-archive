# Multi-Exam DOCX Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to select subjects from different mounted exams, assign a count per subject, and export the selections as ordered sections in one DOCX using one shared year range and hashtag filter.

**Architecture:** Keep the existing single-exam path intact and add an explicit multi-exam mode to `ExportInterface`. The screen will materialize one row per exam-subject pair, carry each row's namespaced exam and subject codes into the existing group-aware selection pipeline, and pass ordered sections to the unchanged `DocxExporter`.

**Tech Stack:** Python 3, PyQt5/QFluentWidgets, mounted repository abstraction, python-docx, pytest.

## Global Constraints

- Multi-exam mode is off by default.
- Existing single-subject, whole-exam, and same-exam multi-subject behavior and filenames remain unchanged.
- All selected subjects share one year range and one hashtag filter.
- Every selected subject has an independent positive question count.
- Namespaced repository codes never enter filenames.
- Grouped questions remain atomic and logical duplicates are excluded across the whole DOCX.
- Do not add presets, per-row filters, or DOCX layout changes.
- Do not stage or modify `exam_bank.maritime_domain.20260705_175510.examdb.zip`.

## File Structure

- Modify `src/gui/interface/export.py`: mode UI, row model, validation, query routing, section metadata, title, and filename.
- Modify `tests/test_export_interface.py`: widget-mode and cross-exam export regression tests.
- Do not modify `src/exporter/docx.py`: it already renders ordered sections with continuous numbering.

---

### Task 1: Multi-Exam Mode and Global Exam-Subject Rows

**Files:**
- Modify: `src/gui/interface/export.py:39-230`
- Test: `tests/test_export_interface.py`

**Interfaces:**
- Consumes: `repository.get_filter_options()` and `repository.get_subject_options(exam_code)`.
- Produces: `multiExamModeCheck`, `examOptions`, `_is_multi_exam_mode()`, `_rebuild_subject_selection_rows()`, and row dictionaries with repository-facing exam and subject codes.

- [ ] **Step 1: Write the failing row-population test**

Add this shared stub and test to `tests/test_export_interface.py`:

```python
class _MultiExamRepository:
    def get_filter_options(self):
        return {
            'exams': [
                {'code': 'first::engineer', 'local_code': 'engineer',
                 'name': 'Engineer Exam', 'mount_label': 'First DB'},
                {'code': 'second::navigation', 'local_code': 'navigation',
                 'name': 'Navigation Exam', 'mount_label': 'Second DB'},
            ],
            'years': [2024, 2025],
        }

    def get_subject_options(self, exam_code):
        return {
            'first::engineer': [
                {'code': 'first::engine1', 'local_code': 'engine1',
                 'name_ko': 'Engine 1', 'mount_label': 'First DB'},
            ],
            'second::navigation': [
                {'code': 'second::nav1', 'local_code': 'nav1',
                 'name_ko': 'Navigation 1', 'mount_label': 'Second DB'},
            ],
        }[exam_code]


def test_multi_exam_mode_lists_subjects_from_every_exam():
    interface = ExportInterface(repository=_MultiExamRepository())

    interface.multiExamModeCheck.setChecked(True)

    assert interface.subjectSelectionTable.columnCount() == 5
    assert [
        interface.subjectSelectionTable.horizontalHeaderItem(index).text()
        for index in range(5)
    ] == ['Use', 'Database', 'Exam', 'Subject', 'Questions']
    assert [row['exam_code'] for row in interface.subjectSelectionRows] == [
        'first::engineer', 'second::navigation',
    ]
    assert [row['subject_code'] for row in interface.subjectSelectionRows] == [
        'first::engine1', 'second::nav1',
    ]
    assert not interface.examFilter.isEnabled()
    assert not interface.subjectFilter.isEnabled()
    assert not interface.randomCountSpin.isEnabled()
    interface.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: Verify the test fails for the missing mode control**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_multi_exam_mode_lists_subjects_from_every_exam -q
```

Expected: FAIL with missing `multiExamModeCheck`.

- [ ] **Step 3: Implement mode state and dynamic rows**

Create the checkbox in `init_ui()` before the bulk-count controls:

```python
self.multiExamModeCheck = QCheckBox('Combine subjects from multiple exams', self)
self.multiExamModeCheck.setChecked(False)
self.multiExamModeCheck.toggled.connect(self._on_multi_exam_mode_changed)
self.vBoxLayout.addWidget(self.multiExamModeCheck)
```

Cache exam dictionaries in `load_options()`:

```python
self.examOptions = [dict(exam) for exam in options.get('exams', [])]
self.examOptionsByCode = {exam['code']: exam for exam in self.examOptions}
```

Add these methods:

```python
def _is_multi_exam_mode(self):
    checkbox = self.__dict__.get('multiExamModeCheck')
    return bool(checkbox and checkbox.isChecked())

def _on_multi_exam_mode_changed(self, checked):
    multi_exam = bool(checked)
    self.examFilter.setEnabled(not multi_exam)
    self.subjectFilter.setEnabled(not multi_exam)
    self.randomCountSpin.setEnabled(not multi_exam)
    self._rebuild_subject_selection_rows()

def _configure_subject_selection_table(self, multi_exam):
    self.subjectSelectionTable.clear()
    headers = (
        ['Use', 'Database', 'Exam', 'Subject', 'Questions']
        if multi_exam
        else ['Use', 'Subject', 'Questions']
    )
    self.subjectSelectionTable.setColumnCount(len(headers))
    self.subjectSelectionTable.setHorizontalHeaderLabels(headers)
    self.subjectSelectionTable.setColumnWidth(0, 70)
    self.subjectSelectionTable.setColumnWidth(len(headers) - 1, 120)
    stretch_columns = (2, 3) if multi_exam else (1,)
    for column in stretch_columns:
        self.subjectSelectionTable.horizontalHeader().setSectionResizeMode(
            column, QHeaderView.Stretch
        )

def _rebuild_subject_selection_rows(self):
    if not hasattr(self, 'subjectSelectionTable'):
        return
    multi_exam = self._is_multi_exam_mode()
    self.subjectSelectionTable.setRowCount(0)
    self.subjectSelectionRows = []
    self._configure_subject_selection_table(multi_exam)
    if multi_exam:
        for exam in self.__dict__.get('examOptions', []):
            for subject in self.repo.get_subject_options(exam['code']):
                self._add_subject_selection_row(subject, exam, True)
        return
    exam_code = self.examFilter.currentData()
    exam = self.__dict__.get('examOptionsByCode', {}).get(exam_code)
    for subject in self.repo.get_subject_options(exam_code):
        self._add_subject_selection_row(subject, exam, False)
```

Change `_add_subject_selection_row` to accept `(subject, exam=None, multi_exam=False)`. For multi mode, put mount, plain exam, and plain subject labels in columns 1-3; for legacy mode keep the subject label in column 1. Store:

```python
{
    'exam_code': exam.get('code') if exam else None,
    'exam_name': exam.get('name') if exam else '',
    'subject_code': subject['code'],
    'code': subject['code'],
    'subject_name': subject.get('name_ko') or subject['code'],
    'name': subject.get('name_ko') or subject['code'],
    'mount_label': ((exam or {}).get('mount_label')
                    or subject.get('mount_label') or ''),
    'multi_exam': multi_exam,
    'checkbox': checkbox,
    'count_spin': count_spin,
}
```

Update `on_exam_changed()` to refresh the subject combo and call `_rebuild_subject_selection_rows()` once.

- [ ] **Step 4: Run focused and legacy UI tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_multi_exam_mode_lists_subjects_from_every_exam tests/test_export_interface.py::test_export_interface_uses_injected_repository_with_mount_labels tests/test_export_interface.py::test_export_interface_keeps_random_subject_section_visible_on_initial_window -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit the mode and row model**

```powershell
git add -- src/gui/interface/export.py tests/test_export_interface.py
git commit -m "feat: add multi-exam subject selection mode"
```

---

### Task 2: Request Identity, Title, and Filename

**Files:**
- Modify: `src/gui/interface/export.py:230-335`
- Test: `tests/test_export_interface.py`

**Interfaces:**
- Consumes: Task 1 row dictionaries.
- Produces: request dictionaries containing `exam_code`, `code`, `name`, `section_title`, and `count`; `_build_multi_exam_title()`; `_build_multi_exam_filename()`.

- [ ] **Step 1: Write failing identity tests**

Add `from datetime import date` and these tests:

```python
def test_multi_exam_selected_requests_keep_section_identity():
    interface = ExportInterface(repository=_MultiExamRepository())
    interface.multiExamModeCheck.setChecked(True)
    for row, count in zip(interface.subjectSelectionRows, (2, 3)):
        row['checkbox'].setChecked(True)
        row['count_spin'].setValue(count)

    requests, invalid = interface._selected_random_subject_requests()

    assert invalid == []
    assert requests == [
        {'exam_code': 'first::engineer', 'code': 'first::engine1',
         'name': 'Engine 1',
         'section_title': 'First DB · Engineer Exam · Engine 1',
         'count': 2},
        {'exam_code': 'second::navigation', 'code': 'second::nav1',
         'name': 'Navigation 1',
         'section_title': 'Second DB · Navigation Exam · Navigation 1',
         'count': 3},
    ]
    interface.deleteLater()
    APP.processEvents()


def test_multi_exam_title_and_filename_are_namespace_safe():
    interface = ExportInterface.__new__(ExportInterface)
    assert interface._build_multi_exam_title(date(2026, 7, 16)) == (
        '2026.07.16 Multi-exam mock exam'
    )
    assert interface._build_multi_exam_filename(2020, 2025, 50) == (
        'multi_exam_2020-2025_rand50.docx'
    )
```

- [ ] **Step 2: Verify missing metadata failures**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_multi_exam_selected_requests_keep_section_identity tests/test_export_interface.py::test_multi_exam_title_and_filename_are_namespace_safe -q
```

Expected: FAIL because requests lack `exam_code` and the metadata helpers are absent.

- [ ] **Step 3: Implement request and document metadata**

Add:

```python
@staticmethod
def _selection_section_title(mount_label, exam_name, subject_name):
    return ' · '.join(
        str(value).strip()
        for value in (mount_label, exam_name, subject_name)
        if str(value or '').strip()
    )

def _build_multi_exam_title(self, today=None):
    today = today or date.today()
    return f'{today:%Y.%m.%d} Multi-exam mock exam'

def _build_multi_exam_filename(self, year_from, year_to, total_count):
    year_part = str(year_from) if year_from == year_to else f'{year_from}-{year_to}'
    return f'multi_exam_{year_part}_rand{total_count}.docx'
```

In `_selected_random_subject_requests()`, keep the existing three-key legacy request shape. For `row.get('multi_exam')`, append:

```python
{
    'exam_code': row['exam_code'],
    'code': row['subject_code'],
    'name': row['subject_name'],
    'section_title': self._selection_section_title(
        row.get('mount_label'), row.get('exam_name'), row.get('subject_name')
    ),
    'count': count,
}
```

Use the same full section title in the invalid-count list.

- [ ] **Step 4: Run new and legacy request tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_multi_exam_selected_requests_keep_section_identity tests/test_export_interface.py::test_multi_exam_title_and_filename_are_namespace_safe tests/test_export_interface.py::test_apply_all_subject_count_selects_every_subject_with_same_count tests/test_export_interface.py::test_build_filename_uses_local_codes_for_mounted_filters -q
```

Expected: 4 passed.

- [ ] **Step 5: Commit request identity**

```powershell
git add -- src/gui/interface/export.py tests/test_export_interface.py
git commit -m "feat: preserve multi-exam export identity"
```

---

### Task 3: Cross-Exam Query Routing and Global Deduplication

**Files:**
- Modify: `src/gui/interface/export.py:333-525`
- Test: `tests/test_export_interface.py`

**Interfaces:**
- Consumes: Task 2 request dictionaries.
- Produces: `export_docx()` queries each row's exam and subject and emits ordered, globally deduplicated sections.

- [ ] **Step 1: Write the failing cross-exam routing test**

Add this helper:

```python
def _multi_exam_subject_request(exam_code, exam_name, subject_code,
                                subject_name, mount_label, count):
    return {
        'exam_code': exam_code, 'exam_name': exam_name,
        'subject_code': subject_code, 'code': subject_code,
        'subject_name': subject_name, 'name': subject_name,
        'mount_label': mount_label, 'multi_exam': True,
        'checkbox': _Check(True), 'count_spin': _Spin(count),
}
```

Add these test helpers and the routing test:

```python
def _multi_exam_export_interface(rows):
    interface = ExportInterface.__new__(ExportInterface)
    interface.multiExamModeCheck = _Check(True)
    interface.examFilter = _Combo(None, '')
    interface.yearFromFilter = _Combo(2024, '2024')
    interface.yearToFilter = _Combo(2025, '2025')
    interface.subjectFilter = _Combo(None, 'All subjects')
    interface.tagFilter = _Line('#safety')
    interface.randomCountSpin = _Spin(0)
    interface.shuffleChoices = _Check(False)
    interface.subjectSelectionRows = rows
    return interface


def _eligible_export_question(question_id, text, year=2025):
    return {
        'id': question_id,
        'year': year,
        'question_text': text,
        'choices': [],
        'correct_answer': 1,
    }


class _AlwaysEligibleValidator:
    def is_random_eligible(self, _question):
        return True


def test_export_docx_combines_subjects_from_different_exams(monkeypatch):
    interface = _multi_exam_export_interface([
        _multi_exam_subject_request(
            'first::engineer', 'Engineer Exam',
            'first::engine1', 'Engine 1', 'First DB', 1,
        ),
        _multi_exam_subject_request(
            'second::navigation', 'Navigation Exam',
            'second::nav1', 'Navigation 1', 'Second DB', 1,
        ),
    ])
    captured = {'calls': []}

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            captured['calls'].append(kwargs)
            if kwargs['exam_code'] == 'first::engineer':
                return [_eligible_export_question(
                    'first::1', 'shared logical question', 2024,
                )]
            return [
                _eligible_export_question(
                    'second::1', 'shared logical question', 2025,
                ),
                _eligible_export_question(
                    'second::2', 'navigation replacement question', 2025,
                ),
            ]

    class Exporter:
        def export(self, title, questions, file_path,
                   shuffle_choices=False, sections=None):
            captured['title'] = title
            captured['questions'] = questions
            captured['sections'] = sections

    interface.repo = Repo()
    interface.validator = _AlwaysEligibleValidator()
    interface.exporter = Exporter()
    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: (
            'C:/tmp/multi.docx', 'Word Documents (*.docx)'
        ),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.success',
        lambda **_kwargs: None,
    )

    interface.export_docx()

assert [(call['exam_code'], call['subject_code'], call['tag_query'])
        for call in captured['calls']] == [
    ('first::engineer', 'first::engine1', '#safety'),
    ('second::navigation', 'second::nav1', '#safety'),
]
assert [question['id'] for question in captured['questions']] == [
    'first::1', 'second::2',
]
assert [section['title'] for section in captured['sections']] == [
    'First DB · Engineer Exam · Engine 1',
    'Second DB · Navigation Exam · Navigation 1',
]
assert captured['title'].endswith('Multi-exam mock exam')
```

- [ ] **Step 2: Verify the test fails on single-exam routing**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py::test_export_docx_combines_subjects_from_different_exams -q
```

Expected: FAIL because every subject request currently reuses the combo-box `exam_code`.

- [ ] **Step 3: Implement multi-exam validation and routing**

At the start of `export_docx()` compute `multi_exam_mode = self._is_multi_exam_mode()`. Require `exam_code` only when the mode is off. When multi mode has no checked rows, report:

```python
InfoBar.error(
    title='No subjects selected',
    content='Select at least one exam subject and set its question count.',
    parent=self,
)
```

Inside the subject-request loop use:

```python
request_exam_code = request['exam_code'] if multi_exam_mode else exam_code
request_label = request.get('section_title') or request['name']
subject_questions = self._get_filtered_unique_questions(
    request_exam_code, request['code'], year_from, year_to,
    dedupe=False, tag_query=tag_query,
)
```

Keep the existing validator, group-aware selection, and document-wide `selected_keys`. Use `request_label` for insufficient-count errors and `sections.append({'title': request_label, 'questions': selected_questions})`.

For multi mode, use:

```python
total_count = sum(request['count'] for request in subject_requests)
filename = self._build_multi_exam_filename(year_from, year_to, total_count)
title = self._build_multi_exam_title()
```

Keep existing filename and title branches unchanged when multi mode is off.

- [ ] **Step 4: Add explicit validation tests**

Add these tests:

```python
def test_multi_exam_export_requires_at_least_one_selected_subject(monkeypatch):
    row = _multi_exam_subject_request(
        'first::engineer', 'Engineer Exam',
        'first::engine1', 'Engine 1', 'First DB', 1,
    )
    row['checkbox'].setChecked(False)
    interface = _multi_exam_export_interface([row])
    errors = []
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.error',
        lambda **kwargs: errors.append(kwargs),
    )

    interface.export_docx()

    assert errors[0]['title'] == 'No subjects selected'


def test_multi_exam_export_reports_full_section_when_unique_is_insufficient(
    monkeypatch,
):
    interface = _multi_exam_export_interface([
        _multi_exam_subject_request(
            'first::engineer', 'Engineer Exam',
            'first::engine1', 'Engine 1', 'First DB', 1,
        ),
        _multi_exam_subject_request(
            'second::navigation', 'Navigation Exam',
            'second::nav1', 'Navigation 1', 'Second DB', 1,
        ),
    ])

    class Repo:
        def get_questions_with_choices(self, **kwargs):
            return [_eligible_export_question(
                f"{kwargs['exam_code']}::1",
                'same logical question',
            )]

    interface.repo = Repo()
    interface.validator = _AlwaysEligibleValidator()
    errors = []
    dialog_calls = []
    monkeypatch.setattr(
        'src.gui.interface.export.random.sample',
        lambda population, count: list(population)[:count],
    )
    monkeypatch.setattr(
        'src.gui.interface.export.InfoBar.error',
        lambda **kwargs: errors.append(kwargs),
    )
    monkeypatch.setattr(
        'src.gui.interface.export.QFileDialog.getSaveFileName',
        lambda *_args, **_kwargs: dialog_calls.append(True),
    )

    interface.export_docx()

    assert 'Second DB · Navigation Exam · Navigation 1' in (
        errors[0]['content']
    )
    assert dialog_calls == []
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py -q
```

Expected: all Export interface tests pass.

- [ ] **Step 5: Commit cross-exam routing**

```powershell
git add -- src/gui/interface/export.py tests/test_export_interface.py
git commit -m "feat: export subjects across mounted exams"
```

---

### Task 4: Mounted Repository and Full Regression Verification

**Files:**
- Verify: `src/gui/interface/export.py`
- Verify: `tests/test_export_interface.py`
- Verify: `data/domain_dbs/mount_manifest.json`

**Interfaces:**
- Consumes: `MountedExamRepository` through `build_question_repository()`.
- Produces: verification evidence for real mounted row population and application regressions.

- [ ] **Step 1: Run focused repository and UI tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_export_interface.py tests/test_main_window_layout.py tests/test_db_mount_prototype.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run a real-manifest offscreen UI check**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
@'
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from src.gui.interface.export import ExportInterface
from src.gui.main import build_question_repository

root = Path.cwd()
repo, error = build_question_repository(
    root / 'data' / 'exam_bank.db',
    root / 'data' / 'domain_dbs' / 'mount_manifest.json',
)
assert error is None, error
app = QApplication.instance() or QApplication([])
widget = ExportInterface(repository=repo)
widget.multiExamModeCheck.setChecked(True)
rows = widget.subjectSelectionRows
assert rows
assert len({row['exam_code'] for row in rows}) >= 2
assert len({row['mount_label'] for row in rows}) >= 2
assert all('::' in row['exam_code'] for row in rows)
assert all('::' in row['subject_code'] for row in rows)
widget.close()
'@ | .\.venv\Scripts\python.exe -
```

Expected: exit code 0.

- [ ] **Step 3: Run the complete suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass; only existing Pillow deprecation warnings may remain.

- [ ] **Step 4: Inspect scope and protected user files**

```powershell
git diff --check
git status --short
git log --oneline -4
```

Expected: implementation files are committed and `exam_bank.maritime_domain.20260705_175510.examdb.zip` remains untracked and unchanged.
