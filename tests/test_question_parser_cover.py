from src.parser.question import QuestionParser


def test_question_page_with_exam_phrase_is_not_treated_as_cover():
    text = (
        "- 4 -\n"
        "1. 해기사 시험 관련 규정에 대한 설명으로 옳은 것은?\n"
        "㉮ 보기 A\n"
        "㉯ 보기 B\n"
        "㉴ 보기 C\n"
        "㉵ 보기 D\n"
    )

    parser = QuestionParser("3급항해사(상선)")

    assert parser._is_cover_page(text) is False


def test_explicit_cover_page_is_treated_as_cover():
    text = "년 정기 제 회 2022 1 해기사 시험\n급항해사 상선3 ( )\n문  제  지"

    parser = QuestionParser("3급항해사(상선)")

    assert parser._is_cover_page(text) is True


def test_ocr_quote_prefix_and_channel_number_are_not_question_starts():
    text = (
        "1. First question?\n"
        "㉮ A ㉯ B ㉴ C ㉵ D\n"
        "2. Steering order question?\n"
        "IIA steering order to reduce swing as rapidly as possible is ().\n"
        "㉮ A ㉯ B ㉴ C ㉵ D\n"
        "3. Radio phrase question?\n"
        "IIStand by () VHF channel 16, over.\n"
        "㉮ on ㉯ in ㉴ with ㉵ to\n"
        "4. Pronunciation question?\n"
        "㉮ A ㉯ B ㉴ C ㉵ D\n"
        "5. SMCP principle question?\n"
        "㉮ A ㉯ B ㉴ C ㉵ D\n"
    )

    parser = QuestionParser("3급항해사(어선)")
    questions = parser._parse_page(text, 1, [], allow_subject_reset=False)

    assert [question.number for question in questions] == [1, 2, 3, 4, 5]


def test_missing_single_question_number_is_inferred_between_choice_blocks():
    text = (
        "9. Stability question?\n"
        "가. A\n나. B\n사. C\n아. D\n"
        ")에 순서대로 적합한 것은?\n"
        "가. E\n나. F\n사. G\n아. H\n"
        "11. GM question?\n"
        "가. I\n나. J\n사. K\n아. L\n"
    )

    parser = QuestionParser("4급항해사(어선)")
    questions = parser._parse_page(text, 1, [], allow_subject_reset=False)

    assert [question.number for question in questions] == [9, 10, 11]
    assert questions[1].text.startswith(")에 순서대로")
