"""Coin control page for inspecting and selecting unspent outputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import humanize_error
from ...core.formatting import format_nvc, shorten_address, shorten_txid
from ...core.tasks import run_async
from ...rpc.models import Utxo
from ..widgets.card import Card, Pill
from ..widgets.fields import IconButton, SearchField
from ..widgets.icons import icon
from ..widgets.table import (
    Column,
    SortItem,
    SortableTable,
    amount_item,
    status_item,
    text_item,
)
from .base import BasePage

FILTERS = (
    ("all", "Все выходы"),
    ("spendable", "Доступные"),
    ("unconfirmed", "Без подтверждений"),
    ("locked", "Недоступные"),
)


class CoinsPage(BasePage):
    """Show every unspent output and allow expert coin selection."""

    page_id = "coins"
    page_title = "Монеты"
    page_subtitle = "Управление входами: выбор конкретных UTXO для отправки"
    auto_refresh = True

    sendRequested = pyqtSignal(object)

    def __init__(self, context: Any, parent: QWidget | None = None) -> None:
        """Initialize the CoinsPage instance."""
        super().__init__(context, parent)
        self._utxos: list[Utxo] = []
        self._updating = False
        self._build()
        self.apply_theme()

    def _build(self) -> None:
        """Create the filter bar, table and actions."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        toolbar = Card(padding=12)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = SearchField()
        self.search.setPlaceholderText("Поиск по адресу или TxID")
        self.search.setFixedWidth(300)
        self.search.searchChanged.connect(lambda _text: self._filter_rows())
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(160)
        for value, label in FILTERS:
            self.filter_combo.addItem(label, value)
        self.filter_combo.currentIndexChanged.connect(
            lambda _index: self._filter_rows()
        )
        self.filter_combo.setToolTip("Показать только определенный тип выходов")
        self.refresh_button = IconButton(
            "refresh",
            self.tokens.get("muted", "#A7B1C2"),
            "Обновить список UTXO (F5)",
            34,
        )
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.search)
        row.addWidget(self.filter_combo)
        row.addStretch(1)
        row.addWidget(self.refresh_button)
        toolbar.add_layout(row)
        root.addWidget(toolbar)

        summary = Card(padding=10)
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.available_pill = Pill("Доступно: 0", "success")
        self.selected_pill = Pill("Выбрано: 0", "accent")
        self.count_pill = Pill("Выходов: 0", "neutral")
        self.select_all_button = QPushButton("Выбрать все")
        self.select_all_button.setObjectName("GhostButton")
        self.select_all_button.setIcon(
            icon("check", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.select_all_button.setToolTip("Отметить все видимые выходы (Ctrl+Shift+A)")
        self.select_all_button.clicked.connect(self._select_all)
        self.clear_button = QPushButton("Снять")
        self.clear_button.setObjectName("GhostButton")
        self.clear_button.setToolTip("Снять выделение со всех выходов")
        self.clear_button.clicked.connect(self._clear_selection)
        self.send_button = QPushButton("Отправить выбранные")
        self.send_button.setObjectName("AccentButton")
        self.send_button.setIcon(
            icon("send", self.tokens.get("accent_text", "#1A1208"), 15)
        )
        self.send_button.setToolTip("Перейти к отправке с выбранными входами")
        self.send_button.clicked.connect(self._request_send)
        summary_row.addWidget(self.available_pill)
        summary_row.addWidget(self.selected_pill)
        summary_row.addWidget(self.count_pill)
        summary_row.addStretch(1)
        summary_row.addWidget(self.select_all_button)
        summary_row.addWidget(self.clear_button)
        summary_row.addWidget(self.send_button)
        summary.add_layout(summary_row)
        root.addWidget(summary)

        self.table = SortableTable(
            [
                Column("Выбор", 58),
                Column("Сумма", 145),
                Column("Подтв.", 80),
                Column("Адрес", 210, stretch=True),
                Column("TxID", 190),
                Column("Статус", 135),
                Column("Блок", 85),
            ],
            row_height=42,
        )
        self.table.set_empty_message(
            "Нет неразмеченных выходов",
            "После получения монет здесь появятся записи listunspent.",
            "coins",
        )
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.table, 1)

        self.footer = QLabel("")
        self.footer.setObjectName("Muted")
        root.addWidget(self.footer)
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self._select_all)

    def refresh(self) -> None:
        """Load the current unspent output set."""
        if self._refreshing:
            return
        self._refreshing = True
        self.busyChanged.emit(True)
        self.refresh_button.setEnabled(False)
        run_async(
            self.service.list_unspent,
            self._on_loaded,
            self._on_failed,
            self._on_finished,
        )

    def _on_loaded(self, utxos: object) -> None:
        """Render the received output list."""
        self._utxos = list(utxos or [])
        self._rebuild_table()

    def _on_failed(self, error: object) -> None:
        """Report a failed listunspent call."""
        self.errorRaised.emit(humanize_error(error))

    def _on_finished(self) -> None:
        """Leave the loading state."""
        self._refreshing = False
        self.busyChanged.emit(False)
        self.refresh_button.setEnabled(True)

    def _rebuild_table(self) -> None:
        """Rebuild the UTXO table from the loaded list."""
        mono = self.themes.mono_font
        self._updating = True
        self.table.begin_update()
        self.table.setRowCount(0)
        for utxo in self._utxos:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = SortItem("", sort_key=utxo.amount)
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setData(Qt.ItemDataRole.UserRole, utxo)
            check.setToolTip(f"{utxo.txid}:{utxo.vout}")
            self.table.setItem(row, 0, check)
            self.table.setItem(
                row,
                1,
                amount_item(utxo.amount, incoming=True, mono_font=mono, signed=False),
            )
            confirm_item = SortItem(str(utxo.confirmations), utxo.confirmations)
            confirm_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            confirm_item.setForeground(self._brush(self.tokens.get("muted", "#A7B1C2")))
            self.table.setItem(row, 2, confirm_item)
            self.table.setItem(
                row,
                3,
                text_item(
                    shorten_address(utxo.address, 12, 8) if utxo.address else "-",
                    sort_key=utxo.address,
                    mono=True,
                    tooltip=utxo.address,
                ),
            )
            txid_item = text_item(
                shorten_txid(utxo.txid),
                sort_key=utxo.txid,
                mono=True,
                tooltip=utxo.txid,
            )
            self.table.setItem(row, 4, txid_item)
            if not utxo.spendable:
                status_text = "Недоступен"
                status_color = self.tokens.get("negative", "#FF7070")
            elif utxo.confirmations <= 0:
                status_text = "Без подтверждений"
                status_color = self.tokens.get("warning", "#F3C969")
            else:
                status_text = "Доступен"
                status_color = self.tokens.get("positive", "#3DD6A0")
            self.table.setItem(
                row,
                5,
                status_item(status_text, status_color, sort_key=status_text),
            )
            height = utxo.raw.get("blockheight", utxo.raw.get("height", "-"))
            height_item = SortItem(
                str(height), int(height) if isinstance(height, int) else 0
            )
            height_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            height_item.setForeground(self._brush(self.tokens.get("muted", "#A7B1C2")))
            self.table.setItem(row, 6, height_item)
        self.table.end_update(sort_column=1, ascending=False)
        self._updating = False
        self._filter_rows()
        self._update_summary()

    def _filter_rows(self) -> None:
        """Apply the text and availability filters."""
        mode = self.filter_combo.currentData()
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            utxo = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not isinstance(utxo, Utxo):
                self.table.setRowHidden(row, True)
                continue
            visible = True
            if mode == "spendable" and (not utxo.spendable or utxo.confirmations <= 0):
                visible = False
            elif mode == "unconfirmed" and utxo.confirmations > 0:
                visible = False
            elif mode == "locked" and utxo.spendable:
                visible = False
            if visible and query:
                visible = query in f"{utxo.txid} {utxo.address}".casefold()
            self.table.setRowHidden(row, not visible)
        self.table.refresh_empty()
        self._update_footer()

    def _update_summary(self) -> None:
        """Update available, selected and count pills."""
        available = sum(
            (utxo.amount for utxo in self._utxos if utxo.spendable), Decimal("0")
        )
        selected = sum((utxo.amount for utxo in self._selected_utxos()), Decimal("0"))
        self.available_pill.set_text(f"Доступно: {format_nvc(available)}")
        self.selected_pill.set_text(
            f"Выбрано: {format_nvc(selected)} ({len(self._selected_utxos())})"
        )
        self.count_pill.set_text(f"Выходов: {len(self._utxos)}")
        self.send_button.setEnabled(bool(self._selected_utxos()))
        self._update_footer()

    def _update_footer(self) -> None:
        """Show visible and total output counts."""
        visible = sum(
            1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)
        )
        self.footer.setText(
            f"Показано {visible} из {self.table.rowCount()} выходов. "
            "Флажок слева включает UTXO в ручную отправку."
        )

    def _selected_utxos(self) -> list[Utxo]:
        """Return all currently checked outputs in table order."""
        selected: list[Utxo] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None or item.checkState() != Qt.CheckState.Checked:
                continue
            utxo = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(utxo, Utxo):
                selected.append(utxo)
        return selected

    def _on_item_changed(self, item: object) -> None:
        """React to a checkbox toggle."""
        if self._updating or item is None or item.column() != 0:
            return
        self._update_summary()

    def _select_all(self) -> None:
        """Check all visible outputs."""
        self._updating = True
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
        self._updating = False
        self._update_summary()

    def _clear_selection(self) -> None:
        """Uncheck every output."""
        self._updating = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._updating = False
        self._update_summary()

    def _request_send(self) -> None:
        """Ask the shell to open the send page with the chosen coins."""
        selected = self._selected_utxos()
        if not selected:
            self.statusMessage.emit("Сначала выберите хотя бы один выход", 3000)
            return
        self.sendRequested.emit(selected)

    def _context_menu(self, position: object) -> None:
        """Copy identifiers from the clicked output."""
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        item = self.table.item(index.row(), 0)
        utxo = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(utxo, Utxo):
            return
        menu = QMenu(self)
        copy_txid = menu.addAction("Копировать TxID")
        copy_address = menu.addAction("Копировать адрес")
        copy_out = menu.addAction("Копировать TxID:выход")
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is copy_txid:
            QApplication.clipboard().setText(utxo.txid)
        elif chosen is copy_address:
            QApplication.clipboard().setText(utxo.address)
        elif chosen is copy_out:
            QApplication.clipboard().setText(utxo.key)
        else:
            return
        self.statusMessage.emit("Данные скопированы", 2500)

    def _brush(self, color: str) -> QBrush:
        """Create a brush from a theme color."""
        return QBrush(QColor(color))

    def apply_theme(self) -> None:
        """Apply theme colors and redraw the table."""
        self.table.set_accent(self.tokens.get("accent", "#FF8A3D"))
        self.refresh_button.set_icon_name("refresh")
        muted = self.tokens.get("muted", "#A7B1C2")
        self.select_all_button.setIcon(icon("check", muted, 15))
        self.send_button.setIcon(
            icon("send", self.tokens.get("accent_text", "#1A1208"), 15)
        )
        self._rebuild_table()
