"""Main window: navigation shell, daemon lifecycle and sync indicators."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..core.config import ProjectConfig
from ..core.daemon import STATE_RUNNING, DaemonProcess
from ..core.errors import humanize_error
from ..core.formatting import format_int, format_percent
from ..core.media import MediaBackdrop
from ..core.sounds import SoundPlayer
from ..core.sync import SyncStatus, build_sync_status, load_parser_progress
from ..rpc.client import RPCClient
from ..rpc.service import WalletService
from ..settings import Settings
from .dialogs.shortcuts import ShortcutsDialog
from .dialogs.tx_details import TxDetailsDialog
from .pages.analytics import AnalyticsPage
from .pages.base import PageContext
from .pages.coins import CoinsPage
from .pages.console import ConsolePage
from .pages.overview import OverviewPage
from .pages.receive import ReceivePage
from .pages.send import SendPage
from .pages.settings import SettingsPage
from .pages.transactions import TransactionsPage
from .widgets.card import Pill
from .widgets.animations import Motion
from .widgets.icons import app_icon, brand_logo, brand_mark, icon, nav_icon
from .widgets.progress import Spinner
from .widgets.theme import ThemeManager
from .widgets.toast import ToastManager

PAGE_CLASSES = (
    OverviewPage,
    SendPage,
    ReceivePage,
    TransactionsPage,
    CoinsPage,
    AnalyticsPage,
    ConsolePage,
    SettingsPage,
)

NAV_META: tuple[tuple[str, str, str], ...] = (
    ("overview", "Обзор", "home"),
    ("send", "Отправить", "send"),
    ("receive", "Получить", "receive"),
    ("transactions", "История", "transactions"),
    ("coins", "Монеты", "coins"),
    ("analytics", "Аналитика", "chart"),
    ("console", "Консоль", "terminal"),
    ("settings", "Настройки", "settings"),
)


class MainWindow(QMainWindow):
    """Coordinate pages, the background daemon and the local RPC proxy."""

    closing = pyqtSignal()

    def __init__(
        self,
        project: ProjectConfig,
        settings: Settings,
        service: WalletService,
        themes: ThemeManager,
        demo: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the MainWindow instance."""
        super().__init__(parent)
        self.project = project
        self.settings = settings
        self.service = service
        self.themes = themes
        self.demo = demo
        self.context = PageContext(
            service=service, settings=settings, themes=themes, config=project
        )
        self._online = False
        self._checking = False
        self._busy_count = 0
        self._really_quit = False
        self._daemon: DaemonProcess | None = None
        self._sync: SyncStatus | None = None
        self._pages: dict[str, Any] = {}
        self._sounds = SoundPlayer(settings, self)
        self._motion: Motion | None = None
        self._intro_played = False
        self._nav_buttons: dict[str, QPushButton] = {}
        self._setup_window()
        self._motion = Motion(settings, self)
        self._build_shell()
        self._build_pages()
        self._build_daemon()
        self._bind_shortcuts()
        self._start_timers()
        self.themes.changed.connect(self._on_theme_changed)
        self._on_theme_changed(self.themes.theme)
        self._restore_geometry()
        QTimer.singleShot(250, self._check_connection)
        QTimer.singleShot(400, self._maybe_start_daemon)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _setup_window(self) -> None:
        """Set titles, size constraints and the central backdrop."""
        network = self._network_caption()
        self.setWindowTitle(f"{__app_name__} - {network}")
        self.setMinimumSize(1120, 720)
        self.resize(1360, 880)
        self.setAcceptDrops(True)
        self.backdrop = MediaBackdrop(self.settings, self.themes.theme, self)
        self.backdrop.setObjectName("RootBackdrop")
        self.backdrop.mediaError.connect(
            lambda message: self.toast.error(message, title="Медиафон")
        )
        self.backdrop.mediaDropped.connect(self._on_media_dropped)
        self.setCentralWidget(self.backdrop)
        self.toast = ToastManager(
            self.backdrop,
            animations=bool(self.settings.animations),
        )

    def _build_shell(self) -> None:
        """Create sidebar, header, page stack and footer."""
        shell = QHBoxLayout(self.backdrop)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())

        content = QWidget()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_header())
        content_layout.addWidget(self._build_banner())

        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        content_layout.addWidget(self.stack, 1)
        content_layout.addWidget(self._build_footer())
        shell.addWidget(content, 1)

    def _build_sidebar(self) -> QWidget:
        """Create brand, navigation groups and daemon state."""
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(236)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(6)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        self.brand_label = QLabel()
        self.brand_label.setFixedSize(38, 38)
        self.brand_label.setToolTip("Phoenix Wallet")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_name = QLabel("Phoenix")
        brand_name.setObjectName("SectionTitle")
        self.network_name = QLabel(self._network_caption())
        self.network_name.setObjectName("Faint")
        brand_text.addWidget(brand_name)
        brand_text.addWidget(self.network_name)
        brand_row.addWidget(self.brand_label)
        brand_row.addLayout(brand_text, 1)
        layout.addLayout(brand_row)
        layout.addSpacing(16)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self._add_nav_section(layout, "КОШЕЛЕК", NAV_META[:5])
        layout.addSpacing(10)
        self._add_nav_section(layout, "ИНСТРУМЕНТЫ", NAV_META[5:])
        layout.addStretch(1)

        self.daemon_pill = Pill("Демон не запущен", "neutral")
        self.daemon_pill.setToolTip("Состояние процесса novacoind")
        layout.addWidget(self.daemon_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self.version_label = QLabel(f"Версия {__version__}")
        self.version_label.setObjectName("Faint")
        layout.addWidget(self.version_label)
        return sidebar

    def _add_nav_section(
        self, layout: QVBoxLayout, title: str, entries: tuple[tuple[str, str, str], ...]
    ) -> None:
        """Create a labelled block of navigation buttons."""
        caption = QLabel(title)
        caption.setObjectName("Faint")
        caption.setContentsMargins(8, 0, 0, 2)
        layout.addWidget(caption)
        for page_id, text, icon_name in entries:
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIconSize(QSize(18, 18))
            button.setToolTip(f"Перейти: {text} (Alt+{len(self._nav_buttons) + 1})")
            button.clicked.connect(
                lambda _checked=False, key=page_id: self.navigate(key)
            )
            self.nav_group.addButton(button)
            self._nav_buttons[page_id] = button
            layout.addWidget(button)

    def _build_header(self) -> QWidget:
        """Create title row with connection, sync and quick actions."""
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(74)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 12, 20, 12)
        layout.setSpacing(10)
        text_column = QVBoxLayout()
        text_column.setSpacing(1)
        self.title_label = QLabel("Обзор")
        self.title_label.setObjectName("PageTitle")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("PageSubtitle")
        text_column.addWidget(self.title_label)
        text_column.addWidget(self.subtitle_label)
        layout.addLayout(text_column, 1)

        self.network_pill = Pill("Проверка связи", "neutral")
        self.network_pill.setToolTip("Состояние соединения с локальным прокси")
        layout.addWidget(self.network_pill)
        self.sync_pill = Pill("Синхронизация", "neutral")
        self.sync_pill.setToolTip("Высота блоков и готовность парсера UTXO")
        layout.addWidget(self.sync_pill)
        self.header_spinner = Spinner(size=16)
        layout.addWidget(self.header_spinner)
        self.refresh_button = QPushButton()
        self.refresh_button.setObjectName("IconButton")
        self.refresh_button.setFixedSize(34, 34)
        self.refresh_button.setToolTip("Обновить данные (Ctrl+R)")
        self.refresh_button.clicked.connect(self.refresh_current)
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("IconButton")
        self.theme_button.setFixedSize(34, 34)
        self.theme_button.setToolTip("Переключить темную и светлую тему (Ctrl+Shift+T)")
        self.theme_button.clicked.connect(self.themes.toggle_light)
        self.settings_button = QPushButton()
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setFixedSize(34, 34)
        self.settings_button.setToolTip("Открыть настройки (Ctrl+,)")
        self.settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.settings_button)
        return header

    def _build_banner(self) -> QWidget:
        """Create a dismissible banner used for connection problems."""
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        self.banner.setVisible(False)
        layout = QHBoxLayout(self.banner)
        layout.setContentsMargins(18, 10, 14, 10)
        layout.setSpacing(10)
        self.banner_icon = QLabel()
        self.banner_icon.setFixedSize(18, 18)
        self.banner_label = QLabel("")
        self.banner_label.setWordWrap(True)
        self.banner_label.setObjectName("Muted")
        layout.addWidget(self.banner_icon)
        layout.addWidget(self.banner_label, 1)
        self.retry_button = QPushButton("Повторить")
        self.retry_button.setObjectName("GhostButton")
        self.retry_button.setToolTip("Повторить проверку прокси")
        self.retry_button.clicked.connect(lambda: self._check_connection(manual=True))
        self.banner_settings = QPushButton("Настройки")
        self.banner_settings.setObjectName("GhostButton")
        self.banner_settings.setToolTip("Открыть параметры подключения")
        self.banner_settings.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(self.retry_button)
        layout.addWidget(self.banner_settings)
        return self.banner

    def _build_footer(self) -> QWidget:
        """Create the compact status strip."""
        footer = QFrame()
        footer.setObjectName("StatusBar")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 6, 18, 6)
        layout.setSpacing(8)
        self.footer_spinner = Spinner(size=12)
        self.footer_status = QLabel("Готово")
        self.footer_status.setObjectName("Muted")
        self.footer_parser = QLabel("Парсер: нет данных")
        self.footer_parser.setObjectName("Faint")
        self.footer_sync = QLabel("")
        self.footer_sync.setObjectName("Faint")
        layout.addWidget(self.footer_spinner)
        layout.addWidget(self.footer_status, 1)
        layout.addWidget(self.footer_parser)
        layout.addWidget(self.footer_sync)
        return footer

    def _build_pages(self) -> None:
        """Instantiate every page and connect its shared signals."""
        for page_class in PAGE_CLASSES:
            page = page_class(self.context)
            self._pages[page.page_id] = page
            self.stack.addWidget(page)
            page.statusMessage.connect(self._on_page_status)
            page.errorRaised.connect(self._on_page_error)
            page.busyChanged.connect(self._on_page_busy)
            page.navigateRequested.connect(self.navigate)
            page.transactionSelected.connect(self._open_transaction)
        self._pages["coins"].sendRequested.connect(self._on_coins_send_requested)
        settings_page = self._pages["settings"]
        settings_page.connectionChanged.connect(self._on_connection_settings)
        settings_page.daemonRestartRequested.connect(self._restart_daemon)
        self.navigate(
            self.settings.last_page
            if self.settings.last_page in self._pages
            else "overview"
        )

    def _build_daemon(self) -> None:
        """Create the owned daemon process controller."""
        if self.demo:
            self.daemon_pill.set_text("Демо-режим")
            self.daemon_pill.set_level("accent")
            self._pages["settings"].set_daemon_status(
                "Демо-режим: novacoind не запускается",
                self.themes.tokens.get("accent", "#FF8A3D"),
            )
            return
        self._daemon = DaemonProcess(self.settings, self.project, self)
        self._daemon.stateChanged.connect(self._on_daemon_state)
        self._daemon.ready.connect(self._on_daemon_ready)
        self._daemon.failed.connect(self._on_daemon_failed)
        self._daemon.stopped.connect(lambda _code: self._check_connection())

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def navigate(self, page_id: str) -> None:
        """Show a page and update navigation, header and persistence."""
        page = self._pages.get(page_id)
        if page is None:
            return
        current = self.stack.currentWidget()
        if current is page:
            self.settings.set("behavior/last_page", page_id)
            return
        if current is not None and current is not page:
            current.deactivate()
        self.stack.setCurrentWidget(page)
        for key, button in self._nav_buttons.items():
            button.setChecked(key == page_id)
        self.title_label.setText(page.page_title)
        self.subtitle_label.setText(page.page_subtitle)
        self.subtitle_label.setVisible(bool(page.page_subtitle))
        self.settings.set("behavior/last_page", page_id)
        self._update_nav_icons()
        page.activate()
        if self._motion is not None:
            self._motion.page_in(page)

    @property
    def current_page(self) -> Any:
        """Return the page currently visible in the stack."""
        return self.stack.currentWidget()

    def refresh_current(self) -> None:
        """Refresh the active page and the connection state."""
        page = self.current_page
        if page is not None and hasattr(page, "refresh"):
            page.refresh()
        self._check_connection(manual=True)

    # ------------------------------------------------------------------
    # Connection and synchronization
    # ------------------------------------------------------------------
    def _network_caption(self) -> str:
        """Return the network label used in the title and sidebar."""
        if self.demo:
            return "Демо-сеть"
        return "Тестовая сеть" if self.project.testnet else "Основная сеть"

    def _check_connection(self, manual: bool = False) -> None:
        """Probe the local proxy without blocking the interface."""
        if self.demo:
            self._online = True
            self._checking = False
            self.banner.setVisible(False)
            self.network_pill.set_text("Демо-режим")
            self.network_pill.set_level("accent")
            self.network_pill.setToolTip(
                "Данные созданы локально, сеть не используется"
            )
            self.sync_pill.set_text("Демо")
            self.sync_pill.set_level("neutral")
            self.footer_status.setText("Демо-режим")
            self.footer_sync.setText("Сеть не используется")
            self.footer_parser.setText("Парсер: демо")
            page = self.current_page
            if page is not None:
                page.activate()
            return
        if self._checking:
            return
        self._checking = True
        if manual:
            self.footer_status.setText("Проверка соединения...")
        self.network_pill.set_text("Проверка связи")
        self.network_pill.set_level("neutral")
        from ..core.tasks import run_async

        run_async(
            self._probe_connection,
            self._on_connection_ok,
            lambda error: self._on_connection_error(error, manual),
            self._on_connection_done,
        )

    def _probe_connection(self) -> SyncStatus:
        """Fetch network and chain information in one background step."""
        network = self.service.network_info()
        chain = self.service.chain_info()
        return build_sync_status(network, chain, self.project)

    def _on_connection_ok(self, status: SyncStatus) -> None:
        """Mark online, update indicators and refresh stale content."""
        was_online = self._online
        self._online = True
        self._sync = status
        self.banner.setVisible(False)
        self.network_pill.set_text("В сети")
        self.network_pill.set_level("success")
        network_label = "Тестовая сеть" if status.network.testnet else "Основная сеть"
        self.network_pill.setToolTip(
            f"{network_label}, блок {format_int(status.network.blocks)}, "
            f"соединений {format_int(status.network.connections)}"
        )
        self.network_name.setText(network_label)
        self._apply_sync_status(status)
        self.footer_status.setText("Готово")
        if not was_online:
            page = self.current_page
            if page is not None and hasattr(page, "mark_stale"):
                page.mark_stale()
            QTimer.singleShot(0, self._activate_current)

    def _activate_current(self) -> None:
        """Activate the current page after the first successful connection."""
        page = self.current_page
        if page is not None:
            page.activate()

    def _on_connection_error(self, error: object, manual: bool) -> None:
        """Show an offline banner with an actionable hint."""
        self._online = False
        self.network_pill.set_text("Нет связи")
        self.network_pill.set_level("danger")
        self.network_pill.setToolTip(humanize_error(error))
        self.sync_pill.set_text("Синхронизация")
        self.sync_pill.set_level("neutral")
        self.footer_status.setText("Прокси недоступен")
        self.footer_sync.setText("")
        message = humanize_error(error)
        self._show_banner(
            "Нет связи с локальным прокси. Запустите python main.py в каталоге проекта "
            f"или проверьте настройки. {message}",
            "warning",
        )
        if manual:
            self.toast.error(message, title="Подключение")

    def _on_connection_done(self) -> None:
        """Clear the connection guard."""
        self._checking = False

    def _apply_sync_status(self, status: SyncStatus) -> None:
        """Update header and footer with block and parser progress."""
        daemon_percent = float(status.daemon_percent)
        if status.fully_synced:
            self.sync_pill.set_text("Синхронизировано")
            self.sync_pill.set_level("success")
        elif not status.daemon_synced:
            self.sync_pill.set_text(f"Блоки {format_percent(daemon_percent / 100)}")
            self.sync_pill.set_level("warning")
        else:
            self.sync_pill.set_text(
                f"Парсер {format_percent(float(status.parser.percent) / 100)}"
            )
            self.sync_pill.set_level("warning")
        self.sync_pill.setToolTip(
            f"Блок {format_int(status.blocks)} из {format_int(status.headers)}; "
            f"демон {format_percent(daemon_percent / 100)}; "
            f"парсер {format_int(status.parser.last_parsed)} из "
            f"{format_int(status.parser.last_known)}"
        )
        self.footer_sync.setText(
            f"Блок {format_int(status.blocks)} / {format_int(status.headers)}"
        )
        self._update_parser_footer()

    def _update_parser_footer(self) -> None:
        """Read local parser height files for the footer."""
        if self.demo:
            self.footer_parser.setText("Парсер: демо")
            return
        progress = load_parser_progress(self.project)
        if progress.available:
            self.footer_parser.setText(
                f"Парсер: {format_int(progress.last_parsed)} / "
                f"{format_int(progress.last_known)}"
            )
            self.footer_parser.setToolTip(
                "Локальный индекс UTXO: "
                f"{format_percent(float(progress.percent) / 100)}"
            )
        else:
            self.footer_parser.setText("Парсер: нет данных")
            self.footer_parser.setToolTip("Файлы индексатора еще не созданы")

    def _show_banner(self, text: str, level: str = "warning") -> None:
        """Show the connection banner with semantic styling."""
        self.banner.setObjectName("ErrorBanner" if level == "error" else "Banner")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        color = self.themes.tokens.get(
            "warning" if level == "warning" else "negative", "#F3C969"
        )
        pixmap = icon("warning" if level == "warning" else "error", color, 18).pixmap(
            18, 18
        )
        self.banner_icon.setPixmap(pixmap)
        self.banner_label.setText(text)
        self.banner.setVisible(True)

    def _on_connection_settings(self) -> None:
        """Rebuild the RPC service after proxy credentials changed."""
        self._rebuild_service()
        self._online = False
        self._check_connection(manual=True)

    def _rebuild_service(self) -> None:
        """Recreate the RPC client and share it with every page."""
        if self.demo:
            self.toast.info("Демо-режим использует локальные данные")
            return
        old = getattr(self.service, "client", None)
        url, user, password = self.settings.effective_proxy()
        client = RPCClient(url, user, password, timeout=self.settings.timeout_seconds)
        self.service = WalletService(client)
        self.context.service = self.service
        for page in self._pages.values():
            page.service = self.service
        if old is not None:
            old.close()

    # ------------------------------------------------------------------
    # Daemon
    # ------------------------------------------------------------------
    def _maybe_start_daemon(self) -> None:
        """Start the owned daemon when the preference is enabled."""
        if self.demo or self._daemon is None:
            return
        if self.settings.daemon_autostart:
            self._daemon.start()
        else:
            self.daemon_pill.set_text("Демон не запущен")
            self.daemon_pill.set_level("neutral")

    def _on_daemon_state(self, state: str) -> None:
        """Mirror daemon state in the sidebar and settings page."""
        mapping = {
            "stopped": ("Демон остановлен", "neutral"),
            "starting": ("Запуск демона", "warning"),
            "running": ("Демон работает", "success"),
            "stopping": ("Остановка демона", "warning"),
            "missing": ("Демон не найден", "danger"),
            "failed": ("Ошибка демона", "danger"),
        }
        text, level = mapping.get(state, (state, "neutral"))
        self.daemon_pill.set_text(text)
        self.daemon_pill.set_level(level)
        color = self.themes.tokens.get(
            {"success": "positive", "warning": "warning", "danger": "negative"}.get(
                level, "muted"
            ),
            "#A7B1C2",
        )
        self._pages["settings"].set_daemon_status(text, color)
        if state == STATE_RUNNING:
            self.daemon_pill.setToolTip(
                "Демон запущен"
                if self._daemon and self._daemon.owned
                else "Подключен внешний демон"
            )

    def _on_daemon_ready(self, external: bool) -> None:
        """Refresh connectivity as soon as the daemon answers."""
        self.daemon_pill.setToolTip(
            "Внешний демон" if external else "Демон запущен этим окном"
        )
        QTimer.singleShot(600, self._check_connection)

    def _on_daemon_failed(self, message: str) -> None:
        """Report daemon failures without hiding the rest of the wallet."""
        self.toast.error(message, title="novacoind")
        self.daemon_pill.set_text("Ошибка демона")
        self.daemon_pill.set_level("danger")
        self.daemon_pill.setToolTip(message)
        if not self._online:
            self._show_banner(
                "Демон novacoind не запущен. Укажите путь к бинарнику в настройках "
                f"или запустите его вручную. {message}",
                "error",
            )

    def _restart_daemon(self) -> None:
        """Restart the owned daemon from the settings page."""
        if self._daemon is None:
            self.toast.info("В демо-режиме демон не запускается")
            return
        self._daemon.restart()
        self.toast.info("Перезапуск novacoind...")

    # ------------------------------------------------------------------
    # Page signals
    # ------------------------------------------------------------------
    def _on_page_status(self, message: str, timeout: int) -> None:
        """Forward transient page messages to the toast area."""
        self._sounds.play("notify")
        self.toast.info(message, duration=max(1500, timeout))
        self.footer_status.setText(message)

    def _on_page_error(self, message: str) -> None:
        """Forward page errors to a toast."""
        self._sounds.play("error")
        self.toast.error(message, title="Ошибка")
        self.footer_status.setText("Ошибка")

    def _on_page_busy(self, busy: bool) -> None:
        """Track page refreshes in the header and footer."""
        self._busy_count = max(0, self._busy_count + (1 if busy else -1))
        active = self._busy_count > 0
        if active:
            self.header_spinner.start()
            self.footer_spinner.start()
        else:
            self.header_spinner.stop()
            self.footer_spinner.stop()

    def _open_transaction(self, transaction: object) -> None:
        """Open the transaction detail dialog."""
        dialog = TxDetailsDialog(
            transaction, dict(self.themes.tokens), self.settings.verbosity, self
        )
        dialog.exec()

    def _on_coins_send_requested(self, _utxos: object) -> None:
        """Open the send page after choosing inputs in the coin table."""
        self.navigate("send")
        send_page = self._pages["send"]
        if hasattr(send_page, "preselect"):
            send_page.preselect(_utxos)

    # ------------------------------------------------------------------
    # Timers and shortcuts
    # ------------------------------------------------------------------
    def _start_timers(self) -> None:
        """Start periodic refresh and parser indicators."""
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._apply_refresh_interval()
        self.settings.changed.connect(self._on_setting_changed)
        self._parser_timer = QTimer(self)
        self._parser_timer.setInterval(5000)
        self._parser_timer.timeout.connect(self._update_parser_footer)
        self._parser_timer.start()

    def _apply_refresh_interval(self) -> None:
        """Restart the timer using the configured interval."""
        self._refresh_timer.setInterval(max(5, self.settings.refresh_seconds) * 1000)
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _on_setting_changed(self, key: str, _value: object) -> None:
        """React to settings that affect the shell."""
        if key == "behavior/refresh_seconds":
            self._apply_refresh_interval()
        elif key == "appearance/batch":
            if self.toast is not None:
                self.toast.set_animations(self.settings.animations)
            for page in self._pages.values():
                page.mark_stale()
            current = self.current_page
            if current is not None and current.page_id != "settings":
                current.refresh()
        elif key == "daemon/autostart" and self.settings.daemon_autostart:
            self._maybe_start_daemon()

    def _periodic_refresh(self) -> None:
        """Refresh the active page and reconnect if needed."""
        if not self._online:
            self._check_connection()
            return
        page = self.current_page
        if page is not None and getattr(page, "auto_refresh", False):
            page.refresh()
        self._update_parser_footer()

    def _bind_shortcuts(self) -> None:
        """Register global keyboard shortcuts."""
        for index, (page_id, _text, _icon) in enumerate(NAV_META, start=1):
            shortcut = QShortcut(QKeySequence(f"Alt+{index}"), self)
            shortcut.activated.connect(lambda key=page_id: self.navigate(key))
        self._shortcut("Ctrl+R", self.refresh_current)
        self._shortcut("F5", self.refresh_current)
        self._shortcut("Ctrl+Q", self._quit)
        self._shortcut("Ctrl+Shift+T", self.themes.cycle)
        self._shortcut("Ctrl+,", lambda: self.navigate("settings"))
        self._shortcut("F1", self._show_shortcuts)

    def _shortcut(self, sequence: str, callback: Any) -> QShortcut:
        """Create and connect one window shortcut."""
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        return shortcut

    def _show_shortcuts(self) -> None:
        """Open the keyboard shortcut reference."""
        ShortcutsDialog(dict(self.themes.tokens), self).exec()

    # ------------------------------------------------------------------
    # Theme, geometry and shutdown
    # ------------------------------------------------------------------
    def _on_theme_changed(self, theme: object) -> None:
        """Recolor icons, brand mark and page-specific details."""
        self.setWindowIcon(app_icon(theme))
        logo = brand_logo(38)
        self.brand_label.setPixmap(logo if not logo.isNull() else brand_mark(theme, 38))
        self.backdrop.set_theme(theme)
        muted = theme.color("muted")
        self.refresh_button.setIcon(icon("refresh", muted, 18))
        self.theme_button.setIcon(icon("sun" if theme.dark else "moon", muted, 18))
        self.settings_button.setIcon(icon("settings", muted, 18))
        self.banner_icon.setPixmap(
            icon("warning", theme.color("warning"), 18).pixmap(18, 18)
        )
        self._update_nav_icons()
        if hasattr(self, "tray"):
            self.tray.setIcon(app_icon(theme))
        for page in self._pages.values():
            if hasattr(page, "apply_theme"):
                page.apply_theme()

    def _update_nav_icons(self) -> None:
        """Tint navigation icons according to active state."""
        current = self.current_page.page_id if self.current_page is not None else ""
        theme = self.themes.theme
        for page_id, button in self._nav_buttons.items():
            button.setIcon(
                nav_icon(
                    NAV_META[[item[0] for item in NAV_META].index(page_id)][2],
                    theme,
                    page_id == current,
                )
            )

    def _restore_geometry(self) -> None:
        """Restore the previous window size and position."""
        geometry = self.settings.window_geometry
        if geometry and not self.restoreGeometry(geometry):
            self.resize(1360, 880)
        state = self.settings.window_state
        if state:
            self.restoreState(state)

    def _save_geometry(self) -> None:
        """Persist window geometry for the next launch."""
        self.settings.window_geometry = self.saveGeometry()
        self.settings.window_state = self.saveState()
        self.settings.sync()

    def _setup_tray(self) -> None:
        """Create a tray icon when the desktop provides one."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(self.themes.theme), self)
        self.tray.setToolTip(__app_name__)
        menu = QMenu(self)
        show_action = QAction("Открыть", self)
        show_action.triggered.connect(self._raise_window)
        refresh_action = QAction("Обновить", self)
        refresh_action.triggered.connect(self.refresh_current)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_media_dropped(self, path: str) -> None:
        """Use a file dropped on the window as the local backdrop."""
        self.settings.media_path = path
        self.settings.media_enabled = True
        self.toast.success("Фон приложения обновлен", title="Медиафон")

    def _raise_window(self) -> None:
        """Bring the window to the foreground."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Restore the window on a double click."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._raise_window()

    def _quit(self) -> None:
        """Quit the application through the normal close path."""
        self._really_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """Save state and stop a daemon owned by this window."""
        self._save_geometry()
        self.closing.emit()
        if self._daemon is not None:
            try:
                self._daemon.stop()
            except RuntimeError:
                pass
        if hasattr(self, "tray"):
            self.tray.hide()
        if self._motion is not None:
            self._motion.shutdown()
        if self.toast is not None:
            self.toast.shutdown()
        event.accept()
        QApplication.instance().quit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Create the tray icon after the window is ready."""
        super().showEvent(event)
        if not hasattr(self, "tray"):
            self._setup_tray()
        if not self._intro_played:
            self._intro_played = True
            if self._motion is not None:
                self._motion.fade_in(self.centralWidget(), 320)
