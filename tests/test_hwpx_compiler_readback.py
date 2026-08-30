from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from src.document_source.adapters.hwpx import HwpxSourceAdapter
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentImage,
    DocumentParagraph,
    DocumentTable,
)
from src.exporter.exam_document import (
    AnswerKeyEntry,
    ExamChoice,
    ExamDocument,
    ExamSection,
    QuestionBlock,
)
from tests.hwpx_export_fixture_factory import minimal_document, semantic_document


def _compiler():
    from src.exporter import HwpxCompiler

    return HwpxCompiler()


def _parse(path: Path):
    return HwpxSourceAdapter().parse(str(path))


def _paragraph_texts(document, section_index: int) -> list[str]:
    return [
        block.text
        for block in document.sections[section_index].blocks
        if isinstance(block, DocumentParagraph) and block.text
    ]


def _cell_text(cell) -> str:
    return "".join(paragraph.text for paragraph in cell.paragraphs)


def test_readback_canonical_adapter_accepts_package_with_zero_errors_and_exact_layouts(tmp_path: Path) -> None:
    destination = tmp_path / "readback-layout.hwpx"

    _compiler().export_document(minimal_document(include_answer_key=True), destination)
    result = _parse(destination)

    assert result.success is True
    assert result.document is not None
    assert [section.column_count for section in result.document.sections] == [1, 2, 1]
    assert [section.column_gap for section in result.document.sections] == [0.0, 2268.0, 0.0]
    assert [section.page_width for section in result.document.sections] == [72852.0] * 3
    assert [section.page_height for section in result.document.sections] == [103180.0] * 3
    assert [master.kind for master in result.document.master_pages] == ["EVEN", "ODD"]
    assert not [diagnostic for diagnostic in result.diagnostics if diagnostic.severity is DiagnosticSeverity.ERROR]


def test_readback_semantic_titles_sections_passage_questions_choices_and_model_answer(tmp_path: Path) -> None:
    destination = tmp_path / "readback-semantics.hwpx"

    _compiler().export_document(semantic_document(), destination)
    result = _parse(destination)

    assert result.success is True and result.document is not None
    assert _paragraph_texts(result.document, 0) == ["2026 해기사", "기관사"]
    body = _paragraph_texts(result.document, 1)
    expected_in_order = [
        "기관일반",
        "[공통지문] 공통 안전 수칙",
        "7. 당직자는 무엇을 확인하는가?",
        "㉮ 선택-1",
        "㉯ 선택-2",
        "㉴ 선택-3",
        "㉵ 선택-4",
        "8. 복원성을 설명하시오.",
        "두 문장으로 쓰시오.",
        "모범답안: 원위치로 돌아오려는 성질",
        "해사영어",
        "9. Choose the correct signal.",
    ]
    cursor = -1
    for expected in expected_in_order:
        cursor = body.index(expected, cursor + 1)
    assert body.count("[공통지문] 공통 안전 수칙") == 1


def test_readback_native_table_and_image_ownership_survive_canonical_mapping(tmp_path: Path) -> None:
    image = tmp_path / "question.png"
    Image.new("RGB", (12, 8), "orange").save(image, format="PNG")
    table_payload = json.dumps(
        {
            "schema_version": 2,
            "tables": [
                {
                    "id": "readback-table",
                    "rows": [["A", "B"], ["C", "D"]],
                    "cells": [
                        {"row": 0, "col": 0, "text": "A", "row_span": 1, "col_span": 1},
                        {"row": 0, "col": 1, "text": "B", "row_span": 1, "col_span": 1},
                        {"row": 1, "col": 0, "text": "C", "row_span": 1, "col_span": 2},
                    ],
                    "anchor": {"offset": 1, "before_context": "앞", "after_context": "뒤"},
                    "confidence": {"score": 0.99},
                    "complexity": {},
                    "source": {},
                    "render_mode": "native",
                }
            ],
        },
        ensure_ascii=False,
    )
    question = QuestionBlock(
        1,
        1,
        1,
        "objective",
        "앞뒤",
        table_payload,
        str(image),
        (ExamChoice(1, 1, "㉮", "정답", None, None),),
        1,
        True,
        None,
        None,
    )
    document = ExamDocument(("표 그림",), (ExamSection(None, (question,)),), (), False)
    destination = tmp_path / "readback-table-image.hwpx"

    _compiler().export_document(document, destination)
    result = _parse(destination)

    assert result.success is True and result.document is not None
    tables = [block for block in result.document.sections[1].blocks if isinstance(block, DocumentTable)]
    images = [block for block in result.document.sections[1].blocks if isinstance(block, DocumentImage)]
    assert len(tables) == 1
    assert (tables[0].row_count, tables[0].column_count) == (2, 2)
    assert [[_cell_text(cell) for cell in row.cells] for row in tables[0].rows] == [["A", "B"], ["C"]]
    assert len(images) == 1
    assert len(result.document.attachments) == 1
    assert images[0].attachment_id == result.document.attachments[0].attachment_id


def test_readback_long_100_question_exam_and_answer_continuations_are_complete(tmp_path: Path) -> None:
    choices = tuple(ExamChoice(number, number, str(number), f"보기-{number}", None, None) for number in range(1, 5))
    questions = tuple(
        QuestionBlock(
            number,
            number,
            number,
            "objective",
            f"장문 문제 {number}",
            None,
            None,
            choices,
            (number - 1) % 4 + 1,
            True,
            None,
            None,
        )
        for number in range(1, 101)
    )
    answers = tuple(
        AnswerKeyEntry(number, "objective", (number - 1) % 4 + 1, True)
        for number in range(1, 101)
    )
    document = ExamDocument(("100문항",), (ExamSection("장문", questions),), answers, True)
    destination = tmp_path / "long-100.hwpx"

    export_result = _compiler().export_document(document, destination)
    result = _parse(destination)

    assert export_result.question_count == 100
    assert "HWPX_ANSWER_KEY_CONTINUATION" in export_result.warnings
    assert result.success is True and result.document is not None
    body = _paragraph_texts(result.document, 1)
    question_lines = [text for text in body if text.partition(". ")[0].isdigit()]
    assert question_lines == [f"{number}. 장문 문제 {number}" for number in range(1, 101)]
    answer_tables = [block for block in result.document.sections[2].blocks if isinstance(block, DocumentTable)]
    assert len(answer_tables) == 3
    assert all((table.row_count, table.column_count) == (12, 8) for table in answer_tables)
