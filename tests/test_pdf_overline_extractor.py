from types import SimpleNamespace

from src.parser.extractor import PDFExtractor


def _char(value, x0, y0, x1, y1):
    return {'c': value, 'bbox': (x0, y0, x1, y1)}


def test_pdf_extractor_detects_text_overline_marks_with_line_context():
    extractor = PDFExtractor()
    page = SimpleNamespace(
        get_drawings=lambda: [
            {
                'items': [
                    (
                        'l',
                        SimpleNamespace(x=50, y=10),
                        SimpleNamespace(x=74, y=10),
                    )
                ]
            }
        ],
        get_text=lambda _kind: {
            'blocks': [
                {
                    'lines': [
                        {
                            'spans': [
                                {
                                    'chars': [
                                        _char('㉮', 10, 12, 18, 24),
                                        _char('Y', 24, 12, 32, 24),
                                        _char(' ', 32, 12, 38, 24),
                                        _char('=', 38, 12, 46, 24),
                                        _char(' ', 46, 12, 50, 24),
                                        _char('A', 50, 12, 58, 24),
                                        _char('+', 58, 12, 66, 24),
                                        _char('B', 66, 12, 74, 24),
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    )

    marks = extractor._extract_overlined_texts(page)

    assert len(marks) == 1
    assert marks[0].text == 'A+B'
    assert marks[0].line_text == '㉮Y = A+B'
    assert marks[0].start == 5
    assert marks[0].end == 8
