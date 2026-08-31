from __future__ import annotations

import dataclasses
import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from zipfile import ZIP_STORED, ZipFile

import pytest

from tests.hwpx_export_fixture_factory import local_name, minimal_document
from src.exporter.exam_document import ExamDocument, ExamSection, QuestionBlock


def _api():
    from src.exporter import HwpxCompileError, HwpxCompiler, HwpxExportResult

    return HwpxCompileError, HwpxCompiler, HwpxExportResult


def test_minimal_export_exposes_immutable_result_and_canonical_members(tmp_path: Path) -> None:
    _error, compiler_type, result_type = _api()
    destination = tmp_path / "minimal.hwpx"

    result = compiler_type().export_document(minimal_document(), destination)

    assert isinstance(result, result_type)
    assert dataclasses.is_dataclass(result)
    assert result.output_path == destination
    assert result.output_bytes == destination.stat().st_size
    assert len(result.package_sha256) == 64
    assert len(result.semantic_digest) == 64
    assert result.section_count == 1
    assert result.question_count == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.output_bytes = 0

    with ZipFile(destination) as package:
        names = package.namelist()
        assert names[0] == "mimetype"
        assert package.getinfo("mimetype").compress_type == ZIP_STORED
        assert package.read("mimetype") == b"application/hwp+zip"
        assert {
            "version.xml",
            "META-INF/container.xml",
            "META-INF/manifest.xml",
            "settings.xml",
            "Contents/header.xml",
            "Contents/masterpage0.xml",
            "Contents/masterpage1.xml",
            "Contents/section0.xml",
            "Contents/section1.xml",
            "Contents/content.hpf",
        }.issubset(names)


def test_package_members_are_safe_unique_and_have_fixed_metadata(tmp_path: Path) -> None:
    _error, compiler_type, _result = _api()
    destination = tmp_path / "safe.hwpx"

    compiler_type().export_document(minimal_document(), destination)

    with ZipFile(destination) as package:
        infos = package.infolist()
        names = [info.filename for info in infos]
        assert len(names) == len(set(names))
        assert {info.date_time for info in infos} == {(1980, 1, 1, 0, 0, 0)}
        assert all(not PurePosixPath(name).is_absolute() for name in names)
        assert all(".." not in PurePosixPath(name).parts for name in names)
        assert all(not (info.flag_bits & 0x1) for info in infos)


def test_all_xml_and_declared_local_package_relationships_resolve(tmp_path: Path) -> None:
    _error, compiler_type, _result = _api()
    destination = tmp_path / "relationships.hwpx"

    compiler_type().export_document(minimal_document(), destination)

    with ZipFile(destination) as package:
        names = set(package.namelist())
        for name in names:
            if name.endswith((".xml", ".hpf")):
                payload = package.read(name)
                assert b"<!DOCTYPE" not in payload.upper()
                assert b"<!ENTITY" not in payload.upper()
                ET.fromstring(payload)

        container = ET.fromstring(package.read("META-INF/container.xml"))
        rootfiles = [element.attrib["full-path"] for element in container.iter() if local_name(element.tag) == "rootfile"]
        assert rootfiles == ["Contents/content.hpf"]
        assert rootfiles[0] in names

        content = ET.fromstring(package.read("Contents/content.hpf"))
        hrefs = [element.attrib["href"] for element in content.iter() if local_name(element.tag) == "item"]
        assert hrefs
        assert all(href in names for href in hrefs)
        assert all("://" not in href for href in hrefs)


def _formatted_document() -> ExamDocument:
    text = "U B I S T C \\overline{x}"
    spans = [
        {"start": 0, "end": 1, "underline": True, "shadow": True},
        {"start": 2, "end": 3, "bold": True},
        {"start": 4, "end": 5, "italic": True},
        {"start": 6, "end": 7, "superscript": True},
        {"start": 8, "end": 9, "subscript": True},
        {"start": 10, "end": 11, "font_size": 1400, "text_color": "#FF0000"},
        {"start": 12, "end": 24, "latex": "\\overline{x}"},
    ]
    block = QuestionBlock(
        1,
        1,
        1,
        "descriptive",
        text,
        json.dumps({"schema_version": 2, "spans": spans}),
        None,
        (),
        None,
        False,
        None,
        None,
    )
    return ExamDocument(("결정성",), (ExamSection(None, (block,)),), (), False)


def test_determinism_atomicity_same_semantics_and_media_produce_identical_bytes(tmp_path: Path) -> None:
    _error, compiler_type, _result = _api()
    document = _formatted_document()
    first = tmp_path / "first.hwpx"
    second = tmp_path / "second.hwpx"

    first_result = compiler_type().export_document(document, first)
    second_result = compiler_type().export_document(document, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_result.package_sha256 == second_result.package_sha256
    assert first_result.semantic_digest == second_result.semantic_digest
    assert first_result.warnings == second_result.warnings


def test_determinism_atomicity_input_document_remains_deeply_unchanged(tmp_path: Path) -> None:
    _error, compiler_type, _result = _api()
    document = _formatted_document()
    snapshot = copy.deepcopy(document)

    compiler_type().export_document(document, tmp_path / "immutable.hwpx")

    assert document == snapshot
    assert document.sections is snapshot.sections or document.sections == snapshot.sections
    assert document.sections[0].blocks[0].format_json == snapshot.sections[0].blocks[0].format_json


def test_determinism_atomicity_failure_preserves_target_and_removes_temporary_sibling(tmp_path: Path) -> None:
    error_type, compiler_type, _result = _api()
    target = tmp_path / "existing.hwpx"
    original = b"OWNER-EXISTING-TARGET"
    target.write_bytes(original)
    missing = tmp_path / "not-present.png"
    block = QuestionBlock(1, 1, 1, "descriptive", "Q", None, str(missing), (), None, False, None, None)
    document = ExamDocument(("T",), (ExamSection(None, (block,)),), (), False)

    with pytest.raises(error_type) as caught:
        compiler_type().export_document(document, target)

    assert caught.value.code == "HWPX_REQUIRED_IMAGE_MISSING"
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_determinism_atomicity_invalid_extension_has_stable_code_and_no_write(tmp_path: Path) -> None:
    error_type, compiler_type, _result = _api()
    target = tmp_path / "invalid.docx"

    with pytest.raises(error_type) as caught:
        compiler_type().export_document(minimal_document(), target)

    assert caught.value.code == "HWPX_INVALID_OUTPUT_PATH"
    assert not target.exists()


def test_determinism_atomicity_supported_styles_and_fallback_warning_order(tmp_path: Path) -> None:
    _error, compiler_type, _result = _api()
    destination = tmp_path / "styles.hwpx"

    result = compiler_type().export_document(_formatted_document(), destination)

    assert result.warnings == (
        "HWPX_UNSUPPORTED_FORMATTING_AS_TEXT",
        "HWPX_EQUATION_TEXT_FALLBACK",
    )
    with ZipFile(destination) as package:
        body = ET.fromstring(package.read("Contents/section1.xml"))
        header = ET.fromstring(package.read("Contents/header.xml"))
    char_properties = {
        element.attrib["id"]: element
        for element in header.iter()
        if local_name(element.tag) == "charPr"
    }
    referenced = {}
    for run in [element for element in body.iter() if local_name(element.tag) == "run"]:
        value = "".join(node.text or "" for node in run.iter() if local_name(node.tag) == "t")
        if value in {"U", "B", "I", "S", "T", "C"}:
            referenced[value] = char_properties[run.attrib["charPrIDRef"]]
    assert {local_name(child.tag) for child in referenced["U"]} >= {"underline"}
    assert {local_name(child.tag) for child in referenced["B"]} >= {"bold"}
    assert {local_name(child.tag) for child in referenced["I"]} >= {"italic"}
    assert {local_name(child.tag) for child in referenced["S"]} >= {"supscript"}
    assert {local_name(child.tag) for child in referenced["T"]} >= {"subscript"}
    assert referenced["C"].attrib["height"] == "1400"
    assert referenced["C"].attrib["textColor"] == "#FF0000"
