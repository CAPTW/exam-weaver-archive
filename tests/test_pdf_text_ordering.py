from types import SimpleNamespace

from src.parser.extractor import PDFExtractor
from src.parser.question import QuestionParser


def _word(x0, y0, x1, text):
    return (x0, y0, x1, y0 + 12, text, 0, 0, 0)


def test_pdf_extractor_rebuilds_mixed_english_korean_text_by_position():
    page = SimpleNamespace(
        rect=SimpleNamespace(width=728),
        get_text=lambda kind: [
            _word(374.9, 631.1, 385.8, '4.'),
            _word(392.2, 631.1, 431.9, 'Anchor'),
            _word(431.9, 631.1, 443.9, '와'),
            _word(450.9, 631.1, 490.6, 'Anchor'),
            _word(497.7, 631.1, 527.9, 'chain'),
            _word(527.9, 631.1, 539.9, '의'),
            _word(547.0, 631.1, 595.0, '파주력과'),
            _word(601.9, 631.1, 649.9, '직접적인'),
            _word(657.0, 631.1, 693.0, '관계가'),
            _word(392.2, 645.5, 416.2, '없는'),
            _word(422.2, 645.5, 452.7, '것은?'),
            _word(394.9, 701.3, 406.9, '㉴'),
            _word(411.4, 701.3, 451.1, 'Anchor'),
            _word(451.1, 701.3, 463.1, '의'),
            _word(469.1, 701.3, 493.1, '중량'),
            _word(394.9, 718.9, 406.9, '㉵'),
            _word(411.4, 718.9, 451.1, 'Anchor'),
            _word(457.1, 718.9, 487.3, 'chain'),
            _word(487.3, 718.9, 499.3, '의'),
            _word(505.3, 718.9, 541.3, '파주부'),
            _word(547.3, 718.9, 571.3, '길이'),
        ] if kind == 'words' else [],
    )

    text = PDFExtractor()._extract_positioned_text(page)

    assert '4. Anchor와 Anchor chain의 파주력과 직접적인 관계가' in text
    assert '㉴ Anchor의 중량' in text
    assert '㉵ Anchor chain의 파주부 길이' in text


def test_question_parser_preserves_mixed_english_korean_choice_order_from_positioned_text():
    text = (
        '4. Anchor와 Anchor chain의 파주력과 직접적인 관계가\n'
        '없는 것은?㉮저질㉯선박의 배수량㉴ Anchor의 중량'
        '㉵ Anchor chain의 파주부 길이'
    )

    questions = QuestionParser('3급항해사(상선)')._parse_page(text, 1, [])

    assert questions[0].text == 'Anchor와 Anchor chain의 파주력과 직접적인 관계가 없는 것은?'
    assert questions[0].choices[2].text == 'Anchor의 중량'
    assert questions[0].choices[3].text == 'Anchor chain의 파주부 길이'


def test_pdf_extractor_places_overlapping_parenthesis_after_choice_marker():
    page = SimpleNamespace(
        rect=SimpleNamespace(width=728),
        get_text=lambda kind: [
            _word(54.84, 527.53, 123.72, '㉯출력용량'),
            _word(149.77, 527.53, 197.77, '입력용량'),
            _word(71.16, 527.53, 75.66, '('),
            _word(123.72, 527.53, 128.22, ')'),
            _word(134.10, 527.53, 139.10, '/'),
            _word(145.23, 527.53, 149.73, '('),
            _word(197.79, 527.53, 202.29, ')'),
        ] if kind == 'words' else [],
    )

    text = PDFExtractor()._extract_positioned_text(page)

    assert '㉯ (출력용량) / (입력용량)' in text


def test_pdf_extractor_restores_arrows_by_visual_position_not_stream_order():
    page = SimpleNamespace(
        rect=SimpleNamespace(width=728),
        get_text=lambda kind: [
            _word(80, 100, 130, '정적압축'),
            _word(160, 100, 210, '정적팽창'),
            _word(240, 100, 290, '단열팽창'),
            _word(320, 100, 370, '단열압축'),
            # The PDF stream emits symbols last even though their x positions
            # place them between the four process labels.
            _word(140, 100, 150, '→'),
            _word(220, 100, 230, '→'),
            _word(300, 100, 310, '→'),
        ] if kind == 'words' else [],
    )

    text = PDFExtractor()._extract_positioned_text(page)

    assert text == '정적압축 → 정적팽창 → 단열팽창 → 단열압축'


def test_pdf_extractor_restores_arrows_between_multiword_sequence_steps():
    page = SimpleNamespace(
        rect=SimpleNamespace(width=728),
        get_text=lambda kind: [
            _word(394.9, 483.3, 447.4, '㉮총톤수'),
            _word(453.4, 483.3, 477.4, '측정'),
            _word(489.4, 483.3, 513.4, '등기'),
            _word(525.4, 483.3, 561.4, '선적항'),
            _word(567.4, 483.3, 591.4, '결정'),
            _word(603.4, 483.3, 627.4, '등록'),
            # Stream order puts all arrows last; coordinates carry the order.
            _word(477.4, 483.3, 489.4, '→'),
            _word(513.4, 483.3, 525.4, '→'),
            _word(591.4, 483.3, 603.4, '→'),
        ] if kind == 'words' else [],
    )

    text = PDFExtractor()._extract_positioned_text(page)

    assert text == '㉮총톤수 측정→등기→선적항 결정→등록'


def test_pdf_extractor_uses_ocr_for_short_native_text_with_embedded_images():
    assert PDFExtractor._should_use_ocr_fallback('', False) is True
    assert PDFExtractor._should_use_ocr_fallback('해사영어 정답안', True) is True
    assert PDFExtractor._should_use_ocr_fallback('해사영어 정답안', False) is False
    assert PDFExtractor._should_use_ocr_fallback('문제 본문 ' * 80, True) is False
