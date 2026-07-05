import pytest

from src.web_import.comcbt import ComcbtPdfParser
from src.web_import.comcbt_pdf import (
    ComcbtParseError,
    PdfTextLine,
    exam_type_from_title,
    line_reading_order_key,
    parse_answer_key,
    question_spans_from_lines,
)


def parse_result(text: str):
    return ComcbtPdfParser().parse_text_result(
        text=text,
        exam_type="Sample Exam",
        subject_name="Fallback Subject",
        year=2025,
        session=1,
    )


def test_inline_and_tail_answer_mismatch_raises():
    text = """
    1. Which answer is correct?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    전자문제집 CBT 홈페이지 : www.comcbt.com
    1
    ③
    """

    with pytest.raises(ComcbtParseError, match="Answer mismatch for question 1"):
        parse_result(text)


def test_explicit_subject_line_before_first_question_is_applied():
    text = """
    1과목 : 네트워크 일반
    1. First question?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    """

    result = parse_result(text)

    assert len(result.questions) == 1
    assert result.questions[0].subject_name == "네트워크 일반"


def test_generic_question_number_over_25_parses():
    text = """
    30. Thirtieth question?
       ① Alpha
       ② Beta
       ❸ Gamma
       ④ Delta
    """

    result = parse_result(text)

    assert [question.number for question in result.questions] == [30]
    assert result.questions[0].correct_answer == 3


def test_layout_lines_sort_column_first_for_two_column_pages():
    lines = [
        PdfTextLine("2. right top", page=0, bbox=(330, 80, 560, 100), page_width=600),
        PdfTextLine("1. left lower", page=0, bbox=(40, 500, 270, 520), page_width=600),
        PdfTextLine("3. left lowest", page=0, bbox=(40, 540, 270, 560), page_width=600),
    ]

    ordered = [line.text for line in sorted(lines, key=line_reading_order_key)]

    assert ordered == ["1. left lower", "3. left lowest", "2. right top"]


def test_full_width_top_lines_sort_before_two_column_body_and_parse_as_context():
    lines = [
        PdfTextLine("1. left question?", page=0, bbox=(40, 150, 260, 170), page_width=600, page_height=800),
        PdfTextLine("① Alpha ❷ Beta ③ Gamma ④ Delta", page=0, bbox=(40, 180, 260, 200), page_width=600, page_height=800),
        PdfTextLine("2. right question?", page=0, bbox=(330, 150, 560, 170), page_width=600, page_height=800),
        PdfTextLine("① One ② Two ③ Three ❹ Four", page=0, bbox=(330, 180, 560, 200), page_width=600, page_height=800),
        PdfTextLine("1과목 : 자료 해석", page=0, bbox=(80, 20, 520, 40), page_width=600, page_height=800),
        PdfTextLine("다음 글을 읽고 물음에 답하시오.", page=0, bbox=(50, 60, 550, 80), page_width=600, page_height=800),
    ]

    ordered = [line.text for line in sorted(lines, key=line_reading_order_key)]
    result = ComcbtPdfParser().parse_lines_result(
        lines=lines,
        exam_type="Sample Exam",
        subject_name="Fallback Subject",
        year=2025,
        session=1,
    )

    assert ordered[:2] == ["1과목 : 자료 해석", "다음 글을 읽고 물음에 답하시오."]
    assert [question.subject_name for question in result.questions] == ["자료 해석", "자료 해석"]
    assert result.groups[0].child_numbers == [1, 2]


def test_question_spans_use_next_question_from_same_column_only():
    lines = [
        PdfTextLine("1. left first", page=0, bbox=(40, 100, 260, 120), page_width=600),
        PdfTextLine("2. right first", page=0, bbox=(330, 120, 560, 140), page_width=600),
        PdfTextLine("3. left second", page=0, bbox=(40, 300, 260, 320), page_width=600),
        PdfTextLine("4. right second", page=0, bbox=(330, 340, 560, 360), page_width=600),
    ]

    spans = question_spans_from_lines(lines, {0: 800})

    assert spans[1]["bottom"] == 300
    assert spans[2]["bottom"] == 340
    assert spans[1]["column"] == 0
    assert spans[2]["column"] == 1


def test_exam_type_from_title_removes_cbt_date_suffix():
    title = "정보처리기사 필기 기출문제 및 CBT 2025년 04월 05일(1회)"

    assert exam_type_from_title(title) == "정보처리기사"


def test_tail_answer_key_rejects_non_matching_question_numbers():
    lines = [
        "1. First question?",
        "① Alpha",
        "② Beta",
        "전자문제집 CBT 홈페이지 : www.comcbt.com",
        "99 100",
        "① ②",
    ]

    assert parse_answer_key(lines, expected_numbers=[1]) == {}


def test_tail_answer_key_accepts_single_matching_pair_for_multi_question_exam():
    text = """
    1. First question?
       ① Alpha
       ② Beta
       ③ Gamma
       ④ Delta
    2. Second question?
       ① One
       ② Two
       ③ Three
       ④ Four
    전자문제집 CBT 홈페이지 : www.comcbt.com
    1
    ②
    """

    result = parse_result(text)

    assert [question.correct_answer for question in result.questions] == [2, None]


def test_single_tail_answer_pair_can_trigger_inline_mismatch_in_multi_question_exam():
    text = """
    1. First question?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    2. Second question?
       ① One
       ② Two
       ③ Three
       ④ Four
    전자문제집 CBT 홈페이지 : www.comcbt.com
    1
    ③
    """

    with pytest.raises(ComcbtParseError, match="Answer mismatch for question 1"):
        parse_result(text)


def test_tail_answer_key_parses_repeated_number_answer_row_pairs():
    lines = [
        "전자문제집 CBT 홈페이지 : www.comcbt.com",
        "1 2 3 4 5",
        "① ② ③ ④ ①",
        "6 7 8 9 10",
        "② ③ ④ ① ②",
    ]

    assert parse_answer_key(lines, expected_numbers=list(range(1, 11))) == {
        1: 1,
        2: 2,
        3: 3,
        4: 4,
        5: 1,
        6: 2,
        7: 3,
        8: 4,
        9: 1,
        10: 2,
    }
