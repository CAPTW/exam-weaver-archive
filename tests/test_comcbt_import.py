from pathlib import Path

import pytest

import src.web_import.comcbt as comcbt_module
from src.web_import.comcbt import (
    ComcbtAttachment,
    ComcbtDocument,
    ComcbtParsedExam,
    ComcbtPdfParser,
    SlowHttpClient,
    canonical_document_url,
    discover_exam_boards,
    parse_attachments,
    parse_board_documents,
    parsed_exam_to_jsonable,
    select_attachment,
)


def test_discover_exam_boards_from_index_html():
    html = """
    <a href="//www.comcbt.com/xe/wc">9급 국가직 공무원 건축계획</a>
    <a href="//www.comcbt.com/xe/wc">9급 국가직 공무원 건축계획</a>
    <a href="//www.comcbt.com/xe">[다운로드]</a>
    <a href="//evil.example/xe/evil">오프사이트</a>
    <a href="http://www.comcbt.com/xe/http">HTTP 링크</a>
    """

    boards = discover_exam_boards(html)

    assert len(boards) == 1
    assert boards[0].mid == "wc"
    assert boards[0].name == "9급 국가직 공무원 건축계획"


def test_parse_board_documents_from_xe_board_html():
    html = """
    <a href="/xe/wc/8837719">9급 국가직 공무원 건축계획 필기 기출문제 및 CBT 2025년 04월 05일(1회)</a>
    <a href="/xe/wc/7786247">9급 국가직 공무원 건축계획 필기 기출문제 및 CBT 2024년 03월 23일(1회)</a>
    <a href="//evil.example/xe/wc/9999999">오프사이트 기출문제 및 CBT 2024년 03월 23일(1회)</a>
    <a href="http://www.comcbt.com/xe/wc/8888888">HTTP 기출문제 및 CBT 2024년 03월 23일(1회)</a>
    """

    documents = parse_board_documents(html, "https://www.comcbt.com/xe/wc")

    assert [document.document_srl for document in documents] == ["8837719", "7786247"]
    assert documents[0].year == 2025
    assert documents[0].session == 1


def test_parse_attachments_prefers_teacher_pdf():
    html = """
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">시험(교사용).pdf</a>
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=2">시험(학생용).pdf</a>
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=3">시험(교사용).hwp</a>
    """

    attachments = parse_attachments(html, "https://www.comcbt.com/xe/wc/8837719")
    selected = select_attachment(attachments)

    assert len(attachments) == 3
    assert selected is not None
    assert selected.role == "teacher"
    assert selected.extension == "pdf"


def test_parse_attachments_excludes_offsite_and_non_https_links():
    html = """
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">시험(교사용).pdf</a>
    <a href="https://evil.example/xe/?module=file&amp;act=procFileDownload&amp;file_srl=2">오프사이트(교사용).pdf</a>
    <a href="http://www.comcbt.com/xe/?module=file&amp;act=procFileDownload&amp;file_srl=3">HTTP(교사용).pdf</a>
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=4&amp;m=1">차단쿼리(교사용).pdf</a>
    <a href="/xe/?module=file&amp;act=dispMemberFindAccount&amp;file_srl=5">차단액션(교사용).pdf</a>
    <a href="/xe/?module=file&amp;file_srl=6">다운로드아님(교사용).pdf</a>
    """

    attachments = parse_attachments(html, "https://www.comcbt.com/xe/wc/8837719")

    assert [attachment.filename for attachment in attachments] == ["시험(교사용).pdf"]


def test_parse_attachments_requires_proc_file_download_act_query():
    html = """
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">시험(교사용).pdf</a>
    <a href="/xe/?module=file&amp;foo=procFileDownload&amp;file_srl=2">foo만일치(교사용).pdf</a>
    <a href="/xe/procFileDownload?module=file&amp;file_srl=3">path만일치(교사용).pdf</a>
    <a href="/xe/?module=file&amp;act=dispFileDownload&amp;file_srl=4">텍스트 procFileDownload.pdf</a>
    """

    attachments = parse_attachments(html, "https://www.comcbt.com/xe/wc/8837719")

    assert [attachment.filename for attachment in attachments] == ["시험(교사용).pdf"]


def test_select_attachment_ranks_teacher_pdf_before_teacher_hwp_and_student_pdf():
    html = """
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=1">시험(교사용).hwp</a>
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=2">시험(학생용).pdf</a>
    <a href="/xe/?module=file&amp;act=procFileDownload&amp;file_srl=3">시험(교사용).pdf</a>
    """

    attachments = parse_attachments(html, "https://www.comcbt.com/xe/wc/8837719")
    selected = select_attachment(attachments)

    assert selected is not None
    assert selected.filename == "시험(교사용).pdf"


def test_parsed_exam_json_includes_selected_attachment_filename():
    attachment = ComcbtAttachment(
        filename="시험(교사용).pdf",
        url="https://www.comcbt.com/xe/?module=file&act=procFileDownload&file_srl=1",
        role="teacher",
        extension="pdf",
    )
    parsed_exam = ComcbtParsedExam(
        title="시험",
        source_url="https://www.comcbt.com/xe/wc/8837719",
        exam_type="시험",
        subject_name="과목",
        year=2025,
        session=1,
        questions=[],
        attachments=[attachment],
        selected_attachment=attachment,
    )

    payload = parsed_exam_to_jsonable(parsed_exam)

    assert payload["selected_attachment"]["filename"] == "시험(교사용).pdf"


def test_canonical_document_url_normalizes_trailing_slash_and_rejects_variants():
    assert (
        canonical_document_url("https://www.comcbt.com/xe/wc/8837719/")
        == "https://www.comcbt.com/xe/wc/8837719"
    )

    for url in [
        "https://www.comcbt.com/xe/wc/8837719?foo=bar",
        "https://www.comcbt.com/xe/wc/8837719#fragment",
        "http://www.comcbt.com/xe/wc/8837719",
        "https://evil.example/xe/wc/8837719",
        "https://www.comcbt.com/xe/wc/page/2",
    ]:
        with pytest.raises(ValueError, match="Expected canonical COMCBT document URL"):
            canonical_document_url(url)


def test_slow_http_client_constructor_does_not_read_robots(monkeypatch):
    calls = []

    def fail_read(self):
        calls.append("read")
        raise AssertionError("robots.txt must not be read in the constructor")

    monkeypatch.setattr(comcbt_module.robotparser.RobotFileParser, "read", fail_read)

    SlowHttpClient(delay_seconds=2.0)

    assert calls == []


def test_slow_http_client_blocks_disallowed_query_patterns_before_network(monkeypatch, tmp_path):
    calls = []

    def fail_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("blocked URLs must not reach urlopen")

    monkeypatch.setattr(comcbt_module.robotparser.RobotFileParser, "read", lambda self: None)
    monkeypatch.setattr(comcbt_module.robotparser.RobotFileParser, "can_fetch", lambda self, user_agent, url: True)
    monkeypatch.setattr(comcbt_module, "urlopen", fail_urlopen)
    client = SlowHttpClient(delay_seconds=2.0)

    with pytest.raises(ValueError, match="Blocked COMCBT crawl URL pattern"):
        client.fetch_text("https://www.comcbt.com/xe/wc?search_target=title")
    with pytest.raises(ValueError, match="Blocked COMCBT crawl URL pattern"):
        client.fetch_bytes("https://www.comcbt.com/xe/wc?sort_index=title")
    with pytest.raises(ValueError, match="Blocked COMCBT crawl URL pattern"):
        client.download("https://www.comcbt.com/xe/wc?m=1", tmp_path / "blocked.html")

    assert calls == []


def test_slow_http_client_blocks_offsite_and_unsupported_scheme_before_network(monkeypatch):
    calls = []

    def fail_urlopen(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("non-canonical URLs must not reach urlopen")

    monkeypatch.setattr(comcbt_module.robotparser.RobotFileParser, "read", lambda self: None)
    monkeypatch.setattr(comcbt_module.robotparser.RobotFileParser, "can_fetch", lambda self, user_agent, url: True)
    monkeypatch.setattr(comcbt_module, "urlopen", fail_urlopen)
    client = SlowHttpClient(delay_seconds=2.0)

    for url in [
        "https://evil.example/xe/wc",
        "http://www.comcbt.com/xe/wc",
        "ftp://www.comcbt.com/xe/wc",
    ]:
        with pytest.raises(ValueError, match="Blocked COMCBT crawl URL pattern"):
            client.fetch_text(url)

    assert calls == []


def test_comcbt_pdf_text_parser_extracts_questions_choices_and_answers():
    text = """
    9급 국가직 공무원 건축계획 ◐2025년 04월 05일 필기 기출문제◑
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
    2
    ②
    ④
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 2
    assert questions[0].number == 1
    assert questions[0].correct_answer == 2
    assert [choice.text for choice in questions[0].choices] == ["Alpha", "Beta", "Gamma", "Delta"]
    assert questions[1].correct_answer == 4


def test_comcbt_pdf_text_parser_supports_five_choice_questions():
    text = """
    1. Five-choice question?
       ① Alpha
       ② Beta
       ③ Gamma
       ④ Delta
       ❺ Epsilon
    전자문제집 CBT 홈페이지 : www.comcbt.com
    1
    ⑤
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 1
    assert questions[0].correct_answer == 5
    assert [choice.number for choice in questions[0].choices] == [1, 2, 3, 4, 5]
    assert [choice.text for choice in questions[0].choices][-1] == "Epsilon"


def test_comcbt_pdf_text_parser_reads_five_choice_tail_answer_key():
    text = """
    1. Five-choice question with tail answer?
       ① Alpha
       ② Beta
       ③ Gamma
       ④ Delta
       ⑤ Epsilon
    전자문제집 CBT 홈페이지 : www.comcbt.com
    1
    ⑤
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 1
    assert questions[0].correct_answer == 5
    assert [choice.number for choice in questions[0].choices] == [1, 2, 3, 4, 5]


def test_comcbt_pdf_text_parser_reads_repeated_tail_answer_blocks():
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
    3. Third question?
       ① Red
       ② Blue
       ③ Green
       ④ Black
    4. Fourth question?
       ① North
       ② South
       ③ East
       ④ West
    전자문제집 CBT 홈페이지 : www.comcbt.com
    전자문제집 CBT란?
    1
    2
    ②
    ④
    3
    4
    ③
    ①
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert [question.correct_answer for question in questions] == [2, 4, 3, 1]


def test_comcbt_pdf_text_parser_supports_choice_markers_without_spaces():
    text = """
    1. No-space choices?
       ①Alpha
       ②Beta
       ❸Gamma
       ④Delta
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 1
    assert questions[0].correct_answer == 3
    assert [choice.text for choice in questions[0].choices] == ["Alpha", "Beta", "Gamma", "Delta"]


def test_comcbt_pdf_text_parser_ignores_colon_references_inside_choices():
    text = """
    1. Dictionary examples?
       ① 1. ❶: Alpha example
       ❷ 1. ❸: Beta example
       ③ 2. Gamma example
       ④ 3. ❶: Delta example
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 1
    assert questions[0].correct_answer == 2
    assert [choice.number for choice in questions[0].choices] == [1, 2, 3, 4]
    assert "❶:" in questions[0].choices[0].text
    assert "❸:" in questions[0].choices[1].text


def test_comcbt_pdf_text_parser_supports_spaced_question_number_dot():
    text = """
    8. First question?
       ❶ Alpha
       ② Beta
       ③ Gamma
       ④ Delta
    9 . Second question?
       ① One
       ② Two
       ③ Three
       ❹ Four
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert [question.number for question in questions] == [8, 9]
    assert [question.correct_answer for question in questions] == [1, 4]


def test_comcbt_pdf_text_parser_does_not_split_decimal_lines_as_questions():
    text = """
    11. School planning?
       ❶ Corridor width is
       2.4m or more.
       ② Gym height is 5m or more.
       ③ Parallel layout has uneven classroom conditions.
       ④ Dalton plan divides classes.
    12. Next question?
       ① Alpha
       ❷ Beta
       ③ Gamma
       ④ Delta
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert [question.number for question in questions] == [11, 12]
    assert [len(question.choices) for question in questions] == [4, 4]
    assert "2.4m or more" in questions[0].choices[0].text


def test_comcbt_pdf_text_parser_ignores_filled_circled_references_inside_stem():
    text = """
    1. Switch S was connected to ❶ and then moved to ❷. Which graph is correct?
       ① First
       ❷ Second
       ③ Third
       ④ Fourth
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert len(questions) == 1
    assert "❶" in questions[0].text
    assert "❷" in questions[0].text
    assert questions[0].correct_answer == 2
    assert [choice.text for choice in questions[0].choices] == ["First", "Second", "Third", "Fourth"]


def test_comcbt_pdf_parser_fills_image_choice_placeholders():
    text = """
    1. Which symbol is correct?
       ①
       ②
       ❸
       ④
    """

    questions = ComcbtPdfParser().parse_text(
        text=text,
        exam_type="Sample Exam",
        subject_name="Sample Subject",
        year=2025,
        session=1,
    )

    assert questions[0].has_image is True
    assert questions[0].correct_answer == 3
    assert {choice.text for choice in questions[0].choices} == {"[이미지 선지]"}
