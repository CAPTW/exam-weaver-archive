# 문서형 표 편집 UI/UX 개선 설계

## 목표

문제 수정창에서 표를 한 줄 텍스트 요약으로만 표시하는 현재 UI를 실제 격자 미리보기로 교체한다. 사용자는 문제 전체 맥락을 유지하면서 표의 형태를 즉시 확인하고, 넓은 전용 편집창에서 DOCX를 편집하는 것과 유사한 방식으로 셀 내용, 행과 열, 병합, 정렬, 폭을 수정할 수 있어야 한다.

이번 개선은 기존 `codex/multicell-table-editor` 브랜치에 구현된 schema-v2 표 구조 엔진, 다중 셀 편집기, 열 폭 저장, DOCX 내용 기반 배치 계산기를 기반으로 한다. DB schema와 저장 column은 변경하지 않는다.

## 사용자 결정

시각적 비교에서 다음 세 접근법을 검토했다.

1. 문제 수정창 안에서 완전 인라인 편집
2. 읽기 전용 시각적 미리보기와 넓은 전용 편집기 결합
3. 발문·표·선지를 한 페이지에서 편집하는 전체 문서형 WYSIWYG

선택한 접근법은 2번이다. 세부 범위는 다음과 같이 확정했다.

- 문제 수정창의 표는 읽기 전용 미리보기로 표시한다.
- 더블클릭 또는 `표 편집` 버튼으로 전용 편집창을 연다.
- 셀은 일반 텍스트, 줄바꿈, 가로/세로 글자 정렬을 지원한다.
- 글꼴, 크기, 색상, 굵게, 밑줄 등 리치 텍스트 서식은 이번 범위에 포함하지 않는다.
- 전용 편집창 안에서 여러 단계 실행 취소와 다시 실행을 지원한다.
- 표 표시는 `편집 맞춤`과 `DOCX 실제 폭` 모드를 전환할 수 있다.

## 현재 UI의 문제

현재 문제 수정창의 표 카드는 `발문 · view-table-1 · <보기> / 사례 / ...`처럼 모든 셀을 한 줄로 평탄화한다. 이 방식에는 다음 문제가 있다.

- 저장된 행·열과 병합 형태를 문제 수정창에서 확인할 수 없다.
- 사용자가 `표 편집`을 누르기 전에는 OCR 또는 구조 오류를 발견하기 어렵다.
- `원본 보기`, `구조 보기`, `표 편집`, `표 삭제`, 출력 방식 선택이 같은 한 줄에 놓여 정보 계층이 약하다.
- 긴 표 내용 때문에 카드의 주요 동작과 상태를 빠르게 구분하기 어렵다.
- 현재 전용 편집기는 9개의 구조 버튼과 격자만 제공해 Word형 명령 구조, 정렬, 상태 표시, 실행 취소, 출력 폭 확인이 없다.

## 선택한 화면 구조

### 문제 수정창의 `TablePreviewCard`

기존 한 줄 카드 대신 표 하나당 읽기 전용 카드 하나를 표시한다.

카드 상단에는 다음 정보를 배치한다.

- 소유 위치: `발문`, `1번 선지` 등
- 표 식별자
- 표 크기: `3행 × 2열`
- 병합 셀 수
- 폭 모드: 자동, 원본, 수동
- DOCX 예상 배치: 2단 82mm 또는 1단 180mm

카드 중앙에는 실제 표 격자를 축소해서 표시한다.

- `rows`, `cells`, `row_span`, `col_span`을 실제 모양으로 렌더링한다.
- 셀 글자 정렬을 미리보기에도 반영한다.
- 미리보기는 편집할 수 없고 selection도 만들지 않는다.
- 더블클릭하면 전용 표 편집창을 연다.
- 최대 표시 높이는 180 logical pixel로 제한하고 큰 표는 카드 내부 스크롤을 사용한다.
- 셀은 줄바꿈을 표시하되 한 행 높이는 64 logical pixel을 넘지 않는다.
- 잘린 셀 내용은 tooltip에서 전체를 확인할 수 있다.
- 가로 폭이 카드보다 넓으면 내부 가로 스크롤을 사용한다.

카드 하단 동작은 다음 순서로 정리한다.

1. `표 편집` — primary action
2. `원본 비교` — 원본 crop이 있을 때만 활성화
3. 출력 방식 선택 — 자동, 원본 이미지, 편집 가능한 표
4. `표 삭제` — destructive action

기존 `구조 보기` modal은 제거한다. 시각적 격자와 상태 정보가 같은 기능을 더 명확하게 제공하기 때문이다.

### 전용 `TableEditorDialog`

전용 편집창은 최소 980×640 logical pixel, 기본 1180×760 logical pixel로 연다. 사용자 화면의 가용 영역을 넘지 않도록 최종 크기를 제한한다.

편집창은 네 영역으로 구성한다.

1. 상단 명령 모음
2. 중앙 표 편집 격자
3. 선택적 원본 비교 패널
4. 하단 상태 표시줄과 저장/취소 동작

## 상단 명령 모음

명령은 기능별 그룹으로 배치한다.

### 편집 그룹

- 실행 취소
- 다시 실행

### 행·열 그룹

- 위에 행 삽입
- 아래에 행 삽입
- 왼쪽에 열 삽입
- 오른쪽에 열 삽입
- 선택 행 삭제
- 선택 열 삭제

삽입과 삭제 명령은 dropdown으로 묶되, 가장 최근에 사용한 동작을 primary face로 다시 실행할 수 있게 한다. 좁은 화면에서는 그룹이 두 번째 줄로 자연스럽게 이동한다.

### 셀 그룹

- 셀 병합
- 셀 분할

### 정렬 그룹

- 가로: 왼쪽, 가운데, 오른쪽
- 세로: 위, 가운데, 아래

### 배치·보기 그룹

- 폭 자동 맞춤
- `편집 맞춤` / `DOCX 실제 폭` 전환
- 확대/축소
- 원본 비교 panel 전환

모든 명령은 icon과 한국어 text 또는 tooltip을 함께 제공한다. 비활성화 상태는 색뿐 아니라 disabled appearance와 tooltip 이유로 전달한다.

## 표 편집 상호작용

### 선택과 직접 편집

- 한 번 클릭: 한 셀 선택
- drag 또는 Shift+클릭: 연속된 직사각형 범위 선택
- Ctrl+클릭: 여러 셀을 추가 선택할 수 있으나 병합 명령은 연속된 직사각형 선택일 때만 활성화
- 더블클릭 또는 F2: 여러 줄 셀 편집 시작
- Enter: 셀 안에 줄바꿈 삽입
- Tab: 현재 입력을 확정하고 다음 논리 셀로 이동
- Shift+Tab: 현재 입력을 확정하고 이전 논리 셀로 이동
- 마지막 셀에서 Tab: 새 행을 자동 생성하지 않고 첫 셀로 순환하지도 않는다. 현재 입력만 확정한다.
- Esc: 현재 셀의 미확정 입력 취소
- Delete: 선택한 셀의 text만 지우며 행과 열은 유지

셀 편집기는 `QPlainTextEdit` 기반 delegate를 사용해 Enter 줄바꿈과 Tab 이동을 명확히 분리한다.

### 구조 변경

행과 열 삽입·삭제, 병합·분할 규칙은 기존 `src/parser/table_structure.py`의 순수 연산을 그대로 사용한다.

- 마지막 행 또는 열은 삭제할 수 없다.
- 병합 영역과 교차하는 행·열 구조 변경은 차단한다.
- 병합은 연속된 직사각형 선택에만 허용한다.
- 분할은 병합 시작 셀을 선택했을 때만 허용한다.
- 병합 전 각 셀 text는 `merge_backup`에 보존하고 분할 때 원래 위치로 복원한다.

### 열 폭

- 가로 header 경계를 drag하면 수동 열 비율로 저장한다.
- drag가 시작될 때 before snapshot을 저장하고 mouse release 때 after snapshot을 기록한다.
- drag 중 발생하는 모든 `sectionResized` event를 개별 undo command로 만들지 않는다.
- `폭 자동 맞춤`은 `layout.width_mode = auto`로 전환한다.

## 실행 취소와 다시 실행

전용 편집창은 하나의 `TableEditSession`을 소유한다. session은 원본 table spec의 deep copy와 `QUndoStack`을 관리한다.

다음 동작은 각각 하나의 undo command가 된다.

- 한 번의 셀 편집 session
- 행 삽입 또는 삭제
- 열 삽입 또는 삭제
- 셀 병합 또는 분할
- 선택 셀 text 삭제
- 한 번의 가로 정렬 적용
- 한 번의 세로 정렬 적용
- 한 번의 열 폭 drag
- 폭 자동 맞춤

command는 전체 table spec의 before/after snapshot과 사용자에게 표시할 한국어 label을 보존한다. 시험 문제의 표 크기가 작고 schema-v2 payload가 compact하므로 snapshot 방식이 구조별 inverse operation보다 안전하다.

- `Ctrl+Z`: 실행 취소
- `Ctrl+Y` 및 `Ctrl+Shift+Z`: 다시 실행
- 편집창 `저장`: 현재 snapshot을 문제 payload에 반영
- 편집창 `취소`: session 전체 폐기
- 보기 모드와 확대율 변경은 table data를 바꾸지 않으므로 undo stack에 기록하지 않는다.

## 편집 맞춤과 DOCX 실제 폭

### 편집 맞춤

- 중앙 viewport의 가용 폭을 최대한 사용한다.
- 저장된 column ratio를 유지하되 편집에 필요한 최소 cell 폭을 확보한다.
- 가로 scroll은 최소화한다.

### DOCX 실제 폭

`src/exporter/table_layout.py`의 동일한 layout resolver를 사용한다.

- 2단 예상 표는 82mm
- 자동 1단 전환 표는 180mm
- logical pixel 환산은 현재 화면의 `logicalDpiX / 25.4`를 사용한다.
- zoom은 50%, 75%, 100%, 125%, 150%, 화면 맞춤을 제공한다.
- zoom은 view state이며 `column_widths`나 `layout`을 변경하지 않는다.
- 표 canvas를 viewport 가운데에 배치하고 필요한 경우 가로/세로 scroll을 제공한다.

상태 표시줄에는 `DOCX 2단 · 82mm` 또는 `DOCX 1단 · 180mm`와 자동 전환 이유를 표시한다.

## 원본 비교 panel

`source.image_path`가 유효할 때 `원본 비교`를 활성화한다.

- panel은 editor 오른쪽에 `QSplitter`로 표시한다.
- 원본 crop은 aspect ratio를 유지하며 fit-to-panel로 표시한다.
- 확대/축소와 실제 크기 보기를 제공한다.
- source가 없거나 파일이 손상됐으면 명령을 비활성화하고 tooltip으로 이유를 알린다.
- 원본 panel은 참조 전용이며 table payload를 변경하지 않는다.

## 데이터 구조와 저장

DB migration은 없다. 기존 `question_format_json`, `choice_format_json` schema-v2를 사용한다.

각 cell의 기존 필드로 이번 요구를 충족한다.

```json
{
  "row": 1,
  "col": 0,
  "text": "여러 줄\n셀 내용",
  "row_span": 1,
  "col_span": 1,
  "horizontal_alignment": "center",
  "vertical_alignment": "top"
}
```

열 폭과 출력 배치도 기존 필드를 사용한다.

```json
{
  "column_widths": [0.3, 0.7],
  "layout": {
    "width_mode": "manual",
    "wide": false
  }
}
```

저장 흐름은 다음과 같다.

1. `TablePreviewCard`가 현재 payload에서 normalized table spec을 받는다.
2. 전용 editor를 열 때 deep copy로 `TableEditSession`을 만든다.
3. 모든 command는 session copy에만 적용된다.
4. `저장`하면 최종 normalized spec을 `QuestionEditor._replace_table_spec()`에 전달한다.
5. 문제 수정창의 preview를 즉시 다시 렌더링한다.
6. 문제 수정창의 최종 `저장`이 기존 repository write routing을 통해 대상 문제은행에 기록한다.

Mounted 문제은행의 쓰기 대상 routing은 변경하지 않는다.

## 컴포넌트 경계

### `TablePreviewCard`

- 위치: 새 `src/gui/table_preview.py`
- 책임: metadata summary, 읽기 전용 격자, preview fallback, edit/delete/mode signals
- 의존: normalized table spec과 layout resolver
- 비책임: table data 변경

### `ReadOnlyTablePreview`

- 위치: `src/gui/table_preview.py`
- 책임: rows/cells/span/alignment 렌더링, 크기 제한, tooltip
- 비책임: selection과 editing

### `TableEditSession`

- 위치: 새 `src/gui/table_edit_session.py`
- 책임: working copy, undo stack, snapshot command, dirty state
- 의존: `table_structure` 순수 함수
- 비책임: widget rendering

### `MultilineTableDelegate`

- 위치: `src/gui/table_editor.py`
- 책임: 여러 줄 cell editor, Enter/Tab/Esc key behavior
- 비책임: 저장과 structure command

### `TableEditorDialog`

- 위치: 기존 `src/gui/table_editor.py`
- 책임: command bar, grid, selection state, view mode, source panel, status, save/cancel
- 의존: `TableEditSession`, layout resolver, delegate

### `QuestionEditor`

- 위치: 기존 `src/gui/interface/editor.py`
- 책임: preview card 구성, editor open, accepted result 반영
- 비책임: table operation 구현

## 오류 처리

가능하면 작업 실행 전에 명령을 비활성화한다.

- 병합 선택이 직사각형이 아니면 `셀 병합` 비활성화
- 일반 셀이면 `셀 분할` 비활성화
- 마지막 행·열이면 해당 삭제 명령 비활성화
- 병합 cell과 충돌하는 구조 작업 비활성화
- disabled tooltip과 하단 상태 표시줄에 이유 표시

작업 시점에 상태가 바뀌어 공통 모듈이 `TableStructureError`를 반환하면 modal 경고 대신 상태 표시줄에 error text를 표시하고 작업 전 snapshot을 유지한다.

- 손상된 rows/cells/span은 editor open 전에 `normalize_rectangular_table()`로 복구한다.
- preview 렌더링 실패는 기존 text summary로 fallback하며 문제 수정창은 계속 연다.
- layout 계산 실패는 균등 폭 preview와 `배치 계산 fallback` 상태를 표시한다.
- source image load 실패는 source panel만 비활성화한다.
- 표 전체 삭제는 기존 확인 dialog를 유지한다.

표 하나의 표시 실패가 문제 수정창 전체를 닫거나 저장을 막지 않는다.

## 접근성 및 화면 대응

- 모든 command에 `QAction` shortcut과 tooltip을 제공한다.
- focus order는 command bar → grid → source panel → 저장/취소 순서로 고정한다.
- 선택 범위, 현재 cell, 병합 범위를 상태 표시줄에 text로 표시한다.
- 선택, disabled, error 상태를 색상만으로 전달하지 않는다.
- 버튼 click target은 최소 32 logical pixel 높이를 확보한다.
- 100%, 125%, 150% Windows display scale에서 command가 잘리지 않게 responsive wrap을 적용한다.
- 최소 960×780 문제 수정창과 980×640 표 편집창에서 primary action이 항상 보이도록 한다.

## 테스트 전략

### Preview 단위 및 GUI 테스트

- rows/cells를 실제 격자로 렌더링
- horizontal/vertical alignment 반영
- row_span/col_span 반영
- 최대 높이와 내부 scroll
- 더블클릭과 `표 편집` button이 같은 signal 발생
- source 없는 상태와 preview render fallback
- metadata summary와 DOCX layout badge

### Session 및 undo 테스트

- text edit 하나가 undo command 하나로 기록
- 구조 작업별 undo/redo round-trip
- merge/split 후 backup 복원
- alignment undo/redo
- width drag event coalescing
- view mode/zoom이 undo stack을 바꾸지 않음
- cancel이 원본 spec을 변경하지 않음

### Editor GUI 테스트

- multiline Enter, Tab, Shift+Tab, Esc behavior
- selection별 command enabled state
- Delete가 cell text만 지우는지 확인
- command bar 좁은 폭 wrap
- edit-fit/DOCX actual 전환
- 82mm/180mm pixel conversion
- source comparison panel toggle
- keyboard shortcut과 focus order

### Integration 및 DOCX 회귀

- QuestionEditor preview refresh
- alignment 저장 후 DOCX paragraph/vertical alignment 반영
- manual/source/auto 폭 우선순위 유지
- 2단/1단 section 전환 유지
- Mounted repository write routing 회귀
- 실제 기본 문제은행 표 75개 read-only normalize/render 검사
- 전체 pytest

### 시각 검수

다음 viewport에서 reference mockup과 구현 screenshot을 같은 크기로 비교한다.

- 문제 수정창 960×780
- 문제 수정창 1280×900
- 표 편집창 1180×760
- Windows display scale 100%, 125%, 150%

버튼 잘림, 표 crop, padding, scroll, tooltip, disabled 상태, source panel 크기를 확인한다.

## 비범위

- 발문·표·선지를 한 canvas에서 편집하는 전체 WYSIWYG
- 셀 글꼴, 크기, 색상, 굵게, 밑줄
- cell 안 image와 formula 삽입
- 표 계산식
- 여러 표를 하나로 병합
- preview에서 직접 cell text 수정
- background autosave
- DB schema migration

## 완료 조건

- 문제 수정창에서 모든 표가 실제 행·열·병합 형태의 읽기 전용 preview로 보인다.
- preview double-click과 `표 편집` button이 같은 전용 editor를 연다.
- 사용자가 여러 줄 text, 행·열, 병합·분할, 가로/세로 정렬, 열 폭을 수정할 수 있다.
- 모든 data change를 여러 단계 undo/redo할 수 있다.
- `편집 맞춤`과 `DOCX 실제 폭`을 전환해 82mm/180mm 예상 결과를 확인할 수 있다.
- 원본 crop이 있으면 editor 안에서 나란히 비교할 수 있다.
- 저장 전 cancel은 원본 data를 변경하지 않는다.
- 기존 schema-v2, DOCX export, Mounted 문제은행 routing과 실제 표 75개 회귀가 없다.
- 960×780과 125% display scale에서 primary action과 표 preview가 잘리지 않는다.
