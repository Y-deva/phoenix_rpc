"""Send page with a simple flow and an expert coin-control flow."""

from __future__ import annotations

from decimal import Decimal

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.coinselect import (
    InsufficientFunds,
    SendPlan,
    estimate_fee,
    estimate_tx_size,
    plan_send,
)
from ...core.formatting import (
    COIN,
    format_int,
    format_nvc,
    from_sat,
    shorten_address,
)
from ...core.tasks import run_async
from ...core.validation import validate_address, validate_amount, validate_comment
from ...rpc.models import Utxo
from ..dialogs.confirm import ConfirmSendDialog
from ..widgets.card import Card, Divider, KeyValueRow, Pill
from ..widgets.fields import AmountField, LabeledField, SegmentedControl
from ..widgets.icons import icon
from ..widgets.table import Column, SortableTable, amount_item, text_item
from .base import ScrollPage


class SendPage(ScrollPage):
    """Create a transfer from a recipient form or from hand-picked inputs."""

    page_id = "send"
    page_title = "Отправка"
    page_subtitle = "Перевод NVC с контролем адреса и входов"

    def __init__(self, context, parent: QWidget | None = None) -> None:
        """Initialize the SendPage instance."""
        super().__init__(context, parent)
        self._utxos: list[Utxo] = []
        self._utxo_map: dict[str, Utxo] = {}
        self._plan: SendPlan | None = None
        self._mode = "simple"
        self._refreshing_coins = False
        self._sending = False
        self._preselected: set[str] = set()
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        """Build both send modes and the persistent summary column."""
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)
        self.mode_control = SegmentedControl()
        self.mode_control.add_segment(
            "simple",
            "Простой",
            "Адрес, сумма и комментарий. Входы выбирает кошелек.",
        )
        self.mode_control.add_segment(
            "expert",
            "Эксперт",
            "Ручной выбор входов и расчет сдачи.",
        )
        self.mode_control.valueChanged.connect(self._switch_mode)
        toolbar.addWidget(self.mode_control)
        toolbar.addStretch(1)
        self.available_pill = Pill("Доступно: 0.00 NVC", "neutral")
        self.available_pill.setToolTip("Сумма подтвержденных и готовых к трате входов")
        toolbar.addWidget(self.available_pill)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("GhostButton")
        refresh.setIcon(icon("refresh", self.tokens.get("muted", "#A7B1C2"), 16))
        refresh.setToolTip("Заново запросить список входов (F5)")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(refresh)
        self.body.addLayout(toolbar)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(14)
        left.addWidget(self._build_recipient_card())
        left.addWidget(self._build_amount_card())
        self.expert_card = self._build_expert_card()
        left.addWidget(self.expert_card, 1)
        columns.addLayout(left, 2)
        self.summary_card = self._build_summary_card()
        columns.addWidget(self.summary_card, 1)
        self.body.addLayout(columns, 1)
        self.body.addWidget(self._build_parameters_card())
        self.body.addStretch(1)
        self.protect(
            self.available_pill,
            self.summary_amount.value_label,
            self.summary_change.value_label,
            self.summary_inputs.value_label,
            self.coin_table.viewport(),
        )

        self._switch_mode("simple")

    def _build_parameters_card(self) -> Card:
        """Show the wallet limits that affect a transfer."""
        card = Card(padding=14, spacing=8, object_name="SoftCard")
        title = QLabel("Параметры перевода")
        title.setObjectName("CardTitle")
        card.add(title)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(6)
        dust = KeyValueRow(
            "Пылевой порог",
            format_nvc(from_sat(self.config.dust_threshold_sat)),
            mono=True,
        )
        comment = KeyValueRow("Комментарий", "до 80 байт, OP_RETURN")
        signing = KeyValueRow("Подпись", "локально в прокси")
        grid.addWidget(dust, 0, 0)
        grid.addWidget(comment, 0, 1)
        grid.addWidget(signing, 1, 0, 1, 2)
        card.add_layout(grid)
        return card

    def _build_recipient_card(self) -> Card:
        """Build the recipient address card."""
        card = Card(padding=18, spacing=10)
        title = QLabel("Получатель")
        title.setObjectName("CardTitle")
        card.add(title)
        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("Введите адрес получателя")
        self.address_input.setClearButtonEnabled(True)
        self.address_input.setMinimumHeight(38)
        self.address_input.setToolTip(
            "Вставьте адрес из буфера обмена. "
            "Поддерживается проверка контрольной суммы."
        )
        self.address_input.textChanged.connect(self._recompute)
        paste_action = QAction(
            icon("copy", self.tokens.get("muted", "#A7B1C2"), 16),
            "Вставить",
            self.address_input,
        )
        paste_action.setToolTip("Вставить адрес из буфера обмена")
        paste_action.triggered.connect(self.address_input.paste)
        self.address_input.addAction(
            paste_action, QLineEdit.ActionPosition.TrailingPosition
        )
        self.address_field = LabeledField(
            "Адрес получателя",
            self.address_input,
            "Base58Check, P2SH",
        )
        card.add(self.address_field)
        self.address_network_hint = QLabel("")
        self.address_network_hint.setObjectName("HintText")
        self.address_network_hint.setWordWrap(True)
        card.add(self.address_network_hint)
        return card

    def _build_amount_card(self) -> Card:
        """Build amount and comment inputs."""
        card = Card(padding=18, spacing=10)
        title = QLabel("Сумма и комментарий")
        title.setObjectName("CardTitle")
        card.add(title)
        amount_row = QHBoxLayout()
        amount_row.setContentsMargins(0, 0, 0, 0)
        amount_row.setSpacing(8)
        self.amount_input = AmountField()
        self.amount_input.setToolTip(
            "Сумма перевода в NVC. Точность: 8 знаков после запятой."
        )
        self.amount_input.textChanged.connect(self._recompute)
        self.amount_field = LabeledField("Сумма", self.amount_input, "NVC")
        amount_row.addWidget(self.amount_field, 1)
        self.max_button = QPushButton("Максимум")
        self.max_button.setObjectName("GhostButton")
        self.max_button.setToolTip("Подставить максимальную доступную сумму")
        self.max_button.clicked.connect(self._fill_max)
        amount_row.addWidget(self.max_button, 0, Qt.AlignmentFlag.AlignBottom)
        card.add_layout(amount_row)
        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("Необязательно, попадёт в OP_RETURN")
        self.comment_input.setMaxLength(80)
        self.comment_input.setClearButtonEnabled(True)
        self.comment_input.setToolTip(
            "Публичный комментарий. Максимум 80 байт в UTF-8."
        )
        self.comment_input.textChanged.connect(self._on_comment_changed)
        self.comment_field = LabeledField(
            "Комментарий", self.comment_input, "0 / 80 байт"
        )
        card.add(self.comment_field)
        self.comment_hint = QLabel(
            "Комментарий записывается в блокчейн через OP_RETURN и виден всем."
        )
        self.comment_hint.setObjectName("HintText")
        self.comment_hint.setWordWrap(True)
        card.add(self.comment_hint)
        return card

    def _build_expert_card(self) -> Card:
        """Build the manual input selection table."""
        card = Card(padding=16, spacing=8)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        title = QLabel("Входы для подписи")
        title.setObjectName("CardTitle")
        self.selection_pill = Pill("Выбрано: 0", "neutral")
        self.select_all_button = QPushButton("Выбрать все")
        self.select_all_button.setObjectName("GhostButton")
        self.select_all_button.setToolTip("Отметить все доступные входы")
        self.select_all_button.clicked.connect(lambda: self._set_all_selected(True))
        self.clear_button = QPushButton("Снять")
        self.clear_button.setObjectName("GhostButton")
        self.clear_button.setToolTip("Снять отметки со всех входов")
        self.clear_button.clicked.connect(lambda: self._set_all_selected(False))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.selection_pill)
        header.addWidget(self.select_all_button)
        header.addWidget(self.clear_button)
        card.add_layout(header)
        self.coin_table = SortableTable(
            [
                Column("", 42, Qt.AlignmentFlag.AlignCenter),
                Column("Вход", 150),
                Column("Адрес", 210, stretch=True),
                Column(
                    "Сумма",
                    120,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
                Column(
                    "Подтв.",
                    70,
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                ),
            ],
            row_height=38,
        )
        self.coin_table.setMinimumHeight(260)
        self.coin_table.setToolTip("Отметьте входы вручную для ручной отправки.")
        self.coin_table.set_empty_message(
            "Нет доступных входов",
            "Дождитесь подтверждения поступлений или обновите список.",
            "coins",
        )
        self.coin_table.itemChanged.connect(self._on_coin_changed)
        card.add(self.coin_table, 1)
        self.coin_footer = QLabel("")
        self.coin_footer.setObjectName("HintText")
        self.coin_footer.setWordWrap(True)
        card.add(self.coin_footer)
        return card

    def _build_summary_card(self) -> Card:
        """Build the sticky-looking summary and send button."""
        card = Card(padding=18, spacing=10)
        title = QLabel("Итог перевода")
        title.setObjectName("CardTitle")
        card.add(title)
        self.summary_amount = KeyValueRow("Сумма", "-")
        self.summary_change = KeyValueRow("Сдача", "-")
        self.summary_inputs = KeyValueRow("Входы", "-")
        for row in (
            self.summary_amount,
            self.summary_change,
            self.summary_inputs,
        ):
            card.add(row)
        card.add(Divider())
        self.send_hint = QLabel("Заполните адрес и сумму.")
        self.send_hint.setObjectName("HintText")
        self.send_hint.setWordWrap(True)
        card.add(self.send_hint)
        self.send_button = QPushButton("Отправить")
        self.send_button.setObjectName("AccentButton")
        self.send_button.setMinimumHeight(42)
        self.send_button.setToolTip("Проверить и отправить транзакцию (Ctrl+Enter)")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._confirm_and_send)
        card.add(self.send_button)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._confirm_and_send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._confirm_and_send)
        self.privacy_note = QLabel(
            "Подпись выполняется локально в прокси. Приватные ключи не передаются."
        )
        self.privacy_note.setObjectName("HintText")
        self.privacy_note.setWordWrap(True)
        card.add(self.privacy_note)
        card.add_stretch(1)
        return card

    def refresh(self) -> None:
        """Reload spendable outputs."""
        if not self.begin_refresh():
            return
        run_async(
            self.service.list_unspent,
            self._apply_utxos,
            self._on_refresh_error,
            lambda: self.end_refresh(True),
        )

    def _apply_utxos(self, utxos: list[Utxo]) -> None:
        """Store the inputs, rebuild the expert table and refresh estimates."""
        self._utxos = list(utxos)
        self._utxo_map = {utxo.key: utxo for utxo in self._utxos}
        spendable = sum(
            (utxo.amount for utxo in self._utxos if utxo.spendable), Decimal("0")
        )
        self.available_pill.set_text(f"Доступно: {format_nvc(spendable)}")
        self.available_pill.set_level("success" if spendable > 0 else "warning")
        self._populate_coins()
        self._recompute()

    def _on_refresh_error(self, error: BaseException) -> None:
        """Report a failed refresh and clear the busy guard."""
        self.end_refresh(False)
        self.fail(error)

    def _populate_coins(self) -> None:
        """Fill the expert table while preserving checked inputs."""
        selected = self._selected_keys() | self._preselected
        self._preselected = set()
        self._refreshing_coins = True
        self.coin_table.begin_update()
        self.coin_table.setRowCount(0)
        for utxo in sorted(self._utxos, key=lambda item: item.amount, reverse=True):
            item = SortItemCheck(utxo.key)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if utxo.key in selected
                else Qt.CheckState.Unchecked
            )
            row = self.coin_table.rowCount()
            self.coin_table.insertRow(row)
            self.coin_table.setItem(row, 0, item)
            self.coin_table.setItem(
                row,
                1,
                text_item(
                    f"{shorten_address(utxo.txid, 7, 5)}:{utxo.vout}",
                    sort_key=utxo.txid,
                    mono=True,
                    tooltip=f"{utxo.txid}:{utxo.vout}",
                    font_family=self.themes.mono_family,
                ),
            )
            self.coin_table.setItem(
                row,
                2,
                text_item(
                    shorten_address(utxo.address, 12, 8) if utxo.address else "-",
                    sort_key=utxo.address,
                    mono=True,
                    tooltip=utxo.address,
                    font_family=self.themes.mono_family,
                ),
            )
            self.coin_table.setItem(
                row,
                3,
                amount_item(
                    utxo.amount,
                    incoming=True,
                    mono_font=self.themes.mono_family,
                    signed=False,
                ),
            )
            self.coin_table.setItem(
                row,
                4,
                text_item(
                    format_int(utxo.confirmations),
                    sort_key=utxo.confirmations,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    color=self.tokens.get("muted", "#A7B1C2"),
                ),
            )
        self.coin_table.end_update(3, ascending=False)
        self._refreshing_coins = False

    def preselect(self, utxos: object) -> None:
        """Open expert mode with the given inputs checked after refresh."""
        keys = {utxo.key for utxo in utxos if getattr(utxo, "spendable", False)}
        if not keys:
            return
        self._preselected = keys
        self._switch_mode("expert")
        self.refresh()

    def _selected_keys(self) -> set[str]:
        """Return keys of rows whose checkbox is on."""
        keys: set[str] = set()
        for row in range(self.coin_table.rowCount()):
            item = self.coin_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                keys.add(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        keys.discard("")
        return keys

    def _selected_utxos(self) -> list[Utxo]:
        """Return checked UTXO objects in table order."""
        return [
            self._utxo_map[key]
            for key in self._selected_keys()
            if key in self._utxo_map and self._utxo_map[key].spendable
        ]

    def _on_coin_changed(self, _item: QTableWidgetItem) -> None:
        """Recompute when a checkbox changes."""
        if self._refreshing_coins:
            return
        self._recompute()

    def _set_all_selected(self, checked: bool) -> None:
        """Check or uncheck every row without triggering a storm of updates."""
        self._refreshing_coins = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.coin_table.rowCount()):
            item = self.coin_table.item(row, 0)
            if item is not None:
                item.setCheckState(state)
        self._refreshing_coins = False
        self._recompute()

    def _switch_mode(self, mode: str) -> None:
        """Show the coin table only in expert mode."""
        self._mode = mode
        self.expert_card.setVisible(mode == "expert")
        self.send_hint.setText(
            "Выберите входы и укажите сумму."
            if mode == "expert"
            else "Заполните адрес и сумму."
        )
        self._recompute()

    def _on_comment_changed(self, text: str) -> None:
        """Update the byte counter and recompute the fee."""
        byte_count = len(text.encode("utf-8"))
        self.comment_field.set_hint(self.tr_text(f"{byte_count} / 80 байт"))
        valid, message = validate_comment(text)
        self.comment_field.set_error(
            "" if valid else self.tr_text("Комментарий длиннее 80 байт")
        )
        self._recompute()

    def _fill_max(self) -> None:
        """Fill the largest amount that still pays a reasonable fee."""
        if self._mode == "expert":
            utxos = self._selected_utxos()
            if not utxos:
                self.notify("Сначала выберите хотя бы один вход", 3500)
                return
        else:
            utxos = [utxo for utxo in self._utxos if utxo.spendable]
        total = sum((utxo.amount for utxo in utxos), Decimal("0"))
        if total <= 0:
            self.notify("Нет доступных средств", 3500)
            return
        has_comment = bool(self.comment_input.text().strip())
        # Reserve the fee for every eligible input. This is slightly
        # conservative, but the change output absorbs the remainder.
        fee = estimate_fee(
            estimate_tx_size(len(utxos), 1, has_comment, True),
            self.config.sat_per_byte,
        )
        maximum = total - fee
        if maximum <= 0:
            self.notify("Недостаточно средств для перевода", 4000)
            return
        self.amount_input.setText(f"{maximum:.8f}")

    def _recompute(self) -> None:
        """Validate the form and update the fee preview."""
        if not hasattr(self, "send_button"):
            return
        address = self.address_input.text().strip()
        address_check = validate_address(
            address,
            expected_network="testnet" if self.config.testnet else "mainnet",
        )
        self.address_field.set_error(
            "" if address_check.valid or not address else address_check.reason
        )
        if address_check.warning:
            self.address_network_hint.setText(
                "Адрес относится к другой сети. Убедитесь, что это намеренно."
            )
        else:
            self.address_network_hint.setText("")
        amount_text = self.amount_input.text().strip()
        amount_check = validate_amount(
            amount_text,
            available=None,
            dust=Decimal(self.config.dust_threshold_sat) / COIN,
        )
        self.amount_field.set_error(
            "" if amount_check.valid or not amount_text else amount_check.reason
        )
        comment = self.comment_input.text().strip()
        comment_ok, _ = validate_comment(comment)
        self._plan = None
        self._clear_summary()
        if not address_check.valid:
            self.send_hint.setText(
                "Введите корректный адрес получателя."
                if address
                else "Заполните адрес и сумму."
            )
            self.send_button.setEnabled(False)
            return
        if not amount_check.valid:
            self.send_hint.setText(
                "Введите сумму больше пылевого порога."
                if amount_text
                else "Укажите сумму перевода."
            )
            self.send_button.setEnabled(False)
            return
        if not comment_ok:
            self.send_hint.setText(self.tr_text("Сократите комментарий до 80 байт."))
            self.send_button.setEnabled(False)
            return
        if self._mode == "expert":
            inputs = self._selected_utxos()
            if not inputs:
                self.send_hint.setText("Отметьте входы в таблице ниже.")
                self.send_button.setEnabled(False)
                return
            selected_total = sum((utxo.amount for utxo in inputs), Decimal("0"))
            if amount_check.amount > selected_total:
                self.send_hint.setText(
                    f"Выбрано {format_nvc(selected_total)}, этого недостаточно."
                )
                self.send_button.setEnabled(False)
                return
        try:
            plan = plan_send(
                self._utxos,
                amount_check.amount,
                sat_per_byte=self.config.sat_per_byte,
                comment=comment,
                fixed_inputs=self._selected_utxos() if self._mode == "expert" else None,
                dust_threshold_sat=self.config.dust_threshold_sat,
            )
        except InsufficientFunds as exc:
            self.send_hint.setText(
                f"Недостаточно средств: нужно {format_nvc(exc.required)}, "
                f"есть {format_nvc(exc.available)}."
            )
            self.send_button.setEnabled(False)
            return
        except ValueError as exc:
            self.send_hint.setText(str(exc))
            self.send_button.setEnabled(False)
            return
        self._plan = plan
        self._show_plan(plan, address)
        self.send_button.setEnabled(not self._sending)

    def _clear_summary(self) -> None:
        """Reset the right-hand totals."""
        for row in (
            self.summary_amount,
            self.summary_change,
            self.summary_inputs,
        ):
            row.set_value("-")
        self.selection_pill.set_text("Выбрано: 0")
        self.selection_pill.set_level("neutral")

    def _show_plan(self, plan: SendPlan, address: str) -> None:
        """Render a validated send plan."""
        self.summary_amount.set_value(f"{format_nvc(plan.amount)}")
        self.summary_change.set_value(
            f"{format_nvc(plan.change)}" if plan.has_change else "Нет"
        )
        self.summary_inputs.set_value(str(plan.input_count))
        self.send_hint.setText("Проверьте адрес и сумму перед отправкой.")
        if self._mode == "expert":
            selected = self._selected_utxos()
            total = sum((utxo.amount for utxo in selected), Decimal("0"))
            self.selection_pill.set_text(f"Выбрано: {len(selected)}")
            self.selection_pill.set_level("accent" if selected else "neutral")
            self.coin_footer.setText(
                f"Выбрано {len(selected)} входов на {format_nvc(total)}. "
                f"Сдача {format_nvc(plan.change)}."
            )
        else:
            self.coin_footer.setText("")
        if self.settings.verbosity >= 2:
            self.privacy_note.setText(
                f"Оценка размера: {plan.size} байт. "
                "Подпись Falcon занимает около 1800 байт на вход."
            )
        else:
            self.privacy_note.setText(
                "Подпись выполняется локально в прокси. Приватные ключи не передаются."
            )
        self.send_button.setToolTip(
            f"Отправить {format_nvc(plan.amount)} на "
            f"{shorten_address(address, 10, 6)} (Ctrl+Enter)"
        )

    def _confirm_and_send(self) -> None:
        """Ask for confirmation, then run the blocking send in a worker."""
        if self._plan is None or self._sending:
            return
        address = self.address_input.text().strip()
        address_check = validate_address(
            address,
            expected_network="testnet" if self.config.testnet else "mainnet",
        )
        if not address_check.valid:
            self.address_field.set_error(address_check.reason)
            return
        if address_check.warning:
            self.notify("Адрес относится к другой сети. Проверьте намерение.", 5000)
        plan = self._plan
        comment = self.comment_input.text().strip()
        mode = self._mode
        if self.settings.confirm_send:
            dialog = ConfirmSendDialog(
                address=address,
                amount=plan.amount,
                fee=plan.fee,
                change=plan.change if plan.has_change else Decimal("0"),
                comment=comment,
                input_count=plan.input_count,
                expert=self._mode == "expert",
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
        self._set_sending(True)
        run_async(
            lambda: self._send_worker(address, plan, comment, mode),
            self._on_send_success,
            self._on_send_error,
            lambda: self._set_sending(False),
        )

    def _send_worker(
        self, address: str, plan: SendPlan, comment: str, mode: str
    ) -> str:
        """Perform the blocking RPC sequence."""
        if mode == "simple":
            return self.service.send_to_address(address, plan.amount, comment)
        change_address = self.service.new_address("change") if plan.has_change else ""
        outputs = plan.outputs(address, change_address)
        data_hex = comment.encode("utf-8").hex() if comment else ""
        raw_hex = self.service.create_raw_transaction(
            [(utxo.txid, utxo.vout) for utxo in plan.inputs],
            outputs,
            data_hex,
        )
        signed = self.service.sign_raw_transaction(raw_hex)
        if not signed.complete:
            raise RuntimeError(
                "Прокси не смог подписать все входы. "
                "Проверьте, что они принадлежат кошельку."
            )
        return self.service.send_raw_transaction(signed.hex)

    def _on_send_success(self, txid: str) -> None:
        """Reset the form and announce the broadcast."""
        self._plan = None
        self.amount_input.clear()
        self.comment_input.clear()
        self.address_input.clear()
        self.notify(f"Транзакция отправлена: {shorten_address(txid, 10, 8)}", 7000)
        self.dataChanged.emit()
        self.refresh()

    def _on_send_error(self, error: BaseException) -> None:
        """Show a human-friendly send error."""
        self.fail(error)
        self._set_sending(False)

    def _set_sending(self, sending: bool) -> None:
        """Toggle the send button and busy text."""
        self._sending = sending
        self.send_button.setText("Отправка..." if sending else "Отправить")
        self.send_button.setEnabled(not sending and self._plan is not None)
        self.max_button.setEnabled(not sending)
        self.address_input.setEnabled(not sending)
        self.amount_input.setEnabled(not sending)
        self.comment_input.setEnabled(not sending)
        self.mode_control.setEnabled(not sending)

    def apply_theme(self) -> None:
        """Update themed icons and table accents."""
        self.coin_table.set_accent(self.tokens.get("accent", "#FF8A3D"))
        self.available_pill.set_level(self.available_pill.level)
        self._populate_coins()
        self._recompute()


class SortItemCheck(QTableWidgetItem):
    """Checkable table cell that keeps a stable UTXO key for sorting."""

    def __init__(self, key: str) -> None:
        """Initialize the SortItemCheck instance."""
        super().__init__("")
        self.setData(Qt.ItemDataRole.UserRole, key)
        self.setToolTip("Отметить вход для подписи")
