"""Read-only visual previews and action cards for schema-v2 tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, ComboBox, PrimaryPushButton, PushButton

from ..exporter.table_layout import fallback_table_layout, resolve_table_layout
from ..parser.table_structure import normalize_rectangular_table


WIDTH_LABELS = {
    "auto": "자동",
    "source": "원본",
    "manual": "수동",
}


@dataclass(frozen=True)
class TablePreviewMetadata:
    """Compact labels shown above a visual table preview."""

    owner_label: str
    table_id: str
    dimensions: str
    merged_cells: int
    width_label: str
    docx_label: str
    layout_fallback: bool


def table_owner_label(owner: str) -> str:
    """Return the Korean location label for a table payload owner."""
    if owner == "question":
        return "발문"
    try:
        number = int(str(owner).split(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return str(owner or "표")
    return f"{number}번 선지"


def build_preview_metadata(owner: str, table_spec: dict) -> TablePreviewMetadata:
    """Build stable metadata without mutating the stored table payload."""
    table = normalize_rectangular_table(table_spec)
    try:
        layout = resolve_table_layout(table)
    except Exception:
        layout = fallback_table_layout(table)

    row_count = len(table["rows"])
    column_count = len(table["rows"][0])
    merged_cells = sum(
        int(cell.get("row_span", 1)) > 1
        or int(cell.get("col_span", 1)) > 1
        for cell in table["cells"]
    )
    return TablePreviewMetadata(
        owner_label=table_owner_label(owner),
        table_id=str(table.get("id") or "table"),
        dimensions=f"{row_count}행 × {column_count}열",
        merged_cells=merged_cells,
        width_label=WIDTH_LABELS.get(layout.width_mode, "자동"),
        docx_label=(
            f"DOCX {'1단' if layout.wide else '2단'} · "
            f"{int(layout.total_width_mm)}mm"
        ),
        layout_fallback=bool(layout.fallback_used),
    )


def cell_qt_alignment(cell: dict) -> Qt.Alignment:
    """Map stored alignment names to a Qt item alignment."""
    horizontal = {
        "left": Qt.AlignLeft,
        "center": Qt.AlignHCenter,
        "right": Qt.AlignRight,
    }.get(str(cell.get("horizontal_alignment") or "left"), Qt.AlignLeft)
    vertical = {
        "top": Qt.AlignTop,
        "center": Qt.AlignVCenter,
        "bottom": Qt.AlignBottom,
    }.get(str(cell.get("vertical_alignment") or "center"), Qt.AlignVCenter)
    return horizontal | vertical


class ReadOnlyTablePreview(QTableWidget):
    """A bounded, non-selectable visual rendering of one table."""

    activated = pyqtSignal()

    def __init__(self, table_spec: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._table_spec = {}
        self._column_ratios = []
        self.setObjectName("ReadOnlyTablePreview")
        self.setAccessibleName("읽기 전용 표 미리보기")
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWordWrap(True)
        self.setShowGrid(True)
        self.setMinimumHeight(84)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.verticalHeader().hide()
        self.horizontalHeader().hide()
        self.set_table_spec(table_spec)

    @property
    def table_spec(self) -> dict:
        return normalize_rectangular_table(self._table_spec)

    def set_table_spec(self, table_spec: dict) -> None:
        """Normalize and render all rows, cells, spans, and alignments."""
        table = normalize_rectangular_table(table_spec)
        layout = resolve_table_layout(table)
        self._table_spec = table
        self._column_ratios = list(layout.column_widths)

        self.clearSpans()
        self.clearContents()
        self.setRowCount(len(table["rows"]))
        self.setColumnCount(len(table["rows"][0]))
        for cell in table["cells"]:
            row = int(cell["row"])
            column = int(cell["col"])
            text = str(cell.get("text") or "")
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            item.setTextAlignment(int(cell_qt_alignment(cell)))
            self.setItem(row, column, item)
            row_span = int(cell.get("row_span", 1))
            column_span = int(cell.get("col_span", 1))
            if row_span > 1 or column_span > 1:
                self.setSpan(row, column, row_span, column_span)

        self.resizeRowsToContents()
        for row in range(self.rowCount()):
            self.setRowHeight(row, min(64, max(28, self.rowHeight(row))))
        self._apply_column_widths()

    def _apply_column_widths(self) -> None:
        if not self._column_ratios:
            return
        available = max(240, self.viewport().width())
        for column, ratio in enumerate(self._column_ratios):
            self.setColumnWidth(column, max(48, round(available * ratio)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_column_widths()

    def mouseDoubleClickEvent(self, event):
        self.activated.emit()
        event.accept()


class TablePreviewCard(QFrame):
    """Read-only table preview with edit, source, mode, and delete actions."""

    editRequested = pyqtSignal(str, str)
    sourceRequested = pyqtSignal(str, str)
    deleteRequested = pyqtSignal(str, str)
    renderModeChanged = pyqtSignal(str, str, str)

    def __init__(
        self,
        owner: str,
        table_spec: dict,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.owner = str(owner)
        self.table_spec = normalize_rectangular_table(table_spec)
        self.table_id = str(self.table_spec.get("id") or "table")
        self.setObjectName("TablePreviewCard")
        self.setFrameShape(QFrame.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(7)

        metadata = build_preview_metadata(self.owner, self.table_spec)
        parts = [
            metadata.owner_label,
            metadata.table_id,
            metadata.dimensions,
            f"병합 {metadata.merged_cells}",
            f"폭 {metadata.width_label}",
            metadata.docx_label,
        ]
        if metadata.layout_fallback:
            parts.append("배치 계산 fallback")
        self.metadata_label = BodyLabel(" · ".join(parts), self)
        self.metadata_label.setWordWrap(True)
        root.addWidget(self.metadata_label)

        try:
            self.preview = ReadOnlyTablePreview(self.table_spec, self)
        except Exception:
            self.preview = QLabel(self._flat_summary(), self)
            self.preview.setWordWrap(True)
            self.preview.setAccessibleName("표 미리보기 fallback")
        root.addWidget(self.preview)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.edit_button = PrimaryPushButton("표 편집", self)
        self.source_button = PushButton("원본 비교", self)
        self.mode_combo = ComboBox(self)
        self.delete_button = PushButton("표 삭제", self)
        for button in (
            self.edit_button,
            self.source_button,
            self.delete_button,
        ):
            button.setMinimumHeight(32)

        for label, value in (
            ("자동", "auto"),
            ("원본 이미지", "image"),
            ("편집 가능한 표", "native"),
        ):
            self.mode_combo.addItem(label, userData=value)
        current_mode = str(self.table_spec.get("render_mode") or "auto")
        current_index = self.mode_combo.findData(current_mode)
        self.mode_combo.setCurrentIndex(max(0, current_index))

        source_path = str(
            (self.table_spec.get("source") or {}).get("image_path") or ""
        )
        source_available = bool(source_path and Path(source_path).is_file())
        self.source_button.setEnabled(source_available)
        if not source_available:
            self.source_button.setToolTip("저장된 원본 표 이미지가 없습니다.")

        self.edit_button.clicked.connect(self._emit_edit)
        if isinstance(self.preview, ReadOnlyTablePreview):
            self.preview.activated.connect(self._emit_edit)
        self.source_button.clicked.connect(
            lambda: self.sourceRequested.emit(self.owner, self.table_id)
        )
        self.delete_button.clicked.connect(
            lambda: self.deleteRequested.emit(self.owner, self.table_id)
        )
        self.mode_combo.currentIndexChanged.connect(self._emit_render_mode)

        actions.addWidget(self.edit_button)
        actions.addWidget(self.source_button)
        actions.addStretch(1)
        actions.addWidget(self.mode_combo)
        actions.addWidget(self.delete_button)
        root.addLayout(actions)

    def _emit_edit(self) -> None:
        self.editRequested.emit(self.owner, self.table_id)

    def _emit_render_mode(self, _index: int) -> None:
        self.renderModeChanged.emit(
            self.owner,
            self.table_id,
            str(self.mode_combo.currentData()),
        )

    def _flat_summary(self) -> str:
        text = " / ".join(
            " | ".join(str(value or "") for value in row)
            for row in self.table_spec.get("rows") or []
        )
        return text or "표 내용을 표시할 수 없습니다."
