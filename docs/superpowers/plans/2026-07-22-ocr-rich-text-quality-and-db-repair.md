# OCR Rich Text Quality and Active DB Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OCR 손상이 발문·선지·rich-text 표·공유 지문에 저장되는 것을 차단하고, 활성 DB 네 개를 동일한 규칙으로 전수 검사하여 원문으로 확정된 값과 고신뢰 교정만 안전하게 반영한다.

**Architecture:** `src/parser/rich_text_quality.py`가 일반 텍스트와 format JSON의 `rows`/`cells`를 공통 표면으로 열거하고 구조 오류를 반환한다. 신규 파싱과 저장 DB 검증은 이 공통 검사기를 사용하며, DB 교정 엔진은 source-confirmed repair를 먼저 적용한 뒤 보수적 자동교정, 전 표면 재검사, SQLite 검증을 수행한다. 네 DB는 모두 staging 검증을 통과한 뒤 일괄 백업·교체하며, 교체 중 하나라도 실패하면 이미 교체한 DB까지 백업으로 복구한다.

**Tech Stack:** Python 3, 표준 라이브러리 `json`/`sqlite3`/`dataclasses`/`pathlib`/`shutil`, 기존 `PyMuPDF` 원문 대조 경로, `pytest`.

## Global Constraints

- 검사 대상은 `data/domain_dbs/exam_bank.maritime_all.db`, `data/domain_dbs/exam_bank.user_workspace.db`, `data/domain_dbs/exam_bank.Maritime.db`, `data/exam_bank.db` 네 개로 고정한다.
- `data/backups/`, `outputs/`, 과거 staging/빌드 산출물은 수정하지 않는다. 새 staging·보고서는 새 실행 디렉터리에만 만든다.
- `question_text`, `question_format_json`의 모든 `rows`/`cells`, `choice_text`, `choice_format_json`의 모든 `rows`/`cells`, `question_groups.shared_text`를 전부 검사한다.
- `rows`와 `cells[].text`가 같은 좌표에서 다르면 어느 한쪽도 선택하지 않고 `rows_cells_divergence`로 차단한다.
- invalid/non-object format JSON은 버리지 않고 `invalid_format_json`으로 차단한다.
- 자동교정은 결과가 하나뿐인 고신뢰 규칙에만 허용하며, 나머지는 `needs_source_review`로 보고하고 원문 없이 수정하지 않는다.
- source-confirmed repair는 DB 적용 시 현재값이 `expected_current_*` 또는 이미 교정된 값과 정확히 일치해야 한다.
- 실제 DB 교체 전 네 staging DB가 모두 무결성·스키마·품질·조회 smoke 검사를 통과해야 한다.
- 실제 DB 파일과 실행 보고서는 `.gitignore` 대상이므로 강제 add하지 않는다. 재현 가능한 코드·repair registry·테스트·설계·계획만 Git에 포함한다.
- 사용자의 요청대로 최종 원격 반영은 `origin/main` 기준 OCR 작업 전체를 하나의 commit으로 정리한 뒤 push한다.

---

## File Map

- Create `src/parser/rich_text_quality.py`: rich-text 표면 열거, format JSON 구조 검사, rows/cells 일치 검사.
- Modify `src/parser/text_quality.py`: 손상된 목록 기호와 사례의 OCR 토큰을 안정된 issue code로 탐지.
- Modify `src/parser/formatting.py`: 단일 해석만 가능한 사례 토큰의 보수적 자동교정.
- Modify `src/parser/offline_quality.py`: stem/choice의 일반 텍스트뿐 아니라 format JSON 표면까지 import gate에 연결.
- Modify `src/database/validator.py`: 저장된 question/choice format JSON과 공유 지문을 공통 품질 검사에 연결.
- Modify `src/database/staging.py`: 구조 오류를 삼키지 않고 blocking code로 승격하며 staging 저장 전 검사.
- Create `src/database/text_repair.py`: DB 행 열거, 보수적 변경 원장, 구조/품질 finding, 예상 기존값 기반 트랜잭션 적용.
- Modify `scripts/repair_db_text.py`: 기존 단일 DB CLI와 공개 함수명을 새 엔진의 호환 wrapper로 유지.
- Modify `src/parser/offline_repairs.py`: source-confirmed question format payload를 재파싱 결과에 복원.
- Modify `src/database/ocr_repairs.py`: source-confirmed stem/format의 expected-current 검증과 원자적 동시 적용.
- Modify `src/parser/offline_source_repairs.json`: 2022년 3회 해사영어 3번의 원문 확정 발문과 `<보기>` payload 등록.
- Create `src/database/text_repair_batch.py`: 네 DB staging 준비·전체 선검증·백업·일괄 교체·전체 롤백.
- Create `src/database/source_review.py`: 검토 finding의 등록 PDF 페이지를 중복 없이 렌더링하고 근거 상태 기록.
- Create `scripts/repair_active_db_text.py`: 네 DB dry-run/apply 및 통합 JSON/Markdown 보고서 CLI.
- Create `tests/test_rich_text_quality.py`: 공통 표면/구조 검사 단위 테스트.
- Modify `tests/test_text_cleanup.py`: 새 OCR 탐지·보수적 교정 회귀 테스트.
- Modify `tests/test_database_validator.py`: 저장 DB의 question/choice 표와 공유 지문 검증 테스트.
- Modify `tests/test_repair_db_text.py`: 전 표면 감사, expected-current, 공유 지문 테스트.
- Modify `tests/test_offline_db_rebuild.py`: source-confirmed 사례 복원과 staging fail-closed 테스트.
- Create `tests/test_text_repair_batch.py`: 네 DB 선검증과 교체 실패 전체 롤백 테스트.
- Create `tests/test_source_review.py`: file URL 해석, 페이지 렌더링, 원본 누락 상태 테스트.
- Create `tests/test_repair_active_db_text.py`: CLI dry-run/apply 및 보고서 스키마 테스트.

### Task 1: Common rich-text surface inspection

**Files:**

- Create: `src/parser/rich_text_quality.py`
- Create: `tests/test_rich_text_quality.py`

**Interfaces:**

- Consumes: format JSON schema의 `tables[].rows[][]`, `tables[].cells[].{row,col,text}`.
- Produces: `RichTextSurface`, `RichTextIssue`, `RichTextInspection`, `inspect_rich_text(text, format_json, *, owner, text_path, format_path, row_id=None, question_id=None, metadata=None) -> RichTextInspection`.

- [ ] **Step 1: Write failing tests for all surfaces and structural errors**

```python
import json

from src.parser.rich_text_quality import inspect_rich_text


def test_inspect_rich_text_enumerates_plain_rows_and_cells():
    payload = {
        "tables": [{
            "rows": [["㉠ Alpha", "㉡ Beta"]],
            "cells": [
                {"row": 0, "col": 0, "text": "㉠ Alpha"},
                {"row": 0, "col": 1, "text": "㉡ Beta"},
            ],
        }]
    }
    result = inspect_rich_text(
        "발문",
        json.dumps(payload, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
        row_id=7,
        question_id=7,
    )

    assert [surface.path for surface in result.surfaces] == [
        "question_text",
        "question_format_json.tables[0].rows[0][0]",
        "question_format_json.tables[0].rows[0][1]",
        "question_format_json.tables[0].cells[0].text",
        "question_format_json.tables[0].cells[1].text",
    ]
    assert result.issues == ()


def test_inspect_rich_text_rejects_invalid_json_and_rows_cells_divergence():
    invalid = inspect_rich_text(
        "발문", "[1, 2]", owner="question",
        text_path="question_text", format_path="question_format_json",
    )
    assert [issue.code for issue in invalid.issues] == ["invalid_format_json"]

    divergent = inspect_rich_text(
        "발문",
        json.dumps({"tables": [{
            "rows": [["원본 A"]],
            "cells": [{"row": 0, "col": 0, "text": "원본 B"}],
        }]}, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
    )
    assert [issue.code for issue in divergent.issues] == ["rows_cells_divergence"]
    assert divergent.issues[0].path == "question_format_json.tables[0].cells[0].text"


def test_inspect_rich_text_rejects_empty_or_unaddressable_cells():
    result = inspect_rich_text(
        "발문",
        json.dumps({"tables": [{
            "rows": [[""]],
            "cells": [{"row": "x", "col": 0, "text": "value"}],
        }]}, ensure_ascii=False),
        owner="question",
        text_path="question_text",
        format_path="question_format_json",
    )
    assert {issue.code for issue in result.issues} == {
        "empty_table_cell",
        "invalid_table_cell_coordinate",
    }
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run: `pytest tests/test_rich_text_quality.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'src.parser.rich_text_quality'`.

- [ ] **Step 3: Implement the focused inspector**

Create the dataclasses as frozen records. `inspect_rich_text` must always add the plain text surface, parse a non-empty format value exactly once, add both row and cell surfaces, and emit one divergence issue per mismatched cell coordinate.

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Mapping


Owner = Literal["question", "choice", "group"]


@dataclass(frozen=True)
class RichTextSurface:
    owner: Owner
    row_id: int | None
    question_id: int | None
    path: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RichTextIssue:
    code: str
    path: str
    text: str
    related_path: str | None = None


@dataclass(frozen=True)
class RichTextInspection:
    surfaces: tuple[RichTextSurface, ...]
    issues: tuple[RichTextIssue, ...]


def inspect_rich_text(
    text: str,
    format_json: str | None,
    *,
    owner: Owner,
    text_path: str,
    format_path: str,
    row_id: int | None = None,
    question_id: int | None = None,
    metadata: Mapping[str, object] | None = None,
) -> RichTextInspection:
    context = dict(metadata or {})
    surfaces = [RichTextSurface(owner, row_id, question_id, text_path, str(text or ""), context)]
    issues: list[RichTextIssue] = []
    if format_json in (None, ""):
        return RichTextInspection(tuple(surfaces), ())
    try:
        payload = json.loads(str(format_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return RichTextInspection(tuple(surfaces), (RichTextIssue("invalid_format_json", format_path, str(format_json)),))
    if not isinstance(payload, dict):
        return RichTextInspection(tuple(surfaces), (RichTextIssue("invalid_format_json", format_path, str(format_json)),))
    tables = payload.get("tables", ()) or ()
    if not isinstance(tables, list):
        return RichTextInspection(tuple(surfaces), (RichTextIssue("invalid_format_json", f"{format_path}.tables", str(tables)),))

    for table_index, table in enumerate(tables):
        table_path = f"{format_path}.tables[{table_index}]"
        if not isinstance(table, dict):
            issues.append(RichTextIssue("invalid_format_json", table_path, str(table)))
            continue
        rows = table.get("rows", ()) or ()
        coordinates: dict[tuple[int, int], tuple[str, str]] = {}
        if not isinstance(rows, list):
            issues.append(RichTextIssue("invalid_format_json", f"{table_path}.rows", str(rows)))
            rows = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, list):
                issues.append(RichTextIssue("invalid_format_json", f"{table_path}.rows[{row_index}]", str(row)))
                continue
            for column_index, value in enumerate(row):
                path = f"{table_path}.rows[{row_index}][{column_index}]"
                if not isinstance(value, str):
                    issues.append(RichTextIssue("invalid_format_json", path, str(value)))
                    continue
                surfaces.append(RichTextSurface(owner, row_id, question_id, path, value, context))
                coordinates[(row_index, column_index)] = (value, path)
                if not value.strip():
                    issues.append(RichTextIssue("empty_table_cell", path, value))

        cells = table.get("cells", ()) or ()
        if not isinstance(cells, list):
            issues.append(RichTextIssue("invalid_format_json", f"{table_path}.cells", str(cells)))
            continue
        for cell_index, cell in enumerate(cells):
            path = f"{table_path}.cells[{cell_index}].text"
            if not isinstance(cell, dict) or not isinstance(cell.get("text"), str):
                issues.append(RichTextIssue("invalid_format_json", path, str(cell)))
                continue
            value = cell["text"]
            surfaces.append(RichTextSurface(owner, row_id, question_id, path, value, context))
            if not value.strip():
                issues.append(RichTextIssue("empty_table_cell", path, value))
            row_value, col_value = cell.get("row"), cell.get("col")
            if not isinstance(row_value, int) or not isinstance(col_value, int):
                issues.append(RichTextIssue("invalid_table_cell_coordinate", path, value))
                continue
            row_entry = coordinates.get((row_value, col_value))
            if row_entry is not None and row_entry[0] != value:
                issues.append(RichTextIssue("rows_cells_divergence", path, value, row_entry[1]))
    return RichTextInspection(tuple(surfaces), tuple(issues))
```

- [ ] **Step 4: Run the common inspector tests and confirm GREEN**

Run: `pytest tests/test_rich_text_quality.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the isolated component checkpoint**

```bash
git add src/parser/rich_text_quality.py tests/test_rich_text_quality.py
git commit -m "feat: inspect all rich text surfaces"
```

### Task 2: Detect and conservatively repair the reported OCR forms

**Files:**

- Modify: `src/parser/formatting.py:174-620`
- Modify: `src/parser/text_quality.py:10-98`
- Modify: `tests/test_text_cleanup.py`

**Interfaces:**

- Consumes: `repair_extracted_text_artifacts(text: str) -> str` and `text_quality_issue_codes(text: str) -> tuple[str, ...]`.
- Produces: new stable issue code `damaged_list_marker`; exact token repairs for `HaIf`, `f01그r`, `Da•elict` and source-grounded Korean phrases `설명으로 을지 않은 것은`, `것은 모두 개인가?`.

- [ ] **Step 1: Add failing regression tests**

```python
def test_reported_maritime_ocr_tokens_are_repaired_conservatively():
    raw = (
        "다음 <보기> 중 용어에 대한 설명으로 을지 않은 것은 모두 개인가?\n"
        "㉢ HaIf cardinal point: The f01그r main points\n"
        "㉤ Da•elict: A vessel"
    )
    repaired = repair_extracted_text_artifacts(raw)
    assert repaired == (
        "다음 <보기> 중 용어에 대한 설명으로 옳지 않은 것은 모두 몇 개인가?\n"
        "㉢ Half cardinal point: The four main points\n"
        "㉤ Derelict: A vessel"
    )


def test_quality_gate_flags_damaged_multiline_list_markers():
    text = "< 보 기 >\n@ Beach (to): text\n㉢ Half cardinal point: text"
    assert "damaged_list_marker" in text_quality_issue_codes(text)


def test_quality_gate_does_not_flag_email_or_valid_ordered_markers():
    assert "damaged_list_marker" not in text_quality_issue_codes("contact@example.com")
    assert "damaged_list_marker" not in text_quality_issue_codes("㉠ Alpha\n㉡ Beta\n㉢ Gamma")
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `pytest tests/test_text_cleanup.py -q -k "reported_maritime or damaged_multiline or valid_ordered"`

Expected: three assertion failures because the new tokens/code are not handled.

- [ ] **Step 3: Add only the source-grounded replacements and marker detector**

Add these exact dictionary entries; do not add a generic `@ -> ㉠/㉣` replacement.

```python
ENGLISH_OCR_TOKEN_REPLACEMENTS.update({
    "HaIf": "Half",
    "f01그r": "four",
    "Da•elict": "Derelict",
})

OCR_EXACT_PHRASE_REPLACEMENTS.update({
    "설명으로 을지 않은 것은": "설명으로 옳지 않은 것은",
    "것은 모두 개인가?": "것은 모두 몇 개인가?",
})
```

In `text_quality.py`, add and call a focused detector.

```python
DAMAGED_LIST_MARKER_PATTERN = re.compile(r"(?m)^\s*@(?=\s*[A-Za-z가-힣])")


def has_damaged_list_marker(text: str) -> bool:
    return bool(DAMAGED_LIST_MARKER_PATTERN.search(str(text or "")))
```

Append `damaged_list_marker` in `text_quality_issue_codes` independently of `ocr_noise` so reports preserve the cause.

```python
if has_damaged_list_marker(value):
    codes.append("damaged_list_marker")
```

- [ ] **Step 4: Run focused and existing cleanup tests**

Run: `pytest tests/test_text_cleanup.py -q`

Expected: all tests pass, including the three new regressions.

- [ ] **Step 5: Commit the detector checkpoint**

```bash
git add src/parser/formatting.py src/parser/text_quality.py tests/test_text_cleanup.py
git commit -m "fix: detect reported OCR corruption"
```

### Task 3: Enforce the common quality gate during parse and persisted validation

**Files:**

- Modify: `src/parser/offline_quality.py:58-149`
- Modify: `src/database/validator.py:48-222`
- Modify: `src/database/staging.py:42-62,252-270,1076-1097,1599-1720`
- Modify: `tests/test_rich_text_quality.py`
- Modify: `tests/test_database_validator.py`
- Modify: `tests/test_offline_db_rebuild.py`

**Interfaces:**

- Consumes: Task 1 `inspect_rich_text`, Task 2 `text_quality_issue_codes`.
- Produces: parser reason codes `invalid_question_format_json`, `rows_cells_divergence_question_format`, `*_question_format`, `*_choice_format`; DB issue codes `invalid_format_json`, `rows_cells_divergence`, `empty_table_cell`, `damaged_marker_text`.

- [ ] **Step 1: Add failing parser and repository validation tests**

```python
def test_offline_quality_checks_question_and_choice_format_surfaces():
    table = json.dumps({"tables": [{
        "rows": [["@ Beach (to): text"]],
        "cells": [{"row": 0, "col": 0, "text": "@ Beach (to): text"}],
    }]}, ensure_ascii=False)
    candidate = ParsedOfflineQuestion(
        number=3,
        stem="정상 발문은?",
        choices=["A", "B", "C", "D"],
        source_page=24,
        confidence=1.0,
        diagnostics=(),
        question_format_json=table,
        choice_format_jsons=("", table, "", ""),
    )
    result = validate_offline_question(candidate)
    assert not result.importable
    assert "damaged_list_marker_question_format" in result.reason_codes
    assert "damaged_list_marker_choice_format" in result.reason_codes
```

```python
def test_validator_checks_question_choice_formats_and_shared_text(
    repo, sample_metadata, sample_question
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    question_table = json.dumps({"tables": [{
        "rows": [["@ Beach (to): text"]],
        "cells": [{"row": 0, "col": 0, "text": "@ Beach (to): text"}],
    }]}, ensure_ascii=False)
    choice_table = json.dumps({"tables": [{
        "rows": [["Da•elict vessel"]],
        "cells": [{"row": 0, "col": 0, "text": "Da•elict vessel"}],
    }]}, ensure_ascii=False)
    with sqlite3.connect(repo.db_path) as connection:
        exam_subject_id = connection.execute(
            "SELECT exam_subject_id FROM questions WHERE id = ?", (question["id"],)
        ).fetchone()[0]
        cursor = connection.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, shared_text
            ) VALUES (?, 2024, 1, 1, ?)
            """,
            (exam_subject_id, "공유 지문 HaIf cardinal point"),
        )
        group_id = cursor.lastrowid
        connection.execute(
            "UPDATE questions SET question_format_json = ?, group_id = ? WHERE id = ?",
            (question_table, group_id, question["id"]),
        )
        connection.execute(
            """
            UPDATE question_choices SET choice_format_json = ?
            WHERE question_id = ? AND choice_number = 1
            """,
            (choice_table, question["id"]),
        )

    issues = QuestionValidator(repo).scan()[0]["issues"]
    issue_codes = {issue["code"] for issue in issues}
    assert {"damaged_marker_text", "ocr_noise_text"} <= issue_codes
    assert any("question_format_json.tables[0]" in issue["message"] for issue in issues)
    assert any("choice_format_json.tables[0]" in issue["message"] for issue in issues)
    assert any("shared_text" in issue["message"] for issue in issues)


def test_validator_rejects_invalid_json_and_rows_cells_divergence(
    repo, sample_metadata, sample_question
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    divergent = json.dumps({"tables": [{
        "rows": [["row value"]],
        "cells": [{"row": 0, "col": 0, "text": "cell value"}],
    }]})
    with sqlite3.connect(repo.db_path) as connection:
        connection.execute(
            "UPDATE questions SET question_format_json = ? WHERE id = ?",
            ("[1, 2]", question["id"]),
        )
        connection.execute(
            """
            UPDATE question_choices SET choice_format_json = ?
            WHERE question_id = ? AND choice_number = 1
            """,
            (divergent, question["id"]),
        )

    issues = QuestionValidator(repo).scan()[0]["issues"]
    assert {"invalid_format_json", "rows_cells_divergence"} <= {
        issue["code"] for issue in issues
    }
```

- [ ] **Step 2: Run the new gate tests and confirm RED**

Run: `pytest tests/test_rich_text_quality.py tests/test_database_validator.py tests/test_offline_db_rebuild.py -q -k "format_surface or rich_text or rows_cells or shared_text"`

Expected: failures showing format JSON and shared text are not validated.

- [ ] **Step 3: Integrate inspection into `validate_offline_question`**

Inspect the question pair and every choice pair. Convert structural issues directly to stable parser reasons and call `_append_text_quality_reasons` for every non-plain surface.

```python
question_inspection = inspect_rich_text(
    stem,
    question.question_format_json,
    owner="question",
    text_path="stem",
    format_path="question_format_json",
)
for issue in question_inspection.issues:
    reasons.append(f"{issue.code}_question_format")
for surface in question_inspection.surfaces[1:]:
    _append_text_quality_reasons(reasons, surface.text, "question_format")

for index, choice in enumerate(choices):
    format_json = (
        question.choice_format_jsons[index]
        if index < len(question.choice_format_jsons)
        else None
    )
    inspection = inspect_rich_text(
        choice,
        format_json,
        owner="choice",
        text_path=f"choices[{index}]",
        format_path=f"choice_format_jsons[{index}]",
    )
    for issue in inspection.issues:
        reasons.append(f"{issue.code}_choice_format")
    for surface in inspection.surfaces[1:]:
        _append_text_quality_reasons(reasons, surface.text, "choice_format")
```

Map Task 2's code in `_append_text_quality_reasons` without collapsing it into generic OCR noise.

```python
elif code == "damaged_list_marker":
    reasons.append(f"damaged_list_marker_{location}")
```

- [ ] **Step 4: Integrate inspection into `QuestionValidator` and staging blockers**

Add one helper that maps structural issues and text-quality codes while retaining the exact path in the message.

```python
def _validate_rich_text_pair(
    self,
    text: str,
    format_json: str | None,
    *,
    owner: str,
    text_path: str,
    format_path: str,
    issues: List[Dict],
) -> None:
    inspection = inspect_rich_text(
        text, format_json, owner=owner,
        text_path=text_path, format_path=format_path,
    )
    for structural in inspection.issues:
        issues.append(self._issue(
            structural.code,
            f"{structural.path}: rich-text 구조 이상",
            "error",
        ))
    for surface in inspection.surfaces:
        self._validate_text_quality(surface.text, surface.path, issues)
```

Call it for the question, every choice, and nonblank `group_shared_text`/`shared_passage`. Map `damaged_list_marker` to `damaged_marker_text` with severity `error`. Add the following to `STAGING_BLOCKING_QUALITY_CODES`:

```python
"invalid_format_json",
"rows_cells_divergence",
"invalid_table_cell_coordinate",
"empty_table_cell",
"damaged_marker_text",
```

Before `_normalize_stored_rich_text` mutates a payload, call `inspect_rich_text`; raise `ValueError` with the structural code and path when inspection returns any structural issue. This removes the current silent invalid-JSON fallback.

- [ ] **Step 5: Run gate and staging tests**

Run: `pytest tests/test_rich_text_quality.py tests/test_database_validator.py tests/test_offline_db_rebuild.py -q`

Expected: all tests pass; the existing valid table normalization tests remain green.

- [ ] **Step 6: Commit the quality-gate checkpoint**

```bash
git add src/parser/offline_quality.py src/database/validator.py src/database/staging.py tests/test_rich_text_quality.py tests/test_database_validator.py tests/test_offline_db_rebuild.py
git commit -m "feat: gate every rich text surface"
```

### Task 4: Build a shared existing-DB audit and conservative repair engine

**Files:**

- Create: `src/database/text_repair.py`
- Modify: `scripts/repair_db_text.py:16-625`
- Modify: `tests/test_repair_db_text.py`

**Interfaces:**

- Consumes: `inspect_rich_text`, `repair_extracted_text_artifacts`, `text_quality_issue_codes`.
- Produces: `TextChange`, `TextFinding`, `AuditSummary`, `collect_changes(connection, *, confusables_only=False)`, `collect_findings(connection)`, `collect_surface_counts(connection)`, `apply_changes(connection, changes)`.

- [ ] **Step 1: Add an in-memory DB fixture and failing all-surface audit tests**

```python
@pytest.fixture()
def audit_connection(repo, sample_metadata, sample_question):
    sample_question.text = "발문 HaIf token"
    repo.save_questions([sample_question], sample_metadata)
    connection = sqlite3.connect(repo.db_path)
    connection.row_factory = sqlite3.Row
    question = connection.execute(
        "SELECT id, exam_subject_id FROM questions ORDER BY id LIMIT 1"
    ).fetchone()
    question_table = json.dumps({"tables": [{
        "rows": [["@ Beach row"]],
        "cells": [{"row": 0, "col": 0, "text": "@ Beach row"}],
    }]}, ensure_ascii=False)
    choice_table = json.dumps({"tables": [{
        "rows": [["Da•elict row"]],
        "cells": [{"row": 0, "col": 0, "text": "Da•elict row"}],
    }]}, ensure_ascii=False)
    group_id = connection.execute(
        """
        INSERT INTO question_groups (
            exam_subject_id, year, session, group_number, shared_text
        ) VALUES (?, 2024, 1, 1, ?)
        """,
        (question["exam_subject_id"], "공유 지문 f01그r token"),
    ).lastrowid
    connection.execute(
        "UPDATE questions SET question_format_json = ?, group_id = ? WHERE id = ?",
        (question_table, group_id, question["id"]),
    )
    connection.execute(
        """
        UPDATE question_choices
        SET choice_text = '선지 설명으로 을지 않은 것은', choice_format_json = ?
        WHERE question_id = ? AND choice_number = 1
        """,
        (choice_table, question["id"]),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def test_collect_findings_audits_question_choice_formats_and_shared_text(audit_connection):
    findings = collect_findings(audit_connection)
    paths = {finding.field_path for finding in findings}
    assert "question_text" in paths
    assert "question_format_json.tables[0].rows[0][0]" in paths
    assert "question_format_json.tables[0].cells[0].text" in paths
    assert "choice_text" in paths
    assert "choice_format_json.tables[0].rows[0][0]" in paths
    assert "choice_format_json.tables[0].cells[0].text" in paths
    assert "shared_text" in paths


def test_apply_changes_rejects_expected_value_mismatch(audit_connection):
    change = TextChange(
        table="question_groups", row_id=1, field="shared_text",
        before="다른 현재값", after="교정값", metadata={},
    )
    with pytest.raises(ValueError, match="expected current value mismatch"):
        apply_changes(audit_connection, [change])
```

- [ ] **Step 2: Run the DB repair tests and confirm RED**

Run: `pytest tests/test_repair_db_text.py -q`

Expected: import/attribute failures for the new core records and missing choice-format/shared-text findings.

- [ ] **Step 3: Implement the core records and exhaustive row enumeration**

Use immutable records in `src/database/text_repair.py`.

```python
@dataclass(frozen=True)
class TextChange:
    table: str
    row_id: int
    field: str
    before: str
    after: str
    format_field: str | None = None
    format_before: str | None = None
    format_after: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    rule: str = "conservative_auto"


@dataclass(frozen=True)
class TextFinding:
    category: str
    severity: Literal["blocked_quality", "needs_source_review"]
    table: str
    row_id: int
    question_id: int | None
    field_path: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AuditSummary:
    surface_counts: Mapping[str, int]
    changes: tuple[TextChange, ...]
    findings: tuple[TextFinding, ...]
```

Query questions and choices with source URL/page metadata, and query each question group once. Pass every text/format pair to `inspect_rich_text`. Structural issues and Task 2 `damaged_list_marker` are `blocked_quality`; legacy heuristic checks that have more than one possible correction are `needs_source_review`.

`collect_surface_counts(connection)` must use that same enumeration and return these exact keys: `question_text`, `question_format_rows`, `question_format_cells`, `choice_text`, `choice_format_rows`, `choice_format_cells`, `shared_text`.

- [ ] **Step 4: Implement expected-current transactional updates**

Every update must include the prior values in the `WHERE` predicate and require `rowcount == 1`. Use `IS ?` for nullable format JSON.

```python
def apply_changes(connection: sqlite3.Connection, changes: Sequence[TextChange]) -> None:
    with connection:
        for change in changes:
            if change.table == "questions":
                cursor = connection.execute(
                    """
                    UPDATE questions
                    SET question_text = ?, question_format_json = ?
                    WHERE id = ? AND question_text = ? AND question_format_json IS ?
                    """,
                    (change.after, change.format_after, change.row_id,
                     change.before, change.format_before),
                )
            elif change.table == "question_choices":
                cursor = connection.execute(
                    """
                    UPDATE question_choices
                    SET choice_text = ?, choice_format_json = ?
                    WHERE id = ? AND choice_text = ? AND choice_format_json IS ?
                    """,
                    (change.after, change.format_after, change.row_id,
                     change.before, change.format_before),
                )
            elif change.table == "question_groups":
                cursor = connection.execute(
                    "UPDATE question_groups SET shared_text = ? WHERE id = ? AND shared_text = ?",
                    (change.after, change.row_id, change.before),
                )
            else:
                raise ValueError(f"unsupported repair table: {change.table}")
            if cursor.rowcount != 1:
                raise ValueError(
                    f"expected current value mismatch: {change.table}#{change.row_id}"
                )
```

- [ ] **Step 5: Keep the old script API as thin wrappers and expand reports**

`scripts/repair_db_text.py` must re-export the core records/functions so existing imports remain valid. Extend JSON/Markdown with `surface_counts`, `blocked_quality_count`, `needs_source_review_count`, exact `field_path`, and source URL/page. The CLI remains dry-run by default.

- [ ] **Step 6: Run repair tests and the legacy single-DB CLI help**

Run: `pytest tests/test_repair_db_text.py -q`

Expected: all tests pass.

Run: `python scripts/repair_db_text.py --help`

Expected: exit 0 and options `--db`, `--output-dir`, `--apply`, `--confusables-only` remain present.

- [ ] **Step 7: Commit the audit-engine checkpoint**

```bash
git add src/database/text_repair.py scripts/repair_db_text.py tests/test_repair_db_text.py
git commit -m "feat: audit and repair all stored rich text"
```

### Task 5: Restore the exact 2022 maritime-English source case and make it reparse-safe

**Files:**

- Modify: `src/parser/offline_repairs.py:34-214`
- Modify: `src/database/ocr_repairs.py:27-337`
- Modify: `src/parser/offline_source_repairs.json`
- Modify: `tests/test_offline_db_rebuild.py`

**Interfaces:**

- Consumes: existing repair key `(source filename, source_page, question_number)` and `confidence="exact_source"`.
- Produces: optional registry fields `expected_current_stem`, `expected_current_question_format_json`, `repaired_question_format_json`; idempotent expected/repaired comparison; `apply_audited_repairs(..., allow_unmatched=False)`.

- [ ] **Step 1: Add failing parser and DB repair regressions**

Use the exact corrupted values from `exam_bank.Maritime.db` question id 1543. Assert the restored stem and both copies of the table cell.

```python
EXPECTED_STEM = "다음 <보기> 중 용어에 대한 설명으로 옳지 않은 것은 모두 몇 개인가?"
EXPECTED_VIEW = (
    "< 보 기 >\n"
    "㉠ Beach (to) : To run a vessel up on a beach\n"
    "to prevent its sinking in deep water\n"
    "㉡ Located : In navigational warnings ; position\n"
    "of object confirmed\n"
    "㉢ Half cardinal point : The four main points\n"
    "of the compass ; north, east, south and west\n"
    "㉣ Muster : List of crew, passengers and\n"
    "others on board and their functions in a\n"
    "distress or drill\n"
    "㉤ Derelict : A vessel which has been\n"
    "destroyed, sunk or abandoned at a sea"
)

assert repaired.stem == EXPECTED_STEM
payload = json.loads(repaired.question_format_json)
assert payload["tables"][0]["rows"][0][0] == EXPECTED_VIEW
assert payload["tables"][0]["cells"][0]["text"] == EXPECTED_VIEW
```

Add a DB test where `expected_current_stem` differs and assert the transaction rolls back both stem and format. Add an idempotency test where both fields already equal repaired values and assert no change count is incremented.

- [ ] **Step 2: Run the exact-source tests and confirm RED**

Run: `pytest tests/test_offline_db_rebuild.py -q -k "2022_maritime_english or expected_current_question_format"`

Expected: failures because the repair loader ignores `repaired_question_format_json` and DB application clears format JSON.

- [ ] **Step 3: Extend parser-side exact repair without trusting current OCR**

In `apply_audited_source_repair`, if `repaired_question_format_json` is present, require a JSON object, serialize it with `ensure_ascii=False`, and normalize it together with the repaired stem. The source filename/page/question key is authoritative on the parser side; `expected_current_*` is reserved for DB mutation safety.

```python
raw_question_format = repair.get("repaired_question_format_json")
if raw_question_format is not None:
    if not isinstance(raw_question_format, Mapping):
        raise ValueError(f"invalid audited question format for {key!r}")
    question_format_json = json.dumps(raw_question_format, ensure_ascii=False)
```

Run `inspect_rich_text` on the repaired stem/payload and raise when any structure issue remains.

- [ ] **Step 4: Enforce DB expected-current values and update stem/format together**

Add semantic JSON equality so insignificant key ordering does not cause mismatch.

```python
def _json_object(value: object, *, label: str) -> dict:
    payload = json.loads(value) if isinstance(value, str) else value
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _matches_expected(current: object, expected: object, repaired: object) -> bool:
    return current == expected or current == repaired
```

For format values, compare parsed dicts. If neither expected nor repaired matches, raise before any update. Replace the current `question_format_json = NULL` behavior with one update of both fields.

```python
connection.execute(
    "UPDATE questions SET question_text = ?, question_format_json = ? WHERE id = ?",
    (repaired_stem_value, repaired_format_text, int(question_id)),
)
```

Add keyword-only `allow_unmatched: bool = False` to `apply_audited_repairs`. Preserve the current strict default for rebuild tests. The four-DB batch passes `True`, so a source repair absent from one domain DB is skipped; a unique row that exists but fails its expected-current check still aborts.

```python
if len(rows) == 0 and allow_unmatched:
    continue
if len(rows) != 1:
    raise ValueError(
        f"audited repair identity is not unique: {identity!r}: {len(rows)}"
    )
```

- [ ] **Step 5: Add the complete exact registry record**

Append this complete `confidence="exact_source"` object to `repairs`. Keep the two table-text strings byte-identical inside each payload.

```json
{
  "question_id": 1543,
  "year": 2022,
  "session": 3,
  "question_number": 3,
  "subject": "해사영어",
  "source_pdf_relative_path": "[론박]해사영어(25년 하반기 포함)/[기출문제]해사영어(24년-13년).pdf",
  "source_page": 24,
  "confidence": "exact_source",
  "evidence_note": "원본 PDF 24쪽 3번 발문과 <보기>를 직접 판독",
  "expected_current_stem": "다음 <보기> 중 용어에 대한 설명으로 을지 않은 것은 모두 개인가?",
  "repaired_stem": "다음 <보기> 중 용어에 대한 설명으로 옳지 않은 것은 모두 몇 개인가?",
  "expected_current_question_format_json": {
    "schema_version": 2,
    "tables": [
      {
        "id": "view-table-1",
        "rows": [["< 보 기 >\n@ Beach (to): To run a vessel up on a beach\nto prevent its sinking in deep water\nLocated: In navigational warnings; position\nof object confirmed\n㉢ HaIf cardinal point: The f01그r main points\nof the; north, east, south and west\n@ Muster List of crew, passengers and\nothers on board and their functions in a\ndistress or drill\n㉤ Da•elict: A vessel which has been\ndestroyed, sunk or abandoned at a sea"]],
        "cells": [
          {
            "row": 0,
            "col": 0,
            "text": "< 보 기 >\n@ Beach (to): To run a vessel up on a beach\nto prevent its sinking in deep water\nLocated: In navigational warnings; position\nof object confirmed\n㉢ HaIf cardinal point: The f01그r main points\nof the; north, east, south and west\n@ Muster List of crew, passengers and\nothers on board and their functions in a\ndistress or drill\n㉤ Da•elict: A vessel which has been\ndestroyed, sunk or abandoned at a sea",
            "row_span": 1,
            "col_span": 1,
            "horizontal_alignment": "left",
            "vertical_alignment": "center",
            "spans": []
          }
        ],
        "anchor": {
          "offset": 38,
          "before_context": "대한 설명으로 을지 않은 것은\n모두 개인가?",
          "after_context": ""
        },
        "source": {"kind": "view_block_text"},
        "confidence": {"score": 1.0, "reasons": ["explicit_view_marker"]},
        "render_mode": "native",
        "column_widths": [],
        "row_heights": [],
        "borders": [],
        "layout": {"width_mode": "auto", "wide": false},
        "complexity": {
          "has_formula": false,
          "has_embedded_image": false,
          "has_rotated_text": false,
          "has_complex_merge": false,
          "has_duplicate_text_risk": false
        },
        "recommended_render": "native"
      }
    ]
  },
  "repaired_question_format_json": {
    "schema_version": 2,
    "tables": [
      {
        "id": "view-table-1",
        "rows": [["< 보 기 >\n㉠ Beach (to) : To run a vessel up on a beach\nto prevent its sinking in deep water\n㉡ Located : In navigational warnings ; position\nof object confirmed\n㉢ Half cardinal point : The four main points\nof the compass ; north, east, south and west\n㉣ Muster : List of crew, passengers and\nothers on board and their functions in a\ndistress or drill\n㉤ Derelict : A vessel which has been\ndestroyed, sunk or abandoned at a sea"]],
        "cells": [
          {
            "row": 0,
            "col": 0,
            "text": "< 보 기 >\n㉠ Beach (to) : To run a vessel up on a beach\nto prevent its sinking in deep water\n㉡ Located : In navigational warnings ; position\nof object confirmed\n㉢ Half cardinal point : The four main points\nof the compass ; north, east, south and west\n㉣ Muster : List of crew, passengers and\nothers on board and their functions in a\ndistress or drill\n㉤ Derelict : A vessel which has been\ndestroyed, sunk or abandoned at a sea",
            "row_span": 1,
            "col_span": 1,
            "horizontal_alignment": "left",
            "vertical_alignment": "center",
            "spans": []
          }
        ],
        "anchor": {
          "offset": 40,
          "before_context": "용어에 대한 설명으로 옳지 않은 것은 모두 몇 개인가?",
          "after_context": ""
        },
        "source": {"kind": "view_block_text"},
        "confidence": {"score": 1.0, "reasons": ["explicit_view_marker"]},
        "render_mode": "native",
        "column_widths": [],
        "row_heights": [],
        "borders": [],
        "layout": {"width_mode": "auto", "wide": false},
        "complexity": {
          "has_formula": false,
          "has_embedded_image": false,
          "has_rotated_text": false,
          "has_complex_merge": false,
          "has_duplicate_text_risk": false
        },
        "recommended_render": "native"
      }
    ]
  }
}
```

- [ ] **Step 6: Run exact repair, staging, and registry loader tests**

Run: `pytest tests/test_offline_db_rebuild.py -q`

Expected: all tests pass, including transaction rollback and idempotency.

- [ ] **Step 7: Commit the exact-source checkpoint**

```bash
git add src/parser/offline_repairs.py src/database/ocr_repairs.py src/parser/offline_source_repairs.json tests/test_offline_db_rebuild.py
git commit -m "fix: restore maritime English source text"
```

### Task 6: Prepare and atomically replace a validated four-DB batch

**Files:**

- Create: `src/database/text_repair_batch.py`
- Create: `tests/test_text_repair_batch.py`

**Interfaces:**

- Consumes: Task 4 audit/apply functions, `apply_audited_repairs`, SQLite backup, `ExamRepository` read APIs.
- Produces: `RepairTarget`, `PreparedDatabaseRepair`, `prepare_repair_batch(targets, repairs_path, work_dir)`, `commit_repair_batch(prepared, backup_dir, receipt_path)`.

- [ ] **Step 1: Add failing all-before-any and rollback tests**

Create four tiny valid DBs with distinct byte hashes. In the first test inject invalid format JSON into the fourth DB and assert no mounted bytes change. In the second test monkeypatch the module's `_atomic_replace` to fail on the second mounted replacement and assert all four mounted hashes return to their original values.

```python
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import src.database.text_repair_batch as batch
from src.database.repository import ExamRepository
from src.database.text_repair_batch import (
    BatchRepairError,
    RepairTarget,
    commit_repair_batch,
    prepare_repair_batch,
)


def _create_valid_database(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = ExamRepository(str(path))
    repository.init_database()
    template = repository.get_manual_question_template()
    template.update({
        "question_text": f"정상 발문 {label}",
        "correct_answer": 1,
        "choices": [
            {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
            {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
            {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
            {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
        ],
    })
    assert repository.create_manual_question(template) is not None


def make_four_targets(tmp_path: Path) -> tuple[RepairTarget, ...]:
    targets = []
    for index, name in enumerate(("one", "two", "three", "four"), start=1):
        path = tmp_path / f"{name}.db"
        _create_valid_database(path, str(index))
        targets.append(RepairTarget(name, path))
    return tuple(targets)


def repairs_path(tmp_path: Path) -> Path:
    path = tmp_path / "repairs.json"
    path.write_text(json.dumps({"repairs": []}), encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corrupt_format_json(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE questions SET question_format_json = '[1, 2]' WHERE id = (SELECT MIN(id) FROM questions)"
        )


def test_prepare_batch_validates_every_staging_before_any_mount_change(tmp_path):
    targets = make_four_targets(tmp_path)
    corrupt_format_json(targets[-1].mounted_path)
    before = {target.name: sha256(target.mounted_path) for target in targets}
    with pytest.raises(BatchRepairError, match="invalid_format_json"):
        prepare_repair_batch(targets, repairs_path(tmp_path), tmp_path / "work")
    assert {target.name: sha256(target.mounted_path) for target in targets} == before


def test_commit_batch_rolls_back_every_replaced_database(tmp_path, monkeypatch):
    targets = make_four_targets(tmp_path)
    prepared = prepare_repair_batch(targets, repairs_path(tmp_path), tmp_path / "work")
    before = {target.name: sha256(target.mounted_path) for target in targets}
    real_replace = batch._atomic_replace
    mounted_calls = 0

    def fail_second_mounted(source, target):
        nonlocal mounted_calls
        if Path(target).name.endswith(".db"):
            mounted_calls += 1
            if mounted_calls == 2:
                raise OSError("simulated second replacement failure")
        return real_replace(source, target)

    monkeypatch.setattr(batch, "_atomic_replace", fail_second_mounted)
    with pytest.raises(BatchRepairError, match="simulated second replacement failure"):
        commit_repair_batch(prepared, tmp_path / "backups", tmp_path / "receipt.json")
    assert {target.name: sha256(target.mounted_path) for target in targets} == before
```

- [ ] **Step 2: Run batch tests and confirm RED**

Run: `pytest tests/test_text_repair_batch.py -q`

Expected: collection fails because the batch module does not exist.

- [ ] **Step 3: Implement staging preparation and validation**

```python
@dataclass(frozen=True)
class RepairTarget:
    name: str
    mounted_path: Path


@dataclass(frozen=True)
class DatabaseRepairValidation:
    valid: bool
    integrity_check: str
    foreign_key_errors: tuple[tuple[object, ...], ...]
    schema_errors: tuple[str, ...]
    smoke_ok: bool
    error_codes: tuple[str, ...]


@dataclass(frozen=True)
class PreparedDatabaseRepair:
    target: RepairTarget
    staging_path: Path
    original_sha256: str
    staging_sha256: str
    audit: AuditSummary
    source_repair_result: OcrRepairResult
    validation: DatabaseRepairValidation


class BatchRepairError(RuntimeError):
    pass
```

Implement preparation in this exact order. `_copy_sqlite_database` uses `source_connection.backup(destination_connection)` and closes both connections before returning. `_validate_repair_database` runs `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, compares `PRAGMA table_info` against `staging.REQUIRED_SCHEMA`, and uses a read-only `ExamRepository` subclass for `get_statistics`, `search_questions(limit=1)`, and `get_question`.

```python
def prepare_repair_batch(
    targets: Sequence[RepairTarget],
    repairs_path: str | Path,
    work_dir: str | Path,
) -> tuple[PreparedDatabaseRepair, ...]:
    work = Path(work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    prepared: list[PreparedDatabaseRepair] = []
    for target in targets:
        mounted = target.mounted_path.resolve()
        if not mounted.is_file():
            raise BatchRepairError(f"mounted database does not exist: {mounted}")
        staging_path = work / f"{target.name}.staging.db"
        _copy_sqlite_database(mounted, staging_path)
        source_result = apply_audited_repairs(
            staging_path, repairs_path, allow_unmatched=True
        )
        with sqlite3.connect(staging_path) as connection:
            connection.row_factory = sqlite3.Row
            changes, skipped = collect_changes(connection)
            if skipped:
                raise BatchRepairError(
                    f"formatted repairs skipped for {target.name}: {len(skipped)}"
                )
            apply_changes(connection, changes)
            findings = tuple(collect_findings(connection))
            surface_counts = collect_surface_counts(connection)
        validation = _validate_repair_database(staging_path)
        blocked = tuple(
            finding for finding in findings
            if finding.severity == "blocked_quality"
        )
        if blocked or not validation.valid:
            codes = [finding.category for finding in blocked]
            codes.extend(validation.error_codes)
            raise BatchRepairError(f"{target.name}: " + ", ".join(codes))
        prepared.append(PreparedDatabaseRepair(
            target=RepairTarget(target.name, mounted),
            staging_path=staging_path,
            original_sha256=sha256_file(mounted),
            staging_sha256=sha256_file(staging_path),
            audit=AuditSummary(
                surface_counts=surface_counts,
                changes=tuple(changes),
                findings=findings,
            ),
            source_repair_result=source_result,
            validation=validation,
        ))
    return tuple(prepared)
```

Only `blocked_quality` findings fail preparation. `needs_source_review` findings remain unchanged and are included in the report.

- [ ] **Step 4: Implement backup, prebuilt replacements, group commit, and rollback**

Before the first mounted replacement, create and validate all SQLite backups and all replacement-temp copies. Record original and staging hashes. Use this control flow so any exception restores every target whose current hash differs from its original hash. `_restore_backup` copies a validated SQLite backup to a sibling temp, fsyncs it, and calls `_atomic_replace`.

```python
def commit_repair_batch(prepared, backup_dir, receipt_path):
    backups = _prepare_all_backups(prepared, Path(backup_dir).resolve())
    replacements = _prepare_all_replacement_copies(prepared)
    try:
        for item in prepared:
            _atomic_replace(replacements[item.target.name], item.target.mounted_path)
        for item in prepared:
            validation = _validate_repair_database(item.target.mounted_path)
            if not validation.valid:
                raise BatchRepairError(
                    f"post-replacement validation failed: {item.target.name}"
                )
        receipt = {
            "status": "applied",
            "targets": [
                {
                    "name": item.target.name,
                    "mounted_path": str(item.target.mounted_path),
                    "backup_path": str(backups[item.target.name]),
                    "before_sha256": item.original_sha256,
                    "after_sha256": sha256_file(item.target.mounted_path),
                }
                for item in prepared
            ],
        }
        write_json_atomic(Path(receipt_path), receipt)
        return receipt
    except Exception as error:
        restore_errors = []
        for item in prepared:
            if sha256_file(item.target.mounted_path) != item.original_sha256:
                try:
                    _restore_backup(
                        backups[item.target.name], item.target.mounted_path
                    )
                except Exception as restore_error:
                    restore_errors.append(
                        f"{item.target.name}: {restore_error}"
                    )
        if restore_errors:
            raise BatchRepairError(
                f"{error}; rollback failed: {'; '.join(restore_errors)}"
            ) from error
        raise BatchRepairError(str(error)) from error
    finally:
        for replacement in replacements.values():
            replacement.unlink(missing_ok=True)
```

- [ ] **Step 5: Run all batch tests**

Run: `pytest tests/test_text_repair_batch.py -q`

Expected: all tests pass; no test leaves a partially replaced target.

- [ ] **Step 6: Commit the batch-transaction checkpoint**

```bash
git add src/database/text_repair_batch.py tests/test_text_repair_batch.py
git commit -m "feat: replace repaired databases as one batch"
```

### Task 7: Add the four-DB dry-run/apply CLI and complete reports

**Files:**

- Create: `src/database/source_review.py`
- Create: `scripts/repair_active_db_text.py`
- Create: `tests/test_source_review.py`
- Create: `tests/test_repair_active_db_text.py`

**Interfaces:**

- Consumes: Task 6 `prepare_repair_batch` and `commit_repair_batch`; `TextFinding.metadata`의 `source_url`/`source_page`.
- Produces: `SourceEvidence`, `render_source_evidence(findings, output_dir)`, CLI options `--root`, `--repairs`, `--output-dir`, `--apply`; `summary.json`, `summary.md`, per-DB audit JSON, 검토용 PDF page PNG.

- [ ] **Step 1: Add failing source-evidence tests**

```python
import fitz

from src.database.source_review import render_source_evidence


def test_render_source_evidence_deduplicates_pdf_page(tmp_path):
    pdf_path = tmp_path / "source.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=200)
    page.insert_text((20, 40), "source evidence")
    document.save(pdf_path)
    document.close()
    findings = [
        TextFinding(
            category="ocr_review", severity="needs_source_review",
            table="questions", row_id=1, question_id=1,
            field_path="question_text", text="suspect",
            metadata={"source_url": pdf_path.as_uri(), "source_page": 1},
        ),
        TextFinding(
            category="ocr_review", severity="needs_source_review",
            table="questions", row_id=1, question_id=1,
            field_path="question_format_json.tables[0].rows[0][0]", text="suspect",
            metadata={"source_url": pdf_path.as_uri(), "source_page": 1},
        ),
    ]
    evidence = render_source_evidence(findings, tmp_path / "evidence")
    assert len(evidence) == 1
    assert evidence[0].status == "rendered"
    assert evidence[0].image_path.is_file()


def test_render_source_evidence_reports_missing_source_without_guessing(tmp_path):
    finding = TextFinding(
        category="ocr_review", severity="needs_source_review",
        table="questions", row_id=1, question_id=1,
        field_path="question_text", text="suspect",
        metadata={"source_url": (tmp_path / "missing.pdf").as_uri(), "source_page": 2},
    )
    evidence = render_source_evidence([finding], tmp_path / "evidence")
    assert evidence[0].status == "source_unavailable"
    assert evidence[0].image_path is None
```

- [ ] **Step 2: Run source-evidence tests and confirm RED**

Run: `pytest tests/test_source_review.py -q`

Expected: collection fails because `src.database.source_review` does not exist.

- [ ] **Step 3: Implement safe file-URL resolution and one render per source page**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import fitz


@dataclass(frozen=True)
class SourceEvidence:
    source_url: str
    source_page: int
    status: str
    image_path: Path | None
    finding_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "source_page": self.source_page,
            "status": self.status,
            "image_path": str(self.image_path) if self.image_path else None,
            "finding_count": self.finding_count,
        }


def _file_url_path(source_url: str) -> Path | None:
    parsed = urlparse(source_url)
    if parsed.scheme not in ("", "file"):
        return None
    decoded = unquote(parsed.path)
    if parsed.netloc:
        decoded = f"//{parsed.netloc}{decoded}"
    if len(decoded) >= 3 and decoded[0] == "/" and decoded[2] == ":":
        decoded = decoded[1:]
    return Path(decoded)


def render_source_evidence(findings, output_dir: Path) -> tuple[SourceEvidence, ...]:
    grouped: dict[tuple[str, int], list] = {}
    for finding in findings:
        source_url = str(finding.metadata.get("source_url") or "")
        source_page = int(finding.metadata.get("source_page") or 0)
        if source_url and source_page > 0:
            grouped.setdefault((source_url, source_page), []).append(finding)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, ((source_url, source_page), matches) in enumerate(sorted(grouped.items()), start=1):
        source_path = _file_url_path(source_url)
        if source_path is None or not source_path.is_file():
            results.append(SourceEvidence(source_url, source_page, "source_unavailable", None, len(matches)))
            continue
        with fitz.open(source_path) as document:
            if source_page > document.page_count:
                results.append(SourceEvidence(source_url, source_page, "page_unavailable", None, len(matches)))
                continue
            image_path = output_dir / f"source_{index:04d}_page_{source_page}.png"
            document[source_page - 1].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(image_path)
        results.append(SourceEvidence(source_url, source_page, "rendered", image_path, len(matches)))
    return tuple(results)
```

- [ ] **Step 4: Run source-evidence tests and confirm GREEN**

Run: `pytest tests/test_source_review.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Add failing CLI tests**

```python
import json
from pathlib import Path

import scripts.repair_active_db_text as cli
from src.database.repository import ExamRepository


def _create_cli_database(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repository = ExamRepository(str(path))
    repository.init_database()
    template = repository.get_manual_question_template()
    template.update({
        "question_text": f"CLI 정상 발문 {label}",
        "correct_answer": 1,
        "choices": [
            {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
            {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
            {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
            {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
        ],
    })
    assert repository.create_manual_question(template) is not None


def make_active_db_tree(tmp_path: Path) -> Path:
    paths = (
        Path("data/domain_dbs/exam_bank.maritime_all.db"),
        Path("data/domain_dbs/exam_bank.user_workspace.db"),
        Path("data/domain_dbs/exam_bank.Maritime.db"),
        Path("data/exam_bank.db"),
    )
    for index, relative in enumerate(paths, start=1):
        _create_cli_database(tmp_path / relative, str(index))
    return tmp_path


def test_cli_is_dry_run_by_default_and_uses_exact_four_targets(tmp_path, monkeypatch):
    root = make_active_db_tree(tmp_path)
    prepared_calls = []
    commit_calls = []
    monkeypatch.setattr(cli, "prepare_repair_batch", lambda targets, repairs, work: prepared_calls.append(tuple(targets)) or ())
    monkeypatch.setattr(cli, "commit_repair_batch", lambda *args: commit_calls.append(args))
    assert cli.main(["--root", str(root), "--output-dir", str(tmp_path / "report")]) == 0
    assert [target.name for target in prepared_calls[0]] == [
        "maritime_all", "user_workspace", "Maritime", "legacy_exam_bank",
    ]
    assert commit_calls == []


def test_cli_apply_writes_machine_and_human_reports(tmp_path):
    root = make_active_db_tree(tmp_path)
    output = tmp_path / "report"
    assert cli.main(["--root", str(root), "--output-dir", str(output), "--apply"]) == 0
    payload = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "apply"
    assert len(payload["databases"]) == 4
    assert (output / "summary.md").is_file()
```

- [ ] **Step 6: Run CLI tests and confirm RED**

Run: `pytest tests/test_repair_active_db_text.py -q`

Expected: collection fails because `scripts.repair_active_db_text` does not exist.

- [ ] **Step 7: Implement fixed target resolution and dry-run-first behavior**

```python
TARGETS = (
    ("maritime_all", Path("data/domain_dbs/exam_bank.maritime_all.db")),
    ("user_workspace", Path("data/domain_dbs/exam_bank.user_workspace.db")),
    ("Maritime", Path("data/domain_dbs/exam_bank.Maritime.db")),
    ("legacy_exam_bank", Path("data/exam_bank.db")),
)


def active_targets(root: Path) -> tuple[RepairTarget, ...]:
    resolved_root = root.resolve()
    targets = tuple(
        RepairTarget(name, (resolved_root / relative).resolve())
        for name, relative in TARGETS
    )
    missing = [str(target.mounted_path) for target in targets if not target.mounted_path.is_file()]
    if missing:
        raise FileNotFoundError("missing active databases: " + ", ".join(missing))
    return targets
```

Always call `prepare_repair_batch`. Call `commit_repair_batch` only with `--apply`. Store work DBs below `<output-dir>/staging`, backups below `<output-dir>/backups`, and receipt at `<output-dir>/receipt.json`. The summary must include counts for inspected question text, choice text, question rows/cells, choice rows/cells, shared passages, conservative changes, source-confirmed changes, blocked findings, and review findings.

After preparation, pass every `needs_source_review` finding to `render_source_evidence(..., output_dir / "source_evidence")`. Add every `SourceEvidence` record to JSON and show `source_unavailable`/`page_unavailable` explicitly; neither status authorizes a text change.

- [ ] **Step 8: Implement deterministic Markdown rendering**

The Markdown must contain one table row per DB and sections for `blocked_quality`, `needs_source_review`, changes with before/after, source URL/page, integrity result, foreign-key result, smoke result, backup path, and applied state. Limit only the Markdown preview; keep every record in JSON.

- [ ] **Step 9: Run CLI and repair regression tests**

Run: `pytest tests/test_source_review.py tests/test_repair_active_db_text.py tests/test_text_repair_batch.py tests/test_repair_db_text.py -q`

Expected: all tests pass.

- [ ] **Step 10: Commit the CLI/report checkpoint**

```bash
git add src/database/source_review.py scripts/repair_active_db_text.py tests/test_source_review.py tests/test_repair_active_db_text.py
git commit -m "feat: audit and repair active databases"
```

### Task 8: Execute the real audit, apply the validated batch, verify, and publish one commit

**Files:**

- Modify locally but do not Git-add: the four active `.db` files listed in Global Constraints.
- Create locally but do not Git-add: `tmp/ocr_rich_text_20260722/**` reports, staging copies, backups, receipt.
- Verify tracked changes: all code, tests, `src/parser/offline_source_repairs.json`, design, and this plan.

**Interfaces:**

- Consumes: `scripts/repair_active_db_text.py` and `scripts/verify_domain_mounts.py`.
- Produces: validated local DBs, audit/apply reports, one pushed `main` commit.

- [ ] **Step 1: Run the complete automated suite before touching active DBs**

Run: `pytest -q`

Expected: exit 0 with no failures.

- [ ] **Step 2: Run a full four-DB dry-run**

Run:

```powershell
python scripts/repair_active_db_text.py `
  --root . `
  --repairs src/parser/offline_source_repairs.json `
  --output-dir tmp/ocr_rich_text_20260722/dry_run
```

Expected: exit 0, `mode="dry-run"`, four DB entries, `applied=false`, and no mounted DB hash changes. Confirm the JSON reports count both rows and cells for question and choice formats and include shared-text counts.

- [ ] **Step 3: Review all dry-run classifications before apply**

Run:

```powershell
$report = Get-Content -Raw tmp/ocr_rich_text_20260722/dry_run/summary.json | ConvertFrom-Json
$report.databases | Select-Object name, blocked_quality_count, needs_source_review_count, change_count
```

Expected: every `blocked_quality_count` is `0` after staging repairs. `needs_source_review_count` may be nonzero, but every such record must retain its original text and include `source_url`, `source_page`, `question_number`, and `field_path`. Confirm `Maritime` question 1543 appears under source-confirmed changes with the exact before/after values from Task 5.

- [ ] **Step 4: Apply the already validated four-DB batch**

Run:

```powershell
python scripts/repair_active_db_text.py `
  --root . `
  --repairs src/parser/offline_source_repairs.json `
  --output-dir tmp/ocr_rich_text_20260722/apply `
  --apply
```

Expected: exit 0, `mode="apply"`, `status="applied"`, four validated backup paths, four before/after hashes, and an atomic receipt.

- [ ] **Step 5: Verify the reported question directly and verify all mounts**

Run a read-only SQLite assertion:

```powershell
$env:PYTHONIOENCODING='utf-8'
@'
import json, sqlite3
from pathlib import Path
path = Path("data/domain_dbs/exam_bank.Maritime.db").resolve()
con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
row = con.execute("SELECT question_text, question_format_json FROM questions WHERE id = 1543").fetchone()
assert row[0] == "다음 <보기> 중 용어에 대한 설명으로 옳지 않은 것은 모두 몇 개인가?"
payload = json.loads(row[1])
assert payload["tables"][0]["rows"][0][0] == payload["tables"][0]["cells"][0]["text"]
assert "㉠ Beach (to) :" in payload["tables"][0]["rows"][0][0]
assert "㉤ Derelict :" in payload["tables"][0]["rows"][0][0]
assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
con.close()
'@ | python -
```

Expected: exit 0.

Run: `python scripts/verify_domain_mounts.py --out tmp/ocr_rich_text_20260722/domain_mount_verification.json`

Expected: exit 0, mounted question total equals summed domain question total, and namespaced IDs are valid.

- [ ] **Step 6: Re-run focused and full regression suites after DB application**

Run: `pytest tests/test_rich_text_quality.py tests/test_text_cleanup.py tests/test_database_validator.py tests/test_repair_db_text.py tests/test_offline_db_rebuild.py tests/test_text_repair_batch.py tests/test_source_review.py tests/test_repair_active_db_text.py tests/test_repository.py -q`

Expected: exit 0.

Run: `pytest -q`

Expected: exit 0 with no failures.

- [ ] **Step 7: Confirm ignored runtime artifacts and tracked scope**

Run: `git status --short --ignored`

Expected: the four `.db` files and `tmp/ocr_rich_text_20260722/**` appear only as ignored entries; tracked changes contain code, tests, registry, design, and plan. Do not use `git add -f` for DBs or reports.

- [ ] **Step 8: Squash all unpushed OCR checkpoints into the user's single commit**

Because `origin/main` is the published base and the OCR design/checkpoints are local, squash only the unpushed range:

```bash
git reset --soft origin/main
git add docs/superpowers/specs/2026-07-21-ocr-rich-text-quality-and-db-repair-design.md docs/superpowers/plans/2026-07-22-ocr-rich-text-quality-and-db-repair.md src/parser/rich_text_quality.py src/parser/text_quality.py src/parser/formatting.py src/parser/offline_quality.py src/parser/offline_repairs.py src/parser/offline_source_repairs.json src/database/validator.py src/database/staging.py src/database/text_repair.py src/database/ocr_repairs.py src/database/text_repair_batch.py src/database/source_review.py scripts/repair_db_text.py scripts/repair_active_db_text.py tests/test_rich_text_quality.py tests/test_text_cleanup.py tests/test_database_validator.py tests/test_repair_db_text.py tests/test_offline_db_rebuild.py tests/test_text_repair_batch.py tests/test_source_review.py tests/test_repair_active_db_text.py
git commit -m "Improve OCR rich text validation and repair"
```

Expected: exactly one local commit exists above `origin/main` and contains no `.db`, backup, staging, or report files.

- [ ] **Step 9: Verify the final commit and push main**

Run: `git diff --check origin/main..HEAD`

Expected: no output.

Run: `git status --short --branch`

Expected: clean worktree and `main...origin/main [ahead 1]`.

Run: `git push origin main`

Expected: push succeeds and local `main` equals `origin/main`.
