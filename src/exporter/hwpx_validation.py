"""Fail-closed package and canonical semantic-readback validation."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from src.document_source.adapters.hwpx import HwpxSourceAdapter
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentImage,
    DocumentParagraph,
    DocumentSourceFormat,
    DocumentTable,
)
from src.document_source.signatures import probe_document_format

from .hwpx_package import HwpxBuildError, MIMETYPE, local_name
from .hwpx_render import ExpectedTable, RenderManifest


REQUIRED_PARTS = frozenset(
    {
        "mimetype",
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
    }
)
FORBIDDEN_XML = re.compile(br"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
DRIVE_PATH = re.compile(rb"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


@dataclass(frozen=True, slots=True)
class ReadbackSummary:
    success: bool
    diagnostic_error_count: int
    section_count: int
    table_count: int
    image_reference_count: int
    attachment_count: int
    semantic_mismatch_count: int
    layout_mismatch_count: int


def _xml_parts(names: set[str]) -> list[str]:
    return sorted(name for name in names if name.endswith((".xml", ".hpf", ".rdf")))


def _safe_member(name: str) -> bool:
    candidate = PurePosixPath(name)
    return not candidate.is_absolute() and ".." not in candidate.parts and not re.match(r"^[A-Za-z]:", name)


def validate_package(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "package output is empty")
    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            names = [info.filename.replace("\\", "/") for info in infos]
            name_set = set(names)
            if not names or names[0] != "mimetype":
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "mimetype is not first")
            if len(names) != len(name_set):
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "duplicate package member")
            if any(not _safe_member(name) for name in names):
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "unsafe package member")
            if any(info.flag_bits & 0x1 for info in infos):
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "encrypted package member")
            mime_info = infos[0]
            if mime_info.compress_type != zipfile.ZIP_STORED or package.read("mimetype") != MIMETYPE:
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "invalid mimetype contract")
            missing = REQUIRED_PARTS - name_set
            if missing:
                raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "required package part missing")
            for part in _xml_parts(name_set):
                payload = package.read(part)
                if FORBIDDEN_XML.search(payload):
                    raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "DTD or entity declaration forbidden")
                if DRIVE_PATH.search(payload) or b"file://" in payload.lower():
                    raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "local source path embedded")
                try:
                    ET.fromstring(payload)
                except ET.ParseError as exc:
                    raise HwpxBuildError("HWPX_XML_SERIALIZATION_FAILED", "malformed package XML") from exc

            container = ET.fromstring(package.read("META-INF/container.xml"))
            rootfiles = [
                element.attrib.get("full-path", "")
                for element in container.iter()
                if local_name(element.tag) == "rootfile"
            ]
            if rootfiles != ["Contents/content.hpf"] or rootfiles[0] not in name_set:
                raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "container rootfile unresolved")

            content = ET.fromstring(package.read("Contents/content.hpf"))
            manifest_items = [element for element in content.iter() if local_name(element.tag) == "item"]
            manifest_by_id: dict[str, str] = {}
            for element in manifest_items:
                identifier = element.attrib.get("id", "")
                href = element.attrib.get("href", "").replace("\\", "/")
                if not identifier or identifier in manifest_by_id or not href or href not in name_set:
                    raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "manifest item unresolved")
                if not _safe_member(href) or "://" in href:
                    raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "external manifest item forbidden")
                manifest_by_id[identifier] = href
            itemrefs = [element.attrib.get("idref", "") for element in content.iter() if local_name(element.tag) == "itemref"]
            if not itemrefs or any(identifier not in manifest_by_id for identifier in itemrefs):
                raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "spine item unresolved")

            image_references: list[str] = []
            master_references: list[str] = []
            for section_name in sorted(name for name in name_set if re.fullmatch(r"Contents/section\d+\.xml", name)):
                root = ET.fromstring(package.read(section_name))
                image_references.extend(
                    element.attrib.get("binaryItemIDRef", "")
                    for element in root.iter()
                    if local_name(element.tag) == "img"
                )
                master_references.extend(
                    element.attrib.get("idRef", "")
                    for element in root.iter()
                    if local_name(element.tag) == "masterPage"
                )
            for identifier in image_references:
                href = manifest_by_id.get(identifier)
                if not href or not href.startswith("BinData/"):
                    raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "image relationship unresolved")
            for identifier in master_references:
                href = manifest_by_id.get(identifier)
                if not href or not href.startswith("Contents/masterpage"):
                    raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "master-page relationship unresolved")
            declared_media = {
                href for href in manifest_by_id.values() if href.startswith("BinData/")
            }
            actual_media = {name for name in name_set if name.startswith("BinData/")}
            if declared_media != actual_media:
                raise HwpxBuildError("HWPX_RELATIONSHIP_UNRESOLVED", "media manifest does not match package")
    except HwpxBuildError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "unable to inspect HWPX package") from exc

    probe = probe_document_format(path)
    if probe.source_format is not DocumentSourceFormat.HWPX:
        raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "canonical signature probe rejected output")


def _cell_text(cell) -> str:
    return "".join(paragraph.text for paragraph in cell.paragraphs)


def _table_rows(table: DocumentTable) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(_cell_text(cell) for cell in sorted(row.cells, key=lambda value: value.column))
        for row in table.rows
    )


def _compare_table(expected: ExpectedTable, actual: DocumentTable) -> bool:
    return (
        actual.row_count == expected.row_count
        and actual.column_count == expected.column_count
        and _table_rows(actual) == expected.cells_by_row
    )


def _paragraphs_equivalent(expected: tuple[str, ...], actual: tuple[str, ...]) -> bool:
    if expected == actual:
        return True
    if len(expected) != len(actual):
        return False
    # hwpxkit 0.2.1 trims whitespace at character-style run boundaries.  The
    # package XML retains that whitespace, so canonical readback may only be
    # compared modulo whitespace when every non-whitespace code point and every
    # paragraph boundary still match.
    return all(
        re.sub(r"\s+", "", expected_text) == re.sub(r"\s+", "", actual_text)
        for expected_text, actual_text in zip(expected, actual)
    )


def validate_semantic_readback(path: Path, manifest: RenderManifest, expected_attachment_count: int) -> ReadbackSummary:
    try:
        result = HwpxSourceAdapter().parse(str(path))
    except Exception as exc:
        raise HwpxBuildError("HWPX_SEMANTIC_READBACK_FAILED", "canonical HWPX adapter raised") from exc
    errors = [diagnostic for diagnostic in result.diagnostics if diagnostic.severity is DiagnosticSeverity.ERROR]
    if not result.success or result.document is None or errors:
        raise HwpxBuildError("HWPX_SEMANTIC_READBACK_FAILED", "canonical HWPX adapter rejected output")
    document = result.document
    semantic_mismatches = 0
    layout_mismatches = 0
    if len(document.sections) != len(manifest.paragraphs_by_section):
        semantic_mismatches += 1
        layout_mismatches += 1
    for index, expected_paragraphs in enumerate(manifest.paragraphs_by_section):
        if index >= len(document.sections):
            continue
        section = document.sections[index]
        actual_paragraphs = tuple(
            block.text
            for block in section.blocks
            if isinstance(block, DocumentParagraph) and block.text
        )
        if not _paragraphs_equivalent(expected_paragraphs, actual_paragraphs):
            semantic_mismatches += 1
        if section.column_count != manifest.layout_columns[index]:
            layout_mismatches += 1
        actual_gap = int(section.column_gap or 0)
        if actual_gap != manifest.layout_gaps[index]:
            layout_mismatches += 1

    actual_tables_by_section: list[list[DocumentTable]] = []
    actual_images_by_section: list[int] = []
    for section in document.sections:
        actual_tables_by_section.append([block for block in section.blocks if isinstance(block, DocumentTable)])
        actual_images_by_section.append(sum(isinstance(block, DocumentImage) for block in section.blocks))
    expected_by_section: list[list[ExpectedTable]] = [[] for _ in manifest.paragraphs_by_section]
    for table in manifest.tables:
        expected_by_section[table.section_index].append(table)
    for expected_tables, actual_tables in zip(expected_by_section, actual_tables_by_section):
        if len(expected_tables) != len(actual_tables):
            semantic_mismatches += 1
            continue
        semantic_mismatches += sum(
            not _compare_table(expected, actual)
            for expected, actual in zip(expected_tables, actual_tables)
        )
    if tuple(actual_images_by_section) != manifest.image_references_by_section:
        semantic_mismatches += 1
    if len(document.attachments) != expected_attachment_count:
        semantic_mismatches += 1
    if semantic_mismatches or layout_mismatches:
        raise HwpxBuildError(
            "HWPX_SEMANTIC_READBACK_FAILED",
            f"semantic mismatches={semantic_mismatches}, layout mismatches={layout_mismatches}",
        )
    return ReadbackSummary(
        success=True,
        diagnostic_error_count=0,
        section_count=len(document.sections),
        table_count=sum(len(values) for values in actual_tables_by_section),
        image_reference_count=sum(actual_images_by_section),
        attachment_count=len(document.attachments),
        semantic_mismatch_count=0,
        layout_mismatch_count=0,
    )


def validate_and_readback(path: Path, manifest: RenderManifest, expected_attachment_count: int) -> ReadbackSummary:
    validate_package(path)
    return validate_semantic_readback(path, manifest, expected_attachment_count)
