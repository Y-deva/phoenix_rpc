"""Transaction history page with filtering, sorting and export."""

from __future__ import annotations

import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, QStandardPaths, Qt
from PyQt6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.errors import humanize_error
from ...core.formatting import (
    category_label,
    format_nvc,
    format_timestamp,
    shorten_address,
)
from ...core.tasks import run_async
from ...rpc.models import Transaction
from ..dialogs.tx_details import TxDetailsDialog
from ..widgets.card import Card, Pill
from ..widgets.fields import IconButton, SearchField
from ..widgets.icons import icon
from ..widgets.progress import Spinner
from ..widgets.table import (
    Column,
    SortItem,
    SortableTable,
    amount_item,
    status_item,
    text_item,
)
from .base import BasePage

PAGE_SIZE = 300

KIND_FILTERS = (
    ("", "Все операции"),
    ("incoming", "Входящие"),
    ("outgoing", "Исходящие"),
    ("mining", "Награды"),
    ("immature", "Незрелые"),
    ("pending", "Без подтверждений"),
)

PERIOD_FILTERS = (
    (0, "Все время"),
    (1, "За сутки"),
    (7, "За неделю"),
    (30, "За месяц"),
    (90, "За квартал"),
    (365, "За год"),
)


class TransactionsPage(BasePage):
    """Browse and inspect the complete wallet history."""

    page_id = "transactions"
    page_title = "История"
    page_subtitle = "Все операции кошелька: поступления, отправки и награды"
    auto_refresh = False

    def __init__(self, context: Any, parent: QWidget | None = None) -> None:
        """Initialize the TransactionsPage instance."""
        super().__init__(context, parent)
        self._transactions: list[Transaction] = []
        self._has_more = False
        self._page_offset = 0
        self._build()
        self._apply_theme()

    def _build(self) -> None:
        """Create the toolbar, summary and table."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        toolbar = Card(padding=12)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.search = SearchField()
        self.search.setPlaceholderText("Поиск по адресу или TxID")
        self.search.setFixedWidth(300)
        self.search.searchChanged.connect(self._on_filters_changed)
        self.kind_combo = QComboBox()
        self.kind_combo.setMinimumWidth(150)
        for value, label in KIND_FILTERS:
            self.kind_combo.addItem(label, value)
        self.kind_combo.setToolTip("Фильтр по типу операции")
        self.kind_combo.currentIndexChanged.connect(self._on_filters_changed)
        self.period_combo = QComboBox()
        self.period_combo.setMinimumWidth(130)
        for value, label in PERIOD_FILTERS:
            self.period_combo.addItem(label, value)
        self.period_combo.setToolTip("Фильтр по времени операции")
        self.period_combo.currentIndexChanged.connect(self._on_filters_changed)
        self.spinner = Spinner(size=18)
        self.refresh_button = IconButton(
            "refresh", self.tokens.get("muted", "#A7B1C2"), "Обновить историю (F5)", 34
        )
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("CSV")
        self.export_button.setObjectName("GhostButton")
        self.export_button.setToolTip("Экспортировать видимые операции в CSV (Ctrl+E)")
        self.export_button.clicked.connect(self._export_csv)
        row.addWidget(self.search)
        row.addWidget(self.kind_combo)
        row.addWidget(self.period_combo)
        row.addStretch(1)
        row.addWidget(self.spinner)
        row.addWidget(self.refresh_button)
        row.addWidget(self.export_button)
        toolbar.add_layout(row)
        root.addWidget(toolbar)

        summary = Card(padding=10)
        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.received_pill = Pill("Получено: 0", "success")
        self.sent_pill = Pill("Отправлено: 0", "accent")
        self.count_pill = Pill("Операций: 0", "neutral")
        summary_row.addWidget(self.received_pill)
        summary_row.addWidget(self.sent_pill)
        summary_row.addWidget(self.count_pill)
        summary_row.addStretch(1)
        self.load_more_button = QPushButton("Загрузить еще")
        self.load_more_button.setObjectName("GhostButton")
        self.load_more_button.setIcon(
            icon("chevron-down", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.load_more_button.setToolTip("Загрузить следующую страницу истории")
        self.load_more_button.clicked.connect(self._load_more)
        self.load_more_button.setVisible(False)
        summary_row.addWidget(self.load_more_button)
        summary.add_layout(summary_row)
        root.addWidget(summary)

        self.table = SortableTable(
            [
                Column("Дата", 135),
                Column("Тип", 165),
                Column("Сумма", 130),
                Column("Подтв.", 80),
                Column("Статус", 140),
                Column("Адрес", 210, stretch=True),
                Column("Комментарий", 165),
            ],
            row_height=42,
        )
        self.table.set_empty_message(
            "Операций пока нет",
            "История появится после первого поступления или отправки.",
            "transactions",
        )
        self.table.doubleClicked.connect(self._open_details)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        root.addWidget(self.table, 1)

        self.footer = QLabel("")
        self.footer.setObjectName("Muted")
        root.addWidget(self.footer)
        self.protect(
            self.received_pill,
            self.sent_pill,
            self.count_pill,
            self.table.viewport(),
        )

        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._export_csv)

    def refresh(self) -> None:
        """Reload the first page of history."""
        if self._refreshing:
            return
        self._begin_load(0)

    def _begin_load(self, offset: int) -> None:
        """Start an asynchronous history request."""
        self._refreshing = True
        self._page_offset = offset
        self.busyChanged.emit(True)
        self.spinner.start()
        self.refresh_button.setEnabled(False)
        self.load_more_button.setEnabled(False)
        run_async(
            self._fetch,
            self._on_loaded,
            self._on_failed,
            self._on_finished,
            offset,
        )

    def _fetch(self, offset: int) -> list[Transaction]:
        """Fetch one history page from the proxy."""
        return self.service.list_transactions(count=PAGE_SIZE, offset=offset)

    def _on_loaded(self, transactions: object) -> None:
        """Replace or append the received history entries."""
        batch = list(transactions or [])
        if self._page_offset == 0:
            self._transactions = batch
        else:
            self._transactions.extend(batch)
        self._has_more = len(batch) >= PAGE_SIZE
        self.load_more_button.setVisible(self._has_more)
        self._render_summary()
        self._rebuild_table()

    def _on_failed(self, error: object) -> None:
        """Report a failed history request."""
        self.errorRaised.emit(humanize_error(error))
        self._refresh_summary_footer()

    def _on_finished(self) -> None:
        """Clear the loading state."""
        self._refreshing = False
        self.busyChanged.emit(False)
        self.spinner.stop()
        self.refresh_button.setEnabled(True)
        self.load_more_button.setEnabled(True)

    def _load_more(self) -> None:
        """Append the next history page."""
        if self._refreshing or not self._has_more:
            return
        self._begin_load(len(self._transactions))

    def _rebuild_table(self) -> None:
        """Rebuild the table from the loaded transaction list."""
        mono = self.themes.mono_font
        header = self.table.horizontalHeader()
        sort_column = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        scroll_position = self.table.verticalScrollBar().value()
        self.table.begin_update()
        self.table.setRowCount(0)
        for transaction in self._transactions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            date_item = SortItem(
                format_timestamp(transaction.timestamp, "%d.%m.%Y %H:%M"),
                transaction.timestamp,
            )
            date_item.setToolTip(
                format_timestamp(transaction.timestamp, "%d.%m.%Y %H:%M:%S")
            )
            self.table.setItem(row, 0, date_item)

            kind_color = {
                "receive": self.tokens.get("positive", "#3DD6A0"),
                "send": self.tokens.get("accent", "#FF8A3D"),
                "mine": self.tokens.get("warning", "#F3C969"),
                "immature": self.tokens.get("warning", "#F3C969"),
            }.get(transaction.kind, self.tokens.get("muted", "#A7B1C2"))
            category_text = self.tr_text(category_label(transaction.category))
            type_item = text_item(
                category_text,
                sort_key=transaction.category,
                color=kind_color,
                tooltip=category_text,
            )
            type_item.setData(Qt.ItemDataRole.UserRole, transaction)
            self.table.setItem(row, 1, type_item)

            self.table.setItem(
                row,
                2,
                amount_item(
                    transaction.amount,
                    incoming=transaction.amount >= 0,
                    mono_font=mono,
                    signed=True,
                ),
            )
            confirm_item = SortItem(
                str(transaction.confirmations), transaction.confirmations
            )
            confirm_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            confirm_item.setForeground(self._brush(self.tokens.get("muted", "#A7B1C2")))
            self.table.setItem(row, 3, confirm_item)

            status_color = {
                "confirmed": self.tokens.get("positive", "#3DD6A0"),
                "pending": self.tokens.get("warning", "#F3C969"),
                "immature": self.tokens.get("warning", "#F3C969"),
                "conflicted": self.tokens.get("negative", "#FF7070"),
            }.get(transaction.status, self.tokens.get("muted", "#A7B1C2"))
            status_rank = {"confirmed": 0, "pending": 1, "immature": 2, "conflicted": 3}
            self.table.setItem(
                row,
                4,
                status_item(
                    self.tr_text(transaction.status_label),
                    status_color,
                    sort_key=status_rank.get(transaction.status, 9),
                ),
            )

            address_item = text_item(
                shorten_address(transaction.address, 10, 6)
                if transaction.address
                else "-",
                sort_key=transaction.address,
                mono=True,
                tooltip=transaction.address,
            )
            self.table.setItem(row, 5, address_item)

            comment = transaction.comment.replace("\n", " ").strip()
            comment_item = text_item(
                comment[:48] + ("..." if len(comment) > 48 else "") if comment else "-",
                sort_key=comment,
                color=self.tokens.get("muted", "#A7B1C2"),
                tooltip=comment,
            )
            self.table.setItem(row, 6, comment_item)
        if sort_column < 0:
            sort_column = 0
            ascending = False
        else:
            ascending = sort_order == Qt.SortOrder.AscendingOrder
        self.table.end_update(sort_column=sort_column, ascending=ascending)
        self._filter_rows()
        self._update_footer()
        self.table.verticalScrollBar().setValue(scroll_position)

    def _brush(self, color: str) -> Any:
        """Create a brush from a theme color."""
        return QBrush(QColor(color))

    def _on_filters_changed(self, *_args: object) -> None:
        """Apply all active filters."""
        self._filter_rows()

    def _filter_rows(self) -> None:
        """Hide rows that do not satisfy the filters."""
        kind = self.kind_combo.currentData()
        days = int(self.period_combo.currentData() or 0)
        cutoff = time.time() - days * 86400 if days else 0
        query = self.search.text().strip().casefold()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            transaction = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not isinstance(transaction, Transaction):
                self.table.setRowHidden(row, True)
                continue
            visible = True
            if kind == "incoming" and transaction.amount <= 0:
                visible = False
            elif kind == "outgoing" and transaction.amount >= 0:
                visible = False
            elif kind == "mining" and transaction.kind != "mine":
                visible = False
            elif kind == "immature" and transaction.category != "immature":
                visible = False
            elif kind == "pending" and transaction.confirmations != 0:
                visible = False
            if (
                visible
                and cutoff
                and transaction.timestamp
                and transaction.timestamp < cutoff
            ):
                visible = False
            if visible and query:
                haystack = " ".join(
                    (
                        transaction.txid,
                        transaction.address,
                        transaction.comment,
                        transaction.account,
                        category_label(transaction.category),
                        self.tr_text(category_label(transaction.category)),
                    )
                ).casefold()
                visible = query in haystack
            self.table.setRowHidden(row, not visible)
        self.table.refresh_empty()
        self._update_footer()

    def _render_summary(self) -> None:
        """Update the totals shown above the table."""
        received = sum(
            (tx.amount for tx in self._transactions if tx.amount > 0), Decimal("0")
        )
        sent = -sum(
            (tx.amount for tx in self._transactions if tx.amount < 0), Decimal("0")
        )
        self.received_pill.set_text(self.tr_text(f"Получено: {format_nvc(received)}"))
        self.sent_pill.set_text(self.tr_text(f"Отправлено: {format_nvc(sent)}"))
        self.count_pill.set_text(self.tr_text(f"Операций: {len(self._transactions)}"))
        self.count_pill.setVisible(self.settings.verbosity >= 1)

    def _update_footer(self) -> None:
        """Show how many rows are visible and loaded."""
        visible = sum(
            1 for row in range(self.table.rowCount()) if not self.table.isRowHidden(row)
        )
        text = self.tr_text(f"Показано {visible} из {self.table.rowCount()} операций.")
        if self._has_more:
            text += " " + self.tr_text("В памяти есть еще страницы.")
        self.footer.setText(text)

    def _refresh_summary_footer(self) -> None:
        """Refresh summary widgets after an error."""
        self._render_summary()
        self._update_footer()

    def _open_details(self, index: object) -> None:
        """Open the details dialog for the activated row."""
        try:
            row = int(index.row())
        except (AttributeError, TypeError, ValueError):
            return
        item = self.table.item(row, 1)
        transaction = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(transaction, Transaction):
            return
        dialog = TxDetailsDialog(
            transaction, dict(self.tokens), self.settings.verbosity, self
        )
        dialog.exec()

    def _context_menu(self, position: object) -> None:
        """Offer copy and detail actions for the clicked row."""
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        item = self.table.item(index.row(), 1)
        transaction = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(transaction, Transaction):
            return
        menu = QMenu(self)
        details_action = menu.addAction("Детали операции")
        copy_tx_action = menu.addAction("Копировать TxID")
        copy_address_action = menu.addAction("Копировать адрес")
        copy_address_action.setEnabled(bool(transaction.address))
        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen is details_action:
            self._open_details(index)
        elif chosen is copy_tx_action:
            QApplication.clipboard().setText(transaction.txid)
            self.statusMessage.emit("TxID скопирован", 3000)
        elif chosen is copy_address_action:
            QApplication.clipboard().setText(transaction.address)
            self.statusMessage.emit("Адрес скопирован", 3000)

    def _export_csv(self) -> None:
        """Export the visible history rows to a CSV file."""
        if self.table.rowCount() == 0:
            self.statusMessage.emit("История пуста", 3000)
            return
        documents = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation
        )
        default = str(Path(documents or Path.home()) / "phoenix-history.csv")
        filename, _selected = QFileDialog.getSaveFileName(
            self, "Экспорт истории", default, "CSV (*.csv)"
        )
        if not filename:
            return
        try:
            count = self.table.export_csv(filename)
        except OSError as error:
            self.errorRaised.emit(f"Не удалось сохранить файл: {error}")
            return
        self.statusMessage.emit(f"Экспортировано операций: {count}", 4000)

    def apply_theme(self) -> None:
        """Apply theme colors to custom widgets and glyphs."""
        self.table.set_accent(self.tokens.get("accent", "#FF8A3D"))
        self.refresh_button.set_icon_name("refresh")
        self.load_more_button.setIcon(
            icon("chevron-down", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.export_button.setIcon(
            icon("download", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.export_button.setIconSize(QSize(15, 15))
        self._rebuild_table()

    def _apply_theme(self) -> None:
        """Initial theme hook used by the constructor."""
        self.export_button.setIcon(
            icon("download", self.tokens.get("muted", "#A7B1C2"), 15)
        )
        self.table.set_accent(self.tokens.get("accent", "#FF8A3D"))
