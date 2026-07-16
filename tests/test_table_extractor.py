import hashlib
from pathlib import Path

import fitz

from src.parser.extractor import PDFExtractor
from src.parser.layout import build_structured_page


def _build_native_table_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=400, height=300)
    x_positions = (40, 180, 320)
    y_positions = (60, 110, 160)
    for x in x_positions:
        page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
    for y in y_positions:
        page.draw_line((x_positions[0], y), (x_positions[-1], y))
    page.insert_text((60, 90), "TYPE")
    page.insert_text((200, 90), "VALUE")
    page.insert_text((60, 140), "A")
    page.insert_text((200, 140), "10")
    document.save(path)
    document.close()
    return path


def _build_merged_table_pdf(path: Path) -> Path:
    document = fitz.open()
    page = document.new_page(width=300, height=220)
    page.draw_rect((40, 40, 240, 140))
    page.draw_line((40, 90), (240, 90))
    page.draw_line((140, 90), (140, 140))
    page.insert_text((90, 70), "HEADER")
    page.insert_text((80, 120), "A")
    page.insert_text((180, 120), "B")
    document.save(path)
    document.close()
    return path


def test_native_table_keeps_structure_and_source_crop(tmp_path):
    pdf_path = _build_native_table_pdf(tmp_path / "native.pdf")
    document = fitz.open(pdf_path)
    try:
        table_dir = tmp_path / "table_images"
        tables = PDFExtractor(tmp_path / "out")._extract_text_tables(
            document[0],
            page_number=1,
            source_path=pdf_path,
            table_image_dir=table_dir,
        )
    finally:
        document.close()

    assert len(tables) == 1
    table = tables[0]
    assert table.rows == [["TYPE", "VALUE"], ["A", "10"]]
    assert table.cells[0]["row"] == 0
    assert table.cells[0]["col"] == 0
    assert len(table.column_widths) == 2
    assert abs(sum(table.column_widths) - 1.0) < 0.01
    assert len(table.row_heights) == 2
    crop_path = Path(table.source["image_path"])
    assert crop_path.is_file()
    assert table.source["page"] == 1
    assert table.source["source_pdf_relative_path"] == "native.pdf"
    assert table.source["sha256"] == hashlib.sha256(crop_path.read_bytes()).hexdigest()
    assert table.confidence["score"] >= 0.90
    assert "native_grid" in table.confidence["reasons"]


def test_table_crop_failure_is_recorded_without_dropping_structure(tmp_path):
    class FakeTable:
        bbox = (0, 0, 10, 10)
        cells = []

        @staticmethod
        def extract():
            return [["A"]]

    class FakeFinder:
        tables = [FakeTable()]

    class FakePage:
        rect = (0, 0, 10, 10)

        @staticmethod
        def find_tables():
            return FakeFinder()

        @staticmethod
        def get_pixmap(**_kwargs):
            raise RuntimeError("render unavailable")

        @staticmethod
        def get_text(*_args, **_kwargs):
            return []

        @staticmethod
        def get_images(**_kwargs):
            return []

    table = PDFExtractor(tmp_path)._extract_text_tables(
        FakePage(),
        page_number=1,
        source_path=tmp_path / "fake.pdf",
        table_image_dir=tmp_path / "tables",
    )[0]

    assert table.rows == [["A"]]
    assert table.source["missing_reason"] == "RuntimeError"


def test_ocr_grid_is_converted_to_hybrid_table_data(tmp_path):
    line_items = []
    for y in (0, 50, 100):
        line_items.append(("l", (0, y), (200, y)))
    for x in (0, 100, 200):
        line_items.append(("l", (x, 0), (x, 100)))

    class Pixmap:
        @staticmethod
        def save(path):
            Path(path).write_bytes(b"ocr-crop")

    class FakePage:
        @staticmethod
        def get_drawings():
            return [{"items": line_items}]

        @staticmethod
        def get_pixmap(**_kwargs):
            return Pixmap()

    structured = build_structured_page(
        [
            (20, 15, 60, 35, "구분", .98),
            (130, 15, 150, 35, "값", .97),
            (30, 65, 45, 85, "A", .96),
            (130, 65, 150, 85, "10", .95),
        ],
        page_number=1,
        width=200,
        height=100,
        source="ocr",
    )

    tables = PDFExtractor(tmp_path)._extract_ocr_grid_tables(
        FakePage(),
        structured,
        page_number=1,
        source_path=tmp_path / "scan.pdf",
        table_image_dir=tmp_path / "tables",
    )

    assert tables[0].rows == [["구분", "값"], ["A", "10"]]
    assert tables[0].confidence["reasons"][0] == "ocr_grid"
    assert Path(tables[0].source["image_path"]).is_file()


def test_native_merged_cell_geometry_is_preserved(tmp_path):
    pdf_path = _build_merged_table_pdf(tmp_path / "merged.pdf")
    document = fitz.open(pdf_path)
    try:
        table = PDFExtractor(tmp_path)._extract_text_tables(
            document[0],
            page_number=1,
            source_path=pdf_path,
            table_image_dir=tmp_path / "tables",
        )[0]
    finally:
        document.close()

    header = next(cell for cell in table.cells if cell["text"] == "HEADER")
    assert header["row"] == 0
    assert header["col"] == 0
    assert header["col_span"] == 2
    assert table.complexity["has_complex_merge"] is False
