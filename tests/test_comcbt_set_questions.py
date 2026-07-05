from pathlib import Path

from src.web_import.comcbt import (
    ComcbtParsedExam,
    ComcbtPdfParser,
    parsed_exam_to_jsonable,
)


def parse_result(text: str):
    return ComcbtPdfParser().parse_text_result(
        text=text,
        exam_type="Sample Exam",
        subject_name="Fallback Subject",
        year=2025,
        session=1,
    )


def test_explicit_range_set_passage_creates_group_with_children():
    fixture = Path("tests/fixtures/comcbt_set_question_text.txt").read_text(encoding="utf-8")

    result = parse_result(fixture)

    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.range_start == 1
    assert group.range_end == 2
    assert group.child_numbers == [1, 2]
    assert group.ambiguous_range is False
    assert result.diagnostics["group_detected"] is True
    assert result.diagnostics["group_range"] == [1, 2]
    assert result.diagnostics["group_child_count"] == 2
    assert result.diagnostics["ambiguous_group_range"] is False
    assert result.diagnostics["invalid_group_range"] is False
    assert result.questions[0].group_id == group.group_id
    assert result.questions[0].group_order == 1


def test_explicit_bracket_range_without_problem_prefix_creates_group():
    text = """
    [1～2] 다음 글을 읽고 물음에 답하시오.
    공통 설명입니다.
    1. 첫째 물음은 무엇인가?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    2. 둘째 물음은 무엇인가?
       ① One
       ② Two
       ③ Three
       ❹ Four
    """

    result = parse_result(text)

    assert len(result.groups) == 1
    assert result.groups[0].range_start == 1
    assert result.groups[0].range_end == 2
    assert result.groups[0].child_numbers == [1, 2]
    assert result.diagnostics["invalid_group_range"] is False


def test_bare_numeric_ranges_inside_choices_do_not_create_groups():
    text = """
    1. 극장의 건축계획에 대한 설명으로 옳지 않은 것은?
       ① 록 레일은 와이어 로프를 조정하는 장소이다.
       ② 그린 룸의 크기는 일반적으로 30m2 이상으로 한다.
       ❸ 그리드 아이언은 무대 주위의 벽에 6~9m 높이로 설치된다.
       ④ 프로시니엄 스테이지는 공연 공간과 관람 공간이 양분된다.
    2. 전시실 설명으로 옳은 것은?
       ① 시각은 27~30°임을 고려한다.
       ② 전시실은 동선이 명확해야 한다.
       ❸ 자연채광은 전시물 특성에 맞춘다.
       ④ 조명은 균질하게 계획한다.
    """

    result = parse_result(text)

    assert result.groups == []
    assert result.diagnostics["group_detected"] is False
    assert [len(question.choices) for question in result.questions] == [4, 4]


def test_ambiguous_set_passage_creates_group_diagnostics():
    text = """
    다음 글을 읽고 물음에 답하시오.
    공통 설명입니다.
    1. 첫째 물음은 무엇인가?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    2. 둘째 물음은 무엇인가?
       ① One
       ② Two
       ③ Three
       ❹ Four
    """

    result = parse_result(text)

    assert len(result.groups) == 1
    assert result.groups[0].child_numbers == [1, 2]
    assert result.groups[0].ambiguous_range is True
    assert result.diagnostics["group_detected"] is True
    assert result.diagnostics["group_range"] is None
    assert result.diagnostics["group_child_count"] == 2
    assert result.diagnostics["ambiguous_group_range"] is True


def test_ambiguous_set_passage_attaches_all_questions_until_boundary():
    text = """
    다음 자료를 보고 물음에 답하시오.
    공통 설명입니다.
    1. 첫째 물음은 무엇인가?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    2. 둘째 물음은 무엇인가?
       ① One
       ② Two
       ③ Three
       ❹ Four
    3. 단독 문항은 무엇인가?
       ❶ Red
       ② Blue
       ③ Green
       ④ Black
    """

    result = parse_result(text)

    assert result.groups[0].child_numbers == [1, 2, 3]
    assert result.questions[0].group_id == result.groups[0].group_id
    assert result.questions[1].group_id == result.groups[0].group_id
    assert result.questions[2].group_id == result.groups[0].group_id
    assert result.questions[2].group_order == 3


def test_ambiguous_set_passage_stops_at_subject_boundary():
    text = """
    다음 글을 읽고 물음에 답하시오.
    공통 설명입니다.
    1. 첫째 물음은 무엇인가?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    2. 둘째 물음은 무엇인가?
       ① One
       ② Two
       ③ Three
       ❹ Four
    2과목 : 단독 과목
    3. 단독 문항은 무엇인가?
       ❶ Red
       ② Blue
       ③ Green
       ④ Black
    """

    result = parse_result(text)

    assert result.groups[0].child_numbers == [1, 2]
    assert result.questions[2].group_id is None
    assert result.questions[2].subject_name == "단독 과목"


def test_explicit_range_without_matching_children_sets_invalid_diagnostic():
    text = """
    [문제 10~11] 다음 글을 읽고 물음에 답하시오.
    공통 설명입니다.
    1. 단독 문항은 무엇인가?
       ❶ Alpha
       ② Beta
       ③ Gamma
       ④ Delta
    """

    result = parse_result(text)

    assert result.groups[0].child_numbers == []
    assert result.diagnostics["group_detected"] is True
    assert result.diagnostics["invalid_group_range"] is True
    assert result.questions[0].group_id is None


def test_json_output_includes_groups_and_diagnostics_without_summary_regression():
    fixture = Path("tests/fixtures/comcbt_set_question_text.txt").read_text(encoding="utf-8")
    result = parse_result(fixture)
    parsed_exam = ComcbtParsedExam(
        title="Sample Title",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        exam_type="Sample Exam",
        subject_name="Fallback Subject",
        year=2025,
        session=1,
        questions=result.questions,
        attachments=[],
        groups=result.groups,
        diagnostics=result.diagnostics,
    )

    payload = parsed_exam_to_jsonable(parsed_exam)

    assert payload["title"] == "Sample Title"
    assert payload["question_count"] == 2
    assert payload["groups"][0]["child_numbers"] == [1, 2]
    assert payload["diagnostics"]["group_detected"] is True
    assert payload["diagnostics"]["invalid_group_range"] is False
    assert payload["questions"][0]["group_id"] == result.groups[0].group_id
    assert payload["questions"][0]["group_order"] == 1
