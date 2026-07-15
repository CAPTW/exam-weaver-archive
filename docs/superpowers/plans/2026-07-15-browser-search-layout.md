# Browser Search Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 문제 관리 탭의 검색 입력창을 독립된 두 번째 행으로 옮기고 바로 오른쪽에 `조회` 버튼을 배치한다.

**Architecture:** 기존 `BrowserInterface.init_ui()`의 필터/관리 header layout은 유지하되 검색 위젯만 새 `QHBoxLayout`으로 분리한다. 검색 입력창에는 stretch factor 1과 최소 폭 320px을 적용하고 기존 검색 이벤트·repository 호출은 변경하지 않는다.

**Tech Stack:** Python, PyQt5, qfluentwidgets, pytest

## Global Constraints

- 첫 번째 행에는 제목, EXAM, SUBJECT, 문제 추가, 서술형 추가, 오류 검사, 선택 삭제만 둔다.
- 두 번째 행에는 검색 입력창과 `조회` 버튼만 둔다.
- 검색 입력창은 최소 폭 320px이고 남는 가로 폭을 모두 사용한다.
- Enter 및 `조회` 클릭은 기존 `load_data()` 동작을 유지한다.
- 테이블은 검색 행 아래에 둔다.

---

### Task 1: 문제 관리 검색 행 분리

**Files:**
- Modify: `tests/test_editor_layout.py`
- Modify: `src/gui/interface/browser.py:52-127`

**Interfaces:**
- Consumes: 기존 `BrowserInterface.headerLayout`, `searchBox`, `btnRefresh`, `vBoxLayout`
- Produces: `BrowserInterface.searchLayout: QHBoxLayout`

- [ ] **Step 1: 실패하는 레이아웃 테스트 작성**

```python
def test_browser_search_controls_use_full_width_second_row(repo):
    widget = BrowserInterface(repo.db_path)

    assert widget.headerLayout.indexOf(widget.searchBox) == -1
    assert widget.headerLayout.indexOf(widget.btnRefresh) == -1
    assert widget.searchLayout.indexOf(widget.searchBox) == 0
    assert widget.searchLayout.indexOf(widget.btnRefresh) == 1
    assert widget.searchLayout.stretch(0) == 1
    assert widget.searchBox.minimumWidth() >= 320
    assert widget.vBoxLayout.itemAt(0).layout() is widget.headerLayout
    assert widget.vBoxLayout.itemAt(1).layout() is widget.searchLayout
    assert widget.vBoxLayout.itemAt(2).widget() is widget.table

    widget.deleteLater()
    APP.processEvents()
```

- [ ] **Step 2: 테스트가 새 search layout 부재로 실패하는지 확인**

Run: `$env:PYTHONPATH='.'; & 'C:\Users\user\Documents\Codex\exam-weaver-archive\.venv\Scripts\python.exe' -m pytest tests/test_editor_layout.py::test_browser_search_controls_use_full_width_second_row -v`

Expected: `AttributeError: 'BrowserInterface' object has no attribute 'searchLayout'` 또는 검색창이 header에 남아 있다는 assertion FAIL.

- [ ] **Step 3: 두 번째 검색 행 최소 구현**

```python
self.headerLayout = QHBoxLayout()
self.searchLayout = QHBoxLayout()

self.searchBox = LineEdit()
self.searchBox.setPlaceholderText("태그/문항/선지 검색...")
self.searchBox.setMinimumWidth(320)
self.searchBox.returnPressed.connect(self.load_data)

self.headerLayout.addWidget(self.btnDeleteSelected)

self.searchLayout.addWidget(self.searchBox, 1)
self.searchLayout.addWidget(self.btnRefresh)

self.vBoxLayout.addLayout(self.headerLayout)
self.vBoxLayout.addLayout(self.searchLayout)
self.vBoxLayout.addWidget(self.table)
```

기존 header에서 `searchBox`와 `btnRefresh`를 추가하던 두 줄은 제거한다.

- [ ] **Step 4: 신규 테스트와 UI 관련 회귀 테스트 통과 확인**

Run: `$env:PYTHONPATH='.'; & 'C:\Users\user\Documents\Codex\exam-weaver-archive\.venv\Scripts\python.exe' -m pytest tests/test_editor_layout.py tests/test_browser_filters.py tests/test_mounted_browser.py -q`

Expected: 전부 PASS.

- [ ] **Step 5: 전체 테스트와 diff 검증**

Run: `git diff --check`

Expected: 출력 없음, exit 0.

Run: `$env:PYTHONPATH='.'; & 'C:\Users\user\Documents\Codex\exam-weaver-archive\.venv\Scripts\python.exe' -m pytest -q`

Expected: 전부 PASS.

- [ ] **Step 6: 구현 커밋**

```powershell
git add docs/superpowers/plans/2026-07-15-browser-search-layout.md src/gui/interface/browser.py tests/test_editor_layout.py
git commit -m "fix: widen browser search controls"
```

Expected: 검색 행 구현과 테스트만 포함한 로컬 커밋 생성.
