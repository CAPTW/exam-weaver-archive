from __future__ import annotations

import importlib
import inspect
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.parser.layout import LayoutLine, LayoutWord, StructuredPage


CORPUS_RELATIVE_PATHS = [
    "(공고)_2026년_해양경찰청_소속_공무원_연간채용계획_등_공고.pdf",
    "2023 2차 - 물리 정답 & 해설.pdf",
    "2023 2차 - 물리.pdf",
    "2023 2차 - 항해.pdf",
    "2023 2차 - 확정답안.pdf",
    "25년 하반기 해양경찰공무원 채용시험 공고.pdf",
    "해양경찰청 교육훈련담당관_25년 하반기 해양경찰공무원 채용시험 공고.pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출문제]경찰직 기관술(학)(24-13년).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출문제]경찰직 기관학(24년 하반기-25년 하반기).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관술(학)(24-13년).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관학(24년 하반기-25년 상반기).pdf",
    "[론박]경찰직 기관학(25년 하반기 포함)/[기출정답]경찰직 기관학(25년 하반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출문제]경찰직 항해학(24년 하반기-25년 하반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출문제]경찰직 항해학(24년-13년).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(24년 하반기-25년 상반기).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(24년-13년).pdf",
    "[론박]경찰직 항해학(25년 하반기 포함)/[기출정답]경찰직 항해학(25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(21년 경사-13년).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(24년 하반기-25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(24년-21년 경장).pdf",
    "[론박]해사법규(26년 승진 포함)/[기출문제]해사법규(26년 승진).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(24년 하반기-25년 상반기).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(24년-13년).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(25년 하반기).pdf",
    "[론박]해사법규(26년 승진 포함)/정답안/[기출정답]해사법규(26년 승진).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출문제]해사영어(24년 하반기-25년 하반기).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출문제]해사영어(24년-13년).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(24년 하반기-25년 상반기).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(24년-13년).pdf",
    "[론박]해사영어(25년 하반기 포함)/[기출정답]해사영어(25년 하반기).pdf",
]


def _line(texts: list[str], y: float) -> LayoutLine:
    words = tuple(
        LayoutWord(text, (0.08 + index * 0.12, y, 0.16 + index * 0.12, y + 0.03), 0.99)
        for index, text in enumerate(texts)
    )
    return LayoutLine(words, (0.08, y, words[-1].bbox[2], y + 0.03), 1, 0)


def _page_with_question(choice_count: int = 4) -> StructuredPage:
    lines = [_line(["1.", "옳은", "것은?"], 0.10)]
    for index, marker in enumerate(("①", "②", "③", "④")[:choice_count], start=1):
        lines.append(_line([marker, f"선택지{index}"], 0.10 + index * 0.08))
    return StructuredPage(1, 1, 1, "scanned", tuple(lines), ())


def test_classifies_exact_corpus_as_12_questions_15_answers_and_3_notices():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    roles = Counter(
        classify_offline_document(Path(relative), probe=None)
        for relative in CORPUS_RELATIVE_PATHS
    )

    assert roles == {
        DocumentRole.QUESTION: 12,
        DocumentRole.ANSWER: 15,
        DocumentRole.NOTICE: 3,
    }


def test_probe_classifies_ambiguous_question_answer_and_notice_documents():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    assert classify_offline_document(
        Path("ambiguous.pdf"),
        {"question_marker_count": 20, "choice_marker_count": 80},
    ) is DocumentRole.QUESTION
    assert classify_offline_document(
        Path("ambiguous.pdf"), {"text": "정답 및 해설", "answer_marker_count": 20}
    ) is DocumentRole.ANSWER
    assert classify_offline_document(
        Path("ambiguous.pdf"), {"text": "2026년도 채용시험 시행 공고"}
    ) is DocumentRole.NOTICE


def test_public_importer_question_role_probe_accepts_material_filename():
    from src.parser.offline_sources import DocumentRole, classify_offline_document

    assert classify_offline_document(
        Path("2025_해경_항해학_자료_100.pdf"), {"role": "자료"}
    ) is DocumentRole.QUESTION


def test_notices_never_invoke_extraction_or_create_question_candidates(monkeypatch):
    import src.parser.offline_sources as sources

    class FailExtractor:
        def __init__(self, *args, **kwargs):
            raise AssertionError("notices must be filtered before extraction")

    monkeypatch.setattr(sources, "PDFExtractor", FailExtractor)

    result = sources.parse_offline_question_pdf(
        Path("25년 하반기 해양경찰공무원 채용시험 공고.pdf"),
        {"subject_name": "항해학"},
    )

    assert result.role is sources.DocumentRole.NOTICE
    assert result.questions == ()
    assert result.rejected == ()


def test_shared_adapter_returns_only_quality_checked_common_parser_questions(monkeypatch):
    import src.parser.offline_sources as sources

    class FakeExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, path):
            return SimpleNamespace(
                pages=[SimpleNamespace(structured_page=_page_with_question())]
            )

    monkeypatch.setattr(sources, "PDFExtractor", FakeExtractor)

    result = sources.parse_offline_question_pdf(
        Path("[기출문제]항해학.pdf"), {"subject_name": "항해학"}
    )

    assert [question.choices for question in result.questions] == [
        ["선택지1", "선택지2", "선택지3", "선택지4"]
    ]
    assert result.rejected == ()
    assert result.metadata["subject_name"] == "항해학"


def test_shared_adapter_rejects_incomplete_candidates_without_generic_choice_synthesis(monkeypatch):
    import src.parser.offline_sources as sources

    class FakeExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, path):
            return SimpleNamespace(
                pages=[SimpleNamespace(structured_page=_page_with_question(choice_count=3))]
            )

    monkeypatch.setattr(sources, "PDFExtractor", FakeExtractor)

    result = sources.parse_offline_question_pdf(Path("[기출문제]기관학.pdf"), {})

    assert result.questions == ()
    assert len(result.rejected) == 1
    assert "invalid_choice_count" in result.rejected[0].reason_codes
    assert "원문 보기 참조" not in repr(result)


def test_group_selector_filters_by_source_page_and_reuses_cached_parse_result():
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import (
        DocumentRole,
        OfflineParseResult,
        RejectedOfflineQuestion,
        select_group_questions,
    )

    page_one = ParsedOfflineQuestion(1, "old", ["a", "b", "c", "d"], 1, 0.9, ())
    page_two = ParsedOfflineQuestion(1, "selected", ["a", "b", "c", "d"], 2, 0.9, ())
    rejected = RejectedOfflineQuestion(
        ParsedOfflineQuestion(2, "bad", ["a"], 2, 0.4, ("invalid_choice_count",)),
        ("invalid_choice_count",),
    )
    result = OfflineParseResult(
        Path("questions.pdf"),
        DocumentRole.QUESTION,
        {},
        (page_one, page_two),
        (rejected,),
    )
    calls = []

    def parse_source(path, metadata):
        calls.append((path, metadata))
        return result

    group = {"pages": [{"page": 2, "source_path": "questions.pdf"}]}
    cache = {}

    selected, rejected_count = select_group_questions(group, parse_source, cache)
    selected_again, _ = select_group_questions(group, parse_source, cache)

    assert selected == {1: page_two}
    assert selected_again == selected
    assert rejected_count == 1
    assert calls == [(Path("questions.pdf"), None)]


@pytest.mark.parametrize(
    ("questions", "answers", "rejected_count", "reason"),
    [
        ({1: object()}, [1, 2], 0, "missing_questions"),
        ({1: object(), 2: object()}, [1, 2], 1, "rejected_questions"),
        ({1: object(), 2: object()}, [1, 0], 0, "invalid_answers"),
        ({1: object(), 2: object()}, [1, 5], 0, "invalid_answers"),
    ],
)
def test_complete_set_gate_rejects_partial_rejected_or_invalid_answer_sets(
    questions, answers, rejected_count, reason
):
    from src.parser.offline_sources import OfflineSetValidationError, require_complete_offline_set

    with pytest.raises(OfflineSetValidationError, match=reason):
        require_complete_offline_set(
            questions,
            expected_numbers=[1, 2],
            answers=answers,
            rejected_count=rejected_count,
            choice_counts={1: 4, 2: 4},
        )


def test_persistence_gate_rejects_zero_answer_question():
    from src.parser.offline_sources import OfflineSetValidationError, require_persistable_offline_questions
    from src.parser.question import Choice, Question

    question = Question(
        number=1,
        text="본문",
        choices=[Choice(number, str(number), str(number)) for number in range(1, 5)],
        correct_answer=0,
    )

    with pytest.raises(OfflineSetValidationError, match="invalid_answers"):
        require_persistable_offline_questions([SimpleNamespace(question=question)])


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.import_maritime_law_pdf",
        "scripts.import_maritime_english_pdf",
        "scripts.import_police_navigation_pdf",
        "scripts.import_police_engineering_pdf",
    ],
)
def test_every_subject_builder_applies_complete_set_gate(module_name):
    module = importlib.import_module(module_name)

    assert "require_complete_offline_set" in inspect.getsource(module.build_questions)
    assert "require_persistable_offline_questions" in inspect.getsource(module.import_into_db)


@pytest.mark.parametrize(
    ("module_name", "subject_name", "exam_type"),
    [
        ("scripts.import_maritime_law_pdf", "해사법규", "해양경찰 해사법규"),
        ("scripts.import_maritime_english_pdf", "해사영어", "해양경찰 해사영어"),
        ("scripts.import_police_navigation_pdf", "항해학", "해양경찰 경찰직 항해학"),
        ("scripts.import_police_engineering_pdf", "기관학", "해양경찰 경찰직 기관학"),
    ],
)
def test_subject_adapters_delegate_to_shared_parser_without_placeholders(
    monkeypatch, module_name, subject_name, exam_type
):
    module = importlib.import_module(module_name)
    sentinel = object()
    calls = []

    def fake_parse(path, metadata):
        calls.append((path, metadata))
        return sentinel

    monkeypatch.setattr(module, "parse_offline_question_pdf", fake_parse)

    result = module.parse_subject_question_pdf(Path("questions.pdf"), {"year": 2025})

    assert result is sentinel
    assert calls == [
        (
            Path("questions.pdf"),
            {"subject_name": subject_name, "exam_type": exam_type, "year": 2025},
        )
    ]
    assert "원문 보기 참조" not in inspect.getsource(module)


def test_public_importer_ocr_required_adapter_uses_shared_parser(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    calls = []

    def fake_parse(path, metadata):
        calls.append((path, metadata))
        question = ParsedOfflineQuestion(1, "본문", ["가", "나", "다", "라"], 2, 0.99, ())
        return OfflineParseResult(path, DocumentRole.QUESTION, metadata, (question,), ())

    monkeypatch.setattr(public_importer, "parse_offline_question_pdf", fake_parse)
    meta = public_importer.PdfMeta(
        path=Path("scanned.pdf"),
        relative_path="scanned.pdf",
        role="문제",
        exam_type="해경",
        subject_name="항해학",
        year=2025,
        session=1,
        document_id="doc",
        top_category="해경",
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert calls and calls[0][0] == Path("scanned.pdf")
    assert [choice.text for choice in parsed.questions[0].choices] == ["가", "나", "다", "라"]
    assert answer_key == {}


def test_public_ocr_coverage_uses_authoritative_expected_count(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 6)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    meta = public_importer.PdfMeta(
        path=Path("scanned.pdf"),
        relative_path="scanned.pdf",
        role="문제",
        exam_type="해경",
        subject_name="항해학",
        year=2025,
        session=1,
        document_id="doc",
        top_category="해경",
        expected_question_count=20,
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert answer_key == {}
    assert parsed.diagnostics["expected_question_numbers"] == list(range(1, 21))
    assert "question_coverage_mismatch" in public_importer.extra_quality_errors(parsed, answer_key)


def test_public_ocr_without_authoritative_coverage_is_blocked(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 11)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    meta = public_importer.PdfMeta(
        Path("scanned.pdf"), "scanned.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경"
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert parsed.diagnostics["expected_question_numbers"] == []
    assert "expected_question_coverage_unknown" in public_importer.extra_quality_errors(
        parsed, answer_key
    )


def test_infer_meta_populates_count_only_for_trusted_exam_format(tmp_path):
    import scripts.import_public_exam_pdf_folder as public_importer

    known = tmp_path / "해경" / "2025" / "항해학" / "2025_해경_항해학_자료_100.pdf"
    unknown = tmp_path / "미분류" / "2025" / "과목" / "2025_미분류_과목_자료_101.pdf"

    known_meta = public_importer.infer_meta(known, tmp_path)
    unknown_meta = public_importer.infer_meta(unknown, tmp_path)

    assert known_meta.expected_question_count == 20
    assert unknown_meta.expected_question_count is None


def test_parsed_answer_key_cannot_establish_expected_ocr_coverage(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult
    from src.web_import.comcbt_pdf import PdfTextLine

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 11)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    monkeypatch.setattr(
        public_importer,
        "parse_gong_answer_key",
        lambda lines, expected: {number: 1 for number in range(1, 11)},
    )
    meta = public_importer.PdfMeta(
        Path("unknown.pdf"), "unknown.pdf", "문제", "미분류", "과목", 2025, 1, "doc", "미분류"
    )
    answer_text = public_importer.CleanTextResult(
        [PdfTextLine("answer")], 1, True, 1, 1, 0, []
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("unknown.pdf"), meta, answer_text, "file:///unknown.pdf"
    )

    assert len(answer_key) == 10
    assert parsed.diagnostics["expected_question_numbers"] == []
    assert parsed.diagnostics["expected_question_coverage_unknown"] is True


def test_public_ocr_conversion_preserves_explicit_shared_passage_groups(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    page = _page_with_question()
    passage = _line(["[1~2]", "다음", "글을", "읽고", "답하시오."], 0.04)
    question_two_lines = (
        _line(["2.", "둘째", "문제"], 0.55),
        _line(["①", "가"], 0.63),
        _line(["②", "나"], 0.71),
        _line(["③", "다"], 0.79),
        _line(["④", "라"], 0.87),
    )
    structured = StructuredPage(
        1, 1, 1, "scanned", (passage, *page.lines, *question_two_lines), ()
    )
    questions = (
        ParsedOfflineQuestion(1, "첫째 문제", ["가", "나", "다", "라"], 1, 0.99, ()),
        ParsedOfflineQuestion(2, "둘째 문제", ["가", "나", "다", "라"], 1, 0.99, ()),
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(
            path, DocumentRole.QUESTION, metadata, questions, (), (structured,)
        ),
    )
    meta = public_importer.PdfMeta(
        Path("scanned.pdf"), "scanned.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경", 2
    )

    parsed, _ = public_importer.build_ocr_required_exam(
        Path("scanned.pdf"), meta, None, "file:///scanned.pdf"
    )

    assert len(parsed.groups) == 1
    assert parsed.groups[0].child_numbers == [1, 2]
    assert parsed.questions[0].shared_passage == parsed.groups[0].text
    assert parsed.questions[1].group_id == parsed.groups[0].group_id


def test_public_ocr_reads_paired_scanned_answer_with_shared_extractor(monkeypatch):
    import scripts.import_public_exam_pdf_folder as public_importer
    from src.parser.offline_exam import ParsedOfflineQuestion
    from src.parser.offline_sources import DocumentRole, OfflineParseResult

    questions = tuple(
        ParsedOfflineQuestion(number, f"Q{number}", ["a", "b", "c", "d"], 1, 0.99, ())
        for number in range(1, 6)
    )
    monkeypatch.setattr(
        public_importer,
        "parse_offline_question_pdf",
        lambda path, metadata: OfflineParseResult(path, DocumentRole.QUESTION, metadata, questions, ()),
    )
    answer_page = StructuredPage(
        1,
        1,
        1,
        "scanned",
        (
            _line(["1", "2", "3", "4", "5"], 0.20),
            _line(["①", "②", "③", "④", "①"], 0.30),
        ),
        (),
    )
    extracted = []

    def fake_extract(path, metadata=None):
        extracted.append(path)
        return (answer_page,)

    monkeypatch.setattr(public_importer, "extract_offline_structured_pages", fake_extract)
    answer_text = public_importer.CleanTextResult([], 1, False, None, None, 0, [])
    meta = public_importer.PdfMeta(
        Path("question.pdf"), "question.pdf", "문제", "해경", "항해학", 2025, 1, "doc", "해경", 5
    )

    parsed, answer_key = public_importer.build_ocr_required_exam(
        Path("question.pdf"),
        meta,
        answer_text,
        "file:///question.pdf",
        answer_path=Path("answer.pdf"),
    )

    assert extracted == [Path("answer.pdf")]
    assert answer_key == {1: 1, 2: 2, 3: 3, 4: 4, 5: 1}
    assert [question.correct_answer for question in parsed.questions] == [1, 2, 3, 4, 1]
