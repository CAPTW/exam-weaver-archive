"""Snapshot-based, undoable editing for one schema-v2 table."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QUndoCommand, QUndoStack

from ..parser.table_structure import (
    normalize_rectangular_table,
    set_auto_width_mode,
    set_manual_column_widths,
)


Coordinate = tuple[int, int]


class SnapshotTableCommand(QUndoCommand):
    """Replace the complete working table with before/after snapshots."""

    def __init__(
        self,
        session: "TableEditSession",
        label: str,
        before: dict,
        after: dict,
    ):
        super().__init__(label)
        self._session = session
        self._before = copy.deepcopy(before)
        self._after = copy.deepcopy(after)

    def undo(self) -> None:
        self._session._set_snapshot(self._before)

    def redo(self) -> None:
        self._session._set_snapshot(self._after)


class TableEditSession(QObject):
    """Own an isolated table copy and all data-changing undo commands."""

    changed = pyqtSignal(dict)

    def __init__(self, table_spec: dict):
        super().__init__()
        self._original = normalize_rectangular_table(copy.deepcopy(table_spec))
        self._working = copy.deepcopy(self._original)
        self.undo_stack = QUndoStack(self)

    def _set_snapshot(self, table_spec: dict) -> None:
        self._working = normalize_rectangular_table(copy.deepcopy(table_spec))
        self.changed.emit(self.result())

    def apply(
        self,
        label: str,
        operation: Callable[[dict], dict],
    ) -> bool:
        """Run one mutation against a copy and push it when it changed data."""
        before = self.result()
        after = normalize_rectangular_table(operation(copy.deepcopy(before)))
        if after == before:
            return False
        self.undo_stack.push(
            SnapshotTableCommand(self, str(label), before, after)
        )
        return True

    def replace_cell_text(
        self,
        row: int,
        column: int,
        text: str,
    ) -> bool:
        """Replace one logical cell's text as a single undo command."""
        row = int(row)
        column = int(column)
        value = str(text or "")

        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                if int(cell["row"]) == row and int(cell["col"]) == column:
                    cell["text"] = value
                    table["rows"][row][column] = value
                    break
            return table

        return self.apply("셀 내용 편집", operation)

    def clear_cells(self, coordinates: Iterable[Coordinate]) -> bool:
        """Clear selected logical cells without changing table dimensions."""
        targets = {
            (int(row), int(column))
            for row, column in coordinates
        }

        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                coordinate = (int(cell["row"]), int(cell["col"]))
                if coordinate not in targets:
                    continue
                cell["text"] = ""
                table["rows"][coordinate[0]][coordinate[1]] = ""
            return table

        return self.apply("셀 내용 삭제", operation)

    def align_cells(
        self,
        coordinates: Iterable[Coordinate],
        *,
        horizontal: str | None = None,
        vertical: str | None = None,
    ) -> bool:
        """Apply horizontal and/or vertical alignment to logical cells."""
        targets = {
            (int(row), int(column))
            for row, column in coordinates
        }
        if horizontal not in {None, "left", "center", "right"}:
            raise ValueError(f"unsupported horizontal alignment: {horizontal}")
        if vertical not in {None, "top", "center", "bottom"}:
            raise ValueError(f"unsupported vertical alignment: {vertical}")

        def operation(table: dict) -> dict:
            for cell in table["cells"]:
                coordinate = (int(cell["row"]), int(cell["col"]))
                if coordinate not in targets:
                    continue
                if horizontal is not None:
                    cell["horizontal_alignment"] = horizontal
                if vertical is not None:
                    cell["vertical_alignment"] = vertical
            return table

        if horizontal is not None and vertical is not None:
            label = "셀 정렬"
        elif horizontal is not None:
            label = "가로 정렬"
        else:
            label = "세로 정렬"
        return self.apply(label, operation)

    def set_manual_widths(self, pixel_widths: Iterable[int | float]) -> bool:
        """Persist a header drag as normalized manual column ratios."""
        widths = list(pixel_widths)
        return self.apply(
            "열 너비 조정",
            lambda table: set_manual_column_widths(table, widths),
        )

    def set_auto_widths(self) -> bool:
        """Switch width layout back to content-aware automatic mode."""
        return self.apply("폭 자동 맞춤", set_auto_width_mode)

    def result(self) -> dict:
        """Return a copy safe for the caller to persist or inspect."""
        return copy.deepcopy(self._working)

    def is_dirty(self) -> bool:
        return self._working != self._original
