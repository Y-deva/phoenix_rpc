"""Dashboard page with balances, activity and network state."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.formatting import (
    format_amount,
    format_difficulty,
    format_int,
    format_nvc,
    format_percent,
)
from ...core.tasks import run_async
from ...rpc.models import (
    AddressInfo,
    BalanceSummary,
    ChainInfo,
    NetworkInfo,
    Transaction,
    Utxo,
)
from ...rpc.service import balance_summary, derive_addresses
from ..widgets.card import Card, EmptyState, KeyValueRow, Pill, StatCard, action_button
from ..widgets.chart import ChartPanel, Sparkline
from ..widgets.rows import TransactionRow
from .base import ScrollPage


class OverviewPage(ScrollPage):
    """Landing page that answers: how much, what happened, is the node healthy."""

    page_id = "overview"
    page_title = "Обзор"
    page_subtitle = "Баланс, последние операции и состояние сети"

    def __init__(self, context, parent: QWidget | None = None) -> None:
        """Initialize the OverviewPage instance."""
        super().__init__(context, parent)
        self._transactions: list[Transaction] = []
        self._balance = BalanceSummary()
        self._network: NetworkInfo | None = None
        self._chain: ChainInfo | None = None
        self._refresh_ok = False
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        """Create the static dashboard layout."""
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(14)
        top.addWidget(self._build_hero(), 2)
        top.addLayout(self._build_metrics(), 1)
        self.body.addLayout(top)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(14)
        self.activity_chart = ChartPanel(
            "Активность",
            "Поступления и отправления за последние 14 дней",
        )
        self.distribution_chart = ChartPanel(
            "Структура баланса",
            "Доступно, в ожидании и незрелые монеты",
        )
        middle.addWidget(self.activity_chart, 2)
        middle.addWidget(self.distribution_chart, 1)
        self.body.addLayout(middle)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(14)
        bottom.addWidget(self._build_recent(), 2)
        bottom.addWidget(self._build_network(), 1)
        self.body.addLayout(bottom)

    def _build_hero(self) -> Card:
        """Build the primary balance card."""
        card = Card(object_name="HeroCard", padding=22, spacing=10)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        title = QLabel("Доступный баланс")
        title.setObjectName("CardTitle")
        self.network_pill = Pill("Сеть", "neutral")
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.network_pill)
        card.add_layout(top)
        self.balance_label = QLabel("0.00 NVC")
        self.balance_label.setObjectName("HeroValue")
        self.balance_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        card.add(self.balance_label)
        self.hero_caption = QLabel("Подтвержденные и готовые к трате входы")
        self.hero_caption.setObjectName("Muted")
        self.hero_caption.setWordWrap(True)
        card.add(self.hero_caption)
        self.hero_spark = Sparkline(color=self.tokens.get("accent", "#FF8A3D"))
        self.hero_spark.setToolTip("Динамика общего баланса за последние 14 дней")
        card.add(self.hero_spark)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.setSpacing(8)
        send_button = action_button(
            "Отправить",
            "send",
            "AccentButton",
            self.tokens.get("accent_text", "#1B0D04"),
        )
        send_button.setToolTip("Перейти к отправке NVC (Ctrl+2)")
        send_button.clicked.connect(lambda: self.navigateRequested.emit("send"))
        receive_button = action_button(
            "Получить", "receive", "GhostButton", self.tokens.get("muted", "#A7B1C2")
        )
        receive_button.setToolTip("Показать адрес для получения (Ctrl+3)")
        receive_button.clicked.connect(lambda: self.navigateRequested.emit("receive"))
        history_button = action_button(
            "История",
            "transactions",
            "GhostButton",
            self.tokens.get("muted", "#A7B1C2"),
        )
        history_button.setToolTip("Открыть полную историю операций (Ctrl+4)")
        history_button.clicked.connect(
            lambda: self.navigateRequested.emit("transactions")
        )
        buttons.addWidget(send_button)
        buttons.addWidget(receive_button)
        buttons.addWidget(history_button)
        buttons.addStretch(1)
        card.add_layout(buttons)
        return card

    def _build_metrics(self) -> QGridLayout:
        """Build four compact metric cards to the right of the hero."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self.pending_card = StatCard(
            "В ожидании",
            "0.00",
            "Нет неподтвержденных входов",
            "clock",
            self.tokens.get("warning", "#F3C969"),
        )
        self.pending_card.setToolTip("Сумма входов без подтверждений")
        self.pending_card.clicked.connect(
            lambda: self.navigateRequested.emit("transactions")
        )
        self.immature_card = StatCard(
            "Не созрело",
            "0.00",
            "Награды за блоки",
            "lock",
            self.tokens.get("warning", "#F3C969"),
        )
        self.immature_card.setToolTip("Монеты, которые еще нельзя потратить")
        self.immature_card.clicked.connect(
            lambda: self.navigateRequested.emit("transactions")
        )
        self.addresses_card = StatCard(
            "Адреса",
            "0",
            "Кошелек",
            "wallet",
            self.tokens.get("info", "#6BB8FF"),
        )
        self.addresses_card.setToolTip("Количество известных адресов кошелька")
        self.addresses_card.clicked.connect(
            lambda: self.navigateRequested.emit("receive")
        )
        self.utxo_card = StatCard(
            "Входы",
            "0",
            "Неизрасходованные выходы",
            "coins",
            self.tokens.get("accent", "#FF8A3D"),
        )
        self.utxo_card.setToolTip("Количество UTXO, доступных кошельку")
        self.utxo_card.clicked.connect(lambda: self.navigateRequested.emit("coins"))
        grid.addWidget(self.pending_card, 0, 0)
        grid.addWidget(self.immature_card, 0, 1)
        grid.addWidget(self.addresses_card, 1, 0)
        grid.addWidget(self.utxo_card, 1, 1)
        return grid

    def _build_recent(self) -> Card:
        """Build the recent transactions card."""
        card = Card(padding=16, spacing=8)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        title = QLabel("Последние операции")
        title.setObjectName("CardTitle")
        open_all = QPushButton("Все операции")
        open_all.setObjectName("GhostButton")
        open_all.setToolTip("Открыть историю с фильтрами и сортировкой")
        open_all.clicked.connect(lambda: self.navigateRequested.emit("transactions"))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(open_all)
        card.add_layout(header)
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_layout.setSpacing(2)
        card.add_layout(self.recent_layout)
        self.recent_empty = EmptyState(
            "Пока нет операций",
            "Здесь появятся поступления, отправки и награды за блоки.",
            "transactions",
        )
        self.recent_empty.setVisible(False)
        card.add(self.recent_empty)
        return card

    def _build_network(self) -> Card:
        """Build the node and synchronization card."""
        card = Card(padding=16, spacing=10)
        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        title = QLabel("Состояние сети")
        title.setObjectName("CardTitle")
        self.mining_pill = Pill("Майнинг", "accent")
        self.mining_pill.setVisible(False)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.mining_pill)
        card.add_layout(header)
        self.block_row = KeyValueRow("Блок", "-")
        self.headers_row = KeyValueRow("Заголовки", "-")
        self.connections_row = KeyValueRow("Соединения", "-")
        self.difficulty_row = KeyValueRow("Сложность", "-")
        self.version_row = KeyValueRow("Версия", "-")
        for row in (
            self.block_row,
            self.headers_row,
            self.connections_row,
            self.difficulty_row,
            self.version_row,
        ):
            card.add(row)
        self.sync_label = QLabel("Синхронизация: -")
        self.sync_label.setObjectName("HintText")
        card.add(self.sync_label)
        self.sync_bar = QProgressBar()
        self.sync_bar.setObjectName("LargeProgress")
        self.sync_bar.setTextVisible(False)
        self.sync_bar.setRange(0, 100)
        self.sync_bar.setValue(0)
        card.add(self.sync_bar)
        self.network_hint = QLabel("")
        self.network_hint.setObjectName("HintText")
        self.network_hint.setWordWrap(True)
        card.add(self.network_hint)
        card.add_stretch(1)
        return card

    def refresh(self) -> None:
        """Load balances, history, addresses and node status in one worker."""
        if not self.begin_refresh():
            return
        self._refresh_ok = False
        run_async(self._load, self._apply, self._on_error, self._on_done)

    def _load(self) -> dict:
        """Blocking loader executed in the thread pool."""
        utxos: list[Utxo] = self.service.list_unspent()
        transactions = self.service.list_transactions(count=500)
        addresses: list[AddressInfo] = self.service.list_addresses()
        if self.service.addresses_supported is False:
            addresses = derive_addresses(utxos, transactions)
        network = self.service.network_info()
        chain = self.service.chain_info()
        return {
            "utxos": utxos,
            "transactions": transactions,
            "addresses": addresses,
            "network": network,
            "chain": chain,
        }

    def _apply(self, payload: dict) -> None:
        """Render a loaded dashboard snapshot."""
        utxos = payload["utxos"]
        self._transactions = payload["transactions"]
        addresses = payload["addresses"]
        self._network = payload["network"]
        self._chain = payload["chain"]
        self._balance = balance_summary(
            utxos, self._transactions, addresses if addresses else None
        )
        self.balance_label.setText(format_nvc(self._balance.available))
        total_caption = f"Всего с ожидающими: {format_nvc(self._balance.total)}"
        self.hero_caption.setText(
            f"{total_caption}. Доступно к отправке: "
            f"{format_nvc(self._balance.spendable)}."
        )
        self.network_pill.set_text(
            "Тестовая сеть" if self._network.testnet else "Основная сеть"
        )
        self.network_pill.set_level("warning" if self._network.testnet else "success")
        pending_utxos = sum(1 for utxo in utxos if utxo.confirmations < 1)
        self.pending_card.set_value(format_amount(self._balance.pending))
        self.pending_card.set_caption(
            f"{pending_utxos} входов без подтверждений"
            if pending_utxos
            else "Нет неподтвержденных входов"
        )
        self.immature_card.set_value(format_amount(self._balance.immature))
        self.immature_card.set_caption("Награды, ожидающие созревания")
        self.addresses_card.set_value(format_int(self._balance.address_count))
        self.addresses_card.set_caption("Известные адреса кошелька")
        self.utxo_card.set_value(format_int(self._balance.utxo_count))
        self.utxo_card.set_caption("Неизрасходованные выходы")
        self._render_activity()
        self._render_distribution()
        self._render_recent()
        self._render_network()
        self._render_sparkline()
        self._refresh_ok = True

    def _on_error(self, error: BaseException) -> None:
        """Report a failed refresh."""
        self._refresh_ok = False
        self.fail(error)

    def _on_done(self) -> None:
        """Release the page refresh guard."""
        self.end_refresh(self._refresh_ok)

    def _render_recent(self) -> None:
        """Rebuild the six newest transaction rows."""
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        rows = sorted(
            (
                transaction
                for transaction in self._transactions
                if transaction.timestamp
            ),
            key=lambda transaction: transaction.timestamp,
            reverse=True,
        )[:6]
        self.recent_empty.setVisible(not rows)
        for transaction in rows:
            row = TransactionRow(transaction, self.tokens)
            row.clicked.connect(self.transactionSelected.emit)
            self.recent_layout.addWidget(row)

    def _render_activity(self) -> None:
        """Aggregate fourteen days of incoming and outgoing volume."""
        labels, received, sent = self._activity_series()
        self.activity_chart.set_tokens(self.tokens)
        self.activity_chart.plot_activity(labels, received, sent)

    def _render_distribution(self) -> None:
        """Draw the balance composition donut."""
        self.distribution_chart.set_tokens(self.tokens)
        self.distribution_chart.plot_distribution(
            [
                ("Доступно", float(self._balance.available)),
                ("В ожидании", float(self._balance.pending)),
                ("Не созрело", float(self._balance.immature)),
            ],
            [
                self.tokens.get("positive", "#4ED19E"),
                self.tokens.get("warning", "#F3C969"),
                self.tokens.get("faint", "#748094"),
            ],
            center_title="Всего",
            center_value=format_amount(self._balance.total),
        )

    def _render_network(self) -> None:
        """Fill node metrics and the synchronization bar."""
        network = self._network
        chain = self._chain
        if network is None:
            return
        self.block_row.set_value(format_int(network.blocks))
        self.headers_row.set_value(format_int(chain.headers) if chain else "-")
        self.connections_row.set_value(format_int(network.connections))
        self.difficulty_row.set_value(format_difficulty(network.difficulty))
        self.version_row.set_value(str(network.version or "-"))
        progress = float(chain.progress_percent) if chain else 100.0
        self.sync_bar.setValue(max(0, min(100, int(progress))))
        self.sync_label.setText(f"Синхронизация: {format_percent(progress / 100.0)}")
        self.mining_pill.setVisible(network.mining)
        hints = []
        if network.warning:
            hints.append(network.warning)
        if network.errors:
            hints.append(network.errors)
        if chain and not chain.synced:
            hints.append("Узел догоняет цепочку, баланс может быть неполным.")
        if not network.connections:
            hints.append("Нет входящих соединений. Проверьте сеть и порт демона.")
        self.network_hint.setText(" ".join(hints))

    def _render_sparkline(self) -> None:
        """Color the sparkline with the current accent."""
        self.hero_spark.set_values(
            self._balance_series(), self.tokens.get("accent", "#FF8A3D")
        )

    def _activity_series(self) -> tuple[list[str], list[float], list[float]]:
        """Return labels and fourteen day buckets."""
        today = date.today()
        start = today - timedelta(days=13)
        buckets: dict[date, list[float]] = {
            start + timedelta(days=offset): [0.0, 0.0] for offset in range(14)
        }
        for transaction in self._transactions:
            if not transaction.timestamp:
                continue
            day = datetime.fromtimestamp(transaction.timestamp).date()
            if day not in buckets:
                continue
            value = float(transaction.amount)
            if value >= 0:
                buckets[day][0] += value
            else:
                buckets[day][1] += abs(value)
        labels = [day.strftime("%d.%m") for day in buckets]
        received = [bucket[0] for bucket in buckets.values()]
        sent = [bucket[1] for bucket in buckets.values()]
        return labels, received, sent

    def _balance_series(self) -> list[float]:
        """Reconstruct a rough fourteen day total balance trend."""
        if not self._transactions:
            return [float(self._balance.total)] * 14
        today = date.today()
        start = today - timedelta(days=13)
        daily_net: dict[date, Decimal] = {}
        for transaction in self._transactions:
            if not transaction.timestamp:
                continue
            day = datetime.fromtimestamp(transaction.timestamp).date()
            if start <= day <= today:
                daily_net[day] = daily_net.get(day, Decimal("0")) + transaction.amount
        running = float(self._balance.total)
        reversed_values: list[float] = []
        for offset in range(14):
            day = today - timedelta(days=offset)
            reversed_values.append(max(0.0, running))
            running -= float(daily_net.get(day, Decimal("0")))
        return list(reversed(reversed_values))

    def apply_theme(self) -> None:
        """Refresh chart colors and icons after a theme change."""
        tokens = self.tokens
        self.hero_spark.set_values(
            self._balance_series(), tokens.get("accent", "#FF8A3D")
        )
        self.activity_chart.set_tokens(tokens)
        self.distribution_chart.set_tokens(tokens)
        for card, icon_name, token_name in (
            (self.pending_card, "clock", "warning"),
            (self.immature_card, "lock", "warning"),
            (self.addresses_card, "wallet", "info"),
            (self.utxo_card, "coins", "accent"),
        ):
            card.set_icon(
                icon_name, tokens.get(token_name, tokens.get("muted", "#A7B1C2"))
            )
        self._render_activity()
        self._render_distribution()
        self._render_recent()
