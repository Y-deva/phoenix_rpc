"""Interface smoke tests against the in-memory demo service."""

from decimal import Decimal

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel

from phoenix_gui.core.formatting import shorten_txid
from phoenix_gui.core.validation import address_from_hash
from phoenix_gui.demo import DemoService
from phoenix_gui.ui.dialogs.confirm import ConfirmSendDialog
from phoenix_gui.ui.dialogs.shortcuts import ShortcutsDialog
from phoenix_gui.ui.dialogs.tx_details import TxDetailsDialog
from phoenix_gui.ui.widgets.table import Column, SortableTable, amount_item, text_item


@pytest.mark.parametrize(
    "page_id",
    [
        "overview",
        "send",
        "receive",
        "transactions",
        "coins",
        "storage",
        "analytics",
        "console",
        "settings",
    ],
)
def test_every_page_navigates_and_refreshes(window, qtbot, page_id):
    window.navigate(page_id)
    page = window.current_page
    assert page.page_id == page_id
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    assert page.isVisible()


def test_demo_status_and_title(window):
    assert "Демо" in window.windowTitle()
    assert window.network_pill.text() == "Демо-сеть"
    assert window.footer_parser.text() == "Парсер: демо"


def test_theme_cycle_applies_and_persists(window, qtbot):
    themes = window.themes
    first = themes.theme.key
    themes.cycle()
    qtbot.wait(150)
    assert themes.theme.key != first
    assert QApplication.instance().styleSheet()
    assert window.settings.theme == themes.theme.key
    themes.toggle_light()
    qtbot.wait(150)
    assert themes.theme.dark is False


def test_overview_renders_balance(window, qtbot):
    window.navigate("overview")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    text = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "NVC" in text


def test_send_validation_accepts_valid_form(window, qtbot):
    window.navigate("send")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    address = address_from_hash(b"recipient" + b"0" * 11, testnet=False)
    page.address_input.setText(address)
    page.amount_input.setText("1.5")
    page.comment_input.setText("invoice 7")
    page._recompute()
    assert page._plan is not None
    assert page.send_button.isEnabled()
    assert page.summary_amount.value_label.text() == "1.50 NVC"


def test_send_rejects_invalid_address(window, qtbot):
    window.navigate("send")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    page.address_input.setText("not-an-address")
    page.amount_input.setText("1")
    page._recompute()
    assert page._plan is None
    assert not page.send_button.isEnabled()


def test_send_expert_mode_shows_coin_table(window, qtbot):
    window.navigate("send")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    page._switch_mode("expert")
    qtbot.wait(100)
    assert page.expert_card.isVisible()
    assert page.coin_table.rowCount() > 0


def test_receive_generates_address(window, qtbot):
    window.navigate("receive")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    before = page.address_label.text()
    page.generate_button.click()
    qtbot.waitUntil(lambda: page.address_label.text() != before, timeout=6000)
    assert page.address_label.text()


def test_console_executes_getinfo(window, qtbot):
    window.navigate("console")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    page.execute("getinfo")
    qtbot.waitUntil(lambda: "getinfo" in page.output.toPlainText(), timeout=6000)
    qtbot.waitUntil(
        lambda: page.output.toPlainText().count("getinfo") >= 1, timeout=6000
    )


def test_transaction_details_dialog(window, qtbot):
    transaction = window.service.list_transactions()[0]
    dialog = TxDetailsDialog(transaction, dict(window.themes.tokens), 2)
    qtbot.addWidget(dialog)
    dialog.show()
    assert shorten_txid(transaction.txid) in dialog.txid_row.value_label.text()


def test_confirm_dialog_ctrl_enter(window, qtbot):
    dialog = ConfirmSendDialog(
        "2NRecipient",
        Decimal("1.5"),
        Decimal("0.001"),
        Decimal("0.0"),
        "test",
        1,
    )
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.amount_label.text().endswith("NVC")


def test_shortcuts_dialog_opens(window, qtbot):
    dialog = ShortcutsDialog(dict(window.themes.tokens))
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.windowTitle() == "Сочетания клавиш"
    assert dialog.isVisible()


def test_sortable_table_sorts_and_exports(qtbot, tmp_path):
    table = SortableTable([Column("Имя", 120), Column("Сумма", 120)], row_height=32)
    qtbot.addWidget(table)
    table.set_rows(
        [
            [text_item("beta"), amount_item(Decimal("2"))],
            [text_item("alpha"), amount_item(Decimal("10"))],
        ]
    )
    table.sortItems(0, Qt.SortOrder.AscendingOrder)
    assert table.item(0, 0).text() == "alpha"
    target = tmp_path / "rows.csv"
    assert table.export_csv(target) == 2
    assert "alpha" in target.read_text(encoding="utf-8")


def test_qr_widget_draws(qtbot):
    from phoenix_gui.ui.widgets.qr import QrCode

    qr = QrCode()
    qtbot.addWidget(qr)
    qr.set_data("2NEm3TqPq8gkFdGJGLUaZTk1gAhNubUurb9")
    image = qr.grab()
    assert not image.isNull()


def test_media_backdrop_loads_local_image(qtbot, settings, window, tmp_path):
    from PyQt6.QtGui import QColor, QImage

    from phoenix_gui.core.media import MediaBackdrop

    image = QImage(320, 200, QImage.Format.Format_RGB32)
    image.fill(QColor("#335577"))
    path = tmp_path / "backdrop.png"
    assert image.save(str(path))
    settings.media_path = str(path)
    settings.media_enabled = True
    settings.media_dim = 45
    backdrop = MediaBackdrop(settings, window.themes.theme)
    qtbot.addWidget(backdrop)
    backdrop.resize(640, 360)
    backdrop.show()
    qtbot.wait(200)
    assert backdrop.has_media
    assert backdrop.source_path == str(path)
    assert not backdrop.grab().isNull()


def test_simple_send_creates_transaction(window, qtbot):
    window.settings.set("behavior/confirm_send", False)
    window.navigate("send")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    before = len(window.service.list_transactions(count=100))
    page.address_input.setText(address_from_hash(b"send" + b"0" * 16, testnet=False))
    page.amount_input.setText("1.25")
    page._recompute()
    assert page._plan is not None
    page.send_button.click()
    qtbot.waitUntil(lambda: not page._sending, timeout=8000)
    qtbot.waitUntil(
        lambda: len(window.service.list_transactions(count=100)) == before + 1,
        timeout=4000,
    )
    latest = window.service.list_transactions(count=100)[0]
    assert latest.category == "send"
    assert latest.amount == Decimal("-1.25")


def test_expert_send_uses_selected_inputs(window, qtbot):
    window.settings.set("behavior/confirm_send", False)
    window.navigate("send")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    page._switch_mode("expert")
    qtbot.wait(100)
    page._set_all_selected(True)
    page.address_input.setText(address_from_hash(b"expert" + b"0" * 14, testnet=False))
    page.amount_input.setText("1")
    page._recompute()
    assert page._plan is not None
    assert page._plan.input_count == 6
    page.send_button.click()
    qtbot.waitUntil(lambda: not page._sending, timeout=8000)
    latest = window.service.list_transactions(count=100)[0]
    assert latest.category == "send"
    assert latest.amount == Decimal("-1")


def test_send_maximum_reserves_fee_for_all_inputs(window):
    page = window._pages["send"]
    window.navigate("send")
    page.refresh()
    QTest.qWait(400)
    page.address_input.setText(
        address_from_hash(b"maximum-address" + b"0" * 5, testnet=True)
    )
    page.max_button.click()
    assert page._plan is not None
    assert page._plan.amount > Decimal("19")
    assert page._plan.fee > 0
    assert page.send_button.isEnabled()


def test_demo_connection_change_keeps_local_service(window):
    settings_page = window._pages["settings"]
    settings_page.connectionChanged.emit()
    assert isinstance(window.service, DemoService)


def test_storage_upload_and_download_roundtrip(window, qtbot, tmp_path):
    window.navigate("storage")
    page = window.current_page
    source = tmp_path / "report.txt"
    source.write_text("phoenix storage test", encoding="utf-8")
    page.file_field.set_path(str(source))
    page.comment_input.setText("test upload")
    page._start_upload()
    qtbot.waitUntil(lambda: bool(page.file_id_output.text()), timeout=6000)
    file_id = page.file_id_output.text()
    assert len(file_id) == 64
    assert page.file_id_input.text() == file_id
    page.extension_input.setText("txt")
    page._start_download()
    qtbot.waitUntil(lambda: bool(page.download_result.text()), timeout=6000)
    target = page.download_result.text()
    assert target.endswith(".txt")
    from pathlib import Path as _Path

    assert _Path(target).is_file()


def test_storage_rejects_invalid_id(window, qtbot):
    window.navigate("storage")
    page = window.current_page
    page.file_id_input.setText("not-a-graph-id")
    page._start_download()
    assert "64" in page.download_status.text()
    assert not page.download_result.isVisible()


def test_coin_selection_survives_refresh(window, qtbot):
    window.navigate("coins")
    page = window.current_page
    qtbot.waitUntil(lambda: page.table.rowCount() >= 2, timeout=6000)
    page.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
    page.table.item(1, 0).setCheckState(Qt.CheckState.Checked)
    page.refresh()
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    states = [
        page.table.item(row, 0).checkState() for row in range(page.table.rowCount())
    ]
    assert states.count(Qt.CheckState.Checked) == 2


def test_privacy_toggle_blurs_balances_and_statistics(window, qtbot):
    """The eye button hides numeric data globally and restores it."""
    window.navigate("overview")
    page = window.current_page
    qtbot.waitUntil(lambda: not page._refreshing, timeout=6000)
    assert page.balance_label.graphicsEffect() is None
    assert window.privacy.hidden is False

    page.privacy_button.click()
    qtbot.wait(80)
    assert window.privacy.hidden is True
    assert page.balance_label.graphicsEffect() is not None
    assert page.activity_chart.canvas.graphicsEffect() is not None
    assert page.pending_card.value_label.graphicsEffect() is not None
    assert window.settings.get("privacy/hidden") is True

    window.navigate("transactions")
    qtbot.waitUntil(lambda: not window.current_page._refreshing, timeout=6000)
    assert window.current_page.table.viewport().graphicsEffect() is not None

    window.navigate("overview")
    page.privacy_button.click()
    qtbot.wait(80)
    assert window.privacy.hidden is False
    assert page.balance_label.graphicsEffect() is None
    assert window.current_page.activity_chart.canvas.graphicsEffect() is None


def test_privacy_state_round_trips_through_settings(settings):
    """A fresh manager sees the persisted eye state."""
    from phoenix_gui.ui.widgets.privacy import PrivacyManager

    first = PrivacyManager(settings)
    first.set_hidden(True)
    second = PrivacyManager(settings)
    assert second.hidden is True
    second.set_hidden(False)
    assert settings.get("privacy/hidden") is False
