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
                for el in root.iter():
                    loc = _local(el.tag)
                    if loc == "pagePr":
                        page_width = _int(el.attrib.get("width")) or page_width
                        page_height = _int(el.attrib.get("height")) or page_height
                        for child in list(el):
                            if _local(child.tag) == "margin":
                                margin_left = _int(child.attrib.get("left"))
                                margin_right = _int(child.attrib.get("right"))
                                margin_top = _int(child.attrib.get("top"))
                                margin_bottom = _int(child.attrib.get("bottom"))
                    if loc == "colPr":
                        count = _int(el.attrib.get("colCount"))
                        gap = _int(el.attrib.get("sameGap"))
                        if count and count >= 2:
                            column_count = count
                            column_gap = gap
                        elif column_count is None:
                            column_count = count
                            column_gap = gap
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
    )
