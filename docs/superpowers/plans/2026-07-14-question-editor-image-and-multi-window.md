# Question Editor Image and Multi-Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent question-image controls with clipboard copy and allow multiple different question edit dialogs while reusing the existing dialog for the same question.

**Architecture:** Keep image behavior inside `QuestionEditor`, using a horizontal action row and a small clipboard abstraction that can be tested without replacing the application clipboard. Keep concurrent edit-window ownership inside `BrowserInterface`, with a registry keyed by question ID and save callbacks that capture the repository used when the window opened. Existing create, clone, and descriptive-question dialogs remain modal.

**Tech Stack:** Python 3, PyQt5, qfluentwidgets, pytest

## Global Constraints

- The question-image action row contains four separate buttons: `이미지 변경` or `이미지 추가`, `붙여넣기`, `클립보드 복사`, and `삭제`.
- Clipboard copy is enabled only when the current image path exists and can be decoded as a `QImage`.
- Only edit dialogs opened from Problem Management become non-modal; create, clone, and descriptive-question dialogs keep their current modal behavior.
- Different questions may have concurrent edit dialogs; the same question ID has exactly one edit dialog.
- Each edit dialog saves through the repository instance captured when that dialog was opened.
- Choice-image controls and cross-process optimistic locking are outside this change.

---

### Task 1: Separate question-image actions and add clipboard copy

**Files:**
- Modify: `src/gui/interface/editor.py:1-240,555-568,888-925`
- Test: `tests/test_editor_layout.py`

**Interfaces:**
- Consumes: `QuestionEditor.imagePath: Optional[str]`, `QApplication.clipboard()`, and `QImage`.
- Produces: `QuestionEditor.btnCopyImage`, `QuestionEditor.imageButtonLayout`, `QuestionEditor._clipboard()`, `QuestionEditor._copy_image_to_clipboard() -> bool`, and `QuestionEditor._can_copy_image(image_path) -> bool`.

- [ ] **Step 1: Add failing layout and clipboard-copy tests**

Add the following tests to `tests/test_editor_layout.py`:

```python
def _question_editor_data(image_path=None):
    return {
        'year': 2024,
        'session': 1,
        'question_number': 1,
        'subject_code': 'engine1',
        'exam_code': '4급기관사',
        'question_text': '이미지 제어를 확인할 문제',
        'image_path': image_path,
        'correct_answer': 1,
        'choices': [
            {'choice_number': 1, 'choice_text': 'A'},
            {'choice_number': 2, 'choice_text': 'B'},
            {'choice_number': 3, 'choice_text': 'C'},
            {'choice_number': 4, 'choice_text': 'D'},
        ],
    }


def test_question_editor_image_actions_are_separate_horizontal_buttons(tmp_path):
    image_path = tmp_path / 'question.png'
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    assert image.save(str(image_path), 'PNG')
    editor = QuestionEditor(
        question_data=_question_editor_data(str(image_path)),
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    editor.show()
    APP.processEvents()

    buttons = [
        editor.btnImage,
        editor.btnPasteImage,
        editor.btnCopyImage,
        editor.btnClearImage,
    ]
    assert editor.imageButtonLayout.count() == 4
    assert [editor.imageButtonLayout.itemAt(i).widget() for i in range(4)] == buttons
    assert [button.text() for button in buttons] == [
        '이미지 변경', '붙여넣기', '클립보드 복사', '삭제'
    ]
    assert all(
        not left.geometry().intersects(right.geometry())
        for index, left in enumerate(buttons)
        for right in buttons[index + 1:]
    )
    editor.close()
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_copies_current_image_to_clipboard(tmp_path, monkeypatch):
    image_path = tmp_path / 'question.png'
    source = QImage(7, 5, QImage.Format.Format_RGB32)
    source.fill(0x12AB34)
    assert source.save(str(image_path), 'PNG')
    editor = QuestionEditor(
        question_data=_question_editor_data(str(image_path)),
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    class Clipboard:
        image = None

        def setImage(self, image):
            self.image = QImage(image)

    clipboard = Clipboard()
    monkeypatch.setattr(editor, '_clipboard', lambda: clipboard)

    assert editor.btnCopyImage.isEnabled() is True
    assert editor._copy_image_to_clipboard() is True
    assert clipboard.image.size() == source.size()
    assert clipboard.image.pixelColor(0, 0) == source.pixelColor(0, 0)
    assert editor.imageStatusLabel.text() == '클립보드에 복사됨'
    editor.deleteLater()
    APP.processEvents()


def test_question_editor_disables_copy_for_missing_or_deleted_image(tmp_path):
    missing_path = tmp_path / 'missing.png'
    editor = QuestionEditor(
        question_data=_question_editor_data(str(missing_path)),
        subject_options=[{'code': 'engine1', 'name_ko': '기관1'}],
    )

    assert editor.btnCopyImage.isEnabled() is False
    assert editor._copy_image_to_clipboard() is False

    editor._clear_image()

    assert editor.btnCopyImage.isEnabled() is False
    assert editor.imageStatusLabel.text() == '이미지 없음'
    editor.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py::test_question_editor_image_actions_are_separate_horizontal_buttons tests/test_editor_layout.py::test_question_editor_copies_current_image_to_clipboard tests/test_editor_layout.py::test_question_editor_disables_copy_for_missing_or_deleted_image -q
```

Expected: FAIL because `btnCopyImage`, `imageButtonLayout`, `_clipboard`, and `_copy_image_to_clipboard` do not exist and the three existing image buttons use a vertical layout constrained to 118 pixels.

- [ ] **Step 3: Implement the horizontal action row and clipboard copy**

In `src/gui/interface/editor.py`, import `QImage`:

```python
from PyQt5.QtGui import QImage, QTextCharFormat, QTextCursor
```

Replace the three vertically stacked image controls with four buttons in a named horizontal layout:

```python
self.btnImage = PushButton("이미지 추가" if self.create_mode else "이미지 변경", self)
self.btnPasteImage = PushButton("붙여넣기", self)
self.btnCopyImage = PushButton("클립보드 복사", self)
self.btnClearImage = PushButton("삭제", self)
for button, width in (
    (self.btnImage, 120),
    (self.btnPasteImage, 100),
    (self.btnCopyImage, 130),
    (self.btnClearImage, 80),
):
    self._apply_input_height(button)
    button.setFixedWidth(width)

self.btnImage.clicked.connect(self._select_image)
self.btnPasteImage.clicked.connect(self._paste_image)
self.btnCopyImage.clicked.connect(self._copy_image_to_clipboard)
self.btnClearImage.setToolTip("문제 이미지 경로 삭제")
self.btnClearImage.clicked.connect(self._clear_image)

self.imageButtonBar = QWidget(self)
self.imageButtonLayout = QHBoxLayout(self.imageButtonBar)
self.imageButtonLayout.setContentsMargins(0, 0, 0, 0)
self.imageButtonLayout.setSpacing(8)
self.imageButtonLayout.addWidget(self.btnImage)
self.imageButtonLayout.addWidget(self.btnPasteImage)
self.imageButtonLayout.addWidget(self.btnCopyImage)
self.imageButtonLayout.addWidget(self.btnClearImage)

imageControlsLayout.addWidget(self.imageStatusLabel)
imageControlsLayout.addWidget(self.imageButtonBar)
imageControlsLayout.addStretch(1)
self.imageWidget.setMinimumHeight(138)
self.imageWidget.setMaximumHeight(156)
```

Add clipboard and validation helpers and make `_clipboard_image` share the same clipboard accessor:

```python
def _clipboard(self):
    return QApplication.clipboard()

def _clipboard_image(self):
    clipboard = self._clipboard()
    return clipboard.image() if clipboard else None

@staticmethod
def _can_copy_image(image_path):
    if not image_path or not Path(image_path).is_file():
        return False
    return not QImage(str(image_path)).isNull()

def _copy_image_to_clipboard(self):
    if not self._can_copy_image(self.imagePath):
        self.imageStatusLabel.setText(
            "이미지 없음" if not self.imagePath else "이미지를 읽을 수 없음"
        )
        self.btnCopyImage.setEnabled(False)
        return False

    clipboard = self._clipboard()
    if clipboard is None:
        self.imageStatusLabel.setText("클립보드를 사용할 수 없음")
        self.btnCopyImage.setEnabled(False)
        return False

    clipboard.setImage(QImage(str(self.imagePath)))
    self.imageStatusLabel.setText("클립보드에 복사됨")
    return True
```

Update `_set_image_preview` so every image change updates button state and the layout height remains sufficient:

```python
def _set_image_preview(self, image_path):
    can_copy = self._can_copy_image(image_path)
    if can_copy:
        self.imageLabel.setVisible(True)
        self.imageLabel.setImage(image_path)
        self.imageLabel.setFixedSize(180, 110)
        self.imageStatusLabel.setText(self._format_image_status(image_path))
    else:
        self.imageLabel.setVisible(False)
        self.imageLabel.setFixedSize(0, 0)
        self.imageStatusLabel.setText(
            self._format_image_status(None) if not image_path else "이미지를 읽을 수 없음"
        )
    self.btnCopyImage.setEnabled(can_copy)
```

- [ ] **Step 4: Run image tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py -q
```

Expected: all editor-layout tests PASS with no Qt warnings or unhandled exceptions.

- [ ] **Step 5: Commit the image controls**

```powershell
git add docs/superpowers/plans/2026-07-14-question-editor-image-and-multi-window.md tests/test_editor_layout.py src/gui/interface/editor.py
git commit -m "feat: separate question image actions"
```

---

### Task 2: Manage concurrent non-modal edit dialogs by question ID

**Files:**
- Modify: `src/gui/interface/browser.py:18-45,349-391`
- Test: `tests/test_editor_layout.py`

**Interfaces:**
- Consumes: `QuestionEditor.accepted`, `QuestionEditor.finished`, `QuestionEditor.get_data()`, and repository methods `get_question`, `get_subject_options`, and `update_question`.
- Produces: `BrowserInterface._open_editors: Dict[Hashable, QuestionEditor]`, `open_editor(question_id) -> Optional[QuestionEditor]`, `_activate_editor(dialog)`, `_save_open_editor(question_id, dialog, repository)`, and `_release_editor(question_id, dialog)`.

- [ ] **Step 1: Add failing concurrent-window tests**

Add this helper and tests to `tests/test_editor_layout.py`:

```python
def _save_two_editable_questions(repo):
    questions = [
        Question(
            number=number,
            text=text,
            choices=[
                Choice(number=1, symbol='㉮', text='A'),
                Choice(number=2, symbol='㉯', text='B'),
                Choice(number=3, symbol='㉴', text='C'),
                Choice(number=4, symbol='㉵', text='D'),
            ],
            correct_answer=1,
            subject_name='기관1',
            year=2024,
            session=1,
            exam_type='3급기관사',
        )
        for number, text in ((1, '첫 번째 편집 문제'), (2, '두 번째 편집 문제'))
    ]
    metadata = type(
        'Metadata', (),
        {'year': 2024, 'session': 1, 'exam_type': '3급기관사'}
    )()
    repo.save_questions(questions, metadata)
    return repo.get_questions_with_choices(exam_code='3급기관사', limit=None)


def test_browser_opens_different_question_editors_and_reuses_same_question(repo):
    questions = _save_two_editable_questions(repo)
    widget = BrowserInterface(repo.db_path)

    first = widget.open_editor(questions[0]['id'])
    second = widget.open_editor(questions[1]['id'])
    same_first = widget.open_editor(questions[0]['id'])

    assert first is same_first
    assert first is not second
    assert first.isModal() is False
    assert second.isModal() is False
    assert widget._open_editors == {
        questions[0]['id']: first,
        questions[1]['id']: second,
    }

    first.reject()
    second.reject()
    APP.processEvents()
    assert widget._open_editors == {}
    widget.deleteLater()
    APP.processEvents()


def test_browser_edit_dialog_saves_through_repository_captured_when_opened(
    repo, monkeypatch
):
    question = _save_two_editable_questions(repo)[0]
    widget = BrowserInterface(repo.db_path)
    dialog = widget.open_editor(question['id'])
    dialog.questionText.setPlainText('열 때의 저장소에 저장된 수정문제')
    refreshed = []
    wrong_repository_calls = []

    class WrongRepository:
        def update_question(self, question_id, data):
            wrong_repository_calls.append((question_id, data))
            return True

    widget.repo = WrongRepository()
    monkeypatch.setattr(widget, 'load_data', lambda: refreshed.append(True))
    monkeypatch.setattr(browser_module.InfoBar, 'success', lambda **_kwargs: None)

    dialog.accept()
    APP.processEvents()

    assert wrong_repository_calls == []
    assert repo.get_question(question['id'])['question_text'] == '열 때의 저장소에 저장된 수정문제'
    assert refreshed == [True]
    assert question['id'] not in widget._open_editors
    widget.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: Run concurrent-window tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py::test_browser_opens_different_question_editors_and_reuses_same_question tests/test_editor_layout.py::test_browser_edit_dialog_saves_through_repository_captured_when_opened -q
```

Expected: FAIL because `open_editor` blocks in `dialog.exec()`, returns `None`, and `BrowserInterface` has no `_open_editors` registry.

- [ ] **Step 3: Implement non-modal edit-window ownership**

Initialize the registry in `BrowserInterface.__init__` before loading data:

```python
self._open_editors = {}
```

Replace the synchronous `open_editor` body and extract save, activation, and cleanup methods:

```python
def open_editor(self, question_id):
    existing = self._open_editors.get(question_id)
    if existing is not None:
        self._activate_editor(existing)
        return existing

    repository = self.repo
    q = repository.get_question(question_id)
    if not q:
        return None

    editor_question = dict(q)
    editor_question['exam_code'] = q.get('mounted_exam_code') or q.get('exam_code')
    editor_question['subject_code'] = q.get('mounted_subject_code') or q.get('subject_code')
    dialog = QuestionEditor(
        self.window(),
        editor_question,
        subject_options=repository.get_subject_options(editor_question.get('exam_code')),
    )
    dialog.setModal(False)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    self._open_editors[question_id] = dialog
    dialog.accepted.connect(
        lambda qid=question_id, editor=dialog, repo=repository:
        self._save_open_editor(qid, editor, repo)
    )
    dialog.finished.connect(
        lambda _result, qid=question_id, editor=dialog:
        self._release_editor(qid, editor)
    )
    dialog.show()
    return dialog

def _activate_editor(self, dialog):
    if dialog.isMinimized():
        dialog.showNormal()
    else:
        dialog.show()
    dialog.raise_()
    dialog.activateWindow()

def _save_open_editor(self, question_id, dialog, repository):
    new_data = dialog.get_data()
    try:
        updated = repository.update_question(question_id, new_data)
    except (OSError, sqlite3.Error, ValueError, RuntimeError) as exc:
        self._show_write_error("수정", exc)
        return
    if not updated:
        InfoBar.error(title='오류', content="DB 업데이트 실패", parent=self)
        return

    InfoBar.success(
        title='수정 완료',
        content="문제가 성공적으로 수정되었습니다.",
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        position=InfoBarPosition.TOP_RIGHT,
        duration=2000,
        parent=self,
    )
    if self.validation_mode:
        self.load_validation_results()
    else:
        self.load_data()

def _release_editor(self, question_id, dialog):
    if self._open_editors.get(question_id) is dialog:
        self._open_editors.pop(question_id, None)
```

- [ ] **Step 4: Run focused and related GUI tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py -q
```

Expected: all editor and browser layout tests PASS. Existing manual-add, descriptive-add, and clone tests continue to prove their dialogs still use `exec()`.

- [ ] **Step 5: Run the full regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the entire suite PASS with no collection errors, crashes, or unhandled Qt exceptions.

- [ ] **Step 6: Inspect diff and commit concurrent editing**

Run:

```powershell
git diff --check
git status --short
git diff -- src/gui/interface/browser.py tests/test_editor_layout.py
git add src/gui/interface/browser.py tests/test_editor_layout.py
git commit -m "feat: allow concurrent question editing"
```

Expected: only the planned source, test, and plan changes are committed; the pre-existing `exam_bank.maritime_domain.20260705_175510.examdb.zip` remains untouched and untracked.
