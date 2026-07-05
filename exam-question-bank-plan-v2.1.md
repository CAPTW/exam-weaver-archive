# 📚 시험 문제은행 시스템 v2.1
## 개발 계획서 (Local Database + PDF 파싱 로직 반영)

---

## 📋 프로젝트 개요

### 변경 사항 (v2.0 → v2.1)
| 항목 | v2.0 | v2.1 |
|------|------|------|
| **PDF 파싱** | LLM 의존 | 규칙 기반 파싱 (90%+) |
| **PDF 구조** | 미정의 | ZIP 아카이브 형식 분석 완료 |
| **웹 배포** | FastAPI + Vercel | **제거** (로컬 전용) |
| **개발 도구** | Claude Code/Codex | Claude Code/Codex (최적화) |
| **LLM 의존성** | 필수 | 선택적 (Edge Case만) |

### 핵심 설계 원칙
```
┌─────────────────────────────────────────────────────────────────┐
│  1. 로컬 우선 (Local First)                                      │
│     - SQLite 로컬 데이터베이스                                   │
│     - 웹 서버 없이 CLI로 완전한 기능 제공                         │
│                                                                  │
│  2. 규칙 기반 파싱 (Rule-Based Parsing)                          │
│     - 해기사 시험 PDF의 표준화된 형식 활용                        │
│     - 정규식 기반으로 90%+ 자동 파싱                             │
│     - LLM은 Edge Case 처리에만 선택적 사용                       │
│                                                                  │
│  3. Claude Code/Codex 최적화                                     │
│     - 모듈화된 코드 구조                                         │
│     - 명확한 인터페이스 정의                                      │
│     - 상세한 타입 힌트 및 문서화                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 핵심 개념: 시험-과목 계층 구조
```
┌─────────────────────────────────────────────────────────────────┐
│                      시험 (Exam)                                 │
│  예: "3급 기관사", "3급 항해사", "소형선박조종사"                 │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ 1:N 관계
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      과목 (Subject)                              │
│  예: "기관1", "기관2", "기관3", "직무일반", "영어"               │
└─────────────────────────────────────────────────────────────────┘
                            │
                            │ 1:N 관계
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      문제 (Question)                             │
│  각 과목에 속한 개별 기출문제 (25문제/과목)                       │
└─────────────────────────────────────────────────────────────────┘
```

### 기술 스택
| 구분 | 기술 |
|------|------|
| **언어** | Python 3.11+ |
| **Database** | SQLite 3 (로컬) |
| **PDF 처리** | zipfile, json (내장) |
| **정규식** | re (내장) |
| **CLI** | Click 또는 Typer |
| **테스트** | pytest |
| **개발 도구** | Claude Code, Codex |

---

# 📄 Phase 0: PDF 구조 분석 결과
**상태: ✅ 완료**

## Step 0.1: PDF 파일 형식

### 발견 사항
업로드된 해기사 시험 PDF는 **ZIP 아카이브** 형식으로, 내부에 다음 파일들이 포함:

```
exam_pdf/
├── 1.jpeg          # 페이지 1 이미지
├── 1.txt           # 페이지 1 OCR 텍스트
├── 2.jpeg
├── 2.txt
├── ...
├── 39.jpeg
├── 39.txt
└── manifest.json   # 페이지 메타데이터
```

### manifest.json 구조
```json
{
  "num_pages": 39,
  "pages": [
    {
      "page_number": 1,
      "image": {"path": "1.jpeg", "dimensions": {"width": 924, "height": 1316}},
      "text": {"path": "1.txt"},
      "has_visual_content": true
    }
  ]
}
```

## Step 0.2: 시험문제 PDF 구조

### 페이지 유형
| 유형 | 식별 패턴 | 예시 |
|-----|----------|------|
| **표지** | `해기사 시험`, `문 제 지` 포함 | "2022 1 해기사 시험 년 정기 제 회" |
| **문제 페이지** | `- {숫자} -` 로 시작 | "- 1 -" |
| **빈 페이지** | 텍스트 없음 또는 최소 | - |

### 문제 형식
```
{문제번호}. {문제 텍스트}
㉮ {선지1}
㉯ {선지2}
㉴ {선지3}
㉵ {선지4}
```

### 선지 기호 체계
| 선지 기호 | 정답 표기 | 번호 값 |
|----------|----------|--------|
| ㉮ | 가 | 1 |
| ㉯ | 나 | 2 |
| ㉴ | 사 | 3 |
| ㉵ | 아 | 4 |

### 과목 전환 패턴
- 문제 번호가 **1번으로 리셋**되면 새 과목 시작
- 각 과목당 **25문제** 고정
- 3급 기관사 과목 순서: `기관1 → 기관2 → 기관3 → 직무일반 → 영어`

### 회차별 페이지 구성 (2022년 3급 기관사)
| 회차 | 표지 페이지 | 문제 페이지 |
|-----|-----------|-----------|
| 1회 | 1 | 2-10 |
| 2회 | 11 | 12-19 |
| 3회 | 20 | 21-29 |
| 4회 | 30 | 31-39 |

## Step 0.3: 정답지 PDF 구조

### 정답 형식 (일반)
```
< 5급 기관사 > 답안
◎ 2022년 제 1회 정기시험 1 2 3 4
56789 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25
기관1 사
가사아나가가나사가나아가가아나아아가나가나사사가
```

### 정답 형식 (국내한정)
```
< 5급 기관사 (국내한정) > 답안
◎ 2022년 제 1회 정기시험
1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25
기관1 사 사 나 사 사 사 나 사 아 나 가 아 아 아 사 나 아 아 나 아 나 나 아 나 가
```

### 급수 코드 매핑 (정답지 → 실제)
| 정답지 표기 | 실제 시험 |
|-----------|----------|
| 5급 기관사 | 3급 기관사 |
| 5급 기관사 (국내한정) | 3급 기관사 (국내한정) |

---

# 🗄️ Phase 1: 데이터베이스 스키마 설계
**예상 기간: 3일**

## Step 1.1: ERD (Entity Relationship Diagram)
```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│    exams     │     │  exam_subjects   │     │   subjects   │
├──────────────┤     ├──────────────────┤     ├──────────────┤
│ id (PK)      │──┐  │ exam_id (FK)     │  ┌──│ id (PK)      │
│ code         │  └─>│ subject_id (FK)  │<─┘  │ code         │
│ name         │     │ display_order    │     │ name_ko      │
│ is_domestic  │     │ questions_count  │     │ name_en      │
│ created_at   │     └──────────────────┘     │ created_at   │
└──────────────┘                              └──────────────┘
                                                     │
                                                     │ 1:N
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│                         questions                             │
├──────────────────────────────────────────────────────────────┤
│ id (PK)           │ exam_subject_id (FK) │ year              │
│ session           │ question_number      │ question_text     │
│ correct_answer    │ has_image            │ image_path        │
│ source_page       │ created_at           │                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                     question_choices                          │
├──────────────────────────────────────────────────────────────┤
│ id (PK)           │ question_id (FK)     │ choice_number     │
│ choice_symbol     │ choice_text          │                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      mock_exams (모의고사)                    │
├──────────────────────────────────────────────────────────────┤
│ id (PK)           │ exam_id (FK)         │ name              │
│ created_at        │                      │                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      exam_results (시험 결과)                 │
├──────────────────────────────────────────────────────────────┤
│ id (PK)           │ mock_exam_id (FK)    │ exam_subject_id   │
│ total_questions   │ correct_count        │ score             │
│ time_spent        │ completed_at         │                   │
└──────────────────────────────────────────────────────────────┘
```

## Step 1.2: DDL 스크립트

```sql
-- database/schema.sql

-- ============ 시험 테이블 ============
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,           -- '3급기관사', '3급기관사(국내)' 등
    name TEXT NOT NULL,                  -- '3급 기관사'
    is_domestic_only BOOLEAN DEFAULT 0,  -- 국내한정 여부
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 과목 테이블 ============
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,           -- 'engine1', 'engine2', 'general', 'english'
    name_ko TEXT NOT NULL,               -- '기관1', '기관2', '직무일반', '영어'
    name_en TEXT,                        -- 'Engine 1', 'Engine 2'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 시험-과목 관계 테이블 ============
CREATE TABLE IF NOT EXISTS exam_subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL REFERENCES exams(id),
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    display_order INTEGER NOT NULL,      -- 과목 표시 순서
    questions_count INTEGER DEFAULT 25,  -- 과목당 문제 수
    UNIQUE(exam_id, subject_id)
);

-- ============ 문제 테이블 ============
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_subject_id INTEGER NOT NULL REFERENCES exam_subjects(id),
    year INTEGER NOT NULL,               -- 2022
    session INTEGER NOT NULL,            -- 1, 2, 3, 4 (회차)
    question_number INTEGER NOT NULL,    -- 1-25
    question_text TEXT NOT NULL,         -- 문제 본문
    has_image BOOLEAN DEFAULT 0,         -- 이미지 포함 여부
    image_path TEXT,                     -- 이미지 경로
    correct_answer INTEGER NOT NULL,     -- 1, 2, 3, 4
    source_page INTEGER,                 -- 원본 PDF 페이지
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_subject_id, year, session, question_number)
);

-- ============ 선지 테이블 ============
CREATE TABLE IF NOT EXISTS question_choices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    choice_number INTEGER NOT NULL,      -- 1, 2, 3, 4
    choice_symbol TEXT NOT NULL,         -- '㉮', '㉯', '㉴', '㉵'
    choice_text TEXT NOT NULL,           -- 선지 텍스트
    UNIQUE(question_id, choice_number)
);

-- ============ 모의고사 테이블 ============
CREATE TABLE IF NOT EXISTS mock_exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id INTEGER NOT NULL REFERENCES exams(id),
    name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 모의고사 문제 테이블 ============
CREATE TABLE IF NOT EXISTS mock_exam_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mock_exam_id INTEGER NOT NULL REFERENCES mock_exams(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    display_order INTEGER NOT NULL
);

-- ============ 시험 결과 테이블 ============
CREATE TABLE IF NOT EXISTS exam_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mock_exam_id INTEGER REFERENCES mock_exams(id),
    exam_subject_id INTEGER REFERENCES exam_subjects(id),
    total_questions INTEGER NOT NULL,
    correct_count INTEGER NOT NULL,
    score REAL NOT NULL,
    time_spent_seconds INTEGER,
    completed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============ 인덱스 ============
CREATE INDEX IF NOT EXISTS idx_questions_exam_subject ON questions(exam_subject_id);
CREATE INDEX IF NOT EXISTS idx_questions_year_session ON questions(year, session);
CREATE INDEX IF NOT EXISTS idx_choices_question ON question_choices(question_id);
```

## Step 1.3: 초기 데이터

```sql
-- database/seed.sql

-- 과목 데이터
INSERT INTO subjects (code, name_ko, name_en) VALUES
    ('engine1', '기관1', 'Engine 1'),
    ('engine2', '기관2', 'Engine 2'),
    ('engine3', '기관3', 'Engine 3'),
    ('general', '직무일반', 'General Duties'),
    ('english', '영어', 'English'),
    ('navigation', '항해', 'Navigation'),
    ('operation', '운용', 'Operation'),
    ('regulation', '법규', 'Regulations'),
    ('merchant', '상선전문', 'Merchant Marine');

-- 시험 데이터
INSERT INTO exams (code, name, is_domestic_only) VALUES
    ('3급기관사', '3급 기관사', 0),
    ('3급기관사(국내)', '3급 기관사 (국내한정)', 1),
    ('3급항해사(상선)', '3급 항해사 (상선)', 0);

-- 시험-과목 관계 (3급 기관사)
INSERT INTO exam_subjects (exam_id, subject_id, display_order) VALUES
    (1, 1, 1),  -- 기관1
    (1, 2, 2),  -- 기관2
    (1, 3, 3),  -- 기관3
    (1, 4, 4),  -- 직무일반
    (1, 5, 5);  -- 영어

-- 시험-과목 관계 (3급 기관사 국내한정)
INSERT INTO exam_subjects (exam_id, subject_id, display_order) VALUES
    (2, 1, 1),  -- 기관1
    (2, 2, 2),  -- 기관2
    (2, 3, 3),  -- 기관3
    (2, 4, 4);  -- 직무일반 (영어 없음)
```

---

# 🔍 Phase 2: PDF 파싱 엔진 개발
**예상 기간: 1주**

## Step 2.1: 파싱 파이프라인 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                     PDF 파싱 파이프라인                           │
├─────────────────────────────────────────────────────────────────┤
│  1. PDF 압축 해제 (PDFExtractor)                                 │
│     └─ ZIP 형식의 PDF에서 텍스트 파일 추출                        │
│                                                                  │
│  2. 메타데이터 추출 (ExamMetadataParser)                          │
│     ├─ 표지에서 시험 정보 추출 (연도, 회차, 시험종류)              │
│     └─ manifest.json에서 페이지 정보 로드                         │
│                                                                  │
│  3. 문제 파싱 (QuestionParser)                                   │
│     ├─ 문제 번호 패턴 인식                                        │
│     ├─ 선지 (㉮㉯㉴㉵) 추출                                       │
│     └─ 과목 전환점 (1번 리셋) 감지                                │
│                                                                  │
│  4. 정답 파싱 (AnswerParser)                                     │
│     ├─ 정답지 헤더에서 시험 정보 매칭                             │
│     └─ 과목별 정답 문자열 파싱 (가/나/사/아 → 1/2/3/4)            │
│                                                                  │
│  5. 데이터 병합 및 저장 (DataMerger)                              │
│     ├─ 문제-정답 매칭                                            │
│     └─ SQLite 데이터베이스 저장                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Step 2.2: 정규식 패턴 정의

```python
# src/parser/patterns.py
"""PDF 파싱을 위한 정규식 패턴 정의"""

import re

# ============ 문제 관련 패턴 ============

# 문제 시작 패턴: "1. ", "25. " 등
QUESTION_START = re.compile(r'^(\d{1,2})\.\s+')

# 선지 추출 패턴
CHOICE_PATTERN = re.compile(
    r'(㉮|㉯|㉴|㉵)\s*([^㉮㉯㉴㉵]+?)(?=\s*(?:㉮|㉯|㉴|㉵|\d+\.|$))',
    re.DOTALL
)

# 페이지 번호 패턴: "- 1 -", "- 25 -" 등
PAGE_NUMBER = re.compile(r'^-\s*(\d+)\s*-')

# ============ 표지 관련 패턴 ============

# 표지 정보 추출: 연도, 회차
COVER_INFO = re.compile(
    r'(\d{4})\s*(\d)\s*해기사\s*시험.*?년\s*정기\s*제\s*회',
    re.DOTALL
)

# 시험 종류 추출
EXAM_TYPE = re.compile(r'(\d급\s*\w+사)')

# 표지 식별 키워드
COVER_INDICATORS = ['해기사 시험', '문 제 지', '기출', '응시자를 위해']

# ============ 정답지 관련 패턴 ============

# 정답지 헤더: "< 5급 기관사 > 답안"
ANSWER_HEADER = re.compile(
    r'<\s*(\d)\s*급?\s*(\w+)\s*(?:\(([^)]+)\))?\s*>\s*답안'
)

# 정답지 회차: "◎ 2022년 제 1회 정기시험"
ANSWER_SESSION = re.compile(
    r'◎\s*(\d{4})\s*년?\s*제?\s*(\d)\s*회?\s*정기시험'
)

# 과목별 정답 (일반 형식)
SUBJECT_ANSWER_COMPACT = re.compile(
    r'^(기관\d|직무일반|영어|항해|운용|법규|상선전문)\s*([가나사아])\s*\n([가나사아\s]+)',
    re.MULTILINE
)

# 과목별 정답 (국내한정 형식 - 공백 구분)
SUBJECT_ANSWER_SPACED = re.compile(
    r'^(기관\d|직무일반|영어|항해|운용|법규)\s+((?:[가나사아]\s*){25})',
    re.MULTILINE
)

# ============ 매핑 테이블 ============

# 선지 기호 → 번호
CHOICE_SYMBOL_TO_NUMBER = {
    '㉮': 1,
    '㉯': 2,
    '㉴': 3,
    '㉵': 4
}

# 정답 문자 → 번호
ANSWER_CHAR_TO_NUMBER = {
    '가': 1,
    '나': 2,
    '사': 3,
    '아': 4
}

# 번호 → 선지 기호
NUMBER_TO_CHOICE_SYMBOL = {v: k for k, v in CHOICE_SYMBOL_TO_NUMBER.items()}

# 과목 이름 → 코드
SUBJECT_NAME_TO_CODE = {
    '기관1': 'engine1',
    '기관2': 'engine2',
    '기관3': 'engine3',
    '직무일반': 'general',
    '영어': 'english',
    '항해': 'navigation',
    '운용': 'operation',
    '법규': 'regulation',
    '상선전문': 'merchant'
}

# 시험별 과목 순서
EXAM_SUBJECT_ORDER = {
    '3급기관사': ['기관1', '기관2', '기관3', '직무일반', '영어'],
    '3급기관사(국내)': ['기관1', '기관2', '기관3', '직무일반'],
    '3급항해사(상선)': ['항해', '운용', '법규', '영어', '상선전문'],
}
```

## Step 2.3: 핵심 파싱 모듈

### PDFExtractor (PDF 압축 해제)

```python
# src/parser/extractor.py
"""PDF(ZIP) 파일에서 텍스트 추출"""

import zipfile
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class PageData:
    """페이지 데이터"""
    number: int
    text: str
    image_path: Optional[str] = None
    has_visual_content: bool = False


@dataclass
class PDFContent:
    """추출된 PDF 컨텐츠"""
    pages: List[PageData]
    manifest: Dict
    source_path: str


class PDFExtractor:
    """PDF(ZIP) 파일에서 텍스트 추출"""
    
    def __init__(self, output_dir: str = './extracted'):
        self.output_dir = Path(output_dir)
    
    def extract(self, pdf_path: str) -> PDFContent:
        """
        PDF 압축 해제 및 텍스트 로드
        
        Args:
            pdf_path: PDF 파일 경로
            
        Returns:
            PDFContent: 추출된 컨텐츠
        """
        pdf_path = Path(pdf_path)
        extract_dir = self.output_dir / pdf_path.stem
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # ZIP 압축 해제
        with zipfile.ZipFile(pdf_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # manifest.json 로드
        manifest_path = extract_dir / 'manifest.json'
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        
        # 페이지별 텍스트 로드
        pages = []
        for page_info in manifest['pages']:
            page_num = page_info['page_number']
            text_path = extract_dir / page_info['text']['path']
            
            text = ''
            if text_path.exists():
                with open(text_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            
            pages.append(PageData(
                number=page_num,
                text=text,
                image_path=str(extract_dir / page_info['image']['path']),
                has_visual_content=page_info.get('has_visual_content', False)
            ))
        
        return PDFContent(
            pages=pages,
            manifest=manifest,
            source_path=str(pdf_path)
        )
    
    def cleanup(self, pdf_path: str):
        """추출된 파일 정리"""
        import shutil
        extract_dir = self.output_dir / Path(pdf_path).stem
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
```

### ExamMetadataParser (시험 메타데이터 파싱)

```python
# src/parser/metadata.py
"""표지에서 시험 정보 추출"""

from typing import Optional, Dict
from dataclasses import dataclass
from .patterns import COVER_INFO, EXAM_TYPE, COVER_INDICATORS


@dataclass
class ExamMetadata:
    """시험 메타데이터"""
    year: int
    session: int
    exam_type: str
    is_domestic: bool = False


class ExamMetadataParser:
    """표지에서 시험 정보 추출"""
    
    def is_cover_page(self, text: str) -> bool:
        """표지 페이지 판별"""
        return any(ind in text for ind in COVER_INDICATORS)
    
    def parse_cover(self, text: str) -> Optional[ExamMetadata]:
        """
        표지 텍스트에서 메타데이터 추출
        
        Args:
            text: 표지 페이지 텍스트
            
        Returns:
            ExamMetadata 또는 None
        """
        if not self.is_cover_page(text):
            return None
        
        # 연도, 회차 추출
        year, session = None, None
        
        # 패턴 1: "2022 1 해기사 시험 년 정기 제 회"
        import re
        match = re.search(r'(\d{4})\s*(\d)\s*해기사', text)
        if match:
            year = int(match.group(1))
            session = int(match.group(2))
        
        # 시험 종류 추출
        exam_type = None
        type_match = EXAM_TYPE.search(text)
        if type_match:
            exam_type = type_match.group(1).replace(' ', '')
        
        # 국내한정 여부
        is_domestic = '국내한정' in text or '국내' in text
        
        if year and session and exam_type:
            return ExamMetadata(
                year=year,
                session=session,
                exam_type=exam_type,
                is_domestic=is_domestic
            )
        
        return None
```

### QuestionParser (문제 파싱)

```python
# src/parser/question.py
"""문제 텍스트 파싱"""

import re
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from .patterns import (
    QUESTION_START, CHOICE_PATTERN, PAGE_NUMBER,
    CHOICE_SYMBOL_TO_NUMBER, EXAM_SUBJECT_ORDER
)


@dataclass
class Choice:
    """선지"""
    number: int
    symbol: str
    text: str


@dataclass
class Question:
    """문제"""
    number: int
    text: str
    choices: List[Choice] = field(default_factory=list)
    correct_answer: Optional[int] = None
    has_image: bool = False
    source_page: Optional[int] = None
    subject_name: Optional[str] = None


class QuestionParser:
    """문제 텍스트 파싱"""
    
    def __init__(self, exam_type: str):
        self.exam_type = exam_type
        self.subject_order = EXAM_SUBJECT_ORDER.get(exam_type, [])
    
    def parse_questions(self, pages: List) -> List[Question]:
        """
        페이지들에서 문제 추출
        
        Args:
            pages: PageData 리스트
            
        Returns:
            Question 리스트
        """
        questions = []
        current_subject_idx = 0
        prev_question_num = 0
        
        for page in pages:
            # 표지 페이지 건너뛰기
            if self._is_cover_page(page.text):
                continue
            
            # 페이지에서 문제 추출
            page_questions = self._parse_page(page.text, page.number)
            
            for q in page_questions:
                # 과목 전환 감지 (1번 리셋)
                if prev_question_num >= 20 and q.number == 1:
                    current_subject_idx += 1
                
                # 과목 이름 할당
                if current_subject_idx < len(self.subject_order):
                    q.subject_name = self.subject_order[current_subject_idx]
                
                questions.append(q)
                prev_question_num = q.number
        
        return questions
    
    def _is_cover_page(self, text: str) -> bool:
        """표지 페이지 판별"""
        indicators = ['해기사 시험', '문 제 지', '기출']
        return any(ind in text for ind in indicators)
    
    def _parse_page(self, text: str, page_num: int) -> List[Question]:
        """단일 페이지에서 문제 추출"""
        questions = []
        
        # 페이지 번호 제거
        text = PAGE_NUMBER.sub('', text)
        
        # 문제 분리
        parts = QUESTION_START.split(text)
        
        i = 1
        while i < len(parts):
            try:
                q_num = int(parts[i])
                q_text_raw = parts[i + 1] if i + 1 < len(parts) else ''
                
                # 선지 추출
                choices = self._extract_choices(q_text_raw)
                
                # 문제 텍스트 정리 (선지 제거)
                q_text = self._clean_question_text(q_text_raw)
                
                # 이미지 포함 여부 (선지 4개 미만이면 이미지 가능성)
                has_image = len(choices) < 4
                
                questions.append(Question(
                    number=q_num,
                    text=q_text.strip(),
                    choices=choices,
                    has_image=has_image,
                    source_page=page_num
                ))
                
                i += 2
            except (ValueError, IndexError):
                i += 1
        
        return questions
    
    def _extract_choices(self, text: str) -> List[Choice]:
        """선지 추출"""
        choices = []
        matches = CHOICE_PATTERN.findall(text)
        
        for symbol, choice_text in matches:
            number = CHOICE_SYMBOL_TO_NUMBER.get(symbol)
            if number:
                choices.append(Choice(
                    number=number,
                    symbol=symbol,
                    text=choice_text.strip()
                ))
        
        return sorted(choices, key=lambda c: c.number)
    
    def _clean_question_text(self, text: str) -> str:
        """문제 텍스트에서 선지 제거"""
        # 첫 번째 선지 기호 전까지만 추출
        for symbol in ['㉮', '㉯', '㉴', '㉵']:
            if symbol in text:
                text = text.split(symbol)[0]
                break
        return text.strip()
```

### AnswerParser (정답 파싱)

```python
# src/parser/answer.py
"""정답지 파싱"""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from .patterns import (
    ANSWER_HEADER, ANSWER_SESSION,
    ANSWER_CHAR_TO_NUMBER, SUBJECT_NAME_TO_CODE
)


@dataclass
class AnswerKey:
    """정답 키"""
    year: int
    session: int
    subject_name: str
    answers: List[int]  # 25개 정답 (1-4)


class AnswerParser:
    """정답지 파싱"""
    
    def parse_answers(self, pages: List) -> Dict[Tuple[int, int, str], List[int]]:
        """
        정답지에서 정답 추출
        
        Args:
            pages: PageData 리스트
            
        Returns:
            {(연도, 회차, 과목명): [정답 리스트]} 딕셔너리
        """
        answers = {}
        current_year = None
        current_session = None
        
        for page in pages:
            text = page.text
            
            # 회차 정보 추출
            session_match = ANSWER_SESSION.search(text)
            if session_match:
                current_year = int(session_match.group(1))
                current_session = int(session_match.group(2))
            
            if not current_year or not current_session:
                continue
            
            # 과목별 정답 추출
            subject_answers = self._extract_subject_answers(text)
            
            for subject_name, answer_list in subject_answers.items():
                key = (current_year, current_session, subject_name)
                answers[key] = answer_list
        
        return answers
    
    def _extract_subject_answers(self, text: str) -> Dict[str, List[int]]:
        """과목별 정답 추출"""
        results = {}
        
        # 과목명 패턴
        subject_names = ['기관1', '기관2', '기관3', '직무일반', '영어',
                        '항해', '운용', '법규', '상선전문']
        
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            for subject in subject_names:
                if line.strip().startswith(subject):
                    # 정답 문자열 추출
                    answer_str = self._extract_answer_string(line, lines, i, subject)
                    if answer_str:
                        answers = self._parse_answer_string(answer_str)
                        if len(answers) == 25:
                            results[subject] = answers
                    break
        
        return results
    
    def _extract_answer_string(self, line: str, lines: List[str], 
                               idx: int, subject: str) -> str:
        """정답 문자열 추출"""
        # 같은 줄에서 추출 시도
        after_subject = line.split(subject, 1)[1] if subject in line else ''
        
        # 공백으로 구분된 형식: "기관1 사 사 나 사 ..."
        spaced = re.findall(r'[가나사아]', after_subject)
        if len(spaced) >= 25:
            return ''.join(spaced[:25])
        
        # 압축 형식: 첫 번째 정답 + 다음 줄
        first_answer = re.search(r'[가나사아]', after_subject)
        if first_answer and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            remaining = re.findall(r'[가나사아]', next_line)
            if len(remaining) >= 24:
                return first_answer.group() + ''.join(remaining[:24])
        
        return ''
    
    def _parse_answer_string(self, answer_str: str) -> List[int]:
        """정답 문자열 → 번호 리스트"""
        return [
            ANSWER_CHAR_TO_NUMBER[char]
            for char in answer_str
            if char in ANSWER_CHAR_TO_NUMBER
        ]
```

### DataMerger (데이터 병합)

```python
# src/parser/merger.py
"""문제와 정답 병합 및 데이터베이스 저장"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

from .question import Question
from .metadata import ExamMetadata

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """검증 결과"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]


class DataMerger:
    """문제와 정답 병합"""
    
    def merge(self, 
              questions: List[Question], 
              answers: Dict[Tuple[int, int, str], List[int]],
              metadata: ExamMetadata) -> List[Question]:
        """
        문제에 정답 매칭
        
        Args:
            questions: 문제 리스트
            answers: {(연도, 회차, 과목명): [정답 리스트]} 딕셔너리
            metadata: 시험 메타데이터
            
        Returns:
            정답이 매칭된 문제 리스트
        """
        merged = []
        
        for q in questions:
            key = (metadata.year, metadata.session, q.subject_name)
            
            if key in answers:
                answer_list = answers[key]
                if 1 <= q.number <= len(answer_list):
                    q.correct_answer = answer_list[q.number - 1]
                else:
                    logger.warning(
                        f"정답 범위 초과: {key}, 문제 {q.number}"
                    )
            else:
                logger.warning(f"정답 키 없음: {key}")
            
            merged.append(q)
        
        return merged
    
    def validate(self, questions: List[Question]) -> ValidationResult:
        """
        데이터 검증
        
        검증 항목:
        - 정답 누락 확인
        - 선지 개수 확인 (4개)
        - 문제 번호 연속성
        """
        errors = []
        warnings = []
        
        subject_questions = {}
        for q in questions:
            if q.subject_name not in subject_questions:
                subject_questions[q.subject_name] = []
            subject_questions[q.subject_name].append(q)
        
        for subject, qs in subject_questions.items():
            # 정답 누락 확인
            missing_answers = [q for q in qs if q.correct_answer is None]
            if missing_answers:
                errors.append(
                    f"{subject}: {len(missing_answers)}개 문제 정답 누락"
                )
            
            # 선지 개수 확인
            for q in qs:
                if len(q.choices) < 4 and not q.has_image:
                    warnings.append(
                        f"{subject} {q.number}번: 선지 {len(q.choices)}개"
                    )
            
            # 문제 번호 연속성
            numbers = sorted([q.number for q in qs])
            expected = list(range(1, 26))
            if numbers != expected:
                missing = set(expected) - set(numbers)
                if missing:
                    errors.append(
                        f"{subject}: 문제 번호 누락 {missing}"
                    )
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
```

## Step 2.4: 메인 파서 클래스

```python
# src/parser/main.py
"""메인 PDF 파서"""

import logging
from pathlib import Path
from typing import Optional

from .extractor import PDFExtractor
from .metadata import ExamMetadataParser
from .question import QuestionParser
from .answer import AnswerParser
from .merger import DataMerger

logger = logging.getLogger(__name__)


class ExamPDFParser:
    """해기사 시험 PDF 파서"""
    
    def __init__(self, work_dir: str = './data/extracted'):
        self.extractor = PDFExtractor(work_dir)
        self.metadata_parser = ExamMetadataParser()
        self.answer_parser = AnswerParser()
        self.merger = DataMerger()
    
    def parse(self, 
              question_pdf: str, 
              answer_pdf: str,
              exam_type: Optional[str] = None) -> dict:
        """
        시험문제 PDF와 정답지 PDF 파싱
        
        Args:
            question_pdf: 시험문제 PDF 경로
            answer_pdf: 정답지 PDF 경로
            exam_type: 시험 종류 (자동 감지 시 None)
            
        Returns:
            {
                'metadata': ExamMetadata,
                'questions': List[Question],
                'validation': ValidationResult,
                'stats': dict
            }
        """
        logger.info(f"파싱 시작: {question_pdf}")
        
        # 1. PDF 압축 해제
        logger.info("[1/5] PDF 압축 해제...")
        question_content = self.extractor.extract(question_pdf)
        answer_content = self.extractor.extract(answer_pdf)
        
        # 2. 메타데이터 추출
        logger.info("[2/5] 메타데이터 파싱...")
        metadata = None
        for page in question_content.pages[:5]:  # 처음 5페이지 검색
            metadata = self.metadata_parser.parse_cover(page.text)
            if metadata:
                break
        
        if not metadata:
            raise ValueError("시험 정보를 찾을 수 없습니다.")
        
        # exam_type 오버라이드
        if exam_type:
            metadata.exam_type = exam_type
        
        logger.info(f"  → {metadata.year}년 제{metadata.session}회 {metadata.exam_type}")
        
        # 3. 문제 파싱
        logger.info("[3/5] 문제 파싱...")
        question_parser = QuestionParser(metadata.exam_type)
        questions = question_parser.parse_questions(question_content.pages)
        logger.info(f"  → {len(questions)}문제 추출")
        
        # 4. 정답 파싱
        logger.info("[4/5] 정답 파싱...")
        answers = self.answer_parser.parse_answers(answer_content.pages)
        logger.info(f"  → {sum(len(v) for v in answers.values())}개 정답 추출")
        
        # 5. 데이터 병합 및 검증
        logger.info("[5/5] 데이터 병합...")
        merged_questions = self.merger.merge(questions, answers, metadata)
        validation = self.merger.validate(merged_questions)
        
        # 통계
        stats = self._calculate_stats(merged_questions)
        
        if validation.errors:
            for err in validation.errors:
                logger.error(f"  ✗ {err}")
        if validation.warnings:
            for warn in validation.warnings:
                logger.warning(f"  ⚠ {warn}")
        
        logger.info(f"파싱 완료: {stats['total_questions']}문제")
        
        return {
            'metadata': metadata,
            'questions': merged_questions,
            'validation': validation,
            'stats': stats
        }
    
    def _calculate_stats(self, questions: list) -> dict:
        """통계 계산"""
        subject_counts = {}
        for q in questions:
            subject = q.subject_name or 'unknown'
            subject_counts[subject] = subject_counts.get(subject, 0) + 1
        
        return {
            'total_questions': len(questions),
            'by_subject': subject_counts,
            'with_images': sum(1 for q in questions if q.has_image),
            'with_answers': sum(1 for q in questions if q.correct_answer)
        }
```

---

# 💻 Phase 3: CLI 도구 개발
**예상 기간: 3일**

## Step 3.1: CLI 구조

```python
# src/cli/main.py
"""CLI 엔트리포인트"""

import click
import logging
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)


@click.group()
@click.version_option(version='2.1.0')
def cli():
    """해기사 문제은행 관리 시스템"""
    pass


# ============ 데이터베이스 명령어 ============

@cli.group()
def db():
    """데이터베이스 관리"""
    pass


@db.command()
@click.option('--db-path', default='./data/exam_bank.db', help='DB 파일 경로')
def init(db_path):
    """데이터베이스 초기화"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    repo.init_database()
    click.echo(f"✓ 데이터베이스 초기화 완료: {db_path}")


@db.command()
@click.option('--db-path', default='./data/exam_bank.db')
@click.option('--output', '-o', default='./backup')
def backup(db_path, output):
    """데이터베이스 백업"""
    import shutil
    from datetime import datetime
    
    Path(output).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = Path(output) / f'exam_bank_{timestamp}.db'
    
    shutil.copy2(db_path, backup_path)
    click.echo(f"✓ 백업 완료: {backup_path}")


# ============ PDF 임포트 명령어 ============

@cli.command()
@click.argument('question_pdf', type=click.Path(exists=True))
@click.argument('answer_pdf', type=click.Path(exists=True))
@click.option('--exam-type', help='시험 종류 (자동 감지 시 생략)')
@click.option('--db-path', default='./data/exam_bank.db')
@click.option('--dry-run', is_flag=True, help='DB 저장 없이 파싱만 실행')
def import_pdf(question_pdf, answer_pdf, exam_type, db_path, dry_run):
    """PDF에서 문제 임포트
    
    예시:
        exam-bank import ./2022_exam.pdf ./2022_answer.pdf
        exam-bank import ./exam.pdf ./answer.pdf --exam-type 3급기관사
    """
    from ..parser.main import ExamPDFParser
    from ..database.repository import ExamRepository
    
    # 파싱
    parser = ExamPDFParser()
    result = parser.parse(question_pdf, answer_pdf, exam_type)
    
    # 결과 출력
    click.echo("\n" + "=" * 60)
    click.echo("📊 파싱 결과")
    click.echo("=" * 60)
    
    meta = result['metadata']
    click.echo(f"시험: {meta.exam_type}")
    click.echo(f"연도: {meta.year}년 제{meta.session}회")
    
    click.echo(f"\n문제 수: {result['stats']['total_questions']}")
    click.echo("과목별:")
    for subject, count in result['stats']['by_subject'].items():
        click.echo(f"  - {subject}: {count}문제")
    
    click.echo(f"\n이미지 포함: {result['stats']['with_images']}문제")
    click.echo(f"정답 매칭: {result['stats']['with_answers']}문제")
    
    # 검증 결과
    val = result['validation']
    if val.errors:
        click.echo("\n❌ 오류:")
        for err in val.errors:
            click.echo(f"  - {err}")
    
    if val.warnings:
        click.echo("\n⚠️ 경고:")
        for warn in val.warnings:
            click.echo(f"  - {warn}")
    
    # DB 저장
    if not dry_run and val.is_valid:
        repo = ExamRepository(db_path)
        saved_count = repo.save_questions(result['questions'], meta)
        click.echo(f"\n✓ {saved_count}문제 저장 완료")
    elif dry_run:
        click.echo("\n[Dry Run] DB 저장 생략")
    else:
        click.echo("\n❌ 오류로 인해 DB 저장 생략")


# ============ 문제 조회 명령어 ============

@cli.group()
def question():
    """문제 관리"""
    pass


@question.command('list')
@click.option('--exam', help='시험 코드')
@click.option('--subject', help='과목 코드')
@click.option('--year', type=int, help='출제 연도')
@click.option('--session', type=int, help='회차')
@click.option('--limit', default=20, help='출력 개수')
@click.option('--db-path', default='./data/exam_bank.db')
def list_questions(exam, subject, year, session, limit, db_path):
    """문제 목록 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    questions = repo.search_questions(
        exam_code=exam,
        subject_code=subject,
        year=year,
        session=session,
        limit=limit
    )
    
    if not questions:
        click.echo("조회된 문제가 없습니다.")
        return
    
    for q in questions:
        click.echo(f"\n[{q['id']}] {q['subject_name']} {q['year']}년 {q['session']}회 {q['question_number']}번")
        click.echo(f"  {q['question_text'][:80]}...")


@question.command('show')
@click.argument('question_id', type=int)
@click.option('--db-path', default='./data/exam_bank.db')
def show_question(question_id, db_path):
    """문제 상세 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    q = repo.get_question(question_id)
    
    if not q:
        click.echo(f"문제 ID {question_id}를 찾을 수 없습니다.")
        return
    
    click.echo(f"\n{'=' * 60}")
    click.echo(f"[{q['id']}] {q['subject_name']} {q['year']}년 {q['session']}회 {q['question_number']}번")
    click.echo(f"{'=' * 60}")
    click.echo(f"\n{q['question_text']}\n")
    
    for choice in q['choices']:
        marker = "✓" if choice['number'] == q['correct_answer'] else " "
        click.echo(f"  {marker} {choice['symbol']} {choice['text']}")
    
    click.echo(f"\n정답: {q['correct_answer']}번")


# ============ 모의고사 명령어 ============

@cli.group()
def mock():
    """모의고사 관리"""
    pass


@mock.command('create')
@click.option('--exam', required=True, help='시험 코드')
@click.option('--subjects', help='과목 코드 (쉼표 구분)')
@click.option('--count', default=25, help='과목당 문제 수')
@click.option('--db-path', default='./data/exam_bank.db')
def create_mock(exam, subjects, count, db_path):
    """모의고사 생성"""
    from ..database.repository import ExamRepository
    from ..quiz.generator import MockExamGenerator
    
    repo = ExamRepository(db_path)
    generator = MockExamGenerator(repo)
    
    subject_list = subjects.split(',') if subjects else None
    mock_exam = generator.create(exam, subject_list, count)
    
    click.echo(f"✓ 모의고사 생성 완료: ID {mock_exam['id']}")
    click.echo(f"  총 {mock_exam['total_questions']}문제")


@mock.command('start')
@click.argument('mock_id', type=int)
@click.option('--db-path', default='./data/exam_bank.db')
def start_mock(mock_id, db_path):
    """모의고사 시작 (CLI 퀴즈 모드)"""
    from ..database.repository import ExamRepository
    from ..quiz.runner import CLIQuizRunner
    
    repo = ExamRepository(db_path)
    runner = CLIQuizRunner(repo)
    
    result = runner.run(mock_id)
    
    click.echo(f"\n{'=' * 60}")
    click.echo(f"📊 결과: {result['score']}점 ({result['correct']}/{result['total']})")
    click.echo(f"{'=' * 60}")


# ============ 통계 명령어 ============

@cli.command()
@click.option('--exam', help='시험 코드')
@click.option('--year', type=int, help='연도')
@click.option('--db-path', default='./data/exam_bank.db')
def stats(exam, year, db_path):
    """통계 조회"""
    from ..database.repository import ExamRepository
    
    repo = ExamRepository(db_path)
    statistics = repo.get_statistics(exam_code=exam, year=year)
    
    click.echo("\n📊 문제은행 통계")
    click.echo("=" * 40)
    click.echo(f"총 문제 수: {statistics['total_questions']}")
    click.echo(f"시험 종류: {statistics['exam_count']}")
    click.echo(f"과목 수: {statistics['subject_count']}")
    
    click.echo("\n연도별 문제 수:")
    for year, count in statistics['by_year'].items():
        click.echo(f"  {year}년: {count}문제")


if __name__ == '__main__':
    cli()
```

## Step 3.2: 사용 예시

```bash
# 데이터베이스 초기화
python -m src.cli.main db init

# PDF 임포트 (dry-run으로 테스트)
python -m src.cli.main import ./2022_exam.pdf ./2022_answer.pdf --dry-run

# PDF 임포트 (실제 저장)
python -m src.cli.main import ./2022_exam.pdf ./2022_answer.pdf

# 문제 조회
python -m src.cli.main question list --exam 3급기관사 --year 2022
python -m src.cli.main question show 42

# 모의고사 생성 및 실행
python -m src.cli.main mock create --exam 3급기관사
python -m src.cli.main mock start 1

# 통계 조회
python -m src.cli.main stats --exam 3급기관사

# 백업
python -m src.cli.main db backup
```

---

# 📁 프로젝트 구조

```
exam_bank/
├── README.md
├── requirements.txt
├── setup.py
├── pyproject.toml
│
├── src/
│   ├── __init__.py
│   │
│   ├── cli/                       # CLI 모듈
│   │   ├── __init__.py
│   │   └── main.py                # CLI 엔트리포인트
│   │
│   ├── parser/                    # PDF 파싱 모듈
│   │   ├── __init__.py
│   │   ├── patterns.py            # 정규식 패턴
│   │   ├── extractor.py           # PDFExtractor
│   │   ├── metadata.py            # ExamMetadataParser
│   │   ├── question.py            # QuestionParser
│   │   ├── answer.py              # AnswerParser
│   │   ├── merger.py              # DataMerger
│   │   └── main.py                # ExamPDFParser (통합)
│   │
│   ├── database/                  # 데이터베이스 모듈
│   │   ├── __init__.py
│   │   ├── schema.sql             # DDL 스크립트
│   │   ├── seed.sql               # 초기 데이터
│   │   └── repository.py          # CRUD 연산
│   │
│   ├── quiz/                      # 퀴즈/모의고사 모듈
│   │   ├── __init__.py
│   │   ├── generator.py           # 문제 출제 로직
│   │   ├── runner.py              # CLI 퀴즈 실행
│   │   └── scorer.py              # 채점 로직
│   │
│   └── utils/                     # 유틸리티
│       ├── __init__.py
│       └── constants.py           # 상수 정의
│
├── tests/                         # 테스트
│   ├── __init__.py
│   ├── test_parser/
│   │   ├── test_extractor.py
│   │   ├── test_question.py
│   │   └── test_answer.py
│   ├── test_database/
│   └── fixtures/                  # 테스트 데이터
│       ├── sample_page.txt
│       └── sample_answer.txt
│
├── data/                          # 데이터 디렉토리
│   ├── pdf/                       # 원본 PDF
│   ├── extracted/                 # 추출된 텍스트
│   ├── images/                    # 추출된 이미지
│   └── exam_bank.db               # SQLite DB
│
└── scripts/                       # 유틸리티 스크립트
    ├── batch_import.py            # PDF 일괄 임포트
    └── export_json.py             # JSON 내보내기
```

---

# 📅 개발 일정

| Phase | 내용 | 예상 기간 | 상태 |
|-------|------|----------|------|
| 0 | PDF 구조 분석 | - | ✅ 완료 |
| 1 | DB 스키마 설계 | 3일 | 🔲 예정 |
| 2 | PDF 파싱 엔진 | 1주 | 🔲 예정 |
| 3 | CLI 도구 개발 | 3일 | 🔲 예정 |
| 4 | 퀴즈/모의고사 기능 | 3일 | 🔲 예정 |
| 5 | 테스트 및 문서화 | 2일 | 🔲 예정 |

**총 예상 개발 기간: 3주**

---

# 🎯 핵심 워크플로우

## 관리자 워크플로우 (Claude Code / Codex)

```bash
# 1. 프로젝트 초기화
cd exam_bank
python -m src.cli.main db init

# 2. PDF 파싱 테스트 (dry-run)
python -m src.cli.main import \
    ./data/pdf/2022_3급기관사_문제.pdf \
    ./data/pdf/2022_3급기관사_정답.pdf \
    --dry-run

# 3. 실제 임포트
python -m src.cli.main import \
    ./data/pdf/2022_3급기관사_문제.pdf \
    ./data/pdf/2022_3급기관사_정답.pdf

# 4. 문제 검토
python -m src.cli.main question list --exam 3급기관사 --year 2022
python -m src.cli.main question show 1

# 5. 백업
python -m src.cli.main db backup
```

## 학습자 워크플로우 (CLI)

```bash
# 1. 통계 확인
python -m src.cli.main stats

# 2. 모의고사 생성
python -m src.cli.main mock create --exam 3급기관사

# 3. 모의고사 실행
python -m src.cli.main mock start 1

# 4. 결과 확인
python -m src.cli.main mock result 1
```

---

# 🔧 LLM 없이 파싱 가능한 범위

| 항목 | 규칙 기반 파싱 | LLM 필요 |
|-----|--------------|---------|
| 문제 번호 인식 | ✅ | - |
| 선지 추출 (㉮㉯㉴㉵) | ✅ | - |
| 과목 전환 감지 | ✅ | - |
| 정답 문자열 파싱 | ✅ | - |
| 표지 메타데이터 | ✅ | - |
| 이미지 포함 문제 | ⚠️ 감지만 | 내용 해석 |
| 표/다이어그램 | ⚠️ 감지만 | 내용 해석 |
| 특수 형식 문제 | ⚠️ 일부 | 복잡한 경우 |

**결론: 90%+ 문제는 LLM 없이 규칙 기반으로 파싱 가능**

---

*이 계획서는 2022년 3급 기관사 시험 PDF 분석 결과를 기반으로 작성되었습니다.*
*개발 도구: Claude Code, Codex*
