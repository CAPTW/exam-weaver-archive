from typing import get_type_hints

from src.parser.offline_exam import OfflineExamParser, ParsedOfflineQuestion
from src.parser.offline_quality import validate_offline_question
from src.parser.layout import LayoutLine, LayoutWord, StructuredPage


def _line(texts, *, y, xs=None, page=2, column=0, confidence=0.98):
    if xs is None:
        xs = [0.08 + index * 0.08 for index in range(len(texts))]
    words = []
    for text, x in zip(texts, xs):
        width = max(0.025, min(0.12, len(text) * 0.018))
        words.append(
            LayoutWord(
                text=text,
                bbox=(x, y, x + width, y + 0.025),
                confidence=confidence,
                column=column,
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


def test_damaged_vertical_choices_use_balanced_wrapped_lines_after_third_marker():
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

    assert question.choices == [
        "첫째 선택지",
        "둘째 선택지",
        "셋째 선택지는 길어서 두 줄로 이어진다",
        "넷째 선택지도 길어서 두 줄로 이어진다",
    ]
    assert validate_offline_question(question).importable is True


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


def test_public_parser_annotations_resolve_at_runtime():
    hints = get_type_hints(OfflineExamParser.parse_pages)

    assert hints["pages"] == list[StructuredPage]
    assert hints["return"] == list[ParsedOfflineQuestion]
