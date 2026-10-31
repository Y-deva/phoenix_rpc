"""In-window sheet host used instead of separate application windows."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt, QEvent, QObject, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SheetHost(QWidget):
    """Display dialogs as sheets inside the main window.

    The host owns a dimmed backdrop and a centered panel. Existing QDialog
    classes can be reused unchanged: they are reparented as widget children
    and their ``finished`` signal closes the sheet.
    """

    def __init__(self, parent: QWidget) -> None:
        """Create a hidden sheet layer over the parent widget."""
        super().__init__(parent)
        self.setObjectName("SheetLayer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._widget: QWidget | None = None
        self._on_closed: Callable[[], None] | None = None
        self._closed = True
        self._build()
        self.hide()
        QShortcut(QKeySequence("Escape"), self, activated=self.close_sheet)

    def _build(self) -> None:
        """Create the scrim, centered panel and empty content layout."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.panel = QFrame()
        self.panel.setObjectName("SheetPanel")
        self.panel.setMaximumWidth(880)
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)
        row.addWidget(self.panel)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.scrim = QFrame(self)
        self.scrim.setObjectName("SheetScrim")
        self.scrim.installEventFilter(self)
        self.scrim.lower()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Close the sheet when the dimmed area is clicked."""
        if watched is self.scrim and event.type() == QEvent.Type.MouseButtonPress:
            self.close_sheet()
            return True
        return super().eventFilter(watched, event)

    def show_sheet(
        self, widget: QWidget, on_closed: Callable[[], None] | None = None
    ) -> None:
        """Show a dialog or page widget inside the main window."""
        self.close_sheet()
        if isinstance(widget, QDialog):
            widget.setWindowFlags(Qt.WindowType.Widget)
            widget.setModal(False)
            widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            widget.finished.connect(lambda _code: self.close_sheet())
        widget.setParent(self.panel)
        self.panel_layout.addWidget(widget)
        widget.show()
        widget.setFocus()
        self._widget = widget
        self._on_closed = on_closed
        self._closed = False
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.scrim.setGeometry(self.rect())
        self.scrim.show()
        self.scrim.lower()
        self.panel.raise_()

    @property
    def current_widget(self) -> QWidget | None:
        """Return the widget currently hosted in the sheet."""
        return self._widget

    def close_sheet(self) -> None:
        """Remove the current sheet and return focus to the page."""
        if self._closed:
            return
        self._closed = True
        widget = self._widget
        self._widget = None
        if widget is not None:
            # Close embedded QDialogs through reject() so their finished
            # handlers run (password dialogs rely on it for cancellation).
            if (
                isinstance(widget, QDialog)
                and widget.result() != QDialog.DialogCode.Accepted
            ):
                widget.reject()
            self.panel_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        callback = self._on_closed
        self._on_closed = None
        self.hide()
        if callback is not None:
            callback()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep the layer covering the whole parent and fit the panel."""
        super().resizeEvent(event)
        self.scrim.setGeometry(self.rect())
        if self.parentWidget() is not None:
            self.panel.setMaximumHeight(max(300, self.parentWidget().height() - 80))


class ConfirmSheet(QWidget):
    """Small in-window confirmation panel."""

    confirmed = pyqtSignal()

    def __init__(
        self,
        title: str,
        message: str,
        accept_text: str = "Продолжить",
        cancel_text: str = "Отмена",
        danger: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        """Build a compact confirmation prompt."""
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setObjectName("DialogTitle")
        heading.setWordWrap(True)
        body = QLabel(message)
        body.setObjectName("Muted")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        cancel = QPushButton(cancel_text)
        cancel.setObjectName("GhostButton")
        accept = QPushButton(accept_text)
        accept.setObjectName("DangerButton" if danger else "AccentButton")
        accept.setDefault(True)
        cancel.clicked.connect(self._cancel)
        accept.clicked.connect(self.confirmed.emit)
        actions.addWidget(cancel)
        actions.addWidget(accept)
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addLayout(actions)

    def _cancel(self) -> None:
        """Ask the host to close the panel."""
        host = self.parent()
        while host is not None and not hasattr(host, "close_sheet"):
            host = host.parent()
        if host is not None:
            host.close_sheet()


class AboutSheet(QWidget):
    """Compact in-window product information panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the About panel."""
        from ... import __app_name__, __version__

        super().__init__(parent)
        from .icons import brand_logo

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 22)
        layout.setSpacing(12)
        logo = QLabel()
        pixmap = brand_logo(64)
        if not pixmap.isNull():
            logo.setPixmap(pixmap)
        title = QLabel(f"{__app_name__} {__version__}")
        title.setObjectName("DialogTitle")
        subtitle = QLabel("Графический кошелек Phoenix на базе NovaCoin")
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        description = QLabel(
            "Локальный демон novacoind работает под капотом, а обмен данными "
            "идет через локальный прокси. Ключи и пароли не покидают компьютер."
        )
        description.setObjectName("Text")
        description.setWordWrap(True)
        close = QPushButton("Закрыть")
        close.setObjectName("AccentButton")
        close.setDefault(True)
        close.clicked.connect(self._close)
        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(description)
        layout.addStretch(1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)

    def _close(self) -> None:
        """Ask the host to close the panel."""
        host = self.parent()
        while host is not None and not hasattr(host, "close_sheet"):
            host = host.parent()
        if host is not None:
            host.close_sheet()
