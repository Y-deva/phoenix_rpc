"""Sortable, filterable table building blocks.

QTableWidget is used deliberately: the wallet tables are small (hundreds
of rows at most) and item widgets keep the page code compact.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from PyQt6.QtCore import QPoint, QPointF, QSize, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPolygonF
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ...core.formatting import format_amount, format_signed_nvc
from .card import EmptyState


@dataclass(frozen=True)
class Column:
    """Description of one table column."""

    title: str
    width: int = 120
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    stretch: bool = False


class SortItem(QTableWidgetItem):
    """Table item that sorts by an explicit key instead of display text."""

    def __init__(self, text: str = "", sort_key: Any = None) -> None:
        """Initialize the SortItem instance."""
        super().__init__(text)
        self.sort_key = text if sort_key is None else sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        """Compare using the explicit key, falling back to text."""
        if isinstance(other, SortItem):
            try:
                return self.sort_key < other.sort_key
            except TypeError:
                return str(self.sort_key) < str(other.sort_key)
        return super().__lt__(other)


class SortHeaderView(QHeaderView):
    """Header that paints a small ASCII-sized sort chevron."""

    def __init__(
        self, orientation: Qt.Orientation, parent: QWidget | None = None
    ) -> None:
        """Initialize the SortHeaderView instance."""
        super().__init__(orientation, parent)
        self._arrow_color = QColor("#FF8A3D")
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.setSortIndicatorShown(True)

    def set_arrow_color(self, color: str | QColor) -> None:
        """Update the sort chevron color."""
        self._arrow_color = QColor(color)
        self.viewport().update()

    def paintSection(self, painter: QPainter, rect, logical_index: int) -> None:  # noqa: N802 - Qt API
        """Draw the standard section, then a compact direction chevron."""
        super().paintSection(painter, rect, logical_index)
        if self.sortIndicatorSection() != logical_index:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._arrow_color)
        center_x = rect.right() - 12.0
        center_y = rect.center().y() + 0.5
        if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
            points = [
                (center_x - 4.0, center_y + 2.0),
                (center_x + 4.0, center_y + 2.0),
                (center_x, center_y - 3.0),
            ]
        else:
            points = [
                (center_x - 4.0, center_y - 2.0),
                (center_x + 4.0, center_y - 2.0),
                (center_x, center_y + 3.0),
            ]
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
        painter.restore()


class SortableTable(QTableWidget):
    """A read-only table with sorting, filtering and an empty overlay."""

    def __init__(
        self,
        columns: Sequence[Column],
        parent: QWidget | None = None,
        row_height: int = 42,
    ) -> None:
        """Initialize the SortableTable instance."""
        super().__init__(0, len(columns), parent)
        self.setObjectName("DataTable")
        self._columns = list(columns)
        self._row_height = row_height
        self._empty = EmptyState(
            "Пока нет данных",
            "Здесь появятся записи, как только кошелек загрузит историю.",
            "info",
            parent=self.viewport(),
        )
        self._empty.hide()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(columns)
        self._configure()

    def _build(self, columns: Sequence[Column]) -> None:
        """Create headers and sizing rules."""
        header = SortHeaderView(Qt.Orientation.Horizontal, self)
        self.setHorizontalHeader(header)
        self.setHorizontalHeaderLabels([column.title for column in columns])
        header.setMinimumSectionSize(60)
        for index, column in enumerate(columns):
            if column.stretch:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Interactive)
                self.setColumnWidth(index, column.width)
            item = self.horizontalHeaderItem(index)
            if item is not None:
                item.setTextAlignment(column.align)
        header.setStretchLastSection(True)

    def _configure(self) -> None:
        """Apply wallet-wide table defaults."""
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(self._row_height)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSortingEnabled(True)
        self.setMinimumHeight(200)
        self.horizontalHeader().setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        self.horizontalHeader().sectionClicked.connect(self._on_section_clicked)

    def set_accent(self, color: str) -> None:
        """Tint the sort chevron for the active theme."""
        header = self.horizontalHeader()
        if isinstance(header, SortHeaderView):
            header.set_arrow_color(color)

    def set_empty_message(
        self, title: str, description: str = "", icon_name: str = "info"
    ) -> None:
        """Replace the placeholder shown for an empty table."""
        self._empty.deleteLater()
        self._empty = EmptyState(title, description, icon_name, parent=self.viewport())
        self._empty.hide()
        self._refresh_empty()

    def begin_update(self) -> None:
        """Temporarily disable sorting while rows are inserted."""
        self.setSortingEnabled(False)
        self.setUpdatesEnabled(False)

    def end_update(
        self, sort_column: int | None = None, ascending: bool = False
    ) -> None:
        """Re-enable sorting and refresh the empty overlay."""
        self.setUpdatesEnabled(True)
        self.setSortingEnabled(True)
        if sort_column is not None:
            self.sortItems(
                sort_column,
                Qt.SortOrder.AscendingOrder
                if ascending
                else Qt.SortOrder.DescendingOrder,
            )
        self._refresh_empty()

    def add_row(self, items: Sequence[QTableWidgetItem]) -> int:
        """Append one row and return its index."""
        row = self.rowCount()
        self.insertRow(row)
        for column, item in enumerate(items):
            self.setItem(row, column, item)
        self._refresh_empty()
        return row

    def set_rows(self, rows: Iterable[Sequence[QTableWidgetItem]]) -> None:
        """Replace all rows efficiently."""
        self.begin_update()
        self.setRowCount(0)
        for row_items in rows:
            row = self.rowCount()
            self.insertRow(row)
            for column, item in enumerate(row_items):
                if column < self.columnCount():
                    self.setItem(row, column, item)
        self.end_update()
        self._refresh_empty()

    def refresh_empty(self) -> None:
        """Re-evaluate the empty overlay after external row filtering."""
        self._refresh_empty()

    def filter_rows(self, text: str) -> int:
        """Hide rows that do not contain the query; return visible count."""
        query = (text or "").strip().casefold()
        visible = 0
        for row in range(self.rowCount()):
            matched = not query
            if query:
                for column in range(self.columnCount()):
                    item = self.item(row, column)
                    if item is not None and query in item.text().casefold():
                        matched = True
                        break
                    tooltip = item.toolTip() if item is not None else ""
                    if query in tooltip.casefold():
                        matched = True
                        break
            self.setRowHidden(row, not matched)
            visible += int(matched)
        self._refresh_empty()
        return visible

    def visible_rows(self) -> list[int]:
        """Return indices of rows that are currently visible."""
        return [row for row in range(self.rowCount()) if not self.isRowHidden(row)]

    def row_at(self, position: QPoint) -> int:
        """Return the row under a viewport position, or -1."""
        index = self.indexAt(position)
        return index.row() if index.isValid() else -1

    def export_csv(self, path: str | Path) -> int:
        """Write the visible table to a UTF-8 CSV file."""
        target = Path(path)
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow([column.title for column in self._columns])
            count = 0
            for row in self.visible_rows():
                values = []
                for column in range(self.columnCount()):
                    item = self.item(row, column)
                    values.append(item.text() if item is not None else "")
                writer.writerow(values)
                count += 1
        return count

    def _on_section_clicked(self, _section: int) -> None:
        """Keep the custom header repainting after a sort."""
        self.horizontalHeader().viewport().update()

    def _refresh_empty(self) -> None:
        """Show the placeholder when no visible rows remain."""
        visible = any(not self.isRowHidden(row) for row in range(self.rowCount()))
        self._empty.setVisible(not visible)
        if not visible:
            self._empty.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Keep the empty overlay aligned with the viewport."""
        super().resizeEvent(event)
        self._empty.setGeometry(self.viewport().rect())


def text_item(
    text: str,
    sort_key: Any = None,
    mono: bool = False,
    color: str = "",
    align: Qt.AlignmentFlag | None = None,
    tooltip: str = "",
    font_family: str = "",
) -> SortItem:
    """Build a standard read-only cell item."""
    item = SortItem(text, sort_key)
    if mono and font_family:
        font = QFont(font_family)
        item.setFont(font)
    if color:
        item.setForeground(QBrush(QColor(color)))
    if align is not None:
        item.setTextAlignment(align)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def amount_item(
    amount: Decimal,
    incoming: bool = True,
    mono_font: str = "",
    signed: bool = True,
    places: int = 8,
) -> SortItem:
    """Build a right aligned, color coded amount cell."""
    if signed:
        text = format_signed_nvc(
            abs(amount) if incoming else -abs(amount), places=places
        )
    else:
        text = format_amount(amount, places=places)
    item = SortItem(text, amount)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if mono_font:
        item.setFont(QFont(mono_font))
    color = "#3DD6A0" if incoming else "#FF7070"
    item.setForeground(QBrush(QColor(color)))
    return item


def status_item(text: str, color: str, sort_key: Any = None) -> SortItem:
    """Build a colored status cell sorted by its raw key."""
    item = SortItem(text, sort_key if sort_key is not None else text)
    item.setForeground(QBrush(QColor(color)))
    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return item


def icon_size(size: int = 16) -> QSize:
    """Return a square icon size."""
    return QSize(size, size)
