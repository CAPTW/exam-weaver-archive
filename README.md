# 기출문제 문제은행 관리자

## English

### Overview

**기출문제 문제은행 관리자** is a Windows-focused desktop application for
building, reviewing, practicing, and exporting structured exam-question banks.
The repository contains the application code, PDF parsing pipeline, import
utilities, tests, packaging scripts, and Codex side-panel integration.

The actual production question-bank databases are intentionally **not** included
in this repository. A new checkout can still run with an empty local SQLite
database created from the schema and seed metadata.

### What Is Included

- PyQt5 / PyQt-Fluent-Widgets desktop application.
- Maritime-license PDF parser for question sheets and answer sheets.
- COMCBT/public-exam PDF importer and quality checks.
- SQLite schema, seed metadata, repository layer, validation, and selection logic.
- Question browser, editor, explanation workflow, practice mode, DB mount tools,
  import screen, and DOCX export screen.
- DOCX exporter with support for grouped passages, images, answer keys, basic
  formatting, underline/overline spans, and math-like notation.
- Codex SDK side panel prepared for per-user login.
- Focused test suite for parser behavior, repository migrations, GUI workflow,
  export behavior, import recovery, and DB mount operations.

### What Is Not Included

- `data/` runtime folder.
- `exam_bank.db`, split domain DBs, DB backups, and snapshots.
- OCR caches, generated image extracts, logs, temporary files, build artifacts,
  virtual environments, packaged executables, and generated DOCX/PDF outputs.
- Personal Codex credentials such as `auth.json`.

These exclusions are intentional so the repository can archive and share the
core codebase without shipping the private question bank or account credentials.

### Main Architecture

```text
src/
  cli/                 Click-based command line entry points
  database/            SQLite schema, migrations, repository, selection, validation
  exporter/            DOCX exam-sheet exporter
  gui/                 PyQt desktop application and screens
  parser/              Maritime exam PDF parser
  quiz/                Mock exam generation and CLI runner
  utils/               Tag generation helpers
  web_import/          COMCBT/public web/PDF import pipeline

scripts/               Import, repair, audit, packaging, and data-prep utilities
tests/                 Unit and workflow tests
experiments/           DB mount prototype and domain split tooling
docs/                  Implementation plans and textbook/reference notes
chapter_cards/         Chapter planning cards for exam-driven materials
source_notes/          Source notes for textbook-style content
```

### PDF Parser Pipeline

The maritime-license PDF parser is centered on `src/parser`.

1. `ExamPDFParser` orchestrates a full parse from question PDF and answer PDF.
2. `PDFExtractor` reads standard PDFs or ZIP-style extracted PDFs.
3. The extractor uses PyMuPDF when available to preserve positioned reading
   order, images, tables, underline marks, and overline marks.
4. Scanned/image-heavy pages can fall back to Windows OCR for Korean text.
5. `ExamMetadataParser` detects year, session, grade, license type, domestic
   qualifiers, and vessel-specialization qualifiers from cover pages or fallback
   text.
6. `QuestionParser` splits pages into questions and choices, handles legacy
   Korean choice markers, repairs common OCR/PDF ordering artifacts, assigns
   subject order, attaches images, and captures formatting metadata.
7. `AnswerParser` reads answer sheets in multiple historical layouts, including
   grid, table, legacy text, embedded-answer, and OCR-based visual-table forms.
8. `DataMerger` maps answer keys back onto parsed questions and validates
   missing answers, duplicate numbers, and expected 1-25 subject sequences.

Related high-volume import helpers are included under `scripts/`, especially:

- `scripts/import_public_exam_pdf_folder.py`
- `scripts/import_maritime_english_pdf.py`
- `scripts/import_maritime_law_pdf.py`
- `scripts/import_police_engineering_pdf.py`
- `scripts/import_police_navigation_pdf.py`
- `scripts/extract_pdf_text.py`

### Database Model

The app uses SQLite. `src/database/schema.sql` defines exams, subjects,
exam-subject mappings, question sources, grouped passages, questions, choices,
mock exams, and results. `ExamRepository` applies migrations on startup, seeds
reference metadata, saves parsed questions, exposes search/filter APIs, updates
editor changes, and deletes question records safely.

The default source-mode writable database path is:

```text
data/exam_bank.db
```

If it does not exist, the app initializes an empty schema. Packaged builds can
also ship `data/seed_exam_bank.db` as a factory database, but that file is not
part of this archive.

### Desktop App

The main window title is:

```text
기출문제 문제은행 관리자
```

Primary screens:

- Home: overview landing screen.
- Question Management: browse, filter, validate, edit, explain, and delete.
- Practice: generate and take mock exams with grading modes.
- Exam Export: sample questions and export DOCX exam sheets.
- Import: parse question/answer PDFs into the local database.
- DB Mount: prototype UI for split/domain database management.
- Codex: embedded Codex side panel for code assistance inside the app.

### Codex Integration

Codex SDK support is included through:

- `openai-codex` in `requirements.txt`
- `openai_codex` and `codex_cli_bin` collection in `ExamGenerator.spec`
- `src/gui/interface/codex_panel.py`

Personal authentication is not included. Each user can open the app, use the
Codex panel's **로그인** button, and connect their own account. Local Codex state
is stored under:

```text
data/codex_panel_home
```

That path is ignored by Git and should remain local.

### Running Locally

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.gui.main
```

Or double-click:

```text
Run_Latest_App.bat
```

### CLI Examples

Initialize a local empty DB:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main db init --db-path .\data\exam_bank.db
```

Parse a question PDF and answer PDF:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main import .\question.pdf .\answer.pdf --exam-type 3급기관사
```

Run statistics:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main stats --db-path .\data\exam_bank.db
```

### Testing

Run the full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run parser-focused tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_parser_2025.py tests\test_text_cleanup.py tests\test_comcbt_pdf.py
```

### Packaging

Build and run the packaged app:

```text
Build_And_Run_Packaged_App.bat
```

The packaging script installs dependencies, runs PyInstaller, prepares portable
data when a source DB is supplied, and writes a portable README. Production DBs
must be supplied locally; they are not stored in this repository.

---

## 한국어

### 개요

**기출문제 문제은행 관리자**는 기출문제를 구조화된 문제은행으로 만들고,
검수하고, 풀이하고, 시험지로 출력하기 위한 Windows 중심 데스크톱
애플리케이션입니다. 이 저장소에는 앱 코드, PDF 파서, import 유틸리티,
테스트, 패키징 스크립트, Codex 사이드 패널 연동 코드가 포함되어 있습니다.

실제 운영 문제은행 데이터베이스는 의도적으로 **포함하지 않았습니다**. 새로
clone한 사용자는 빈 SQLite DB를 생성해 앱 구조와 기능을 실행해 볼 수 있고,
운영 DB는 별도로 로컬에 배치해야 합니다.

### 포함된 것

- PyQt5 / PyQt-Fluent-Widgets 기반 데스크톱 앱.
- 시험 문제지/정답지 PDF 파서.
- COMCBT 및 공개 기출 PDF import/품질검사 파이프라인.
- SQLite schema, seed metadata, repository, selection, validation 계층.
- 문제 조회, 수정, 해설 작성, 풀이 모드, DB mount, PDF import, DOCX 출력 UI.
- 공통 지문, 이미지, 정답표, 기본 서식, 밑줄/윗줄, 수식형 표기를 처리하는
  DOCX exporter.
- 사용자별 로그인으로 동작하도록 준비된 Codex SDK 사이드 패널.
- parser, repository migration, GUI workflow, export, import recovery,
  DB mount 기능을 검증하는 테스트.

### 포함하지 않은 것

- `data/` 런타임 폴더.
- `exam_bank.db`, domain split DB, DB backup, snapshot.
- OCR cache, 추출 이미지, logs, tmp, build/dist 산출물, `.venv`, exe, 생성된
  DOCX/PDF.
- `auth.json` 같은 개인 Codex 인증 파일.

즉, 이 저장소는 실제 문제은행 DB와 개인 계정 인증을 제외한 핵심 codebase
archive입니다.

### 주요 구조

```text
src/
  cli/                 Click 기반 CLI
  database/            SQLite schema, migration, repository, selection, validation
  exporter/            DOCX 시험지 exporter
  gui/                 PyQt 데스크톱 앱과 화면들
  parser/              PDF parser
  quiz/                모의고사 생성 및 CLI 풀이
  utils/               태그 생성 helper
  web_import/          COMCBT/public web/PDF import

scripts/               import, repair, audit, packaging, data-prep 유틸리티
tests/                 단위/워크플로 테스트
experiments/           DB mount prototype, domain split 도구
docs/                  구현 계획과 참고 문서
chapter_cards/         시험 중심 교재/챕터 카드
source_notes/          출처 노트
```

### PDF Parser 흐름

PDF parser의 핵심은 `src/parser`입니다.

1. `ExamPDFParser`가 문제 PDF와 정답 PDF의 전체 parsing을 조율합니다.
2. `PDFExtractor`가 일반 PDF 또는 ZIP 형태의 추출 PDF를 읽습니다.
3. 가능하면 PyMuPDF를 사용해 좌표 기반 읽기 순서, 이미지, 표, 밑줄, 윗줄을
   보존합니다.
4. 스캔본/이미지 기반 페이지는 Windows OCR로 한글 텍스트를 복원합니다.
5. `ExamMetadataParser`가 표지 또는 fallback 텍스트에서 연도, 회차, 급수,
   자격 종류, 국내/상선/어선 구분을 추출합니다.
6. `QuestionParser`가 문제와 선지를 분리하고, 오래된 한글 선지 기호와
   OCR/PDF 순서 깨짐을 보정하며, 과목 순서와 이미지/서식 정보를 붙입니다.
7. `AnswerParser`가 여러 연도별 정답지 레이아웃을 처리합니다. grid, table,
   legacy text, embedded-answer, OCR 기반 정답표를 모두 고려합니다.
8. `DataMerger`가 문제와 정답을 결합하고, 정답 누락, 번호 중복, 과목별
   1-25번 연속성 등을 검증합니다.

관련 대량 import script:

- `scripts/import_public_exam_pdf_folder.py`
- `scripts/import_maritime_english_pdf.py`
- `scripts/import_maritime_law_pdf.py`
- `scripts/import_police_engineering_pdf.py`
- `scripts/import_police_navigation_pdf.py`
- `scripts/extract_pdf_text.py`

### 데이터베이스

앱은 SQLite를 사용합니다. `src/database/schema.sql`에는 시험, 과목, 시험-과목
관계, 문제 출처, 공통 지문/그룹, 문제, 선지, 모의고사, 풀이 결과 테이블이
정의되어 있습니다. `ExamRepository`는 앱 시작 시 schema/migration을 적용하고,
reference metadata를 seed하며, parsing된 문제 저장, 검색/필터, 수정, 삭제
기능을 제공합니다.

기본 source 실행 DB 경로:

```text
data/exam_bank.db
```

파일이 없으면 빈 schema로 초기화됩니다. packaged build에서는
`data/seed_exam_bank.db`를 factory DB로 사용할 수 있지만, 이 archive에는 실제
DB가 포함되어 있지 않습니다.

### 데스크톱 앱

현재 앱 창 제목:

```text
기출문제 문제은행 관리자
```

주요 화면:

- 홈: 앱 시작 화면.
- 문제 관리: 문제 검색, 필터링, 검증, 수정, 해설 작성, 삭제.
- 문제 풀이: 조건별 문제 선택과 모의고사 풀이.
- 시험지 출력: 조건별 문제 샘플링 후 DOCX 생성.
- 문제 가져오기: 문제 PDF/정답 PDF parsing 후 DB 저장.
- DB Mount: domain DB 분리/이동 prototype UI.
- Codex: 앱 내부에서 사용할 수 있는 Codex 사이드 패널.

### Codex 연동

Codex SDK 연결은 다음 파일에 준비되어 있습니다.

- `requirements.txt`의 `openai-codex`
- `ExamGenerator.spec`의 `openai_codex`, `codex_cli_bin` 번들 설정
- `src/gui/interface/codex_panel.py`

개인 인증은 저장소에 포함하지 않습니다. 사용자는 앱의 Codex 패널에서
**로그인** 버튼을 눌러 자기 계정으로 연결하면 됩니다. 로컬 Codex 상태는 아래
경로에 저장됩니다.

```text
data/codex_panel_home
```

이 경로는 Git에 포함하지 않는 로컬 런타임 데이터입니다.

### 로컬 실행

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m src.gui.main
```

또는 더블클릭:

```text
Run_Latest_App.bat
```

### CLI 예시

빈 로컬 DB 초기화:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main db init --db-path .\data\exam_bank.db
```

문제 PDF와 정답 PDF parsing:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main import .\question.pdf .\answer.pdf --exam-type 3급기관사
```

통계 확인:

```powershell
.\.venv\Scripts\python.exe -m src.cli.main stats --db-path .\data\exam_bank.db
```

### 테스트

전체 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

parser 중심 테스트:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_parser_2025.py tests\test_text_cleanup.py tests\test_comcbt_pdf.py
```

### 패키징

패키징 후 실행:

```text
Build_And_Run_Packaged_App.bat
```

패키징 스크립트는 dependency 설치, PyInstaller build, portable data 준비,
portable README 생성을 수행합니다. 운영 DB는 로컬에서 별도로 공급해야 하며
이 저장소에는 저장하지 않습니다.
