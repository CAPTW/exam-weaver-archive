"""Geometry-first table detection helpers for OCR and structured pages."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence


BBox = tuple[float, float, float, float]


def _cluster(values: Iterable[float], tolerance: float = 3.0) -> list[float]:
    ordered = sorted(float(value) for value in values)
    clusters: list[list[float]] = []
    for value in ordered:
        if not clusters or value - clusters[-1][-1] > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(group) / len(group) for group in clusters]


def _word_value(word: Mapping | Sequence) -> tuple[str, BBox, float]:
    if isinstance(word, Mapping):
        text = str(word.get("text") or "")
        bbox = tuple(float(value) for value in word.get("bbox", (0, 0, 0, 0)))
        confidence = word.get("confidence")
    else:
        x0, y0, x1, y1, text = word[:5]
        bbox = (float(x0), float(y0), float(x1), float(y1))
        confidence = word[5] if len(word) > 5 else None
    try:
        score = float(confidence) if confidence is not None else 1.0
    except (TypeError, ValueError):
        score = 0.0
    if score > 1.0:
        score /= 100.0
    return text, bbox, min(1.0, max(0.0, score))


def detect_grid_tables(
    horizontal_segments: Iterable[Sequence[float]],
    vertical_segments: Iterable[Sequence[float]],
    words: Iterable[Mapping | Sequence],
    tolerance: float = 3.0,
) -> list[dict]:
    """Build a rectangular OCR table when vector/raster line segments close a grid."""
    horizontal = [
        tuple(float(value) for value in segment[:4])
        for segment in horizontal_segments
        if len(segment) >= 4 and abs(float(segment[3]) - float(segment[1])) <= tolerance
    ]
    vertical = [
        tuple(float(value) for value in segment[:4])
        for segment in vertical_segments
        if len(segment) >= 4 and abs(float(segment[2]) - float(segment[0])) <= tolerance
    ]
    x_edges = _cluster(((line[0] + line[2]) / 2 for line in vertical), tolerance)
    y_edges = _cluster(((line[1] + line[3]) / 2 for line in horizontal), tolerance)
    if len(x_edges) < 3 or len(y_edges) < 3:
        return []

    x0, x1 = x_edges[0], x_edges[-1]
    y0, y1 = y_edges[0], y_edges[-1]
    horizontal_coverage = sum(
        1 for line in horizontal if min(line[0], line[2]) <= x0 + tolerance
        and max(line[0], line[2]) >= x1 - tolerance
    )
    vertical_coverage = sum(
        1 for line in vertical if min(line[1], line[3]) <= y0 + tolerance
        and max(line[1], line[3]) >= y1 - tolerance
    )
    if horizontal_coverage < len(y_edges) or vertical_coverage < len(x_edges):
        return []

    assigned: dict[tuple[int, int], list[tuple[float, float, str, float]]] = defaultdict(list)
    normalized_words = [_word_value(word) for word in words]
    words_in_table = 0
    for text, bbox, confidence in normalized_words:
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        if not (x0 <= center_x <= x1 and y0 <= center_y <= y1):
            continue
        words_in_table += 1
        for row in range(len(y_edges) - 1):
            if not y_edges[row] <= center_y <= y_edges[row + 1]:
                continue
            for col in range(len(x_edges) - 1):
                if x_edges[col] <= center_x <= x_edges[col + 1]:
                    assigned[(row, col)].append((bbox[1], bbox[0], text, confidence))
                    break
            break

    rows: list[list[str]] = []
    cells: list[dict] = []
    confidence_values = []
    for row in range(len(y_edges) - 1):
        row_values = []
        for col in range(len(x_edges) - 1):
            cell_words = sorted(assigned.get((row, col), []))
            text = " ".join(item[2] for item in cell_words).strip()
            confidence_values.extend(item[3] for item in cell_words)
            row_values.append(text)
            cells.append({
                "row": row,
                "col": col,
                "text": text,
                "row_span": 1,
                "col_span": 1,
                "horizontal_alignment": "left",
                "vertical_alignment": "center",
            })
        rows.append(row_values)

    assigned_count = sum(len(items) for items in assigned.values())
    assignment_ratio = assigned_count / max(1, words_in_table)
    mean_ocr = sum(confidence_values) / max(1, len(confidence_values))
    score = min(0.99, 0.70 + 0.20 * assignment_ratio + 0.10 * mean_ocr)
    widths = [
        (x_edges[index + 1] - x_edges[index]) / max(1e-9, x1 - x0)
        for index in range(len(x_edges) - 1)
    ]
    heights = [
        (y_edges[index + 1] - y_edges[index]) / max(1e-9, y1 - y0)
        for index in range(len(y_edges) - 1)
    ]
    return [{
        "rows": rows,
        "cells": cells,
        "bbox": (x0, y0, x1, y1),
        "column_widths": widths,
        "row_heights": heights,
        "confidence": {
            "score": round(score, 4),
            "reasons": ["ocr_grid", "all_words_assigned"]
            if assignment_ratio == 1.0 else ["ocr_grid"],
        },
        "complexity": {
            "has_formula": False,
            "has_embedded_image": False,
            "has_rotated_text": False,
            "has_complex_merge": False,
            "has_duplicate_text_risk": False,
        },
    }]


def _intersection_ratio(inner: BBox, outer: BBox) -> float:
    x0 = max(inner[0], outer[0])
    y0 = max(inner[1], outer[1])
    x1 = min(inner[2], outer[2])
    y1 = min(inner[3], outer[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area = max(1e-9, inner[2] - inner[0]) * max(1e-9, inner[3] - inner[1])
    return intersection / area


def _area(bbox: BBox) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def assign_table_owner(table_bbox: Sequence[float], regions: Mapping) -> tuple[str, int] | None:
    """Choose exactly one spatial owner, preferring a more specific choice region."""
    bbox = tuple(float(value) for value in table_bbox[:4])
    candidates: list[tuple[float, float, tuple[str, int]]] = []
    question = regions.get("question")
    if question:
        question_bbox = tuple(float(value) for value in question[:4])
        candidates.append((_intersection_ratio(bbox, question_bbox), _area(question_bbox), ("question", 0)))
    for number, choice in (regions.get("choices") or {}).items():
        choice_bbox = tuple(float(value) for value in choice[:4])
        candidates.append((_intersection_ratio(bbox, choice_bbox), _area(choice_bbox), ("choice", int(number))))
    eligible = [candidate for candidate in candidates if candidate[0] >= 0.50]
    if not eligible:
        return None
    eligible.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
    best = eligible[0]
    if len(eligible) > 1 and best[:2] == eligible[1][:2]:
        return None
    return best[2]
