-- database/seed.sql

-- 과목 데이터
INSERT OR IGNORE INTO subjects (code, name_ko, name_en) VALUES
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
INSERT OR IGNORE INTO exams (code, name, is_domestic_only) VALUES
    ('1급기관사', '1급 기관사', 0),
    ('2급기관사', '2급 기관사', 0),
    ('3급기관사', '3급 기관사', 0),
    ('3급기관사(국내)', '3급 기관사 (국내한정)', 1),
    ('4급기관사', '4급 기관사', 0),
    ('5급기관사', '5급 기관사', 0),
    ('5급기관사(국내)', '5급 기관사 (국내한정)', 1),
    ('6급기관사', '6급 기관사', 0),
    ('1급항해사(상선)', '1급 항해사 (상선)', 0),
    ('1급항해사(어선)', '1급 항해사 (어선)', 0),
    ('2급항해사(상선)', '2급 항해사 (상선)', 0),
    ('2급항해사(어선)', '2급 항해사 (어선)', 0),
    ('3급항해사(상선)', '3급 항해사 (상선)', 0);

-- 공통 기관사 시험-과목 관계 (기관1, 기관2, 기관3, 직무일반, 영어)
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, v.display_order, 25
FROM exams e
JOIN (
    SELECT 'engine1' AS subject_code, 1 AS display_order
    UNION ALL SELECT 'engine2', 2
    UNION ALL SELECT 'engine3', 3
    UNION ALL SELECT 'general', 4
    UNION ALL SELECT 'english', 5
) v
JOIN subjects s ON s.code = v.subject_code
WHERE e.code IN ('1급기관사', '2급기관사', '3급기관사', '4급기관사', '5급기관사');

-- 국내한정/6급 기관사 시험-과목 관계 (영어 제외)
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, v.display_order, 25
FROM exams e
JOIN (
    SELECT 'engine1' AS subject_code, 1 AS display_order
    UNION ALL SELECT 'engine2', 2
    UNION ALL SELECT 'engine3', 3
    UNION ALL SELECT 'general', 4
) v
JOIN subjects s ON s.code = v.subject_code
WHERE e.code IN ('3급기관사(국내)', '5급기관사(국내)', '6급기관사');

-- 상선 항해사 시험-과목 관계
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, v.display_order, 25
FROM exams e
JOIN (
    SELECT 'navigation' AS subject_code, 1 AS display_order
    UNION ALL SELECT 'operation', 2
    UNION ALL SELECT 'regulation', 3
    UNION ALL SELECT 'english', 4
    UNION ALL SELECT 'merchant', 5
) v
JOIN subjects s ON s.code = v.subject_code
WHERE e.code IN ('1급항해사(상선)', '2급항해사(상선)', '3급항해사(상선)');

-- 시험-과목 관계 (3급 기관사)
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 1, 25
FROM exams e
JOIN subjects s ON s.code = 'engine1'
WHERE e.code = '3급기관사';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 2, 25
FROM exams e
JOIN subjects s ON s.code = 'engine2'
WHERE e.code = '3급기관사';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 3, 25
FROM exams e
JOIN subjects s ON s.code = 'engine3'
WHERE e.code = '3급기관사';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 4, 25
FROM exams e
JOIN subjects s ON s.code = 'general'
WHERE e.code = '3급기관사';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 5, 25
FROM exams e
JOIN subjects s ON s.code = 'english'
WHERE e.code = '3급기관사';

-- 시험-과목 관계 (3급 기관사 국내한정)
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 1, 25
FROM exams e
JOIN subjects s ON s.code = 'engine1'
WHERE e.code = '3급기관사(국내)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 2, 25
FROM exams e
JOIN subjects s ON s.code = 'engine2'
WHERE e.code = '3급기관사(국내)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 3, 25
FROM exams e
JOIN subjects s ON s.code = 'engine3'
WHERE e.code = '3급기관사(국내)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 4, 25
FROM exams e
JOIN subjects s ON s.code = 'general'
WHERE e.code = '3급기관사(국내)';

-- 시험-과목 관계 (3급 항해사 상선)
INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 1, 25
FROM exams e
JOIN subjects s ON s.code = 'navigation'
WHERE e.code = '3급항해사(상선)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 2, 25
FROM exams e
JOIN subjects s ON s.code = 'operation'
WHERE e.code = '3급항해사(상선)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 3, 25
FROM exams e
JOIN subjects s ON s.code = 'regulation'
WHERE e.code = '3급항해사(상선)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 4, 25
FROM exams e
JOIN subjects s ON s.code = 'english'
WHERE e.code = '3급항해사(상선)';

INSERT OR IGNORE INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
SELECT e.id, s.id, 5, 25
FROM exams e
JOIN subjects s ON s.code = 'merchant'
WHERE e.code = '3급항해사(상선)';
