# Choice Marker Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 선택한 객관식 선지 표기 방식이 앱 전체와 DOCX 출력에 일관되게 적용되도록 한다.

**Architecture:** DB의 `choice_number`는 그대로 유지하고 새 표시 유틸리티가 UI와 DOCX용 기호를 만든다. 설정은 기존 `app_settings.json`에 별도 키로 저장하며 메인 창이 각 화면에 전역 값을 주입한다.

**Tech Stack:** Python 3, PyQt5/qfluentwidgets, python-docx, pytest

## Global Constraints

- 기본값은 `㉮ ㉯ ㉴ ㉵`이다.
- 숫자 원문자 선택 시 `①`~`⑩`을 지원한다.
- DB 스키마와 기존 `choice_symbol` 데이터는 마이그레이션하지 않는다.
- 현재 작업 트리의 기존 OCR 변경과 사용자 ZIP 파일을 수정하거나 포함하지 않는다.
- 사용자가 별도로 요청하지 않았으므로 이 구현 과정에서 Git commit/push는 수행하지 않는다.

---

### Task 1: 표시 변환과 설정 저장

**Files:**
- Create: `src/choice_markers.py`
- Create: `src/gui/choice_marker_settings.py`
- Create: `tests/test_choice_markers.py`
- Create: `tests/test_choice_marker_settings.py`

**Interfaces:**
- Produces: `normalize_choice_marker_style(style: object) -> str`
- Produces: `choice_marker(number: object, style: object, fallback: str = "") -> str`
- Produces: `load_choice_marker_style(base_dir: str | Path) -> str`
- Produces: `save_choice_marker_style(base_dir: str | Path, style: str) -> Path`

- [ ] **Step 1: Write failing unit tests**

```python
def test_circled_number_style_formats_supported_choice_numbers():
    assert [choice_marker(number, CIRCLED_NUMBER_STYLE) for number in range(1, 11)] == list("①②③④⑤⑥⑦⑧⑨⑩")

def test_choice_marker_setting_preserves_existing_menu_locale(tmp_path):
    settings = tmp_path / "data" / "app_settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"menu_locale":"en"}', encoding="utf-8")
    save_choice_marker_style(tmp_path, CIRCLED_NUMBER_STYLE)
    assert json.loads(settings.read_text(encoding="utf-8")) == {"menu_locale": "en", "choice_marker_style": CIRCLED_NUMBER_STYLE}
```

- [ ] **Step 2: Run the new tests and verify missing-module failures**

Run: `python -m pytest tests/test_choice_markers.py tests/test_choice_marker_settings.py -q`
Expected: FAIL because the new modules do not exist.

- [ ] **Step 3: Implement validated formatting and atomic JSON persistence**

```python
LEGACY_KOREAN_STYLE = "legacy_korean"
CIRCLED_NUMBER_STYLE = "circled_number"
DEFAULT_CHOICE_MARKER_STYLE = LEGACY_KOREAN_STYLE
_MARKERS = {
    LEGACY_KOREAN_STYLE: {1: "㉮", 2: "㉯", 3: "㉴", 4: "㉵", 5: "⑤"},
    CIRCLED_NUMBER_STYLE: dict(enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1)),
}

def choice_marker(number, style=DEFAULT_CHOICE_MARKER_STYLE, fallback=""):
    normalized_style = normalize_choice_marker_style(style)
    try:
        normalized_number = int(number)
    except (TypeError, ValueError):
        return str(fallback or "")
    return _MARKERS[normalized_style].get(
        normalized_number,
        str(fallback or normalized_number),
    )
```

- [ ] **Step 4: Run the focused tests**

Run: `python -m pytest tests/test_choice_markers.py tests/test_choice_marker_settings.py -q`
Expected: PASS.

### Task 2: 설정 UI와 전역 주입

**Files:**
- Modify: `src/gui/interface/settings.py`
- Modify: `src/gui/main.py`
- Modify: `tests/test_settings_interface.py`
- Modify: `tests/test_main_window_layout.py`

**Interfaces:**
- Consumes: Task 1 style constants and persistence functions.
- Produces: `SettingsDialog.selected_choice_marker_style() -> str`
- Produces: `MainWindow.apply_choice_marker_style(style: str) -> None`

- [ ] **Step 1: Add failing settings-dialog and main wiring tests**

```python
dialog = SettingsDialog(packs=packs, current_locale="ko", warnings=[], current_choice_marker_style=CIRCLED_NUMBER_STYLE)
assert dialog.selected_choice_marker_style() == CIRCLED_NUMBER_STYLE
assert "load_choice_marker_style" in gui_main_source
assert "apply_choice_marker_style" in gui_main_source
```
- [ ] **Step 2: Run `python -m pytest tests/test_settings_interface.py tests/test_main_window_layout.py -q` and verify failure**
- [ ] **Step 3: Add the two-option combo, load the saved style, persist it, and fan it out to all three feature interfaces**

```python
self.choiceMarkerCombo.addItem("한글 원문자 (㉮ ㉯ ㉴ ㉵)", userData=LEGACY_KOREAN_STYLE)
self.choiceMarkerCombo.addItem("숫자 원문자 (① ② ③ ④)", userData=CIRCLED_NUMBER_STYLE)
self.browser_interface.set_choice_marker_style(style)
self.practice_interface.set_choice_marker_style(style)
self.export_interface.set_choice_marker_style(style)
```
- [ ] **Step 4: Re-run the focused tests and verify PASS**

### Task 3: 문제 편집과 문제 풀이 표시

**Files:**
- Modify: `src/gui/interface/browser.py`
- Modify: `src/gui/interface/editor.py`
- Modify: `src/gui/interface/practice.py`
- Modify: `tests/test_editor_layout.py`
- Modify: `tests/test_practice_interface.py`

**Interfaces:**
- Produces: `BrowserInterface.set_choice_marker_style(style: str) -> None`
- Produces: `QuestionEditor.set_choice_marker_style(style: str) -> None`
- Produces: `PracticeInterface.set_choice_marker_style(style: str) -> None`

- [ ] **Step 1: Add failing tests for numeric display and stored-symbol preservation**

```python
editor = QuestionEditor(question_data=question, choice_marker_style=CIRCLED_NUMBER_STYLE)
assert editor.choiceLabels[1].text() == "①"
assert editor.get_data()["choices"][0]["choice_symbol"] == "㉮"
practice = PracticeInterface(repository=repository, choice_marker_style=CIRCLED_NUMBER_STYLE)
assert practice._format_choice_text(question["choices"][0]).startswith("① ")
```
- [ ] **Step 2: Run the editor/practice tests and verify failure**
- [ ] **Step 3: Apply presentation markers to labels, answer options, choice buttons, and feedback while preserving stored symbols**

```python
def _choice_symbol(self, number):
    return choice_marker(number, self.choice_marker_style)

def _stored_choice_symbol(self, number):
    for choice in self.question_data.get("choices") or []:
        if int(choice.get("choice_number") or choice.get("number") or 0) == number:
            return choice.get("choice_symbol") or NUMBER_TO_CHOICE_SYMBOL.get(number, str(number))
    return NUMBER_TO_CHOICE_SYMBOL.get(number, str(number))
```
- [ ] **Step 4: Re-run the editor/practice tests and verify PASS**

### Task 4: DOCX 본문과 정답표

**Files:**
- Modify: `src/gui/interface/export.py`
- Modify: `src/exporter/docx.py`
- Modify: `tests/test_docx_exporter.py`
- Modify: `tests/test_export_interface.py`

**Interfaces:**
- Produces: `DocxExporter.set_choice_marker_style(style: str) -> None`
- Produces: `ExportInterface.set_choice_marker_style(style: str) -> None`

- [ ] **Step 1: Add a failing DOCX XML test for `①`~`④` in choices and the answer key**

```python
exporter = DocxExporter(choice_marker_style=CIRCLED_NUMBER_STYLE)
exporter.export("숫자 원문자", questions, str(output_path), include_answer_key=True)
text = "\n".join(_paragraph_text(p) for p in _paragraphs(_read_document_xml(output_path)))
assert "① 첫 번째" in text
assert "1. ①" in text
```
- [ ] **Step 2: Run the DOCX/export interface tests and verify failure**
- [ ] **Step 3: Derive rendered and answer-key markers from `choice_number` and the configured style**

```python
symbol = choice_marker(
    choice.get("choice_number"),
    self.choice_marker_style,
    fallback=choice.get("choice_symbol") or "",
)
return choice_marker(answer_number, self.choice_marker_style, fallback=str(answer_number))
```
- [ ] **Step 4: Re-run the DOCX/export tests and verify PASS**

### Task 5: 회귀 검증

**Files:**
- Verify only: all files changed in Tasks 1-4

- [ ] **Step 1: Run focused feature suites**

Run: `python -m pytest tests/test_choice_markers.py tests/test_choice_marker_settings.py tests/test_settings_interface.py tests/test_editor_layout.py tests/test_practice_interface.py tests/test_docx_exporter.py tests/test_export_interface.py tests/test_main_window_layout.py -q`
Expected: PASS.

- [ ] **Step 2: Run the complete test suite**

Run: `python -m pytest -q`
Expected: PASS with no new failures.

- [ ] **Step 3: Review the diff and working tree**

Run: `git diff --check` and `git status --short`
Expected: no whitespace errors; only this feature plus the pre-existing OCR work and untracked user files are present.
