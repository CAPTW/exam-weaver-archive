import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QAbstractItemView

from src.gui.table_preview import (
    ReadOnlyTablePreview,
    TablePreviewCard,
    build_preview_metadata,
)


APP = QApplication.instance() or QApplication([])


def _table():
    return {
        "id": "view-table-1",
        "rows": [["<보기>", ""], ["A", "B"]],
        "cells": [
            {
                "row": 0,
                "col": 0,
                "text": "<보기>",
                "row_span": 1,
                "col_span": 2,
                "horizontal_alignment": "center",
                "vertical_alignment": "top",
            },
            {"row": 1, "col": 0, "text": "A"},
            {"row": 1, "col": 1, "text": "B"},
        ],
        "layout": {"width_mode": "manual", "wide": False},
        "column_widths": [0.35, 0.65],
        "source": {"image_path": "missing-source.png"},
        "render_mode": "native",
    }


def _close(widget):
    widget.close()
    widget.deleteLater()
    APP.processEvents()


def test_metadata_reports_owner_shape_merge_width_and_docx_layout():
    metadata = build_preview_metadata("question", _table())

    assert metadata.owner_label == "발문"
    assert metadata.table_id == "view-table-1"
    assert metadata.dimensions == "2행 × 2열"
    assert metadata.merged_cells == 1
    assert metadata.width_label == "수동"
    assert metadata.docx_label == "DOCX 2단 · 82mm"


def test_preview_is_read_only_and_renders_spans_alignment_and_tooltip():
    preview = ReadOnlyTablePreview(_table())
    preview.show()
    APP.processEvents()

    item = preview.item(0, 0)
    assert preview.editTriggers() == QAbstractItemView.NoEditTriggers
    assert preview.selectionMode() == QAbstractItemView.NoSelection
    assert preview.rowSpan(0, 0) == 1
    assert preview.columnSpan(0, 0) == 2
    assert item.text() == "<보기>"
    assert item.toolTip() == "<보기>"
    assert item.textAlignment() & Qt.AlignHCenter
    assert item.textAlignment() & Qt.AlignTop
    assert preview.maximumHeight() == 180
    _close(preview)


def test_card_emits_actions_and_disables_missing_source():
    card = TablePreviewCard("question", _table())
    edits = []
    deletes = []
    card.editRequested.connect(lambda owner, table_id: edits.append((owner, table_id)))
    card.deleteRequested.connect(
        lambda owner, table_id: deletes.append((owner, table_id))
    )

    card.edit_button.click()
    card.preview.activated.emit()
    card.delete_button.click()

    assert edits == [
        ("question", "view-table-1"),
        ("question", "view-table-1"),
    ]
    assert deletes == [("question", "view-table-1")]
    assert card.source_button.isEnabled() is False
    assert "원본" in card.source_button.toolTip()
    _close(card)


def test_card_render_mode_signal_uses_owner_table_and_selected_mode():
    card = TablePreviewCard("choice:2", _table())
    emitted = []
    card.renderModeChanged.connect(
        lambda owner, table_id, mode: emitted.append((owner, table_id, mode))
    )

    card.mode_combo.setCurrentIndex(card.mode_combo.findData("image"))

    assert emitted[-1] == ("choice:2", "view-table-1", "image")
    assert "2번 선지" in card.metadata_label.text()
    _close(card)
