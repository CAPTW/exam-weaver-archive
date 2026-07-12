from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from src.parser.extractor import PDFExtractor
from src.parser.layout import LayoutWord, StructuredPage


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
