# 다중 셀 표 편집기 및 DOCX 자동 배치 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 문제 수정 창에서 표의 행·열 추가/삭제, 사각형 병합/분할, 수동 열 너비 저장을 지원하고, DOCX 출력 시 수동·원본·내용 기반 우선순위에 따라 고정 폭과 2단/1단 배치를 계산한다.

**Architecture:** `src/parser/table_structure.py`가 schema-v2 표 dict의 모든 구조 변경을 순수 함수로 담당하고, `src/exporter/table_layout.py`가 Qt 및 python-docx에 의존하지 않는 폭 계산을 담당한다. `src/gui/table_editor.py`는 `QTableWidget`의 선택과 헤더 폭을 구조 모듈 호출로 변환하며, `src/gui/interface/editor.py`는 편집 결과를 기존 format payload에 교체 저장한다. `src/exporter/docx.py`는 계산 결과만 받아 OpenXML 고정 폭과 임시 1단 section을 적용한다.

**Tech Stack:** Python 3, PyQt5, qfluentwidgets, python-docx, lxml, pytest

## Global Constraints

- 기존 schema version은 2로 유지하고 DB column migration을 만들지 않는다.
- 기존 `<보기>` 1셀 표, PDF 파싱 표, 알 수 없는 forward-compatible metadata를 보존한다.
- 구조 연산과 폭 계산은 입력 dict를 직접 변경하지 않고 새 dict를 반환한다.
- 표의 `rows`는 항상 최소 `1 × 1` 직사각형이며, `cells`는 덮인 병합 셀을 제외한 모든 origin을 갖는다.
- 병합 영역과 교차하는 행·열 삽입/삭제는 암묵적으로 span을 변경하지 않고 `TableStructureError`로 차단한다.
- DOCX 계산 실패는 해당 표를 균등 폭으로 fallback하고 warning을 남기며 전체 export를 중단하지 않는다.
- 사용자 소유 파일 `exam_bank.maritime_domain.20260705_175510.examdb.zip`은 stage, 수정, 삭제하지 않는다.
- 구현 중 feature commit은 허용하되 GitHub push와 main 병합은 별도 요청 전까지 하지 않는다.

---

## Task 1: schema-v2 폭 모드 정규화

**Files:**

- Modify: `src/parser/table_format.py`
- Modify: `tests/test_table_format.py`

- [ ] **Step 1: legacy 폭 모드 회귀 테스트 작성**

`tests/test_table_format.py`에 다음 사례를 추가한다.

```python
def test_normalization_infers_source_width_mode_from_legacy_widths():
    table = normalize_table_spec({
        "rows": [["A", "B"]],
        "column_widths": [3, 1],
    })

    assert table["column_widths"] == [0.75, 0.25]
    assert table["layout"]["width_mode"] == "source"


def test_invalid_widths_fall_back_to_auto_mode():
    table = normalize_table_spec({
        "rows": [["A", "B"]],
        "column_widths": [1, 0],
        "layout": {"width_mode": "manual", "wide": True},
    })

    assert table["column_widths"] == []
    assert table["layout"] == {"width_mode": "auto", "wide": True}


def test_explicit_auto_mode_ignores_but_preserves_valid_source_widths():
    table = normalize_table_spec({
        "rows": [["A", "B"]],
        "column_widths": [0.4, 0.6],
        "layout": {"width_mode": "auto"},
    })

    assert table["column_widths"] == [0.4, 0.6]
    assert table["layout"]["width_mode"] == "auto"
```

- [ ] **Step 2: 테스트가 현재 실패하는지 확인**

Run:

```powershell
python -m pytest tests/test_table_format.py -q
```

Expected: 새 `layout.width_mode` 단언들이 실패한다.

- [ ] **Step 3: 폭 정규화 helper와 layout 정규화 구현**

`src/parser/table_format.py`에 양수이고 열 수와 일치하는 폭만 합계 1로 만드는 helper를 추가한다.

```python
TABLE_WIDTH_MODES = {"auto", "source", "manual"}


def _normalized_widths(value: Any, column_count: int) -> list[float]:
    numbers = _clean_numbers(value)
    if column_count < 1 or len(numbers) != column_count or any(number <= 0 for number in numbers):
        return []
    total = sum(numbers)
    if total <= 0:
        return []
    return [number / total for number in numbers]
```

`normalize_table_spec()`에서 `rows` 열 수를 계산한 뒤 다음 규칙으로 저장한다.

```python
column_count = max((len(row) for row in normalized["rows"]), default=0)
normalized["column_widths"] = _normalized_widths(
    normalized.get("column_widths"), column_count
)
layout = _as_dict(normalized.get("layout"))
requested_mode = str(layout.get("width_mode") or "").lower()
if requested_mode not in TABLE_WIDTH_MODES:
    requested_mode = "source" if normalized["column_widths"] else "auto"
if requested_mode in {"manual", "source"} and not normalized["column_widths"]:
    requested_mode = "auto"
layout["width_mode"] = requested_mode
layout["wide"] = bool(layout.get("wide", False))
normalized["layout"] = layout
```

- [ ] **Step 4: targeted 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_table_format.py -q
```

Expected: 모든 `tests/test_table_format.py` 테스트 통과.

- [ ] **Step 5: local feature commit**

```powershell
git add src/parser/table_format.py tests/test_table_format.py
git commit -m "feat: normalize table width modes"
```

---

## Task 2: 순수 표 구조 모델과 행·열 연산

**Files:**

- Create: `src/parser/table_structure.py`
- Create: `tests/test_table_structure.py`

- [ ] **Step 1: 직사각형 정규화와 행·열 삽입 실패 테스트 작성**

`tests/test_table_structure.py`를 만들고 다음 공개 API를 기준으로 테스트한다.

```python
import pytest

from src.parser.table_structure import (
    TableStructureError,
    insert_column,
    insert_row,
    normalize_rectangular_table,
)


def _table():
    return {
        "id": "t1",
        "rows": [["A", "B"], ["C", "D"]],
        "cells": [
            {"row": row, "col": col, "text": text, "row_span": 1, "col_span": 1}
            for row, values in enumerate([["A", "B"], ["C", "D"]])
            for col, text in enumerate(values)
        ],
        "column_widths": [0.6, 0.4],
        "layout": {"width_mode": "source"},
        "custom": {"keep": True},
    }


def test_normalize_repairs_ragged_rows_and_preserves_unknown_metadata():
    result = normalize_rectangular_table({"rows": [["A"], ["B", "C"]], "custom": 7})

    assert result["rows"] == [["A", ""], ["B", "C"]]
    assert [(cell["row"], cell["col"]) for cell in result["cells"]] == [
        (0, 0), (0, 1), (1, 0), (1, 1)
    ]
    assert result["custom"] == 7


def test_insert_row_above_moves_existing_cells_without_mutating_input():
    original = _table()
    result = insert_row(original, 1)

    assert result["rows"] == [["A", "B"], ["", ""], ["C", "D"]]
    assert original["rows"] == [["A", "B"], ["C", "D"]]


def test_insert_column_scales_old_widths_and_assigns_new_share():
    result = insert_column(_table(), 1)

    assert result["rows"] == [["A", "", "B"], ["C", "", "D"]]
    assert result["column_widths"] == pytest.approx([0.4, 1 / 3, 4 / 15])
    assert sum(result["column_widths"]) == pytest.approx(1.0)
```

- [ ] **Step 2: 신규 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_table_structure.py -q
```

Expected: `src.parser.table_structure` import 실패.

- [ ] **Step 3: 구조 기본 API 구현**

`src/parser/table_structure.py`에 `TableStructureError(code, message)`,
`normalize_column_widths(widths, column_count)`,
`normalize_rectangular_table(table)`, `insert_row(table, index)`,
`insert_column(table, index)`의 공개 계약을 구현한다. `TableStructureError`는
`ValueError`를 상속하고 호출자가 분기할 수 있도록 `code` 속성을 보존한다.

구현 규칙:

- `copy.deepcopy()`로 시작하여 알 수 없는 metadata를 유지한다.
- 빈/손상 rows는 `[[""]]`로 복구한다.
- 열 수는 최소 1이고 모든 row를 빈 문자열로 pad한다.
- 기존 cell의 정렬·source metadata는 같은 origin 좌표에서 보존한다.
- 새 일반 cell 기본값은 `row_span=1`, `col_span=1`, `horizontal_alignment="left"`, `vertical_alignment="center"`이다.
- 삽입 index는 `0..row_count` 또는 `0..column_count` 범위를 허용한다.
- 병합 span 내부를 가르는 index이면 `TableStructureError("merged_region_conflict", "병합 셀을 먼저 분할하세요.")`를 발생시킨다.

- [ ] **Step 4: 행·열 삽입 테스트 통과 확인**

Run:

```powershell
python -m pytest tests/test_table_structure.py -q
```

Expected: 작성한 3개 테스트 통과.

- [ ] **Step 5: local feature commit**

```powershell
git add src/parser/table_structure.py tests/test_table_structure.py
git commit -m "feat: add rectangular table structure operations"
```

---

## Task 3: 행·열 삭제와 병합 충돌 보호

**Files:**

- Modify: `src/parser/table_structure.py`
- Modify: `tests/test_table_structure.py`

- [ ] **Step 1: 삭제 동작 실패 테스트 추가**

```python
from src.parser.table_structure import delete_columns, delete_rows


def test_delete_multiple_rows_reindexes_remaining_cells():
    table = normalize_rectangular_table({
        "rows": [["A"], ["B"], ["C"], ["D"]]
    })

    result = delete_rows(table, [1, 2])

    assert result["rows"] == [["A"], ["D"]]
    assert [(cell["row"], cell["text"]) for cell in result["cells"]] == [(0, "A"), (1, "D")]


def test_delete_column_renormalizes_stored_widths():
    result = delete_columns(_table(), [0])

    assert result["rows"] == [["B"], ["D"]]
    assert result["column_widths"] == [1.0]


@pytest.mark.parametrize(
    ("operation", "indices"),
    [(delete_rows, [0, 1]), (delete_columns, [0, 1])],
)
def test_deleting_last_dimension_is_rejected(operation, indices):
    with pytest.raises(TableStructureError, match="최소 1개") as error:
        operation(_table(), indices)

    assert error.value.code == "minimum_table_size"


def test_structural_change_through_merged_region_is_rejected():
    table = {
        "rows": [["AB", ""], ["C", "D"]],
        "cells": [
            {"row": 0, "col": 0, "text": "AB", "row_span": 1, "col_span": 2},
            {"row": 1, "col": 0, "text": "C", "row_span": 1, "col_span": 1},
            {"row": 1, "col": 1, "text": "D", "row_span": 1, "col_span": 1},
        ],
    }

    with pytest.raises(TableStructureError) as error:
        insert_column(table, 1)

    assert error.value.code == "merged_region_conflict"
```

- [ ] **Step 2: 삭제 API 구현**

공개 함수 `delete_rows(table, indices)`와
`delete_columns(table, indices)`를 구현한다.

구현 규칙:

- 중복 index를 제거하고 오름차순 검증 후 내부 제거는 내림차순으로 수행한다.
- 하나 이상의 행과 열을 반드시 남긴다.
- 삭제 대상이 병합 span의 일부 또는 전체와 교차하면 모두 차단한다. 사용자가 먼저 명시적으로 분할해야 한다.
- 열 삭제 후 저장 폭이 유효하면 남은 폭만 합계 1로 재정규화한다.
- `manual`/`source`인데 폭이 손상되면 `column_widths=[]`, `width_mode="auto"`로 복구한다.

- [ ] **Step 3: targeted 테스트 실행**

Run:

```powershell
python -m pytest tests/test_table_structure.py -q
```

Expected: 삭제·충돌 테스트 포함 전부 통과.

- [ ] **Step 4: local feature commit**

```powershell
git add src/parser/table_structure.py tests/test_table_structure.py
git commit -m "feat: support safe table row and column deletion"
```

---

## Task 4: 사각형 병합과 원문 복원 분할

**Files:**

- Modify: `src/parser/table_structure.py`
- Modify: `tests/test_table_structure.py`

- [ ] **Step 1: 병합·분할 실패 테스트 추가**

```python
from src.parser.table_structure import merge_cells, split_cell


def test_merge_rectangle_combines_text_and_keeps_exact_backup():
    result = merge_cells(_table(), 0, 0, 1, 1)
    origin = result["cells"][0]

    assert result["rows"] == [["A\nB\nC\nD", ""], ["", ""]]
    assert origin["row_span"] == 2
    assert origin["col_span"] == 2
    assert origin["merge_backup"] == [
        {"row": 0, "col": 0, "text": "A"},
        {"row": 0, "col": 1, "text": "B"},
        {"row": 1, "col": 0, "text": "C"},
        {"row": 1, "col": 1, "text": "D"},
    ]


def test_split_restores_original_cell_text_from_backup():
    result = split_cell(merge_cells(_table(), 0, 0, 1, 1), 0, 0)

    assert result["rows"] == [["A", "B"], ["C", "D"]]
    assert all(cell["row_span"] == cell["col_span"] == 1 for cell in result["cells"])


def test_split_without_backup_keeps_text_only_in_origin():
    table = {
        "rows": [["HEADER", ""]],
        "cells": [{"row": 0, "col": 0, "text": "HEADER", "row_span": 1, "col_span": 2}],
    }

    assert split_cell(table, 0, 0)["rows"] == [["HEADER", ""]]


def test_merge_rejects_single_cell_and_partial_existing_merge():
    with pytest.raises(TableStructureError) as single:
        merge_cells(_table(), 0, 0, 0, 0)
    assert single.value.code == "merge_requires_multiple_cells"

    merged = merge_cells(_table(), 0, 0, 0, 1)
    with pytest.raises(TableStructureError) as overlap:
        merge_cells(merged, 0, 1, 1, 1)
    assert overlap.value.code == "merged_region_conflict"


def test_split_requires_merged_origin():
    with pytest.raises(TableStructureError) as error:
        split_cell(_table(), 0, 0)
    assert error.value.code == "split_requires_merged_origin"
```

- [ ] **Step 2: 병합과 분할 API 구현**

공개 함수 `merge_cells(table, top, left, bottom, right)`와
`split_cell(table, row, col)`을 구현한다.

구현 규칙:

- 좌표를 정렬해 직사각형으로 만들고 최소 2셀인지 검사한다.
- 선택 사각형이 기존 병합 영역을 정확히 전부 포함하는 경우도 중첩 병합으로 해석해 차단한다.
- `merge_backup`은 선택된 모든 논리 셀의 row/col/text를 행 우선으로 보존한다.
- 화면 text는 비어 있지 않은 문자열만 `\n`으로 결합한다.
- origin 외 덮인 위치는 `rows`에서 빈 문자열로 만들고 `cells`에서 제거한다.
- 분할은 origin의 span 크기만큼 기본 cell을 다시 만들고 backup이 있으면 좌표별 text를 복원한다.

- [ ] **Step 3: targeted 테스트 실행**

Run:

```powershell
python -m pytest tests/test_table_structure.py -q
```

Expected: 병합·분할 및 기존 구조 테스트 전부 통과.

- [ ] **Step 4: local feature commit**

```powershell
git add src/parser/table_structure.py tests/test_table_structure.py
git commit -m "feat: add reversible table cell merge and split"
```

---

## Task 5: 수동 열 너비와 자동 모드 전환

**Files:**

- Modify: `src/parser/table_structure.py`
- Modify: `tests/test_table_structure.py`

- [ ] **Step 1: 폭 상태 API 실패 테스트 추가**

```python
from src.parser.table_structure import set_auto_width_mode, set_manual_column_widths


def test_header_pixel_widths_are_saved_as_manual_ratios():
    result = set_manual_column_widths(_table(), [180, 60])

    assert result["column_widths"] == pytest.approx([0.75, 0.25])
    assert result["layout"]["width_mode"] == "manual"


def test_auto_mode_keeps_width_metadata_but_marks_it_non_authoritative():
    manual = set_manual_column_widths(_table(), [180, 60])
    result = set_auto_width_mode(manual)

    assert result["column_widths"] == pytest.approx([0.75, 0.25])
    assert result["layout"]["width_mode"] == "auto"


@pytest.mark.parametrize("widths", ([100], [100, 0], ["bad", 10]))
def test_invalid_manual_header_widths_are_rejected(widths):
    with pytest.raises(TableStructureError) as error:
        set_manual_column_widths(_table(), widths)
    assert error.value.code == "invalid_column_widths"
```

- [ ] **Step 2: 폭 API 구현**

공개 함수 `set_manual_column_widths(table, pixel_widths)`와
`set_auto_width_mode(table)`를 구현한다.

`set_manual_column_widths`는 열 수 일치, 유한 양수, 합계 양수를 검증하고 정규화한다. `set_auto_width_mode`는 폭 값을 지우지 않고 `layout.width_mode`만 `auto`로 바꿔 사용자가 다시 수동 모드로 돌아올 때 참고할 수 있게 한다.

- [ ] **Step 3: 구조 모듈 전체 테스트 확인**

Run:

```powershell
python -m pytest tests/test_table_structure.py tests/test_table_format.py -q
```

Expected: 전부 통과.

- [ ] **Step 4: local feature commit**

```powershell
git add src/parser/table_structure.py tests/test_table_structure.py
git commit -m "feat: persist manual table column widths"
```

---

## Task 6: 독립 다중 셀 표 편집 대화상자

**Files:**

- Create: `src/gui/table_editor.py`
- Create: `tests/test_table_editor_dialog.py`

- [ ] **Step 1: 버튼·선택 연산 GUI 실패 테스트 작성**

`tests/test_table_editor_dialog.py`에서 기존 GUI 테스트 방식처럼 전역 `QApplication`을 만든다.

```python
from PyQt5.QtCore import QItemSelectionModel
from PyQt5.QtWidgets import QApplication, QAbstractItemView

from src.gui.table_editor import TableEditorDialog


APP = QApplication.instance() or QApplication([])


def _dialog():
    dialog = TableEditorDialog({"id": "t1", "rows": [["A"]]})
    dialog.show()
    APP.processEvents()
    return dialog


def test_dialog_exposes_all_structure_actions():
    dialog = _dialog()

    assert [button.text() for button in dialog.structure_buttons] == [
        "위에 행 추가", "아래에 행 추가", "왼쪽에 열 추가", "오른쪽에 열 추가",
        "선택 행 삭제", "선택 열 삭제", "셀 병합", "셀 분할", "폭 자동 맞춤",
    ]


def test_add_below_and_right_expands_one_cell_table():
    dialog = _dialog()
    dialog.grid.setCurrentCell(0, 0)

    dialog.add_row_below()
    dialog.add_column_right()

    assert dialog.table_spec["rows"] == [["A", ""], ["", ""]]
    assert dialog.grid.rowCount() == 2
    assert dialog.grid.columnCount() == 2


def test_rectangular_selection_merges_and_splits():
    dialog = TableEditorDialog({"rows": [["A", "B"], ["C", "D"]]})
    selection = dialog.grid.selectionModel()
    for row in range(2):
        for col in range(2):
            selection.select(
                dialog.grid.model().index(row, col),
                QItemSelectionModel.Select,
            )

    dialog.merge_selected_cells()
    assert dialog.grid.rowSpan(0, 0) == 2
    assert dialog.grid.columnSpan(0, 0) == 2

    dialog.grid.setCurrentCell(0, 0)
    dialog.split_current_cell()
    assert dialog.table_spec["rows"] == [["A", "B"], ["C", "D"]]
```

- [ ] **Step 2: GUI 테스트 실패 확인**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_table_editor_dialog.py -q
```

Expected: `src.gui.table_editor` import 실패.

- [ ] **Step 3: `TableEditorDialog` 구현**

`src/gui/table_editor.py`에 `QDialog` 기반 `TableEditorDialog`를 만든다.
생성자는 `(table_spec, parent=None)`를 받고, 공개 동작은
`result_table_spec()`, `add_row_above()`, `add_row_below()`,
`add_column_left()`, `add_column_right()`, `delete_selected_rows()`,
`delete_selected_columns()`, `merge_selected_cells()`,
`split_current_cell()`, `auto_fit_widths()`로 고정한다.

구현 세부사항:

- `grid.setSelectionMode(QAbstractItemView.ExtendedSelection)`와 `SelectItems`를 사용한다.
- 가로 header는 `QHeaderView.Interactive`로 설정하고 section resize signal을 받는다.
- `_sync_model_from_grid()`가 편집 중 cell text를 현재 table dict로 먼저 반영한 뒤 구조 함수를 호출한다.
- `_render_table()`은 `rows`, `cells`, span을 다시 QTableWidget에 투영한다.
- 이미 덮인 병합 위치는 선택/편집 대상에서 제외한다.
- 구조 함수의 `TableStructureError`는 `QMessageBox.warning(self, "표 편집", str(exc))`로 표시하고 상태를 변경하지 않는다.
- 헤더 resize 이벤트는 `_render_table()` 중에는 guard flag로 무시한다.
- `result_table_spec()` 호출 전 마지막 cell edit와 현재 header 폭을 동기화한다. 자동 모드에서는 header 폭을 manual로 바꾸지 않는다.
- `auto_fit_widths()`는 `resizeColumnsToContents()` 후 `set_auto_width_mode()`를 호출한다.

- [ ] **Step 4: header 폭 상태 GUI 테스트 추가**

```python
def test_header_resize_is_persisted_as_manual_width():
    dialog = TableEditorDialog({"rows": [["A", "B"]]})
    dialog.grid.setColumnWidth(0, 210)
    dialog.grid.setColumnWidth(1, 70)

    result = dialog.result_table_spec()

    assert result["layout"]["width_mode"] == "manual"
    assert result["column_widths"] == pytest.approx([0.75, 0.25], abs=0.02)


def test_auto_fit_marks_width_mode_auto():
    dialog = TableEditorDialog({
        "rows": [["A", "긴 설명"]],
        "column_widths": [0.5, 0.5],
        "layout": {"width_mode": "manual"},
    })

    dialog.auto_fit_widths()

    assert dialog.result_table_spec()["layout"]["width_mode"] == "auto"
```

- [ ] **Step 5: GUI targeted 테스트 통과 확인**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_table_editor_dialog.py -q
```

Expected: 모든 신규 GUI 테스트 통과.

- [ ] **Step 6: local feature commit**

```powershell
git add src/gui/table_editor.py tests/test_table_editor_dialog.py
git commit -m "feat: add multicell table editor dialog"
```

---

## Task 7: 문제 수정 창에 새 편집기 연결

**Files:**

- Modify: `src/gui/interface/editor.py`
- Modify: `tests/test_editor_table_format.py`

- [ ] **Step 1: 편집 결과 교체 저장 실패 테스트 작성**

`tests/test_editor_table_format.py`에 다음 테스트를 추가한다.

```python
def test_replacing_table_spec_keeps_source_anchor_and_unknown_metadata():
    editor = QuestionEditor(question_data=_question_with_table())
    replacement = {
        "rows": [["A", "B"], ["C", "D"]],
        "cells": [],
        "column_widths": [0.3, 0.7],
        "layout": {"width_mode": "manual"},
    }

    editor._replace_table_spec("question", "table-1", replacement)

    table = json.loads(editor.get_data()["question_format_json"])["tables"][0]
    assert table["id"] == "table-1"
    assert table["source"]["sha256"] == "abc123"
    assert table["anchor"]["offset"] == 8
    assert table["rows"] == [["A", "B"], ["C", "D"]]
    assert table["layout"]["width_mode"] == "manual"
```

이 테스트는 같은 파일의 기존 `_editor_data()` helper를 사용한다.

- [ ] **Step 2: 기존 inline 대화상자 제거 및 연결 구현**

`src/gui/interface/editor.py`에서 `QTableWidget`, `QTableWidgetItem`, `QHeaderView`, `QDialogButtonBox` inline 편집 의존을 제거하고 다음 import를 추가한다.

```python
from ..table_editor import TableEditorDialog
from ...parser.table_structure import normalize_rectangular_table
```

`_edit_table_structure()`는 다음 책임만 갖는다.

```python
def _edit_table_structure(self, owner, table_id):
    table = self._find_owner_table(owner, table_id)
    if not table:
        return
    dialog = TableEditorDialog(table, self)
    if dialog.exec() != QDialog.Accepted:
        return
    self._replace_table_spec(owner, table_id, dialog.result_table_spec())
```

`_replace_table_spec()`는 기존 table의 `id`, `anchor`, `source`, `confidence`, `complexity`, 알 수 없는 metadata를 기본으로 두고 편집 가능한 `rows`, `cells`, `column_widths`, `row_heights`, `layout`만 replacement에서 덮은 후 `normalize_rectangular_table()`로 정리한다. 기존 `_update_table_rows()`는 호환 wrapper로 유지하되 새 교체 API를 사용한다.

- [ ] **Step 3: 편집기 통합 테스트 실행**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_editor_table_format.py tests/test_table_editor_dialog.py -q
```

Expected: 기존 표 카드/1셀 표 테스트와 신규 통합 테스트 전부 통과.

- [ ] **Step 4: local feature commit**

```powershell
git add src/gui/interface/editor.py tests/test_editor_table_format.py
git commit -m "feat: connect multicell editor to question dialog"
```

---

## Task 8: 내용 기반 표 레이아웃 계산기

**Files:**

- Create: `src/exporter/table_layout.py`
- Create: `tests/test_table_layout.py`

- [ ] **Step 1: 문자 점수와 우선순위 실패 테스트 작성**

```python
import pytest

from src.exporter.table_layout import (
    NARROW_TABLE_WIDTH_MM,
    WIDE_TABLE_WIDTH_MM,
    display_units,
    resolve_table_layout,
)


def test_display_units_uses_longest_line_and_character_classes():
    assert display_units("한글 AB") == pytest.approx(6.5)
    assert display_units("짧음\n가장긴줄ABC") == pytest.approx(11.0)


def test_manual_widths_override_content_scores():
    layout = resolve_table_layout({
        "rows": [["아주 긴 첫 번째 열", "B"]],
        "column_widths": [0.25, 0.75],
        "layout": {"width_mode": "manual"},
    })

    assert layout.width_mode == "manual"
    assert layout.column_widths == pytest.approx((0.25, 0.75))


def test_legacy_source_widths_override_auto_content_scores():
    layout = resolve_table_layout({
        "rows": [["아주 긴 첫 번째 열", "B"]],
        "column_widths": [0.4, 0.6],
    })

    assert layout.width_mode == "source"
    assert layout.column_widths == pytest.approx((0.4, 0.6))


def test_auto_layout_gives_more_width_to_long_content():
    layout = resolve_table_layout({
        "rows": [["구분", "매우 긴 설명 문자열입니다"]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.column_widths[1] > layout.column_widths[0]
    assert sum(layout.column_widths) == pytest.approx(1.0)
```

- [ ] **Step 2: 테스트 실패 확인**

Run:

```powershell
python -m pytest tests/test_table_layout.py -q
```

Expected: `src.exporter.table_layout` import 실패.

- [ ] **Step 3: 레이아웃 dataclass와 문자 점수 구현**

```python
from dataclasses import dataclass

NARROW_TABLE_WIDTH_MM = 82.0
WIDE_TABLE_WIDTH_MM = 180.0
MIN_COLUMN_WIDTH_MM = 12.0
MAX_COLUMN_SHARE = 0.75
MM_PER_DISPLAY_UNIT = 1.6
MAX_NARROW_WRAP_LINES = 3


@dataclass(frozen=True)
class TableLayout:
    column_widths: tuple[float, ...]
    column_widths_mm: tuple[float, ...]
    total_width_mm: float
    width_mode: str
    wide: bool
    estimated_max_lines: int
    fallback_used: bool = False


```

이 dataclass와 함께 공개 함수 `display_units(text: str) -> float`와
`resolve_table_layout(table_spec: dict) -> TableLayout`을 구현한다.

`display_units()`는 Unicode east asian width가 `W/F/A`인 문자를 2, 공백과 `.,:;!'\"|ilI`를 0.5, 나머지를 1로 계산하고 명시적 줄 중 최대값을 반환한다. 한글·CJK ambiguous 문자를 일관되게 2로 취급한다.

- [ ] **Step 4: 병합 분배와 1단 전환 실패 테스트 추가**

```python
def test_merged_cell_need_is_distributed_across_spanned_columns():
    layout = resolve_table_layout({
        "rows": [["긴 병합 제목", ""], ["A", "B"]],
        "cells": [
            {"row": 0, "col": 0, "text": "긴 병합 제목", "row_span": 1, "col_span": 2},
            {"row": 1, "col": 0, "text": "A", "row_span": 1, "col_span": 1},
            {"row": 1, "col": 1, "text": "B", "row_span": 1, "col_span": 1},
        ],
        "layout": {"width_mode": "auto"},
    })

    assert layout.column_widths[0] == pytest.approx(layout.column_widths[1])


def test_too_many_minimum_width_columns_switch_to_wide_layout():
    layout = resolve_table_layout({
        "rows": [["A", "B", "C", "D", "E", "F", "G"]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.wide is True
    assert layout.total_width_mm == WIDE_TABLE_WIDTH_MM
    assert min(layout.column_widths_mm) >= 12.0


def test_predicted_four_line_wrap_switches_to_wide_layout():
    layout = resolve_table_layout({
        "rows": [["A", "한글" * 40]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.wide is True
    assert layout.estimated_max_lines <= 4


def test_explicit_wide_flag_always_wins():
    layout = resolve_table_layout({
        "rows": [["A"]],
        "layout": {"width_mode": "auto", "wide": True},
    })

    assert layout.wide is True
    assert layout.total_width_mm == WIDE_TABLE_WIDTH_MM
```

- [ ] **Step 5: auto 폭 제약과 1단 판단 구현**

계산 순서:

1. `normalize_table_spec()`으로 rows, cells, width mode를 정규화한다.
2. 일반 cell은 longest-line display units를 해당 열 점수의 최댓값에 반영한다.
3. 병합 cell은 필요 점수를 span 안의 현재 비율 또는 균등 비율로 분배한다.
4. manual/source 유효 폭이면 비율은 그대로 사용하고, auto만 내용 점수로 비율을 만든다.
5. 82mm에서 각 열 12mm 확보 불가, 어느 cell이 3줄 초과 예상, 또는 `layout.wide=True`이면 180mm로 재계산한다.
6. 2열 이상에서 한 열이 75%를 넘으면 초과분을 다른 열에 반복 분배한다. 단 최소 폭과 75%를 동시에 만족할 수 없는 열 수에서는 최소 폭을 우선한다.
7. 비정상 score/width/산술 오류는 균등 비율, `fallback_used=True`로 반환한다.

- [ ] **Step 6: 레이아웃 테스트 실행**

Run:

```powershell
python -m pytest tests/test_table_layout.py -q
```

Expected: 모든 내용 폭, 우선순위, 병합, wide 테스트 통과.

- [ ] **Step 7: local feature commit**

```powershell
git add src/exporter/table_layout.py tests/test_table_layout.py
git commit -m "feat: calculate content aware table layouts"
```

---

## Task 9: DOCX에 고정 grid 폭과 자동 1단 배치 적용

**Files:**

- Modify: `src/exporter/docx.py`
- Modify: `tests/test_docx_exporter.py`

- [ ] **Step 1: OpenXML 고정 폭 실패 테스트 작성**

`tests/test_docx_exporter.py`에 manual 2열 표를 export하고 다음을 단언한다.

```python
def test_native_table_writes_fixed_grid_widths_from_manual_layout(tmp_path):
    output = tmp_path / "manual-widths.docx"
    payload = json.dumps({
        "tables": [{
            "id": "manual",
            "rows": [["A", "B"]],
            "column_widths": [0.25, 0.75],
            "layout": {"width_mode": "manual"},
            "confidence": {"score": 1.0},
            "render_mode": "native",
        }]
    })

    DocxExporter().export("수동 폭", _single_table_question(payload), str(output))

    xml = _read_document_xml(output)
    assert xml.xpath("string(//w:tbl/w:tblPr/w:tblLayout/@w:type)", namespaces=NS) == "fixed"
    grid_widths = [int(value) for value in xml.xpath("//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=NS)]
    assert len(grid_widths) == 2
    assert grid_widths[1] / grid_widths[0] == pytest.approx(3.0, rel=0.03)
```

필요하면 이 테스트 파일 상단에 `import pytest`를 추가한다.

- [ ] **Step 2: 현재 exporter에서 실패 확인**

Run:

```powershell
python -m pytest tests/test_docx_exporter.py -q -k "fixed_grid_widths"
```

Expected: `w:tblLayout` 또는 grid ratio 단언 실패.

- [ ] **Step 3: exporter에 layout resolver 연결**

`src/exporter/docx.py`에 다음 import를 추가한다.

```python
from .table_layout import resolve_table_layout
```

`_add_one_format_table()`에서 표를 render하기 전에 한 번 계산해 `_table_requires_one_column(table_spec, layout)`과 `_render_one_format_table(doc, table_spec, layout)`에 전달한다. 계산 예외는 균등 폭 fallback layout을 만드는 공통 helper로 처리하거나 `resolve_table_layout`의 fallback 결과를 사용한다.

`_add_native_table()`은 다음 동작을 한다.

- `table.autofit = False`
- `w:tblPr`에 `<w:tblLayout w:type="fixed"/>` 삽입/갱신
- `w:tblGrid/w:gridCol` 값을 `column_widths_mm`의 twip으로 설정
- 모든 row의 각 physical cell에도 `tcW`를 적용해 Word 재배치를 방지
- 병합 cell의 `tcW`는 span 열 폭의 합으로 설정
- 기존 cell text, 정렬, 병합, 9pt 글꼴은 유지

- [ ] **Step 4: 내용 기반 wide section 및 복원 테스트 강화**

기존 `test_wide_table_temporarily_switches_to_one_column_section`은 5열 개수만 의존하지 않도록 2열 장문 auto 표로 바꾸거나 아래 테스트를 추가한다.

```python
def test_content_heavy_table_switches_to_one_column_and_restores_two_columns(tmp_path):
    output = tmp_path / "content-wide.docx"
    payload = json.dumps({
        "tables": [{
            "id": "wide-content",
            "rows": [["구분", "아주 긴 설명" * 30]],
            "layout": {"width_mode": "auto"},
            "confidence": {"score": 1.0},
            "render_mode": "native",
        }]
    }, ensure_ascii=False)

    DocxExporter().export("내용 폭", _single_table_question(payload), str(output))

    xml = _read_document_xml(output)
    column_counts = xml.xpath("//w:sectPr/w:cols/@w:num", namespaces=NS)
    assert "1" in column_counts
    assert column_counts[-1] == "2"
    grid_widths = [int(value) for value in xml.xpath("//w:tbl/w:tblGrid/w:gridCol/@w:w", namespaces=NS)]
    assert sum(grid_widths) == pytest.approx(180 / 25.4 * 1440, rel=0.03)
```

- [ ] **Step 5: fallback warning 테스트 추가**

`resolve_table_layout`을 monkeypatch해 계산 예외를 발생시키고, export 성공·균등 grid·`table_layout_fallback` warning을 단언한다. exporter 내부 예외 경계가 resolver 호출을 포함해야 한다.

- [ ] **Step 6: DOCX targeted 테스트 실행**

Run:

```powershell
python -m pytest tests/test_docx_exporter.py tests/test_table_layout.py -q
```

Expected: 기존 DOCX 표/이미지 fallback/anchor 테스트와 신규 폭 테스트 전부 통과.

- [ ] **Step 7: local feature commit**

```powershell
git add src/exporter/docx.py tests/test_docx_exporter.py
git commit -m "feat: render fixed content aware docx tables"
```

---

## Task 10: 편집 저장 round-trip과 기존 payload 회귀

**Files:**

- Modify: `tests/test_table_editor_dialog.py`
- Modify: `tests/test_editor_table_format.py`
- Modify: `tests/test_validate_table_payloads.py`

- [ ] **Step 1: parse → edit → serialize → reopen round-trip 테스트 추가**

다음 시나리오를 하나의 통합 테스트로 만든다.

1. legacy `column_widths`가 있는 2×2 PDF 표 payload를 `parse_format_payload()`로 읽는다.
2. `TableEditorDialog`에서 아래 행, 오른쪽 열을 추가한다.
3. 새 2×2 선택을 병합하고 열 폭을 수동 변경한다.
4. `serialize_format_payload()`로 저장 후 재parse한다.
5. rows/cells/span/merge_backup/manual widths/source/anchor/custom metadata가 모두 유지되는지 단언한다.

- [ ] **Step 2: 1셀 `<보기>` 확장 회귀 테스트 추가**

기존 `add_one_cell_table()` 결과를 `TableEditorDialog`에 넣어 3행×2열로 확장하고, 첫 셀의 `<보기>` 텍스트와 anchor/source/render_mode가 유지되는지 단언한다.

- [ ] **Step 3: DB payload validator 회귀 테스트 추가**

`tests/test_validate_table_payloads.py`에 `layout.width_mode`, `merge_backup`, manual widths가 포함된 payload를 넣고 validate/normalize 후 metadata가 제거되지 않는지 확인한다.

- [ ] **Step 4: 표 관련 전체 targeted 테스트 실행**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/test_table_format.py tests/test_table_structure.py tests/test_table_editor_dialog.py tests/test_editor_table_format.py tests/test_table_layout.py tests/test_docx_exporter.py tests/test_validate_table_payloads.py tests/test_view_table.py -q
```

Expected: 전부 통과.

- [ ] **Step 5: local feature commit**

```powershell
git add tests/test_table_editor_dialog.py tests/test_editor_table_format.py tests/test_validate_table_payloads.py
git commit -m "test: cover table editing and export round trips"
```

---

## Task 11: 실제 문제은행 read-only 회귀 검증

**Files:**

- Conditional modify: `scripts/validate_table_payloads.py` (forward-compatible metadata를 오류로 판정할 때만)
- Conditional modify: `tests/test_validate_table_payloads.py` (위 수정의 실패 테스트가 필요할 때만)

- [ ] **Step 1: mounted/factory DB 후보 탐색**

Run:

```powershell
rg --files data | rg "\.(db|sqlite|examdb)$"
```

실제 `Run_Latest_App.bat`이 참조하는 runtime data path도 `src/runtime_paths.py`를 통해 확인한다. 어떠한 DB에도 write하지 않는다.

- [ ] **Step 2: 표 payload read-only 검증 실행**

각 발견 DB에 대해 다음 명령을 실행한다.

```powershell
$dbs = rg --files data | Where-Object { $_ -match '\.(db|sqlite|examdb)$' }
foreach ($db in $dbs) {
    python scripts/validate_table_payloads.py --db (Resolve-Path $db)
}
```

Expected:

- JSON parse failure 0
- schema-v2 normalize failure 0
- 기존 `<보기>` native table 수 유지
- out-of-bounds cell 또는 잘못된 span 0, 또는 이미 존재한 finding이면 개수와 sample ID를 기록

- [ ] **Step 3: 실제 payload sample을 새 순수 모듈로 round-trip**

표가 있는 question/choice payload를 read-only SELECT하여 `parse_format_payload() → normalize_rectangular_table() → serialize_format_payload()`로 메모리에서만 처리한다. 원래의 `id`, `anchor`, `source`, `rows` 및 알 수 없는 key가 유지되는지 비교하는 임시 검증 명령을 실행하고 결과를 작업 보고에 남긴다.

- [ ] **Step 4: validator 보완이 필요할 때만 테스트 우선 수정**

기존 validator가 `layout`이나 `merge_backup`을 오류로 오인할 경우 실패 테스트를 먼저 추가하고 forward-compatible 보존만 수정한다. DB 데이터 자체는 이 단계에서 변경하지 않는다.

- [ ] **Step 5: validator 변경이 생긴 경우에만 commit**

```powershell
git add scripts/validate_table_payloads.py tests/test_validate_table_payloads.py
git commit -m "test: validate multicell table payload compatibility"
```

---

## Task 12: 전체 검증과 수동 UX smoke test

**Files:**

- No production changes expected
- Update only if behavior changed: `README.md`

- [ ] **Step 1: 전체 자동 테스트 실행**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
```

Expected: 기존 baseline `887 passed, 1 skipped` 이상이며 신규 테스트 포함 전체 통과. 실패가 있으면 해당 실패를 수정하고 동일 명령을 다시 실행한다.

- [ ] **Step 2: compile/import smoke test**

Run:

```powershell
python -m compileall -q src
python -c "from src.gui.table_editor import TableEditorDialog; from src.exporter.table_layout import resolve_table_layout; print('imports-ok')"
```

Expected: `imports-ok`, exit code 0.

- [ ] **Step 3: `Run_Latest_App.bat` 기준 수동 UX 확인**

앱을 실행해 복제된 테스트 문제에서만 다음을 확인한다.

- 기존 1셀 `<보기>` 표 열기
- 위/아래 행, 왼쪽/오른쪽 열 추가
- 여러 행/열 삭제와 마지막 dimension 삭제 차단
- 2×2 병합 후 분할 시 원문 복원
- header 드래그 후 저장·재열기 폭 유지
- `폭 자동 맞춤` 후 저장·재열기
- DOCX export에서 좁은 표 2단 유지, 장문 표만 1단 전환, 뒤 문항 2단 복원

- [ ] **Step 4: worktree diff와 사용자 파일 보호 확인**

Run:

```powershell
git status --short
git diff --check
git log --oneline --decorate -12
```

Expected:

- `git diff --check` 출력 없음
- ZIP 파일이 stage되지 않음
- 구현 파일과 테스트만 feature commits에 포함

- [ ] **Step 5: 최종 구현 commit이 필요한 경우 생성**

문서 또는 마지막 조정이 남아 있을 때만 다음을 실행한다.

```powershell
git add README.md
git commit -m "docs: describe multicell table editing"
```

README 변경이 없으면 빈 commit은 만들지 않는다.

## Completion Evidence

완료 보고에는 다음 근거를 반드시 포함한다.

- 구현한 구조 버튼과 저장되는 폭 모드
- 구조/GUI/DOCX targeted test 명령 및 결과
- 전체 pytest 결과
- 실제 문제은행 read-only validation 결과와 검사한 DB 절대 경로
- 수동 smoke test 결과
- 생성된 commit hash 목록
- main 병합·GitHub push는 수행하지 않았는지 또는 후속 승인으로 수행했는지 명시
