"""Deterministic, repository-authored OWPML/HWPX package primitives."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

from .hwpx_profile import HwpxTemplateProfile


MIMETYPE = b"application/hwp+zip"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

NS = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
    "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    "opf": "http://www.idpf.org/2007/opf/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ocf": "urn:oasis:names:tc:opendocument:xmlns:container",
    "odf": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
    "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
}

for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)


class HwpxBuildError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def q(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean_xml_text(value: object) -> str:
    """Return XML 1.0-safe visible Unicode without changing valid characters."""
    output: list[str] = []
    for character in str(value or ""):
        code = ord(character)
        valid = (
            code in {0x9, 0xA, 0xD}
            or 0x20 <= code <= 0xD7FF
            or 0xE000 <= code <= 0xFFFD
            or 0x10000 <= code <= 0x10FFFF
        )
        output.append(character if valid else "\uFFFD")
    return "".join(output)


def xml_bytes(root: ET.Element) -> bytes:
    try:
        return ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    except (TypeError, ValueError) as exc:
        raise HwpxBuildError("HWPX_XML_SERIALIZATION_FAILED", "unable to serialize OWPML XML") from exc


@dataclass(frozen=True, slots=True)
class StyleSpec:
    height: int = 1000
    text_color: str = "#000000"
    bold: bool = False
    italic: bool = False
    underline: bool = False
    superscript: bool = False
    subscript: bool = False


class StyleRegistry:
    """First-use ordered character-style registry."""

    def __init__(self) -> None:
        self._styles: list[StyleSpec] = []
        self._ids: dict[StyleSpec, int] = {}
        self.body = self.id_for(StyleSpec())
        self.title = self.id_for(StyleSpec(height=1600, bold=True))
        self.heading = self.id_for(StyleSpec(height=1400, bold=True))
        self.label = self.id_for(StyleSpec(height=1000, bold=True))
        self.table = self.id_for(StyleSpec(height=900))

    def id_for(self, style: StyleSpec) -> int:
        found = self._ids.get(style)
        if found is not None:
            return found
        identifier = len(self._styles)
        self._styles.append(style)
        self._ids[style] = identifier
        return identifier

    @property
    def styles(self) -> tuple[StyleSpec, ...]:
        return tuple(self._styles)


class DeterministicIds:
    """Monotonic identifiers scoped to one render."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}

    def next(self, scope: str) -> int:
        value = self._counters.get(scope, 0) + 1
        self._counters[scope] = value
        return value


@dataclass(frozen=True, slots=True)
class MediaPart:
    identifier: str
    member_name: str
    media_type: str
    data: bytes
    pixel_width: int
    pixel_height: int


def _sub(parent: ET.Element, prefix: str, local: str, **attributes: object) -> ET.Element:
    return ET.SubElement(
        parent,
        q(prefix, local),
        {name: str(value) for name, value in attributes.items()},
    )


def _add_fontfaces(ref_list: ET.Element, font_name: str) -> None:
    languages = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
    fontfaces = _sub(ref_list, "hh", "fontfaces", itemCnt=len(languages))
    for language in languages:
        face = _sub(fontfaces, "hh", "fontface", lang=language, fontCnt=1)
        font = _sub(face, "hh", "font", id=0, face=font_name, type="TTF", isEmbedded=0)
        _sub(
            font,
            "hh",
            "typeInfo",
            familyType="FCAT_GOTHIC",
            weight=6,
            proportion=4,
            contrast=0,
            strokeVariation=1,
            armStyle=1,
            letterform=1,
            midline=1,
            xHeight=1,
        )


def _add_border_fill(parent: ET.Element, identifier: int, line_type: str) -> None:
    border = _sub(
        parent,
        "hh",
        "borderFill",
        id=identifier,
        threeD=0,
        shadow=0,
        centerLine="NONE",
        breakCellSeparateLine=0,
    )
    _sub(border, "hh", "slash", type="NONE", Crooked=0, isCounter=0)
    _sub(border, "hh", "backSlash", type="NONE", Crooked=0, isCounter=0)
    for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
        _sub(border, "hh", side, type=line_type, width="0.12 mm", color="#000000")
    _sub(border, "hh", "diagonal", type="NONE", width="0.12 mm", color="#000000")


def _add_char_property(parent: ET.Element, identifier: int, style: StyleSpec) -> None:
    char = _sub(
        parent,
        "hh",
        "charPr",
        id=identifier,
        height=style.height,
        textColor=style.text_color,
        shadeColor="none",
        useFontSpace=0,
        useKerning=0,
        symMark="NONE",
        borderFillIDRef=1,
    )
    language_values = {
        "hangul": 0,
        "latin": 0,
        "hanja": 0,
        "japanese": 0,
        "other": 0,
        "symbol": 0,
        "user": 0,
    }
    _sub(char, "hh", "fontRef", **language_values)
    _sub(char, "hh", "ratio", **{key: 100 for key in language_values})
    _sub(char, "hh", "spacing", **{key: 0 for key in language_values})
    _sub(char, "hh", "relSz", **{key: 100 for key in language_values})
    _sub(char, "hh", "offset", **{key: 0 for key in language_values})
    _sub(
        char,
        "hh",
        "underline",
        type="BOTTOM" if style.underline else "NONE",
        shape="SOLID",
        color="#000000",
    )
    _sub(char, "hh", "strikeout", shape="NONE", color="#000000")
    _sub(char, "hh", "outline", type="NONE")
    _sub(char, "hh", "shadow", type="NONE", color="#B2B2B2", offsetX=10, offsetY=10)
    if style.bold:
        _sub(char, "hh", "bold")
    if style.italic:
        _sub(char, "hh", "italic")
    if style.superscript:
        _sub(char, "hh", "supscript")
    if style.subscript:
        _sub(char, "hh", "subscript")


def _add_para_property(parent: ET.Element, identifier: int, alignment: str) -> None:
    para = _sub(
        parent,
        "hh",
        "paraPr",
        id=identifier,
        tabPrIDRef=0,
        condense=0,
        fontLineHeight=0,
        snapToGrid=1,
        suppressLineNumbers=0,
        checked=0,
    )
    _sub(para, "hh", "align", horizontal=alignment, vertical="BASELINE")
    _sub(para, "hh", "heading", type="NONE", idRef=0, level=0)
    _sub(
        para,
        "hh",
        "breakSetting",
        breakLatinWord="KEEP_WORD",
        breakNonLatinWord="BREAK_WORD",
        widowOrphan=1,
        keepWithNext=0,
        keepLines=0,
        pageBreakBefore=0,
        lineWrap="BREAK",
    )
    switch = _sub(para, "hp", "switch")
    case = _sub(switch, "hp", "case", **{q("hp", "required-namespace"): NS["hp10"]})
    default = _sub(switch, "hp", "default")
    for branch in (case, default):
        margin = _sub(branch, "hh", "margin")
        for name in ("intent", "left", "right", "prev", "next"):
            _sub(margin, "hc", name, value=0, unit="HWPUNIT")
        _sub(branch, "hh", "lineSpacing", type="PERCENT", value=140, unit="HWPUNIT")
    _sub(para, "hh", "autoSpacing", eAsianEng=0, eAsianNum=0)
    _sub(
        para,
        "hh",
        "border",
        borderFillIDRef=1,
        offsetLeft=0,
        offsetRight=0,
        offsetTop=0,
        offsetBottom=0,
        connect=0,
        ignoreMargin=0,
    )


def build_header_xml(styles: StyleRegistry, profile: HwpxTemplateProfile, section_count: int) -> bytes:
    root = ET.Element(q("hh", "head"), {"version": "1.4", "secCnt": str(section_count)})
    _sub(root, "hh", "beginNum", page=1, footnote=1, endnote=1, pic=1, tbl=1, equation=1)
    refs = _sub(root, "hh", "refList")
    _add_fontfaces(refs, profile.font_name)
    border_fills = _sub(refs, "hh", "borderFills", itemCnt=2)
    _add_border_fill(border_fills, 1, "NONE")
    _add_border_fill(border_fills, 2, "SOLID")
    char_properties = _sub(refs, "hh", "charProperties", itemCnt=len(styles.styles))
    for identifier, style in enumerate(styles.styles):
        _add_char_property(char_properties, identifier, style)
    tabs = _sub(refs, "hh", "tabProperties", itemCnt=1)
    _sub(tabs, "hh", "tabPr", id=0, autoTabLeft=0, autoTabRight=0)
    numberings = _sub(refs, "hh", "numberings", itemCnt=1)
    numbering = _sub(numberings, "hh", "numbering", id=1, start=0)
    for level in range(1, 8):
        head = _sub(
            numbering,
            "hh",
            "paraHead",
            start=1,
            level=level,
            align="LEFT",
            useInstWidth=1,
            autoIndent=1,
            widthAdjust=0,
            textOffsetType="PERCENT",
            textOffset=50,
            numFormat="DIGIT",
            charPrIDRef=4294967295,
            checkable=0,
        )
        head.text = f"^{level}."
    para_properties = _sub(refs, "hh", "paraProperties", itemCnt=3)
    _add_para_property(para_properties, 0, "LEFT")
    _add_para_property(para_properties, 1, "CENTER")
    _add_para_property(para_properties, 2, "RIGHT")
    styles_element = _sub(refs, "hh", "styles", itemCnt=3)
    _sub(styles_element, "hh", "style", id=0, type="PARA", name="Exam Body", engName="Exam Body", paraPrIDRef=0, charPrIDRef=styles.body, nextStyleIDRef=0, langID=1042, lockForm=0)
    _sub(styles_element, "hh", "style", id=1, type="PARA", name="Exam Title", engName="Exam Title", paraPrIDRef=1, charPrIDRef=styles.title, nextStyleIDRef=1, langID=1042, lockForm=0)
    _sub(styles_element, "hh", "style", id=2, type="PARA", name="Exam Section", engName="Exam Section", paraPrIDRef=1, charPrIDRef=styles.heading, nextStyleIDRef=2, langID=1042, lockForm=0)
    compatible = _sub(root, "hh", "compatibleDocument", targetProgram="HWP201X")
    _sub(compatible, "hh", "layoutCompatibility")
    option = _sub(root, "hh", "docOption")
    _sub(option, "hh", "linkinfo", path="", pageInherit=0, footnoteInherit=0)
    return xml_bytes(root)


def build_version_xml() -> bytes:
    root = ET.Element(
        "{http://www.hancom.co.kr/hwpml/2011/version}HCFVersion",
        {
            "tagetApplication": "WORDPROCESSOR",
            "major": "5",
            "minor": "1",
            "micro": "0",
            "buildNumber": "0",
            "xmlVersion": "1.4",
            "application": "Exam Generator",
            "appVersion": "1",
        },
    )
    return xml_bytes(root)


def build_settings_xml() -> bytes:
    root = ET.Element(q("ha", "HWPApplicationSetting"))
    _sub(root, "ha", "CaretPosition", listIDRef=0, paraIDRef=0, pos=0)
    return xml_bytes(root)


def build_container_xml() -> bytes:
    root = ET.Element(q("ocf", "container"))
    rootfiles = _sub(root, "ocf", "rootfiles")
    _sub(
        rootfiles,
        "ocf",
        "rootfile",
        **{"full-path": "Contents/content.hpf", "media-type": "application/hwpml-package+xml"},
    )
    return xml_bytes(root)


def build_manifest_xml() -> bytes:
    return xml_bytes(ET.Element(q("odf", "manifest")))


def build_master_page_xml(identifier: str, role: str) -> bytes:
    root = ET.Element(
        q("hm", "masterPage"),
        {
            "id": identifier,
            "type": role,
            "pageNumber": "0",
            "pageDuplicate": "0",
            "pageFront": "0",
        },
    )
    return xml_bytes(root)


def _add_note_properties(sec_pr: ET.Element, kind: str) -> None:
    note = _sub(sec_pr, "hp", kind)
    _sub(note, "hp", "autoNumFormat", type="DIGIT", userChar="", prefixChar="", suffixChar=")", supscript=0)
    _sub(note, "hp", "noteLine", length=-1, type="SOLID", width="0.12 mm", color="#000000")
    _sub(note, "hp", "noteSpacing", betweenNotes=283, belowLine=567, aboveLine=850)


def new_section_root(
    profile: HwpxTemplateProfile,
    identifiers: DeterministicIds,
    *,
    columns: int,
    gap: int,
    new_page: bool = False,
) -> ET.Element:
    root_attributes = {"data-new-page": "1"} if new_page else {}
    root = ET.Element(q("hs", "sec"), root_attributes)
    paragraph = _sub(
        root,
        "hp",
        "p",
        id=identifiers.next("paragraph"),
        paraPrIDRef=0,
        styleIDRef=0,
        pageBreak=1 if new_page else 0,
        columnBreak=0,
        merged=0,
    )
    run = _sub(paragraph, "hp", "run", charPrIDRef=0)
    sec_pr = _sub(
        run,
        "hp",
        "secPr",
        id="",
        textDirection="HORIZONTAL",
        spaceColumns=profile.body_column_gap,
        tabStop=8000,
        tabStopVal=4000,
        tabStopUnit="HWPUNIT",
        outlineShapeIDRef=1,
        memoShapeIDRef=0,
        textVerticalWidthHead=0,
        masterPageCnt=2,
    )
    _sub(sec_pr, "hp", "grid", lineGrid=0, charGrid=0, wonggojiFormat=0)
    _sub(sec_pr, "hp", "startNum", pageStartsOn="BOTH", page=0, pic=0, tbl=0, equation=0)
    _sub(
        sec_pr,
        "hp",
        "visibility",
        hideFirstHeader=0,
        hideFirstFooter=0,
        hideFirstMasterPage=0,
        border="SHOW_ALL",
        fill="SHOW_ALL",
        hideFirstPageNum=0,
        hideFirstEmptyLine=0,
        showLineNumber=0,
    )
    _sub(sec_pr, "hp", "lineNumberShape", restartType=0, countBy=0, distance=0, startNumber=0)
    page = _sub(
        sec_pr,
        "hp",
        "pagePr",
        landscape="WIDELY",
        width=profile.page_width,
        height=profile.page_height,
        gutterType="TOP_BOTTOM",
    )
    _sub(
        page,
        "hp",
        "margin",
        header=profile.margin_header,
        footer=profile.margin_footer,
        gutter=0,
        left=profile.margin_left,
        right=profile.margin_right,
        top=profile.margin_top,
        bottom=profile.margin_bottom,
    )
    _add_note_properties(sec_pr, "footNotePr")
    _add_note_properties(sec_pr, "endNotePr")
    for border_type in ("BOTH", "EVEN", "ODD"):
        border = _sub(sec_pr, "hp", "pageBorderFill", type=border_type, borderFillIDRef=1, textBorder="PAPER", fillArea="PAPER", inside=0)
        _sub(border, "hp", "offset", left=0, right=0, top=0, bottom=0)
    _sub(sec_pr, "hp", "colPr", id="", type="NEWSPAPER", layout="LEFT", colCount=columns, sameSz=1, sameGap=gap)
    _sub(sec_pr, "hp", "masterPage", idRef="masterpage0")
    _sub(sec_pr, "hp", "masterPage", idRef="masterpage1")
    return root


def append_paragraph(
    root: ET.Element,
    identifiers: DeterministicIds,
    runs: Sequence[tuple[str, int]],
    *,
    alignment: str = "left",
    style_id: int = 0,
) -> ET.Element:
    para_ref = {"left": 0, "center": 1, "right": 2}.get(alignment, 0)
    paragraph = _sub(
        root,
        "hp",
        "p",
        id=identifiers.next("paragraph"),
        paraPrIDRef=para_ref,
        styleIDRef=style_id,
        pageBreak=0,
        columnBreak=0,
        merged=0,
    )
    if not runs:
        runs = (("", 0),)
    for text, char_style in runs:
        run = _sub(paragraph, "hp", "run", charPrIDRef=char_style)
        value = _sub(run, "hp", "t")
        value.text = clean_xml_text(text)
    return paragraph


def append_image_paragraph(
    root: ET.Element,
    identifiers: DeterministicIds,
    media: MediaPart,
    *,
    max_width: int = 17000,
) -> ET.Element:
    paragraph = _sub(root, "hp", "p", id=identifiers.next("paragraph"), paraPrIDRef=1, styleIDRef=0, pageBreak=0, columnBreak=0, merged=0)
    run = _sub(paragraph, "hp", "run", charPrIDRef=0)
    picture = _sub(
        run,
        "hp",
        "pic",
        id=identifiers.next("object"),
        zOrder=identifiers.next("zorder"),
        numberingType="PICTURE",
        textWrap="TOP_AND_BOTTOM",
        textFlow="BOTH_SIDES",
        lock=0,
        dropcapstyle="None",
    )
    width = max(1, media.pixel_width)
    height = max(1, media.pixel_height)
    rendered_width = min(max_width, max(100, width * 120))
    rendered_height = max(100, round(rendered_width * height / width))
    _sub(picture, "hp", "offset", x=0, y=0)
    _sub(picture, "hp", "orgSz", width=width, height=height)
    _sub(picture, "hp", "curSz", width=rendered_width, height=rendered_height)
    _sub(picture, "hp", "flip", horizontal=0, vertical=0)
    _sub(picture, "hp", "rotationInfo", rotate=0, rotationCenter=0, rotationCenterX=0, rotationCenterY=0)
    _sub(picture, "hp", "renderingInfo")
    _sub(picture, "hp", "img", binaryItemIDRef=media.identifier, bright=0, contrast=0, effect="REAL_PIC", alpha=0)
    return paragraph


def append_table_paragraph(
    root: ET.Element,
    identifiers: DeterministicIds,
    styles: StyleRegistry,
    cells: Sequence[Mapping[str, object]],
    *,
    row_count: int,
    column_count: int,
    column_widths: Sequence[int] | None = None,
) -> ET.Element:
    if row_count < 1 or column_count < 1:
        raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "table dimensions must be positive")
    widths = list(column_widths or ())
    if len(widths) != column_count or any(width <= 0 for width in widths):
        widths = [max(1000, 17000 // column_count)] * column_count
    table_width = sum(widths)
    paragraph = _sub(root, "hp", "p", id=identifiers.next("paragraph"), paraPrIDRef=1, styleIDRef=0, pageBreak=0, columnBreak=0, merged=0)
    run = _sub(paragraph, "hp", "run", charPrIDRef=styles.table)
    table = _sub(
        run,
        "hp",
        "tbl",
        id=identifiers.next("table"),
        zOrder=identifiers.next("zorder"),
        numberingType="TABLE",
        textWrap="TOP_AND_BOTTOM",
        textFlow="BOTH_SIDES",
        lock=0,
        dropcapstyle="None",
        pageBreak="CELL",
        repeatHeader=1,
        rowCnt=row_count,
        colCnt=column_count,
        cellSpacing=0,
        borderFillIDRef=2,
        noAdjust=0,
    )
    _sub(table, "hp", "sz", width=table_width, widthRelTo="ABSOLUTE", height=max(1200, row_count * 1200), heightRelTo="ABSOLUTE", protect=0)
    _sub(table, "hp", "pos", treatAsChar=1, affectLSpacing=0, flowWithText=1, allowOverlap=0, holdAnchorAndSO=0, vertRelTo="PARA", horzRelTo="PARA", vertAlign="TOP", horzAlign="CENTER", vertOffset=0, horzOffset=0)
    _sub(table, "hp", "outMargin", left=100, right=100, top=100, bottom=100)
    _sub(table, "hp", "inMargin", left=100, right=100, top=100, bottom=100)
    by_row: dict[int, list[Mapping[str, object]]] = {row: [] for row in range(row_count)}
    for cell in cells:
        row = int(cell["row"])
        if row not in by_row:
            raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "cell row outside table")
        by_row[row].append(cell)
    for row in range(row_count):
        row_element = _sub(table, "hp", "tr")
        for cell in sorted(by_row[row], key=lambda item: int(item["col"])):
            column = int(cell["col"])
            row_span = int(cell.get("row_span", 1))
            column_span = int(cell.get("col_span", 1))
            if column < 0 or column + column_span > column_count or row + row_span > row_count:
                raise HwpxBuildError("HWPX_TABLE_TOPOLOGY_INVALID", "cell span outside table")
            cell_element = _sub(row_element, "hp", "tc", name="", header=1 if row == 0 else 0)
            _sub(cell_element, "hp", "cellAddr", colAddr=column, rowAddr=row)
            _sub(cell_element, "hp", "cellSpan", colSpan=column_span, rowSpan=row_span)
            cell_width = sum(widths[column : column + column_span])
            _sub(cell_element, "hp", "cellSz", width=cell_width, height=1200)
            _sub(cell_element, "hp", "cellMargin", left=100, right=100, top=100, bottom=100)
            sublist = _sub(
                cell_element,
                "hp",
                "subList",
                id=identifiers.next("cell"),
                textDirection="HORIZONTAL",
                lineWrap="BREAK",
                vertAlign=str(cell.get("vertical_alignment", "center")).upper(),
                linkListIDRef=0,
                linkListNextIDRef=0,
                textWidth=cell_width,
                textHeight=0,
                hasMargin=0,
                paraMargin=0,
                marginLeft=0,
                marginRight=0,
                marginTop=0,
                marginBottom=0,
            )
            append_paragraph(
                sublist,
                identifiers,
                ((clean_xml_text(cell.get("text", "")), styles.table),),
                alignment=str(cell.get("horizontal_alignment", "left")),
            )
    return paragraph


def build_content_hpf(section_names: Sequence[str], media: Sequence[MediaPart]) -> bytes:
    root = ET.Element(q("opf", "package"), {"version": "1.0", "unique-identifier": "", "id": "exam-generator"})
    metadata = _sub(root, "opf", "metadata")
    title = _sub(metadata, "opf", "title")
    title.text = "Exam Generator"
    language = _sub(metadata, "opf", "language")
    language.text = "ko"
    manifest = _sub(root, "opf", "manifest")
    items: list[tuple[str, str, str, dict[str, str]]] = [
        ("header", "Contents/header.xml", "application/xml", {}),
        ("masterpage0", "Contents/masterpage0.xml", "application/xml", {}),
        ("masterpage1", "Contents/masterpage1.xml", "application/xml", {}),
    ]
    for index, section_name in enumerate(section_names):
        items.append((f"section{index}", section_name, "application/xml", {}))
    items.append(("settings", "settings.xml", "application/xml", {}))
    for item in media:
        items.append((item.identifier, item.member_name, item.media_type, {"isEmbeded": "1"}))
    for identifier, href, media_type, extras in items:
        _sub(manifest, "opf", "item", id=identifier, href=href, **{"media-type": media_type}, **extras)
    spine = _sub(root, "opf", "spine")
    _sub(spine, "opf", "itemref", idref="header", linear="yes")
    for index, _section_name in enumerate(section_names):
        _sub(spine, "opf", "itemref", idref=f"section{index}", linear="yes")
    return xml_bytes(root)


def deterministic_parts(
    *,
    styles: StyleRegistry,
    profile: HwpxTemplateProfile,
    sections: Sequence[ET.Element],
    media: Sequence[MediaPart],
) -> "OrderedDict[str, bytes]":
    section_names = [f"Contents/section{index}.xml" for index in range(len(sections))]
    parts: "OrderedDict[str, bytes]" = OrderedDict()
    parts["mimetype"] = MIMETYPE
    parts["version.xml"] = build_version_xml()
    parts["META-INF/container.xml"] = build_container_xml()
    parts["META-INF/manifest.xml"] = build_manifest_xml()
    parts["settings.xml"] = build_settings_xml()
    parts["Contents/header.xml"] = build_header_xml(styles, profile, len(sections))
    parts["Contents/masterpage0.xml"] = build_master_page_xml("masterpage0", "EVEN")
    parts["Contents/masterpage1.xml"] = build_master_page_xml("masterpage1", "ODD")
    for name, section in zip(section_names, sections):
        parts[name] = xml_bytes(section)
    for item in sorted(media, key=lambda value: value.member_name):
        parts[item.member_name] = item.data
    parts["Contents/content.hpf"] = build_content_hpf(section_names, media)
    return parts


def write_deterministic_package(path: Path, parts: Mapping[str, bytes]) -> None:
    names = list(parts)
    if not names or names[0] != "mimetype":
        raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "mimetype must be the first package member")
    if len(names) != len(set(names)):
        raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "duplicate package member")
    for name in names:
        candidate = PurePosixPath(name)
        if candidate.is_absolute() or ".." in candidate.parts or re.match(r"^[A-Za-z]:", name):
            raise HwpxBuildError("HWPX_PACKAGE_STRUCTURE_INVALID", "unsafe package member")
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, data in parts.items():
                info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
                info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                info.create_system = 0
                info.external_attr = 0
                info.internal_attr = 0
                package.writestr(info, data, compress_type=info.compress_type, compresslevel=9)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise HwpxBuildError("HWPX_PACKAGE_CONSTRUCTION_FAILED", "unable to write HWPX package") from exc
