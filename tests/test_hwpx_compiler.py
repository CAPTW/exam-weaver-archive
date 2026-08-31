from __future__ import annotations

import dataclasses
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import pytest

from src.exporter.exam_document import AnswerKeyEntry, ExamDocument, ExamSection, QuestionBlock
from src.parser.question import ALL_CHOICES_CORRECT
from tests.hwpx_export_fixture_factory import (
    local_name,
    minimal_document,
    semantic_document,
    variable_choice_document,
)


def _api():
    from src.exporter import DEFAULT_HWPX_PROFILE, HwpxCompiler

    return DEFAULT_HWPX_PROFILE, HwpxCompiler


def _elements(root: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in root.iter() if local_name(element.tag) == name]


def _paragraph_texts(path: Path, section_index: int) -> list[str]:
    with ZipFile(path) as package:
        root = ET.fromstring(package.read(f"Contents/section{section_index}.xml"))
    return [
        "".join((node.text or "") for node in paragraph.iter() if local_name(node.tag) == "t")
        for paragraph in _elements(root, "p")
    ]


def test_default_profile_is_immutable_and_matches_accepted_safe_layout() -> None:
    profile, _compiler = _api()

    assert dataclasses.is_dataclass(profile)
    assert (profile.page_width, profile.page_height) == (72852, 103180)
    assert (profile.margin_left, profile.margin_right) == (3402, 3402)
    assert (profile.margin_top, profile.margin_bottom) == (5102, 1984)
    assert profile.cover_columns == 1
    assert profile.body_columns == 2
    assert profile.body_column_gap == 2268
    assert profile.answer_key_layout_columns == 1
    assert (profile.answer_key_rows, profile.answer_key_table_columns) == (12, 8)
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.page_width = 1


def test_cover_body_and_answer_key_have_exact_layout_segments(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "layouts.hwpx"

    compiler_type().export_document(minimal_document(include_answer_key=True), destination)

    with ZipFile(destination) as package:
        roots = [
            ET.fromstring(package.read(f"Contents/section{index}.xml"))
            for index in range(3)
        ]
    page_prs = [_elements(root, "pagePr")[0] for root in roots]
    margins = [_elements(root, "margin")[0] for root in roots]
    columns = [_elements(root, "colPr")[0] for root in roots]
    assert [(item.attrib["width"], item.attrib["height"]) for item in page_prs] == [
        ("72852", "103180"),
        ("72852", "103180"),
        ("72852", "103180"),
    ]
    assert [
        (item.attrib["left"], item.attrib["right"], item.attrib["top"], item.attrib["bottom"])
        for item in margins
    ] == [("3402", "3402", "5102", "1984")] * 3
    assert [(item.attrib["colCount"], item.attrib["sameGap"]) for item in columns] == [
        ("1", "0"),
        ("2", "2268"),
        ("1", "0"),
    ]
    assert roots[2].attrib.get("data-new-page") == "1"


def test_master_pages_are_empty_repository_authored_even_and_odd_roles(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "masters.hwpx"

    compiler_type().export_document(minimal_document(), destination)

    with ZipFile(destination) as package:
        masters = [
            ET.fromstring(package.read("Contents/masterpage0.xml")),
            ET.fromstring(package.read("Contents/masterpage1.xml")),
        ]
    assert [master.attrib["type"] for master in masters] == ["EVEN", "ODD"]
    assert all(not _elements(master, "t") for master in masters)


def test_semantic_multiline_titles_sections_numbers_and_choices_keep_order(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "semantics.hwpx"

    result = compiler_type().export_document(semantic_document(), destination)

    cover = _paragraph_texts(destination, 0)
    body = _paragraph_texts(destination, 1)
    assert [text for text in cover if text] == ["2026 해기사", "기관사"]
    assert result.section_count == 2
    assert result.question_count == 3
    assert body.index("기관일반") < body.index("7. 당직자는 무엇을 확인하는가?")
    assert body.index("해사영어") < body.index("9. Choose the correct signal.")
    choice_positions = [
        body.index(f"{marker} 선택-{number}")
        for number, marker in enumerate(("㉮", "㉯", "㉴", "㉵"), start=1)
    ]
    assert choice_positions == sorted(choice_positions)
    visible = "\n".join(body)
    assert "db-private" not in visible
    assert "group-private-id" not in visible


def test_semantic_shared_passage_is_rendered_once_at_source_position(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "passage.hwpx"

    compiler_type().export_document(semantic_document(), destination)

    body = _paragraph_texts(destination, 1)
    passage = "[공통지문] 공통 안전 수칙"
    assert body.count(passage) == 1
    assert body.index("기관일반") < body.index(passage) < body.index("7. 당직자는 무엇을 확인하는가?")


def test_semantic_variable_choice_counts_and_tuple_order_ignore_original_number(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "choices.hwpx"

    result = compiler_type().export_document(variable_choice_document(), destination)

    body = _paragraph_texts(destination, 1)
    assert result.question_count == 3
    cursor = -1
    markers = ("㉮", "㉯", "㉴", "㉵", "⑤", "6", "7", "8", "9", "10")
    for count in (4, 5, 10):
        for number, marker in enumerate(markers[:count], start=1):
            cursor = body.index(f"{marker} 선택-{number}", cursor + 1)


def test_semantic_descriptive_answer_preserves_paragraphs_and_has_no_choices(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "descriptive.hwpx"

    compiler_type().export_document(semantic_document(), destination)

    body = _paragraph_texts(destination, 1)
    assert "8. 복원성을 설명하시오." in body
    assert "두 문장으로 쓰시오." in body
    assert "모범답안: 원위치로 돌아오려는 성질" in body
    answer_index = body.index("모범답안: 원위치로 돌아오려는 성질")
    assert body[answer_index - 1] == "두 문장으로 쓰시오."


def test_semantic_mixed_unicode_xml_sensitive_and_invalid_controls_stay_visible(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    document = ExamDocument(
        title_lines=(),
        sections=(
            ExamSection(
                None,
                (
                    QuestionBlock(
                        1,
                        1,
                        1,
                        "descriptive",
                        "한글 & <English> 😀\x01끝",
                        None,
                        None,
                        (),
                        None,
                        False,
                        None,
                        None,
                    ),
                ),
            ),
        ),
        answer_key=(),
        include_answer_key=False,
    )
    destination = tmp_path / "unicode.hwpx"

    compiler_type().export_document(document, destination)

    assert [text for text in _paragraph_texts(destination, 0) if text] == []
    visible = "\n".join(_paragraph_texts(destination, 1))
    assert "1. 한글 & <English> 😀�끝" in visible


def _answer_only_document(entries: tuple[AnswerKeyEntry, ...], *, include: bool = True) -> ExamDocument:
    return ExamDocument(("정답표",), (ExamSection(None, ()),), entries, include)


def _answer_tables(path: Path) -> list[ET.Element]:
    with ZipFile(path) as package:
        root = ET.fromstring(package.read("Contents/section2.xml"))
    return _elements(root, "tbl")


def _table_cell_texts(table: ET.Element) -> list[str]:
    return [
        "".join(node.text or "" for node in cell.iter() if local_name(node.tag) == "t")
        for cell in _elements(table, "tc")
    ]


def test_answer_contract_absent_when_disabled_or_empty(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    disabled = tmp_path / "disabled.hwpx"
    empty = tmp_path / "empty.hwpx"

    compiler_type().export_document(
        _answer_only_document((AnswerKeyEntry(1, "objective", 1, True),), include=False),
        disabled,
    )
    compiler_type().export_document(_answer_only_document((), include=True), empty)

    for path in (disabled, empty):
        with ZipFile(path) as package:
            assert "Contents/section2.xml" not in package.namelist()


def test_answer_contract_one_entry_uses_native_12x8_table(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    destination = tmp_path / "one-answer.hwpx"

    result = compiler_type().export_document(
        _answer_only_document((AnswerKeyEntry(1, "objective", 2, True),)),
        destination,
    )

    tables = _answer_tables(destination)
    assert result.table_count == 1
    assert len(tables) == 1
    assert (tables[0].attrib["rowCnt"], tables[0].attrib["colCnt"]) == ("12", "8")
    cells = _table_cell_texts(tables[0])
    assert cells[:8] == ["번호", "정답"] * 4
    assert cells[8:10] == ["1", "㉯"]
    assert len(cells) == 96


@pytest.mark.parametrize(
    ("count", "expected_tables", "continuation"),
    [(44, 1, False), (45, 2, True), (100, 3, True)],
)
def test_answer_contract_44_45_100_entries_continue_deterministically(
    tmp_path: Path,
    count: int,
    expected_tables: int,
    continuation: bool,
) -> None:
    _profile, compiler_type = _api()
    entries = tuple(AnswerKeyEntry(number, "objective", (number - 1) % 5 + 1, True) for number in range(1, count + 1))
    destination = tmp_path / f"answers-{count}.hwpx"

    result = compiler_type().export_document(_answer_only_document(entries), destination)

    tables = _answer_tables(destination)
    assert len(tables) == expected_tables
    assert all((table.attrib["rowCnt"], table.attrib["colCnt"]) == ("12", "8") for table in tables)
    visible_numbers = []
    for table in tables:
        cells = _table_cell_texts(table)[8:]
        visible_numbers.extend(int(cells[index]) for index in range(0, len(cells), 2) if cells[index])
    assert visible_numbers == list(range(1, count + 1))
    assert ("HWPX_ANSWER_KEY_CONTINUATION" in result.warnings) is continuation


def test_answer_contract_special_values_are_visible_and_never_inferred(tmp_path: Path) -> None:
    _profile, compiler_type = _api()
    entries = (
        AnswerKeyEntry(1, "objective", 2, True),
        AnswerKeyEntry(2, "descriptive", 0, True),
        AnswerKeyEntry(3, "objective", ALL_CHOICES_CORRECT, True),
        AnswerKeyEntry(4, "objective", None, False),
    )
    destination = tmp_path / "special-answers.hwpx"

    compiler_type().export_document(_answer_only_document(entries), destination)

    cells = _table_cell_texts(_answer_tables(destination)[0])
    assert cells[8:16] == ["1", "㉯", "2", "서술형", "3", "전원 정답", "4", "-"]
