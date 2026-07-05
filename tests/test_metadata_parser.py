from src.parser.metadata import ExamMetadataParser


def test_metadata_parser_accepts_2022_reordered_navigation_cover():
    text = (
        "년 정기 제 회 2022 1 자격시험\n"
        "급항해사 상선3 ( )\n"
        "문  제  지"
    )

    metadata = ExamMetadataParser().parse_cover(text)

    assert metadata.year == 2022
    assert metadata.session == 1
    assert metadata.exam_type == "3급항해사(상선)"


def test_metadata_parser_accepts_all_reordered_2022_sessions():
    parser = ExamMetadataParser()

    sessions = [
        parser.parse_cover(f"년 정기 제 회 2022 {session} 자격시험\n급항해사 상선3 ( )\n문  제  지")
        for session in range(1, 5)
    ]

    assert [(meta.year, meta.session, meta.exam_type) for meta in sessions] == [
        (2022, 1, "3급항해사(상선)"),
        (2022, 2, "3급항해사(상선)"),
        (2022, 3, "3급항해사(상선)"),
        (2022, 4, "3급항해사(상선)"),
    ]
