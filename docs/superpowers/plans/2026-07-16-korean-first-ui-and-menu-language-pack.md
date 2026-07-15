# 한국어 중심 UI 및 메뉴 언어 팩 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱 전체의 사용자 노출 문구와 핵심 배치를 한국어 중심으로 통일하고, 메인 메뉴만 한국어·영어·외부 JSON 팩으로 전환할 수 있게 한다.

**Architecture:** 메뉴 번역과 설정 저장은 `src/gui/menu_language.py`에 격리하고, 설정 대화상자는 유효한 locale만 MainWindow에 전달한다. 업무 화면은 기존 위젯과 Repository/내보내기 동작을 유지하면서 문구, 상태 요약, 기능 선택의 시각적 위계만 조정한다. 각 작업은 실패 테스트를 먼저 추가하고 화면 단위 회귀 테스트를 통과시킨 뒤 커밋한다.

**Tech Stack:** Python 3.11+, PyQt5, PyQt-Fluent-Widgets, JSON, pytest, PyInstaller

## Global Constraints

- 사용자 화면의 `DB`와 `Database`는 `문제은행`으로 표시한다.
- 사용자 화면의 `태그`, `Tag`, `Hashtag`는 `해시태그`로 표시한다.
- `Codex`, `PDF`, `DOCX`, `OCR`, `ID`, 모델명과 파일 확장자는 유지한다.
- 메뉴 언어 팩은 메인 탐색 메뉴에만 적용하며 업무 화면 본문과 알림은 한국어를 유지한다.
- Repository 주입, Mounted Repository 갱신, 쓰기 대상 결정, 문제은행 schema와 DOCX 선택·중복 제거 로직을 변경하지 않는다.
- 외부 언어 팩은 알려진 문자열 키만 읽고 코드, 경로, 스타일 또는 임의 객체를 실행하지 않는다.
- 모든 동작 변경은 실패 테스트를 먼저 확인한 뒤 최소 구현으로 통과시킨다.
- 사용자 소유 `exam_bank.maritime_domain.20260705_175510.examdb.zip`은 수정·삭제·stage하지 않는다.

---

### Task 1: 메뉴 언어 팩 로더와 휴대용 설정 저장

**Files:**
- Create: `src/gui/menu_language.py`
- Create: `assets/language_packs/menu/ko.json`
- Create: `assets/language_packs/menu/en.json`
- Create: `tests/test_menu_language.py`

**Interfaces:**
- Produces: `MenuLanguagePack(locale: str, display_name: str, version: int, strings: Mapping[str, str])`
- Produces: `discover_menu_language_packs(base_dir: str | Path) -> tuple[dict[str, MenuLanguagePack], list[str]]`
- Produces: `load_menu_locale(base_dir: str | Path, available_locales: Collection[str]) -> str`
- Produces: `save_menu_locale(base_dir: str | Path, locale: str, available_locales: Collection[str]) -> Path`
- Produces: `menu_text(pack: MenuLanguagePack, key: str) -> str`

- [x] **Step 1: Write failing loader, fallback, validation, and persistence tests**

```python
def test_builtin_menu_packs_supply_every_known_key(tmp_path):
    packs, warnings = discover_menu_language_packs(PROJECT_ROOT)
    assert warnings == []
    assert set(packs) >= {"ko", "en"}
    for key in MENU_KEYS:
        assert packs["ko"].strings[key]
        assert packs["en"].strings[key]


def test_external_pack_uses_korean_fallback_for_missing_keys(tmp_path):
    pack_dir = tmp_path / "data" / "language_packs" / "menu"
    pack_dir.mkdir(parents=True)
    (pack_dir / "ja.json").write_text(
        json.dumps({
            "locale": "ja",
            "display_name": "日本語",
            "version": 1,
            "strings": {"menu.home": "ホーム", "unknown": "ignored"},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    packs, warnings = discover_menu_language_packs(tmp_path)
    assert menu_text(packs["ja"], "menu.home") == "ホーム"
    assert menu_text(packs["ja"], "menu.export") == "시험지 출력"
    assert "unknown" not in packs["ja"].strings


def test_broken_external_pack_is_excluded_without_blocking_startup(tmp_path):
    pack_dir = tmp_path / "data" / "language_packs" / "menu"
    pack_dir.mkdir(parents=True)
    (pack_dir / "broken.json").write_text("{", encoding="utf-8")
    packs, warnings = discover_menu_language_packs(tmp_path)
    assert set(packs) >= {"ko", "en"}
    assert any("broken.json" in warning for warning in warnings)


def test_menu_locale_setting_round_trips_and_unknown_value_falls_back(tmp_path):
    save_menu_locale(tmp_path, "en", {"ko", "en"})
    assert load_menu_locale(tmp_path, {"ko", "en"}) == "en"
    settings = tmp_path / "data" / "app_settings.json"
    settings.write_text('{"menu_locale":"xx"}', encoding="utf-8")
    assert load_menu_locale(tmp_path, {"ko", "en"}) == "ko"
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_menu_language.py -q`

Expected: collection fails because `src.gui.menu_language` does not exist.

- [x] **Step 3: Implement immutable packs, strict JSON validation, Korean fallback, and atomic settings write**

```python
MENU_KEYS = (
    "menu.home",
    "menu.question_management",
    "menu.practice",
    "menu.export",
    "menu.import",
    "menu.question_bank_connections",
    "menu.codex",
    "menu.settings",
)


@dataclass(frozen=True)
class MenuLanguagePack:
    locale: str
    display_name: str
    version: int
    strings: Mapping[str, str]


def menu_text(pack: MenuLanguagePack, key: str) -> str:
    value = pack.strings.get(key)
    return value if isinstance(value, str) and value.strip() else KOREAN_MENU_STRINGS[key]


def save_menu_locale(base_dir, locale, available_locales):
    if locale not in set(available_locales):
        raise ValueError(f"지원하지 않는 메뉴 언어입니다: {locale}")
    target = Path(base_dir) / "data" / "app_settings.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"menu_locale": locale}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
```

`discover_menu_language_packs()`는 `assets/language_packs/menu`의 기본 팩을 먼저 읽고 `data/language_packs/menu`의 외부 팩을 추가한다. locale은 영문·숫자·`-`·`_`만 허용하고, `strings`는 `MENU_KEYS`에 속하는 비어 있지 않은 문자열만 보관한다. 외부 팩 오류는 경고 목록에만 추가한다.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_menu_language.py -q`

Expected: all menu-language tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/menu_language.py assets/language_packs/menu/ko.json assets/language_packs/menu/en.json tests/test_menu_language.py
git commit -m "feat: add safe menu language packs"
```

### Task 2: 설정 대화상자와 MainWindow 메뉴 즉시 전환

**Files:**
- Create: `src/gui/interface/settings.py`
- Modify: `src/gui/main.py`
- Modify: `tests/test_main_window_layout.py`
- Create: `tests/test_settings_interface.py`

**Interfaces:**
- Consumes: Task 1의 `discover_menu_language_packs`, `load_menu_locale`, `save_menu_locale`, `menu_text`
- Produces: `SettingsDialog(packs: Mapping[str, MenuLanguagePack], current_locale: str, warnings: Sequence[str], parent=None)`
- Produces: `SettingsDialog.selected_locale() -> str`
- Produces: `MainWindow.open_settings()` 및 `MainWindow.apply_menu_locale(locale: str)`

- [x] **Step 1: Write failing settings and navigation application tests**

```python
def test_settings_dialog_lists_packs_and_returns_selected_locale():
    dialog = SettingsDialog(
        packs={"ko": _pack("ko", "한국어"), "en": _pack("en", "English")},
        current_locale="ko",
        warnings=[],
    )
    assert [dialog.languageCombo.itemData(i) for i in range(dialog.languageCombo.count())] == ["ko", "en"]
    dialog.languageCombo.setCurrentIndex(1)
    assert dialog.selected_locale() == "en"


def test_apply_menu_pack_updates_existing_navigation_items_only():
    navigation = _NavigationStub(MENU_ROUTE_KEYS)
    apply_menu_pack(navigation, ENGLISH_PACK)
    assert navigation.widget("HomeInterface").text() == "Home"
    assert navigation.widget("DbMountInterface").text() == "Question Bank Connections"
    assert navigation.widget("CodexToggle").text() == "Codex"


def test_main_window_settings_action_is_connected():
    source = gui_main.__loader__.get_source(gui_main.__name__)
    assert "onClick=self.open_settings" in source
    assert "save_menu_locale" in source
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings_interface.py tests/test_main_window_layout.py -q`

Expected: settings module and menu application functions are missing.

- [x] **Step 3: Implement settings dialog and route-key mapping**

```python
MENU_ROUTE_KEYS = {
    "HomeInterface": "menu.home",
    "BrowserInterface": "menu.question_management",
    "PracticeInterface": "menu.practice",
    "ExportInterface": "menu.export",
    "ImportInterface": "menu.import",
    "DbMountInterface": "menu.question_bank_connections",
    "CodexToggle": "menu.codex",
    "Settings": "menu.settings",
}


def apply_menu_pack(navigation_interface, pack):
    for route_key, text_key in MENU_ROUTE_KEYS.items():
        widget = navigation_interface.widget(route_key)
        if widget is not None:
            widget.setText(menu_text(pack, text_key))
```

`SettingsDialog`는 `메뉴 언어` 콤보, 경고 표시, `적용`, `취소` 버튼만 가진다. MainWindow는 인터페이스 생성 전에 팩과 저장 locale을 읽고, 탐색 메뉴 생성 직후 선택 팩을 적용한다. `open_settings()`는 accepted일 때만 설정을 원자적으로 저장하고 메뉴를 다시 그린다. 팩 오류는 한국어 InfoBar의 `확인 필요` 알림으로 표시하되 앱 시작을 막지 않는다.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_settings_interface.py tests/test_main_window_layout.py -q`

Expected: all settings and main-window tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/interface/settings.py src/gui/main.py tests/test_settings_interface.py tests/test_main_window_layout.py
git commit -m "feat: add menu language setting"
```

### Task 3: 문제 관리·문제 풀이·시험지 출력의 한국어 UX

**Files:**
- Modify: `src/gui/interface/browser.py`
- Modify: `src/gui/interface/practice.py`
- Modify: `src/gui/interface/export.py`
- Modify: `tests/test_browser_filters.py`
- Modify: `tests/test_practice_interface.py`
- Modify: `tests/test_export_interface.py`

**Interfaces:**
- Produces: 각 화면의 `repositoryStatusLabel`
- Produces: `ExportInterface.singleExamModeCheck`, 기존 호환 `ExportInterface.multiExamModeCheck`
- Produces: `ExportInterface.selectionSummaryLabel` 및 `_update_selection_summary()`

- [x] **Step 1: Write failing UI-copy, mode-discovery, and summary tests**

```python
def test_browser_uses_korean_filters_and_independent_search_row(repo):
    widget = BrowserInterface(repo.db_path)
    assert widget.examFilterLabel.text() == "시험 종류"
    assert widget.subjectFilterLabel.text() == "과목"
    assert widget.searchBox.placeholderText() == "해시태그 또는 문제 내용 검색"
    assert widget.vBoxLayout.indexOf(widget.searchRowWidget) >= 0


def test_practice_labels_problem_bank_and_hashtag(repo):
    widget = PracticeInterface(repo.db_path)
    assert "문제은행" in widget.repositoryStatusLabel.text()
    assert widget.tagFilter.placeholderText() == "#계산, #SOLAS"
    assert widget.tagFilterLabel.text() == "해시태그 필터"


def test_export_exposes_two_korean_composition_modes(repository):
    widget = ExportInterface(repository=repository)
    assert widget.singleExamModeCheck.text() == "한 시험에서 구성"
    assert widget.multiExamModeCheck.text() == "여러 시험의 과목을 조합"
    assert widget.singleExamModeCheck.isChecked()
    widget.multiExamModeCheck.setChecked(True)
    assert widget._is_multi_exam_mode() is True


def test_export_selection_summary_counts_checked_rows(repository):
    widget = ExportInterface(repository=repository)
    widget.multiExamModeCheck.setChecked(True)
    first = widget.subjectSelectionRows[0]
    first["checkbox"].setChecked(True)
    first["count_spin"].setValue(7)
    assert widget.selectionSummaryLabel.text() == "선택 1과목 · 예상 7문항"
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browser_filters.py tests/test_practice_interface.py tests/test_export_interface.py -q`

Expected: Korean labels, status labels, the single-mode radio button, and selection summary are missing.

- [x] **Step 3: Implement Korean labels and discoverable composition controls**

```python
self.compositionModeLabel = BodyLabel("구성 방식", self)
self.singleExamModeCheck = QRadioButton("한 시험에서 구성", self)
self.multiExamModeCheck = QRadioButton("여러 시험의 과목을 조합", self)
self.singleExamModeCheck.setChecked(True)
self.compositionModeGroup = QButtonGroup(self)
self.compositionModeGroup.addButton(self.singleExamModeCheck)
self.compositionModeGroup.addButton(self.multiExamModeCheck)
self.multiExamModeCheck.toggled.connect(self._on_multi_exam_mode_changed)


def _update_selection_summary(self):
    selected = 0
    total = 0
    for row in self.subjectSelectionRows:
        if row["checkbox"].isChecked():
            selected += 1
            total += int(row["count_spin"].value())
    self.selectionSummaryLabel.setText(f"선택 {selected}과목 · 예상 {total}문항")
```

Export의 제목, 설명, 입력 라벨, placeholder, 표 머리글, 파일 대화상자와 모든 InfoBar를 한국어로 바꾼다. 부족 문항 오류는 `요청 N문항 / 사용 가능 M문항`을 포함한다. `여러 시험의 과목을 조합` 선택 시 기존 multi-exam boolean과 같은 경로를 사용하고 관련 없는 단일 시험 컨트롤의 비활성화 툴팁을 제공한다.

Browser의 `EXAM`, `SUBJECT`, `태그/문항/선지 검색`, `서술형 추가`, `선택 삭제`, `DB ... 실패`를 합의 용어로 바꾸고, 검색 행을 `searchRowWidget`으로 독립 유지한다. Repository filter options의 `mount_label`을 모아 `연결된 문제은행: ...`를 표시하고 없으면 `현재 문제은행: 기본 문제은행`을 표시한다.

Practice의 `시험`, `연도 범위`, `태그 필터`를 `시험 종류`, `출제 연도 범위`, `해시태그 필터`로 바꾸고 같은 방식의 문제은행 상태를 표시한다. 기존 문제 선택·채점 로직은 변경하지 않는다.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_browser_filters.py tests/test_mounted_browser.py tests/test_practice_interface.py tests/test_mounted_practice.py tests/test_export_interface.py -q`

Expected: all three interfaces and mounted repository regressions pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/interface/browser.py src/gui/interface/practice.py src/gui/interface/export.py tests/test_browser_filters.py tests/test_practice_interface.py tests/test_export_interface.py
git commit -m "feat: improve core workflow Korean UX"
```

### Task 4: 문제 가져오기와 문제은행 연결 관리의 작업 흐름 정리

**Files:**
- Modify: `src/gui/interface/import_view.py`
- Modify: `src/gui/interface/db_mount.py`
- Modify: `tests/test_db_mount_interface.py`
- Create: `tests/test_import_interface.py`

**Interfaces:**
- Produces: `ImportInterface.stepLabel`, `ImportInterface.qualitySummaryLabel`
- Produces: `DbMountInterface.connectionStatusLabel` 및 `_update_connection_status()`

- [x] **Step 1: Write failing terminology, step, and status tests**

```python
def test_import_interface_shows_three_step_workflow(tmp_path):
    widget = ImportInterface(str(tmp_path / "exam_bank.db"))
    assert widget.stepLabel.text() == "1. 파일 선택  →  2. 분석 및 검수  →  3. 문제은행에 저장"
    assert widget.parseBtn.text() == "분석 및 검수 시작"
    assert widget.saveBtn.text() == "문제은행에 저장"


def test_question_bank_connection_screen_has_no_legacy_ui_terms(tmp_path):
    widget, _manifest = _make_mount_interface(tmp_path)
    assert widget.titleLabel.text() == "문제은행 연결 관리"
    assert widget.sourceLabel.text() == "원본 문제은행"
    assert widget.targetLabel.text() == "대상 문제은행"
    assert widget.examLabel.text() == "시험 종류"
    assert widget.dryRunBtn.text() == "연결 사전 검사"
    assert "문제은행" in widget.connectionStatusLabel.text()
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_import_interface.py tests/test_db_mount_interface.py -q`

Expected: workflow and connection-status widgets are missing and legacy text remains.

- [x] **Step 3: Implement Korean workflow and connection state**

```python
self.stepLabel = BodyLabel(
    "1. 파일 선택  →  2. 분석 및 검수  →  3. 문제은행에 저장",
    self,
)
self.qualitySummaryLabel = BodyLabel("분석 전", self)


def _update_connection_status(self):
    active = len(self.active_mounts)
    writable = sum(not mount.read_only for mount in self.active_mounts)
    self.connectionStatusLabel.setText(
        f"연결된 문제은행 {active}개 · 쓰기 가능 {writable}개"
    )
```

Import는 validation 결과를 이용해 `전체`, `정상`, `검토 필요` 수를 표시하고, 자동 교정 수가 result 통계에 존재할 때만 `자동 교정`을 추가한다. `Error`, `DB 저장`, `데이터베이스` 표현은 각각 `검토 필요`, `문제은행에 저장`, `문제은행`으로 바꾼다.

DbMount의 화면 제목, 설명, 라벨, 버튼, placeholder, 로그, 대화상자, InfoBar에서 `DB`, `Mount`, `Source`, `Target`, `Exam`, `Dry-run`을 합의한 사용자 용어로 바꾼다. 내부 변수명, manifest 파일명, `.db` 확장자 필터와 backend 예외 문자열은 변경하지 않는다. 활성 연결이 바뀔 때마다 상태 라벨을 갱신하고 읽기 전용 여부를 텍스트로 표시한다.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_import_interface.py tests/test_db_mount_interface.py tests/test_db_mount_management.py tests/test_db_mount_prototype.py -q`

Expected: import and all problem-bank management tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/interface/import_view.py src/gui/interface/db_mount.py tests/test_import_interface.py tests/test_db_mount_interface.py
git commit -m "feat: clarify import and question bank UX"
```

### Task 5: 편집창·Codex 패널·공통 상태 문구 통일

**Files:**
- Modify: `src/gui/interface/editor.py`
- Modify: `src/gui/interface/codex_panel.py`
- Modify: `tests/test_editor_layout.py`
- Modify: `tests/test_codex_panel.py`

**Interfaces:**
- Preserves: 편집창 이미지 변경·붙여넣기·복사·삭제와 문제별 다중 창 API
- Preserves: Codex worker, 모델명, sandbox/approval data 값
- Produces: 사용자 노출 채팅 블록 제목 `사용자`, `시스템`, `오류`

- [x] **Step 1: Write failing copy and preservation tests**

```python
def test_editor_uses_hashtag_and_explicit_image_action_labels():
    editor = QuestionEditor(_question_editor_data(), subject_options=[])
    assert editor.tagsSectionLabel.text() == "해시태그"
    assert editor.tagsInput.placeholderText() == "해시태그 (쉼표로 구분)"
    assert editor.btnCopyImage.text() == "클립보드에 복사"


def test_codex_panel_uses_korean_user_system_and_error_titles(tmp_path):
    widget = CodexInterface(tmp_path, side_panel=True)
    widget._append_block(USER_BLOCK_TITLE, "질문")
    widget._append_block(SYSTEM_BLOCK_TITLE, "상태")
    widget._append_block(ERROR_BLOCK_TITLE, "실패")
    assert [block["title"] for block in widget._chat_blocks[-3:]] == ["사용자", "시스템", "오류"]
    assert widget.newThreadButton.text() == "새 작업"
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py tests/test_codex_panel.py -q`

Expected: legacy `태그`, compact copy label, and English block titles fail assertions.

- [x] **Step 3: Implement consistent editor and Codex copy**

```python
USER_BLOCK_TITLE = "사용자"
SYSTEM_BLOCK_TITLE = "시스템"
ERROR_BLOCK_TITLE = "오류"
```

Editor의 `태그` 표현을 `해시태그`로 바꾸고 이미지 버튼을 `이미지 변경`, `붙여넣기`, `클립보드에 복사`, `삭제`로 통일한다. 버튼 간격과 최소 너비를 같게 하되 기존 clipboard와 다중 편집창 signal을 변경하지 않는다.

Codex 패널의 `Model`, `You`, `System`, `Error`, `Thread`, `Images`, `Code`를 각각 `모델`, `사용자`, `시스템`, `오류`, `작업`, `이미지`, `코드`로 표시한다. 모델명과 backend data 값은 유지한다. `새 Thread`는 `새 작업`, 기술 오류는 InfoBar의 원인 요약과 채팅 블록의 상세 내용으로 남긴다.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/test_editor_layout.py tests/test_codex_panel.py -q`

Expected: all editor and Codex tests pass.

- [x] **Step 5: Commit**

```powershell
git add -- src/gui/interface/editor.py src/gui/interface/codex_panel.py tests/test_editor_layout.py tests/test_codex_panel.py
git commit -m "feat: unify editor and Codex Korean copy"
```

### Task 6: 패키징, 정적 문구 감사, 실제 실행 및 전체 회귀 검증

**Files:**
- Modify: `ExamGenerator.spec`
- Create: `tests/test_gui_copy_audit.py`
- Modify: `tests/test_launchers.py`
- Modify: `docs/superpowers/plans/2026-07-16-korean-first-ui-and-menu-language-pack.md`

**Interfaces:**
- Consumes: 모든 앞선 UI와 언어 팩 구현
- Produces: PyInstaller 배포물의 기본 메뉴 팩

- [x] **Step 1: Write failing packaging and visible-copy audit tests**

```python
def test_pyinstaller_bundles_builtin_menu_language_packs():
    spec = Path("ExamGenerator.spec").read_text(encoding="utf-8")
    assert "assets\\language_packs\\menu\\*.json" in spec


def test_gui_source_has_no_disallowed_visible_legacy_copy():
    visible_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path("src/gui/interface")).glob("*.py")
    )
    for legacy in (
        'BodyLabel("EXAM"',
        'BodyLabel("SUBJECT"',
        'SubtitleLabel("Export Exam',
        'PushButton("Export"',
        'SubtitleLabel("DB Mount',
        'BodyLabel("Source"',
        'BodyLabel("Target"',
        'PushButton("Dry-run"',
        'BodyLabel("Model"',
    ):
        assert legacy not in visible_sources
```

- [x] **Step 2: Run tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/test_gui_copy_audit.py tests/test_launchers.py -q`

Expected: language-pack asset pattern is absent from the spec before implementation.

- [x] **Step 3: Bundle JSON resources and complete the copy audit**

```python
datas = [
    ('src\\database\\schema.sql', 'src\\database'),
    ('src\\database\\seed.sql', 'src\\database'),
    ('src\\parser\\tessdata\\*.traineddata', 'src\\parser\\tessdata'),
    ('assets\\icons\\exam_generator_icon.ico', 'assets\\icons'),
    ('assets\\language_packs\\menu\\*.json', 'assets\\language_packs\\menu'),
]
```

정적 감사에는 사용자 노출 위젯 생성 문자열만 포함해 내부 `db_path`, Repository 오류, manifest와 파일 확장자까지 오탐하지 않게 한다. `Run_Latest_App.bat`가 source `scripts/run_gui.py`를 실행하는 기존 검증을 유지한다.

- [x] **Step 4: Run focused and full automated verification**

Run: `.venv\Scripts\python.exe -m pytest tests/test_gui_copy_audit.py tests/test_launchers.py -q`

Expected: focused tests pass.

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: full suite passes with zero failures.

- [x] **Step 5: Run source launcher smoke checks**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\smoke_test_gui.ps1` if the script exists; otherwise launch `Run_Latest_App.bat`, confirm the main window responds, and close only the process started by this check.

Expected: the app opens with Korean menus, Settings changes only menu labels to English and back, Export exposes both composition modes, and no control is clipped at 100% or 125% scaling.

- [x] **Step 6: Mark completed plan checkboxes and commit**

```powershell
git add -- ExamGenerator.spec tests/test_gui_copy_audit.py tests/test_launchers.py docs/superpowers/plans/2026-07-16-korean-first-ui-and-menu-language-pack.md
git commit -m "test: verify Korean UI language pack integration"
```

## Final Verification Checklist

- [x] Re-read `docs/superpowers/specs/2026-07-16-korean-first-ui-and-menu-language-pack-design.md` and map every requirement to a completed task.
- [x] Run `git diff --check` and confirm no whitespace errors.
- [x] Run `.venv\Scripts\python.exe -m pytest -q` fresh and record the pass count.
- [x] Run `git status --short` and confirm the only unrelated path is the user-owned untracked problem-bank ZIP.
- [x] Inspect the final commit list and verify every production change has a preceding RED test in the execution log.
