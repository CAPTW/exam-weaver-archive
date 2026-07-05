from src.parser.metadata import ExamMetadataParser


def test_metadata_parser_detects_old_cover_with_grade_split_from_role():
    text = (
        '2021년 정기 제회1\n'
        '3\n'
        '문 제\n'
        '자격시험\n'
        '급기관사\n'
        '지'
    )

    metadata = ExamMetadataParser().parse_cover(text)

    assert metadata.year == 2021
    assert metadata.session == 1
    assert metadata.exam_type == '3급기관사'


def test_metadata_parser_detects_small_vessel_operator_cover():
    text = '2024년 정기 제1회\n소형선박조종사\n문 제\n자격시험'

    metadata = ExamMetadataParser().parse_cover(text)

    assert metadata.year == 2024
    assert metadata.session == 1
    assert metadata.exam_type == '소형선박조종사'


def test_metadata_parser_marks_navigation_fishing_qualifier():
    text = '2025년 제1회\n3급 항해사\n어선\n문 제 지'

    metadata = ExamMetadataParser().parse_cover(text)

    assert metadata.year == 2025
    assert metadata.session == 1
    assert metadata.exam_type == '3급항해사(어선)'


def test_metadata_parser_combines_domestic_navigation_qualifier():
    text = '2025년 제1회\n5급 항해사\n국내한정 상선\n문 제 지'

    metadata = ExamMetadataParser().parse_cover(text)

    assert metadata.exam_type == '5급항해사(국내 상선)'
