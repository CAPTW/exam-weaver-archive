import sqlite3
import json

from src.parser.merger import DataMerger
from src.parser.question import Choice, Question
from src.database.repository import (
    CLONED_MANUAL_TAG,
    MANUAL_EXAM_CODE,
    MANUAL_SUBJECT_CODE,
    QUESTION_TYPE_DESCRIPTIVE,
)
from src.database.repository import ExamRepository
from src.web_import.importer import ComcbtImportService, QuestionSource
from src.web_import.models import ComcbtParsedExam, ComcbtQuestionGroup


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def test_init_database_backfills_missing_tags_and_reference_data(repo):
    with sqlite3.connect(repo.db_path) as conn:
        exam_subject_id = conn.execute("""
            SELECT es.id
            FROM exam_subjects es
            JOIN exams e ON e.id = es.exam_id
            JOIN subjects s ON s.id = es.subject_id
            WHERE e.code = '3급기관사' AND s.code = 'engine1'
        """).fetchone()[0]

        conn.execute("""
            INSERT INTO questions (
                exam_subject_id,
                year,
                session,
                question_number,
                question_text,
                has_image,
                image_path,
                correct_answer,
                source_page,
                tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            exam_subject_id,
            2023,
            1,
            1,
            '기관 출력 계산 문제',
            0,
            None,
            2,
            1,
            None,
        ))
        question_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.executemany("""
            INSERT INTO question_choices (question_id, choice_number, choice_symbol, choice_text)
            VALUES (?, ?, ?, ?)
        """, [
            (question_id, 1, '㉮', '10'),
            (question_id, 2, '㉯', '20'),
            (question_id, 3, '㉴', '30'),
            (question_id, 4, '㉵', '40'),
        ])
        conn.commit()

    repo._initialized = False
    repo.init_database()

    with sqlite3.connect(repo.db_path) as conn:
        tags = conn.execute("SELECT tags FROM questions WHERE id = ?", (question_id,)).fetchone()[0]

    assert '#3급기관사' in tags
    assert '#기관1' in tags
    assert '#계산' in tags

    options = repo.get_filter_options()
    assert [row['code'] for row in options['exams']] == ['3급기관사']
    assert [row['code'] for row in repo.get_subject_options('3급기관사')] == ['engine1']


def test_empty_database_hides_seed_reference_options(repo):
    options = repo.get_filter_options()

    assert options['exams'] == []
    assert repo.get_subject_options() == []
    assert repo.get_subject_options('4급기관사') == []


def test_init_database_creates_comcbt_source_group_tables_and_question_columns(tmp_path):
    db_path = tmp_path / "fresh.db"
    repo = ExamRepository(str(db_path))
    repo.init_database()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        question_columns = _columns(conn, "questions")

    assert "question_sources" in tables
    assert "question_groups" in tables
    assert {"group_id", "group_order", "source_id", "source_question_id"}.issubset(question_columns)


def test_init_database_migrates_old_questions_table_with_missing_comcbt_columns(tmp_path):
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE exams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                is_domestic_only BOOLEAN DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name_ko TEXT NOT NULL,
                name_en TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE exam_subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_id INTEGER NOT NULL REFERENCES exams(id),
                subject_id INTEGER NOT NULL REFERENCES subjects(id),
                display_order INTEGER NOT NULL,
                questions_count INTEGER DEFAULT 25,
                UNIQUE(exam_id, subject_id)
            );
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_subject_id INTEGER NOT NULL REFERENCES exam_subjects(id),
                year INTEGER NOT NULL,
                session INTEGER NOT NULL,
                question_number INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                has_image BOOLEAN DEFAULT 0,
                image_path TEXT,
                correct_answer INTEGER NOT NULL,
                source_page INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(exam_subject_id, year, session, question_number)
            );
            CREATE TABLE question_choices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL REFERENCES questions(id),
                choice_number INTEGER NOT NULL,
                choice_symbol TEXT NOT NULL,
                choice_text TEXT NOT NULL,
                UNIQUE(question_id, choice_number)
            );
            """
        )

    repo = ExamRepository(str(db_path))
    repo.init_database()

    with sqlite3.connect(db_path) as conn:
        assert {"group_id", "group_order", "source_id", "source_question_id"}.issubset(
            _columns(conn, "questions")
        )
        assert "question_format_json" in _columns(conn, "questions")
        assert "tags" in _columns(conn, "questions")
        assert "choice_image_path" in _columns(conn, "question_choices")
        assert "question_sources" in {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }


def test_init_database_migrates_partial_comcbt_tables_and_importer_can_insert(tmp_path):
    db_path = tmp_path / "partial-comcbt.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE question_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT
            );
            CREATE TABLE question_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exam_subject_id INTEGER
            );
            """
        )

    repo = ExamRepository(str(db_path))
    repo.init_database()

    required_source_columns = {
        "provider",
        "source_url",
        "document_id",
        "attachment_url",
        "attachment_filename",
        "content_hash",
        "fetched_at",
    }
    required_group_columns = {
        "exam_subject_id",
        "year",
        "session",
        "group_number",
        "group_type",
        "shared_text",
        "shared_image_path",
        "source_id",
        "source_page",
        "tags",
        "created_at",
    }
    with sqlite3.connect(db_path) as conn:
        assert required_source_columns.issubset(_columns(conn, "question_sources"))
        assert required_group_columns.issubset(_columns(conn, "question_groups"))

    group = ComcbtQuestionGroup(
        group_id="group-1",
        text="공통 지문",
        child_numbers=[1],
        range_start=1,
        range_end=1,
        explicit_range=True,
    )
    question = Question(
        number=1,
        text="공통 문항",
        choices=[
            Choice(number=1, symbol="㉮", text="A"),
            Choice(number=2, symbol="㉯", text="B"),
            Choice(number=3, symbol="㉴", text="C"),
            Choice(number=4, symbol="㉵", text="D"),
        ],
        correct_answer=1,
        subject_name="자료 해석",
        year=2025,
        session=1,
        exam_type="Sample Exam",
        group_id="group-1",
        group_order=1,
        shared_passage="공통 지문",
    )
    parsed_exam = ComcbtParsedExam(
        title="Sample",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        exam_type="Sample Exam",
        subject_name="자료 해석",
        year=2025,
        session=1,
        questions=[question],
        attachments=[],
        groups=[group],
        diagnostics={"invalid_group_range": False, "ambiguous_group_range": False},
    )
    source = QuestionSource(
        provider="comcbt",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        document_id="8837719",
        attachment_url="https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1",
        attachment_filename="시험(교사용).pdf",
        content_hash="abc123",
        fetched_at="2026-06-29T00:00:00+00:00",
    )

    result = ComcbtImportService(db_path).import_exam(parsed_exam=parsed_exam, source=source)

    assert result.status == "imported"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM question_groups").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0] == 1


def test_filter_subject_options_only_include_subjects_with_questions(repo):
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()
    question = Question(
        number=1,
        text='4급 기관 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )

    assert repo.save_questions([question], metadata) == 1

    assert [row['code'] for row in repo.get_subject_options('4급기관사')] == ['engine1']


def test_save_questions_accepts_4th_engine_exam(repo):
    question = Question(
        number=1,
        text='4급 기관 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()

    assert repo.save_questions([question], metadata) == 1

    saved = repo.get_questions_with_choices(exam_code='4급기관사', limit=1)
    assert saved[0]['subject_name'] == '기관1'
    assert saved[0]['correct_answer'] == 1


def test_save_questions_ignores_duplicate_choice_numbers(repo):
    question = Question(
        number=1,
        text='중복 선지 번호 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='첫 번째 1번'),
            Choice(number=2, symbol='㉯', text='2번'),
            Choice(number=1, symbol='㉮', text='중복 1번'),
            Choice(number=3, symbol='㉴', text='3번'),
            Choice(number=4, symbol='㉵', text='4번'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()

    assert repo.save_questions([question], metadata) == 1

    saved = repo.get_questions_with_choices(exam_code='4급기관사', limit=1)
    assert [choice['number'] for choice in saved[0]['choices']] == [1, 2, 3, 4]
    assert saved[0]['choices'][0]['text'] == '첫 번째 1번'


def test_save_questions_preserves_fifth_choice(repo):
    question = Question(
        number=2,
        text='5지선다 저장 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='1번'),
            Choice(number=2, symbol='㉯', text='2번'),
            Choice(number=3, symbol='㉴', text='3번'),
            Choice(number=4, symbol='㉵', text='4번'),
            Choice(number=5, symbol='⑤', text='5번'),
        ],
        correct_answer=5,
        subject_name='기관1',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()

    assert repo.save_questions([question], metadata) == 1

    saved = repo.get_questions_with_choices(exam_code='4급기관사', limit=1)
    assert [choice['number'] for choice in saved[0]['choices']] == [1, 2, 3, 4, 5]
    assert saved[0]['correct_answer'] == 5


def test_save_questions_updates_existing_question_and_choices(repo):
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()
    original = Question(
        number=3,
        text='잘못 저장된 밸브 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='오답1'),
            Choice(number=2, symbol='㉯', text='오답2'),
            Choice(number=3, symbol='㉴', text='오답3'),
            Choice(number=4, symbol='㉵', text='오답4'),
        ],
        correct_answer=1,
        has_image=True,
        image_path='wrong-logo.jpg',
        source_page=7,
        subject_name='직무일반',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )
    updated = Question(
        number=3,
        text='다음 그림과 같은 밸브는?',
        choices=[
            Choice(number=1, symbol='㉮', text='슬루스밸브'),
            Choice(number=2, symbol='㉯', text='글러브밸브'),
            Choice(number=3, symbol='㉴', text='체크밸브'),
            Choice(number=4, symbol='㉵', text='나비밸브'),
        ],
        correct_answer=3,
        has_image=True,
        image_path='correct-valve.jpg',
        source_page=7,
        subject_name='직무일반',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )

    assert repo.save_questions([original], metadata) == 1
    assert repo.save_questions([updated], metadata) == 1

    saved = repo.get_questions_with_choices(
        exam_code='4급기관사',
        subject_code='general',
        year=2025,
        session=1,
        question_numbers=[3],
        limit=1,
    )[0]
    assert saved['question_text'] == '다음 그림과 같은 밸브는?'
    assert saved['image_path'] == 'correct-valve.jpg'
    assert saved['correct_answer'] == 3
    assert [choice['text'] for choice in saved['choices']] == [
        '슬루스밸브', '글러브밸브', '체크밸브', '나비밸브'
    ]


def test_save_questions_preserves_existing_choices_when_reparse_has_blank_choices(repo):
    metadata = type('Metadata', (), {'year': 2025, 'session': 1, 'exam_type': '4급기관사'})()
    original = Question(
        number=4,
        text='기존 선지가 있는 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='기존 1번'),
            Choice(number=2, symbol='㉯', text='기존 2번', image_path='choice-2.png'),
            Choice(number=3, symbol='㉴', text='기존 3번'),
            Choice(number=4, symbol='㉵', text='기존 4번'),
        ],
        correct_answer=2,
        has_image=True,
        image_path='old-question.png',
        source_page=8,
        subject_name='기관3',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )
    reparsed = Question(
        number=4,
        text='재파싱된 발문',
        choices=[
            Choice(number=1, symbol='㉮', text=''),
            Choice(number=2, symbol='㉯', text=''),
            Choice(number=3, symbol='㉴', text=''),
            Choice(number=4, symbol='㉵', text=''),
        ],
        correct_answer=3,
        has_image=True,
        image_path='new-question.png',
        source_page=8,
        subject_name='기관3',
        year=2025,
        session=1,
        exam_type='4급기관사',
    )

    assert repo.save_questions([original], metadata) == 1
    assert repo.save_questions([reparsed], metadata) == 1

    saved = repo.get_questions_with_choices(
        exam_code='4급기관사',
        subject_code='engine3',
        year=2025,
        session=1,
        question_numbers=[4],
        limit=1,
    )[0]
    assert saved['question_text'] == '재파싱된 발문'
    assert saved['correct_answer'] == 3
    assert saved['image_path'] == 'new-question.png'
    assert [choice['text'] for choice in saved['choices']] == [
        '기존 1번', '기존 2번', '기존 3번', '기존 4번'
    ]
    assert saved['choices'][1]['choice_image_path'] == 'choice-2.png'


def test_save_questions_auto_registers_unknown_exam_type(repo):
    question = Question(
        number=1,
        text='처음 보는 시험 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=2,
        subject_name='기관1',
        year=2026,
        session=1,
        exam_type='새시험기관사',
    )
    metadata = type('Metadata', (), {'year': 2026, 'session': 1, 'exam_type': '새시험기관사'})()

    assert repo.save_questions([question], metadata) == 1

    saved = repo.get_questions_with_choices(exam_code='새시험기관사', limit=1)
    assert saved[0]['exam_name'] == '새시험기관사'
    assert saved[0]['subject_name'] == '기관1'
    assert [row['code'] for row in repo.get_subject_options('새시험기관사')] == ['engine1']


def test_save_questions_auto_registers_unknown_subjects_in_order(repo):
    questions = [
        Question(
            number=1,
            text='새 과목 A 문제',
            choices=[Choice(number=1, symbol='㉮', text='가')],
            correct_answer=1,
            subject_name='특수과목A',
            year=2026,
            session=1,
            exam_type='새시험',
        ),
        Question(
            number=1,
            text='새 과목 B 문제',
            choices=[Choice(number=1, symbol='㉮', text='가')],
            correct_answer=1,
            subject_name='특수과목B',
            year=2026,
            session=1,
            exam_type='새시험',
        ),
    ]
    metadata = type('Metadata', (), {'year': 2026, 'session': 1, 'exam_type': '새시험'})()

    assert repo.save_questions(questions, metadata) == 2

    subjects = repo.get_subject_options('새시험')
    assert [row['name_ko'] for row in subjects] == ['특수과목A', '특수과목B']
    assert all(row['code'].startswith('auto_') for row in subjects)
    assert all('특수과목' in row['code'] for row in subjects)


def test_get_question_and_search_with_choices_expose_choice_aliases(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)

    question = repo.get_question(1)
    assert question is not None
    assert question['choices'][0]['choice_number'] == 1
    assert question['choices'][0]['number'] == 1
    assert question['choices'][0]['choice_symbol'] == '㉮'
    assert question['choices'][0]['symbol'] == '㉮'
    assert question['choices'][0]['choice_text'] == '10'
    assert question['choices'][0]['text'] == '10'

    searched = repo.get_questions_with_choices(limit=1)
    assert searched[0]['choices'][1]['number'] == 2
    assert searched[0]['choices'][1]['symbol'] == '㉯'
    assert searched[0]['choices'][1]['text'] == '20'


def test_update_question_persists_text_choices_answer_tags_and_image(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    assert repo.update_question(question['id'], {
        'question_text': '수정된 발문',
        'correct_answer': 4,
        'tags': '#수정 #태그',
        'image_path': 'updated-image.png',
        'choices': [
            {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': '수정 선지 1'},
            {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': '수정 선지 2'},
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '수정 선지 3'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '수정 선지 4'},
        ],
    }) is True

    updated = repo.get_question(question['id'])
    assert updated['question_text'] == '수정된 발문'
    assert updated['correct_answer'] == 4
    assert updated['tags'] == '#수정 #태그'
    assert updated['image_path'] == 'updated-image.png'
    assert updated['has_image'] == 1
    assert [(c['choice_number'], c['choice_symbol'], c['choice_text']) for c in updated['choices']] == [
        (1, '㉮', '수정 선지 1'),
        (2, '㉯', '수정 선지 2'),
        (3, '㉴', '수정 선지 3'),
        (4, '㉵', '수정 선지 4'),
    ]


def test_create_manual_question_inserts_personal_exam_subject_and_choices(repo):
    template = repo.get_manual_question_template()
    template.update({
        'question_text': '개인이 만든 안전관리 문제',
        'correct_answer': 2,
        'explanation': '사용자 작성 해설',
        'tags': '#안전관리',
        'choices': [
            {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': '오답 A'},
            {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': '정답 B'},
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '오답 C'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '오답 D'},
        ],
    })

    question_id = repo.create_manual_question(template)

    assert question_id is not None
    saved = repo.get_questions_with_choices(exam_code=MANUAL_EXAM_CODE, limit=1)[0]
    assert saved['id'] == question_id
    assert saved['exam_name'] == '개인 제작 문제'
    assert saved['subject_name'] == '개인 문제'
    assert saved['question_text'] == '개인이 만든 안전관리 문제'
    assert saved['correct_answer'] == 2
    assert '#안전관리' in saved['tags']
    assert '#개인제작' in saved['tags']
    assert [choice['choice_text'] for choice in saved['choices']] == [
        '오답 A',
        '정답 B',
        '오답 C',
        '오답 D',
    ]

    next_template = repo.get_manual_question_template()
    assert next_template['exam_code'] == MANUAL_EXAM_CODE
    assert next_template['subject_code'] == MANUAL_SUBJECT_CODE
    assert next_template['question_number'] == template['question_number'] + 1


def test_create_manual_question_accepts_more_than_five_choices(repo):
    template = repo.get_manual_question_template()
    template.update({
        'question_text': '6지선다 개인 제작 문제',
        'correct_answer': 6,
        'choices': [
            {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': 'A'},
            {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': 'B'},
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': 'C'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': 'D'},
            {'choice_number': 5, 'choice_symbol': '⑤', 'choice_text': 'E'},
            {'choice_number': 6, 'choice_symbol': '6', 'choice_text': 'F'},
        ],
    })

    question_id = repo.create_manual_question(template)

    assert question_id is not None
    saved = repo.get_question(question_id)
    assert saved['correct_answer'] == 6
    assert [choice['choice_number'] for choice in saved['choices']] == [1, 2, 3, 4, 5, 6]
    assert saved['choices'][-1]['choice_symbol'] == '6'
    assert saved['choices'][-1]['choice_text'] == 'F'


def test_create_manual_descriptive_question_stores_model_answer_without_choices(repo):
    template = repo.get_manual_descriptive_question_template()
    template.update({
        'question_text': '선박 복원성의 의미를 설명하시오.',
        'model_answer': '외력으로 기울어진 선박이 원래 자세로 돌아가려는 성질이다.',
        'tags': '#복원성',
    })

    question_id = repo.create_manual_question(template)

    assert question_id is not None
    saved = repo.get_question(question_id)
    assert saved['question_type'] == QUESTION_TYPE_DESCRIPTIVE
    assert saved['question_text'] == '선박 복원성의 의미를 설명하시오.'
    assert saved['model_answer'] == '외력으로 기울어진 선박이 원래 자세로 돌아가려는 성질이다.'
    assert saved['correct_answer'] == 0
    assert saved['choices'] == []
    assert '#복원성' in saved['tags']
    assert '#서술형' in saved['tags']
    assert '#개인제작' in saved['tags']

    searched = repo.get_questions_with_choices(search_text='원래 자세', limit=1)
    assert searched[0]['id'] == question_id


def test_manual_clone_template_copies_existing_question_for_customization(repo, sample_metadata):
    question = Question(
        number=8,
        text='복제할 원본 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='A'),
            Choice(number=2, symbol='㉯', text='B'),
            Choice(number=3, symbol='㉴', text='C'),
            Choice(number=4, symbol='㉵', text='D'),
            Choice(number=5, symbol='⑤', text='E'),
        ],
        correct_answer=5,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    assert repo.save_questions([question], sample_metadata) == 1
    source = repo.get_questions_with_choices(exam_code='3급기관사', limit=1)[0]
    assert repo.update_question_explanation(source['id'], '원본 해설') is True

    template = repo.get_manual_question_clone_template(source['id'])

    assert template is not None
    assert template['editor_title'] == '기존 문제 복제'
    assert template['exam_code'] == MANUAL_EXAM_CODE
    assert template['subject_code'] == MANUAL_SUBJECT_CODE
    assert template['question_text'] == '복제할 원본 문제'
    assert template['correct_answer'] == 5
    assert template['explanation'] == '원본 해설'
    assert CLONED_MANUAL_TAG in template['tags']
    assert '#개인제작' in template['tags']
    assert [choice['choice_number'] for choice in template['choices']] == [1, 2, 3, 4, 5]
    assert template['choices'][-1]['choice_text'] == 'E'


def test_question_explanation_is_migrated_saved_and_exposed(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    assert 'explanation' in question
    assert repo.update_question_explanation(question['id'], "기관 출력은 비례식으로 계산한다.") is True

    updated = repo.get_question(question['id'])
    assert updated['explanation'] == "기관 출력은 비례식으로 계산한다."

    assert repo.update_question(question['id'], {
        'question_text': updated['question_text'],
        'correct_answer': updated['correct_answer'],
        'tags': updated['tags'],
        'image_path': updated['image_path'],
        'choices': updated['choices'],
    }) is True
    assert repo.get_question(question['id'])['explanation'] == "기관 출력은 비례식으로 계산한다."

    assert repo.update_question_explanation(question['id'], "   ") is True
    assert repo.get_question(question['id'])['explanation'] is None


def test_update_question_can_convert_to_descriptive_and_clear_choices(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    assert repo.update_question(question['id'], {
        'question_text': '압축 공기 계통 점검 절차를 서술하시오.',
        'question_type': QUESTION_TYPE_DESCRIPTIVE,
        'model_answer': '드레인 배출, 압력 확인, 누설 점검 순서로 확인한다.',
        'tags': '#서술형',
        'image_path': None,
        'choices': question['choices'],
    }) is True

    updated = repo.get_question(question['id'])
    assert updated['question_type'] == QUESTION_TYPE_DESCRIPTIVE
    assert updated['model_answer'] == '드레인 배출, 압력 확인, 누설 점검 순서로 확인한다.'
    assert updated['correct_answer'] == 0
    assert updated['choices'] == []


def test_choice_image_paths_are_saved_updated_and_exposed(repo, sample_metadata):
    question = Question(
        number=1,
        text='이미지가 포함된 선지를 고르는 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='텍스트 선지'),
            Choice(number=2, symbol='㉯', text='이미지 선지', image_path='choice-before.png'),
            Choice(number=3, symbol='㉴', text='다른 선지'),
            Choice(number=4, symbol='㉵', text='마지막 선지'),
        ],
        correct_answer=2,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )

    assert repo.save_questions([question], sample_metadata) == 1

    saved = repo.get_questions_with_choices(limit=1)[0]
    assert saved['choices'][1]['choice_image_path'] == 'choice-before.png'
    assert saved['choices'][1]['image_path'] == 'choice-before.png'

    assert repo.update_question(saved['id'], {
        'question_text': saved['question_text'],
        'correct_answer': saved['correct_answer'],
        'tags': saved['tags'],
        'image_path': saved['image_path'],
        'choices': [
            {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': '텍스트 선지'},
            {
                'choice_number': 2,
                'choice_symbol': '㉯',
                'choice_text': '이미지 선지 수정',
                'choice_image_path': 'choice-after.png',
            },
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '다른 선지'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '마지막 선지'},
        ],
    }) is True

    updated = repo.get_question(saved['id'])
    assert updated['choices'][1]['choice_text'] == '이미지 선지 수정'
    assert updated['choices'][1]['choice_image_path'] == 'choice-after.png'
    assert updated['choices'][1]['image_path'] == 'choice-after.png'


def test_update_question_can_clear_question_and_choice_image_paths(repo, sample_metadata):
    question = Question(
        number=1,
        text='잘못 연결된 이미지를 삭제할 문제',
        image_path='wrong-question.png',
        choices=[
            Choice(number=1, symbol='㉮', text='이미지 없는 선지', image_path='wrong-choice.png'),
            Choice(number=2, symbol='㉯', text='다른 선지'),
            Choice(number=3, symbol='㉴', text='다른 선지'),
            Choice(number=4, symbol='㉵', text='다른 선지'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )

    assert repo.save_questions([question], sample_metadata) == 1
    saved = repo.get_questions_with_choices(limit=1)[0]

    assert repo.update_question(saved['id'], {
        'question_text': saved['question_text'],
        'correct_answer': saved['correct_answer'],
        'tags': saved['tags'],
        'image_path': None,
        'choices': [
            {
                'choice_number': 1,
                'choice_symbol': '㉮',
                'choice_text': '이미지 없는 선지',
                'choice_image_path': None,
            },
            {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': '다른 선지'},
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': '다른 선지'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': '다른 선지'},
        ],
    }) is True

    updated = repo.get_question(saved['id'])
    assert updated['image_path'] is None
    assert updated['has_image'] == 0
    assert updated['choices'][0]['choice_image_path'] is None
    assert updated['choices'][0]['image_path'] is None


def test_question_and_choice_format_json_are_saved_and_exposed(repo, sample_metadata):
    question = Question(
        number=1,
        text='밑줄 문제',
        format_json=json.dumps({"spans": [{"start": 0, "end": 2, "underline": True}]}),
        choices=[
            Choice(
                number=1,
                symbol='㉮',
                text='정답',
                format_json=json.dumps({"spans": [{"start": 0, "end": 2, "underline": True}]}),
            ),
            Choice(number=2, symbol='㉯', text='오답'),
            Choice(number=3, symbol='㉴', text='오답'),
            Choice(number=4, symbol='㉵', text='오답'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )

    assert repo.save_questions([question], sample_metadata) == 1

    saved = repo.get_questions_with_choices(limit=1)[0]

    assert json.loads(saved['question_format_json'])['spans'][0]['underline'] is True
    assert json.loads(saved['choices'][0]['choice_format_json'])['spans'][0]['underline'] is True


def test_update_question_persists_year_session_number_and_subject(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    assert repo.update_question(question['id'], {
        'question_text': question['question_text'],
        'correct_answer': question['correct_answer'],
        'tags': question['tags'],
        'image_path': question['image_path'],
        'year': 2025,
        'session': 3,
        'question_number': 7,
        'subject_code': 'engine2',
        'exam_code': '3급기관사',
        'choices': question['choices'],
    }) is True

    updated = repo.get_question(question['id'])
    assert updated['year'] == 2025
    assert updated['session'] == 3
    assert updated['question_number'] == 7
    assert updated['subject_code'] == 'engine2'
    assert updated['subject_name'] == '기관2'


def test_delete_question_removes_choices_and_mock_exam_links(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    with sqlite3.connect(repo.db_path) as conn:
        exam_id = conn.execute(
            "SELECT id FROM exams WHERE code = ?",
            (sample_metadata.exam_type,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO mock_exams (exam_id, name) VALUES (?, ?)",
            (exam_id, '삭제 테스트')
        )
        mock_exam_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("""
            INSERT INTO mock_exam_questions (mock_exam_id, question_id, display_order)
            VALUES (?, ?, ?)
        """, (mock_exam_id, question['id'], 1))
        conn.commit()

    assert repo.delete_question(question['id']) is True
    assert repo.get_question(question['id']) is None

    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM question_choices WHERE question_id = ?",
            (question['id'],)
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM mock_exam_questions WHERE question_id = ?",
            (question['id'],)
        ).fetchone()[0] == 0


def test_delete_questions_removes_multiple_questions(repo, sample_metadata, sample_question):
    second_question = Question(
        number=2,
        text='두 번째 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions([sample_question, second_question], sample_metadata)
    ids = [q['id'] for q in repo.get_questions_with_choices(limit=None)]

    assert repo.delete_questions(ids) == 2
    assert repo.get_questions_with_choices(limit=None) == []


def test_search_questions_matches_question_and_choice_text(repo, sample_metadata):
    valve_question = Question(
        number=1,
        text='다음 그림과 같은 밸브는?',
        choices=[
            Choice(number=1, symbol='㉮', text='슬루스밸브'),
            Choice(number=2, symbol='㉯', text='글러브밸브'),
            Choice(number=3, symbol='㉴', text='체크밸브'),
            Choice(number=4, symbol='㉵', text='나비밸브'),
        ],
        correct_answer=3,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions([valve_question], sample_metadata)

    by_question = repo.search_questions(search_text='그림과 같은 밸브', limit=10)
    by_choice = repo.search_questions(search_text='체크밸브', limit=10)

    assert [q['question_number'] for q in by_question] == [1]
    assert [q['question_number'] for q in by_choice] == [1]


def test_search_questions_tag_query_matches_exact_hashtag_token(repo, sample_metadata):
    subject_tag_only = Question(
        number=1,
        text='일반 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    engine_tagged = Question(
        number=2,
        text='디젤 엔진 점검 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='가'),
            Choice(number=2, symbol='㉯', text='나'),
            Choice(number=3, symbol='㉴', text='사'),
            Choice(number=4, symbol='㉵', text='아'),
        ],
        correct_answer=1,
        subject_name='직무일반',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions([subject_tag_only, engine_tagged], sample_metadata)

    by_engine_tag = repo.search_questions(tag_query='#기관', limit=10)
    by_subject_tag = repo.search_questions(tag_query='기관1', limit=10)

    assert [q['question_number'] for q in by_engine_tag] == [2]
    assert [q['question_number'] for q in by_subject_tag] == [1]


def test_validate_handles_questions_without_embedded_metadata():
    result = DataMerger().validate([
        Question(number=1, text='텍스트', choices=[], correct_answer=1, subject_name='기관1')
    ])

    assert result.is_valid is False
    assert any('기관1' in error for error in result.errors)
