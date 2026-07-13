from scripts.audit_public_exam_import_blocks import (
    answer_secondary_links,
    classify_no_text_case,
    classify_roleish,
    dedupe_inventory_rows,
    matching_primary_relatives,
    status_counts,
)
from scripts.import_public_exam_pdf_folder import (
    ExamKey,
    NoTextProbeResult,
    candidate_key_aliases,
    classify_no_text_probe,
    count_question_markers,
    extra_quality_errors,
    filter_fragment_questions,
    infer_meta,
    is_exam_start_page,
    is_fast_skippable_non_exam_listing,
    is_fallback_examish_page,
    is_hard_stop_line,
    load_reprocess_pdf_paths,
    normalize_subject_label,
    normalize_gong_line,
    parse_reprocess_status_filters,
    protect_nonsequential_question_starts,
    should_promote_answer_pdf,
    split_inline_choices,
    split_trailing_question_start_from_choice,
)
from src.parser.question import Choice, Question
from src.web_import.comcbt_pdf import PdfTextLine
from src.web_import.models import ComcbtParsedExam, ComcbtQuestionGroup


def test_dedupe_inventory_rows_keeps_last_non_blank_status():
    rows = [
        {"relative_path": "A.pdf", "status": "blocked_no_text"},
        {"relative_path": "A.pdf", "status": ""},
        {"relative_path": "A.pdf", "status": "blocked_quality"},
        {"relative_path": "B.pdf", "status": ""},
    ]

    deduped = dedupe_inventory_rows(rows)

    assert deduped["A.pdf"]["status"] == "blocked_quality"
    assert deduped["B.pdf"]["status"] == ""


def test_status_counts_uses_deduped_rows():
    rows = [
        {"relative_path": "A.pdf", "status": "blocked_no_text"},
        {"relative_path": "A.pdf", "status": "skipped_answer_secondary"},
        {"relative_path": "B.pdf", "status": "blocked_no_text"},
    ]

    assert status_counts(rows) == {
        "skipped_answer_secondary": 1,
        "blocked_no_text": 1,
    }


def test_classify_no_text_case_marks_text_start_failure():
    assert (
        classify_no_text_case(
            raw_text_length=5000,
            clean_text_length=0,
            image_count=0,
            question_marker_count=20,
            choice_marker_count=80,
        )
        == "text_start_detection_failed"
    )


def test_classify_no_text_case_marks_ocr_required():
    assert (
        classify_no_text_case(
            raw_text_length=0,
            clean_text_length=0,
            image_count=12,
            question_marker_count=0,
        )
        == "ocr_required"
    )


def test_classify_no_text_case_marks_listing_when_question_like_numbers_have_no_choices():
    assert (
        classify_no_text_case(
            raw_text_length=5000,
            clean_text_length=0,
            image_count=0,
            question_marker_count=20,
            choice_marker_count=0,
        )
        == "listing_or_non_exam_page"
    )


def test_importer_no_text_probe_marks_listing_page():
    raw_text = (
        "공기출 연도별 : 2026 전체보기 댓글 쓰기 정렬 > 제목 제목+내용 "
        "1. 해경 자료 2. 국가직 자료 3. 경찰직 자료 4. 소방직 자료 5. 지방직 자료"
    )

    assert classify_no_text_probe(raw_text, image_count=0) == "listing_or_non_exam_page"


def test_importer_no_text_probe_marks_ocr_required():
    assert classify_no_text_probe("", image_count=3) == "ocr_required"


def test_importer_no_text_probe_keeps_exam_start_failures_blocked():
    raw_text = "1. 다음 중 옳은 것은? ① 갑 ② 을 ③ 병 ④ 정"

    assert classify_no_text_probe(raw_text, image_count=0) == "text_start_detection_failed"


def test_fast_listing_skip_requires_unknown_subject(tmp_path):
    unknown_path = tmp_path / "국가직 9급" / "2024" / "2024_국가직 9급_자료_123.pdf"
    known_path = tmp_path / "국가직 9급" / "2024" / "국어" / "2024_국가직 9급_국어_자료_123.pdf"
    unknown_path.parent.mkdir(parents=True)
    known_path.parent.mkdir(parents=True)
    unknown_meta = infer_meta(unknown_path, tmp_path)
    known_meta = infer_meta(known_path, tmp_path)
    probe = NoTextProbeResult(
        cause="listing_or_non_exam_page",
        raw_text_length=5000,
        question_marker_count=70,
        choice_marker_count=0,
        image_count=0,
        page_count=10,
    )

    assert is_fast_skippable_non_exam_listing(unknown_meta, probe) is True
    assert is_fast_skippable_non_exam_listing(known_meta, probe) is False


def test_classify_roleish_uses_filename_role_markers():
    assert classify_roleish(r"해경\2025_해경_항해학_자료_100.pdf") == "questionish"
    assert classify_roleish(r"해경\2025_해경_항해학_정답_101.pdf") == "answerish"
    assert classify_roleish(r"국가직 5급\2008_국가직 5급_자료해석_정답_92684.pdf") == "answerish"


def test_normalize_subject_label_does_not_strip_subject_prefix_material():
    assert normalize_subject_label("자료해석") == "자료해석"
    assert normalize_subject_label("자료 해사영어") == "해사영어"


def test_infer_meta_treats_material_analysis_as_subject_not_role(tmp_path):
    root = tmp_path
    path = root / "국가직 5급" / "2008" / "자료해석" / "2008_국가직 5급_자료해석_정답_92684.pdf"
    path.parent.mkdir(parents=True)
    path.write_text("x", encoding="utf-8")

    meta = infer_meta(path, root, "건물 84 차이가 가장 작은 것은?")

    assert meta.role == "정답"
    assert meta.subject_name == "자료해석"
    assert meta.session == 1


def test_promote_answer_pdf_when_no_matching_question_pdf_exists(tmp_path):
    answer = tmp_path / "2025_해경_한국사_정답_123.pdf"
    answer.write_text("x", encoding="utf-8")

    assert should_promote_answer_pdf(answer, "정답") is True


def test_do_not_promote_answer_pdf_when_question_pdf_exists(tmp_path):
    question = tmp_path / "2025_해경_한국사_자료_122.pdf"
    answer = tmp_path / "2025_해경_한국사_정답_123.pdf"
    question.write_text("x", encoding="utf-8")
    answer.write_text("x", encoding="utf-8")

    assert should_promote_answer_pdf(answer, "정답") is False


def test_matching_primary_relatives_links_answer_to_question_pdf():
    directory_index = {
        "해경": [
            r"해경\2025_해경_항해학_자료_100.pdf",
            r"해경\2025_해경_항해학_정답_101.pdf",
        ]
    }

    assert matching_primary_relatives(
        r"해경\2025_해경_항해학_정답_101.pdf",
        directory_index,
    ) == [r"해경\2025_해경_항해학_자료_100.pdf"]


def test_answer_secondary_links_marks_blocked_primary_as_reprocess_candidate():
    rows = [
        {
            "relative_path": r"해경\2025_해경_항해학_자료_100.pdf",
            "filename": "2025_해경_항해학_자료_100.pdf",
            "status": "blocked_no_text",
        },
        {
            "relative_path": r"해경\2025_해경_항해학_정답_101.pdf",
            "filename": "2025_해경_항해학_정답_101.pdf",
            "status": "skipped_answer_secondary",
        },
    ]

    links = answer_secondary_links(rows)

    assert links[0]["primary_statuses"] == "blocked_no_text"
    assert links[0]["resolution"] == "primary_blocked"


def test_fallback_examish_page_accepts_single_question_with_four_choices():
    assert is_fallback_examish_page(question_count=1, choice_count=4)
    assert not is_fallback_examish_page(question_count=5, choice_count=0)


def test_exam_start_page_accepts_fallback_examish_density():
    assert is_exam_start_page("2. 다음 글 ① A ② B ③ C ④ D", question_count=1, choice_count=4)


def test_normalize_gong_line_converts_korean_question_prefix():
    assert normalize_gong_line("문 2. 다음 글에서 알 수 있는 것은?") == "2. 다음 글에서 알 수 있는 것은?"


def test_count_question_markers_accepts_korean_question_prefix():
    assert count_question_markers("문 2. 다음 글에서 알 수 있는 것은?") == 1


def test_hard_stop_does_not_treat_general_storage_word_as_site_chrome():
    assert not is_hard_stop_line("노동은 다른 상품들과는 달리 저장할 수가 없다.")


def test_split_trailing_question_start_from_last_choice():
    assert split_trailing_question_start_from_choice("\u2464 A - 4, B - 3 4. next question") == [
        "\u2464 A - 4, B - 3",
        "4. next question",
    ]


def test_split_inline_choices_preserves_next_question_after_last_choice():
    lines = split_inline_choices(PdfTextLine("x"), "\u2464 tail choice 5. next question")

    assert [line.text for line in lines] == ["\u2464 tail choice", "5. next question"]


def test_protect_nonsequential_question_starts_keeps_embedded_numbered_list_out_of_questions():
    lines = [
        PdfTextLine("1. 첫 문제"),
        PdfTextLine("2. 둘째 문제"),
        PdfTextLine("3. 조건을 고르시오"),
        PdfTextLine("1. 첫 조건"),
        PdfTextLine("2. 둘째 조건"),
        PdfTextLine("① A"),
        PdfTextLine("4. 넷째 문제"),
    ]

    protected = protect_nonsequential_question_starts(lines)

    assert [line.text for line in protected] == [
        "1. 첫 문제",
        "2. 둘째 문제",
        "3. 조건을 고르시오",
        "1) 첫 조건",
        "2) 둘째 조건",
        "① A",
        "4. 넷째 문제",
    ]


def test_protect_nonsequential_question_starts_keeps_date_lines_out_of_questions():
    lines = [
        PdfTextLine("28. 특허 문제"),
        PdfTextLine("2002."),
        PdfTextLine("5."),
        PdfTextLine("11. 출원된 것으로"),
        PdfTextLine("29. 다음 문제"),
    ]

    protected = protect_nonsequential_question_starts(lines)

    assert [line.text for line in protected] == [
        "28. 특허 문제",
        "2002.",
        "5)",
        "11) 출원된 것으로",
        "29. 다음 문제",
    ]


def test_load_reprocess_pdf_paths_reads_relative_paths(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text("relative_path\nA.pdf\nA.pdf\nB.pdf\n", encoding="utf-8")

    assert load_reprocess_pdf_paths(csv_path, tmp_path) == [tmp_path / "A.pdf", tmp_path / "B.pdf"]


def test_load_reprocess_pdf_paths_filters_by_status(tmp_path):
    csv_path = tmp_path / "candidates.csv"
    csv_path.write_text(
        "relative_path,status\nA.pdf,blocked_no_text\nB.pdf,blocked_quality\nC.pdf,blocked_no_text\n",
        encoding="utf-8",
    )

    assert load_reprocess_pdf_paths(csv_path, tmp_path, ["blocked_no_text"]) == [
        tmp_path / "A.pdf",
        tmp_path / "C.pdf",
    ]


def test_parse_reprocess_status_filters_accepts_repeated_and_csv_values():
    assert parse_reprocess_status_filters(["blocked_no_text,blocked_quality", "skipped_answer_secondary"]) == [
        "blocked_no_text",
        "blocked_quality",
        "skipped_answer_secondary",
    ]


def test_candidate_alias_for_haegyeong_numbered_round():
    aliases = candidate_key_aliases(ExamKey("해경 1차", "항해술", 2020, 1))

    assert any(alias.exam_type == "해경" and alias.session == 1 for alias in aliases)


def test_candidate_alias_for_parenthesized_second_stage():
    aliases = candidate_key_aliases(ExamKey("국가직 7급(2차)", "헌법", 2024, 1))

    assert any(alias.exam_type == "국가직 7급" and alias.session == 2 for alias in aliases)


def test_filter_fragment_questions_removes_only_blank_no_choice_questions():
    parsed = ComcbtParsedExam(
        title="t",
        source_url="u",
        exam_type="해경",
        subject_name="항해술",
        year=2024,
        session=1,
        questions=[
            Question(number=1, text="", choices=[], correct_answer=1),
            Question(number=2, text="본문", choices=[Choice(1, "①", "A")], correct_answer=1),
            Question(number=3, text="", choices=[Choice(1, "①", "A")], correct_answer=1),
        ],
        attachments=[],
        groups=[ComcbtQuestionGroup(group_id="g1", text="g", child_numbers=[1, 2, 3])],
    )

    filtered, answer_key, removed = filter_fragment_questions(parsed, {1: 1, 2: 1, 3: 1})

    assert removed == 1
    assert [question.number for question in filtered.questions] == [2, 3]
    assert answer_key == {2: 1, 3: 1}
    assert filtered.groups[0].child_numbers == [2, 3]


def test_extra_quality_errors_marks_missing_answer_key():
    parsed = ComcbtParsedExam(
        title="t",
        source_url="u",
        exam_type="가맹거래사",
        subject_name="민법",
        year=2024,
        session=1,
        questions=[
            Question(number=1, text="Q1", choices=[Choice(1, "①", "A")], correct_answer=None),
            Question(number=2, text="Q2", choices=[Choice(1, "①", "A")], correct_answer=None),
            Question(number=3, text="Q3", choices=[Choice(1, "①", "A")], correct_answer=None),
            Question(number=4, text="Q4", choices=[Choice(1, "①", "A")], correct_answer=None),
            Question(number=5, text="Q5", choices=[Choice(1, "①", "A")], correct_answer=None),
        ],
        attachments=[],
    )

    assert "answer_key_missing" in extra_quality_errors(parsed, {})


def test_extra_quality_errors_accepts_explicit_all_choices_answer():
    choices = [Choice(number, str(number), str(number)) for number in range(1, 5)]
    questions = [
        Question(
            number=number,
            text=f"Q{number}",
            choices=choices,
            correct_answer=-1 if number == 1 else 1,
            subject_name="항해술",
        )
        for number in range(1, 11)
    ]
    parsed = ComcbtParsedExam(
        title="t",
        source_url="u",
        exam_type="해경",
        subject_name="항해술",
        year=2024,
        session=1,
        questions=questions,
        attachments=[],
    )
    answer_key = {number: (-1 if number == 1 else 1) for number in range(1, 11)}

    errors = extra_quality_errors(parsed, answer_key)

    assert "invalid_answer_value" not in errors
    assert "invalid_question_answer" not in errors
