"""Receive page with a scannable QR code and the address book."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ...core.formatting import format_nvc, format_timestamp, shorten_address
from ...core.tasks import run_async
from ...rpc.models import AddressInfo
from ..widgets.card import Card, KeyValueRow, Pill
from ..widgets.fields import SearchField
from ..widgets.icons import icon
from ..widgets.qr import QrCode
from ..widgets.table import Column, SortableTable, SortItem, text_item
from .base import ScrollPage


class ReceivePage(ScrollPage):
    """Show one address at a time and keep the rest of the wallet nearby."""

    page_id = "receive"
    page_title = "Получение"
    page_subtitle = "Адрес, QR-код и список известных адресов кошелька"

    def __init__(self, context, parent: QWidget | None = None) -> None:
        """Initialize the ReceivePage instance."""
        super().__init__(context, parent)
        self._addresses: list[AddressInfo] = []
        self._current_address = ""
        self._generating = False
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        """Create the QR panel, the address details and the address table."""
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(16)
        top.addWidget(self._build_qr_card(), 0)
        top.addWidget(self._build_details_card(), 1)
        self.body.addLayout(top)
        self.body.addWidget(self._build_addresses_card(), 1)
        self.body.addStretch(1)

    def _build_qr_card(self) -> Card:
        """Build the QR panel with a save action."""
        card = Card(object_name="SoftCard", padding=18, spacing=10)
        card.setFixedWidth(320)
        title = QLabel("QR-код адреса")
        title.setObjectName("CardTitle")
        card.add(title)
        self.qr = QrCode()
        self.qr.setMinimumSize(250, 250)
        self.qr.setToolTip("Отсканируйте код кошельком или телефоном")
        card.add(self.qr)
        self.qr_hint = QLabel(
            "Код содержит только адрес и не содержит приватных данных."
        )
        self.qr_hint.setObjectName("HintText")
        self.qr_hint.setWordWrap(True)
        card.add(self.qr_hint)
        save_button = QPushButton("Сохранить PNG")
        save_button.setObjectName("GhostButton")
        save_button.setIcon(icon("download", self.tokens.get("muted", "#A7B1C2"), 16))
        save_button.setToolTip("Сохранить QR-код как изображение для печати")
        save_button.clicked.connect(self._save_qr)
        card.add(save_button)
        return card

    def _build_details_card(self) -> Card:
        """Build the current address and generation controls."""
        card = Card(padding=18, spacing=10)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        title = QLabel("Ваш адрес")
        title.setObjectName("CardTitle")
        self.status_pill = Pill("Не выбран", "warning")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.status_pill)
        card.add_layout(header)
        self.address_label = QLabel("Нажмите кнопку ниже, чтобы создать адрес")
        self.address_label.setObjectName("MonoStrong")
        self.address_label.setWordWrap(True)
        self.address_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.address_label.setMinimumHeight(54)
        self.address_label.setToolTip("Адрес можно выделить и скопировать")
        card.add(self.address_label)
        self.copy_button = QPushButton("Копировать адрес")
        self.copy_button.setObjectName("AccentButton")
        self.copy_button.setIcon(
            icon("copy", self.tokens.get("accent_text", "#1B0D04"), 16)
        )
        self.copy_button.setToolTip("Скопировать адрес в буфер обмена")
        self.copy_button.clicked.connect(self._copy_current)
        card.add(self.copy_button)

        card.add(QLabel(""))
        account_label = QLabel("Аккаунт")
        account_label.setObjectName("Muted")
        card.add(account_label)
        self.account_input = QLineEdit()
        self.account_input.setPlaceholderText("Основной")
        self.account_input.setToolTip("Необязательная метка для группировки адресов")
        self.account_input.setClearButtonEnabled(True)
        self.account_input.setMaximumWidth(280)
        card.add(self.account_input)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.generate_button = QPushButton("Новый адрес")
        self.generate_button.setObjectName("GhostButton")
        self.generate_button.setIcon(
            icon("plus", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.generate_button.setToolTip("Создать новый адрес в текущем аккаунте")
        self.generate_button.clicked.connect(self._generate)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("GhostButton")
        self.refresh_button.setIcon(
            icon("refresh", self.tokens.get("muted", "#A7B1C2"), 16)
        )
        self.refresh_button.setToolTip("Обновить список адресов (F5)")
        self.refresh_button.clicked.connect(self.refresh)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.refresh_button)
        actions.addStretch(1)
        card.add_layout(actions)

        card.add(QLabel(""))
        self.balance_row = KeyValueRow("Баланс адреса", "-")
        self.utxo_row = KeyValueRow("Входов", "-")
        self.tx_row = KeyValueRow("Операций", "-")
        self.created_row = KeyValueRow("Первый контакт", "-")
        for row in (self.balance_row, self.utxo_row, self.tx_row, self.created_row):
            card.add(row)
        self.account_note = QLabel(
            "Новый адрес не связан с предыдущими в блокчейне, "
            "но кошелек знает обо всех."
        )
        self.account_note.setObjectName("HintText")
        self.account_note.setWordWrap(True)
        card.add(self.account_note)
        card.add_stretch(1)
        return card

    def _build_addresses_card(self) -> Card:
        """Build the sortable address book."""
        card = Card(padding=16, spacing=8)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        title = QLabel("Адреса кошелька")
        title.setObjectName("CardTitle")
        self.search = SearchField("Найти адрес или аккаунт")
        self.search.textChanged.connect(self._filter_addresses)
        self.search.setFixedWidth(280)
        self.search.setToolTip("Фильтр по адресу, аккаунту или заметке")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.search)
        card.add_layout(header)
        self.table = SortableTable(
            [
                Column("Адрес", 250, stretch=True),
                Column("Аккаунт", 120),
                Column(
                    "Баланс",
                    135,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "Входы",
                    75,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "Операции",
                    100,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column("Первый контакт", 140),
            ]
        )
        self.table.setMinimumHeight(260)
        self.table.setToolTip(
            "Двойной щелчок копирует адрес, Enter выбирает его для получения"
        )
        self.table.set_empty_message(
            "Адресов пока нет",
            "Создайте первый адрес, чтобы получить монеты.",
            "wallet",
        )
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        card.add(self.table, 1)
        self.footer = QLabel("")
        self.footer.setObjectName("HintText")
        self.footer.setWordWrap(True)
        card.add(self.footer)
        return card

    def refresh(self) -> None:
        """Reload the address list and restore the last address."""
        if not self.begin_refresh():
            return
        run_async(
            self.service.available_addresses,
            self._apply_addresses,
            self.fail,
            lambda: self.end_refresh(True),
        )

    def _apply_addresses(self, addresses: list[AddressInfo]) -> None:
        """Fill the table and pick a sensible current address."""
        self._addresses = addresses
        if not self._current_address:
            saved = self.settings.last_receive_address
            if saved and any(item.address == saved for item in addresses):
                self._current_address = saved
            elif addresses:
                self._current_address = addresses[0].address
        self._render_address()
        self._render_table()
        self.status_pill.set_text(f"Адресов: {len(addresses)}")
        self.status_pill.set_level("success" if addresses else "warning")

    def _render_table(self) -> None:
        """Rebuild rows while preserving the filter."""
        query = self.search.text()
        rows = []
        for item in self._addresses:
            address_cell = text_item(
                shorten_address(item.address, 18, 10),
                sort_key=item.address,
                mono=True,
                tooltip=item.address,
                font_family=self.themes.mono_family,
            )
            account_cell = text_item(
                item.account or "Основной", sort_key=item.account or "Основной"
            )
            balance_cell = SortItem(f"{format_nvc(item.balance)}", item.balance)
            balance_cell.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            utxo_cell = text_item(
                str(item.utxo_count),
                sort_key=item.utxo_count,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            tx_cell = text_item(
                str(item.tx_count),
                sort_key=item.tx_count,
                align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            )
            created = (
                format_timestamp(item.created_at, "%d.%m.%Y")
                if item.created_at
                else "-"
            )
            created_cell = text_item(created, sort_key=item.created_at)
            for cell in (
                address_cell,
                account_cell,
                balance_cell,
                utxo_cell,
                tx_cell,
                created_cell,
            ):
                cell.setData(Qt.ItemDataRole.UserRole, item.address)
            rows.append(
                [
                    address_cell,
                    account_cell,
                    balance_cell,
                    utxo_cell,
                    tx_cell,
                    created_cell,
                ]
            )
        self.table.set_rows(rows)
        self.table.end_update(2, ascending=False)
        if query:
            self.table.filter_rows(query)
        total = sum((item.balance for item in self._addresses), Decimal("0"))
        self.footer.setText(
            f"Показано {len(self._addresses)} адресов на {format_nvc(total)}. "
            "Двойной щелчок копирует адрес."
        )

    def _render_address(self) -> None:
        """Show the current address, QR and per-address statistics."""
        address = self._current_address
        if not address:
            self.address_label.setText("Нажмите кнопку ниже, чтобы создать адрес")
            self.qr.set_data("")
            self.status_pill.set_text("Не выбран")
            self.status_pill.set_level("warning")
            for row in (self.balance_row, self.utxo_row, self.tx_row, self.created_row):
                row.set_value("-")
            self.copy_button.setEnabled(False)
            return
        self.address_label.setText(address)
        self.qr.set_data(address)
        self.qr.set_colors("#0B111A", "#FFFFFF")
        self.copy_button.setEnabled(True)
        info = next((item for item in self._addresses if item.address == address), None)
        if info is None:
            self.balance_row.set_value("0.00 NVC")
            self.utxo_row.set_value("0")
            self.tx_row.set_value("0")
            self.created_row.set_value("-")
            self.status_pill.set_text("Выбран")
        else:
            self.balance_row.set_value(f"{format_nvc(info.balance)}")
            self.utxo_row.set_value(str(info.utxo_count))
            self.tx_row.set_value(str(info.tx_count))
            self.created_row.set_value(
                format_timestamp(info.created_at, "%d.%m.%Y %H:%M")
                if info.created_at
                else "-"
            )
            self.status_pill.set_text("Выбран")
        self.status_pill.set_level("success")
        self.settings.last_receive_address = address

    def _filter_addresses(self, _text: str) -> None:
        """Filter table rows by the search box."""
        self.table.filter_rows(self.search.text())

    def _on_selection_changed(self) -> None:
        """Show a hovered or keyboard-selected address in the details card."""
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        address = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if address and address != self._current_address:
            self._current_address = address
            self._render_address()

    def _on_cell_clicked(self, row: int, _column: int) -> None:
        """Select the clicked address."""
        item = self.table.item(row, 0)
        if item is not None:
            self._current_address = str(item.data(Qt.ItemDataRole.UserRole) or "")
            self._render_address()

    def _on_cell_double_clicked(self, row: int, _column: int) -> None:
        """Copy the double-clicked address."""
        item = self.table.item(row, 0)
        if item is not None:
            self._select_and_copy(str(item.data(Qt.ItemDataRole.UserRole) or ""))

    def _select_and_copy(self, address: str) -> None:
        """Copy an address and make it current."""
        if not address:
            return
        self._current_address = address
        self._render_address()
        QApplication.clipboard().setText(address)
        self.notify("Адрес скопирован в буфер обмена", 3000)

    def _copy_current(self) -> None:
        """Copy the displayed address."""
        self._select_and_copy(self._current_address)

    def _generate(self) -> None:
        """Ask the proxy for a fresh deterministic address."""
        if self._generating:
            return
        account = self.account_input.text().strip()
        self._generating = True
        self.generate_button.setEnabled(False)
        self.generate_button.setText("Создание...")
        run_async(
            lambda: self.service.new_address(account),
            self._on_generated,
            self._on_generate_error,
            self._on_generate_done,
        )

    def _on_generated(self, address: str) -> None:
        """Display a freshly generated address."""
        if not address:
            self.fail("Прокси вернул пустой адрес")
            return
        self._current_address = address
        self.settings.last_receive_address = address
        self.notify("Новый адрес создан", 4000)
        self.refresh()
        self._render_address()

    def _on_generate_error(self, error: BaseException) -> None:
        """Report a generation failure."""
        self.fail(error)

    def _on_generate_done(self) -> None:
        """Restore the generate button."""
        self._generating = False
        self.generate_button.setEnabled(True)
        self.generate_button.setText("Новый адрес")

    def _save_qr(self) -> None:
        """Save the current QR matrix as a PNG file."""
        if not self._current_address:
            self.notify("Сначала создайте адрес", 3000)
            return
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        suggested = str(
            Path(pictures or ".")
            / f"phoenix-{shorten_address(self._current_address, 8, 0)}.png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить QR-код",
            suggested,
            "PNG-изображение (*.png)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if self.qr.save_png(path, 512):
            self.notify(f"QR-код сохранен: {path}", 5000)
        else:
            self.fail("Не удалось сохранить изображение")

    def apply_theme(self) -> None:
        """Repaint table accents and keep the QR scannable on a white field."""
        self.table.set_accent(self.tokens.get("accent", "#FF8A3D"))
        self.qr.set_colors("#0B111A", "#FFFFFF")
        self._render_table()
