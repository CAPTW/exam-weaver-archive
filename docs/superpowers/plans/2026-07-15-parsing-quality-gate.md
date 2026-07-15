# Parsing Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OCR·PDF 파싱 문항을 공통 규칙으로 검수하고 불확실한 후보를 격리하며, 오류가 남은 staging DB의 Mounted DB 승격을 자동 차단한다.

**Architecture:** `src/parser/text_quality.py`가 문맥 독립적인 OCR 품질 판정을 제공하고 parser 후보 게이트와 DB validator가 이를 공유한다. `build_staging_database`는 후보별 격리 정보를 DB와 JSON에 보존하며, `validate_staging_database`는 적재된 전 문항을 다시 검사해 차단 가능한 품질 오류를 `ValidationReport`에 포함한다.

**Tech Stack:** Python 3, dataclasses, SQLite, pytest, 기존 `ExamRepository`/`QuestionValidator`/offline parser pipeline

## Global Constraints

- 의미가 확실한 정규화만 자동 적용하고 문맥 추정이 필요한 오류는 원문을 보존해 격리한다.
- Mounted DB 교체는 기존 백업·원자적 교체 흐름을 유지하며 품질 게이트 실패 시 운영 DB를 변경하지 않는다.
- 기존 공개 importer와 운영 문항 스키마의 호출 호환성을 유지한다.
- 사용자 소유의 무관한 ZIP 파일은 stage·commit하지 않는다.

---

## File Structure

- Create `src/parser/text_quality.py`: OCR 노이즈, 깨진 단위, 괄호 균형 공통 판정.
- Modify `src/parser/offline_quality.py`: 공통 판정 결과를 파서 후보 거부 사유로 변환.
- Modify `src/database/validator.py`: 중복 정규식을 제거하고 공통 판정기를 사용.
- Modify `scripts/repair_db_text.py`: 외부 호출 호환용 괄호 판정 wrapper를 공통 구현에 연결.
- Modify `src/database/staging.py`: 격리 테이블·보고서, DB 전체 품질 스캔, 승격 차단 보고 필드.
- Modify `tests/test_offline_source_adapters.py`: 후보 게이트의 실패/정상 특수기호 회귀 테스트.
- Modify `tests/test_offline_db_rebuild.py`: 격리 보존과 staging 최종 품질 게이트 통합 테스트.
- Modify `tests/test_database_validator.py`: 공통 판정기로 전환한 validator 동작 회귀 테스트.

### Task 1: 공통 텍스트 품질 판정과 파서 후보 게이트

**Files:**
- Create: `src/parser/text_quality.py`
- Modify: `src/parser/offline_quality.py:55`
- Modify: `tests/test_offline_source_adapters.py`

**Interfaces:**
- Produces: `text_quality_issue_codes(text: str) -> tuple[str, ...]`, `has_unbalanced_delimiters(text: str) -> bool`
- Consumes: 기존 `ParsedOfflineQuestion`, `has_suspicious_text_artifact`

- [ ] **Step 1: 의심 후보가 거부되고 정상 기호는 통과하는 실패 테스트 작성**

```python
@pytest.mark.parametrize(
    ("stem", "choices", "reason"),
    [
        ("카르노 사이클은?", ("정적압축 정적팽창 단열팽창 단열압축→→→", "나", "다", "라"), "suspicious_choice"),
        ("압력은 [0/해 로 표시한다.", ("가", "나", "다", "라"), "broken_unit_stem"),
        ("다음 (설명 중 옳은 것은?", ("가", "나", "다", "라"), "unbalanced_stem_delimiter"),
    ],
)
def test_offline_quality_rejects_residual_text_corruption(stem, choices, reason):
    result = validate_offline_question(
        ParsedOfflineQuestion(1, stem, list(choices), 1, 1.0, ())
    )
    assert result.importable is False
    assert reason in result.reason_codes

def test_offline_quality_accepts_valid_arrows_and_example_parenthesis():
    result = validate_offline_question(
        ParsedOfflineQuestion(1, "A → B의 관계는?", ["Ex.) 정상 예시", "나", "다", "라"], 1, 1.0, ())
    )
    assert result.importable is True
```

- [ ] **Step 2: 테스트를 실행해 현재 동작이 실패하는지 확인**

Run: `pytest tests/test_offline_source_adapters.py -k "residual_text_corruption or valid_arrows" -v`

Expected: 의심 후보가 importable로 판정되어 최소 1개 FAIL.

- [ ] **Step 3: 공통 판정기와 후보 사유 매핑 구현**

```python
# src/parser/text_quality.py
OCR_NOISE_PATTERN = re.compile(r"(?:0[卜ㅏ]|(?<![A-Za-z])[O0]h(?![A-Za-z])|[卜入人]{2,}|으\s*(?:9|느|그)|으\s+거|[가-힣A-Za-z][卜入人][가-힣A-Za-z]|[쥐튢飇恤喬盞])")
BROKEN_UNIT_PATTERN = re.compile(r"\[(?:0/해|Ⅵ|H기|시|외|이(?=\s|$|[\]\)])|P비|kg되|넣디|Q|\(\)|\))")

def text_quality_issue_codes(text: str) -> tuple[str, ...]:
    value = str(text or "")
    codes = []
    if OCR_NOISE_PATTERN.search(value):
        codes.append("ocr_noise")
    if BROKEN_UNIT_PATTERN.search(value):
        codes.append("broken_unit")
    if has_unbalanced_delimiters(value):
        codes.append("unbalanced_delimiter")
    return tuple(codes)
```

`validate_offline_question`에서 발문과 각 선지를 검사하고 `ocr_noise_stem`, `broken_unit_choice`, `unbalanced_stem_delimiter`, `suspicious_choice`처럼 위치가 포함된 사유 코드를 중복 없이 추가한다.

- [ ] **Step 4: 후보 게이트 테스트 통과 확인**

Run: `pytest tests/test_offline_source_adapters.py -k "residual_text_corruption or valid_arrows" -v`

Expected: 선택된 테스트 전부 PASS.

### Task 2: 기존 DB validator와 수리 스크립트의 판정 통합

**Files:**
- Modify: `src/database/validator.py:1-240`
- Modify: `scripts/repair_db_text.py:308`
- Modify: `tests/test_database_validator.py`
- Modify: `tests/test_repair_db_text.py`

**Interfaces:**
- Consumes: `text_quality_issue_codes`, `has_unbalanced_delimiters`
- Produces: 기존 `QuestionValidator.scan()` 및 `scripts.repair_db_text.has_unbalanced_delimiters()`와 동일한 공개 동작

- [ ] **Step 1: 공통 규칙의 validator 사유·심각도 회귀 테스트 작성**

```python
def test_question_validator_maps_shared_text_quality_codes(repo, sample_metadata, sample_question):
    sample_question.text = "다음 (설명에서 [0/해 값을 고르시오."
    repo.save_questions([sample_question], sample_metadata)
    codes = {
        issue["code"]
        for finding in QuestionValidator(repo).scan()
        for issue in finding["issues"]
    }
    assert {"broken_unit_text", "unbalanced_delimiter"} <= codes
```

- [ ] **Step 2: 테스트 실행 후 실패 또는 기존 중복 구현 의존 확인**

Run: `pytest tests/test_database_validator.py tests/test_repair_db_text.py -v`

Expected: 새 공유 인터페이스가 아직 없어 수집 또는 assertion 단계 FAIL.

- [ ] **Step 3: validator와 수리 스크립트를 공통 판정기에 연결**

```python
from ..parser.text_quality import has_unbalanced_delimiters, text_quality_issue_codes

def _validate_text_quality(self, text, label, issues):
    codes = text_quality_issue_codes(text)
    if "ocr_noise" in codes:
        issues.append(self._issue("ocr_noise_text", f"{label} OCR 잡문자 의심", "error"))
    if "broken_unit" in codes:
        issues.append(self._issue("broken_unit_text", f"{label} 단위/수식 깨짐 의심", "warning"))
    if "unbalanced_delimiter" in codes:
        issues.append(self._issue("unbalanced_delimiter", f"{label} 괄호/대괄호 불균형", "warning"))
```

`scripts/repair_db_text.py`는 기존 함수명을 보존한 wrapper로 공통 `has_unbalanced_delimiters`를 호출한다.

- [ ] **Step 4: 관련 회귀 테스트 통과 확인**

Run: `pytest tests/test_database_validator.py tests/test_repair_db_text.py -v`

Expected: 전부 PASS.

### Task 3: staging 격리 저장과 DB 전체 품질 게이트

**Files:**
- Modify: `src/database/staging.py:130-1020`
- Modify: `tests/test_offline_db_rebuild.py`

**Interfaces:**
- Produces: `QualityFinding`, `ValidationReport.quality_findings`, `offline_rebuild_quarantine`, `quality_quarantine.json`
- Consumes: `RejectedOfflineQuestion`, `QuestionValidator(ExamRepository(path)).scan(limit=None)`

- [ ] **Step 1: 의심 staging 문항과 격리 상세 보존 실패 테스트 작성**

```python
def test_staging_quality_gate_blocks_persisted_ocr_corruption(valid_staging_db):
    with sqlite3.connect(valid_staging_db) as connection:
        connection.execute("UPDATE questions SET question_text = ? WHERE question_number = 1", ("깨진 0卜 문장",))
    report = validate_staging_database(valid_staging_db, (_expected(1),))
    assert report.valid is False
    assert "quality_gate_findings" in report.error_codes
    assert report.quality_findings[0].issue_codes == ("ocr_noise_text",)

def test_build_records_rejected_candidate_details_and_report(tmp_path, monkeypatch):
    # fake parser가 RejectedOfflineQuestion 한 건을 반환하도록 구성한다.
    summary = build_staging_database(root, staging_db, report_dir, inventory_contract=None)
    with sqlite3.connect(staging_db) as connection:
        row = connection.execute("SELECT reason_codes_json, stem FROM offline_rebuild_quarantine").fetchone()
    assert json.loads(row[0]) == ["suspicious_choice"]
    assert row[1] == "격리 발문"
    payload = json.loads(summary.report_paths["quarantine_json"].read_text(encoding="utf-8"))
    assert payload["parser_rejections"][0]["reason_codes"] == ["suspicious_choice"]
```

- [ ] **Step 2: 새 테스트가 현재 구현에서 실패하는지 확인**

Run: `pytest tests/test_offline_db_rebuild.py -k "quality_gate_blocks or records_rejected_candidate" -v`

Expected: `quality_findings` 또는 `offline_rebuild_quarantine`가 없어 FAIL.

- [ ] **Step 3: 격리 스키마·직렬화·최종 품질 스캔 구현**

```python
STAGING_BLOCKING_QUALITY_CODES = frozenset({
    "empty_question_text", "ocr_placeholder", "suspicious_text_artifact",
    "ocr_noise_text", "broken_unit_text", "unbalanced_delimiter",
    "invalid_session", "invalid_question_number", "invalid_correct_answer",
    "invalid_answer_state", "choice_count", "empty_choice_text",
    "invalid_choice_symbol", "missing_choice_image_file", "missing_image_path",
    "missing_image_file", "missing_required_image",
})

@dataclass(frozen=True)
class QualityFinding:
    question_id: int
    issue_codes: tuple[str, ...]
    summary: str

def _scan_staging_quality(path: Path) -> tuple[QualityFinding, ...]:
    findings = QuestionValidator(ExamRepository(str(path))).scan(limit=None)
    return tuple(
        QualityFinding(
            question_id=int(item["question_id"]),
            issue_codes=tuple(dict.fromkeys(
                issue["code"] for issue in item["issues"]
                if issue["code"] in STAGING_BLOCKING_QUALITY_CODES
            )),
            summary=str(item["summary"]),
        )
        for item in findings
        if any(issue["code"] in STAGING_BLOCKING_QUALITY_CODES for issue in item["issues"])
    )
```

`_initialize_rebuild_schema`에 `offline_rebuild_quarantine`를 만들고 일반 offline build 경로에서 `parsed.rejected`를 `_record_rejected_questions`로 저장한다. `ValidationReport.to_dict()`와 validation JSON에 `quality_findings`를 포함하고, `report_paths`에 `quarantine_json`을 추가해 parser 격리 행과 최종 스캔 결과를 기록한다.

- [ ] **Step 4: staging 품질 게이트 통합 테스트 통과 확인**

Run: `pytest tests/test_offline_db_rebuild.py -k "quality_gate or rejected_candidate or build_staging_database" -v`

Expected: 선택된 테스트 전부 PASS.

### Task 4: 전체 검증과 GitHub 전달

**Files:**
- Verify: 모든 intended source/test/docs 파일
- Exclude: `exam_bank.maritime_domain.20260705_175510.examdb.zip`

**Interfaces:**
- Consumes: Tasks 1-3의 전체 변경
- Produces: 테스트 증거가 있는 Git commit과 GitHub 원격 브랜치

- [ ] **Step 1: 변경 범위와 문서 완결성 점검**

Run: `git diff --check`

Expected: 출력 없음, exit 0.

설계 목표, 공통 규칙, 격리 저장, staging 차단, 오탐 방지, 회귀 테스트, Git 전달 항목이 각각 구현 task에 연결되어 있는지 두 문서를 다시 읽어 확인한다.

- [ ] **Step 2: 대상 테스트 실행**

Run: `pytest tests/test_offline_source_adapters.py tests/test_database_validator.py tests/test_repair_db_text.py tests/test_offline_db_rebuild.py -q`

Expected: 전부 PASS.

- [ ] **Step 3: 전체 테스트 실행**

Run: `pytest -q`

Expected: 전부 PASS.

- [ ] **Step 4: 사용자 소유 파일을 제외하고 명시적으로 stage 및 commit**

```powershell
git add docs/superpowers/specs/2026-07-15-parsing-quality-gate-design.md docs/superpowers/plans/2026-07-15-parsing-quality-gate.md src/parser/text_quality.py src/parser/offline_quality.py src/parser/formatting.py src/parser/maritime_source_repairs.json src/database/validator.py src/database/staging.py src/database/ocr_repairs.py scripts/repair_db_text.py scripts/apply_maritime_ocr_repairs.py scripts/build_maritime_source_repairs.py tests/test_offline_source_adapters.py tests/test_database_validator.py tests/test_repair_db_text.py tests/test_offline_db_rebuild.py tests/test_pdf_text_ordering.py tests/test_text_cleanup.py
git diff --cached --stat
git commit -m "feat: gate parsed questions before database promotion"
```

Expected: intended 파일만 포함된 commit 생성.

- [ ] **Step 5: GitHub 원격 브랜치에 push하고 draft PR 생성**

```powershell
git push -u origin codex/parsing-quality-gate
gh pr create --draft --base main --head codex/parsing-quality-gate --title "feat: gate parsed questions before database promotion" --body "## Summary`n- share OCR quality rules across parser and database validation`n- quarantine rejected candidates with auditable reports`n- block mounted database promotion when staging contains corrupt questions`n`n## Tests`n- pytest -q"
```

Expected: push 성공 및 `main` 대상 draft PR URL 출력.
