"""Repository-owned, private-template-free HWPX layout profile."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HwpxTemplateProfile:
    name: str = "exam_generator_clean_v1"
    unit: str = "HWPUNIT"
    page_width: int = 72852
    page_height: int = 103180
    margin_left: int = 3402
    margin_right: int = 3402
    margin_top: int = 5102
    margin_bottom: int = 1984
    margin_header: int = 3968
    margin_footer: int = 2835
    cover_columns: int = 1
    body_columns: int = 2
    body_column_gap: int = 2268
    answer_key_layout_columns: int = 1
    answer_key_rows: int = 12
    answer_key_table_columns: int = 8
    answer_key_entries_per_table: int = 44
    font_name: str = "Malgun Gothic"


DEFAULT_HWPX_PROFILE = HwpxTemplateProfile()
