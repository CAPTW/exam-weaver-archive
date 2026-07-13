from typing import get_type_hints

from src.parser.offline_exam import OfflineExamParser, ParsedOfflineQuestion
from src.parser.offline_quality import validate_offline_question
from src.parser.layout import LayoutLine, LayoutWord, StructuredPage


def _line(
    texts,
    *,
    y,
    xs=None,
    page=2,
    column=0,
    confidence=0.98,
    visual_indexes=(),
):
    if xs is None:
        xs = [0.08 + index * 0.08 for index in range(len(texts))]
    words = []
    for index, (text, x) in enumerate(zip(texts, xs)):
        width = max(0.025, min(0.12, len(text) * 0.018))
        words.append(
            LayoutWord(
                text=text,
                bbox=(x, y, x + width, y + 0.025),
                confidence=confidence,
                column=column,
                visual_choice_marker=index in visual_indexes,
            )
        )
    return LayoutLine(
        words=tuple(words),
        bbox=(min(xs), y, max(word.bbox[2] for word in words), y + 0.025),
        page=page,
        column=column,
    )


def _page(*lines, number=2):
    return StructuredPage(
        number=number,
        width=1.0,
        height=1.0,
        kind="scanned_image",
        lines=tuple(lines),
        images=(),
    )


def _bbox_line(text, *, y, x0, x1, page=2, column=0):
    word = LayoutWord(
        text=text,
        bbox=(x0, y, x1, y + 0.025),
        confidence=0.98,
        column=column,
    )
    return LayoutLine(
        words=(word,),
        bbox=word.bbox,
        page=page,
        column=column,
    )


def test_indented_backward_number_stays_inside_the_current_question_region():
    lines = [
        _line(["14.", "앞문제"], y=0.05, xs=[0.06, 0.10]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["15.", "현재문제"], y=0.23, xs=[0.06, 0.10]),
        _line(["1.", "내부", "장비"], y=0.27, xs=[0.106, 0.14, 0.20]),
        _line(["2.", "내부", "시설"], y=0.30, xs=[0.106, 0.14, 0.20]),
        _line(["①", "하나"], y=0.34, xs=[0.09, 0.12]),
        _line(["②", "둘"], y=0.37, xs=[0.09, 0.12]),
        _line(["③", "셋"], y=0.40, xs=[0.09, 0.12]),
        _line(["④", "넷"], y=0.43, xs=[0.09, 0.12]),
        _line(["16.", "다음문제"], y=0.49, xs=[0.06, 0.10]),
        _line(["①", "A"], y=0.52, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.55, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.58, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.61, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [14, 15, 16]
    assert "1. 내부 장비" in questions[1].stem
    assert "2. 내부 시설" in questions[1].stem


def test_question_numbers_accept_whitespace_and_bullet_delimiters_at_the_gutter():
    lines = [
        _line(["1", "「법률」", "문제"], y=0.05, xs=[0.06, 0.10, 0.18]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["2•", "다음", "문제"], y=0.23, xs=[0.06, 0.10, 0.18]),
        _line(["①", "A"], y=0.26, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.29, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.32, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.35, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [1, 2]
    assert all(len(question.choices) == 4 for question in questions)


def test_dropped_tens_digit_is_recovered_from_same_page_number_sequence():
    lines = [
        _line(["17.", "문제"], y=0.05, xs=[0.06, 0.10]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["8.", "다음문제"], y=0.23, xs=[0.06, 0.10]),
        _line(["①", "A"], y=0.26, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.29, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.32, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.35, xs=[0.09, 0.12]),
        _line(["9.", "마지막문제"], y=0.41, xs=[0.06, 0.10]),
        _line(["①", "ㄱ"], y=0.44, xs=[0.09, 0.12]),
        _line(["②", "ㄴ"], y=0.47, xs=[0.09, 0.12]),
        _line(["③", "ㄷ"], y=0.50, xs=[0.09, 0.12]),
        _line(["④", "ㄹ"], y=0.53, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [17, 18, 19]


def test_missing_number_is_inferred_after_a_complete_choice_sequence():
    lines = [
        _line(["1.", "문제"], y=0.05, xs=[0.06, 0.10]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["다음", "중", "옳은", "것은?"], y=0.23, xs=[0.09, 0.16, 0.21, 0.29]),
        _line(["①", "A"], y=0.26, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.29, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.32, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.35, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [1, 2]
    assert questions[1].stem.startswith("다음 중")


def test_missing_number_is_inferred_after_a_coordinate_choice_row():
    lines = [
        _line(["19.", "문제"], y=0.05, xs=[0.06, 0.10]),
        _line(
            ["㉦", "5인", "4인", "3인", "㉦", "2인"],
            y=0.17,
            xs=[0.08, 0.105, 0.215, 0.325, 0.408, 0.435],
            confidence=0.72,
        ),
        _line(["다음", "중", "옳은", "것은?"], y=0.25, xs=[0.09, 0.16, 0.21, 0.29]),
        _line(["①", "A"], y=0.29, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.33, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.37, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.41, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [19, 20]
    assert questions[0].choices == ["5인", "4인", "3인", "2인"]
    assert questions[1].stem.startswith("다음 중")


def test_missing_first_number_is_inferred_before_the_first_numbered_question():
    lines = [
        _line(["「법률」", "문제"], y=0.05, xs=[0.09, 0.18]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["2.", "다음문제"], y=0.23, xs=[0.06, 0.10]),
        _line(["①", "A"], y=0.26, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.29, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.32, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.35, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [1, 2]


def test_hanging_number_is_moved_from_previous_choice_to_next_question():
    lines = [
        _line(["1.", "문제"], y=0.05, xs=[0.06, 0.10]),
        _line(["①", "가"], y=0.08, xs=[0.09, 0.12]),
        _line(["②", "나"], y=0.11, xs=[0.09, 0.12]),
        _line(["③", "다"], y=0.14, xs=[0.09, 0.12]),
        _line(["④", "라"], y=0.17, xs=[0.09, 0.12]),
        _line(["2.", "이어진다."], y=0.20, xs=[0.06, 0.12]),
        _line(["다음", "문제"], y=0.23, xs=[0.09, 0.18]),
        _line(["①", "A"], y=0.26, xs=[0.09, 0.12]),
        _line(["②", "B"], y=0.29, xs=[0.09, 0.12]),
        _line(["③", "C"], y=0.32, xs=[0.09, 0.12]),
        _line(["④", "D"], y=0.35, xs=[0.09, 0.12]),
    ]

    questions = OfflineExamParser().parse_pages([_page(*lines)])

    assert [question.number for question in questions] == [1, 2]
    assert questions[0].choices[-1] == "라 이어진다."
    assert questions[1].stem == "다음 문제"


def test_ronpark_damaged_vertical_choices_recover_complete_40_question_group():
    pages = []
    number = 1
    for page_number in range(2, 8):
        lines = [
            _line(["2021년도", "경찰공무원", "승진시험", "문제지"], y=0.023, page=page_number),
        ]
        for slot in range(7 if page_number < 7 else 5):
            y = 0.08 + slot * 0.125
            lines.append(_line([f"{number}.", "다음", "중", "옳은", "것은?"], y=y, xs=[0.02, 0.06, 0.13, 0.20, 0.27], page=page_number))
            if number == 3:
                lines.extend([
                    _line(["㉠", "첫째", "명제"], y=y + 0.020, xs=[0.06, 0.10, 0.18], page=page_number),
                    _line(["㉡", "둘째", "명제"], y=y + 0.038, xs=[0.06, 0.10, 0.18], page=page_number),
                    _line(
                        ["1개", "2개", "㉭", "3개", "4개"],
                        y=y + 0.058,
                        xs=[0.08, 0.20, 0.29, 0.32, 0.44],
                        page=page_number,
                    ),
                ])
            elif number % 2:
                lines.extend([
                    _line(["㉦", f"{number}번 첫째 선택지."], y=y + 0.020, xs=[0.05, 0.09], page=page_number),
                    _line([f"{number}번 둘째 선택지."], y=y + 0.038, xs=[0.08], page=page_number),
                    _line(["㉭", f"{number}번 셋째 선택지."], y=y + 0.056, xs=[0.05, 0.09], page=page_number),
                    _line([f"{number}번 넷째 선택지."], y=y + 0.074, xs=[0.08], page=page_number),
                ])
            else:
                lines.extend([
                    _line([f"{number}번 첫째 선택지."], y=y + 0.020, xs=[0.08], page=page_number),
                    _line([f"{number}번 둘째 선택지."], y=y + 0.038, xs=[0.08], page=page_number),
                    _line(["㉭", f"{number}번 셋째 선택지."], y=y + 0.056, xs=[0.05, 0.09], page=page_number),
                    _line([f"{number}번 넷째 선택지."], y=y + 0.074, xs=[0.08], page=page_number),
                ])
            number += 1
        lines.append(
            _line(["[론박", "합격코스", "커리큘럼]"], y=0.965, xs=[0.08, 0.18, 0.30], page=page_number)
        )
        pages.append(_page(*lines, number=page_number))

    questions = OfflineExamParser().parse_pages(pages)

    assert [question.number for question in questions] == list(range(1, 41))
    rejected = [
        (question.number, question.choices, question.diagnostics, validate_offline_question(question).reason_codes)
        for question in questions
        if not validate_offline_question(question).importable
    ]
    assert rejected == []
    assert questions[0].choices == ["1번 첫째 선택지.", "1번 둘째 선택지.", "1번 셋째 선택지.", "1번 넷째 선택지."]
    assert questions[2].choices == ["1개", "2개", "3개", "4개"]
    assert "㉠ 첫째 명제" in questions[2].stem


def test_ambiguous_balanced_wrapped_lines_after_third_marker_fail_closed():
    page = _page(
        _line(["9.", "다음", "중", "옳지", "않은", "것은?"], y=0.12),
        _line(["㉦", "첫째 선택지"], y=0.22, xs=[0.05, 0.09]),
        _line(["둘째 선택지"], y=0.28, xs=[0.08]),
        _line(["㉭", "셋째 선택지는 길어서"], y=0.34, xs=[0.05, 0.09]),
        _line(["두 줄로 이어진다"], y=0.40, xs=[0.08]),
        _line(["넷째 선택지도 길어서"], y=0.46, xs=[0.08]),
        _line(["두 줄로 이어진다"], y=0.52, xs=[0.08]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == []
    assert "셋째 선택지는 길어서" in question.stem
    assert validate_offline_question(question).importable is False


def test_damaged_two_by_two_choice_grid_is_recovered_without_promoting_view_rows():
    page = _page(
        _line(["19.", "다음", "보기에서", "옳은", "조합은?"], y=0.12),
        _line(["㉠", "보기 하나", "㉡", "보기 둘"], y=0.22, xs=[0.06, 0.10, 0.27, 0.31]),
        _line(["㉢", "보기 셋", "㉣", "보기 넷"], y=0.28, xs=[0.06, 0.10, 0.27, 0.31]),
        _line(["㉠,", "㉡", "㉠,", "㉢"], y=0.40, xs=[0.08, 0.12, 0.30, 0.34]),
        _line(["㉭", "㉡,", "㉣", "㉢,", "㉣"], y=0.46, xs=[0.05, 0.08, 0.12, 0.30, 0.34]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["㉠, ㉡", "㉠, ㉢", "㉡, ㉣", "㉢, ㉣"]
    assert "보기 하나" in question.stem
    assert validate_offline_question(question).importable is True


def test_repeated_first_damaged_marker_after_three_is_treated_as_fourth_choice():
    page = _page(
        _line(["40.", "다음", "보기의", "설명으로", "옳은", "것은?"], y=0.12),
        _line(["㉠", "보기 하나"], y=0.20, xs=[0.06, 0.10]),
        _line(["㉦", "보기 일곱"], y=0.26, xs=[0.06, 0.10]),
        _line(["㉦", "첫째 선택지"], y=0.36, xs=[0.05, 0.09]),
        _line(["㉨", "둘째 선택지는"], y=0.42, xs=[0.05, 0.09]),
        _line(["이어진다"], y=0.48, xs=[0.08]),
        _line(["㉭", "셋째 선택지는"], y=0.54, xs=[0.05, 0.09]),
        _line(["이어진다"], y=0.60, xs=[0.08]),
        _line(["㉦", "넷째 선택지는"], y=0.66, xs=[0.05, 0.09]),
        _line(["이어진다"], y=0.72, xs=[0.08]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert "㉦ 보기 일곱" in question.stem
    assert question.choices == [
        "첫째 선택지",
        "둘째 선택지는 이어진다",
        "셋째 선택지는 이어진다",
        "넷째 선택지는 이어진다",
    ]
    assert validate_offline_question(question).importable is True


def test_proven_fourth_at_sign_is_removed_during_damaged_choice_recovery():
    page = _page(
        _line(["10.", "옳지", "않은", "것은?"], y=0.12),
        _line(["첫째"], y=0.22, xs=[0.08]),
        _line(["둘째"], y=0.28, xs=[0.08]),
        _line(["㉭", "셋째"], y=0.34, xs=[0.05, 0.09]),
        _line(["@", "넷째"], y=0.40, xs=[0.05, 0.09], visual_indexes=(0,)),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["첫째", "둘째", "셋째", "넷째"]
    assert validate_offline_question(question).importable is True


def test_unproven_fourth_at_sign_is_preserved_and_rejected():
    page = _page(
        _line(["10.", "옳지", "않은", "것은?"], y=0.12),
        _line(["첫째"], y=0.22, xs=[0.08]),
        _line(["둘째"], y=0.28, xs=[0.08]),
        _line(["㉭", "셋째"], y=0.34, xs=[0.05, 0.09]),
        _line(["@", "넷째"], y=0.40, xs=[0.05, 0.09]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["첫째", "둘째", "셋째", "@ 넷째"]
    result = validate_offline_question(question)
    assert result.importable is False
    assert "contaminated_choice" in result.reason_codes


def test_quality_gate_does_not_treat_slash_damaged_percentages_as_page_counters():
    question = ParsedOfflineQuestion(
        number=13,
        stem="비율 조합으로 옳은 것은?",
        choices=["1209/0 200/0", "12096 209/0", "11096 300%", "1100/0 200/0"],
        source_page=4,
        confidence=0.98,
        diagnostics=("damaged_choice_recovery",),
    )

    result = validate_offline_question(question)

    assert result.importable is True


def test_damaged_third_choice_wrap_is_not_split_in_the_middle_of_a_word():
    page = _page(
        _bbox_line("10. 조업보호본부의 사무로 옳지 않은 것은?", y=0.10, x0=0.02, x1=0.47),
        _bbox_line("㉦ 조업보호를 위한 경비 및 단속", y=0.20, x0=0.05, x1=0.34),
        _bbox_line("어선의 출입항 및 출어등록 현황과 출어선의", y=0.26, x0=0.08, x1=0.49),
        _bbox_line("동태 파악", y=0.32, x0=0.08, x1=0.17),
        _bbox_line("㉭ 조업자의 위법행위 적발, 처리 및 관", y=0.38, x0=0.05, x1=0.49),
        _bbox_line("계 기관 통보", y=0.44, x0=0.08, x1=0.20),
        _bbox_line("조업자제해역에 출입하는 어획물운반선의 통제", y=0.50, x0=0.08, x1=0.48),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "조업보호를 위한 경비 및 단속",
        "어선의 출입항 및 출어등록 현황과 출어선의 동태 파악",
        "조업자의 위법행위 적발, 처리 및 관 계 기관 통보",
        "조업자제해역에 출입하는 어획물운반선의 통제",
    ]


def test_damaged_third_choice_continuation_stays_before_true_fourth_choice():
    page = _page(
        _bbox_line("15. 기본계획에 포함될 내용으로 옳지 않은 것은?", y=0.10, x0=0.02, x1=0.48),
        _bbox_line("㉦ 정책의 기본방향 및 목표", y=0.20, x0=0.05, x1=0.41),
        _bbox_line("㉨ 시설의 구축 및 유지, 관리에", y=0.26, x0=0.05, x1=0.49),
        _bbox_line("관한 사항", y=0.32, x0=0.08, x1=0.16),
        _bbox_line("㉭ 해양수산부장관이", y=0.38, x0=0.05, x1=0.49),
        _bbox_line("필요하다고 인정하는 사항", y=0.44, x0=0.08, x1=0.30),
        _bbox_line("선박교통관제사의 교육, 훈련에 관한 사항", y=0.50, x0=0.08, x1=0.44),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices[2:] == [
        "해양수산부장관이 필요하다고 인정하는 사항",
        "선박교통관제사의 교육, 훈련에 관한 사항",
    ]


def test_marker_three_only_recovers_complete_multiline_first_and_second_choices():
    page = _page(
        _bbox_line("33. 법률의 목적으로 옳은 것은?", y=0.10, x0=0.50, x1=0.90),
        _bbox_line("첫째 선택지는 여러 줄로", y=0.20, x0=0.56, x1=0.97),
        _bbox_line("이어지고 마지막 줄은", y=0.26, x0=0.56, x1=0.95),
        _bbox_line("짧게 끝난다.", y=0.32, x0=0.56, x1=0.68),
        _bbox_line("둘째 선택지도 여러 줄로", y=0.38, x0=0.56, x1=0.97),
        _bbox_line("이어진 뒤 짧게 끝난다.", y=0.44, x0=0.56, x1=0.69),
        _bbox_line("㉭ 셋째 선택지는", y=0.50, x0=0.53, x1=0.97),
        _bbox_line("짧게 끝난다.", y=0.56, x0=0.56, x1=0.69),
        _bbox_line("넷째 선택지는 여러 줄로", y=0.62, x0=0.56, x1=0.97),
        _bbox_line("온전하게 이어진다.", y=0.68, x0=0.56, x1=0.75),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "첫째 선택지는 여러 줄로 이어지고 마지막 줄은 짧게 끝난다.",
        "둘째 선택지도 여러 줄로 이어진 뒤 짧게 끝난다.",
        "셋째 선택지는 짧게 끝난다.",
        "넷째 선택지는 여러 줄로 온전하게 이어진다.",
    ]


def test_plain_four_year_table_is_not_promoted_to_choices():
    page = _page(
        _line(["7.", "다음", "연도별", "자료를", "검토하시오."], y=0.12),
        _line(["2019", "2020", "2021", "2022"], y=0.34, xs=[0.08, 0.31, 0.54, 0.77]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == []
    assert "2019 2020 2021 2022" in question.stem
    assert "coordinate_choice_recovery" not in question.diagnostics
    assert validate_offline_question(question).importable is False


def test_vertical_mapping_choices_are_not_split_into_single_field_grid_cells():
    page = _page(
        _line(["2.", "빈칸에", "들어갈", "조합으로", "옳은", "것은?"], y=0.12),
        _line(["㉠", "15년", "㉡", "치안정감"], y=0.28, xs=[0.08, 0.11, 0.27, 0.30]),
        _line(["㉠", "15년", "㉡", "치안감"], y=0.34, xs=[0.08, 0.11, 0.27, 0.30]),
        _line(["㉭", "㉠", "20년", "㉡", "치안정감"], y=0.40, xs=[0.05, 0.08, 0.11, 0.27, 0.30]),
        _line(["㉠", "20년", "㉡", "치안감"], y=0.46, xs=[0.08, 0.11, 0.27, 0.30]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "㉠ 15년 ㉡ 치안정감",
        "㉠ 15년 ㉡ 치안감",
        "㉠ 20년 ㉡ 치안정감",
        "㉠ 20년 ㉡ 치안감",
    ]


def test_parses_explicit_circled_choices_and_stops_at_next_question():
    page = _page(
        _line(["7.", "다음", "중", "옳은", "것은?"], y=0.12),
        _line(["①", "첫째"], y=0.22),
        _line(["②", "둘째"], y=0.28),
        _line(["③", "셋째"], y=0.34),
        _line(["④", "넷째"], y=0.40),
        _line(["8.", "다음", "문제"], y=0.52),
        _line(["①", "가"], y=0.62),
        _line(["②", "나"], y=0.68),
        _line(["③", "다"], y=0.74),
        _line(["④", "라"], y=0.80),
    )

    questions = OfflineExamParser().parse_pages([page])

    assert [(question.number, question.choices) for question in questions] == [
        (7, ["첫째", "둘째", "셋째", "넷째"]),
        (8, ["가", "나", "다", "라"]),
    ]
    assert "8. 다음 문제" not in questions[0].choices[-1]


def test_preserves_view_propositions_in_stem_instead_of_promoting_them():
    page = _page(
        _line(["3.", "옳은", "것을", "고르시오."], y=0.12),
        _line(["<보기>"], y=0.20),
        _line(["㉠", "첫째", "명제"], y=0.26),
        _line(["㉡", "둘째", "명제"], y=0.32),
        _line(["㉢", "셋째", "명제"], y=0.38),
        _line(["㉣", "넷째", "명제"], y=0.44),
        _line(["①", "㉠"], y=0.54),
        _line(["②", "㉠,", "㉡"], y=0.60),
        _line(["③", "㉡,", "㉢"], y=0.66),
        _line(["④", "㉠,", "㉡,", "㉢,", "㉣"], y=0.72),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert all(label in question.stem for label in ("㉠", "㉡", "㉢", "㉣"))
    assert question.choices == ["㉠", "㉠, ㉡", "㉡, ㉢", "㉠, ㉡, ㉢, ㉣"]


def test_2026_q8_recovers_four_coordinate_cells_from_exact_damaged_tokens():
    page = _page(
        _line(["8.", "다음", "설명으로", "옳은", "것은?"], y=0.12),
        _line(["<보기>"], y=0.20),
        _line(["㉠", "첫째", "명제"], y=0.27),
        _line(["㉡", "둘째", "명제"], y=0.34),
        _line(["㉢", "셋째", "명제"], y=0.41),
        _line(["㉣", "넷째", "명제"], y=0.48),
        # Sanitized Windows OCR tokens from the 2026 maritime-law Q8 answer row:
        # "㉦ 44 246 48 ㉦ 50". Large x gaps reveal four answer cells even
        # though markers ①, ②, and ④ were lost or fused into neighboring text.
        _line(
            ["㉦", "44", "246", "48", "㉦", "50"],
            y=0.64,
            xs=[0.08, 0.12, 0.31, 0.54, 0.76, 0.80],
            confidence=0.72,
        ),
        _line(["2026년도", "해양경찰", "채용시험"], y=0.95),
        _line(["2", "/", "8"], y=0.975),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.number == 8
    assert all(label in question.stem for label in ("㉠", "㉡", "㉢", "㉣"))
    assert question.choices == ["44", "46", "48", "50"]
    assert "해양경찰" not in question.stem
    assert all("해양경찰" not in choice for choice in question.choices)
    assert "coordinate_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_transposed_four_by_four_percentage_table_recovers_column_choices():
    page = _page(
        _line(["14.", "기준을", "고르시오."], y=0.10),
        _line(["구분", "㉦", "㉨"], y=0.16, xs=[0.08, 0.30, 0.42]),
        _line(["법A", "0.01%", "0.02%", "0.03%", "0.04%"], y=0.22, xs=[0.08, 0.30, 0.42, 0.54, 0.66]),
        _line(["법B", "0.11%", "0.12%", "0.13%", "0.14%"], y=0.28, xs=[0.08, 0.30, 0.42, 0.54, 0.66]),
        _line(["법C", "0.21%", "0.22%", "0.23%", "0.24%"], y=0.34, xs=[0.08, 0.30, 0.42, 0.54, 0.66]),
        _line(["법D", "0.31%", "0.32%", "0.33%", "0.34%"], y=0.40, xs=[0.08, 0.30, 0.42, 0.54, 0.66]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "0.01% 0.11% 0.21% 0.31%",
        "0.02% 0.12% 0.22% 0.32%",
        "0.03% 0.13% 0.23% 0.33%",
        "0.04% 0.14% 0.24% 0.34%",
    ]
    assert validate_offline_question(question).importable is True


def test_quality_gate_rejects_placeholder_and_contaminated_choices():
    placeholder = ParsedOfflineQuestion(
        number=1,
        stem="비어 있지 않은 문제 본문",
        choices=["가", "나", "원문 보기 참조", "라"],
        source_page=1,
        confidence=0.99,
        diagnostics=(),
    )
    contaminated = ParsedOfflineQuestion(
        number=2,
        stem="또 다른 문제 본문",
        choices=["가", "나", "다", "④ 라 3 / 8 9. 다음 문제"],
        source_page=1,
        confidence=0.99,
        diagnostics=(),
    )

    placeholder_result = validate_offline_question(placeholder)
    contaminated_result = validate_offline_question(contaminated)

    assert placeholder_result.importable is False
    assert "placeholder_choice" in placeholder_result.reason_codes
    assert contaminated_result.importable is False
    assert "contaminated_choice" in contaminated_result.reason_codes


def test_quality_gate_rejects_unproven_leading_at_sign_choice():
    question = ParsedOfflineQuestion(
        number=18,
        stem="평문 선택지 문제",
        choices=["첫째", "둘째", "셋째", "@ 넷째"],
        source_page=4,
        confidence=0.99,
        diagnostics=(),
    )

    result = validate_offline_question(question)

    assert result.importable is False
    assert "contaminated_choice" in result.reason_codes


def test_quality_gate_rejects_question_text_and_damaged_marker_in_choices():
    question = ParsedOfflineQuestion(
        number=9,
        stem="정상 문제 본문",
        choices=["가장 옳지 않은 것은?", "㉨ 둘째", "셋째", "넷째"],
        source_page=1,
        confidence=0.99,
        diagnostics=(),
    )

    result = validate_offline_question(question)

    assert result.importable is False
    assert "question_text_in_choice" in result.reason_codes
    assert "damaged_marker_choice" in result.reason_codes


def test_quality_gate_allows_spaced_numeric_unit_choices():
    question = ParsedOfflineQuestion(
        number=19,
        stem="알맞은 수량은?",
        choices=["1 개", "2 년", "3 대", "4 명"],
        source_page=1,
        confidence=0.99,
        diagnostics=(),
    )

    assert validate_offline_question(question).importable is True


def test_quality_gate_fails_closed_for_structure_and_confidence():
    question = ParsedOfflineQuestion(
        number=4,
        stem="",
        choices=["하나", "둘", "둘"],
        source_page=3,
        confidence=0.40,
        diagnostics=("ambiguous_choice_row",),
    )

    result = validate_offline_question(question)

    assert result.importable is False
    assert set(result.reason_codes) >= {
        "empty_stem",
        "invalid_choice_count",
        "duplicate_choice",
        "low_confidence",
        "parser_diagnostic",
    }


def test_sequential_proposition_cells_are_never_recovered_as_final_choices():
    page = _page(
        _line(["5.", "다음", "자료를", "검토하시오."], y=0.12),
        _line(
            ["㉠", "44", "㉡", "46", "㉢", "48", "㉣", "50"],
            y=0.34,
            xs=[0.08, 0.12, 0.30, 0.34, 0.52, 0.56, 0.74, 0.78],
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == []
    assert all(label in question.stem for label in ("㉠", "㉡", "㉢", "㉣"))
    assert "coordinate_choice_recovery" not in question.diagnostics
    assert validate_offline_question(question).importable is False


def test_fused_sequential_proposition_cells_are_not_recovered_as_choices():
    page = _page(
        _line(["5.", "붙은", "명제", "표를", "검토하시오."], y=0.12),
        _line(
            ["㉠44", "㉡46", "㉢48", "㉣50"],
            y=0.34,
            xs=[0.08, 0.30, 0.52, 0.74],
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == []
    assert all(label in question.stem for label in ("㉠", "㉡", "㉢", "㉣"))
    assert "coordinate_choice_recovery" not in question.diagnostics
    assert validate_offline_question(question).importable is False


def test_geometry_candidate_stays_in_stem_when_explicit_choices_follow():
    page = _page(
        _line(["6.", "표의", "수치를", "보고", "답하시오."], y=0.12),
        _line(
            ["10", "20", "30", "40"],
            y=0.28,
            xs=[0.08, 0.31, 0.54, 0.77],
        ),
        _line(["①", "첫째"], y=0.48),
        _line(["②", "둘째"], y=0.55),
        _line(["③", "셋째"], y=0.62),
        _line(["④", "넷째"], y=0.69),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert "10 20 30 40" in question.stem
    assert question.choices == ["첫째", "둘째", "셋째", "넷째"]
    assert "coordinate_choice_recovery" not in question.diagnostics


def test_missing_explicit_choice_marker_is_fail_closed_even_with_four_choices():
    page = _page(
        _line(["9.", "표지", "누락", "문제"], y=0.12),
        _line(["①", "하나"], y=0.25),
        _line(["②", "둘"], y=0.32),
        _line(["④", "넷"], y=0.39),
        _line(["⑤", "다섯"], y=0.46),
    )

    question = OfflineExamParser().parse_pages([page])[0]
    result = validate_offline_question(question)

    assert "invalid_choice_sequence" in question.diagnostics
    assert result.importable is False
    assert "parser_diagnostic" in result.reason_codes


def test_duplicate_explicit_choice_marker_is_fail_closed():
    page = _page(
        _line(["10.", "표지", "중복", "문제"], y=0.12),
        _line(["①", "하나"], y=0.25),
        _line(["②", "둘"], y=0.32),
        _line(["②", "중복"], y=0.39),
        _line(["③", "셋"], y=0.46),
        _line(["④", "넷"], y=0.53),
    )

    question = OfflineExamParser().parse_pages([page])[0]
    result = validate_offline_question(question)

    assert "duplicate_choice_marker" in question.diagnostics
    assert result.importable is False
    assert "parser_diagnostic" in result.reason_codes


def test_varying_page_counter_and_residual_footer_at_point_nine_are_stripped():
    page = _page(
        _line(["11.", "바닥글", "제거", "문제"], y=0.12),
        _line(["①", "하나"], y=0.30),
        _line(["②", "둘"], y=0.38),
        _line(["③", "셋"], y=0.46),
        _line(["④", "넷"], y=0.54),
        _line(["7", "/", "12"], y=0.90),
        _line(["시험지", "A형"], y=0.91),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["하나", "둘", "셋", "넷"]
    assert "시험지" not in question.stem
    assert "document_noise_removed" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_ambiguous_bottom_margin_choice_continuation_is_preserved_and_blocked():
    page = _page(
        _line(["12.", "아래", "문장을", "고르시오."], y=0.12),
        _line(["①", "하나"], y=0.30),
        _line(["②", "둘"], y=0.38),
        _line(["③", "셋"], y=0.46),
        _line(["④", "넷째", "문장의"], y=0.54),
        _line(["계속되는", "내용"], y=0.89),
    )

    question = OfflineExamParser().parse_pages([page])[0]
    result = validate_offline_question(question)

    assert question.choices[-1] == "넷째 문장의 계속되는 내용"
    assert "ambiguous_bottom_margin" in question.diagnostics
    assert result.importable is False
    assert "parser_diagnostic" in result.reason_codes


def test_bottom_margin_proposition_line_is_kept_as_question_body():
    page = _page(
        _line(["12.", "자료를", "보고", "고르시오."], y=0.76),
        _line(["㉠", "첫째", "명제"], y=0.89),
    )

    records, _removed = OfflineExamParser()._document_lines([page])
    proposition = next(record for record in records if record.text.startswith("㉠"))

    assert proposition.ambiguous_bottom_margin is False


def test_unknown_top_margin_continuation_on_second_page_is_preserved_and_blocked():
    first_page = _page(
        _line(["13.", "두", "페이지에", "걸친", "문제"], y=0.72, page=1),
        number=1,
    )
    second_page = _page(
        _line(["계속되는", "문제", "본문"], y=0.05, page=2),
        _line(["①", "하나"], y=0.20, page=2),
        _line(["②", "둘"], y=0.28, page=2),
        _line(["③", "셋"], y=0.36, page=2),
        _line(["④", "넷"], y=0.44, page=2),
        number=2,
    )

    question = OfflineExamParser().parse_pages([first_page, second_page])[0]
    result = validate_offline_question(question)

    assert "계속되는 문제 본문" in question.stem
    assert "ambiguous_top_margin" in question.diagnostics
    assert result.importable is False
    assert "parser_diagnostic" in result.reason_codes


def test_repeated_header_on_later_region_page_is_stripped_and_diagnosed():
    preface_page = _page(
        _line(["해양경찰", "채용시험"], y=0.03, page=0),
        number=0,
    )
    first_page = _page(
        _line(["14.", "반복", "머리글", "제거", "문제"], y=0.70, page=1),
        number=1,
    )
    second_page = _page(
        _line(["해양경찰", "채용시험"], y=0.03, page=2),
        _line(["이어지는", "본문"], y=0.14, page=2),
        _line(["①", "하나"], y=0.24, page=2),
        _line(["②", "둘"], y=0.32, page=2),
        _line(["③", "셋"], y=0.40, page=2),
        _line(["④", "넷"], y=0.48, page=2),
        number=2,
    )

    question = OfflineExamParser().parse_pages(
        [preface_page, first_page, second_page]
    )[0]

    assert "해양경찰 채용시험" not in question.stem
    assert "document_noise_removed" in question.diagnostics
    assert "ambiguous_top_margin" not in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_ocr_damaged_year_exam_header_in_next_column_is_stripped():
    page = _page(
        _line(["8.", "머리글", "제거", "문제"], y=0.12, column=0),
        _line(["①", "하나"], y=0.30, column=0),
        _line(["②", "둘"], y=0.38, column=0),
        _line(["③", "셋"], y=0.46, column=0),
        _line(["④", "넷"], y=0.54, column=0),
        _line(
            ["2014년", "도", "하반기", "해", "영"],
            y=0.03,
            page=2,
            column=1,
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["하나", "둘", "셋", "넷"]
    assert "2014년" not in question.choices[-1]
    assert "document_noise_removed" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_spaced_year_and_damaged_exam_header_is_stripped():
    page = _page(
        _line(["9.", "머리글", "문제"], y=0.12),
        _line(["2", "0", "1", "5", "년", "3", "자", "경", "공", "원"], y=0.03),
        _line(["①", "하나"], y=0.30),
        _line(["②", "둘"], y=0.38),
        _line(["③", "셋"], y=0.46),
        _line(["④", "넷"], y=0.54),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert "2 0 1 5" not in question.stem
    assert "ambiguous_top_margin" not in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_overlaid_damaged_ring_under_visual_choice_marker_is_removed():
    page = _page(
        _line(["8.", "겹친", "표지", "문제"], y=0.12),
        _line(
            ["①", "하나", "②", "둘", "③", "셋", "④", "㉦", "넷"],
            y=0.30,
            xs=[0.05, 0.08, 0.27, 0.30, 0.49, 0.52, 0.71, 0.71, 0.74],
            visual_indexes={0, 2, 4, 6},
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["하나", "둘", "셋", "넷"]
    assert validate_offline_question(question).importable is True


def test_prompt_ring_overlay_shifts_visual_two_three_four_and_recovers_fourth():
    page = _page(
        _line(["2.", "괄호에", "들어갈", "내용은"], y=0.12),
        _line(
            ["옳", "①", "은", "것은?"],
            y=0.18,
            xs=[0.08, 0.081, 0.11, 0.16],
            visual_indexes={1},
        ),
        _line(["보기", "본문이다."], y=0.24, xs=[0.09, 0.16]),
        _line(
            ["②", "첫째", "값"],
            y=0.32,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(
            ["③", "둘째", "값"],
            y=0.39,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(
            ["④", "셋째", "긴"],
            y=0.46,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(["내용이다."], y=0.51, xs=[0.08]),
        _line(["넷째", "값"], y=0.56, xs=[0.08, 0.15]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "첫째 값",
        "둘째 값",
        "셋째 긴 내용이다.",
        "넷째 값",
    ]
    assert "damaged_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_lines_above_next_page_question_number_leave_completed_prior_question():
    first_page = _page(
        _line(["1.", "첫", "문제"], y=0.70, page=1),
        _line(["①", "하나"], y=0.74, page=1),
        _line(["②", "둘"], y=0.78, page=1),
        _line(["③", "셋"], y=0.82, page=1),
        _line(["④", "넷"], y=0.86, page=1),
        number=1,
    )
    second_page = _page(
        _line(["사례의", "첫째", "줄"], y=0.06, page=2),
        _line(["사례의", "둘째", "줄"], y=0.08, page=2),
        _line(["2.", "다음", "조치는?"], y=0.10, page=2),
        _line(["①", "가"], y=0.14, page=2),
        _line(["②", "나"], y=0.18, page=2),
        _line(["③", "다"], y=0.22, page=2),
        _line(["④", "라"], y=0.26, page=2),
        number=2,
    )

    first, second = OfflineExamParser().parse_pages([first_page, second_page])

    assert first.choices == ["하나", "둘", "셋", "넷"]
    assert "사례의" not in first.choices[-1]
    assert "사례의 첫째 줄" in second.stem
    assert "사례의 둘째 줄" in second.stem


def test_corrupted_question_number_is_inferred_from_neighbors_and_gutter():
    first_page = _page(
        _line(["9.", "아홉"], y=0.10, xs=[0.52, 0.56], page=1, column=1),
        _line(["①", "가"], y=0.14, xs=[0.54, 0.58], page=1, column=1),
        _line(["②", "나"], y=0.18, xs=[0.54, 0.58], page=1, column=1),
        _line(["③", "다"], y=0.22, xs=[0.54, 0.58], page=1, column=1),
        _line(["④", "라"], y=0.26, xs=[0.54, 0.58], page=1, column=1),
        _line(["1이다음", "보상은?"], y=0.32, xs=[0.52, 0.60], page=1, column=1),
        _line(["①", "하나"], y=0.36, xs=[0.54, 0.58], page=1, column=1),
        _line(["②", "둘"], y=0.40, xs=[0.54, 0.58], page=1, column=1),
        _line(["③", "셋"], y=0.44, xs=[0.54, 0.58], page=1, column=1),
        _line(["④", "넷"], y=0.48, xs=[0.54, 0.58], page=1, column=1),
        number=1,
    )
    second_page = _page(
        _line(["11.", "열하나"], y=0.10, page=2),
        _line(["①", "A"], y=0.14, page=2),
        _line(["②", "B"], y=0.18, page=2),
        _line(["③", "C"], y=0.22, page=2),
        _line(["④", "D"], y=0.26, page=2),
        number=2,
    )

    questions = OfflineExamParser().parse_pages([first_page, second_page])

    assert [question.number for question in questions] == [9, 10, 11]
    assert questions[1].choices == ["하나", "둘", "셋", "넷"]


def test_bottom_margin_stem_continuation_before_choices_is_not_ambiguous():
    page = _page(
        _line(["16.", "보기에서", "고르시오?"], y=0.76),
        _line(["㉣", "긴", "보기"], y=0.84),
        _line(["마지막", "계속문장"], y=0.883),
        _line(["①", "1개", "②", "2개", "③", "3개", "④", "4개"], y=0.908),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["1개", "2개", "3개", "4개"]
    assert "ambiguous_bottom_margin" not in question.diagnostics


def test_four_spaced_numeric_choices_recover_through_damaged_inline_markers():
    page = _page(
        _line(["12.", "합을", "고르시오?"], y=0.12),
        _line(
            ["115", "(기", "120", "㉦", "125", "㉦", "130"],
            y=0.30,
            xs=[0.08, 0.15, 0.25, 0.32, 0.42, 0.49, 0.59],
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["115", "120", "125", "130"]
    assert "coordinate_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_tiny_spurious_visual_one_shifts_two_three_four_to_damaged_fourth():
    page = _page(
        _line(["16.", "가장", "옳은", "것은?"], y=0.12),
        _line(["①", "으", "거", "으7"], y=0.18, visual_indexes={0}),
        _line(["②", "실제", "첫째"], y=0.24, visual_indexes={0}),
        _line(["이어지는", "문장이다."], y=0.28),
        _line(["③", "실제", "둘째"], y=0.34, visual_indexes={0}),
        _line(["④", "실제", "셋째"], y=0.40, visual_indexes={0}),
        _line(["셋째의", "계속이다."], y=0.44),
        _line(["㉦", "실제", "넷째"], y=0.50),
        _line(["넷째의", "계속이다."], y=0.54),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "실제 첫째 이어지는 문장이다.",
        "실제 둘째",
        "실제 셋째 셋째의 계속이다.",
        "실제 넷째 넷째의 계속이다.",
    ]
    assert "damaged_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_tiny_spurious_visual_one_shifts_to_unmarked_fourth_paragraph():
    page = _page(
        _line(["33.", "가장", "거리가"], y=0.12),
        _line(
            ["①", "먼", "것은?"],
            y=0.18,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(
            ["②", "실제", "첫째다."],
            y=0.24,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(
            ["③", "실제", "둘째다."],
            y=0.31,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(
            ["④", "실제", "셋째"],
            y=0.38,
            xs=[0.05, 0.08, 0.15],
            visual_indexes={0},
        ),
        _line(["설명이다."], y=0.43, xs=[0.08]),
        _line(["실제", "넷째"], y=0.49, xs=[0.08, 0.15]),
        _line(["설명이다."], y=0.54, xs=[0.08]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "실제 첫째다.",
        "실제 둘째다.",
        "실제 셋째 설명이다.",
        "실제 넷째 설명이다.",
    ]
    assert validate_offline_question(question).importable is True


def test_public_parser_annotations_resolve_at_runtime():
    hints = get_type_hints(OfflineExamParser.parse_pages)

    assert hints["pages"] == list[StructuredPage]
    assert hints["return"] == list[ParsedOfflineQuestion]


def test_four_by_three_labeled_numeric_table_recovers_row_choices():
    page = _page(
        _line(["8.", "세", "값을", "고르시오?"], y=0.12),
        _line(
            ["①", "㉦:", "5", "㉭:15", "㉧:", "20"],
            y=0.30,
            xs=[0.05, 0.08, 0.12, 0.27, 0.37, 0.42],
            visual_indexes={0},
        ),
        _line(
            ["②", "㉦:", "5", "㉭:", "20", "㉧:", "25"],
            y=0.36,
            xs=[0.05, 0.08, 0.12, 0.22, 0.27, 0.37, 0.42],
            visual_indexes={0},
        ),
        _line(
            ["③", "㉦:", "10", "㉭:", "20", "㉧:", "25"],
            y=0.42,
            xs=[0.05, 0.08, 0.12, 0.22, 0.27, 0.37, 0.42],
            visual_indexes={0},
        ),
        _line(
            ["㉦", "㉦:", "10", "㉭:", "25", "㉧:", "30"],
            y=0.48,
            xs=[0.05, 0.08, 0.12, 0.22, 0.27, 0.37, 0.42],
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == ["5 15 20", "5 20 25", "10 20 25", "10 25 30"]
    assert "table_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_four_wrapped_mixed_value_rows_recover_by_aligned_geometry():
    page = _page(
        _line(["7.", "세", "항목을", "고르시오?"], y=0.12),
        *[
            line
            for row, (first, second, third) in enumerate(
                [
                    ("장관", "10", "청장"),
                    ("청장", "5", "장관"),
                    ("시•도지사", "10", "장관"),
                    ("청장", "5", "청장"),
                ]
            )
            for line in (
                _line(
                    ["①" if row == 0 else "③" if row == 1 else "㉦", "㉦", first, "㉭", second],
                    y=0.30 + row * 0.06,
                    xs=[0.05, 0.08, 0.12, 0.34, 0.38],
                    visual_indexes={0} if row < 2 else (),
                ),
                _line(
                    ["@", ".", third],
                    y=0.33 + row * 0.06,
                    xs=[0.08, 0.10, 0.12],
                ),
            )
        ],
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "장관 10 청장",
        "청장 5 장관",
        "시•도지사 10 장관",
        "청장 5 청장",
    ]
    assert "table_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_two_prompt_overlays_shift_three_four_into_two_by_two_choice_grid():
    page = _page(
        _line(["13.", "법규", "질문"], y=0.12),
        _line(
            ["①", "앞부분", "본문"],
            y=0.18,
            xs=[0.08, 0.081, 0.18],
            visual_indexes={0},
        ),
        _line(
            ["②한", "나머지", "본문"],
            y=0.24,
            xs=[0.08, 0.16, 0.24],
            visual_indexes={0},
        ),
        _line(["어느", "것인가9"], y=0.30),
        _line(
            ["③", "내수", "영해"],
            y=0.38,
            xs=[0.08, 0.11, 0.30],
            visual_indexes={0},
        ),
        _line(
            ["④", "접속수역", "@", "배타적", "경제수역"],
            y=0.44,
            xs=[0.08, 0.11, 0.28, 0.31, 0.39],
            visual_indexes={0},
        ),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert "앞부분 본문" in question.stem
    assert "한 나머지 본문" in question.stem
    assert question.choices == ["내수", "영해", "접속수역", "배타적 경제수역"]
    assert "damaged_choice_recovery" in question.diagnostics
    assert validate_offline_question(question).importable is True


def test_four_paragraphs_recover_from_damaged_rings_and_one_bare_digit():
    page = _page(
        _line(["4.", "가장", "옳은", "것은?"], y=0.12),
        _line(["㉦", "첫째", "문장"], y=0.20, xs=[0.05, 0.08, 0.16]),
        _line(["계속이다."], y=0.24, xs=[0.08]),
        _line(["2", "둘째", "문장"], y=0.30, xs=[0.05, 0.08, 0.16]),
        _line(["계속이다."], y=0.34, xs=[0.08]),
        _line(["㉦", "셋째", "문장"], y=0.40, xs=[0.05, 0.08, 0.16]),
        _line(["㉦", "넷째", "문장"], y=0.46, xs=[0.05, 0.08, 0.16]),
        _line(["계속이다."], y=0.50, xs=[0.08]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "첫째 문장 계속이다.",
        "둘째 문장 계속이다.",
        "셋째 문장",
        "넷째 문장 계속이다.",
    ]
    assert validate_offline_question(question).importable is True


def test_first_last_damaged_rings_and_sentence_boundaries_recover_four_paragraphs():
    page = _page(
        _line(["5.", "가장", "틀린", "것은?"], y=0.12),
        _line(["㉦", "첫째", "문장"], y=0.20, xs=[0.05, 0.08, 0.16]),
        _line(["끝난다."], y=0.24, xs=[0.08]),
        _line(["둘째", "문장"], y=0.30, xs=[0.08, 0.16]),
        _line(["이어지고"], y=0.34, xs=[0.08]),
        _line(["끝난다."], y=0.38, xs=[0.08]),
        _line(["셋째", "문장"], y=0.44, xs=[0.08, 0.16]),
        _line(["끝난다."], y=0.48, xs=[0.08]),
        _line(["㉦", "넷째", "문장"], y=0.54, xs=[0.05, 0.08, 0.16]),
    )

    question = OfflineExamParser().parse_pages([page])[0]

    assert question.choices == [
        "첫째 문장 끝난다.",
        "둘째 문장 이어지고 끝난다.",
        "셋째 문장 끝난다.",
        "넷째 문장",
    ]
    assert validate_offline_question(question).importable is True
