import ast
import copy
import inspect
import json
import random
from pathlib import Path

import pytest

from src.parser.question import ALL_CHOICES_CORRECT
from src.parser.table_format import parse_format_payload


def _builder_mod():
    from src.exporter.builder import ExamDocumentBuilder, freeze_format_payload, split_title

    return ExamDocumentBuilder, freeze_format_payload, split_title


def _model_mod():
    from src.exporter.exam_document import (
        AnswerKeyEntry,
        ExamChoice,
        ExamDocument,
        ExamSection,
        QuestionBlock,
        SharedPassageBlock,
    )

    return AnswerKeyEntry, ExamChoice, ExamDocument, ExamSection, QuestionBlock, SharedPassageBlock


def _exporter():
    from src.exporter.docx import DocxExporter

    return DocxExporter


MODULE_ROOT = Path(__file__).resolve().parents[1] / "src" / "exporter"


def _four_choices():
    return [
        {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
        {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
        {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
        {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
    ]


def test_exam_document_contracts_are_immutable():
    AnswerKeyEntry, ExamChoice, ExamDocument, ExamSection, QuestionBlock, SharedPassageBlock = _model_mod()
    choice = ExamChoice(1, 1, "㉮", "A", None, None)
    block = QuestionBlock(1, 9, 1, "objective", "Q", None, None, (choice,), 1, True, None, None)
    section = ExamSection("S", (block,))
    document = ExamDocument(("T",), (section,), (AnswerKeyEntry(1, "objective", 1, True),), False)
    with pytest.raises(Exception):
        document.title_lines = ("X",)
    with pytest.raises(Exception):
        block.text = "nope"
    assert isinstance(document.sections, tuple)
    assert isinstance(block.choices, tuple)


def test_model_module_has_no_forbidden_imports():
    source = (MODULE_ROOT / "exam_document.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    joined = " ".join(imported)
    assert "docx" not in joined
    assert "PyQt5" not in joined
    assert "qfluentwidgets" not in joined
    assert "sqlite3" not in joined
    assert "database" not in joined
    assert "gui" not in joined


def test_builder_module_has_no_forbidden_imports():
    source = (MODULE_ROOT / "builder.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    joined = " ".join(imported)
    assert "docx" not in joined
    assert "PyQt5" not in joined
    assert "sqlite3" not in joined
    assert "gui" not in joined


def test_format_payload_cannot_be_mutated_through_source_dict():
    payload = {"spans": [{"start": 0, "end": 1}]}
    original = copy.deepcopy(payload)
    _, freeze_format_payload, _ = _builder_mod()
    frozen = freeze_format_payload(payload)
    payload["spans"].append({"start": 2, "end": 3})
    assert parse_format_payload(original) == parse_format_payload(frozen)


def test_title_splitting_matches_legacy():
    _, _, split_title = _builder_mod()
    assert split_title("A\n\n B \n") == ("A", "B")
    assert split_title("   \n") == ("",)
    assert split_title("") == ("",)


def test_builder_uses_top_level_questions_when_sections_empty():
    questions = [{"question_text": "Q1", "choices": _four_choices(), "correct_answer": 1}]
    ExamDocumentBuilder, _, _ = _builder_mod()
    document = ExamDocumentBuilder().build("T", questions, sections=[])
    assert len(document.sections) == 1
    assert document.sections[0].title is None
    assert document.sections[0].blocks[0].text == "Q1"


def test_builder_truthy_sections_override_top_level_questions():
    ExamDocumentBuilder, _, _ = _builder_mod()
    _, _, _, _, QuestionBlock, _ = _model_mod()
    unused = [{"question_text": "UNUSED", "choices": [], "correct_answer": 1}]
    sections = [{"title": "기관1", "questions": [{"question_text": "USED", "choices": [], "correct_answer": 1}]}]
    document = ExamDocumentBuilder().build("T", unused, sections=sections)
    texts = [b.text for b in document.sections[0].blocks if isinstance(b, QuestionBlock)]
    assert texts == ["USED"]


def test_numbering_continues_across_sections_and_resets_group_state():
    sections = [
        {
            "title": "S1",
            "questions": [
                {"question_text": "G1A", "group_id": 1, "shared_passage": "PASS", "choices": [], "correct_answer": 1},
                {"question_text": "G1B", "group_id": 1, "shared_passage": "PASS", "choices": [], "correct_answer": 1},
            ],
        },
        {
            "title": "S2",
            "questions": [
                {"question_text": "G1C", "group_id": 1, "shared_passage": "PASS", "choices": [], "correct_answer": 1},
                {"question_text": "U", "group_id": None, "shared_passage": "NO", "choices": [], "correct_answer": 1},
                {"question_text": "G1D", "group_id": 1, "shared_passage": "PASS", "choices": [], "correct_answer": 1},
            ],
        },
    ]
    ExamDocumentBuilder, _, _ = _builder_mod()
    _, _, _, _, QuestionBlock, SharedPassageBlock = _model_mod()
    document = ExamDocumentBuilder().build("T", [], sections=sections)
    assert [s.title for s in document.sections] == ["S1", "S2"]
    s1 = document.sections[0].blocks
    s2 = document.sections[1].blocks
    assert isinstance(s1[0], SharedPassageBlock)
    assert [b.display_number for b in s1 if isinstance(b, QuestionBlock)] == [1, 2]
    assert [b.display_number for b in s2 if isinstance(b, QuestionBlock)] == [3, 4, 5]
    assert isinstance(s2[0], SharedPassageBlock)
    assert isinstance(s2[2], QuestionBlock) and s2[2].text == "U"
    assert isinstance(s2[3], SharedPassageBlock)


def test_builder_does_not_mutate_source_inputs():
    questions = [{"question_text": "Q", "choices": _four_choices(), "correct_answer": 2, "question_format_json": {"spans": []}}]
    sections = [{"title": "S", "questions": questions}]
    q_before = copy.deepcopy(questions)
    s_before = copy.deepcopy(sections)
    ExamDocumentBuilder, _, _ = _builder_mod()
    ExamDocumentBuilder().build("T", questions, sections=sections, shuffle_choices=True, rng=random.Random(0))
    assert questions == q_before
    assert sections == s_before


def test_object_choices_are_normalized_and_special_answers_preserved():
    class Choice:
        def __init__(self, number, symbol, text):
            self.number = number
            self.symbol = symbol
            self.text = text
            self.image_path = None
            self.format_json = None

    ExamDocumentBuilder, _, _ = _builder_mod()
    document = ExamDocumentBuilder().build(
        "T",
        [
            {
                "question_text": "all",
                "correct_answer": ALL_CHOICES_CORRECT,
                "answer_available": True,
                "choices": [Choice(1, "㉮", "A"), Choice(2, "㉯", "B"), Choice(3, "㉴", "C"), Choice(4, "㉵", "D")],
            },
            {"question_text": "missing", "correct_answer": None, "answer_available": False, "choices": _four_choices()},
            {"question_text": "desc", "question_type": "descriptive", "model_answer": "답", "choices": []},
        ],
    )
    assert document.sections[0].blocks[0].correct_answer == ALL_CHOICES_CORRECT
    assert document.sections[0].blocks[0].choices[0].text == "A"
    assert document.sections[0].blocks[1].correct_answer is None
    assert document.sections[0].blocks[1].answer_available is False
    assert document.sections[0].blocks[2].model_answer == "답"
    assert document.answer_key[2].question_type == "descriptive"


def test_four_choice_shuffle_remaps_and_five_choices_do_not_shuffle():
    four = [{"question_text": "4", "correct_answer": 2, "choices": _four_choices()}]
    five = [
        {
            "question_text": "5",
            "correct_answer": 5,
            "choices": _four_choices() + [{"choice_number": 5, "choice_symbol": "⑤", "choice_text": "E"}],
        }
    ]
    ExamDocumentBuilder, _, _ = _builder_mod()
    shuffled = ExamDocumentBuilder().build("T", four, shuffle_choices=True, rng=random.Random(1))
    unshuffled = ExamDocumentBuilder().build("T", five, shuffle_choices=True, rng=random.Random(1))
    numbers = [c.number for c in shuffled.sections[0].blocks[0].choices]
    assert numbers == [1, 2, 3, 4]
    original_correct = next(
        c.original_number
        for c in shuffled.sections[0].blocks[0].choices
        if c.number == shuffled.sections[0].blocks[0].correct_answer
    )
    assert original_correct == 2
    assert [c.text for c in unshuffled.sections[0].blocks[0].choices] == ["A", "B", "C", "D", "E"]
    assert unshuffled.sections[0].blocks[0].correct_answer == 5


def test_export_document_matches_legacy_export_semantically(tmp_path):
    questions = [
        {"question_text": "복원성을 설명하시오.", "question_type": "descriptive", "model_answer": "성질", "choices": []},
        {"question_text": "숫자", "correct_answer": 2, "choices": _four_choices()},
    ]
    legacy = tmp_path / "legacy.docx"
    modern = tmp_path / "modern.docx"
    ExamDocumentBuilder, _, _ = _builder_mod()
    DocxExporter = _exporter()
    DocxExporter().export("제목", questions, str(legacy), include_answer_key=True)
    document = ExamDocumentBuilder().build("제목", questions, include_answer_key=True)
    DocxExporter().export_document(document, str(modern))
    from zipfile import ZipFile
    from lxml import etree

    def texts(path):
        with ZipFile(path) as zf:
            xml = etree.fromstring(zf.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return ["".join(p.xpath(".//w:t/text()", namespaces=ns)) for p in xml.xpath("//w:body/w:p", namespaces=ns)]

    assert texts(legacy) == texts(modern)


def test_legacy_export_signature_unchanged():
    DocxExporter = _exporter()
    params = inspect.signature(DocxExporter.export).parameters
    assert list(params) == [
        "self",
        "title",
        "questions",
        "output_path",
        "shuffle_choices",
        "include_answer_key",
        "sections",
    ]


def test_export_document_creates_parent_directory(tmp_path):
    dest = tmp_path / "nested" / "out.docx"
    ExamDocumentBuilder, _, _ = _builder_mod()
    DocxExporter = _exporter()
    document = ExamDocumentBuilder().build("T", [{"question_text": "Q", "choices": [], "correct_answer": 1}])
    DocxExporter().export_document(document, str(dest))
    assert dest.is_file()
