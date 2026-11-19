"""Central diagnostics and control for the local daemon and proxy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.proxy import STATE_RUNNING, STATE_STARTING
from ...core.tasks import run_async
from ..widgets.card import Card, Pill, SectionHeader
from ..widgets.icons import icon
from ..widgets.theme import ThemeManager

if TYPE_CHECKING:
    from ..main_window import MainWindow


class ConnectionDialog(QDialog):
    """Show service health, start/stop actions and live backend output."""

    def __init__(self, host: "MainWindow", parent: QWidget | None = None) -> None:
        """Build the server control center for the given main window."""
        super().__init__(parent)
        self.host = host
        self.setWindowTitle("Серверы и подключение")
        self.setModal(False)
        self.resize(780, 640)
        self.setMinimumSize(680, 540)
        self._build()
        self._connect_processes()
        self._network_task = False
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self._network_timer = QTimer(self)
        self._network_timer.setInterval(5000)
        self._network_timer.timeout.connect(self._refresh_network)
        self._network_timer.start()
        self.refresh()
        QTimer.singleShot(200, self._refresh_network)

    def showEvent(self, event: object) -> None:
        """Refresh network statistics once the sheet is actually visible."""
        super().showEvent(event)
        QTimer.singleShot(250, self._refresh_network)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        """Create the dialog layout."""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(14)

        heading = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(
            icon("server", self._tokens().get("accent", "#FF8A3D"), 26).pixmap(26, 26)
        )
        heading.addWidget(badge)
        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("Серверы и подключение")
        title.setObjectName("DialogTitle")
        subtitle = QLabel(
            "Состояние локального узла и прокси, запуск и диагностика без терминала."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(subtitle)
        heading.addLayout(text, 1)
        root.addLayout(heading)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        daemon_card, self.daemon_pill, self.daemon_detail = self._service_card(
            "Узел Novacoin", "server"
        )
        self.daemon_start = self._button("Запустить", "GhostButton")
        self.daemon_start.clicked.connect(self.host.start_daemon_backend)
        self.daemon_restart = self._button("Перезапустить", "GhostButton")
        self.daemon_restart.clicked.connect(self.host.restart_daemon_backend)
        self.daemon_stop = self._button("Остановить", "GhostButton")
        self.daemon_stop.setToolTip("Остановить узел после подтверждения")
        self.daemon_stop.clicked.connect(self.host.stop_daemon_backend)
        daemon_actions = QHBoxLayout()
        daemon_actions.addWidget(self.daemon_start)
        daemon_actions.addWidget(self.daemon_stop)
        daemon_actions.addWidget(self.daemon_restart)
        daemon_actions.addStretch(1)
        daemon_card.layout().addLayout(daemon_actions)
        cards.addWidget(daemon_card, 1)

        proxy_card, self.proxy_pill, self.proxy_detail = self._service_card(
            "Локальный прокси", "link"
        )
        proxy_actions = QHBoxLayout()
        self.proxy_start = self._button("Запустить", "GhostButton")
        self.proxy_start.clicked.connect(self.host.start_proxy_backend)
        self.proxy_stop = self._button("Остановить", "GhostButton")
        self.proxy_stop.clicked.connect(self.host.stop_proxy_backend)
        self.proxy_restart = self._button("Перезапустить", "GhostButton")
        self.proxy_restart.clicked.connect(self.host.restart_proxy_backend)
        for button in (self.proxy_start, self.proxy_stop, self.proxy_restart):
            proxy_actions.addWidget(button)
        proxy_actions.addStretch(1)
        proxy_card.layout().addLayout(proxy_actions)
        cards.addWidget(proxy_card, 1)
        root.addLayout(cards)

        network_card = Card(padding=12, spacing=6)
        network_header = SectionHeader(
            "Состояние сети",
            "Краткая сводка узла; подробные команды доступны в консоли.",
        )
        network_card.layout().addWidget(network_header)
        network_row = QHBoxLayout()
        network_row.setSpacing(18)
        self.network_values: dict[str, QLabel] = {}
        for key, caption in (
            ("blocks", "Высота"),
            ("connections", "Соединения"),
            ("difficulty", "Сложность"),
            ("hashrate", "Хешрейт"),
            ("mining", "Майнинг"),
        ):
            column = QVBoxLayout()
            column.setSpacing(1)
            name = QLabel(caption)
            name.setObjectName("HintText")
            value = QLabel("-")
            value.setObjectName("StatValue")
            column.addWidget(name)
            column.addWidget(value)
            self.network_values[key] = value
            network_row.addLayout(column)
        network_row.addStretch(1)
        network_card.layout().addLayout(network_row)
        root.addWidget(network_card)

        log_card = Card()
        log_header = SectionHeader(
            "Журнал процессов",
            "Последние строки вывода. Пароли и ключи сюда не записываются.",
        )
        log_card.layout().addWidget(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(150)
        self.log.setMaximumBlockCount(1500)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setObjectName("ConsoleOutput")
        self.log.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        log_card.layout().addWidget(self.log, 1)
        root.addWidget(log_card, 1)

        footer = QHBoxLayout()
        self.start_all = self._button("Запустить всё", "AccentButton")
        self.start_all.setToolTip("Запустить узел и прокси, если они еще не работают")
        self.start_all.clicked.connect(self._start_all)
        self.check = self._button("Проверить связь", "GhostButton")
        self.check.setToolTip("Повторить проверку RPC через локальный прокси")
        self.check.clicked.connect(self.host.check_connection_now)
        self.copy = self._button("Скопировать диагностику", "GhostButton")
        self.copy.setToolTip("Скопировать состояния и журнал в буфер обмена")
        self.copy.clicked.connect(self._copy_diagnostics)
        self.close_button = self._button("Закрыть", "GhostButton")
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.start_all)
        footer.addWidget(self.check)
        footer.addStretch(1)
        footer.addWidget(self.copy)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self._append("Диалог диагностики открыт.")
        self._append(self._collect_diagnostics())

    def _service_card(self, title: str, icon_name: str) -> tuple[Card, Pill, QLabel]:
        """Create one service status card and return its updateable children."""
        card = Card()
        header = QHBoxLayout()
        badge = QLabel()
        badge.setPixmap(
            icon(icon_name, self._tokens().get("accent", "#FF8A3D"), 20).pixmap(20, 20)
        )
        header.addWidget(badge)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        header.addWidget(label)
        header.addStretch(1)
        pill = Pill("Проверка", "neutral")
        header.addWidget(pill)
        card.layout().addLayout(header)
        detail = QLabel("")
        detail.setObjectName("Muted")
        detail.setWordWrap(True)
        card.layout().addWidget(detail)
        card.layout().addStretch(1)
        return card, pill, detail

    @staticmethod
    def _button(text: str, object_name: str) -> QPushButton:
        """Create a themed action button."""
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _tokens(self) -> dict[str, str]:
        """Return current theme tokens."""
        manager = getattr(self.host, "themes", None)
        if isinstance(manager, ThemeManager):
            return manager.tokens
        return {}

    def _connect_processes(self) -> None:
        """Stream live output from both backend processes."""
        for process in (
            self.host.daemon_process,
            self.host.proxy_process,
        ):
            if process is None:
                continue
            process.output.connect(self._append)
            process.stateChanged.connect(self.refresh)
            process.failed.connect(lambda message: self._append(f"ОШИБКА: {message}"))

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Refresh status cards and action availability."""
        daemon = self.host.daemon_process
        proxy = self.host.proxy_process
        if daemon is not None and daemon.state != STATE_RUNNING and self.host.online:
            self.daemon_pill.set_text(self._tr("Подключен"))
            self.daemon_pill.set_level("success")
            self.daemon_detail.setText(
                self._tr("RPC отвечает; процесс запущен вне этого окна.")
            )
            self.daemon_start.setEnabled(False)
            self.daemon_restart.setEnabled(False)
            self.daemon_stop.setEnabled(True)
        elif daemon is not None:
            text, level = self._state_presentation(daemon.state)
            self.daemon_pill.set_text(text)
            self.daemon_pill.set_level(level)
            owner = self._owner_text(daemon)
            details = [owner]
            if daemon.binary is not None:
                details.append(str(daemon.binary))
            self.daemon_detail.setText("\n".join(details))
            self.daemon_start.setEnabled(
                daemon.state not in {STATE_STARTING, STATE_RUNNING}
            )
            self.daemon_restart.setEnabled(daemon.state == STATE_RUNNING)
            self.daemon_stop.setEnabled(
                daemon.state == STATE_RUNNING and (daemon.owned or self.host.online)
            )
        else:
            self.daemon_pill.set_text("Демо-режим")
            self.daemon_pill.set_level("accent")
            self.daemon_detail.setText(
                self._tr("Локальные данные, процессы не используются")
            )
            self.daemon_start.setEnabled(False)
            self.daemon_restart.setEnabled(False)
            self.daemon_stop.setEnabled(False)

        if proxy is not None:
            text, level = self._state_presentation(proxy.state)
            self.proxy_pill.set_text(text)
            self.proxy_pill.set_level(level)
            endpoint, _, _ = self.host.settings.effective_proxy()
            owner = self._owner_text(proxy)
            self.proxy_detail.setText(f"{endpoint}\n{owner}")
            self.proxy_start.setEnabled(
                proxy.state not in {STATE_STARTING, STATE_RUNNING}
            )
            self.proxy_stop.setEnabled(proxy.owned and proxy.state == STATE_RUNNING)
            self.proxy_restart.setEnabled(
                proxy.state in {STATE_STARTING, STATE_RUNNING, "failed"}
            )
        else:
            self.proxy_pill.set_text("Демо-режим")
            self.proxy_pill.set_level("accent")
            self.proxy_detail.setText(self._tr("В демо-режиме прокси не запускается"))
            self.proxy_start.setEnabled(False)
            self.proxy_stop.setEnabled(False)
            self.proxy_restart.setEnabled(False)

        daemon_external = bool(
            daemon is not None and daemon.state != STATE_RUNNING and self.host.online
        )
        any_stopped = bool(
            (
                daemon is not None
                and daemon.state != STATE_RUNNING
                and not daemon_external
            )
            or (proxy is not None and proxy.state != STATE_RUNNING)
        )
        self.start_all.setEnabled(any_stopped)

    def _tr(self, text: str) -> str:
        """Translate a dynamic string through the shared manager."""
        manager = getattr(self.host, "translations", None)
        return manager.tr(text) if manager is not None else text

    def _owner_text(self, process: object) -> str:
        """Describe whether a running backend belongs to this window."""
        if getattr(process, "state", "") == STATE_RUNNING:
            if getattr(process, "owned", False):
                return self._tr("запущен этим окном")
            return self._tr("работает вне этого окна")
        return self._tr("внешний процесс или не запущен")

    def _state_presentation(self, state: str) -> tuple[str, str]:
        """Translate backend states into pill text and semantic level."""
        table = {
            "stopped": ("Остановлен", "neutral"),
            "starting": ("Запуск", "warning"),
            "running": ("Работает", "success"),
            "stopping": ("Остановка", "warning"),
            "missing": ("Не найден", "danger"),
            "failed": ("Ошибка", "danger"),
        }
        text, level = table.get(state, (state, "neutral"))
        return self._tr(text), level

    def _refresh_network(self) -> None:
        """Fetch node statistics without blocking the dialog."""
        if self._network_task or not self.isVisible():
            return
        if getattr(self.host, "demo", False):
            self._set_network({})
            return
        service = getattr(self.host, "service", None)
        if service is None:
            return
        self._network_task = True

        def done(snapshot: object) -> None:
            self._network_task = False
            if self.isVisible() and isinstance(snapshot, dict):
                self._set_network(snapshot)

        def failed(_error: object) -> None:
            self._network_task = False

        run_async(
            service.node_snapshot,
            done,
            failed,
            lambda: setattr(self, "_network_task", False),
        )

    def _set_network(self, snapshot: dict[str, object]) -> None:
        """Update the compact node summary."""
        if not snapshot:
            for value in self.network_values.values():
                value.setText("-")
            return
        blocks = snapshot.get("blocks")
        connections = snapshot.get("connections")
        difficulty = snapshot.get("difficulty")
        hashrate = snapshot.get("hashrate")
        self.network_values["blocks"].setText(
            str(blocks) if blocks is not None else "-"
        )
        self.network_values["connections"].setText(
            str(connections) if connections is not None else "-"
        )
        try:
            difficulty_text = (
                f"{float(difficulty):.6g}" if difficulty is not None else "-"
            )
        except (TypeError, ValueError):
            difficulty_text = "-"
        self.network_values["difficulty"].setText(difficulty_text)
        try:
            hashrate_text = f"{float(hashrate) / 1e9:.2f} GH/s" if hashrate else "-"
        except (TypeError, ValueError):
            hashrate_text = "-"
        self.network_values["hashrate"].setText(hashrate_text)
        self.network_values["mining"].setText(
            self._tr("Да") if snapshot.get("mining") else self._tr("Нет")
        )

    def _append(self, text: str) -> None:
        """Append process output without stealing focus."""
        clean = text.rstrip()
        if not clean:
            return
        self.log.appendPlainText(clean)
        bar = self.log.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _start_all(self) -> None:
        """Start both services through the main window controller."""
        self._append("Запуск всех серверных компонентов...")
        self.host.start_all_backends()
        QTimer.singleShot(300, self.refresh)

    def _copy_diagnostics(self) -> None:
        """Copy a safe diagnostic report to the clipboard."""
        QApplication.clipboard().setText(self._collect_diagnostics())
        self._append("Диагностика скопирована в буфер обмена.")

    def _collect_diagnostics(self) -> str:
        """Return a compact report that excludes secrets."""
        daemon = self.host.daemon_process
        proxy = self.host.proxy_process
        endpoint, user, _ = self.host.settings.effective_proxy()
        lines = [
            "Phoenix/Novacoin connection diagnostics",
            f"daemon state: {getattr(daemon, 'state', 'n/a')}",
            f"daemon owned: {getattr(daemon, 'owned', 'n/a')}",
            f"proxy state: {getattr(proxy, 'state', 'n/a')}",
            f"proxy owned: {getattr(proxy, 'owned', 'n/a')}",
            f"proxy endpoint: {endpoint}",
            f"proxy user: {user}",
            "",
            "daemon log:",
            getattr(daemon, "recent_output", "")[-4000:],
            "",
            "proxy log:",
            getattr(proxy, "recent_output", "")[-4000:],
        ]
        return "\n".join(lines)
