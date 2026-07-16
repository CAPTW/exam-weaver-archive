from src.parser.table_detection import assign_table_owner, detect_grid_tables


def test_grid_detector_assigns_each_word_once():
    horizontal = [(0, 0, 200, 0), (0, 50, 200, 50), (0, 100, 200, 100)]
    vertical = [(0, 0, 0, 100), (100, 0, 100, 100), (200, 0, 200, 100)]
    words = [
        {"text": "구분", "bbox": (20, 15, 60, 35), "confidence": .98},
        {"text": "값", "bbox": (130, 15, 150, 35), "confidence": .97},
        {"text": "A", "bbox": (30, 65, 45, 85), "confidence": .96},
        {"text": "10", "bbox": (130, 65, 150, 85), "confidence": .95},
    ]

    tables = detect_grid_tables(horizontal, vertical, words)

    assert len(tables) == 1
    assert tables[0]["rows"] == [["구분", "값"], ["A", "10"]]
    assigned = [cell["text"] for cell in tables[0]["cells"] if cell["text"]]
    assert assigned == ["구분", "값", "A", "10"]
    assert tables[0]["confidence"]["score"] >= .90
    assert "ocr_grid" in tables[0]["confidence"]["reasons"]


def test_incomplete_grid_is_not_reported_as_table():
    assert detect_grid_tables(
        [(0, 0, 100, 0), (0, 50, 100, 50)],
        [(0, 0, 0, 50)],
        [],
    ) == []


def test_choice_bbox_owns_intersecting_table():
    regions = {
        "question": (0, 0, 500, 300),
        "choices": {2: (0, 180, 500, 260)},
    }

    assert assign_table_owner((50, 195, 450, 245), regions) == ("choice", 2)


def test_ambiguous_owner_is_rejected():
    regions = {
        "question": (0, 0, 100, 100),
        "choices": {1: (0, 0, 100, 100)},
    }

    assert assign_table_owner((10, 10, 90, 90), regions) is None
