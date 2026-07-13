import io
import re
import threading
import time
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image, ImageDraw

from src.parser import extractor as extractor_module
from src.parser.extractor import PDFExtractor
from src.parser.layout import LayoutLine, LayoutWord, StructuredPage, build_structured_page
from src.parser.offline_exam import OfflineExamParser


def _word(x0, y0, x1, text, *, height=12):
    return (x0, y0, x1, y0 + height, text, 0, 0, 0)


class _Page:
    def __init__(self, words, *, width=1000, height=1000, full_page_image=False):
        self.rect = SimpleNamespace(width=width, height=height)
        self._words = words
        self._full_page_image = full_page_image

    def get_text(self, kind):
        assert kind == "words"
        return self._words

    def get_images(self, full=False):
        return [(7, 0, 1000, 1000)] if self._full_page_image else []

    def get_image_rects(self, xref):
        assert xref == 7
        return [SimpleNamespace(x0=0, y0=0, x1=self.rect.width, y1=self.rect.height)]


def _texts(page: StructuredPage):
    return [" ".join(word.text for word in line.words) for line in page.lines]


def test_targeted_ton_hour_rows_merge_only_numeric_raster_evidence(monkeypatch):
    lines = []
    for row, (ton, hour) in enumerate(((200, 12), (200, 24), (300, 12), (300, 24))):
        y = 0.20 + row * 0.04
        damaged_ton = f"{'②' if row == 1 else '④' if row == 2 else ''}00톤"
        upper_words = (
            LayoutWord("㉦" if row == 0 else "①", (0.05, y, 0.07, y + 0.015), 0.95, 0),
            LayoutWord("국제항해에 취항하는", (0.08, y, 0.25, y + 0.015), 0.95, 0),
            LayoutWord(damaged_ton, (0.30, y, 0.37, y + 0.015), 0.95, 0),
            LayoutWord("이상의 선박", (0.39, y, 0.50, y + 0.015), 0.95, 0),
        )
        lower_words = (
            LayoutWord("시간이", (0.08, y + 0.02, 0.14, y + 0.035), 0.95, 0),
            LayoutWord(f"{hour}시간", (0.16, y + 0.02, 0.22, y + 0.035), 0.95, 0),
            LayoutWord("이상인 선박", (0.24, y + 0.02, 0.36, y + 0.035), 0.95, 0),
        )
        lines.extend((
            LayoutLine(upper_words, (0.05, y, 0.50, y + 0.015), 1, 0),
            LayoutLine(lower_words, (0.08, y + 0.02, 0.36, y + 0.035), 1, 0),
        ))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(
        f"국제항해에 취항하는 {ton}톤 이상의 선박 중 항행 시간이 {hour}시간 이상인 선박"
        for ton, hour in ((200, 12), (200, 24), (300, 12), (300, 24))
    )
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )

    restored = PDFExtractor._recover_targeted_ton_hour_rows(
        page, Image.new("L", (1000, 1000), "white")
    )

    assert len(restored.lines) == 4
    assert [line.words[0].text for line in restored.lines] == ["①", "②", "③", "④"]
    assert [
        (re.search(r"(\d+)톤", line.text).group(1), re.search(r"(\d+)시간", line.text).group(1))
        for line in restored.lines
    ] == [("200", "12"), ("200", "24"), ("300", "12"), ("300", "24")]


def test_targeted_three_field_rows_replace_internal_false_markers(monkeypatch):
    lines = []
    for row in range(4):
        y = 0.20 + row * 0.02
        words = (
            LayoutWord("①" if row == 2 else "㉦", (0.05, y, 0.07, y + 0.015), 0.95, 0),
            LayoutWord("㉠", (0.08, y, 0.10, y + 0.015), 0.95, 0),
            LayoutWord("정류", (0.11, y, 0.16, y + 0.015), 0.95, 0),
            LayoutWord("㉡", (0.18, y, 0.20, y + 0.015), 0.95, 0),
            LayoutWord("2", (0.21, y, 0.23, y + 0.015), 0.95, 0),
            LayoutWord("㉢", (0.25, y, 0.27, y + 0.015), 0.95, 0),
            LayoutWord("②0" if row == 2 else "20", (0.28, y, 0.32, y + 0.015), 0.95, 0),
        )
        lines.append(LayoutLine(words, (0.05, y, 0.32, y + 0.015), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(
        ("㉠ 정박 ㉡ 2 ㉢ 20", "㉠ 정류 ㉡ 2 ㉢ 100", "㉠ 정류 ㉡ 2 ㉢ 20", "㉠ 정류 ㉡ 3 ㉢ 20")
    )
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )

    restored = PDFExtractor._recover_targeted_three_field_rows(
        page, Image.new("L", (1000, 1000), "white")
    )

    assert [line.words[0].text for line in restored.lines] == ["①", "②", "③", "④"]
    assert [line.words[1].text for line in restored.lines] == [
        "㉠ 정박 ㉡ 2 ㉢ 20",
        "㉠ 정류 ㉡ 2 ㉢ 100",
        "㉠ 정류 ㉡ 2 ㉢ 20",
        "㉠ 정류 ㉡ 3 ㉢ 20",
    ]


def test_targeted_percentage_rows_merge_raw_leading_and_raster_last_cells(monkeypatch):
    raw_rows = (
        ("①", "1100/0", "100/0", "②00/0"),
        ("③", "1100/0", "100/0", "④00/0"),
        ("㉭", "1200/0", "209/0", "200%"),
        ("", "12096", "2096", "300%"),
    )
    lines = []
    for row, values in enumerate(raw_rows):
        y = 0.20 + row * 0.016
        words = tuple(
            LayoutWord(text, (0.05 + offset * 0.10, y, 0.12 + offset * 0.10, y + 0.012), 0.95, 0)
            for offset, text in enumerate(values)
            if text
        )
        lines.append(LayoutLine(words, (0.05, y, 0.43, y + 0.012), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(("10% 10% 20%", "110% 10% 30%", "120% 20% 20%", "20% 20% 30%"))
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )

    restored = PDFExtractor._recover_targeted_percentage_rows(
        page, Image.new("L", (1000, 1000), "white")
    )

    assert [line.words[1].text for line in restored.lines] == [
        "110% 10% 20%",
        "110% 10% 30%",
        "120% 20% 20%",
        "120% 20% 30%",
    ]


def test_targeted_percentage_rows_recovers_comma_suffixed_11070(monkeypatch):
    values = (
        ("11070,", "10%,", "20%"),
        ("11096,", "1096,", "300%"),
        ("120%,", "20%,", "20%"),
        ("120%,", "20%,", "30%"),
    )
    lines = []
    for row, row_values in enumerate(values):
        y = 0.20 + row * 0.018
        words = tuple(
            LayoutWord(text, (0.08 + column * 0.06, y, 0.13 + column * 0.06, y + 0.012), 0.95, 0)
            for column, text in enumerate(row_values)
        )
        lines.append(LayoutLine(words, (0.08, y, 0.28, y + 0.012), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(("10% 10% 20%", "10% 10% 30%", "120% 20% 20%", "120% 20% 30%"))
    monkeypatch.setattr(PDFExtractor, "_targeted_choice_crop_text", staticmethod(lambda _crop: next(targets)))

    restored = PDFExtractor._recover_targeted_percentage_rows(page, Image.new("L", (1000, 1000), "white"))

    assert [line.words[1].text for line in restored.lines] == [
        "110% 10% 20%", "110% 10% 30%", "120% 20% 20%", "120% 20% 30%"
    ]


def test_targeted_year_pairs_uses_four_independent_cell_crops(monkeypatch):
    lines = []
    for y, endings in ((0.20, ("1년", "구한")), (0.22, ("3년", "구한"))):
        words = []
        for offset, ending in zip((0.10, 0.40), endings):
            words.extend((
                LayoutWord("㉠", (offset, y, offset + 0.02, y + 0.012), 0.95, 0),
                LayoutWord("6개월" if y == 0.20 else "1년", (offset + 0.04, y, offset + 0.10, y + 0.012), 0.95, 0),
                LayoutWord("㉡", (offset + 0.13, y, offset + 0.15, y + 0.012), 0.95, 0),
                LayoutWord(ending, (offset + 0.17, y, offset + 0.21, y + 0.012), 0.95, 0),
            ))
        lines.append(LayoutLine(tuple(words), (0.07, y, 0.62, y + 0.012), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(("㉠ 6개월 ㉡ 1년", "㉠ 6개월 ㉡ 5년", "㉠ 1년 ㉡ 3년", "㉠ 1년 ㉡ 5년"))
    monkeypatch.setattr(PDFExtractor, "_targeted_choice_crop_text", staticmethod(lambda _crop: next(targets)))

    restored = PDFExtractor._recover_targeted_year_pairs(page, Image.new("L", (1000, 1000), "white"))

    assert [line.words[1].text for line in restored.lines] == [
        "㉠ : 6개월 ㉡ : 1년", "㉠ : 6개월 ㉡ : 5년", "㉠ : 1년 ㉡ : 3년", "㉠ : 1년 ㉡ : 5년"
    ]


def test_targeted_training_rows_requires_exact_first_and_tail_ocr(monkeypatch):
    texts = ("선니1숙지 훈련", "퇴선 훈련", "기름유출대응, 소화 훈련", "인명구조, 추락 및 충돌 좌초사고 대응 후려")
    lines = []
    for index, value in enumerate(texts):
        y = 0.20 + index * 0.019
        word = LayoutWord(value, (0.08, y, 0.45, y + 0.012), 0.95, 0)
        lines.append(LayoutLine((word,), word.bbox, 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(("선내숙지 훈련", "대응 훈련"))
    monkeypatch.setattr(PDFExtractor, "_targeted_choice_crop_text", staticmethod(lambda _crop: next(targets)))

    restored = PDFExtractor._recover_targeted_training_rows(page, Image.new("L", (1000, 1000), "white"))

    assert restored.lines[0].words[1].text == "선내숙지 훈련"
    assert restored.lines[3].words[1].text.endswith("대응 훈련")


def test_targeted_ocr_timeout_opens_circuit_without_leaking_workers():
    release = threading.Event()
    invocations = []

    def blocked_worker():
        invocations.append(1)
        release.wait()

    try:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            extractor_module._run_with_timeout(blocked_worker, timeout_seconds=0.02)
        for _ in range(24):
            with pytest.raises(RuntimeError):
                extractor_module._run_with_timeout(blocked_worker, timeout_seconds=0.02)

        live_workers = [
            thread
            for thread in threading.enumerate()
            if thread.name == "exam-weaver-targeted-ocr" and thread.is_alive()
        ]
        assert invocations == [1]
        assert len(live_workers) <= 1
        assert time.monotonic() - started < 0.30
    finally:
        release.set()
        deadline = time.monotonic() + 1
        while (
            any(
                thread.name == "exam-weaver-targeted-ocr" and thread.is_alive()
                for thread in threading.enumerate()
            )
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        reset = getattr(extractor_module, "_reset_targeted_ocr_circuit_for_tests", None)
        if reset is not None:
            reset()


def test_targeted_percentage_length_rows_prefer_clean_raw_percent_cells(monkeypatch):
    header_words = tuple(
        LayoutWord(label, (0.08 + index * 0.10, 0.18, 0.10 + index * 0.10, 0.192), 0.95, 0)
        for index, label in enumerate(("㉠", "㉡", "㉢", "㉣"))
    )
    lines = [LayoutLine(header_words, (0.08, 0.18, 0.40, 0.192), 1, 0)]
    raw_rows = (
        ("1100/0", "1096", "2096", "10m"),
        ("1100/0", "1096", "3096", "30m"),
        ("12096", "2096", "2096", "10m"),
        ("①2096", "②096", "③096", "④0m"),
    )
    for row, values in enumerate(raw_rows):
        y = 0.20 + row * 0.02
        words = tuple(
            LayoutWord(text, (0.08 + offset * 0.10, y, 0.15 + offset * 0.10, y + 0.012), 0.95, 0)
            for offset, text in enumerate(values)
        )
        lines.append(LayoutLine(words, (0.08, y, 0.45, y + 0.012), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    targets = iter(
        ("1100/0 100/0 200/0 10m", "100/0 100/0 300/0 30m", "1200/0 200/0 200/0 10m", "1200/0 200/0 300/0 30m")
    )
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )

    restored = PDFExtractor._recover_targeted_percentage_length_rows(
        page, Image.new("L", (1000, 1000), "white")
    )

    assert [line.words[1].text for line in restored.lines[1:]] == [
        "110% 10% 20% 10m",
        "110% 10% 30% 30m",
        "120% 20% 20% 10m",
        "120% 20% 30% 30m",
    ]


def test_raster_verified_vertical_sequence_inserts_only_missing_third_ring(monkeypatch):
    specs = (
        ("㉦", "첫째", 0.05, 0.20),
        ("계속", "", 0.08, 0.22),
        ("㉨", "둘째", 0.05, 0.24),
        ("계속", "", 0.08, 0.26),
        ("셋째", "문장", 0.08, 0.28),
        ("계속", "", 0.08, 0.30),
        ("㉦", "넷째", 0.05, 0.32),
    )
    lines = []
    for first, second, x, y in specs:
        words = [LayoutWord(first, (x, y, x + 0.04, y + 0.012), 0.95, 0)]
        if second:
            words.append(LayoutWord(second, (x + 0.05, y, x + 0.12, y + 0.012), 0.95, 0))
        lines.append(LayoutLine(tuple(words), (x, y, x + 0.20, y + 0.012), 1, 0))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())
    monkeypatch.setattr(
        PDFExtractor,
        "_visual_marker_ring_score",
        staticmethod(lambda _gray, _x, bbox: (24, 200) if bbox[1] == pytest.approx(0.28) else (0, 0)),
    )

    restored = PDFExtractor._recover_raster_verified_vertical_sequence(
        page, Image.new("L", (1000, 1000), "white")
    )

    assert [restored.lines[index].words[0].text for index in (0, 2, 4, 6)] == [
        "①",
        "②",
        "③",
        "④",
    ]


def test_separated_glyph_mapping_uses_raster_templates_and_global_assignment(monkeypatch):
    image = Image.new("L", (1000, 1000), "white")
    draw = ImageDraw.Draw(image)

    def draw_glyph(x, y, identity):
        left, top = round(x * 1000), round(y * 1000)
        draw.ellipse((left, top, left + 16, top + 16), outline="black", width=2)
        if identity == 0:
            draw.line((left + 8, top + 4, left + 8, top + 12), fill="black", width=2)
        elif identity == 1:
            draw.line((left + 4, top + 8, left + 12, top + 8), fill="black", width=2)
        elif identity == 2:
            draw.line((left + 4, top + 4, left + 12, top + 12), fill="black", width=2)
        else:
            draw.line((left + 12, top + 4, left + 4, top + 12), fill="black", width=2)

    lines = []
    for identity, (label, y) in enumerate(zip(("㉠", "㉡", "㉢", "㉣"), (0.20, 0.23, 0.26, 0.29))):
        draw_glyph(0.52, y, identity)
        words = (
            LayoutWord(label, (0.52, y, 0.538, y + 0.018), 0.95, 1),
            LayoutWord("항목", (0.55, y, 0.62, y + 0.018), 0.95, 1),
        )
        lines.append(LayoutLine(words, (0.52, y, 0.62, y + 0.018), 1, 1))
    for identity, y in enumerate((0.33, 0.36, 0.39, 0.42)):
        draw_glyph(0.52, y, identity)
        words = (
            LayoutWord(
                "①②③④"[identity],
                (0.52, y, 0.538, y + 0.018),
                0.95,
                1,
                visual_choice_marker=True,
            ),
            LayoutWord("설명", (0.55, y, 0.62, y + 0.018), 0.95, 1),
        )
        lines.append(LayoutLine(words, (0.52, y, 0.62, y + 0.018), 1, 1))

    xs = (0.501, 0.528, 0.558, 0.681, 0.708, 0.738)
    ys = (0.45, 0.48)
    left_identities = (0, 1, 2, 3)
    right_identities = (3, 2, 0, 1)
    cells = [
        (xs[offset], xs[offset + 1], xs[offset + 2], y)
        for y in ys
        for offset in (0, 3)
    ]
    for identity, right_identity, (_outer, left_x, right_x, y) in zip(
        left_identities, right_identities, cells
    ):
        draw_glyph(left_x, y, identity)
        draw_glyph(right_x, y, right_identity)
    for text, x, y in (("㉡ - 손상", 0.708, 0.45), ("㉣ - 손상", 0.708, 0.48)):
        word = LayoutWord(text, (x, y, x + 0.08, y + 0.018), 0.95, 1)
        lines.append(LayoutLine((word,), word.bbox, 1, 1))
    next_question = LayoutWord("2. 다음 문제", (0.50, 0.52, 0.65, 0.538), 0.95, 1)
    lines.append(LayoutLine((next_question,), next_question.bbox, 1, 1))
    page = StructuredPage(1, 1.0, 1.0, "scanned_image", tuple(lines), ())

    reference_positions = {(0.52, y) for y in (0.33, 0.36, 0.39, 0.42)}
    scan_positions = {(x, y) for x in xs for y in ys}

    def ring_score(_gray, x, bbox):
        y = float(bbox[1])
        if any(abs(x - px) <= 0.004 and abs(y - py) <= 0.004 for px, py in reference_positions):
            return 24, 200
        if any(abs(x - px) <= 0.004 and abs(y - py) <= 0.004 for px, py in scan_positions):
            return 24, 200
        return 0, 0

    monkeypatch.setattr(PDFExtractor, "_visual_marker_ring_score", staticmethod(ring_score))

    restored = PDFExtractor._recover_separated_glyph_mapping(page, image)

    assert [line.text for line in restored.lines if line.words[0].visual_choice_marker] == [
        "① mapping ㉠ - d",
        "② mapping ㉡ - c",
        "③ mapping ㉢ - a",
        "④ mapping ㉣ - b",
    ]
    assert [restored.lines[index].words[0].text for index in range(4, 8)] == list("abcd")


def test_extract_structured_page_normalizes_one_column_words_and_freezes_records():
    words = [
        _word(100, 100, 150, "1."),
        _word(160, 100, 250, "첫째"),
        _word(100, 130, 180, "둘째"),
        _word(190, 130, 280, "문장"),
        _word(100, 160, 170, "①"),
        _word(180, 160, 270, "선택지"),
    ]

    structured = PDFExtractor().extract_structured_page(_Page(words), 3)

    assert structured.number == 3
    assert structured.kind == "native"
    assert _texts(structured) == ["1. 첫째", "둘째 문장", "① 선택지"]
    assert [line.column for line in structured.lines] == [0, 0, 0]
    assert structured.lines[0].words[0].bbox == pytest.approx((0.1, 0.1, 0.15, 0.112))
    with pytest.raises(FrozenInstanceError):
        structured.lines[0].words[0].column = 1


def test_extract_structured_page_orders_each_detected_column_top_to_bottom():
    words = [
        _word(80, 100, 150, "왼쪽1"),
        _word(170, 100, 240, "본문"),
        _word(80, 150, 150, "왼쪽2"),
        _word(170, 150, 240, "본문"),
        _word(590, 90, 660, "오른쪽1"),
        _word(680, 90, 750, "본문"),
        _word(590, 140, 660, "오른쪽2"),
        _word(680, 140, 750, "본문"),
    ]

    structured = PDFExtractor().extract_structured_page(_Page(words), 1)

    assert _texts(structured) == [
        "왼쪽1 본문",
        "왼쪽2 본문",
        "오른쪽1 본문",
        "오른쪽2 본문",
    ]
    assert [line.column for line in structured.lines] == [0, 0, 1, 1]
    assert [word.column for line in structured.lines for word in line.words] == [
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
    ]


def test_column_detection_is_recalculated_for_a_following_full_width_page():
    extractor = PDFExtractor()
    two_column = _Page([
        _word(80, 100, 180, "L1"),
        _word(80, 140, 180, "L2"),
        _word(600, 100, 700, "R1"),
        _word(600, 140, 700, "R2"),
    ])
    single_column = _Page([
        _word(80, 100, 180, "전체"),
        _word(200, 100, 470, "너비의"),
        _word(500, 100, 760, "첫째줄"),
        _word(80, 140, 200, "이어지는"),
        _word(220, 140, 480, "단일"),
        _word(510, 140, 780, "둘째줄"),
    ])

    first = extractor.extract_structured_page(two_column, 1)
    second = extractor.extract_structured_page(single_column, 2)

    assert {line.column for line in first.lines} == {0, 1}
    assert _texts(second) == ["전체 너비의 첫째줄", "이어지는 단일 둘째줄"]
    assert [line.column for line in second.lines] == [0, 0]


def test_repeated_native_words_over_a_full_page_image_are_fake_text_layer():
    repeated = []
    for y in (100, 130, 160, 190):
        repeated.extend([
            _word(100, y, 180, "문제"),
            _word(200, y, 280, "문제"),
            _word(300, y, 380, "문제"),
        ])

    structured = PDFExtractor().extract_structured_page(
        _Page(repeated, full_page_image=True),
        4,
    )

    assert structured.kind == "image_with_fake_text_layer"
    assert structured.images == ((0.0, 0.0, 1.0, 1.0),)
    assert all(isinstance(word, LayoutWord) for line in structured.lines for word in line.words)


def test_fake_text_layer_uses_ocr_layout_and_keeps_legacy_text_in_sync(tmp_path, monkeypatch):
    pdf_path = tmp_path / "fake-layer.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    image = Image.new("RGB", (10, 10), "white")
    image_bytes = io.BytesIO()
    image.save(image_bytes, format="PNG")
    page.insert_image(page.rect, stream=image_bytes.getvalue())
    fake_token = "FAKE_LAYER_TOKEN_ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for y in range(100, 460, 30):
        page.insert_text((50, y), fake_token, fontsize=10)
    document.save(pdf_path)
    document.close()

    ocr_page = build_structured_page(
        [
            _word(50, 100, 90, "OCR"),
            _word(100, 100, 160, "문제"),
            _word(50, 140, 90, "둘째"),
            _word(100, 140, 160, "문장"),
            _word(50, 180, 90, "①"),
            _word(100, 180, 160, "정답"),
        ],
        page_number=1,
        width=600,
        height=800,
        source="ocr",
        images=((0, 0, 600, 800),),
    )
    extractor = PDFExtractor(output_dir=str(tmp_path / "output"))
    monkeypatch.setattr(
        extractor,
        "_extract_ocr_structured_page",
        lambda _page, _number: ocr_page,
    )

    extracted = extractor.extract(str(pdf_path)).pages[0]

    assert extracted.structured_page == ocr_page
    assert extracted.structured_page.kind == "scanned"
    assert extracted.text == extractor._structured_page_text(ocr_page)
    assert fake_token not in extracted.text


def test_same_baseline_four_cell_answer_row_does_not_create_page_columns():
    words = [
        _word(80, 20, 180, "왼쪽머리1"),
        _word(80, 50, 180, "왼쪽머리2"),
        _word(80, 500, 110, "①"),
        _word(130, 500, 180, "44"),
        _word(300, 500, 330, "②"),
        _word(350, 500, 400, "46"),
        _word(560, 500, 590, "③"),
        _word(610, 500, 660, "48"),
        _word(800, 500, 830, "④"),
        _word(850, 500, 900, "50"),
        _word(820, 930, 920, "오른쪽꼬리1"),
        _word(820, 960, 920, "오른쪽꼬리2"),
    ]

    structured = PDFExtractor().extract_structured_page(_Page(words), 1)

    assert "① 44 ② 46 ③ 48 ④ 50" in _texts(structured)
    assert {line.column for line in structured.lines} == {0}


def test_multiple_four_cell_answer_rows_do_not_establish_page_columns():
    words = [
        _word(80, 120, 200, "단일열"),
        _word(220, 120, 460, "문제의"),
        _word(480, 120, 760, "첫째본문"),
        _word(80, 160, 200, "가운데를"),
        _word(220, 160, 460, "가로지르는"),
        _word(480, 160, 760, "둘째본문"),
        _word(80, 500, 110, "①"),
        _word(130, 500, 180, "44"),
        _word(300, 500, 330, "②"),
        _word(350, 500, 400, "46"),
        _word(560, 500, 590, "③"),
        _word(610, 500, 660, "48"),
        _word(800, 500, 830, "④"),
        _word(850, 500, 900, "50"),
        _word(80, 550, 110, "①"),
        _word(130, 550, 180, "10"),
        _word(300, 550, 330, "②"),
        _word(350, 550, 400, "20"),
        _word(560, 550, 590, "③"),
        _word(610, 550, 660, "30"),
        _word(800, 550, 830, "④"),
        _word(850, 550, 900, "40"),
    ]

    structured = PDFExtractor().extract_structured_page(_Page(words), 1)

    assert "① 44 ② 46 ③ 48 ④ 50" in _texts(structured)
    assert "① 10 ② 20 ③ 30 ④ 40" in _texts(structured)
    assert {line.column for line in structured.lines} == {0}


def test_sparse_header_footer_and_cover_text_is_non_question_page():
    words = [
        _word(100, 20, 180, "시험명"),
        _word(190, 20, 270, "안내"),
        _word(100, 50, 180, "응시자"),
        _word(300, 450, 380, "표지"),
        _word(390, 450, 470, "문구"),
        _word(700, 950, 760, "1"),
        _word(770, 950, 790, "/"),
        _word(800, 950, 860, "8"),
    ]

    structured = PDFExtractor().extract_structured_page(_Page(words), 1)

    assert structured.kind == "non_question"


def test_sparse_repeated_cover_layer_is_non_question_before_fake_layer_classification():
    words = [
        _word(100, 20, 180, "표지"),
        _word(200, 20, 280, "표지"),
        _word(300, 20, 380, "표지"),
        _word(300, 450, 380, "표지"),
        _word(500, 950, 580, "표지"),
        _word(600, 950, 680, "표지"),
        _word(700, 950, 780, "표지"),
    ]

    structured = PDFExtractor().extract_structured_page(
        _Page(words, full_page_image=True),
        1,
    )

    assert structured.kind == "non_question"


def test_winrt_adapter_scales_pixels_preserves_confidence_and_matches_text_order():
    def ocr_word(text, x, y, width, height, confidence):
        return SimpleNamespace(
            text=text,
            confidence=confidence,
            bounding_rect=SimpleNamespace(x=x, y=y, width=width, height=height),
        )

    result = SimpleNamespace(lines=[
        SimpleNamespace(words=[
            ocr_word("B", 250, 200, 100, 100, 0.91),
            ocr_word("A", 100, 200, 100, 100, 0.83),
        ]),
        SimpleNamespace(words=[
            ocr_word("D", 250, 500, 100, 100, 0.92),
            ocr_word("C", 100, 500, 100, 100, 0.84),
        ]),
        SimpleNamespace(words=[
            ocr_word("F", 250, 800, 100, 100, 0.93),
            ocr_word("E", 100, 800, 100, 100, 0.85),
        ]),
    ])
    extractor = PDFExtractor()

    structured = extractor._structured_page_from_ocr_result(
        result,
        page_number=5,
        page_width=100,
        page_height=200,
        image_width=1000,
        image_height=2000,
        divider_x=None,
    )

    assert structured.width == 100
    assert structured.height == 200
    assert _texts(structured) == ["A B", "C D", "E F"]
    assert structured.lines[0].words[0].bbox == pytest.approx((0.1, 0.1, 0.2, 0.15))
    assert structured.lines[0].words[0].confidence == pytest.approx(0.83)
    assert extractor._structured_page_text(structured) == "A B\nC D\nE F"


@pytest.mark.parametrize(
    ("question_number", "known_markers", "line_counts"),
    [
        pytest.param(1, (1, 3), (4, 5, 3, 3), id="q1"),
        pytest.param(5, (1, 3), (3, 4, 2, 3), id="q5"),
        pytest.param(7, (3,), (3, 1, 3, 1), id="q7"),
        pytest.param(12, (1, 3), (3, 5, 3, 2), id="q12"),
        pytest.param(14, (1, 2, 3), (1, 1, 1, 2), id="q14"),
        pytest.param(17, (1, 2, 3), (2, 1, 2, 2), id="q17"),
        pytest.param(29, (2, 3), (4, 3, 2, 5), id="q29"),
        pytest.param(30, (1, 2, 3), (3, 2, 2, 4), id="q30"),
    ],
)
def test_visual_choice_markers_restore_all_rejected_ronpark_boundaries(
    question_number, known_markers, line_counts
):
    damaged_markers = {1: "㉦", 2: "㉨", 3: "㉭"}
    words = [
        {"text": f"{question_number}.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    expected_choices = []
    y = 100
    for choice_number, line_count in enumerate(line_counts, start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        if choice_number in known_markers:
            words.append({
                "text": damaged_markers[choice_number],
                "bbox": (50, y, 68, y + 14),
                "confidence": 0.80,
            })
        choice_parts = [f"선택지{choice_number}-시작"]
        words.append({
            "text": choice_parts[0],
            "bbox": (80, y, 450, y + 14),
            "confidence": 0.98,
        })
        for continuation_number in range(1, line_count):
            y += 20
            text = f"선택지{choice_number}-연속{continuation_number}"
            choice_parts.append(text)
            words.append({
                "text": text,
                "bbox": (80, y, 300, y + 14),
                "confidence": 0.98,
            })
        expected_choices.append(" ".join(choice_parts))
        y += 20

    structured = build_structured_page(
        words,
        page_number=2,
        width=1000,
        height=1000,
        source="ocr",
        images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == expected_choices


def test_choice_ring_prevents_citation_choice_from_becoming_semantic_question_start():
    words = [
        {"text": "13.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제는?", "bbox": (52, 40, 150, 54), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    starts = ("年", "둘째", "「해운법」", "㉦")
    for number, (text, y) in enumerate(zip(starts, (100, 180, 260, 340)), start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        x = 50 if text in {"年", "「해운법」", "㉦"} else 80
        words.append({"text": text, "bbox": (x, y, x + 80, y + 14), "confidence": 0.8})
        words.append({"text": f"선택지{number}", "bbox": (140, y, 300, y + 14), "confidence": 0.98})
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "선택지1", "둘째 선택지2", "「해운법」 선택지3", "선택지4"
    ]


def test_three_strong_choice_rings_restore_weak_year_shaped_first_marker(monkeypatch):
    words = [
        {"text": "14.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제는?", "bbox": (52, 40, 150, 54), "confidence": 0.98},
    ]
    for marker, y in zip(("年", "2", "셋째", "㉦"), (100, 180, 260, 340)):
        marker_x = 50 if marker != "셋째" else 83
        words.extend([
            {"text": marker, "bbox": (marker_x, y, marker_x + 18, y + 14), "confidence": 0.80},
            {"text": f"선택지-{y}", "bbox": (100, y, 300, y + 14), "confidence": 0.98},
        ])

    def ring_score(_gray, marker_x, bbox):
        if abs(marker_x - 0.05) > 0.001:
            return 0, 0
        return (20, 168) if float(bbox[1]) == pytest.approx(0.10) else (24, 200)

    monkeypatch.setattr(
        PDFExtractor, "_visual_marker_ring_score", staticmethod(ring_score)
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(
        structured, Image.new("L", (1000, 1000), 255)
    )
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "선택지-100", "선택지-180", "셋째 선택지-260", "선택지-340"
    ]


def test_weak_year_shaped_ring_is_not_restored_without_three_strong_peers(monkeypatch):
    words = [
        {"text": "14.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제는?", "bbox": (52, 40, 150, 54), "confidence": 0.98},
        {"text": "年", "bbox": (50, 100, 68, 114), "confidence": 0.80},
        {"text": "연도 설명", "bbox": (100, 100, 300, 114), "confidence": 0.98},
    ]
    monkeypatch.setattr(
        PDFExtractor,
        "_visual_marker_ring_score",
        staticmethod(lambda _gray, marker_x, _bbox: (20, 168) if abs(marker_x - 0.05) <= 0.006 else (0, 0)),
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(
        structured, Image.new("L", (1000, 1000), 255)
    )

    assert restored.lines[-1].text == "年 연도 설명"
    assert restored.lines[-1].words[0].visual_choice_marker is False


@pytest.mark.parametrize(
    ("first_token", "expected_first"),
    [
        pytest.param("취득한", "취득한 선택지-100", id="missing-marker-bbox"),
        pytest.param("年㉠최대", "㉠최대 선택지-100", id="fused-damaged-marker"),
    ],
)
def test_three_aligned_peers_restore_strong_first_ring_at_content_bbox(
    monkeypatch, first_token, expected_first
):
    words = [
        {"text": "33.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "가장 옳지", "bbox": (52, 40, 150, 54), "confidence": 0.98},
        {"text": "0들으 LÉ =", "bbox": (52, 60, 150, 74), "confidence": 0.70},
    ]
    for marker, y in zip((first_token, "2", "㉭", "㉦"), (100, 180, 260, 340)):
        words.extend([
            {"text": marker, "bbox": (50, y, 95, y + 14), "confidence": 0.80},
            {"text": f"선택지-{y}", "bbox": (110, y, 300, y + 14), "confidence": 0.98},
        ])

    monkeypatch.setattr(
        PDFExtractor,
        "_visual_marker_ring_score",
        staticmethod(
            lambda _gray, marker_x, _bbox: (24, 200)
            if abs(marker_x - 0.05) <= 0.004 else (0, 0)
        ),
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(
        structured, Image.new("L", (1000, 1000), 255)
    )
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        expected_first, "선택지-180", "선택지-260", "선택지-340"
    ]


def test_vertical_choice_table_recovers_two_missing_first_column_cells(monkeypatch):
    words = [
        {"text": "23.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "내용은?", "bbox": (52, 40, 150, 54), "confidence": 0.98},
        {"text": "(가)", "bbox": (145, 80, 180, 94), "confidence": 0.98},
        {"text": "(나)", "bbox": (285, 80, 320, 94), "confidence": 0.98},
        {"text": "(다)", "bbox": (405, 80, 440, 94), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    rows = (
        (None, "2", "20"),
        (None, "2", "20"),
        ("정류", "3", "20"),
        ("정박", "3", "100"),
    )
    for number, (row, y) in enumerate(zip(rows, (120, 160, 200, 240)), start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        words.append({"text": "㉦", "bbox": (50, y, 68, y + 14), "confidence": 0.8})
        for value, x in zip(row, (145, 285, 405)):
            if value:
                words.append({"text": value, "bbox": (x, y, x + 40, y + 14), "confidence": 0.98})
    targets = iter(("정류", "정박"))
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "정류 2 20", "정박 2 20", "정류 3 20", "정박 3 100"
    ]


def test_vertical_choice_table_recovers_one_different_missing_cell_per_row(monkeypatch):
    words = [
        {"text": "26.", "bbox": (520, 40, 550, 54), "confidence": 0.98},
        {"text": "내용은?", "bbox": (560, 40, 650, 54), "confidence": 0.98},
    ]
    rows = (
        ("감정", None, "검량"),
        ("검량", None, "감정"),
        ("거 ^", None, "검량"),
        ("검량", "감정", None),
    )
    for marker, row, y in zip(("年", "2", "㉭", "㉦"), rows, (120, 160, 200, 240)):
        words.append({"text": marker, "bbox": (535, y, 553, y + 14), "confidence": 0.8})
        for value, x in zip(row, (623, 751, 879)):
            if value:
                words.append({"text": value, "bbox": (x, y, x + 40, y + 14), "confidence": 0.98})
    targets = iter(("검수", "검수", "검수", "감정", "검수"))
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y in (120, 160, 200, 240):
        draw.ellipse((535, y, 553, y + 14), outline=0, width=2)

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "감정 검수 검량", "검량 검수 감정", "검수 감정 검량", "검량 감정 검수"
    ]


def test_vertical_choice_table_preserves_normal_standalone_punctuation(monkeypatch):
    words = [
        {"text": "26.", "bbox": (520, 40, 550, 54), "confidence": 0.98},
        {"text": "내용은?", "bbox": (560, 40, 650, 54), "confidence": 0.98},
    ]
    rows = (
        (("감정", "·"), None, ("검량",)),
        (("검량",), None, ("감정",)),
        (("검수",), None, ("검량",)),
        (("검량",), ("감정",), None),
    )
    for marker, row, y in zip(("年", "2", "㉭", "㉦"), rows, (120, 160, 200, 240)):
        words.append({"text": marker, "bbox": (535, y, 553, y + 14), "confidence": 0.8})
        for values, x in zip(row, (623, 751, 879)):
            if not values:
                continue
            for offset, value in enumerate(values):
                token_x = x + offset * 43
                words.append({
                    "text": value,
                    "bbox": (token_x, y, token_x + 40, y + 14),
                    "confidence": 0.98,
                })
    targets = iter(("검수", "검수", "감정", "검수"))
    monkeypatch.setattr(
        PDFExtractor,
        "_targeted_choice_crop_text",
        staticmethod(lambda _crop: next(targets)),
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y in (120, 160, 200, 240):
        draw.ellipse((535, y, 553, y + 14), outline=0, width=2)

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "감정 · 검수 검량", "검량 검수 감정", "검수 감정 검량", "검량 감정 검수"
    ]


def test_compact_inline_damaged_choices_restore_missing_inner_marker():
    words = [
        {"text": "27.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "고른 것은?", "bbox": (52, 40, 150, 54), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    tokens = (
        ("㉦", 50), ("㉠", 80), ("2", 123), ("㉠,", 152), ("㉣", 186),
        ("㉠,", 258), ("㉡,", 292), ("㉣", 326), ("㉦", 368),
        ("㉡,", 397), ("㉢,", 431), ("㉣", 465),
    )
    for x in (50, 123, 229, 368):
        draw.ellipse((x, 100, x + 18, 114), outline=0, width=2)
    for text, x in tokens:
        words.append({"text": text, "bbox": (x, 100, x + 18, 114), "confidence": 0.9})
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == ["㉠", "㉠, ㉣", "㉠, ㉡, ㉣", "㉡, ㉢, ㉣"]


def test_inline_two_by_two_markers_do_not_override_later_vertical_choices():
    lines = (
        LayoutLine(
            (
                LayoutWord("①", (0.18, 0.10, 0.20, 0.115), 0.98, 0),
                LayoutWord("발문내용", (0.21, 0.10, 0.40, 0.115), 0.98, 0),
                LayoutWord("②", (0.45, 0.10, 0.47, 0.115), 0.98, 0),
                LayoutWord("발문내용", (0.48, 0.10, 0.68, 0.115), 0.98, 0),
            ),
            (0.18, 0.10, 0.68, 0.115), 1, 0,
        ),
        LayoutLine(
            (
                LayoutWord("③", (0.18, 0.13, 0.20, 0.145), 0.98, 0),
                LayoutWord("발문내용", (0.21, 0.13, 0.40, 0.145), 0.98, 0),
                LayoutWord("④", (0.45, 0.13, 0.47, 0.145), 0.98, 0),
                LayoutWord("발문내용", (0.48, 0.13, 0.68, 0.145), 0.98, 0),
            ),
            (0.18, 0.13, 0.68, 0.145), 1, 0,
        ),
        *tuple(
            LayoutLine(
                (
                    LayoutWord(marker, (0.05, y, 0.07, y + 0.015), 0.98, 0),
                    LayoutWord(text, (0.08, y, 0.50, y + 0.015), 0.98, 0),
                ),
                (0.05, y, 0.50, y + 0.015), 1, 0,
            )
            for marker, text, y in zip(
                ("①", "②", "③", "④"),
                ("첫째선택지", "둘째선택지", "셋째선택지", "넷째선택지"),
                (0.20, 0.30, 0.40, 0.50),
            )
        ),
    )
    anchors = tuple(
        (line_index, word.bbox[0], word_index, True)
        for line_index, line in enumerate(lines)
        for word_index, word in enumerate(line.words)
        if word.text in {"①", "②", "③", "④"}
    )

    selected = PDFExtractor._select_complete_visual_choice_layout(lines, anchors)

    assert [anchor[0] for anchor in selected] == [2, 3, 4, 5]


def test_inline_explicit_markers_do_not_block_later_damaged_vertical_choices(monkeypatch):
    words = [
        {"text": "27.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "OCR로 종결부가 손상된 발문", "bbox": (52, 40, 350, 54), "confidence": 0.70},
    ]
    for y, markers in ((100, (("①", 180), ("②", 450))), (130, (("③", 180), ("④", 450)))):
        for marker, x in markers:
            words.extend((
                {"text": marker, "bbox": (x, y, x + 18, y + 14), "confidence": 0.98},
                {"text": "발문내용", "bbox": (x + 30, y, x + 240, y + 14), "confidence": 0.98},
            ))
    for marker, text, y in zip(
        ("年", "2", None, "㉦"),
        ("첫째선택지", "둘째선택지", "셋째선택지", "넷째선택지"),
        (200, 300, 400, 500),
    ):
        if marker:
            words.append({"text": marker, "bbox": (50, y, 68, y + 14), "confidence": 0.80})
        words.append({"text": text, "bbox": (80, y, 400, y + 14), "confidence": 0.98})

    def ring_score(_gray, marker_x, bbox):
        y = round(float(bbox[1]), 2)
        expected = {0.10: (0.18, 0.45), 0.13: (0.18, 0.45)}.get(y, (0.05,))
        return (24, 200) if any(abs(marker_x - x) <= 0.004 for x in expected) else (0, 0)

    monkeypatch.setattr(
        PDFExtractor, "_visual_marker_ring_score", staticmethod(ring_score)
    )
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(
        structured, Image.new("L", (1000, 1000), 255)
    )
    visual_lines = [
        line.text
        for line in restored.lines
        if any(word.visual_choice_marker for word in line.words)
    ]
    assert visual_lines == [
        "① 첫째선택지", "② 둘째선택지", "③ 셋째선택지", "④ 넷째선택지"
    ]
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "첫째선택지", "둘째선택지", "셋째선택지", "넷째선택지"
    ]


def test_two_by_two_choice_grid_allows_small_column_stagger():
    lines = (
        LayoutLine(
            (
                LayoutWord("①", (0.534, 0.20, 0.552, 0.215), 0.98, 0),
                LayoutWord("어항기본사업", (0.56, 0.20, 0.70, 0.215), 0.98, 0),
                LayoutWord("②", (0.725, 0.20, 0.743, 0.215), 0.98, 0),
                LayoutWord("레저관광기반시설사업", (0.75, 0.20, 0.96, 0.215), 0.98, 0),
            ),
            (0.534, 0.20, 0.96, 0.215), 1, 0,
        ),
        LayoutLine(
            (
                LayoutWord("③", (0.534, 0.24, 0.552, 0.255), 0.98, 0),
                LayoutWord("어항환경개선사업", (0.56, 0.24, 0.72, 0.255), 0.98, 0),
                LayoutWord("④", (0.748, 0.24, 0.766, 0.255), 0.98, 0),
                LayoutWord("어항관광발전사업", (0.77, 0.24, 0.96, 0.255), 0.98, 0),
            ),
            (0.534, 0.24, 0.96, 0.255), 1, 0,
        ),
    )
    anchors = tuple(
        (line_index, word.bbox[0], word_index, True)
        for line_index, line in enumerate(lines)
        for word_index, word in enumerate(line.words)
        if word.text in {"①", "②", "③", "④"}
    )

    selected = PDFExtractor._select_complete_visual_choice_layout(lines, anchors)

    assert [anchor[0] for anchor in selected] == [0, 0, 1, 1]


def test_visual_marker_evidence_allows_a_choice_continuation_at_bottom_margin():
    words = [
        {"text": "17.", "bbox": (20, 650, 42, 664), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 650, 92, 664), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    damaged_markers = ("㉦", "㉨", "㉭", None)
    for choice_number, (marker, y) in enumerate(zip(damaged_markers, (700, 750, 800, 850)), start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        if marker:
            words.append({"text": marker, "bbox": (50, y, 68, y + 14), "confidence": 0.80})
        words.append({
            "text": f"선택지{choice_number}",
            "bbox": (80, y, 450, y + 14),
            "confidence": 0.98,
        })
    words.append({
        "text": "넷째선택지-연속",
        "bbox": (80, 900, 300, 914),
        "confidence": 0.98,
    })
    structured = build_structured_page(
        words,
        page_number=2,
        width=1000,
        height=1000,
        source="ocr",
        images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices[-1] == "선택지4 넷째선택지-연속"
    assert "ambiguous_bottom_margin" not in question.diagnostics


def test_incomplete_visual_marker_sequence_is_left_untouched():
    words = [
        {"text": "1.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
        {"text": "㉦", "bbox": (50, 100, 68, 114), "confidence": 0.80},
        {"text": "첫째", "bbox": (80, 100, 450, 114), "confidence": 0.98},
        {"text": "둘째", "bbox": (80, 150, 450, 164), "confidence": 0.98},
        {"text": "㉭", "bbox": (50, 200, 68, 214), "confidence": 0.80},
        {"text": "셋째", "bbox": (80, 200, 450, 214), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y in (100, 150, 200):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
    structured = build_structured_page(
        words,
        page_number=2,
        width=1000,
        height=1000,
        source="ocr",
        images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)

    assert restored == structured
    assert not any(word.visual_choice_marker for line in restored.lines for word in line.words)


def test_fused_damaged_marker_keeps_its_choice_text_when_visually_restored():
    words = [
        {"text": "5.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
        {"text": "㉦첫째", "bbox": (50, 100, 180, 114), "confidence": 0.80},
        {"text": "둘째", "bbox": (80, 150, 450, 164), "confidence": 0.98},
        {"text": "㉭셋째", "bbox": (50, 200, 180, 214), "confidence": 0.80},
        {"text": "넷째", "bbox": (80, 250, 450, 264), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y in (100, 150, 200, 250):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
    structured = build_structured_page(
        words,
        page_number=2,
        width=1000,
        height=1000,
        source="ocr",
        images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == ["첫째", "둘째", "셋째", "넷째"]


def test_at_sign_is_restored_as_fourth_marker_only_with_visual_ring_evidence():
    words = [
        {"text": "18.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
        {"text": "㉦", "bbox": (50, 100, 68, 114), "confidence": 0.80},
        {"text": "첫째", "bbox": (80, 100, 450, 114), "confidence": 0.98},
        {"text": "㉨", "bbox": (50, 150, 68, 164), "confidence": 0.80},
        {"text": "둘째", "bbox": (80, 150, 450, 164), "confidence": 0.98},
        {"text": "㉭", "bbox": (50, 200, 68, 214), "confidence": 0.80},
        {"text": "셋째", "bbox": (80, 200, 450, 214), "confidence": 0.98},
        {"text": "@", "bbox": (50, 250, 68, 264), "confidence": 0.80},
        {"text": "넷째", "bbox": (80, 250, 450, 264), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y in (100, 150, 200, 250):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
    structured = build_structured_page(
        words,
        page_number=2,
        width=1000,
        height=1000,
        source="ocr",
        images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == ["첫째", "둘째", "셋째", "넷째"]
    assert restored.lines[-1].words[0].visual_choice_marker is True


def test_visual_ring_replaces_an_arbitrary_ocr_token_in_the_marker_column():
    words = [
        {"text": "2.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for marker, y in zip(("㉦", "2", "㉭", "㉦"), (100, 150, 200, 250)):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        words.extend([
            {"text": marker, "bbox": (50, y, 68, y + 14), "confidence": 0.80},
            {"text": f"선택지-{y}", "bbox": (80, y, 450, y + 14), "confidence": 0.98},
        ])
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        "선택지-100", "선택지-150", "선택지-200", "선택지-250",
    ]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        (
            ((100, ((80, "3개"), (180, "4개"), (280, "5개"), (380, "㉦6개"))),),
            ["3개", "4개", "5개", "6개"],
        ),
        (
            (
                (100, ((80, "13만원"), (280, "14만원"))),
                (150, ((80, "15만원"), (280, "㉦16만원"))),
            ),
            ["13만원", "14만원", "15만원", "16만원"],
        ),
    ],
    ids=("single-row", "two-by-two"),
)
def test_visual_rings_restore_common_coordinate_choice_layouts(rows, expected):
    words = [
        {"text": "3.", "bbox": (20, 50, 42, 64), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 50, 92, 64), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for y, cells in rows:
        for content_x, value in cells:
            marker_x = content_x - 30
            draw.ellipse((marker_x, y, marker_x + 18, y + 14), outline=0, width=2)
            if value.startswith("㉦"):
                words.append({
                    "text": "㉦", "bbox": (marker_x, y, marker_x + 18, y + 14),
                    "confidence": 0.80,
                })
                value = value[1:]
            words.append({
                "text": value, "bbox": (content_x, y, content_x + 40, y + 14),
                "confidence": 0.98,
            })
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == expected


def test_outer_marker_gutter_wins_over_adjacent_inner_ring_markers():
    words = [
        {"text": "7.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 40, 92, 54), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for choice_number, y in enumerate((100, 200, 300, 400), start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        draw.ellipse((80, y, 98, y + 14), outline=0, width=2)
        if choice_number != 3:
            words.append({
                "text": str(choice_number), "bbox": (50, y, 68, y + 14),
                "confidence": 0.80,
            })
        words.extend([
            {"text": "㉦", "bbox": (80, y, 98, y + 14), "confidence": 0.80},
            {"text": f"선택지{choice_number}", "bbox": (110, y, 300, y + 14), "confidence": 0.98},
        ])
        continuation_y = y + 30
        draw.ellipse((80, continuation_y, 98, continuation_y + 14), outline=0, width=2)
        words.extend([
            {"text": "@", "bbox": (80, continuation_y, 98, continuation_y + 14), "confidence": 0.80},
            {"text": f"연속{choice_number}", "bbox": (110, continuation_y, 300, continuation_y + 14), "confidence": 0.98},
        ])
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [
        f"㉦ 선택지{number} @ 연속{number}" for number in range(1, 5)
    ]


def test_footer_ring_is_not_used_as_the_fourth_choice_marker():
    words = [
        {"text": "4.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 40, 92, 54), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    for number, y in enumerate((700, 770, 840, 910), start=1):
        draw.ellipse((50, y, 68, y + 14), outline=0, width=2)
        words.extend([
            {"text": "㉦", "bbox": (50, y, 68, y + 14), "confidence": 0.80},
            {"text": f"선택지{number}", "bbox": (80, y, 300, y + 14), "confidence": 0.98},
        ])
    draw.ellipse((50, 940, 68, 954), outline=0, width=2)
    words.extend([
        {"text": "㉦", "bbox": (50, 940, 68, 954), "confidence": 0.80},
        {
            "text": "[론박 합격코스 커리큘럼]",
            "bbox": (80, 940, 300, 954),
            "confidence": 0.98,
        },
    ])
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [f"선택지{number}" for number in range(1, 5)]
    assert restored.lines[-1].words[0].visual_choice_marker is False


def test_two_by_two_outer_choice_rings_ignore_inner_proposition_rings():
    words = [
        {"text": "9.", "bbox": (20, 40, 42, 54), "confidence": 0.98},
        {"text": "문제", "bbox": (52, 40, 92, 54), "confidence": 0.98},
    ]
    image = Image.new("L", (1000, 1000), 255)
    draw = ImageDraw.Draw(image)
    choice_number = 1
    for y in (100, 200):
        for outer_x in (50, 250):
            inner_x = outer_x + 50
            draw.ellipse((outer_x, y, outer_x + 18, y + 14), outline=0, width=2)
            draw.ellipse((inner_x, y, inner_x + 18, y + 14), outline=0, width=2)
            words.extend([
                {"text": "㉦", "bbox": (outer_x, y, outer_x + 18, y + 14), "confidence": 0.80},
                {"text": "㉠", "bbox": (inner_x, y, inner_x + 18, y + 14), "confidence": 0.80},
                {
                    "text": f"값{choice_number}",
                    "bbox": (inner_x + 30, y, inner_x + 80, y + 14),
                    "confidence": 0.98,
                },
            ])
            choice_number += 1
    structured = build_structured_page(
        words, page_number=2, width=1000, height=1000,
        source="ocr", images=((0, 0, 1000, 1000),),
    )

    restored = PDFExtractor()._restore_visual_choice_markers(structured, image)
    question = OfflineExamParser().parse_pages([restored])[0]

    assert question.choices == [f"㉠ 값{number}" for number in range(1, 5)]
