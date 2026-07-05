from src.parser.main import ExamPDFParser


def test_session_marker_ignores_body_mentions():
    parser = ExamPDFParser()

    assert parser._extract_session_from_page_text("㉴ 심판장은 직권으로 제1회 심판기일을 변경할") is None
    assert parser._extract_session_from_page_text("2019 년 정기\n제 4 회\n10. 문제") == 4
    assert parser._extract_session_from_page_text("2019 년\n정기 제 3 회\n1. 문제") == 3


def test_fishing_navigation_skips_merchant_specialized_section():
    parser = ExamPDFParser()
    text = (
        "25. English tail\n"
        "[제5과목 상선전문]\n"
        "1. Merchant-only question?\n"
        "가. A 나. B 사. C 아. D\n"
        "[제5과목 어선전문]\n"
        "1. Fishing question?\n"
        "가. A 나. B 사. C 아. D\n"
    )

    segments = parser._subject_segments_from_page_text(
        text,
        "영어",
        "4급항해사(어선)",
    )

    assert [subject for subject, _ in segments] == ["영어", "어선전문"]
    assert "Merchant-only" not in segments[1][1]
    assert "Fishing question" in segments[1][1]
