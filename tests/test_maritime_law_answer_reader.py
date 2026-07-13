from PIL import Image

from scripts.import_maritime_law_pdf import DigitAnswerTableReader


def test_answer_reader_accepts_only_explicit_all_correct_text(monkeypatch):
    reader = DigitAnswerTableReader()
    crop = Image.new("L", (140, 100), 255)
    monkeypatch.setattr(
        reader,
        "_read_crop_text_values",
        lambda _crop: ("l전원: \\정답!", "좋전원; 좋정답I"),
    )

    assert reader._classify_non_numeric_answer(crop) == -1

    monkeypatch.setattr(
        reader,
        "_read_crop_text_values",
        lambda _crop: ("인식 실패", "복수 정답"),
    )
    assert reader._classify_non_numeric_answer(crop) == 0


def test_table_candidate_scoring_never_runs_nonnumeric_ocr(monkeypatch):
    reader = DigitAnswerTableReader()
    lines = [
        {"y": 10, "count": 1300, "x0": 50, "x1": 1100},
        {"y": 80, "count": 600, "x0": 50, "x1": 1100},
        {"y": 150, "count": 1300, "x0": 50, "x1": 1100},
    ]
    calls = []
    monkeypatch.setattr(reader, "_horizontal_lines", lambda _gray: lines)

    def score_box(_image, box, *, recover_non_numeric=True):
        calls.append(recover_non_numeric)
        return [1] * (box[4] * 10)

    monkeypatch.setattr(reader, "_read_box", score_box)

    boxes = reader._table_boxes(Image.new("RGB", (1200, 200), "white"))

    assert boxes == [(10, 150, 50, 1100, 2)]
    assert calls == [False]
