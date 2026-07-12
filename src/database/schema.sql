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

-- ============ 문제 출처 테이블 ============
CREATE TABLE IF NOT EXISTS question_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    source_url TEXT NOT NULL,
    document_id TEXT,
    attachment_url TEXT,
    attachment_filename TEXT,
    content_hash TEXT NOT NULL,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider, source_url, content_hash)
);

-- ============ 공통 지문/그룹 테이블 ============
CREATE TABLE IF NOT EXISTS question_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_subject_id INTEGER NOT NULL REFERENCES exam_subjects(id),
    year INTEGER NOT NULL,
    session INTEGER NOT NULL,
    group_number INTEGER NOT NULL,
    group_type TEXT,
    shared_text TEXT,
    shared_image_path TEXT,
    source_id INTEGER REFERENCES question_sources(id),
    source_page INTEGER,
    tags TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(exam_subject_id, year, session, group_number)
);

-- ============ 문제 테이블 ============
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_subject_id INTEGER NOT NULL REFERENCES exam_subjects(id),
    year INTEGER NOT NULL,               -- 2022
    session INTEGER NOT NULL,            -- 1, 2, 3, 4 (회차)
    question_number INTEGER NOT NULL,    -- 1-25
    question_text TEXT NOT NULL,         -- 문제 본문
    question_format_json TEXT,           -- 문제 본문 서식 JSON
    explanation TEXT,                    -- 사용자가 직접 작성한 상세 해설
    has_image BOOLEAN DEFAULT 0,         -- 이미지 포함 여부
    image_path TEXT,                     -- 이미지 경로
    correct_answer INTEGER NOT NULL,     -- 1, 2, 3, 4
    answer_available BOOLEAN NOT NULL DEFAULT 1, -- 0 when the official source provides no answer
    source_page INTEGER,                 -- 원본 PDF 페이지
    tags TEXT,                           -- 태그 (comma separated)
    group_id INTEGER REFERENCES question_groups(id),
    group_order INTEGER,
    source_id INTEGER REFERENCES question_sources(id),
    source_question_id TEXT,
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
    choice_format_json TEXT,             -- 선지 텍스트 서식 JSON
    choice_image_path TEXT,              -- 선지 이미지 경로
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
