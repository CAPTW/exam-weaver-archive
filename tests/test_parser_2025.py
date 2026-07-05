import json
from types import SimpleNamespace

from src.parser.extractor import ImageData, TableData
from src.parser.answer import AnswerParser
from src.parser.main import ExamPDFParser
from src.parser.merger import DataMerger
from src.parser.metadata import ExamMetadata
from src.parser.patterns import EXAM_SUBJECT_ORDER
from src.parser.question import Question, QuestionParser


def test_4th_engine_exam_has_subject_order_for_answer_matching():
    assert EXAM_SUBJECT_ORDER['4급기관사'] == ['기관1', '기관2', '기관3', '직무일반', '영어']


def test_navigation_exam_subject_orders_cover_all_grades():
    assert EXAM_SUBJECT_ORDER['1급항해사(상선)'] == ['항해', '운용', '법규', '영어', '상선전문']
    assert EXAM_SUBJECT_ORDER['4급항해사(상선)'] == ['항해', '운용', '법규', '영어', '상선전문']
    assert EXAM_SUBJECT_ORDER['6급항해사(상선)'] == ['항해', '운용', '법규', '상선전문']
    assert EXAM_SUBJECT_ORDER['5급항해사(국내 상선)'] == ['항해', '운용', '법규', '상선전문']


def test_small_vessel_subject_order_includes_engine():
    assert EXAM_SUBJECT_ORDER['소형선박조종사'] == ['항해', '운용', '법규', '기관']


def test_answer_parser_detects_compact_engine_header():
    text = '<4급기관사 답안>  ◎ 2025년 제1회 정기시험 기관1 가 나 사 아'

    assert AnswerParser()._extract_exam_type(text) == '4급기관사'


def test_answer_parser_detects_small_vessel_operator_header():
    assert AnswerParser()._extract_exam_type('<소형선박조종사 답안>') == '소형선박조종사'


def test_answer_parser_detects_compact_old_engine_header():
    assert AnswerParser()._extract_exam_type('< 3급 기관사답안() >') == '3급기관사'


def test_answer_parser_detects_compact_old_navigation_merchant_header():
    assert AnswerParser()._extract_exam_type('< 3급 항해사상선답안() >') == '3급항해사(상선)'


def test_answer_parser_filters_to_requested_exam_type():
    pages = [
        SimpleNamespace(
            text='<1급기관사 답안> ◎ 2025년 제1회 정기시험 '
                 '1 2 3 4 5 기관1 가 가 가 가 가 가 가 가 가 가 '
                 '가 가 가 가 가 가 가 가 가 가 가 가 가 가 가'
        ),
        SimpleNamespace(
            text='<4급기관사 답안> ◎ 2025년 제1회 정기시험 '
                 '1 2 3 4 5 기관1 나 나 나 나 나 나 나 나 나 나 '
                 '나 나 나 나 나 나 나 나 나 나 나 나 나 나 나'
        ),
    ]

    answers = AnswerParser().parse_answers(pages, exam_type='4급기관사', year_hint=2025)

    assert answers[(2025, 1, '4급기관사', '기관1')] == [2] * 25
    assert (2025, 1, '1급기관사', '기관1') not in answers


def test_answer_parser_combines_split_multi_session_grid_rows():
    pages = [
        SimpleNamespace(
            text='<4급기관사 답안>\n'
                 '◎ 2025년 제1회 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '기관1 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '기관2 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '기관3 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '직무일반 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '영어 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '◎ 2025년 제2회 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '기관1 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '기관2 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '기관3 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '직무일반 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '영어 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '13 14 15 16 17 18 19 20 21 22 23 24 25\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '사 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '나 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '13 14 15 16 17 18 19 20 21 22 23 24 25\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '사 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '나 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가'
        )
    ]

    answers = AnswerParser().parse_answers(pages, exam_type='4급기관사', year_hint=2025)

    assert answers[(2025, 1, '4급기관사', '기관1')] == [1] * 12 + [4] * 13
    assert answers[(2025, 1, '4급기관사', '기관2')] == [2] * 12 + [3] * 13
    assert answers[(2025, 2, '4급기관사', '기관1')] == [2] * 12 + [1] * 13
    assert answers[(2025, 2, '4급기관사', '영어')] == [2] * 12 + [1] * 13


def test_answer_parser_combines_old_compact_session_grid_rows():
    pages = [
        SimpleNamespace(
            text='< 3급 기관사답안() >\n'
                 '◎ 2021년 제회1 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '기관1 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '기관2 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '기관3 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '직무일반 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '영어 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '◎ 2021년 제회2 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '기관1 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '기관2 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '기관3 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '직무일반 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '영어 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '13 14 15 16 17 18 19 20 21 22 23 24 25\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '사 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '나 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '13 14 15 16 17 18 19 20 21 22 23 24 25\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '사 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '나 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가'
        ),
        SimpleNamespace(
            text='< 4급 기관사답안() >\n'
                 '◎ 2021년 제회1 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '기관1 사 사 사 사 사 사 사 사 사 사 사 사\n'
        )
    ]

    answers = AnswerParser().parse_answers(pages, exam_type='3급기관사', year_hint=2021)

    assert answers[(2021, 1, '3급기관사', '기관1')] == [1] * 12 + [4] * 13
    assert answers[(2021, 2, '3급기관사', '기관1')] == [2] * 12 + [1] * 13
    assert (2021, 1, '4급기관사', '기관1') not in answers


def test_answer_parser_reads_small_vessel_engine_subject():
    pages = [
        SimpleNamespace(
            text='<소형선박조종사 답안>\n'
                 '◎ 2025년 제1회 정기시험\n'
                 '1 2 3 4 5 6 7 8 9 10 11 12\n'
                 '항해 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '운용 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '법규 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '기관 아 아 아 아 아 아 아 아 아 아 아 아\n'
                 '13 14 15 16 17 18 19 20 21 22 23 24 25\n'
                 '가 가 가 가 가 가 가 가 가 가 가 가 가\n'
                 '나 나 나 나 나 나 나 나 나 나 나 나 나\n'
                 '사 사 사 사 사 사 사 사 사 사 사 사 사\n'
                 '아 아 아 아 아 아 아 아 아 아 아 아 아'
        )
    ]

    answers = AnswerParser().parse_answers(pages, exam_type='소형선박조종사', year_hint=2025)

    assert answers[(2025, 1, '소형선박조종사', '기관')] == [4] * 25


def test_main_parser_collects_answers_for_each_exam_type():
    class FakeAnswerParser:
        def __init__(self):
            self.calls = []

        def parse_answers(self, pages, exam_type=None, year_hint=None):
            self.calls.append((exam_type, year_hint))
            return {(year_hint, 1, exam_type, '항해'): [1] * 25}

    parser = ExamPDFParser()
    fake_answer_parser = FakeAnswerParser()
    parser.answer_parser = fake_answer_parser
    metadata_blocks = [
        (0, ExamMetadata(2025, 1, '3급항해사(상선)')),
        (10, ExamMetadata(2025, 2, '3급항해사(상선)')),
        (20, ExamMetadata(2025, 1, '3급항해사(어선)')),
    ]

    answers = parser._parse_answers_for_metadata_blocks([], metadata_blocks)

    assert fake_answer_parser.calls == [
        ('3급항해사(상선)', 2025),
        ('3급항해사(어선)', 2025),
    ]
    assert (2025, 1, '3급항해사(상선)', '항해') in answers
    assert (2025, 1, '3급항해사(어선)', '항해') in answers


def test_merger_reports_duplicate_question_numbers():
    questions = [
        Question(number=1, text='a', correct_answer=1, subject_name='기관1', year=2025, session=1, exam_type='4급기관사'),
        Question(number=1, text='b', correct_answer=2, subject_name='기관1', year=2025, session=1, exam_type='4급기관사'),
    ]

    result = DataMerger().validate(questions)

    assert result.is_valid is False
    assert any('문제 번호 중복' in error and '1' in error for error in result.errors)


def test_question_parser_splits_choice_answer_joined_to_single_digit_question_number():
    parser = QuestionParser('4급기관사')
    text = (
        '8.역률은?㉮0.5㉯0.6㉴0.8㉵1'
        '9.도선의 단면을 이동한 전하는?㉮0.2㉯0.4㉴0.6㉵0.8'
        '10.축전지 연결은?㉮12㉯24㉴36㉵48'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [8, 9, 10]
    assert questions[0].choices[3].text == '1'


def test_question_parser_splits_choice_answer_joined_to_question_number_after_two_digit_choice():
    parser = QuestionParser('4급기관사')
    text = (
        '2.압축비는?㉮17㉯18㉴19㉵20'
        '3.메인 베어링 발열 원인은?㉮과부하㉯공급부족㉴어긋남㉵점도'
        '4.피스톤 상사점 설명은?㉮분사㉯소기공㉴배기밸브㉵안전밸브'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [2, 3, 4]
    assert questions[0].choices[3].text == '20'


def test_question_parser_accepts_question_text_starting_with_number():
    parser = QuestionParser('4급기관사')
    text = (
        '7.전원의 정격전압은?㉮63.6[V]㉯100[V]㉴141[V]㉵157[V]'
        '8.3상 교류를 Y결선하면?㉮1배㉯루트3배㉴2배㉵3배'
        '9.도선의 전류는?㉮0.2[A]㉯0.4[A]㉴0.6[A]㉵0.8[A]'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [7, 8, 9]


def test_question_parser_keeps_two_digit_question_number_before_numeric_text():
    parser = QuestionParser('4급기관사')
    text = (
        '13.교류 배전반 계기는?㉮전압계㉯전류계㉴역률계㉵기중 차단기'
        '14.3상 유도전동기 설명은?㉮A㉯B㉴C㉵D'
        '15.3상 동기발전기 설명은?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [13, 14, 15]


def test_question_parser_splits_spaced_question_number_before_numeric_text():
    parser = QuestionParser('4급기관사')
    text = (
        '6.전기자 반작용은?㉮전자력㉯유도 기전력㉴정류 작용㉵전기자 반작용    '
        '7.3상 교류회로에서 상전압은?㉮1배㉯3배㉴루트3배㉵1/루트3배'
        '8.콘덴서 단위는?㉮헨리㉯패럿㉴쿨롱㉵볼트'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [6, 7, 8]


def test_question_parser_keeps_quoted_sentence_ending_number_inside_question():
    parser = QuestionParser('4급기관사')
    text = (
        '10.앞 문제는?㉮A㉯B㉴C㉵D'
        '11."Adjusted fuel handle notch of M/E to 7."\n'
        '친 단어와 뜻이 같은 것은?㉮Attached㉯Regulated㉴Increased㉵Decreased'
        '12.다음 문제는?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [10, 11, 12]
    assert 'to 7' in questions[1].text


def test_question_parser_keeps_decimal_choice_from_becoming_question():
    parser = QuestionParser('4급기관사')
    text = (
        '11.전열기에 전원을 연결하면 전열기에 450[W] 100[V]\n'
        '흐르는 전류는?㉮ 3.5[A] ㉯ 4.5[A] ㉴ 6.5[A] ㉵ 7.5[A]\n'
        '12.동기발전기를 병렬투입하기 직전 서로 일치시켜야 하는 것은?'
        '㉮주파수와 유효전력㉯역률과 주파수㉴주파수와 위상㉵위상과 역률'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [11, 12]
    assert questions[0].choices[3].text == '7.5[A]'


def test_question_parser_keeps_decimal_range_choice_from_becoming_question():
    parser = QuestionParser('4급기관사')
    text = (
        '23.시동공기의 압력은?'
        '㉮0.2 ~ 1.0 bar㉯25 ~ 30 MPa㉴2.5 ~ 3.0 bar㉵2.5 ~ 3.0 MPa'
        '24.댐퍼의 역할은?㉮유량조절㉯분무㉴점화㉵냉각'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [23, 24]
    assert questions[0].choices[3].text == '2.5 ~ 3.0 MPa'


def test_question_parser_splits_joined_single_digit_question_after_numeric_choice():
    parser = QuestionParser('3급항해사(상선)')
    text = (
        '7.거리 문제는?㉮50, 50㉯50, 150㉴150, 50㉵150, 150'
        '8.기준면 설명은?㉮A㉯B㉴C㉵D'
        '9.다음 해도 도식은?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [7, 8, 9]
    assert questions[0].choices[3].text == '150, 150'
    assert questions[1].text == '기준면 설명은?'


def test_question_parser_splits_joined_question_after_unit_suffix():
    parser = QuestionParser('3급항해사(상선)')
    text = (
        '3.배수량 문제는?㉮약 4,902m3㉯약 5,000m3㉴약 5,020m3㉵약 5,100m3'
        '4.선미트림 문제는?㉮약 500톤㉯약 750톤㉴약 1,000톤㉵약 1,250톤'
        '5.전단력 문제는?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [3, 4, 5]
    assert questions[0].choices[3].text == '약 5,100m3'
    assert questions[1].text == '선미트림 문제는?'


def test_question_parser_splits_joined_twenty_five_after_decimal_choice():
    parser = QuestionParser('3급항해사(상선)')
    text = (
        '24.황산화물 기준은?㉮0.1㉯0.2㉴0.5㉵1.0'
        '25.윌리암슨 턴 설명은?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [24, 25]
    assert questions[0].choices[3].text == '1.0'
    assert questions[1].choices[0].text == 'A'


def test_question_parser_does_not_treat_spaced_decimal_as_question_start():
    parser = QuestionParser('3급항해사(상선)')
    text = (
        '19.앞지르기 설명은?㉮A㉯B㉴C㉵정횡 후 22. 5도를 넘는 후방이다.'
        '20.횡단 상태 설명은?㉮A㉯B㉴C㉵D'
        '21.범선 설명은?㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(text, 1, [])

    assert [q.number for q in questions] == [19, 20, 21]
    assert '22. 5도' in questions[0].choices[3].text


def test_question_gap_recovery_skips_unknown_subjects():
    parser = QuestionParser('4급기관사')
    questions = [Question(number=1, text='분리 오류', subject_name=None)]
    raw_text = (
        '1.분리 오류 ㉮A㉯B㉴C㉵D '
        '2.과목이 없는 상태에서는 이 문항을 복구하면 안 된다. ㉮A㉯B㉴C㉵D'
    )

    recovered = parser._recover_missing_questions(questions, raw_text)

    assert recovered == questions


def test_question_parser_assigns_images_by_pdf_position_not_extraction_order(tmp_path):
    parser = QuestionParser('4급기관사')
    text = (
        '24.다음과 같은 소자의 명칭은?㉮A㉯B㉴C㉵D'
        '25.다음 문제는?㉮A㉯B㉴C㉵D'
        '1.일반 문제는?㉮A㉯B㉴C㉵D'
        '2.일반 문제는?㉮A㉯B㉴C㉵D'
        '3.다음 그림과 같은 밸브는?㉮A㉯B㉴C㉵D'
    )
    from PIL import Image, ImageDraw

    def make_image(name):
        path = tmp_path / name
        image = Image.new('RGB', (80, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 70, 70), outline='black', width=4)
        image.save(path)
        return str(path)

    footer = make_image('footer-logo.jpg')
    valve = make_image('valve.jpg')
    diode = make_image('diode.jpg')

    images = [
        ImageData(footer, (324, 998, 398, 1003)),
        ImageData(valve, (81, 797, 280, 915)),
        ImageData(diode, (153, 230, 216, 312)),
    ]

    questions = parser._parse_page(text, 7, [], images)

    by_number = {q.number: q for q in questions}
    assert by_number[24].image_path == diode
    assert by_number[3].image_path == valve


def test_question_parser_assigns_images_to_image_only_choices(tmp_path):
    parser = QuestionParser('4급기관사')
    text = '5.그림에 해당하는 부품을 순서대로 고른 것은?㉮ ㉯ ㉴ ㉵'
    from PIL import Image, ImageDraw

    def make_image(name):
        path = tmp_path / name
        image = Image.new('RGB', (80, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((10, 10, 70, 70), fill='black', width=4)
        image.save(path)
        return str(path)

    image_paths = [make_image(f'choice-{number}.jpg') for number in range(1, 5)]
    images = [
        ImageData(path, (70, 200 + idx * 80, 150, 260 + idx * 80))
        for idx, path in enumerate(image_paths)
    ]

    questions = parser._parse_page(text, 1, [], images)

    assert len(questions) == 1
    assert [choice.number for choice in questions[0].choices] == [1, 2, 3, 4]
    assert [choice.text for choice in questions[0].choices] == ['', '', '', '']
    assert [choice.image_path for choice in questions[0].choices] == image_paths
    assert questions[0].image_path is None
    assert questions[0].has_image is True


def test_question_parser_keeps_question_and_choice_image_order_separate(tmp_path):
    parser = QuestionParser('4급기관사')
    text = (
        '1.다음 그림과 같은 장치는?㉮A㉯B㉴C㉵D'
        '2.그림 선지를 고른 것은?㉮ ㉯ ㉴ ㉵'
    )
    from PIL import Image, ImageDraw

    def make_image(name):
        path = tmp_path / name
        image = Image.new('RGB', (80, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 70, 70), outline='black', width=4)
        image.save(path)
        return str(path)

    question_image = make_image('question.jpg')
    choice_images = [make_image(f'choice-{number}.jpg') for number in range(1, 5)]
    images = [
        ImageData(question_image, (70, 180, 150, 260)),
        ImageData(choice_images[0], (70, 420, 150, 480)),
        ImageData(choice_images[1], (180, 420, 260, 480)),
        ImageData(choice_images[2], (70, 500, 150, 560)),
        ImageData(choice_images[3], (180, 500, 260, 560)),
    ]

    questions = parser._parse_page(text, 1, [], images)

    assert questions[0].image_path == question_image
    assert [choice.image_path for choice in questions[1].choices] == choice_images


def test_question_parser_assigns_question_and_choice_images_in_same_question(tmp_path):
    parser = QuestionParser('4급기관사')
    text = '1.다음 그림과 같은 회로에서 출력 파형을 고른 것은?㉮ ㉯ ㉴ ㉵'
    from PIL import Image, ImageDraw

    def make_image(name):
        path = tmp_path / name
        image = Image.new('RGB', (80, 80), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 70, 70), outline='black', width=4)
        image.save(path)
        return str(path)

    question_image = make_image('question.jpg')
    choice_images = [make_image(f'choice-{number}.jpg') for number in range(1, 5)]
    images = [
        ImageData(question_image, (70, 180, 150, 260)),
        ImageData(choice_images[0], (70, 360, 150, 420)),
        ImageData(choice_images[1], (180, 360, 260, 420)),
        ImageData(choice_images[2], (70, 440, 150, 500)),
        ImageData(choice_images[3], (180, 440, 260, 500)),
    ]

    questions = parser._parse_page(text, 1, [], images)

    assert len(questions) == 1
    assert questions[0].image_path == question_image
    assert [choice.image_path for choice in questions[0].choices] == choice_images
    assert questions[0].has_image is True


def test_question_parser_attaches_underlined_text_format_to_question_and_choice():
    parser = QuestionParser('4급기관사')
    text = (
        '1. 밑줄 친 부분에 알맞은 것은?'
        '㉮정답㉯오답㉴오답㉵오답'
    )

    questions = parser._parse_page(
        text,
        1,
        [],
        underlined_texts=['밑줄', '정답'],
    )

    question_format = json.loads(questions[0].format_json)
    choice_format = json.loads(questions[0].choices[0].format_json)

    assert question_format['spans'] == [{'start': 0, 'end': 2, 'underline': True}]
    assert choice_format['spans'] == [{'start': 0, 'end': 2, 'underline': True}]


def test_question_parser_attaches_detected_table_format_to_matching_question():
    parser = QuestionParser('4급기관사')
    table = TableData(rows=[['구분', '값'], ['A', '10'], ['B', '20']])
    text = (
        '1. 다음 표를 보고 옳은 것은? 구분 값 A 10 B 20'
        '㉮A㉯B㉴C㉵D'
    )

    questions = parser._parse_page(
        text,
        1,
        [],
        tables=[table],
    )

    question_format = json.loads(questions[0].format_json)

    assert question_format['tables'] == [{'rows': [['구분', '값'], ['A', '10'], ['B', '20']]}]


def test_question_parser_converts_root_notation_to_latex_spans():
    parser = QuestionParser('4급기관사')
    text = (
        '1. GM 값은 ROOT(GM)인가?'
        '㉮ROOT(2)㉯√3㉴4㉵5'
    )

    questions = parser._parse_page(text, 1, [])

    question_format = json.loads(questions[0].format_json)
    first_choice_format = json.loads(questions[0].choices[0].format_json)
    second_choice_format = json.loads(questions[0].choices[1].format_json)

    assert questions[0].text == 'GM 값은 \\sqrt{GM}인가?'
    assert question_format['spans'] == [{'start': 6, 'end': 15, 'latex': '\\sqrt{GM}'}]
    assert questions[0].choices[0].text == '\\sqrt{2}'
    assert first_choice_format['spans'] == [{'start': 0, 'end': 8, 'latex': '\\sqrt{2}'}]
    assert questions[0].choices[1].text == '\\sqrt{3}'
    assert second_choice_format['spans'] == [{'start': 0, 'end': 8, 'latex': '\\sqrt{3}'}]


def test_question_parser_converts_unicode_power_formula_choices_to_latex_spans():
    parser = QuestionParser('3급기관사')
    text = (
        '1. 3상 교류 유효전력을 표시한 것으로 옳은 것은? '
        '(단, E는 선간전압, I는 선전류, θ는 위상각이다)'
        '㉮ P = √2 × E × I × cosθ'
        '㉯ P = √3 × E × I × cosθ'
        '㉴ P = √2 × E × I × sinθ'
        '㉵ P = √3 × E × I × sinθ'
    )

    questions = parser._parse_page(text, 1, [])

    expected = [
        'P=\\sqrt{2} \\times E \\times I \\times \\cos\\theta',
        'P=\\sqrt{3} \\times E \\times I \\times \\cos\\theta',
        'P=\\sqrt{2} \\times E \\times I \\times \\sin\\theta',
        'P=\\sqrt{3} \\times E \\times I \\times \\sin\\theta',
    ]

    assert questions[0].format_json is None
    assert [choice.text for choice in questions[0].choices] == expected
    for choice, latex in zip(questions[0].choices, expected):
        assert json.loads(choice.format_json)['spans'] == [
            {'start': 0, 'end': len(latex), 'latex': latex}
        ]


def test_question_parser_normalizes_private_math_glyphs_in_prompt_and_choices():
    parser = QuestionParser('3급기관사')
    text = (
        '1. 3상 교류 유효전력을 표시한 것으로 옳은 것은? '
        '(단, \ue004는 선간전압, \ue008는 선전류, \ue0a4는 위상각이다)'
        '㉮ P = \ue05c\ue06d\ue035 × \ue004 × \ue008 × cos\ue0a4'
        '㉯ P = \ue05c\ue06d\ue036 × \ue004 × \ue008 × cos\ue0a4'
        '㉴ C'
        '㉵ D'
    )

    questions = parser._parse_page(text, 1, [])

    assert questions[0].text == (
        '3상 교류 유효전력을 표시한 것으로 옳은 것은? '
        '(단, E는 선간전압, I는 선전류, θ는 위상각이다)'
    )
    assert questions[0].format_json is None
    assert questions[0].choices[0].text == (
        'P=\\sqrt{2} \\times E \\times I \\times \\cos\\theta'
    )
    assert questions[0].choices[1].text == (
        'P=\\sqrt{3} \\times E \\times I \\times \\cos\\theta'
    )
    for value in [questions[0].text, *[choice.text for choice in questions[0].choices]]:
        assert '\ue004' not in value
        assert '\ue008' not in value
        assert '\ue0a4' not in value


def test_question_parser_converts_positioned_overline_marks_to_latex_spans():
    parser = QuestionParser('4급기관사')
    text = (
        '1. NAND의 논리 관계로 옳은 것은?'
        '㉮Y = A+B㉯Y = A+B㉴Y = A·B㉵Y = A+B'
    )
    overlined_texts = [
        {'line_text': '㉮Y = A+B', 'start': 5, 'end': 8, 'text': 'A+B'},
        {'line_text': '㉵Y = A+B', 'start': 7, 'end': 8, 'text': 'B'},
    ]

    questions = parser._parse_page(text, 1, [], overlined_texts=overlined_texts)

    first_choice = questions[0].choices[0]
    second_choice = questions[0].choices[1]
    fourth_choice = questions[0].choices[3]
    first_format = json.loads(first_choice.format_json)
    fourth_format = json.loads(fourth_choice.format_json)

    assert first_choice.text == 'Y = \\overline{A+B}'
    assert first_format['spans'] == [
        {'start': 4, 'end': 18, 'latex': '\\overline{A+B}'}
    ]
    assert second_choice.text == 'Y = A+B'
    assert second_choice.format_json is None
    assert fourth_choice.text == 'Y = A+\\overline{B}'
    assert fourth_format['spans'] == [
        {'start': 6, 'end': 18, 'latex': '\\overline{B}'}
    ]
