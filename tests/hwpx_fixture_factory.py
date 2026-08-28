# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import io
import struct
import zlib
import zipfile
from pathlib import Path

HEADER_XML = zlib.decompress(base64.b64decode("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")).decode("utf-8")
SETTINGS_XML = zlib.decompress(base64.b64decode("eNp1j01LAzEQhv9KmLubrgeRsNkiFtFb8QPPQ3ZqQpNJSKau/ntT8dCLx4F53/d5pu1XiuqTaguZLYzDBhSxy0vgDwtvrw9Xt6CaIC8YM5OFb2qgtvPk0Ty+7+9KicGh9PALifSQ6n3cjEcLXqQYrdd1HTz2zjS4PByr9mtJUV9vxlFjKfCXcJkPoW+eKpuMLTTDmKgZcSYX4iW7UyIWc/ltzry/LPdYSfa5hTOKiqHJ0+6ZDha6T8GKF1du3fMG9Dzp/yTmH4YTX/4=")).decode("utf-8")
MIMETYPE = "application/hwp+zip"
VERSION_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="0" micro="5" buildNumber="0" xmlVersion="1.4" application="ExamGenerator" appVersion="test"/>'
CONTAINER_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"><ocf:rootfiles><ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/></ocf:rootfiles></ocf:container>'
MANIFEST_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
NS = (
    'xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app" '
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hp10="http://www.hancom.co.kr/hwpml/2016/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hhs="http://www.hancom.co.kr/hwpml/2011/history" '
    'xmlns:hm="http://www.hancom.co.kr/hwpml/2011/master-page" '
    'xmlns:hpf="http://www.hancom.co.kr/schema/2011/hpf"'
)

def _secpr(*, width="59528", height="84188", col_count="1", same_gap="0", master_cnt="0"):
    return (
        f'<hp:run charPrIDRef="0"><hp:secPr id="" textDirection="HORIZONTAL" spaceColumns="1134" '
        f'tabStop="8000" tabStopVal="4000" tabStopUnit="HWPUNIT" outlineShapeIDRef="1" memoShapeIDRef="0" '
        f'textVerticalWidthHead="0" masterPageCnt="{master_cnt}">'
        f'<hp:grid lineGrid="0" charGrid="0" wonggojiFormat="0"/>'
        f'<hp:startNum pageStartsOn="BOTH" page="0" pic="0" tbl="0" equation="0"/>'
        f'<hp:visibility hideFirstHeader="0" hideFirstFooter="0" hideFirstMasterPage="0" border="SHOW_ALL" fill="SHOW_ALL" hideFirstPageNum="0" hideFirstEmptyLine="0" showLineNumber="0"/>'
        f'<hp:lineNumberShape restartType="0" countBy="0" distance="0" startNumber="0"/>'
        f'<hp:pagePr landscape="WIDELY" width="{width}" height="{height}" gutterType="LEFT_ONLY">'
        f'<hp:margin header="4252" footer="4252" gutter="0" left="8504" right="8504" top="5668" bottom="4252"/></hp:pagePr>'
        f'<hp:footNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
        f'<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
        f'<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/></hp:footNotePr>'
        f'<hp:endNotePr><hp:autoNumFormat type="DIGIT" userChar="" prefixChar="" suffixChar=")" supscript="0"/>'
        f'<hp:noteLine length="-1" type="SOLID" width="0.12 mm" color="#000000"/>'
        f'<hp:noteSpacing betweenNotes="283" belowLine="567" aboveLine="850"/></hp:endNotePr>'
        f'<hp:pageBorderFill type="BOTH" borderFillIDRef="1" textBorder="PAPER" fillArea="PAPER" inside="0">'
        f'<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
        f'<hp:pageBorderFill type="EVEN" borderFillIDRef="1" textBorder="PAPER" fillArea="PAPER" inside="0">'
        f'<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
        f'<hp:pageBorderFill type="ODD" borderFillIDRef="1" textBorder="PAPER" fillArea="PAPER" inside="0">'
        f'<hp:offset left="1417" right="1417" top="1417" bottom="1417"/></hp:pageBorderFill>'
        f'<hp:colPr id="" type="NEWSPAPER" layout="LEFT" colCount="{col_count}" sameSz="1" sameGap="{same_gap}" />'
        f'</hp:secPr></hp:run>'
    )

def _p(text: str, *, char="0", pid="1") -> str:
    return (
        f'<hp:p id="{pid}" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="{char}"><hp:t>{text}</hp:t></hp:run></hp:p>'
    )

def _p_runs(runs: list[tuple[str, str]], *, pid="1") -> str:
    inner = "".join(f'<hp:run charPrIDRef="{c}"><hp:t>{t}</hp:t></hp:run>' for t, c in runs)
    return f'<hp:p id="{pid}" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">{inner}</hp:p>'

def _section(body: str, **secpr) -> str:
    first = _p(" ", pid="0")
    # attach secPr into a leading empty paragraph
    lead = (
        f'<hp:p id="0" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'{_secpr(**secpr)}</hp:p>'
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?><hs:sec {NS}>{lead}{body}</hs:sec>'

def _hpf(section_ids: list[str], extra_items: list[str] | None = None) -> str:
    items = ['<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>']
    refs = ['<opf:itemref idref="header"/>']
    for sid in section_ids:
        items.append(f'<opf:item id="{sid}" href="Contents/{sid}.xml" media-type="application/xml"/>')
        refs.append(f'<opf:itemref idref="{sid}"/>')
    items.append('<opf:item id="settings" href="settings.xml" media-type="application/xml"/>')
    for it in extra_items or []:
        items.append(it)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
        f'<opf:package {NS} xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf/" version="" unique-identifier="" id="">'
        '<opf:metadata><opf:title/><opf:language>ko</opf:language></opf:metadata>'
        f'<opf:manifest>{"".join(items)}</opf:manifest>'
        f'<opf:spine>{"".join(refs)}</opf:spine></opf:package>'
    )

def write_package(path: Path, parts: dict[str, bytes | str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, MIMETYPE)
        for name, data in parts.items():
            payload = data.encode("utf-8") if isinstance(data, str) else data
            zf.writestr(name, payload)
    return path

def _base_parts(sections: dict[str, str], extra: dict[str, bytes | str] | None = None) -> dict[str, bytes | str]:
    ids = list(sections)
    parts: dict[str, bytes | str] = {
        "version.xml": VERSION_XML,
        "META-INF/container.xml": CONTAINER_XML,
        "META-INF/manifest.xml": MANIFEST_XML,
        "settings.xml": SETTINGS_XML,
        "Contents/header.xml": HEADER_XML,
        "Contents/content.hpf": _hpf(ids),
    }
    for sid, xml in sections.items():
        parts[f"Contents/{sid}.xml"] = xml
    if extra:
        parts.update(extra)
    return parts

def hx1_minimal(path: Path) -> Path:
    body = _p_runs([("EGHX1-KO-한글", "0"), ("EGHX1-EN-Hello", "0"), ("EGHX1-SYM-#@$%", "0")], pid="1")
    body += _p("EGHX1-P2-second", pid="2")
    return write_package(path, _base_parts({"section0": _section(body)}))

def hx2_styled(path: Path) -> Path:
    body = _p_runs([("plain", "0"), ("boldish", "1")], pid="1")
    return write_package(path, _base_parts({"section0": _section(body)}))

def hx3_multi_section(path: Path) -> Path:
    s0 = _section(_p("EGHX3-S0", pid="1"), width="72852", height="103180", col_count="1", same_gap="0")
    s1 = _section(_p("EGHX3-S1", pid="1"), width="72852", height="103180", col_count="2", same_gap="2268")
    extra = {
        "Contents/masterpage0.xml": f'<?xml version="1.0" encoding="UTF-8"?><hm:masterPage {NS} type="EVEN"><hp:p id="1" paraPrIDRef="3" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>EVEN</hp:t></hp:run></hp:p></hm:masterPage>',
        "Contents/masterpage1.xml": f'<?xml version="1.0" encoding="UTF-8"?><hm:masterPage {NS} type="ODD"><hp:p id="1" paraPrIDRef="3" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>ODD</hp:t></hp:run></hp:p></hm:masterPage>',
    }
    return write_package(path, _base_parts({"section0": s0, "section1": s1}, extra))

def _cell(r: int, c: int, text: str, rs=1, cs=1) -> str:
    return (
        f'<hp:tc name="" header="0"><hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
        f'<hp:cellSpan colSpan="{cs}" rowSpan="{rs}"/>'
        f'<hp:cellSz width="4252" height="4252"/><hp:cellMargin left="141" right="141" top="141" bottom="141"/>'
        f'<hp:subList id="" textDirection="HORIZONTAL" lineWrap="BREAK" vertAlign="CENTER" linkListIDRef="0" linkListNextIDRef="0" textWidth="4252" textHeight="0" hasMargin="0" paraMargin="0" marginLeft="0" marginRight="0" marginTop="0" marginBottom="0">'
        f'{_p(text, pid="1")}</hp:subList></hp:tc>'
    )

def _table(rows: list[list[tuple]]) -> str:
    # cell tuple: (text, rs, cs) or skip None
    trs = []
    for r, row in enumerate(rows):
        tcs = []
        for c, cell in enumerate(row):
            if cell is None:
                continue
            text, rs, cs = cell
            tcs.append(_cell(r, c, text, rs, cs))
        trs.append(f'<hp:tr>{"".join(tcs)}</hp:tr>')
    row_n = len(rows)
    col_n = max(len(row) for row in rows)
    return (
        f'<hp:p id="10" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        f'<hp:run charPrIDRef="0"><hp:tbl id="1" zOrder="0" numberingType="TABLE" textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" pageBreak="NONE" repeatHeader="1" rowCnt="{row_n}" colCnt="{col_n}" cellSpacing="0" borderFillIDRef="1" noAdjust="0">'
        f'<hp:sz width="14173" widthRelTo="ABSOLUTE" height="4252" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="141" right="141" top="141" bottom="141"/>'
        f'<hp:inMargin left="141" right="141" top="141" bottom="141"/>'
        f'{"".join(trs)}</hp:tbl></hp:run></hp:p>'
    )

def hx4_table(path: Path) -> Path:
    rows = [
        [("A", 1, 1), ("B", 1, 2)],
        [("C", 2, 1), None, None],
        [None, ("D1", 1, 1), ("D2", 1, 1)],
    ]
    # simpler 2x2 with rowspan and colspan
    rows = [
        [("R0C0", 1, 1), ("SPAN", 1, 1)],
        [("R1C0-rowspan", 1, 1), ("R1C1", 1, 1)],
    ]
    body = _table([
        [("EGHX4-00", 1, 1), ("EGHX4-01-colspan", 1, 2)],
        [("EGHX4-10-rowspan", 2, 1), None, ("EGHX4-12", 1, 1)],
        [None, ("EGHX4-21a", 1, 1), ("EGHX4-21b", 1, 1)],
    ])
    # cell paragraphs extra
    return write_package(path, _base_parts({"section0": _section(body)}))

def _png() -> bytes:
    # 1x1 PNG
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
    )

def hx5_image(path: Path) -> Path:
    pic = (
        '<hp:p id="11" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="0"><hp:pic id="1" zOrder="0" numberingType="PICTURE" textWrap="SQUARE" textFlow="BOTH_SIDES" lock="0" dropcapstyle="None">'
        '<hp:offset x="0" y="0"/><hp:orgSz width="100" height="100"/><hp:curSz width="100" height="100"/>'
        '<hp:flip horizontal="0" vertical="0"/><hp:rotationInfo rotate="0" rotationCenter="0" rotationCenterX="0" rotationCenterY="0"/>'
        '<hp:renderingInfo/>'
        '<hp:img binaryItemIDRef="image1" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        '</hp:pic></hp:run></hp:p>'
    )
    extra = {"BinData/image1.png": _png()}
    hpf = _hpf(["section0"], [ '<opf:item id="image1" href="BinData/image1.png" media-type="image/png"/>' ])
    parts = _base_parts({"section0": _section(pic)}, extra)
    parts["Contents/content.hpf"] = hpf
    return write_package(path, parts)

def hx6_field_control(path: Path) -> Path:
    body = (
        '<hp:p id="1" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="0"><hp:fieldBegin id="1" type="CLICK_HERE" name="EG_FIELD"/><hp:t>EGHX6-FIELD</hp:t><hp:fieldEnd/></hp:run>'
        '</hp:p>'
        '<hp:p id="2" paraPrIDRef="3" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
        '<hp:run charPrIDRef="0"><hp:ctrl><hp:unknownCtrl id="99" type="CUSTOM_UNSUPPORTED"/></hp:ctrl><hp:t>EGHX6-CTRL</hp:t></hp:run>'
        '</hp:p>'
    )
    return write_package(path, _base_parts({"section0": _section(body)}))

def hx7_final_table(path: Path) -> Path:
    rows = []
    for r in range(12):
        row = []
        for c in range(8):
            if r == 1 and c == 0:
                row.append((f"EGHX7-R{r:02d}C{c:02d}", 1, 2))
            elif r == 1 and c == 1:
                row.append(None)
            elif r == 2 and c == 0:
                row.append((f"EGHX7-R{r:02d}C{c:02d}", 2, 1))
            elif r == 3 and c == 0:
                row.append(None)
            else:
                row.append((f"EGHX7-R{r:02d}C{c:02d}", 1, 1))
        rows.append(row)
    return write_package(path, _base_parts({"section0": _section(_table(rows))}))

def hx8_malformed(path: Path, kind: str) -> Path:
    if kind == "missing_part":
        parts = _base_parts({"section0": _section(_p("x"))})
        del parts["Contents/header.xml"]
        return write_package(path, parts)
    if kind == "broken_relationship":
        parts = _base_parts({"section0": _section(_p("x"))})
        parts["Contents/content.hpf"] = _hpf(["section0", "section99"])
        return write_package(path, parts)
    if kind == "malformed_xml":
        parts = _base_parts({"section0": "<not-xml"})
        return write_package(path, parts)
    if kind == "duplicate_path":
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", MIMETYPE)
            zf.writestr("mimetype", MIMETYPE)
        return path
    if kind == "traversal":
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", MIMETYPE)
            zf.writestr("../evil.txt", "x")
        return path
    if kind == "oversize_meta":
        parts = _base_parts({"section0": _section(_p("x"))})
        parts["BinData/huge.bin"] = b"x" * (33 * 1024 * 1024)
        return write_package(path, parts)
    if kind == "wrong_mimetype":
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("mimetype", "application/zip")
            zf.writestr("version.xml", VERSION_XML)
        return path
    raise ValueError(kind)

def mapper_payload_hx1() -> dict:
    return {
        "file_header": {"version": "5.1.0.0"},
        "doc_info": {"char_shapes": [{"attributes": {"bold": False, "italic": False, "underline_type": 0}}, {"attributes": {"bold": True, "italic": False, "underline_type": 1}}]},
        "body_text": {"sections": [{"index": 0, "paragraphs": [
            {"para_header": {"instance_id": 1, "para_style_id": 0, "para_shape_id": 3}, "records": [
                {"type": "para_text", "text": "EGHX1-KO-한글EGHX1-EN-HelloEGHX1-SYM-#@$%", "runs": [
                    {"kind": "text", "text": "EGHX1-KO-한글", "char_shape_id": 0},
                    {"kind": "text", "text": "EGHX1-EN-Hello", "char_shape_id": 0},
                    {"kind": "text", "text": "EGHX1-SYM-#@$%", "char_shape_id": 0},
                ], "control_char_positions": []},
                {"type": "para_line_seg", "segments": []},
            ]},
            {"para_header": {"instance_id": 2}, "records": [
                {"type": "para_text", "text": "EGHX1-P2-second", "control_char_positions": []},
            ]},
        ]}]},
        "bin_data": {"items": []},
        "diagnostics": {"items": []},
        "warnings": [],
    }

def mapper_payload_table() -> dict:
    return {
        "file_header": {"version": "5.1.0.0"},
        "doc_info": {"char_shapes": []},
        "body_text": {"sections": [{"index": 0, "paragraphs": [{
            "para_header": {"instance_id": 10},
            "records": [{"type": "table", "table": {
                "attributes": {"row_count": 2, "col_count": 2},
                "cells": [
                    {"cell_attributes": {"row_address": 0, "col_address": 0, "row_span": 1, "col_span": 1},
                     "paragraphs": [{"para_header": {}, "records": [{"type": "para_text", "text": "A", "runs": [{"kind": "text", "text": "A", "char_shape_id": 0}]}]}]},
                    {"cell_attributes": {"row_address": 0, "col_address": 1, "row_span": 1, "col_span": 1},
                     "paragraphs": [{"para_header": {}, "records": [{"type": "para_text", "text": "B"}]}]},
                    {"cell_attributes": {"row_address": 1, "col_address": 0, "row_span": 1, "col_span": 2},
                     "paragraphs": [{"para_header": {}, "records": [{"type": "para_text", "text": "CD"}]}]},
                ],
            }}],
        }]}]},
        "bin_data": {"items": []},
        "diagnostics": {"items": []},
        "warnings": [],
    }
