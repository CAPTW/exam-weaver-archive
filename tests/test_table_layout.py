import pytest

from src.exporter.table_layout import (
    NARROW_TABLE_WIDTH_MM,
    WIDE_TABLE_WIDTH_MM,
    display_units,
    resolve_table_layout,
)


def test_display_units_uses_longest_line_and_character_classes():
    assert display_units("한글 AB") == pytest.approx(6.5)
    assert display_units("짧음\n가장긴줄ABC") == pytest.approx(11.0)


def test_manual_widths_override_content_scores():
    layout = resolve_table_layout({
        "rows": [["아주 긴 첫 번째 열", "B"]],
        "column_widths": [0.25, 0.75],
        "layout": {"width_mode": "manual"},
    })

    assert layout.width_mode == "manual"
    assert layout.column_widths == pytest.approx((0.25, 0.75))


def test_legacy_source_widths_override_auto_content_scores():
    layout = resolve_table_layout({
        "rows": [["아주 긴 첫 번째 열", "B"]],
        "column_widths": [0.4, 0.6],
    })

    assert layout.width_mode == "source"
    assert layout.column_widths == pytest.approx((0.4, 0.6))


def test_auto_layout_gives_more_width_to_long_content():
    layout = resolve_table_layout({
        "rows": [["구분", "매우 긴 설명 문자열입니다"]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.column_widths[1] > layout.column_widths[0]
    assert sum(layout.column_widths) == pytest.approx(1.0)
    assert layout.total_width_mm == NARROW_TABLE_WIDTH_MM


def test_merged_cell_need_is_distributed_across_spanned_columns():
    layout = resolve_table_layout({
        "rows": [["긴 병합 제목", ""], ["A", "B"]],
        "cells": [
            {"row": 0, "col": 0, "text": "긴 병합 제목", "row_span": 1, "col_span": 2},
            {"row": 1, "col": 0, "text": "A", "row_span": 1, "col_span": 1},
            {"row": 1, "col": 1, "text": "B", "row_span": 1, "col_span": 1},
        ],
        "layout": {"width_mode": "auto"},
    })

    assert layout.column_widths[0] == pytest.approx(layout.column_widths[1])


def test_too_many_minimum_width_columns_switch_to_wide_layout():
    layout = resolve_table_layout({
        "rows": [["A", "B", "C", "D", "E", "F", "G"]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.wide is True
    assert layout.total_width_mm == WIDE_TABLE_WIDTH_MM
    assert min(layout.column_widths_mm) >= 12.0


def test_predicted_four_line_wrap_switches_to_wide_layout():
    layout = resolve_table_layout({
        "rows": [["A", "한글" * 40]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.wide is True
    assert layout.total_width_mm == WIDE_TABLE_WIDTH_MM
    assert layout.estimated_max_lines <= 3


def test_long_one_cell_view_block_wraps_inside_narrow_column():
    layout = resolve_table_layout({
        "rows": [["<보기> " + ("긴 지문 내용 " * 80)]],
        "layout": {"width_mode": "auto"},
    })

    assert layout.wide is False
    assert layout.total_width_mm == NARROW_TABLE_WIDTH_MM
    assert layout.column_widths_mm == pytest.approx((NARROW_TABLE_WIDTH_MM,))


def test_explicit_wide_flag_always_wins():
    layout = resolve_table_layout({
        "rows": [["A"]],
        "layout": {"width_mode": "auto", "wide": True},
    })

    assert layout.wide is True
    assert layout.total_width_mm == WIDE_TABLE_WIDTH_MM


def test_auto_layout_enforces_minimum_and_maximum_column_widths():
    layout = resolve_table_layout({
        "rows": [["A", "한글" * 10, "B"]],
        "layout": {"width_mode": "auto"},
    })

    assert min(layout.column_widths_mm) >= 12.0
    assert max(layout.column_widths) <= 0.75
    assert sum(layout.column_widths_mm) == pytest.approx(layout.total_width_mm)
