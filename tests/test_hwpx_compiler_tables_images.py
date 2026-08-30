from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from src.exporter.exam_document import (
    AnswerKeyEntry,
    ExamChoice,
    ExamDocument,
    ExamSection,
    QuestionBlock,
    SharedPassageBlock,
)
from tests.hwpx_export_fixture_factory import local_name


def _api():
    from src.exporter import HwpxCompileError, HwpxCompiler

    return HwpxCompileError, HwpxCompiler


def _question_document(text: str, format_json: str) -> ExamDocument:
    question = QuestionBlock(
        1,
        1,
        1,
        "objective",
        text,
        format_json,
        None,
        (ExamChoice(1, 1, "㉮", "정답", None, None),),
        1,
        True,
        None,
        None,
    )
    return ExamDocument(
        ("표 시험",),
        (ExamSection(None, (question,)),),
        (AnswerKeyEntry(1, "objective", 1, True),),
        False,
    )


def _simple_table(*, merged: bool = False, source_image: Path | None = None, complex_table: bool = False) -> str:
    if merged:
        rows = [["A", "B", ""], ["C", "", "D"]]
        cells = [
            {"row": 0, "col": 0, "text": "A", "row_span": 2, "col_span": 1},
            {"row": 0, "col": 1, "text": "B", "row_span": 1, "col_span": 2},
            {"row": 1, "col": 1, "text": "D", "row_span": 1, "col_span": 2},
        ]
    else:
        rows = [["A", "B"], ["C", "D"]]
        cells = [
            {"row": 0, "col": 0, "text": "A", "row_span": 1, "col_span": 1, "horizontal_alignment": "left", "vertical_alignment": "top"},
            {"row": 0, "col": 1, "text": "B", "row_span": 1, "col_span": 1, "horizontal_alignment": "center", "vertical_alignment": "center"},
            {"row": 1, "col": 0, "text": "C", "row_span": 1, "col_span": 1, "horizontal_alignment": "right", "vertical_alignment": "bottom"},
            {"row": 1, "col": 1, "text": "D", "row_span": 1, "col_span": 1},
        ]
    payload = {
        "schema_version": 2,
        "tables": [
            {
                "id": "owned-table",
                "rows": rows,
                "cells": cells,
                "column_widths": [0.4, 0.6] if not merged else [0.25, 0.35, 0.4],
                "layout": {"width_mode": "manual", "wide": False},
                "anchor": {"offset": 1, "before_context": "앞", "after_context": "뒤"},
                "confidence": {"score": 0.99, "reasons": []},
                "complexity": {"has_formula": complex_table},
                "source": {"image_path": str(source_image)} if source_image else {},
                "render_mode": "auto",
            }
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _body_root(path: Path) -> ET.Element:
    with ZipFile(path) as package:
        return ET.fromstring(package.read("Contents/section1.xml"))


def _elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) == name]


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter() if local_name(node.tag) == "t")


def _ordered_visible_blocks(root: ET.Element) -> list[str]:
    blocks = []
    for paragraph in [node for node in list(root) if local_name(node.tag) == "p"]:
        tables = _elements(paragraph, "tbl")
        if tables:
            blocks.append("TABLE:" + "|".join(_paragraph_text(cell) for cell in _elements(tables[0], "tc")))
        else:
            text = _paragraph_text(paragraph)
            if text:
                blocks.append("TEXT:" + text)
    return blocks


def _write_image(path: Path, image_format: str, color: str) -> bytes:
    Image.new("RGB", (12, 8), color).save(path, format=image_format)
    return path.read_bytes()


def test_table_image_simple_native_table_keeps_anchor_order_and_dimensions(tmp_path: Path) -> None:
    _error, compiler_type = _api()
    destination = tmp_path / "native-table.hwpx"

    result = compiler_type().export_document(_question_document("앞뒤", _simple_table()), destination)

    root = _body_root(destination)
    tables = _elements(root, "tbl")
    assert result.table_count == 1
    assert len(tables) == 1
    assert (tables[0].attrib["rowCnt"], tables[0].attrib["colCnt"]) == ("2", "2")
    assert _ordered_visible_blocks(root)[:3] == ["TEXT:1. 앞", "TABLE:A|B|C|D", "TEXT:뒤"]


def test_table_image_merged_native_table_has_nonoverlapping_row_and_column_spans(tmp_path: Path) -> None:
    _error, compiler_type = _api()
    destination = tmp_path / "merged-table.hwpx"

    compiler_type().export_document(_question_document("앞뒤", _simple_table(merged=True)), destination)

    table = _elements(_body_root(destination), "tbl")[0]
    cells = []
    covered: set[tuple[int, int]] = set()
    for cell in _elements(table, "tc"):
        address = _elements(cell, "cellAddr")[0].attrib
        span = _elements(cell, "cellSpan")[0].attrib
        row, column = int(address["rowAddr"]), int(address["colAddr"])
        row_span, column_span = int(span["rowSpan"]), int(span["colSpan"])
        coordinates = {
            (r, c)
            for r in range(row, row + row_span)
            for c in range(column, column + column_span)
        }
        assert not (covered & coordinates)
        covered.update(coordinates)
        cells.append((row, column, row_span, column_span, _paragraph_text(cell)))
    assert cells == [(0, 0, 2, 1, "A"), (0, 1, 1, 2, "B"), (1, 1, 1, 2, "D")]
    assert covered == {(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)}


def test_table_image_complex_table_uses_supplied_image_with_explicit_warning(tmp_path: Path) -> None:
    _error, compiler_type = _api()
    source = tmp_path / "table.png"
    _write_image(source, "PNG", "blue")
    destination = tmp_path / "table-image-fallback.hwpx"

    result = compiler_type().export_document(
        _question_document("앞뒤", _simple_table(source_image=source, complex_table=True)),
        destination,
    )

    root = _body_root(destination)
    assert "HWPX_TABLE_IMAGE_FALLBACK" in result.warnings
    assert result.fallback_count == 1
    assert len(_elements(root, "pic")) == 1
    assert not _elements(root, "tbl")


def test_table_image_complex_table_without_image_preserves_all_text(tmp_path: Path) -> None:
    _error, compiler_type = _api()
    destination = tmp_path / "table-text-fallback.hwpx"

    result = compiler_type().export_document(
        _question_document("앞뒤", _simple_table(complex_table=True)),
        destination,
    )

    visible = "\n".join(_paragraph_text(item) for item in _elements(_body_root(destination), "p"))
    assert "HWPX_TABLE_TEXT_FALLBACK" in result.warnings
    assert result.fallback_count == 1
    assert "A | B" in visible
    assert "C | D" in visible


def test_table_image_question_passage_and_choice_images_keep_ownership_and_deduplicate_bytes(tmp_path: Path) -> None:
    _error, compiler_type = _api()
    shared_png = tmp_path / "shared.png"
    duplicate_png = tmp_path / "duplicate.png"
    jpeg = tmp_path / "passage.jpg"
    png_bytes = _write_image(shared_png, "PNG", "green")
    duplicate_png.write_bytes(png_bytes)
    _write_image(jpeg, "JPEG", "red")
    passage = SharedPassageBlock("g", "그림 공통지문", str(jpeg))
    question = QuestionBlock(
        1,
        1,
        1,
        "objective",
        "그림 문제",
        None,
        str(shared_png),
        (
            ExamChoice(1, 1, "㉮", "", None, str(duplicate_png)),
            ExamChoice(2, 2, "㉯", "텍스트", None, None),
        ),
        2,
        True,
        None,
        "g",
    )
    document = ExamDocument(
        ("이미지",),
        (ExamSection(None, (passage, question)),),
        (AnswerKeyEntry(1, "objective", 2, True),),
        False,
    )
    destination = tmp_path / "owned-images.hwpx"

    result = compiler_type().export_document(document, destination)

    with ZipFile(destination) as package:
        media = [name for name in package.namelist() if name.startswith("BinData/")]
        body = ET.fromstring(package.read("Contents/section1.xml"))
    assert len(media) == 2
    assert result.image_count == 2
    assert len(_elements(body, "pic")) == 3
    refs = [element.attrib["binaryItemIDRef"] for element in _elements(body, "img")]
    assert refs[1] == refs[2]
    assert refs[0] != refs[1]
    assert hashlib.sha256(shared_png.read_bytes()).hexdigest() == hashlib.sha256(duplicate_png.read_bytes()).hexdigest()


def test_table_image_missing_required_and_convertible_gif_have_stable_policy(tmp_path: Path) -> None:
    error_type, compiler_type = _api()
    missing = tmp_path / "missing.png"
    target = tmp_path / "missing.hwpx"
    broken = QuestionBlock(1, 1, 1, "descriptive", "Q", None, str(missing), (), None, False, None, None)
    broken_document = ExamDocument(("T",), (ExamSection(None, (broken,)),), (), False)
    with pytest.raises(error_type) as caught:
        compiler_type().export_document(broken_document, target)
    assert caught.value.code == "HWPX_REQUIRED_IMAGE_MISSING"

    gif = tmp_path / "convert.gif"
    _write_image(gif, "GIF", "purple")
    converted = QuestionBlock(1, 1, 1, "descriptive", "Q", None, str(gif), (), None, False, None, None)
    converted_document = ExamDocument(("T",), (ExamSection(None, (converted,)),), (), False)
    converted_target = tmp_path / "converted.hwpx"
    result = compiler_type().export_document(converted_document, converted_target)
    assert "HWPX_IMAGE_CONVERTED_TO_PNG" in result.warnings
    with ZipFile(converted_target) as package:
        media = [name for name in package.namelist() if name.startswith("BinData/")]
    assert len(media) == 1 and media[0].endswith(".png")
