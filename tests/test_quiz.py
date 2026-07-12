import sqlite3

import pytest
import click

from src.quiz.generator import MockExamGenerator
from src.quiz.runner import CLIQuizRunner
from src.parser.question import Choice, Question


def _group_choice_set():
    return [
        Choice(number=1, symbol='㉮', text='A'),
        Choice(number=2, symbol='㉯', text='B'),
        Choice(number=3, symbol='㉴', text='C'),
        Choice(number=4, symbol='㉵', text='D'),
    ]


def _save_grouped_questions(repo, sample_metadata, group_id_override=None):
    second_child = Question(
        number=1,
        text='공통 지문 두 번째 하위 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    first_child = Question(
        number=2,
        text='공통 지문 첫 번째 하위 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions([second_child, first_child], sample_metadata)

    with sqlite3.connect(repo.db_path) as conn:
        rows = conn.execute("""
            SELECT id, question_number, exam_subject_id
            FROM questions
            ORDER BY question_number ASC
        """).fetchall()
        exam_subject_id = rows[0][2]
        if group_id_override is None:
            cursor = conn.execute(
                """
                INSERT INTO question_groups (
                    exam_subject_id, year, session, group_number, group_type, shared_text
                ) VALUES (?, 2024, 1, 1, 'passage', ?)
                """,
                (exam_subject_id, '공통 지문 본문'),
            )
            group_id = cursor.lastrowid
        else:
            conn.execute(
                """
                INSERT INTO question_groups (
                    id, exam_subject_id, year, session, group_number, group_type, shared_text
                ) VALUES (?, ?, 2024, 1, 1, 'passage', ?)
                """,
                (group_id_override, exam_subject_id, '공통 지문 본문'),
            )
            group_id = group_id_override
        ids_by_number = {question_number: question_id for question_id, question_number, _ in rows}
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 2 WHERE id = ?",
            (group_id, ids_by_number[1]),
        )
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 1 WHERE id = ?",
            (group_id, ids_by_number[2]),
        )

    return ids_by_number


def _save_duplicate_text_grouped_questions(repo, sample_metadata):
    second_order_child = Question(
        number=1,
        text='같은 공통 발문',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    first_order_child = Question(
        number=2,
        text='같은 공통 발문',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    standalone = Question(
        number=3,
        text='단독 대체 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions(
        [second_order_child, first_order_child, standalone],
        sample_metadata,
    )

    with sqlite3.connect(repo.db_path) as conn:
        rows = conn.execute("""
            SELECT id, question_number, exam_subject_id
            FROM questions
            ORDER BY question_number ASC
        """).fetchall()
        exam_subject_id = rows[0][2]
        cursor = conn.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, group_type, shared_text
            ) VALUES (?, 2024, 1, 1, 'passage', ?)
            """,
            (exam_subject_id, '공통 지문 본문'),
        )
        group_id = cursor.lastrowid
        ids_by_number = {question_number: question_id for question_id, question_number, _ in rows}
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 2 WHERE id = ?",
            (group_id, ids_by_number[1]),
        )
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 1 WHERE id = ?",
            (group_id, ids_by_number[2]),
        )

    return ids_by_number


def _save_group_with_invalid_child(repo, sample_metadata):
    valid_group_child = Question(
        number=1,
        text='유효한 공통 하위 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    invalid_group_child = Question(
        number=2,
        text='정답 오류가 있는 공통 하위 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    standalone = Question(
        number=3,
        text='선택 가능한 단독 문제',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions(
        [valid_group_child, invalid_group_child, standalone],
        sample_metadata,
    )

    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE questions SET correct_answer = 5 WHERE question_number = 2")
        rows = conn.execute("""
            SELECT id, question_number, exam_subject_id
            FROM questions
            ORDER BY question_number ASC
        """).fetchall()
        exam_subject_id = rows[0][2]
        cursor = conn.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, group_type, shared_text
            ) VALUES (?, 2024, 1, 1, 'passage', ?)
            """,
            (exam_subject_id, '공통 지문 본문'),
        )
        group_id = cursor.lastrowid
        ids_by_number = {question_number: question_id for question_id, question_number, _ in rows}
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 1 WHERE id = ?",
            (group_id, ids_by_number[1]),
        )
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 2 WHERE id = ?",
            (group_id, ids_by_number[2]),
        )

    return ids_by_number


def _save_invalid_then_valid_duplicate_groups(repo, sample_metadata):
    invalid_group = Question(
        number=1,
        text='다음 중 옳은 것은?',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    valid_group = Question(
        number=2,
        text='다음 중 옳은 것은?',
        choices=_group_choice_set(),
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repo.save_questions([invalid_group, valid_group], sample_metadata)

    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE questions SET correct_answer = 5 WHERE question_number = 1")
        rows = conn.execute("""
            SELECT id, question_number, exam_subject_id
            FROM questions
            ORDER BY question_number ASC
        """).fetchall()
        exam_subject_id = rows[0][2]
        ids_by_number = {question_number: question_id for question_id, question_number, _ in rows}
        first_group_id = conn.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, group_type, shared_text
            ) VALUES (?, 2024, 1, 1, 'passage', ?)
            """,
            (exam_subject_id, '같은 지문'),
        ).lastrowid
        second_group_id = conn.execute(
            """
            INSERT INTO question_groups (
                exam_subject_id, year, session, group_number, group_type, shared_text
            ) VALUES (?, 2024, 1, 2, 'passage', ?)
            """,
            (exam_subject_id, '같은 지문'),
        ).lastrowid
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 1 WHERE id = ?",
            (first_group_id, ids_by_number[1]),
        )
        conn.execute(
            "UPDATE questions SET group_id = ?, group_order = 1 WHERE id = ?",
            (second_group_id, ids_by_number[2]),
        )

    return ids_by_number


def test_mock_exam_create_rejects_invalid_subject(repo):
    generator = MockExamGenerator(repo)

    with pytest.raises(ValueError, match="Unknown subject code"):
        generator.create('3급기관사', ['not-a-subject'], count=1)

    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_exams").fetchone()[0] == 0


def test_mock_exam_create_rejects_insufficient_question_pool(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    generator = MockExamGenerator(repo)

    with pytest.raises(ValueError, match="Not enough questions available"):
        generator.create('3급기관사', ['engine1'], count=2)

    with sqlite3.connect(repo.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mock_exams").fetchone()[0] == 0


def test_mock_exam_random_pool_excludes_invalid_questions(repo, sample_metadata, sample_question):
    invalid_question = Question(
        number=2,
        text='정답 오류가 있는 문제',
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
    repo.save_questions([sample_question, invalid_question], sample_metadata)
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("UPDATE questions SET correct_answer = 5 WHERE question_number = 2")
    generator = MockExamGenerator(repo)

    with pytest.raises(ValueError, match="Not enough questions available"):
        generator.create('3급기관사', ['engine1'], count=2)

    mock_exam = generator.create('3급기관사', ['engine1'], count=1)

    with sqlite3.connect(repo.db_path) as conn:
        selected_texts = conn.execute("""
            SELECT q.question_text
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
        """, (mock_exam['id'],)).fetchall()

    assert selected_texts == [(sample_question.text,)]


def test_mock_exam_create_skips_duplicate_questions_across_subjects(
    repo,
    sample_metadata,
    monkeypatch,
):
    repeated_engine1 = Question(
        number=1,
        text='회차만 다른 반복 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='A'),
            Choice(number=2, symbol='㉯', text='B'),
            Choice(number=3, symbol='㉴', text='C'),
            Choice(number=4, symbol='㉵', text='D'),
        ],
        correct_answer=1,
        subject_name='기관1',
        year=2024,
        session=1,
        exam_type='3급기관사',
    )
    repeated_engine2 = Question(
        number=1,
        text='회차만 다른 반복 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='A'),
            Choice(number=2, symbol='㉯', text='B'),
            Choice(number=3, symbol='㉴', text='C'),
            Choice(number=4, symbol='㉵', text='D'),
        ],
        correct_answer=1,
        subject_name='기관2',
        year=2025,
        session=2,
        exam_type='3급기관사',
    )
    fallback_engine2 = Question(
        number=2,
        text='대체 가능한 기관2 문제',
        choices=[
            Choice(number=1, symbol='㉮', text='A'),
            Choice(number=2, symbol='㉯', text='B'),
            Choice(number=3, symbol='㉴', text='C'),
            Choice(number=4, symbol='㉵', text='D'),
        ],
        correct_answer=1,
        subject_name='기관2',
        year=2025,
        session=2,
        exam_type='3급기관사',
    )
    repo.save_questions(
        [repeated_engine1, repeated_engine2, fallback_engine2],
        sample_metadata,
    )
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )
    generator = MockExamGenerator(repo)

    mock_exam = generator.create('3급기관사', ['engine1', 'engine2'], count=1)

    with sqlite3.connect(repo.db_path) as conn:
        selected_texts = conn.execute("""
            SELECT q.question_text
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
            ORDER BY meq.display_order
        """, (mock_exam['id'],)).fetchall()

    assert selected_texts == [
        ('회차만 다른 반복 문제',),
        ('대체 가능한 기관2 문제',),
    ]


def test_mock_exam_create_inserts_grouped_questions_contiguously_in_group_order(
    repo,
    sample_metadata,
    monkeypatch,
):
    ids_by_number = _save_grouped_questions(repo, sample_metadata)
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )
    generator = MockExamGenerator(repo)

    mock_exam = generator.create('3급기관사', ['engine1'], count=2)

    with sqlite3.connect(repo.db_path) as conn:
        selected = conn.execute("""
            SELECT q.id, q.group_order, meq.display_order
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
            ORDER BY meq.display_order ASC
        """, (mock_exam['id'],)).fetchall()

    assert selected == [
        (ids_by_number[2], 1, 1),
        (ids_by_number[1], 2, 2),
    ]


def test_mock_exam_create_preserves_duplicate_text_children_inside_selected_group(
    repo,
    sample_metadata,
    monkeypatch,
):
    ids_by_number = _save_duplicate_text_grouped_questions(repo, sample_metadata)
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )

    mock_exam = MockExamGenerator(repo).create('3급기관사', ['engine1'], count=2)

    with sqlite3.connect(repo.db_path) as conn:
        selected = conn.execute("""
            SELECT q.id, q.group_order, q.question_text, meq.display_order
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
            ORDER BY meq.display_order ASC
        """, (mock_exam['id'],)).fetchall()

    assert selected == [
        (ids_by_number[2], 1, '같은 공통 발문', 1),
        (ids_by_number[1], 2, '같은 공통 발문', 2),
    ]


def test_mock_exam_create_excludes_entire_group_when_any_child_is_invalid(
    repo,
    sample_metadata,
    monkeypatch,
):
    ids_by_number = _save_group_with_invalid_child(repo, sample_metadata)
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )

    mock_exam = MockExamGenerator(repo).create('3급기관사', ['engine1'], count=1)

    with sqlite3.connect(repo.db_path) as conn:
        selected = conn.execute("""
            SELECT q.id, q.question_text, q.group_id
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
            ORDER BY meq.display_order ASC
        """, (mock_exam['id'],)).fetchall()

    assert selected == [(ids_by_number[3], '선택 가능한 단독 문제', None)]


def test_mock_exam_filters_invalid_duplicate_group_before_dedupe(
    repo,
    sample_metadata,
    monkeypatch,
):
    ids_by_number = _save_invalid_then_valid_duplicate_groups(repo, sample_metadata)
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )

    mock_exam = MockExamGenerator(repo).create('3급기관사', ['engine1'], count=1)

    with sqlite3.connect(repo.db_path) as conn:
        selected = conn.execute("""
            SELECT q.id, q.correct_answer
            FROM mock_exam_questions meq
            JOIN questions q ON q.id = meq.question_id
            WHERE meq.mock_exam_id = ?
            ORDER BY meq.display_order ASC
        """, (mock_exam['id'],)).fetchall()

    assert selected == [(ids_by_number[2], 1)]


def test_cli_quiz_runner_records_overall_and_subject_results(
    repo,
    sample_metadata,
    sample_question,
    monkeypatch,
):
    repo.save_questions([sample_question], sample_metadata)
    generator = MockExamGenerator(repo)
    mock_exam = generator.create('3급기관사', ['engine1'], count=1)

    monkeypatch.setattr(click, 'prompt', lambda *_args, **_kwargs: 2)
    monkeypatch.setattr('src.quiz.runner.time.sleep', lambda _seconds: None)

    result = CLIQuizRunner(repo).run(mock_exam['id'])

    assert result['correct'] == 1
    assert result['total'] == 1
    assert result['score'] == 100.0

    with sqlite3.connect(repo.db_path) as conn:
        rows = conn.execute("""
            SELECT exam_subject_id, total_questions, correct_count, score
            FROM exam_results
            WHERE mock_exam_id = ?
            ORDER BY exam_subject_id IS NULL DESC, exam_subject_id ASC
        """, (mock_exam['id'],)).fetchall()

    assert rows[0] == (None, 1, 1, 100.0)
    assert rows[1][0] is not None
    assert rows[1][1:] == (1, 1, 100.0)


def test_cli_quiz_runner_prints_shared_passage_once_for_contiguous_group(
    repo,
    sample_metadata,
    monkeypatch,
):
    _save_grouped_questions(repo, sample_metadata, group_id_override=0)
    monkeypatch.setattr(
        'src.quiz.generator.random.sample',
        lambda population, count: list(population)[:count],
    )
    mock_exam = MockExamGenerator(repo).create('3급기관사', ['engine1'], count=2)
    answers = iter([1, 1])
    output = []

    monkeypatch.setattr(click, 'prompt', lambda *_args, **_kwargs: next(answers))
    monkeypatch.setattr(click, 'echo', lambda message='', **_kwargs: output.append(str(message)))
    monkeypatch.setattr('src.quiz.runner.time.sleep', lambda _seconds: None)

    result = CLIQuizRunner(repo).run(mock_exam['id'])

    rendered = "\n".join(output)
    assert result['total'] == 2
    assert rendered.count('[공통지문]') == 1
    assert rendered.count('공통 지문 본문') == 1
