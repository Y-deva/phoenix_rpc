"""Analytics page powered by matplotlib."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from ...core.errors import humanize_error
from ...core.formatting import format_nvc, shorten_address
from ...core.tasks import run_async
from ...rpc.models import BalanceSummary, Transaction
from ...rpc.service import balance_summary
from ..widgets.card import Card, Pill, StatCard
from ..widgets.chart import ChartPanel
from ..widgets.fields import IconButton, SegmentedControl
from ..widgets.progress import Spinner
from .base import ScrollPage


class AnalyticsPage(ScrollPage):
    """Visual analysis of flows, balances and counterparties."""

    page_id = "analytics"
    page_title = "Аналитика"
    page_subtitle = "Динамика баланса, структура средств и активность"
    auto_refresh = False

    def __init__(self, context: Any, parent: QWidget | None = None) -> None:
        """Initialize the AnalyticsPage instance."""
        super().__init__(context, parent)
        self._transactions: list[Transaction] = []
        self._summary = BalanceSummary()
        self._has_data = False
        self._build()
        self.apply_theme()

    def _build(self) -> None:
        """Create the period switcher, metrics and chart grid."""
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)
        title = QLabel("Период анализа")
        title.setObjectName("SectionTitle")
        self.period_control = SegmentedControl()
        for days in (7, 30, 90, 365):
            self.period_control.add_segment(str(days), f"{days} дней")
        self.period_control.set_value(str(self.settings.chart_days))
        self.period_control.valueChanged.connect(self._on_period_changed)
        self.spinner = Spinner(size=18)
        self.refresh_button = IconButton(
            "refresh",
            self.tokens.get("muted", "#A7B1C2"),
            "Пересчитать графики (F5)",
            34,
        )
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(title)
        toolbar.addWidget(self.period_control)
        toolbar.addStretch(1)
        toolbar.addWidget(self.spinner)
        toolbar.addWidget(self.refresh_button)
        self.body.addLayout(toolbar)

        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.balance_card = StatCard(
            "Текущий баланс", "0", "Все подтвержденные средства", "wallet"
        )
        self.received_card = StatCard("Получено", "0", "За выбранный период", "receive")
        self.sent_card = StatCard("Отправлено", "0", "За выбранный период", "send")
        self.fees_card = StatCard(
            "Комиссии", "0", "За выбранный период", "transactions"
        )
        for card in (
            self.balance_card,
            self.received_card,
            self.sent_card,
            self.fees_card,
        ):
            metrics.addWidget(card, 1)
        self.body.addLayout(metrics)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.activity_chart = ChartPanel(
            "Объем операций", "Поступления и отправки по дням"
        )
        self.flow_chart = ChartPanel(
            "Накопленный поток", "Суммарное изменение баланса за период"
        )
        self.distribution_chart = ChartPanel(
            "Структура средств", "Доступные, ожидающие и незрелые монеты"
        )
        self.fee_chart = ChartPanel("Комиссии", "Расходы на комиссии по дням")
        grid.addWidget(self.activity_chart, 0, 0)
        grid.addWidget(self.flow_chart, 0, 1)
        grid.addWidget(self.distribution_chart, 1, 0)
        grid.addWidget(self.fee_chart, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        self.addresses_chart = ChartPanel(
            "Крупнейшие контрагенты",
            "Адреса с наибольшим оборотом в загруженной истории",
        )
        self.body.addWidget(self.addresses_chart)

        insight = Card(padding=12)
        insight_row = QHBoxLayout()
        insight_row.setSpacing(8)
        self.insight_pill = Pill("История загружается", "neutral")
        self.insight_label = QLabel("")
        self.insight_label.setObjectName("Muted")
        self.insight_label.setWordWrap(True)
        insight_row.addWidget(self.insight_pill)
        insight_row.addWidget(self.insight_label, 1)
        insight.add_layout(insight_row)
        self.body.addWidget(insight)
        self.add_stretch()

    def refresh(self) -> None:
        """Reload history and balance used by all charts."""
        if self._refreshing:
            return
        self._refreshing = True
        self.busyChanged.emit(True)
        self.spinner.start()
        self.refresh_button.setEnabled(False)
        run_async(self._fetch, self._on_loaded, self._on_failed, self._on_finished)

    def _fetch(self) -> tuple[list[Transaction], BalanceSummary]:
        """Fetch up to 1000 history entries and the current UTXO snapshot."""
        transactions = self.service.list_transactions(count=1000)
        utxos = self.service.list_unspent()
        summary = balance_summary(utxos, transactions)
        return transactions, summary

    def _on_loaded(self, payload: object) -> None:
        """Store data and redraw all charts."""
        transactions, summary = payload
        self._transactions = list(transactions)
        self._summary = summary
        self._has_data = True
        self._render()

    def _on_failed(self, error: object) -> None:
        """Report analytics load failure."""
        self.errorRaised.emit(humanize_error(error))

    def _on_finished(self) -> None:
        """Stop the loading indicator."""
        self._refreshing = False
        self.busyChanged.emit(False)
        self.spinner.stop()
        self.refresh_button.setEnabled(True)

    def _on_period_changed(self, value: str) -> None:
        """Persist the selected period and reload."""
        try:
            self.settings.chart_days = int(value)
        except (TypeError, ValueError):
            return
        self.refresh()

    def _buckets(
        self,
    ) -> tuple[list[str], list[float], list[float], list[float], list[float]]:
        """Aggregate transactions into daily buckets for the selected period."""
        days = self.settings.chart_days
        end = date.today()
        start = end - timedelta(days=days - 1)
        labels = [
            (start + timedelta(days=index)).strftime("%d.%m") for index in range(days)
        ]
        received = [0.0] * days
        sent = [0.0] * days
        fees = [0.0] * days
        for transaction in self._transactions:
            if not transaction.timestamp:
                continue
            moment = datetime.fromtimestamp(transaction.timestamp).date()
            index = (moment - start).days
            if index < 0 or index >= days:
                continue
            amount = float(transaction.amount)
            if amount >= 0:
                received[index] += amount
            else:
                sent[index] += abs(amount)
            fees[index] += float(transaction.fee)
        cumulative: list[float] = []
        running = 0.0
        for index in range(days):
            running += received[index] - sent[index]
            cumulative.append(running)
        return labels, received, sent, fees, cumulative

    def _render(self) -> None:
        """Draw all panels from the current data and theme."""
        tokens = dict(self.tokens)
        for panel in (
            self.activity_chart,
            self.flow_chart,
            self.distribution_chart,
            self.fee_chart,
            self.addresses_chart,
        ):
            panel.set_tokens(tokens)
        labels, received, sent, fees, cumulative = self._buckets()
        total_received = sum(received)
        total_sent = sum(sent)
        total_fees = sum(fees)
        self.balance_card.set_value(f"{format_nvc(self._summary.total)}")
        self.balance_card.set_caption(f"Доступно {format_nvc(self._summary.available)}")
        self.received_card.set_value(f"{format_nvc(total_received)}")
        self.sent_card.set_value(f"{format_nvc(total_sent)}")
        self.fees_card.set_value(f"{format_nvc(total_fees)}")

        if total_received or total_sent:
            self.activity_chart.plot_activity(labels, received, sent)
            self.flow_chart.plot_balance(labels, cumulative, unit="NVC")
        else:
            self.activity_chart.show_message("Нет операций за выбранный период")
            self.flow_chart.show_message("Недостаточно данных для динамики")

        distribution = [
            ("Доступно", float(self._summary.available)),
            ("В ожидании", float(self._summary.pending)),
            ("Незрелые", float(self._summary.immature)),
        ]
        colors = [
            self.tokens.get("positive", "#4ED19E"),
            self.tokens.get("warning", "#F3C969"),
            self.tokens.get("muted", "#8B97AA"),
        ]
        self.distribution_chart.plot_distribution(
            distribution,
            colors,
            center_title="Всего",
            center_value=format_nvc(self._summary.total),
        )
        if total_fees:
            self.fee_chart.plot_fees(labels, fees)
        else:
            self.fee_chart.show_message("Комиссии не начислялись")

        addresses: dict[str, float] = {}
        for transaction in self._transactions:
            if not transaction.address:
                continue
            addresses[transaction.address] = addresses.get(
                transaction.address, 0.0
            ) + abs(float(transaction.amount))
        top = sorted(addresses.items(), key=lambda item: item[1], reverse=True)[:8]
        top_short = [(shorten_address(address, 6, 4), value) for address, value in top]
        if top_short:
            self.addresses_chart.plot_top_addresses(
                top_short, self.tokens.get("accent", "#FF8A3D")
            )
        else:
            self.addresses_chart.show_message("Адреса в истории не найдены")

        count = len(
            [
                transaction
                for transaction in self._transactions
                if transaction.timestamp
                and (
                    datetime.fromtimestamp(transaction.timestamp).date()
                    >= date.today() - timedelta(days=self.settings.chart_days - 1)
                )
            ]
        )
        self.insight_pill.set_text(f"Операций: {count}")
        self.insight_pill.set_level("accent" if count else "neutral")
        if count:
            average = (total_received + total_sent) / count
            self.insight_label.setText(
                f"Средний оборот одной операции: {format_nvc(average)}. "
                "Комиссии составляют "
                f"{self._share(total_fees, total_received + total_sent)} "
                "от общего оборота."
            )
        else:
            self.insight_label.setText(
                "Выберите более длинный период или выполните операцию, "
                "чтобы увидеть закономерности."
            )

    @staticmethod
    def _share(part: float, whole: float) -> str:
        """Return a small percentage string without a division by zero."""
        if whole <= 0:
            return "0 %"
        return f"{part / whole * 100:.2f} %"

    def apply_theme(self) -> None:
        """Update chart palette and repaint existing data."""
        self.refresh_button.set_icon_name("refresh")
        if self._has_data:
            self._render()
