from __future__ import annotations

import hashlib
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ENTRY_CAP = 4096
ENTRY_SIZE_CAP = 32 * 1024 * 1024
XML_SIZE_CAP = 8 * 1024 * 1024

_DTD = re.compile(br"<!DOCTYPE|<!ENTITY", re.I)


@dataclass(frozen=True, slots=True)
class PackageMedia:
    part: str
    byte_size: int
    sha256: str
    media_type: str


@dataclass(frozen=True, slots=True)
class PackageMasterPage:
    master_page_id: str
    kind: str
    part: str


@dataclass(frozen=True, slots=True)
class PackageSectionLayout:
    part: str
    page_width: int | None
    page_height: int | None
    column_count: int | None
    column_gap: int | None
    margin_left: int | None
    margin_right: int | None
    margin_top: int | None
    margin_bottom: int | None


@dataclass(frozen=True, slots=True)
class PackageSupplement:
    entries: tuple[str, ...]
    page_width: int | None
    page_height: int | None
    column_count: int | None
    column_gap: int | None
    margin_left: int | None
    margin_right: int | None
    margin_top: int | None
    margin_bottom: int | None
    master_pages: tuple[PackageMasterPage, ...]
    media: tuple[PackageMedia, ...]
    section_parts: tuple[str, ...]
    section_layouts: tuple[PackageSectionLayout, ...]


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _safe_xml(data: bytes) -> ET.Element:
    if len(data) > XML_SIZE_CAP:
        raise ValueError("oversize xml")
    if _DTD.search(data[:4096]):
        raise ValueError("dtd forbidden")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"malformed xml: {exc}") from exc


def _int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def inspect_hwpx_package(path: str | Path) -> PackageSupplement:
    source = Path(path)
    names: list[str] = []
    media: list[PackageMedia] = []
    masters: list[PackageMasterPage] = []
    section_parts: list[str] = []
    section_layouts: list[PackageSectionLayout] = []
    page_width = page_height = None
    column_count = column_gap = None
    margin_left = margin_right = margin_top = margin_bottom = None
    with zipfile.ZipFile(source) as zf:
        infos = zf.infolist()
        if len(infos) > ENTRY_CAP:
            raise ValueError("oversize entry count")
        seen: set[str] = set()
        for info in infos:
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            if name in seen:
                raise ValueError("duplicate zip entry")
            seen.add(name)
            if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
                raise ValueError("absolute path")
            parts = Path(name).parts
            if ".." in parts:
                raise ValueError("traversal")
            if info.flag_bits & 0x1:
                raise ValueError("encrypted entry")
            if info.file_size > ENTRY_SIZE_CAP:
                raise ValueError("oversize")
            names.append(name)
            if name.startswith("BinData/") and not name.endswith("/"):
                digest = hashlib.sha256()
                with zf.open(info, "r") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        digest.update(chunk)
                suffix = Path(name).suffix.lower()
                media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp"}.get(
                    suffix, "application/octet-stream"
                )
                media.append(PackageMedia(part=name, byte_size=info.file_size, sha256=digest.hexdigest(), media_type=media_type))
            if re.fullmatch(r"Contents/section\d+\.xml", name):
                section_parts.append(name)
                root = _safe_xml(zf.read(info))
                section_page_width = section_page_height = None
                section_column_count = section_column_gap = None
                section_margin_left = section_margin_right = section_margin_top = section_margin_bottom = None
                layout_seen = False
                for el in root.iter():
                    loc = _local(el.tag)
                    if loc == "pagePr":
                        layout_seen = True
                        section_page_width = _int(el.attrib.get("width"))
                        section_page_height = _int(el.attrib.get("height"))
                        for child in list(el):
                            if _local(child.tag) == "margin":
                                section_margin_left = _int(child.attrib.get("left"))
                                section_margin_right = _int(child.attrib.get("right"))
                                section_margin_top = _int(child.attrib.get("top"))
                                section_margin_bottom = _int(child.attrib.get("bottom"))
                    if loc == "colPr":
                        layout_seen = True
                        section_column_count = _int(el.attrib.get("colCount"))
                        section_column_gap = _int(el.attrib.get("sameGap"))
                if layout_seen:
                    if section_column_count is None:
                        section_column_count = 1
                    layout = PackageSectionLayout(
                        part=name,
                        page_width=section_page_width,
                        page_height=section_page_height,
                        column_count=section_column_count,
                        column_gap=section_column_gap,
                        margin_left=section_margin_left,
                        margin_right=section_margin_right,
                        margin_top=section_margin_top,
                        margin_bottom=section_margin_bottom,
                    )
                    section_layouts.append(layout)
                    page_width = layout.page_width if layout.page_width is not None else page_width
                    page_height = layout.page_height if layout.page_height is not None else page_height
                    margin_left = layout.margin_left
                    margin_right = layout.margin_right
                    margin_top = layout.margin_top
                    margin_bottom = layout.margin_bottom
                    if layout.column_count and layout.column_count >= 2:
                        column_count = layout.column_count
                        column_gap = layout.column_gap
                    elif column_count is None:
                        column_count = layout.column_count
                        column_gap = layout.column_gap
            if re.fullmatch(r"Contents/masterpage\d+\.xml", name):
                root = _safe_xml(zf.read(info))
                kind = root.attrib.get("type") or "UNKNOWN"
                masters.append(PackageMasterPage(master_page_id=Path(name).stem, kind=kind, part=name))
    if column_count is None:
        column_count = 1
    return PackageSupplement(
        entries=tuple(names),
        page_width=page_width,
        page_height=page_height,
        column_count=column_count,
        column_gap=column_gap,
        margin_left=margin_left,
        margin_right=margin_right,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        master_pages=tuple(masters),
        media=tuple(media),
        section_parts=tuple(section_parts),
        section_layouts=tuple(section_layouts),
    )
