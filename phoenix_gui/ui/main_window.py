"""Main window: navigation shell, daemon lifecycle and sync indicators."""

from __future__ import annotations

import logging
import time
from typing import Any

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
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

from .. import __version__
from ..core.config import ProjectConfig
from ..core.daemon import STATE_RUNNING, DaemonProcess
from ..core.proxy import ProxyProcess
from ..core.errors import humanize_error
from ..core.formatting import format_int, format_percent
from ..core.logs import clean_output
from ..core.media import MediaBackdrop
from ..core.sounds import SoundPlayer
from ..core.sync import SyncStatus, build_sync_status, load_parser_progress
from ..core.tasks import run_async
from ..i18n import SOURCE_LANGUAGE, TranslationManager
from ..rpc.client import RPCClient, RPCConnectionError
from ..rpc.service import WalletService
from ..settings import Settings
from .dialogs.connection import ConnectionDialog
from .dialogs.migration import MigrationDialog
from .dialogs.shortcuts import ShortcutsDialog
from .dialogs.wallet_password import WalletPasswordDialog
from .dialogs.tx_details import TxDetailsDialog
from .pages.analytics import AnalyticsPage
from .pages.base import PageContext
from .widgets.privacy import PrivacyManager
from .pages.coins import CoinsPage
from .pages.console import ConsolePage
from .pages.logs import LogsPage
from .pages.overview import OverviewPage
from .pages.receive import ReceivePage
from .pages.send import SendPage
from .pages.settings import SettingsPage
from .pages.storage import StoragePage
from .pages.transactions import TransactionsPage
from .widgets.card import Pill
from .widgets.animations import Motion
from .widgets.icons import app_icon, brand_logo, brand_mark, icon, nav_icon
from .widgets.progress import Spinner
from .widgets.sheet import AboutSheet, ConfirmSheet, SheetHost
from .widgets.theme import ThemeManager
from .widgets.toast import ToastManager

LOGGER = logging.getLogger("phoenix")

PAGE_CLASSES = (
    OverviewPage,
    SendPage,
    ReceivePage,
    TransactionsPage,
    CoinsPage,
    StoragePage,
    AnalyticsPage,
    ConsolePage,
    LogsPage,
    SettingsPage,
)

NAV_META: tuple[tuple[str, str, str], ...] = (
    ("overview", "Обзор", "home"),
    ("send", "Отправить", "send"),
    ("receive", "Получить", "receive"),
    ("transactions", "История", "transactions"),
    ("coins", "Монеты", "coins"),
    ("storage", "Хранилище", "file"),
    ("analytics", "Аналитика", "chart"),
    ("console", "Консоль", "terminal"),
    ("logs", "Журнал", "file"),
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
        self.translations = TranslationManager(settings, self)
        self.privacy = PrivacyManager(settings, themes, self)
        self.context = PageContext(
            service=service,
            settings=settings,
            themes=themes,
            config=project,
            translations=self.translations,
            privacy=self.privacy,
        )
        self._online = False
        self._checking = False
        self._busy_count = 0
        self._really_quit = False
        self._daemon: DaemonProcess | None = None
        self._proxy: ProxyProcess | None = None
        self._connection_dialog: ConnectionDialog | None = None
        self._wallet_password = ""
        self._proxy_prompt_denied = False
        self._daemon_user_stopped = False
        self._proxy_user_stopped = False
        self._last_daemon_auto = 0.0
        self._last_proxy_auto = 0.0
        self._last_connection_check = 0.0
        self._connection_retry = 8.0
        self._last_connectivity_notice = 0.0
        self._backend_failure_notice_at = 0.0
        self._sync: SyncStatus | None = None
        self._pages: dict[str, Any] = {}
        self._sounds = SoundPlayer(settings, self)
        self._motion: Motion | None = None
        self._intro_played = False
        self._nav_buttons: dict[str, QPushButton] = {}
        self._setup_window()
        self._motion = Motion(settings, self)
        self._build_shell()
        self.sheet_host = SheetHost(self.backdrop)
        self._build_pages()
        self._build_daemon()
        self._build_proxy()
        self._bind_shortcuts()
        if self.translations.language != SOURCE_LANGUAGE:
            self.translations.translate_tree(self)
        self._start_timers()
        self.themes.changed.connect(self._on_theme_changed)
        self.translations.languageChanged.connect(self._on_language_changed)
        self._on_theme_changed(self.themes.theme)
        self._start_translation_timer()
        self._restore_geometry()
        QTimer.singleShot(250, self._initial_connection_check)
        QTimer.singleShot(400, self._maybe_start_daemon)
        QTimer.singleShot(1800, self._maybe_start_proxy)

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    def _start_translation_timer(self) -> None:
        """Refresh translated dynamic labels while a foreign language is active."""
        self._translation_timer = QTimer(self)
        self._translation_timer.setInterval(800)
        self._translation_timer.timeout.connect(self._retranslate_visible)
        if self.translations.language != SOURCE_LANGUAGE:
            self._translation_timer.start()

    def _retranslate_visible(self) -> None:
        """Translate the visible page after asynchronous data updates."""
        if self.translations.language == SOURCE_LANGUAGE:
            return
        self.translations.translate_tree(self)

    def _on_language_changed(self, code: str) -> None:
        """Apply a new language to the whole window and its dynamic parts."""
        self.translations.translate_tree(self)
        self._apply_window_title()
        page = self.stack.currentWidget()
        if page is not None and getattr(page, "page_id", "") != "settings":
            page.refresh()
        if code == SOURCE_LANGUAGE:
            self._translation_timer.stop()
        else:
            self._translation_timer.start()
        language = self.translations.active_language
        self.toast.info(
            f"{self.translations.tr('Язык интерфейса')}: {language.native_name}",
            title=self.translations.tr("Язык"),
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _apply_window_title(self) -> None:
        """Keep the native title bar in sync with the active language."""
        network = self.translations.tr(self._network_caption())
        self.setWindowTitle(f"Novacoin - {network}")

    def _setup_window(self) -> None:
        """Set titles, size constraints and the central backdrop."""
        self._apply_window_title()
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
        self.sidebar = self._build_sidebar()
        shell.addWidget(self.sidebar)

        self.content = QWidget()
        self.content.setObjectName("Content")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._build_header())
        content_layout.addWidget(self._build_banner())

        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        content_layout.addWidget(self.stack, 1)
        content_layout.addWidget(self._build_footer())
        shell.addWidget(self.content, 1)

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
        self.brand_label.setToolTip("Novacoin")
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_name = QLabel("Novacoin")
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
        self.daemon_pill.setToolTip(
            "Нажмите, чтобы открыть управление серверами и диагностику"
        )
        self.daemon_pill.set_clickable(True)
        self.daemon_pill.clicked.connect(self.open_connection_dialog)
        layout.addWidget(self.daemon_pill, 0, Qt.AlignmentFlag.AlignLeft)
        self.proxy_pill = Pill("Прокси не запущен", "neutral")
        self.proxy_pill.setToolTip(
            "Нажмите, чтобы запустить прокси, перезапустить или посмотреть журнал"
        )
        self.proxy_pill.set_clickable(True)
        self.proxy_pill.clicked.connect(self.open_connection_dialog)
        layout.addWidget(self.proxy_pill, 0, Qt.AlignmentFlag.AlignLeft)
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
            position = len(self._nav_buttons) + 1
            hint = f"Alt+{position}" if position <= 9 else "Ctrl+,"
            button.setToolTip(f"Перейти: {text} ({hint})")
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
        self.servers_button = QPushButton()
        self.servers_button.setObjectName("IconButton")
        self.servers_button.setFixedSize(34, 34)
        self.servers_button.setToolTip(
            "Серверы и подключение: запуск, диагностика (Ctrl+Shift+S)"
        )
        self.servers_button.clicked.connect(self.open_connection_dialog)
        self.settings_button = QPushButton()
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setFixedSize(34, 34)
        self.settings_button.setToolTip("Открыть настройки (Ctrl+,)")
        self.settings_button.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.theme_button)
        layout.addWidget(self.servers_button)
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
        self.banner_start = QPushButton("Запустить прокси")
        self.banner_start.setObjectName("AccentButton")
        self.banner_start.setToolTip("Запустить локальный прокси без терминала")
        self.banner_start.clicked.connect(lambda: self._start_proxy(True))
        self.banner_servers = QPushButton("Серверы")
        self.banner_servers.setObjectName("GhostButton")
        self.banner_servers.setToolTip("Открыть управление серверами и журналом")
        self.banner_servers.clicked.connect(self.open_connection_dialog)
        self.retry_button = QPushButton("Повторить")
        self.retry_button.setObjectName("GhostButton")
        self.retry_button.setToolTip("Повторить проверку прокси")
        self.retry_button.clicked.connect(lambda: self._check_connection(manual=True))
        self.banner_settings = QPushButton("Настройки")
        self.banner_settings.setObjectName("GhostButton")
        self.banner_settings.setToolTip("Открыть параметры подключения")
        self.banner_settings.clicked.connect(lambda: self.navigate("settings"))
        layout.addWidget(self.banner_start)
        layout.addWidget(self.banner_servers)
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
            page.dataChanged.connect(lambda source=page: self._on_data_changed(source))
        self._pages["coins"].sendRequested.connect(self._on_coins_send_requested)
        settings_page = self._pages["settings"]
        settings_page.connectionChanged.connect(self._on_connection_settings)
        settings_page.daemonRestartRequested.connect(self._restart_daemon)
        settings_page.proxyStartRequested.connect(self._start_proxy)
        settings_page.proxyStopRequested.connect(self._stop_proxy)
        settings_page.proxyRestartRequested.connect(self._restart_proxy)
        settings_page.diagnosticsRequested.connect(self.open_connection_dialog)
        settings_page.migrationRequested.connect(self._open_migration)
        self.navigate(
            self.settings.last_page
            if self.settings.last_page in self._pages
            else "overview"
        )

    def _on_data_changed(self, source) -> None:
        """Invalidate other pages after a send or address mutation."""
        for page in self._pages.values():
            if page is not source and hasattr(page, "mark_stale"):
                page.mark_stale()
        current = self.current_page
        if current is not None and current is not source:
            current.refresh()

    @staticmethod
    def _log_backend(source: str, chunk: str) -> None:
        """Write process output to the rotating application log."""
        for line in clean_output(chunk):
            LOGGER.info("%s | %s", source, line)

    # ------------------------------------------------------------------
    # Backend control center
    # ------------------------------------------------------------------
    @property
    def daemon_process(self) -> DaemonProcess | None:
        """Return the daemon controller used by this window."""
        return self._daemon

    @property
    def proxy_process(self) -> ProxyProcess | None:
        """Return the proxy controller used by this window."""
        return self._proxy

    def show_sheet(self, widget: QWidget, on_closed=None) -> None:
        """Show an application dialog inside the main window."""
        if self.translations.language != SOURCE_LANGUAGE:
            self.translations.translate_tree(widget)
        self.sheet_host.show_sheet(widget, on_closed)

    def close_sheet(self) -> None:
        """Close the embedded dialog, if one is open."""
        self.sheet_host.close_sheet()

    def show_about(self) -> None:
        """Show product information inside the main window."""
        self.show_sheet(AboutSheet(parent=self))

    def confirm(
        self,
        title: str,
        message: str,
        on_accept,
        accept_text: str = "Продолжить",
        danger: bool = False,
    ) -> None:
        """Ask for confirmation inside the main window."""
        sheet = ConfirmSheet(
            title,
            message,
            accept_text=accept_text,
            danger=danger,
            parent=self,
        )

        def accepted() -> None:
            self.close_sheet()
            on_accept()

        sheet.confirmed.connect(accepted)
        self.show_sheet(sheet)

    def open_connection_dialog(self) -> None:
        """Open the server control center inside the main window."""
        if self._connection_dialog is not None:
            return
        dialog = ConnectionDialog(self, self)
        self._connection_dialog = dialog
        if self.translations.language != SOURCE_LANGUAGE:
            self.translations.translate_tree(dialog)
        self.show_sheet(
            dialog,
            on_closed=lambda: setattr(self, "_connection_dialog", None),
        )

    def start_daemon_backend(self) -> None:
        """Start the daemon from the control center."""
        if self.demo or self._daemon is None:
            self.toast.info("В демо-режиме демон не запускается")
            return
        self._daemon_user_stopped = False
        self._daemon.start()

    def restart_daemon_backend(self) -> None:
        """Restart the daemon from the control center."""
        self._restart_daemon()

    def stop_daemon_backend(self) -> None:
        """Stop the daemon, asking first for an externally started node."""
        if self.demo or self._daemon is None:
            return
        if self._daemon.owned:
            self._daemon_user_stopped = True
            self._daemon.stop()
            return
        self.confirm(
            "Остановить узел",
            "Узел запущен вне этого окна. После остановки кошелек потеряет "
            "соединение с сетью, пока узел не будет запущен снова.",
            self._stop_external_daemon,
            "Остановить",
            True,
        )

    def _stop_external_daemon(self) -> None:
        """Send the raw stop command to an externally managed daemon."""
        self._daemon_user_stopped = True
        run_async(
            self.service.call,
            lambda _result: self.toast.info("Команда остановки узла отправлена"),
            lambda error: self.toast.error(humanize_error(error)),
            None,
            "stop",
        )

    def start_proxy_backend(self) -> None:
        """Start the proxy from the control center."""
        self._proxy_prompt_denied = False
        self._proxy_user_stopped = False
        self._start_proxy(manual=True)

    def stop_proxy_backend(self) -> None:
        """Stop the proxy from the control center."""
        self._stop_proxy()

    def restart_proxy_backend(self) -> None:
        """Restart the proxy from the control center."""
        self._restart_proxy()

    def check_connection_now(self) -> None:
        """Repeat the RPC health check immediately."""
        self._check_connection(manual=True)

    def start_all_backends(self) -> None:
        """Start both services in order, asking for the wallet password once."""
        self._daemon_user_stopped = False
        self._proxy_user_stopped = False
        self._proxy_prompt_denied = False
        if self.demo:
            self.toast.info("В демо-режиме серверные процессы не нужны")
            return
        if self._daemon is not None:
            self._daemon.start()
        if self._proxy is not None:
            QTimer.singleShot(700, lambda: self._start_proxy(manual=True))

    def _build_proxy(self) -> None:
        """Create the owned local proxy process controller."""
        if self.demo:
            self.proxy_pill.setVisible(False)
            self._pages["settings"].set_proxy_status(
                "Демо-режим: прокси не запускается",
                self.themes.tokens.get("accent", "#FF8A3D"),
            )
            return
        self._proxy = ProxyProcess(self.settings, self.project, self)
        self._proxy.stateChanged.connect(self._on_proxy_state)
        self._proxy.output.connect(lambda text: self._log_backend("proxy", text))
        self._proxy.failed.connect(lambda message: LOGGER.error("proxy: %s", message))
        self._proxy.ready.connect(self._on_proxy_ready)
        self._proxy.failed.connect(self._on_proxy_failed)
        self._pages["settings"].set_proxy_controls("stopped")
        self._proxy.stopped.connect(lambda _code: self._check_connection())

    def _build_daemon(self) -> None:
        """Create the owned daemon process controller."""
        if self.demo:
            self.daemon_pill.set_text("Локальные данные")
            self.daemon_pill.set_level("accent")
            self._pages["settings"].set_daemon_status(
                "Демо-режим: novacoind не запускается",
                self.themes.tokens.get("accent", "#FF8A3D"),
            )
            return
        self._daemon = DaemonProcess(self.settings, self.project, self)
        self._daemon.stateChanged.connect(self._on_daemon_state)
        self._daemon.output.connect(lambda text: self._log_backend("novacoind", text))
        self._daemon.failed.connect(
            lambda message: LOGGER.error("novacoind: %s", message)
        )
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
        if self.translations.language != SOURCE_LANGUAGE:
            self.translations.translate_tree(self)
            if page_id != "settings":
                page.refresh()

    @property
    def online(self) -> bool:
        """Return whether the last RPC health check succeeded."""
        return self._online

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

    def _initial_connection_check(self) -> None:
        """Check an existing proxy before autostart has had time to run."""
        if (
            self._proxy is not None
            and self.settings.proxy_autostart
            and not self._proxy.port_open()
        ):
            self.footer_status.setText("Запуск локального прокси...")
            return
        self._check_connection()

    def _check_connection(self, manual: bool = False) -> None:
        """Probe the local proxy without blocking the interface."""
        if self.demo:
            self._online = True
            self._checking = False
            self.banner.setVisible(False)
            self.network_pill.set_text("Демо-сеть")
            self.network_pill.set_level("accent")
            self.network_pill.setToolTip(
                "Данные созданы локально, сеть не используется"
            )
            self.sync_pill.setVisible(False)
            self.footer_status.setText("Локальные данные")
            self.footer_sync.setText("Сеть не используется")
            self.footer_parser.setText("Парсер: демо")
            page = self.current_page
            if page is not None:
                page.activate()
            return
        if self._checking:
            return
        if manual:
            self._connection_retry = 8.0
        if self.service is None:
            self._checking = False
            self.footer_status.setText("Ожидание прокси...")
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
        self._connection_retry = 20.0
        self._last_connectivity_notice = 0.0
        self._sync = status
        self.banner.setVisible(False)
        self.network_pill.set_text(self.translations.tr("В сети"))
        self.network_pill.set_level("success")
        if (
            not self.demo
            and self._daemon is not None
            and self._daemon.state != "running"
        ):
            self.daemon_pill.set_text(self.translations.tr("Демон подключен"))
            self.daemon_pill.set_level("success")
            self.daemon_pill.setToolTip(
                self.translations.tr(
                    "Локальный демон отвечает по RPC; процесс запущен вне этого окна."
                )
            )
        network_label = self.translations.tr(
            "Тестовая сеть" if status.network.testnet else "Основная сеть"
        )
        self.network_pill.setToolTip(
            f"{network_label}, блок {format_int(status.network.blocks)}, "
            f"соединений {format_int(status.network.connections)}"
        )
        self.network_name.setText(network_label)
        self._apply_sync_status(status)
        self.footer_status.setText(self.translations.tr("Готово"))
        clear_toasts = getattr(self.toast, "clear", None)
        if clear_toasts is not None:
            clear_toasts()
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
        self._connection_retry = min(60.0, max(8.0, self._connection_retry * 1.6))
        self.network_pill.set_text(self.translations.tr("Нет связи"))
        self.network_pill.set_level("danger")
        self.network_pill.setToolTip(humanize_error(error))
        self.sync_pill.set_text(self.translations.tr("Синхронизация"))
        self.sync_pill.set_level("neutral")
        self.footer_sync.setText("")
        message = humanize_error(error)
        proxy = self._proxy
        if (
            isinstance(error, RPCConnectionError)
            and proxy is not None
            and proxy.state == "running"
        ):
            text = self.translations.tr(
                "Прокси работает, но узел Novacoin не ответил. "
                "Дождитесь синхронизации или проверьте журнал."
            )
            self.footer_status.setText(self.translations.tr("Узел не отвечает"))
        elif proxy is not None and proxy.state == "starting":
            text = "Локальный прокси запускается. Это занимает несколько секунд."
            self.footer_status.setText(self.translations.tr("Прокси недоступен"))
        else:
            text = self.translations.tr(message)
            self.footer_status.setText(self.translations.tr("Прокси недоступен"))
        self._show_banner(text, "warning")
        self.banner.setToolTip(message)
        if manual:
            self.toast.error(message, title="Подключение")

    def _on_connection_done(self) -> None:
        """Clear the connection guard."""
        self._checking = False

    def _apply_sync_status(self, status: SyncStatus) -> None:
        """Update header and footer with block and parser progress."""
        daemon_percent = float(status.daemon_percent)
        if status.fully_synced:
            self.sync_pill.set_text(self.translations.tr("Синхронизировано"))
            self.sync_pill.set_level("success")
        elif not status.daemon_synced:
            self.sync_pill.set_text(
                f"{self.translations.tr('Блоки')} "
                f"{format_percent(daemon_percent / 100)}"
            )
            self.sync_pill.set_level("warning")
        else:
            self.sync_pill.set_text(
                f"{self.translations.tr('Парсер')} "
                f"{format_percent(float(status.parser.percent) / 100)}"
            )
            self.sync_pill.set_level("warning")
        self.sync_pill.setToolTip(
            f"Блок {format_int(status.blocks)} из {format_int(status.headers)}; "
            f"демон {format_percent(daemon_percent / 100)}; "
            f"парсер {format_int(status.parser.last_parsed)} из "
            f"{format_int(status.parser.last_known)}"
        )
        self.footer_sync.setText(
            f"{self.translations.tr('Блок')} {format_int(status.blocks)} / "
            f"{format_int(status.headers)}"
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
        self._sync_banner_actions()
        self.banner.setVisible(True)

    def _sync_banner_actions(self) -> None:
        """Show the proxy start action only when it can be useful."""
        if not hasattr(self, "banner_start"):
            return
        proxy = self._proxy
        can_start = (
            not self.demo
            and proxy is not None
            and proxy.state not in {"starting", "running", "stopping"}
        )
        self.banner_start.setVisible(can_start)

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
        text = self.translations.tr(text)
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

    def _notify_backend_failure(self, title: str, message: str) -> None:
        """Show backend failures at most once a minute during automatic retries."""
        now = time.monotonic()
        if now - self._backend_failure_notice_at < 60.0:
            return
        self._backend_failure_notice_at = now
        self.toast.error(message, title=title)

    def _on_daemon_failed(self, message: str) -> None:
        """Report daemon failures without hiding the rest of the wallet."""
        self._notify_backend_failure("novacoind", message)
        self.daemon_pill.set_text("Ошибка демона")
        self.daemon_pill.set_level("danger")
        self.daemon_pill.setToolTip(message)
        if not self._online:
            self._show_banner(
                "Демон novacoind не запущен. Укажите путь к бинарнику в настройках "
                f"или запустите его вручную. {message}",
                "error",
            )

    def _wallet_file(self) -> Any:
        """Return the encrypted key-store path for this checkout."""
        return self.project.root / "keypair.bin"

    def _ensure_wallet_password(self, on_ready) -> None:
        """Ask for the key-store password in an embedded sheet."""
        if self._wallet_password:
            on_ready(True)
            return
        create = not self._wallet_file().is_file()
        dialog = WalletPasswordDialog(create=create, parent=self)

        def finished(code: int) -> None:
            if code == QDialog.DialogCode.Accepted:
                self._wallet_password = dialog.password_value()
            on_ready(bool(self._wallet_password))

        dialog.finished.connect(finished)
        self.show_sheet(dialog)

    def _start_proxy(self, manual: bool = True) -> None:
        """Start the local proxy from the GUI, asking for its password."""
        if self.demo or self._proxy is None:
            if manual:
                self.toast.info("В демо-режиме прокси не запускается")
            return
        if self._proxy.state in {"starting", "running"}:
            if manual:
                self.toast.info("Прокси уже запущен")
            return
        if self._proxy.port_open() and not self._proxy.owned:
            self._proxy.start()
            if manual:
                self.toast.info("Подключение к уже запущенному прокси")
            return
        if not self._wallet_password:
            self._ensure_wallet_password(
                lambda ready: (
                    self._launch_proxy(manual) if ready else self._cancel_proxy_launch()
                )
            )
            return
        self._launch_proxy(manual)

    def _launch_proxy(self, manual: bool = True) -> None:
        """Start the proxy once the key-store password is available."""
        if self.demo or self._proxy is None:
            return
        if self._proxy.state in {"starting", "running"}:
            if manual:
                self.toast.info("Прокси уже запущен")
            return
        self._proxy.start(self._wallet_password)
        if manual:
            self.toast.info("Запуск локального прокси...")

    def _cancel_proxy_launch(self) -> None:
        """Report a cancelled password prompt and stop auto-retrying it."""
        self._proxy_prompt_denied = True
        self._pages["settings"].set_proxy_status("Запуск отменен")

    def _maybe_start_proxy(self) -> None:
        """Autostart the proxy after the daemon has been launched."""
        if self.demo or self._proxy is None:
            return
        if self.settings.proxy_autostart and not self._proxy_prompt_denied:
            self._start_proxy(manual=False)
        elif self._proxy.state in {"stopped", "missing", "failed"}:
            self.proxy_pill.set_text("Прокси не запущен")
            self.proxy_pill.set_level("neutral")

    def _stop_proxy(self) -> None:
        """Stop an owned proxy; external proxies are left untouched."""
        if self._proxy is None:
            return
        if not self._proxy.owned:
            self.toast.info("Внешний прокси не останавливается")
            return
        self._proxy_user_stopped = True
        self._proxy.stop()
        self.toast.info("Остановка прокси...")

    def _restart_proxy(self) -> None:
        """Restart the local proxy and ask for the password again if needed."""
        if self._proxy is None:
            return
        self._proxy_prompt_denied = False
        self._proxy_user_stopped = False
        if not self._proxy.owned and not self._proxy.port_open():
            self._start_proxy()
            return
        if not self._wallet_password:
            self._ensure_wallet_password(
                lambda ready: self._finish_proxy_restart() if ready else None
            )
            return
        self._finish_proxy_restart()

    def _finish_proxy_restart(self) -> None:
        """Restart the proxy after the password is available."""
        if self._proxy is None:
            return
        self._proxy.restart(self._wallet_password)
        self.toast.info("Перезапуск прокси...")

    def _on_proxy_state(self, state: str) -> None:
        """Mirror proxy lifecycle in the sidebar and settings page."""
        mapping = {
            "stopped": ("Прокси остановлен", "neutral"),
            "starting": ("Запуск прокси", "warning"),
            "running": ("Прокси работает", "success"),
            "stopping": ("Остановка прокси", "warning"),
            "missing": ("Прокси не найден", "danger"),
            "failed": ("Ошибка прокси", "danger"),
        }
        text, level = mapping.get(state, (state, "neutral"))
        text = self.translations.tr(text)
        self.proxy_pill.set_text(text)
        self.proxy_pill.set_level(level)
        self._sync_banner_actions()
        color = self.themes.tokens.get(
            {"success": "positive", "warning": "warning", "danger": "negative"}.get(
                level, "muted"
            ),
            "#A7B1C2",
        )
        self._pages["settings"].set_proxy_status(text, color)
        self._pages["settings"].set_proxy_controls(
            state, bool(self._proxy is not None and self._proxy.owned)
        )

    def _on_proxy_ready(self, external: bool) -> None:
        """Reconnect all pages once the proxy endpoint answers."""
        self._proxy_prompt_denied = False
        self._backend_failure_notice_at = 0.0
        self.proxy_pill.setToolTip(
            self.translations.tr("Внешний прокси")
            if external
            else self.translations.tr("Прокси запущен этим окном")
        )
        self._rebuild_service()
        self._online = False
        self._check_connection(manual=True)

    def _on_proxy_failed(self, message: str) -> None:
        """Report proxy failures and allow a password retry."""
        # Only forget the key-store password when authentication failed.
        if any(
            token in message.lower()
            for token in ("парол", "password", "mac check", "хранилищ")
        ):
            self._wallet_password = ""
            self._proxy_prompt_denied = True
        self._notify_backend_failure("Прокси", message)
        self.proxy_pill.set_text("Ошибка прокси")
        self.proxy_pill.set_level("danger")
        self.proxy_pill.setToolTip(message)
        self._pages["settings"].set_proxy_status(
            "Ошибка прокси", self.themes.tokens.get("negative", "#FF7070")
        )
        if not self._online:
            self._show_banner(
                "Локальный прокси не запущен. Запустите его в настройках "
                f"или проверьте пароль. {message}",
                "error",
            )

    def _restart_daemon(self) -> None:
        """Restart the owned daemon from the settings page."""
        if self._daemon is None:
            self.toast.info("В демо-режиме демон не запускается")
            return
        self._daemon_user_stopped = False
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
        """Forward page errors to a toast, throttling connectivity noise."""
        now = time.monotonic()
        lowered = message.casefold()
        connectivity = any(
            hint in lowered
            for hint in (
                "did not respond",
                "не ответил",
                "timed out",
                "таймаут",
                "timeout",
                "connection",
                "соединен",
                "прокси",
                "демон",
                "502",
                "503",
                "429",
                "частот",
            )
        )
        # One connectivity toast until a successful check: the banner and
        # footer already show the live state, so automatic retries stay quiet.
        if connectivity and self._last_connectivity_notice:
            self.footer_status.setText(message[:160])
            return
        if connectivity:
            self._last_connectivity_notice = now
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

    def _open_migration(self) -> None:
        """Open the guided wallet migration assistant."""
        if self.demo:
            self.toast.info("В демо-режиме перенос кошелька недоступен")
            return
        receive = self._pages.get("receive")
        destination = getattr(receive, "_current_address", "") if receive else ""
        dialog = MigrationDialog(
            self.project,
            self.settings,
            dict(self.themes.tokens),
            destination=destination,
            parent=self,
        )
        dialog.completed.connect(self._on_migration_completed)
        dialog.completed.connect(self.close_sheet)
        self.show_sheet(dialog)

    def _on_migration_completed(self) -> None:
        """Refresh wallet views after a successful legacy sweep."""
        for page_id in ("overview", "transactions", "receive", "coins"):
            page = self._pages.get(page_id)
            if page is not None:
                page.mark_stale()
        current = self.current_page
        if current is not None:
            current.refresh()
        self.toast.success("Средства перенесены. Проверьте историю операций.")

    def _open_transaction(self, transaction: object) -> None:
        """Open the transaction detail dialog."""
        dialog = TxDetailsDialog(
            transaction, dict(self.themes.tokens), self.settings.verbosity, self
        )
        self.show_sheet(dialog)

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
        self._backend_timer = QTimer(self)
        self._backend_timer.setInterval(5000)
        self._backend_timer.timeout.connect(self._watch_backends)
        self._backend_timer.start()

    def _watch_backends(self) -> None:
        """Keep hidden services alive and refresh their health without clicks."""
        if self.demo or self._really_quit:
            return
        now = time.monotonic()
        if self.sheet_host.current_widget is None:
            if (
                self._daemon is not None
                and self.settings.daemon_autostart
                and not self._daemon_user_stopped
                and self._daemon.state in {"stopped", "failed", "missing"}
                and now - self._last_daemon_auto >= 30
            ):
                self._last_daemon_auto = now
                self._daemon.start()
            if (
                self._proxy is not None
                and self.settings.proxy_autostart
                and not self._proxy_user_stopped
                and not self._proxy_prompt_denied
                and self._proxy.state in {"stopped", "failed", "missing"}
                and now - self._last_proxy_auto >= 15
            ):
                self._last_proxy_auto = now
                self._start_proxy(manual=False)
        interval = 20.0 if self._online else self._connection_retry
        if not self._checking and now - self._last_connection_check >= interval:
            self._last_connection_check = now
            self._check_connection()

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
            self._daemon_user_stopped = False
            self._maybe_start_daemon()
        elif key == "proxy/autostart" and self.settings.proxy_autostart:
            self._proxy_user_stopped = False
            self._proxy_prompt_denied = False
            self._maybe_start_proxy()

    def _periodic_refresh(self) -> None:
        """Refresh the active page and reconnect if needed."""
        if not self._online:
            if time.monotonic() - self._last_connection_check >= self._connection_retry:
                self._last_connection_check = time.monotonic()
                self._check_connection()
            return
        page = self.current_page
        if page is not None and getattr(page, "auto_refresh", False):
            page.refresh()
        self._update_parser_footer()

    def _bind_shortcuts(self) -> None:
        """Register global keyboard shortcuts."""
        for index, (page_id, _text, _icon) in enumerate(NAV_META, start=1):
            key = f"Alt+{index}" if index <= 9 else "Alt+0"
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(lambda target=page_id: self.navigate(target))
        self._shortcut("Ctrl+R", self.refresh_current)
        self._shortcut("F5", self.refresh_current)
        self._shortcut("Ctrl+Q", self._quit)
        self._shortcut("Ctrl+Shift+T", self.themes.cycle)
        self._shortcut("Ctrl+,", lambda: self.navigate("settings"))
        self._shortcut("Ctrl+Shift+L", lambda: self.navigate("logs"))
        self._shortcut("Ctrl+Shift+S", self.open_connection_dialog)
        self._shortcut("F1", self._show_shortcuts)

    def _shortcut(self, sequence: str, callback: Any) -> QShortcut:
        """Create and connect one window shortcut."""
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(callback)
        return shortcut

    def _show_shortcuts(self) -> None:
        """Open the keyboard shortcut reference."""
        dialog = ShortcutsDialog(dict(self.themes.tokens), self)
        self.show_sheet(dialog)

    # ------------------------------------------------------------------
    # Theme, geometry and shutdown
    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep the in-window sheet layer aligned with the window."""
        super().resizeEvent(event)
        host = getattr(self, "sheet_host", None)
        if host is not None:
            host.setGeometry(self.backdrop.rect())

    def _on_theme_changed(self, theme: object) -> None:
        """Recolor icons, brand mark and page-specific details."""
        self.setWindowIcon(app_icon(theme))
        logo = brand_logo(38)
        self.brand_label.setPixmap(logo if not logo.isNull() else brand_mark(theme, 38))
        self.backdrop.set_theme(theme)
        muted = theme.color("muted")
        self.refresh_button.setIcon(icon("refresh", muted, 18))
        self.theme_button.setIcon(icon("sun" if theme.dark else "moon", muted, 18))
        self.servers_button.setIcon(icon("server", muted, 18))
        self.settings_button.setIcon(icon("settings", muted, 18))
        self.banner_icon.setPixmap(
            icon("warning", theme.color("warning"), 18).pixmap(18, 18)
        )
        self._update_nav_icons()
        if hasattr(self, "tray"):
            self.tray.setIcon(app_icon(theme))
        self.privacy.refresh_theme()
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
        self.tray.setToolTip(f"Novacoin - {self._network_caption()}")
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
        if self._proxy is not None:
            try:
                self._proxy.stop()
            except RuntimeError:
                pass
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
