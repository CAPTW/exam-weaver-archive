from pathlib import Path
import json
import random
from zipfile import ZipFile

from lxml import etree
from docx import Document
from PIL import Image

from src.exporter.docx import DocxExporter


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
MATH_NS = {"m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
ALL_NS = {**NS, **MATH_NS}
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xd2\xe5\xc7\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _read_document_xml(path: Path):
    with ZipFile(path) as docx:
        return etree.fromstring(docx.read("word/document.xml"))


def _paragraph_text(paragraph):
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def _paragraphs(document_xml):
    return document_xml.xpath("//w:body/w:p", namespaces=NS)


def _run_text(run):
    return "".join(run.xpath(".//w:t/text()", namespaces=NS))


def _math_texts(element):
    return element.xpath(".//m:t/text()", namespaces=MATH_NS)


def test_export_renders_descriptive_question_with_model_answer(tmp_path):
    output_path = tmp_path / "descriptive.docx"
    questions = [
        {
            "question_text": "복원성을 설명하시오.",
            "question_type": "descriptive",
            "model_answer": "기울어진 선박이 원래 자세로 돌아가려는 성질이다.",
            "choices": [],
            "correct_answer": 0,
        }
    ]

    DocxExporter().export("서술형 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    paragraph_texts = [_paragraph_text(p) for p in _paragraphs(document_xml)]

    assert "1. 복원성을 설명하시오." in paragraph_texts
    assert "모범답안: 기울어진 선박이 원래 자세로 돌아가려는 성질이다." in paragraph_texts


def test_export_renders_grouped_subject_sections_for_multi_subject_mock(tmp_path):
    output_path = tmp_path / "multi-subject.docx"
    sections = [
        {
            "title": "기관1",
            "questions": [
                {
                    "question_text": "기관1 문제",
                    "correct_answer": 1,
                    "choices": [
                        {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                    ],
                }
            ],
        },
        {
            "title": "기관2",
            "questions": [
                {
                    "question_text": "기관2 문제",
                    "correct_answer": 1,
                    "choices": [
                        {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "B"},
                    ],
                }
            ],
        },
    ]

    DocxExporter().export("2026.06.22 3급 기관사 모의고사", [], str(output_path), sections=sections)

    document_xml = _read_document_xml(output_path)
    paragraph_texts = [_paragraph_text(p) for p in _paragraphs(document_xml)]

    assert paragraph_texts[:10] == [
        "2026.06.22 3급 기관사 모의고사 ",
        "기관1",
        "",
        "1. 기관1 문제",
        "㉮ A",
        "",
        "기관2",
        "",
        "2. 기관2 문제",
        "㉮ B",
    ]
    subject_paragraphs = [
        p for p in _paragraphs(document_xml)
        if _paragraph_text(p) in {"기관1", "기관2"}
    ]
    assert all(p.xpath("./w:pPr/w:jc/@w:val", namespaces=NS) == ["center"] for p in subject_paragraphs)
    assert all(p.xpath(".//w:b", namespaces=NS) for p in subject_paragraphs)


def test_export_renders_group_shared_passage_once_and_numbers_children(tmp_path):
    output_path = tmp_path / "grouped-passage.docx"
    questions = [
        {
            "id": 1,
            "group_id": 10,
            "group_order": 1,
            "shared_passage": "공통 지문 본문",
            "question_text": "첫 번째 하위 문제",
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "정답"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "오답"},
            ],
        },
        {
            "id": 2,
            "group_id": 10,
            "group_order": 2,
            "shared_passage": "공통 지문 본문",
            "question_text": "두 번째 하위 문제",
            "correct_answer": 2,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "오답"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "정답"},
            ],
        },
    ]

    DocxExporter().export("공통지문 테스트", questions, str(output_path), include_answer_key=True)

    document_xml = _read_document_xml(output_path)
    paragraph_texts = [_paragraph_text(p) for p in _paragraphs(document_xml)]

    assert paragraph_texts.count("[공통지문] 공통 지문 본문") == 1
    assert "1. 첫 번째 하위 문제" in paragraph_texts
    assert "2. 두 번째 하위 문제" in paragraph_texts
    assert "Answer Key" in paragraph_texts
    assert "1. ㉮  2. ㉯" in paragraph_texts


def test_export_uses_group_shared_text_when_shared_passage_is_absent(tmp_path):
    output_path = tmp_path / "group-shared-text.docx"
    questions = [
        {
            "id": 1,
            "group_id": 0,
            "group_order": 1,
            "group_shared_text": "group_shared_text 공통 지문",
            "question_text": "첫 번째 하위 문제",
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "정답"},
            ],
        },
        {
            "id": 2,
            "group_id": 0,
            "group_order": 2,
            "group_shared_text": "group_shared_text 공통 지문",
            "question_text": "두 번째 하위 문제",
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "정답"},
            ],
        },
    ]

    DocxExporter().export("공통지문 fallback 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    paragraph_texts = [_paragraph_text(p) for p in _paragraphs(document_xml)]
    passage = "[공통지문] group_shared_text 공통 지문"

    assert paragraph_texts.count(passage) == 1
    assert paragraph_texts.index(passage) < paragraph_texts.index("1. 첫 번째 하위 문제")
    assert paragraph_texts.index(passage) < paragraph_texts.index("2. 두 번째 하위 문제")


def test_export_repairs_pdf_linewrap_and_parenthetical_note_artifact(tmp_path):
    output_path = tmp_path / "ocr-artifact.docx"
    questions = [
        {
            "question_text": (
                "크랭크암 개폐량의 허용한도 중 안전하게 운전할 수 \n"
                "있는 한도는 단 는 행정 이다? ( , S [mm] .)"
            ),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "정답"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "오답"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "오답"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "오답"},
            ],
        }
    ]

    DocxExporter().export("OCR 보정 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    question_paragraph = _paragraphs(document_xml)[1]

    assert _paragraph_text(question_paragraph) == (
        "1. 크랭크암 개폐량의 허용한도 중 안전하게 운전할 수 "
        "있는 한도는? (단, S는 행정[mm]이다.)"
    )
    assert not question_paragraph.xpath(".//w:br", namespaces=NS)


def test_export_uses_reference_exam_layout_and_highlights_correct_choice(tmp_path):
    output_path = tmp_path / "exam.docx"
    questions = [
        {
            "question_text": "축계의 탐상법 중 침투액, 솔벤트 및 현상액을 사용하여 균열을 확인하는 방법은?",
            "correct_answer": 3,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "자분 탐상법"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "초음파 탐상법"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "컬러 체크"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "방사선 탐상법"},
            ],
        }
    ]

    DocxExporter().export("2023-2025 4급 기관사\n기관1", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    section = document_xml.xpath("//w:body/w:sectPr", namespaces=NS)[0]
    assert section.xpath("./w:pgSz/@w:w", namespaces=NS) == ["11906"]
    assert section.xpath("./w:pgSz/@w:h", namespaces=NS) == ["16838"]
    assert section.xpath("./w:pgMar/@w:top", namespaces=NS) == ["850"]
    assert section.xpath("./w:pgMar/@w:right", namespaces=NS) == ["850"]
    assert section.xpath("./w:pgMar/@w:bottom", namespaces=NS) == ["850"]
    assert section.xpath("./w:pgMar/@w:left", namespaces=NS) == ["850"]
    assert section.xpath("./w:cols/@w:num", namespaces=NS) == ["2"]
    assert section.xpath("./w:cols/@w:sep", namespaces=NS) == ["1"]
    assert section.xpath("./w:cols/@w:space", namespaces=NS) == ["425"]

    paragraphs = _paragraphs(document_xml)
    assert [_paragraph_text(p) for p in paragraphs] == [
        "2023-2025 4급 기관사 ",
        "기관1 ",
        "1. 축계의 탐상법 중 침투액, 솔벤트 및 현상액을 사용하여 균열을 확인하는 방법은?",
        "㉮ 자분 탐상법",
        "㉯ 초음파 탐상법",
        "㉴ 컬러 체크",
        "㉵ 방사선 탐상법",
        "",
    ]

    for paragraph in paragraphs:
        assert paragraph.xpath("./w:pPr/w:spacing/@w:after", namespaces=NS) == ["0"]
        assert paragraph.xpath("./w:pPr/w:spacing/@w:line", namespaces=NS) == ["160"]
        assert paragraph.xpath("./w:pPr/w:spacing/@w:lineRule", namespaces=NS) == ["atLeast"]
        assert paragraph.xpath(".//w:rFonts/@w:eastAsia", namespaces=NS)
        assert set(paragraph.xpath(".//w:rFonts/@w:eastAsia", namespaces=NS)) == {
            "경기천년제목OTF Light"
        }

    assert paragraphs[0].xpath(".//w:sz/@w:val", namespaces=NS) == ["32"]
    assert paragraphs[1].xpath(".//w:sz/@w:val", namespaces=NS) == ["32"]
    assert set(paragraphs[3].xpath(".//w:sz/@w:val", namespaces=NS)) == {"20"}

    highlighted = [
        _paragraph_text(p)
        for p in paragraphs
        if p.xpath(".//w:highlight[@w:val='yellow']", namespaces=NS)
    ]
    assert highlighted == ["㉴ 컬러 체크"]
    assert "Answer Key" not in "\n".join(_paragraph_text(p) for p in paragraphs)


def test_export_highlights_every_choice_for_all_choices_correct(tmp_path):
    output_path = tmp_path / "all-correct.docx"
    questions = [{
        "question_text": "전원 정답 문제",
        "correct_answer": -1,
        "choices": [
            {
                "choice_number": number,
                "choice_symbol": symbol,
                "choice_text": f"선택지 {number}",
            }
            for number, symbol in enumerate(("㉮", "㉯", "㉴", "㉵"), start=1)
        ],
    }]

    DocxExporter().export("전원 정답", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    highlighted = [
        _paragraph_text(paragraph)
        for paragraph in _paragraphs(document_xml)
        if paragraph.xpath(".//w:highlight[@w:val='yellow']", namespaces=NS)
    ]
    assert highlighted == [
        "㉮ 선택지 1", "㉯ 선택지 2", "㉴ 선택지 3", "㉵ 선택지 4"
    ]


def test_shuffle_choices_moves_correct_answer_highlight_to_new_position(tmp_path):
    question = {
        "question_text": "정답 재배치 확인 문제",
        "correct_answer": 2,
        "choices": [
            {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "오답 A"},
            {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "정답 B"},
            {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "오답 C"},
            {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "오답 D"},
        ],
    }
    exporter = DocxExporter()
    document = Document()
    exporter._set_document_defaults(document)

    answer_symbol = exporter._add_question(
        document,
        question,
        display_number=1,
        shuffle_choices=True,
        rng=random.Random(1),
    )

    output_path = tmp_path / "shuffled.docx"
    document.save(output_path)
    document_xml = _read_document_xml(output_path)
    paragraphs = _paragraphs(document_xml)
    choice_paragraphs = paragraphs[1:]
    choice_texts = [_paragraph_text(p) for p in choice_paragraphs]
    highlighted = [
        _paragraph_text(p)
        for p in choice_paragraphs
        if p.xpath(".//w:highlight[@w:val='yellow']", namespaces=NS)
    ]

    assert choice_texts == ["㉮ 오답 D", "㉯ 오답 A", "㉴ 오답 C", "㉵ 정답 B"]
    assert answer_symbol == "㉵"
    assert highlighted == ["㉵ 정답 B"]


def test_export_includes_choice_image_with_matching_choice(tmp_path):
    image_path = tmp_path / "choice.png"
    image_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "choice-image.docx"
    questions = [
        {
            "question_text": "이미지가 있는 선지는?",
            "correct_answer": 2,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "텍스트"},
                {
                    "choice_number": 2,
                    "choice_symbol": "㉯",
                    "choice_text": "그림",
                    "choice_image_path": str(image_path),
                },
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "텍스트"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "텍스트"},
            ],
        }
    ]

    DocxExporter().export("선지 이미지 테스트", questions, str(output_path))

    with ZipFile(output_path) as docx:
        media_files = [name for name in docx.namelist() if name.startswith("word/media/")]
        document_xml = etree.fromstring(docx.read("word/document.xml"))

    assert len(media_files) == 1
    paragraphs = _paragraphs(document_xml)
    paragraph_texts = [_paragraph_text(p) for p in paragraphs]
    assert "㉯ 그림" in paragraph_texts
    assert document_xml.xpath("//w:drawing", namespaces=NS)


def test_export_places_choice_image_in_same_paragraph_as_choice_label(tmp_path):
    image_path = tmp_path / "choice.png"
    image_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "choice-image-inline.docx"
    questions = [
        {
            "question_text": "이미지 선지를 고른 것은?",
            "correct_answer": 2,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "텍스트"},
                {
                    "choice_number": 2,
                    "choice_symbol": "㉯",
                    "choice_text": "",
                    "choice_image_path": str(image_path),
                },
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "텍스트"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "텍스트"},
            ],
        }
    ]

    DocxExporter().export("선지 이미지 배치 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    drawing_paragraphs = [
        paragraph
        for paragraph in _paragraphs(document_xml)
        if paragraph.xpath(".//w:drawing", namespaces=NS)
    ]

    assert len(drawing_paragraphs) == 1
    assert _paragraph_text(drawing_paragraphs[0]) == "㉯ "


def test_export_renders_underlined_question_text_from_format_json(tmp_path):
    output_path = tmp_path / "underline.docx"
    questions = [
        {
            "question_text": "밑줄 친 부분에 알맞은 것은?",
            "question_format_json": json.dumps({
                "spans": [{"start": 0, "end": 2, "underline": True}]
            }, ensure_ascii=False),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "정답"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "오답"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "오답"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "오답"},
            ],
        }
    ]

    DocxExporter().export("밑줄 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    question_paragraph = _paragraphs(document_xml)[1]
    underlined_runs = [
        _run_text(run)
        for run in question_paragraph.xpath("./w:r", namespaces=NS)
        if run.xpath("./w:rPr/w:u", namespaces=NS)
    ]

    assert underlined_runs == ["밑줄"]


def test_export_renders_table_format_as_native_word_table(tmp_path):
    output_path = tmp_path / "table.docx"
    questions = [
        {
            "question_text": "다음 표를 보고 옳은 것은?",
            "question_format_json": json.dumps({
                "tables": [
                    {"rows": [["구분", "값"], ["A", "10"], ["B", "20"]]}
                ]
            }, ensure_ascii=False),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    DocxExporter().export("표 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    tables = document_xml.xpath("//w:tbl", namespaces=NS)
    cell_texts = document_xml.xpath("//w:tbl//w:t/text()", namespaces=NS)

    assert len(tables) == 1
    assert cell_texts == ["구분", "값", "A", "10", "B", "20"]


def test_export_keeps_question_image_when_table_format_is_absent(tmp_path):
    image_path = tmp_path / "question.png"
    image_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "question-image.docx"
    questions = [
        {
            "question_text": "이미지 표를 보고 옳은 것은?",
            "image_path": str(image_path),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    DocxExporter().export("이미지 fallback 테스트", questions, str(output_path))

    with ZipFile(output_path) as docx:
        media_files = [name for name in docx.namelist() if name.startswith("word/media/")]
        document_xml = etree.fromstring(docx.read("word/document.xml"))

    assert len(media_files) == 1
    assert document_xml.xpath("//w:drawing", namespaces=NS)


def test_export_keeps_question_image_paragraph_with_question_block(tmp_path):
    image_path = tmp_path / "question.png"
    image_path.write_bytes(PNG_1X1)
    output_path = tmp_path / "question-image-keep.docx"
    questions = [
        {
            "question_text": "다음 그림을 보고 옳은 것은?",
            "image_path": str(image_path),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    DocxExporter().export("이미지 keep 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    paragraphs = _paragraphs(document_xml)
    question_paragraph = next(
        paragraph for paragraph in paragraphs
        if _paragraph_text(paragraph).startswith("1. 다음 그림")
    )
    image_paragraph = next(
        paragraph for paragraph in paragraphs
        if paragraph.xpath(".//w:drawing", namespaces=NS)
    )

    assert question_paragraph.xpath("./w:pPr/w:keepNext", namespaces=NS)
    assert image_paragraph.xpath("./w:pPr/w:keepNext", namespaces=NS)
    assert image_paragraph.xpath("./w:pPr/w:keepLines", namespaces=NS)


def test_export_converts_images_that_python_docx_cannot_read_directly(tmp_path):
    image_path = tmp_path / "zero-dpi.jpg"
    Image.new('RGB', (8, 8), 'white').save(image_path, dpi=(0, 0))
    output_path = tmp_path / "normalized-image.docx"
    questions = [
        {
            "question_text": "이미지 변환 테스트",
            "image_path": str(image_path),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    DocxExporter().export("이미지 변환 테스트", questions, str(output_path))

    with ZipFile(output_path) as docx:
        media_files = [name for name in docx.namelist() if name.startswith("word/media/")]
        document_xml = etree.fromstring(docx.read("word/document.xml"))

    assert len(media_files) == 1
    assert document_xml.xpath("//w:drawing", namespaces=NS)


def test_export_converts_extracted_pdf_jpeg_with_invalid_density(tmp_path):
    image_path = Path("data/extracted/images/2022_202203/34_46_xref1199.jpeg")
    output_path = tmp_path / "extracted-jpeg.docx"
    questions = [
        {
            "question_text": "실제 추출 이미지 변환 테스트",
            "image_path": str(image_path),
            "correct_answer": 1,
            "choices": [
                {"choice_number": 1, "choice_symbol": "㉮", "choice_text": "A"},
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    assert image_path.exists()

    DocxExporter().export("추출 이미지 변환 테스트", questions, str(output_path))

    with ZipFile(output_path) as docx:
        media_files = [name for name in docx.namelist() if name.startswith("word/media/")]
        document_xml = etree.fromstring(docx.read("word/document.xml"))

    assert len(media_files) == 1
    assert document_xml.xpath("//w:drawing", namespaces=NS)


def test_export_renders_latex_equation_spans_in_latex_style(tmp_path):
    output_path = tmp_path / "equation.docx"
    questions = [
        {
            "question_text": "값은 \\sqrt{GM} 이다",
            "question_format_json": json.dumps({
                "spans": [{"start": 3, "end": 12, "latex": "\\sqrt{GM}"}]
            }, ensure_ascii=False),
            "correct_answer": 1,
            "choices": [
                {
                    "choice_number": 1,
                    "choice_symbol": "㉮",
                    "choice_text": "\\sqrt{L}",
                    "choice_format_json": json.dumps({
                        "spans": [{"start": 0, "end": 8, "latex": "\\sqrt{L}"}]
                    }, ensure_ascii=False),
                },
                {"choice_number": 2, "choice_symbol": "㉯", "choice_text": "B"},
                {"choice_number": 3, "choice_symbol": "㉴", "choice_text": "C"},
                {"choice_number": 4, "choice_symbol": "㉵", "choice_text": "D"},
            ],
        }
    ]

    DocxExporter().export("수식 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    paragraph_texts = [_paragraph_text(p) for p in _paragraphs(document_xml)]
    math_texts = _math_texts(document_xml)

    assert "1. 값은  이다" in paragraph_texts
    assert "㉮ " in paragraph_texts
    assert math_texts == ["GM", "L"]
    assert document_xml.xpath("//m:rad", namespaces=MATH_NS)


def test_export_renders_composite_latex_power_formula_as_word_math(tmp_path):
    output_path = tmp_path / "power-formula.docx"
    latex = r"P=\sqrt{3} \times E \times I \times \cos\theta"
    questions = [
        {
            "question_text": "3상 교류 유효전력을 표시한 것으로 옳은 것은?",
            "correct_answer": 1,
            "choices": [
                {
                    "choice_number": 1,
                    "choice_symbol": "㉮",
                    "choice_text": latex,
                    "choice_format_json": json.dumps({
                        "spans": [{"start": 0, "end": len(latex), "latex": latex}]
                    }, ensure_ascii=False),
                },
            ],
        }
    ]

    DocxExporter().export("복합 수식 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    visible_text = "".join(document_xml.xpath("//w:t/text()", namespaces=NS))
    math_texts = _math_texts(document_xml)

    assert r"\sqrt" not in visible_text
    assert r"\times" not in visible_text
    assert math_texts == ["P=", "3", " × E × I × cosθ"]
    assert len(document_xml.xpath("//m:rad", namespaces=MATH_NS)) == 1


def test_export_renders_unicode_sqrt_and_private_math_glyphs_visibly(tmp_path):
    output_path = tmp_path / "unicode-equation.docx"
    questions = [
        {
            "question_text": "3상 전력은 \ue05c\ue06d\ue036EIcos\ue0a4이다.",
            "correct_answer": 1,
            "choices": [
                {
                    "choice_number": 1,
                    "choice_symbol": "㉮",
                    "choice_text": "값은 √3배",
                },
            ],
        }
    ]

    DocxExporter().export("유니코드 수식 테스트", questions, str(output_path))

    document_xml = _read_document_xml(output_path)
    visible_text = "".join(document_xml.xpath("//w:t/text()", namespaces=NS))
    math_texts = _math_texts(document_xml)

    assert "\ue05c" not in visible_text
    assert "\ue06d" not in visible_text
    assert "\ue036" not in visible_text
    assert "\ue0a4" not in visible_text
    assert "θ" in visible_text
    assert math_texts == ["3", "3"]
    assert len(document_xml.xpath("//m:rad", namespaces=MATH_NS)) == 2
