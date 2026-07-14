from pathlib import Path

from src.database.selection import (
    dedupe_questions_by_content,
    filter_random_eligible_questions,
    question_content_key,
    select_group_aware_questions,
)
from src.database.repository import ExamRepository
from src.database.validator import QuestionValidator
from PIL import Image
import pytest


def test_dedupe_questions_by_content_keeps_one_copy_of_same_problem():
    questions = [
        {
            'id': 1,
            'question_text': ' 같은 문제인가? ',
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        {
            'id': 2,
            'question_text': '같은   문제인가?',
            'year': 2025,
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
        {
            'id': 3,
            'question_text': '다른 문제인가?',
            'choices': [
                {'choice_number': 1, 'choice_text': 'A'},
                {'choice_number': 2, 'choice_text': 'B'},
                {'choice_number': 3, 'choice_text': 'C'},
                {'choice_number': 4, 'choice_text': 'D'},
            ],
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1, 3]


def test_question_content_key_uses_normalized_prompt_and_choice_fingerprint():
    base = {
        'question_text': '다음 중 옳은 것은?',
        'choices': [
            {'choice_number': 1, 'choice_text': '첫 번째 설명'},
            {'choice_number': 2, 'choice_text': '두 번째 설명'},
        ],
    }
    reordered = {
        'question_text': ' 다음 중 옳은 것은? ',
        'choices': list(reversed(base['choices'])),
    }
    different_choices = {
        'question_text': '다음 중 옳은 것은?',
        'choices': [
            {'choice_number': 1, 'choice_text': '전혀 다른 설명'},
            {'choice_number': 2, 'choice_text': '또 다른 설명'},
        ],
    }

    assert question_content_key(base) == question_content_key(reordered)
    assert question_content_key(base) != question_content_key(different_choices)


def test_dedupe_questions_by_content_removes_high_confidence_wording_variant():
    choices = [
        {'choice_number': 1, 'choice_text': '폴리염화비닐(PVCs)'},
        {'choice_number': 2, 'choice_text': '폴리염화비페닐(PCBs)'},
        {'choice_number': 3, 'choice_text': '배기가스 세정장치의 잔류물'},
        {
            'choice_number': 4,
            'choice_text': '할로겐 화합물질을 함유하고 있는 정제된 석유제품',
        },
    ]
    questions = [
        {
            'id': 1374,
            'question_text': (
                'MARPOL 협약 및 개정규정상 IMO 형식승인증서를 발급받은 '
                '선내 소각기에서 소각할 수 있는 물질은?'
            ),
            'choices': choices,
        },
        {
            'id': 7622,
            'question_text': (
                'MARPOL 협약 및 개정규정의 부속서 Ⅵ에서 IMO 형식승인증서를 '
                '발급받은 선내 소각기에서 소각할 수 있는 물질은?'
            ),
            'choices': choices,
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1374]


def test_dedupe_questions_by_content_keeps_similar_prompt_with_different_choices():
    questions = [
        {
            'id': 1,
            'question_text': '선박안전법령상 정기검사의 유효기간 연장 기준으로 옳은 것은?',
            'choices': [
                {'choice_number': 1, 'choice_text': '1개월'},
                {'choice_number': 2, 'choice_text': '2개월'},
                {'choice_number': 3, 'choice_text': '3개월'},
                {'choice_number': 4, 'choice_text': '4개월'},
            ],
        },
        {
            'id': 2,
            'question_text': '선박안전법령상 정기검사의 유효기간 연장 기준으로 옳지 않은 것은?',
            'choices': [
                {'choice_number': 1, 'choice_text': '검사 면제'},
                {'choice_number': 2, 'choice_text': '검사 생략'},
                {'choice_number': 3, 'choice_text': '검사 정지'},
                {'choice_number': 4, 'choice_text': '검사 취소'},
            ],
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1, 2]


def test_dedupe_questions_by_content_keeps_opposite_question_polarity():
    choices = [
        {'choice_number': 1, 'choice_text': '안전밸브를 점검한다.'},
        {'choice_number': 2, 'choice_text': '압력계를 점검한다.'},
        {'choice_number': 3, 'choice_text': '수면계를 점검한다.'},
        {'choice_number': 4, 'choice_text': '연료밸브를 점검한다.'},
    ]
    questions = [
        {
            'id': 1,
            'question_text': '보일러 운전 전 안전 점검사항에 관한 설명으로 옳은 것은?',
            'choices': choices,
        },
        {
            'id': 2,
            'question_text': '보일러 운전 전 안전 점검사항에 관한 설명으로 옳지 않은 것은?',
            'choices': choices,
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1, 2]


def test_dedupe_questions_by_content_keeps_different_numeric_conditions():
    choices = [
        {'choice_number': 1, 'choice_text': '10[C]'},
        {'choice_number': 2, 'choice_text': '20[C]'},
        {'choice_number': 3, 'choice_text': '30[C]'},
        {'choice_number': 4, 'choice_text': '40[C]'},
    ]
    questions = [
        {
            'id': 1,
            'question_text': '10[F]의 콘덴서에 100[V]를 가할 때 충전되는 전기량은?',
            'choices': choices,
        },
        {
            'id': 2,
            'question_text': '20[F]의 콘덴서에 100[V]를 가할 때 충전되는 전기량은?',
            'choices': choices,
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1, 2]


def test_fuzzy_content_key_excludes_wording_variant_from_later_subject_pool():
    from src.database import selection

    choices = [
        {'choice_number': 1, 'choice_text': '폴리염화비닐(PVCs)'},
        {'choice_number': 2, 'choice_text': '폴리염화비페닐(PCBs)'},
        {'choice_number': 3, 'choice_text': '배기가스 세정장치의 잔류물'},
        {'choice_number': 4, 'choice_text': '정제된 석유제품'},
    ]
    selected = [{
        'id': 1,
        'question_text': (
            'MARPOL 협약 및 개정규정상 IMO 형식승인증서를 발급받은 '
            '선내 소각기에서 소각할 수 있는 물질은?'
        ),
        'choices': choices,
    }]
    later_pool = [{
        'id': 2,
        'question_text': (
            'MARPOL 협약 및 개정규정의 부속서 Ⅵ에서 IMO 형식승인증서를 '
            '발급받은 선내 소각기에서 소각할 수 있는 물질은?'
        ),
        'choices': choices,
    }]

    selected_keys = selection.selection_content_keys(selected)

    assert selection.count_group_aware_questions(
        later_pool,
        excluded_keys=selected_keys,
    ) == 0


@pytest.mark.parametrize('question_ids', [(1374, 7622), (7866, 469)])
def test_actual_exam_database_wording_variants_are_deduped(question_ids):
    db_path = Path(__file__).resolve().parents[1] / 'data' / 'exam_bank.db'
    if not db_path.exists():
        pytest.skip('Local application exam database is not available')

    repository = ExamRepository(str(db_path))
    questions = [repository.get_question(question_id) for question_id in question_ids]
    if any(question is None for question in questions):
        pytest.skip(f'Actual DB regression records are unavailable: {question_ids}')

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [question_ids[0]]


def test_group_aware_dedupe_keeps_duplicate_text_children_inside_same_group():
    from src.database import selection

    questions = [
        {
            'id': 1,
            'question_text': '같은 공통 발문',
            'group_id': 10,
            'group_order': 1,
            'group_shared_text': '공통 지문',
        },
        {
            'id': 2,
            'question_text': '같은 공통 발문',
            'group_id': 10,
            'group_order': 2,
            'group_shared_text': '공통 지문',
        },
        {'id': 3, 'question_text': '같은 공통 발문', 'question_number': 3},
    ]

    deduped = selection.dedupe_group_aware_questions_by_content(questions)

    assert [question['id'] for question in deduped] == [1, 2, 3]


def test_group_aware_dedupe_keeps_distinct_groups_with_same_child_prompts():
    from src.database import selection

    questions = [
        {
            'id': 1,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 10,
            'group_order': 1,
            'group_shared_text': '첫 번째 지문',
        },
        {
            'id': 2,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 20,
            'group_order': 1,
            'group_shared_text': '두 번째 지문',
        },
    ]

    deduped = selection.dedupe_group_aware_questions_by_content(questions)

    assert [question['id'] for question in deduped] == [1, 2]


def test_group_aware_dedupe_removes_duplicate_group_fingerprint():
    from src.database import selection

    questions = [
        {
            'id': 1,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 10,
            'group_order': 1,
            'group_shared_text': '같은 지문',
        },
        {
            'id': 2,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 20,
            'group_order': 1,
            'group_shared_text': '같은 지문',
        },
    ]

    deduped = selection.dedupe_group_aware_questions_by_content(questions)

    assert [question['id'] for question in deduped] == [1]


def test_group_aware_excluded_keys_use_group_fingerprint_not_child_prompt_only():
    from src.database import selection

    selected_group = [
        {
            'id': 1,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 10,
            'group_order': 1,
            'group_shared_text': '첫 번째 지문',
        },
    ]
    distinct_group = [
        {
            'id': 2,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 20,
            'group_order': 1,
            'group_shared_text': '두 번째 지문',
        },
    ]
    duplicate_group = [
        {
            'id': 3,
            'question_text': '다음 중 옳은 것은?',
            'group_id': 30,
            'group_order': 1,
            'group_shared_text': '첫 번째 지문',
        },
    ]

    selected_keys = selection.selection_content_keys(selected_group)

    assert selection.count_group_aware_questions(
        distinct_group,
        excluded_keys=selected_keys,
    ) == 1
    assert selection.count_group_aware_questions(
        duplicate_group,
        excluded_keys=selected_keys,
    ) == 0


def test_dedupe_questions_by_content_ignores_minor_ocr_and_symbol_noise():
    questions = [
        {
            'id': 1,
            'question_text': '도통(on)상태에 있는 SCR을 차단(off)하기 위한 방법으로 옳은 것은?',
            'choices': [
                {'choice_number': 1, 'choice_text': '게이트 전류를 차단시킨다.'},
                {'choice_number': 2, 'choice_text': '게이트에 역방향 바이어스를 인가시킨다.'},
                {'choice_number': 3, 'choice_text': '양극의 전위를 게이트 전위보다 더 높인다.'},
                {'choice_number': 4, 'choice_text': '음극의 전위를 양극보다 더 높인다.'},
            ],
        },
        {
            'id': 2,
            'question_text': '도통(on)상태에 있는 SCR을 차단(off)하기 위한 방법으로 옳은 것은?',
            'choices': [
                {'choice_number': 1, 'choice_text': '게이트 전류를 차단시킨다.'},
                {'choice_number': 2, 'choice_text': '게이트에 역방향 바이어스를 인가시킨다.'},
                {'choice_number': 3, 'choice_text': '양극(A)의 전위를 게이트(G) 전위보다 더 높인다.'},
                {'choice_number': 4, 'choice_text': '음극(K)의 전위를 양극(A) 보다 더 높인다.'},
            ],
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1]


def test_dedupe_questions_by_content_treats_same_prompt_image_records_as_duplicates(tmp_path):
    first_image = tmp_path / 'first.png'
    second_image = tmp_path / 'second.png'
    Image.new('RGB', (2, 2), 'white').save(first_image)
    Image.new('RGB', (2, 2), 'black').save(second_image)
    questions = [
        {
            'id': 1,
            'question_text': '다음 그림과 같은 파형의 주파수는?',
            'image_path': str(first_image),
            'choices': [{'choice_number': 1, 'choice_text': '4[Hz]'}],
        },
        {
            'id': 2,
            'question_text': '다음 그림과 같은 파형의 주파수는?',
            'image_path': str(second_image),
            'choices': [{'choice_number': 1, 'choice_text': '4[Hz]'}],
        },
    ]

    assert [q['id'] for q in dedupe_questions_by_content(questions)] == [1]


def test_filter_random_eligible_questions_excludes_blocking_errors(repo):
    validator = QuestionValidator(repo)
    valid = {
        'id': 1,
        'question_text': '정상 문제',
        'session': 1,
        'question_number': 1,
        'correct_answer': 1,
        'has_image': 0,
        'image_path': None,
        'tags': '#3급기관사 #기관1',
        'exam_name': '3급기관사',
        'subject_name': '기관1',
        'choices': [
            {'choice_number': 1, 'choice_symbol': '㉮', 'choice_text': 'A'},
            {'choice_number': 2, 'choice_symbol': '㉯', 'choice_text': 'B'},
            {'choice_number': 3, 'choice_symbol': '㉴', 'choice_text': 'C'},
            {'choice_number': 4, 'choice_symbol': '㉵', 'choice_text': 'D'},
        ],
    }
    invalid = dict(valid, id=2, correct_answer=5)

    assert [q['id'] for q in filter_random_eligible_questions([invalid, valid], validator)] == [1]


def test_group_aware_random_eligibility_drops_entire_group_when_one_child_is_invalid():
    from src.database import selection

    class Validator:
        def is_random_eligible(self, question):
            return question['id'] != 2

    questions = [
        {'id': 1, 'question_text': 'valid grouped child', 'group_id': 10, 'group_order': 1},
        {'id': 2, 'question_text': 'invalid grouped child', 'group_id': 10, 'group_order': 2},
        {'id': 3, 'question_text': 'valid standalone'},
    ]

    eligible = selection.filter_group_aware_random_eligible_questions(
        questions,
        Validator(),
    )

    assert [question['id'] for question in eligible] == [3]


class _FirstSampleRng:
    def sample(self, population, count):
        return list(population)[:count]


def test_select_group_aware_questions_keeps_group_atomic_and_orders_children():
    questions = [
        {'id': 1, 'question_text': 'group child 2', 'group_id': 10, 'group_order': 2, 'question_number': 7},
        {'id': 2, 'question_text': 'group child 1', 'group_id': 10, 'group_order': 1, 'question_number': 6},
        {'id': 3, 'question_text': 'standalone', 'question_number': 8},
    ]

    selected = select_group_aware_questions(questions, 2, rng=_FirstSampleRng())

    assert [question['id'] for question in selected] == [2, 1]


def test_select_group_aware_questions_skips_oversized_group_and_fills_with_other_units():
    questions = [
        {'id': 1, 'question_text': 'group child 1', 'group_id': 10, 'group_order': 1, 'question_number': 1},
        {'id': 2, 'question_text': 'group child 2', 'group_id': 10, 'group_order': 2, 'question_number': 2},
        {'id': 3, 'question_text': 'group child 3', 'group_id': 10, 'group_order': 3, 'question_number': 3},
        {'id': 4, 'question_text': 'single 1', 'question_number': 4},
        {'id': 5, 'question_text': 'single 2', 'question_number': 5},
    ]

    selected = select_group_aware_questions(questions, 2, rng=_FirstSampleRng())

    assert [question['id'] for question in selected] == [4, 5]


def test_select_group_aware_questions_raises_when_strict_fill_is_impossible():
    questions = [
        {'id': 1, 'question_text': 'group child 1', 'group_id': 10, 'group_order': 1},
        {'id': 2, 'question_text': 'group child 2', 'group_id': 10, 'group_order': 2},
    ]

    with pytest.raises(ValueError, match="Not enough questions"):
        select_group_aware_questions(questions, 1, rng=_FirstSampleRng())
