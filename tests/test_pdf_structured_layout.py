import io
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image, ImageDraw

from src.parser.extractor import PDFExtractor
from src.parser.layout import LayoutWord, StructuredPage, build_structured_page
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
