"""In-window sheet host and confirmation helpers."""

from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel


def test_sheet_host_shows_and_closes_content(window) -> None:
    """A widget opened through the host must stay inside the main window."""
    content = QLabel("Встроенная панель")
    window.show_sheet(content)
    assert content.isVisible()
    assert window.sheet_host.isVisible()
    window.close_sheet()
    assert not window.sheet_host.isVisible()


def test_confirm_sheet_calls_callback_once(window) -> None:
    """Confirming a destructive action must invoke the callback."""
    calls: list[bool] = []
    window.confirm(
        "Удалить запись",
        "Действие необратимо.",
        lambda: calls.append(True),
        "Удалить",
        True,
    )
    assert window.sheet_host.isVisible()
    window.sheet_host.current_widget.confirmed.emit()
    window.close_sheet()
    assert calls == [True]


def test_about_sheet_is_embedded(window) -> None:
    """About information uses the same sheet host instead of a dialog."""
    window.show_about()
    assert window.sheet_host.isVisible()
    assert window.sheet_host.current_widget is not None
    window.close_sheet()
    assert not window.sheet_host.isVisible()


def test_closing_password_sheet_reports_cancellation(window) -> None:
    """Escape/scrim close must run the dialog's cancellation callback."""
    results: list[bool] = []
    window._wallet_password = ""
    window._ensure_wallet_password(results.append)
    assert window.sheet_host.isVisible()
    window.close_sheet()
    assert results == [False]


def test_connection_network_labels_are_stored(qtbot) -> None:
    """The network card must keep all value labels addressable."""
    from phoenix_gui.ui.dialogs.connection import ConnectionDialog

    host = SimpleNamespace(
        daemon_process=None,
        proxy_process=None,
        demo=True,
        online=False,
        translations=None,
        themes=None,
        settings=SimpleNamespace(
            effective_proxy=lambda: ("http://127.0.0.1:16666", "", "")
        ),
        start_daemon_backend=lambda: None,
        restart_daemon_backend=lambda: None,
        stop_daemon_backend=lambda: None,
        start_proxy_backend=lambda: None,
        stop_proxy_backend=lambda: None,
        restart_proxy_backend=lambda: None,
        start_all_backends=lambda: None,
        check_connection_now=lambda: None,
    )
    dialog = ConnectionDialog(host, None)
    qtbot.addWidget(dialog)
    dialog._set_network(
        {
            "blocks": 100,
            "connections": 4,
            "difficulty": 1.5,
            "hashrate": 2_000_000_000,
            "mining": False,
        }
    )
    assert dialog.network_values["blocks"].text() == "100"
    assert dialog.network_values["connections"].text() == "4"
    assert dialog.network_values["mining"].text() == "Нет"


def test_connection_close_button_removes_scrim(window) -> None:
    """Closing a sheet via its own Close button must hide the dim layer."""
    window.open_connection_dialog()
    dialog = window._connection_dialog
    assert dialog is not None
    dialog.close_button.click()
    assert not window.sheet_host.isVisible()
    assert not window.sheet_host.scrim.isVisible()
    assert window.sheet_host.current_widget is None
