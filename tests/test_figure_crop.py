from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from src.parser.figure_crop import (
    locate_figure_band,
    materialize_offline_figure_crops,
    trim_figure_ink,
)
from src.parser.layout import LayoutLine, LayoutWord, StructuredPage
from src.parser.offline_exam import ParsedOfflineQuestion


def _line(text, bbox, column=1):
    word = LayoutWord(text, bbox, 1.0, column)
    return LayoutLine((word,), bbox, 1, column)


def _scanned_diagram_page():
    return StructuredPage(
        number=1,
        width=600,
        height=800,
        kind="scanned",
        images=((0.0, 0.0, 1.0, 1.0),),
        lines=(
            _line("13. 다음 그림은 압력-체적 선도이다.", (0.52, 0.10, 0.94, 0.12)),
            _line("가장 옳은 것은?", (0.55, 0.125, 0.78, 0.145)),
            _line("2 3", (0.64, 0.19, 0.73, 0.21)),
            _line("0 1", (0.65, 0.29, 0.83, 0.31)),
            _line("① 가솔린 기관의 기본 사이클이다.", (0.54, 0.34, 0.90, 0.36)),
            _line("② 압축과정은 등온압축이다.", (0.54, 0.37, 0.88, 0.39)),
            _line("14. 다음 문제", (0.52, 0.44, 0.80, 0.46)),
        ),
    )


def _candidate():
    return ParsedOfflineQuestion(
        number=13,
        stem="다음 그림은 압력-체적 선도이다. 가장 옳은 것은?",
        choices=["가", "나", "다", "라"],
        source_page=1,
        confidence=1.0,
        diagnostics=(),
    )


def test_figure_band_ends_before_first_choice_row():
    band = locate_figure_band(
        _scanned_diagram_page(),
        13,
        _candidate().stem,
        _candidate().choices,
    )

    assert band is not None
    assert band[1] > 0.145
    assert band[3] < 0.34
    assert band[0] >= 0.5


def test_trim_figure_ink_keeps_diagram_and_excludes_choice_text():
    image = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((340, 145, 520, 250), outline="black", width=3)
    draw.line((350, 250, 520, 150), fill="black", width=3)
    draw.text((330, 272), "choice row must stay outside crop", fill="black")
    band = locate_figure_band(
        _scanned_diagram_page(),
        13,
        _candidate().stem,
        _candidate().choices,
    )

    cropped = trim_figure_ink(image, band)

    assert cropped is not None
    assert cropped.width < 230
    assert cropped.height < 150


def test_materialized_crop_is_attached_to_candidate(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(340, 145, 520, 250), width=3)
    page.draw_line(fitz.Point(350, 250), fitz.Point(520, 150), width=3)
    document.save(pdf_path)
    document.close()

    result = materialize_offline_figure_crops(
        pdf_path,
        [_scanned_diagram_page()],
        [_candidate()],
        tmp_path / "extract",
    )[0]

    assert result.image_path is not None
    assert Path(result.image_path).is_file()
    assert result.image_bbox is not None
    assert "figure_crop_heuristic" in result.diagnostics


def test_figure_band_keeps_parenthetical_condition_with_stem():
    page = StructuredPage(
        number=1,
        width=600,
        height=800,
        kind="scanned",
        images=((0.0, 0.0, 1.0, 1.0),),
        lines=(
            _line("3. 다음 그림의 전류는 얼마인가?", (0.03, 0.43, 0.45, 0.45), 0),
            _line("(단, 전류계의 내부저항은 무시한다.)", (0.04, 0.456, 0.42, 0.47), 0),
            _line("40Ω A 30Ω", (0.08, 0.51, 0.38, 0.54), 0),
            _line("① 1A", (0.04, 0.56, 0.20, 0.58), 0),
        ),
    )

    band = locate_figure_band(page, 3, "다음 그림의 전류는 얼마인가?", ("1A",))

    assert band is not None
    assert band[1] > 0.47
    assert band[3] < 0.56


def test_figure_band_stops_before_fuzzy_damaged_choice_marker():
    page = StructuredPage(
        number=1,
        width=600,
        height=800,
        kind="scanned",
        images=((0.0, 0.0, 1.0, 1.0),),
        lines=(
            _line("6. 다음은 시퀀스 응용회로이다.", (0.52, 0.29, 0.93, 0.31)),
            _line("가장 알맞은 것은", (0.53, 0.315, 0.78, 0.326)),
            _line("PB 51-1 GL OL", (0.56, 0.35, 0.88, 0.60)),
            _line("年 전동기 정·역제어 회로", (0.53, 0.62, 0.91, 0.64)),
            _line("② 전동기 기동 회로", (0.53, 0.65, 0.88, 0.67)),
        ),
    )

    band = locate_figure_band(
        page,
        6,
        "다음은 시퀀스 응용회로이다. 가장 알맞은 것은",
        ("전동기 정·역제어 회로", "전동기 기동 회로"),
    )

    assert band is not None
    assert band[1] < 0.35
    assert band[3] < 0.62


def test_figure_band_without_question_mark_stops_before_diagram_labels():
    page = StructuredPage(
        number=1,
        width=600,
        height=800,
        kind="scanned",
        images=((0.0, 0.0, 1.0, 1.0),),
        lines=(
            _line("6. 다음은 시퀀스 응용회로이다.", (0.52, 0.29, 0.93, 0.31)),
            _line("가장 알맞은 것을 고르시오", (0.53, 0.316, 0.82, 0.326)),
            _line("PB 51-1", (0.56, 0.343, 0.77, 0.36)),
            _line("ON 52-2b -?b", (0.66, 0.445, 0.90, 0.46)),
            _line("① 정·역제어 회로", (0.53, 0.62, 0.88, 0.64)),
        ),
    )

    band = locate_figure_band(
        page,
        6,
        "다음은 시퀀스 응용회로이다. 가장 알맞은 것을 고르시오",
        ("정·역제어 회로",),
    )

    assert band is not None
    assert 0.326 < band[1] < 0.343


def test_figure_band_allows_symbol_with_no_ocr_text_inside_diagram():
    page = StructuredPage(
        number=1,
        width=600,
        height=800,
        kind="scanned",
        images=((0.0, 0.0, 1.0, 1.0),),
        lines=(
            _line("7. 다음 그림의 밸브 기호는?", (0.52, 0.42, 0.93, 0.44)),
            _line("① 감압 밸브", (0.53, 0.56, 0.88, 0.58)),
        ),
    )

    band = locate_figure_band(
        page,
        7,
        "다음 그림의 밸브 기호는?",
        ("감압 밸브",),
    )

    assert band is not None
    assert band[1] > 0.44
    assert band[3] < 0.56
