"""Shared page base class and page context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QMessageBox, QScrollArea, QVBoxLayout, QWidget

from ...core.config import ProjectConfig
from ...core.errors import humanize_error
from ...i18n import TranslationManager
from ...settings import Settings
from ...rpc.service import WalletService
from ..widgets.privacy import PrivacyManager
from ..widgets.theme import ThemeManager


@dataclass(slots=True)
class PageContext:
    """Dependencies shared by every page."""

    service: WalletService
    settings: Settings
    themes: ThemeManager
    config: ProjectConfig
    translations: TranslationManager | None = None
    privacy: PrivacyManager | None = None


class BasePage(QWidget):
    """Base class with refresh guards and common signals."""

    page_id = "page"
    page_title = "Страница"
    page_subtitle = ""
    auto_refresh = True

    statusMessage = pyqtSignal(str, int)
    errorRaised = pyqtSignal(str)
    dataChanged = pyqtSignal()
    busyChanged = pyqtSignal(bool)
    navigateRequested = pyqtSignal(str)
    transactionSelected = pyqtSignal(object)

    def __init__(self, context: PageContext, parent: QWidget | None = None) -> None:
        """Initialize the BasePage instance."""
        super().__init__(parent)
        self.context = context
        self.service = context.service
        self.settings = context.settings
        self.themes = context.themes
        self.config = context.config
        self._loaded = False
        self._refreshing = False

    def tr_text(self, text: str) -> str:
        """Translate dynamic page text through the shared manager."""
        if self.context.translations is None:
            return text
        return self.context.translations.tr(text)

    def protect(self, *widgets, radius: float = 9.0) -> None:
        """Register statistics widgets with the global privacy manager."""
        if self.context.privacy is not None:
            self.context.privacy.register(*widgets, radius=radius)

    def protect_table(self, table, columns) -> None:
        """Cover amount columns while keeping dates, types and labels readable."""
        if self.context.privacy is not None:
            self.context.privacy.register_table(table, columns)

    @property
    def tokens(self) -> dict[str, str]:
        """Current theme tokens."""
        return self.themes.tokens

    def activate(self) -> None:
        """Called when the page becomes visible."""
        if not self._loaded:
            self.refresh()

    def deactivate(self) -> None:
        """Called when another page becomes visible."""

    def refresh(self) -> None:
        """Reload page data. Subclasses override this."""
        self._loaded = True

    def mark_stale(self) -> None:
        """Force a refresh on the next activation."""
        self._loaded = False

    def begin_refresh(self) -> bool:
        """Return False when a refresh is already running."""
        if self._refreshing:
            return False
        self._refreshing = True
        self.busyChanged.emit(True)
        return True

    def end_refresh(self, success: bool = True) -> None:
        """Finish a refresh started with begin_refresh."""
        self._refreshing = False
        self.busyChanged.emit(False)
        if success:
            self._loaded = True

    def notify(self, text: str, timeout: int = 4500) -> None:
        """Send a transient message to the main window."""
        self.statusMessage.emit(text, timeout)

    def fail(self, error: BaseException | str) -> None:
        """Report an error without breaking the page."""
        text = error if isinstance(error, str) else humanize_error(error)
        self.errorRaised.emit(text)

    def ask(
        self,
        title: str,
        message: str,
        on_accept,
        accept_text: str = "Продолжить",
        danger: bool = False,
    ) -> None:
        """Ask for confirmation without leaving the main window."""
        host = self.window()
        confirm = getattr(host, "confirm", None)
        if callable(confirm):
            confirm(title, message, on_accept, accept_text, danger)
            return
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            on_accept()

    def format_value(self, value: Any) -> str:
        """Small shortcut used by table builders."""
        return str(value)


class ScrollPage(BasePage):
    """Base page that places its content inside a scroll area."""

    def __init__(self, context: PageContext, parent: QWidget | None = None) -> None:
        """Initialize the ScrollPage instance."""
        super().__init__(context, parent)
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setObjectName("Scroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("Page")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(24, 18, 24, 24)
        self.body.setSpacing(16)
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll)

    def add_stretch(self) -> None:
        """Push the content upwards when the viewport is taller."""
        self.body.addStretch(1)
