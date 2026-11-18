"""Receive page address generation and account grouping."""

from __future__ import annotations

from decimal import Decimal

from phoenix_gui.rpc.models import AddressInfo
from phoenix_gui.settings import Settings
from phoenix_gui.ui.pages.base import PageContext
from phoenix_gui.ui.pages.receive import ReceivePage
from phoenix_gui.ui.widgets.theme import ThemeManager


class EmptyReceiveService:
    """Minimal service that starts without any generated address."""

    def __init__(self) -> None:
        """Create an empty address store."""
        self.addresses: list[AddressInfo] = []
        self.created_accounts: list[str] = []

    def available_addresses(self) -> list[AddressInfo]:
        """Return the current address list."""
        return list(self.addresses)

    def new_address(self, account: str = "") -> str:
        """Create a deterministic address and remember its account."""
        self.created_accounts.append(account)
        address = f"2NReceive{len(self.addresses) + 1:04d}"
        self.addresses.append(
            AddressInfo(
                address=address,
                account=account or "Основной",
                balance=Decimal("0"),
                utxo_count=0,
                tx_count=0,
            )
        )
        return address


def make_page(qtbot, qapp, settings: Settings, project, service) -> ReceivePage:
    """Build a visible receive page backed by the supplied service."""
    themes = ThemeManager(settings, qapp)
    themes.apply("novacoin")
    context = PageContext(
        service=service,
        settings=settings,
        themes=themes,
        config=project,
    )
    page = ReceivePage(context)
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    return page


def test_receive_page_auto_creates_first_address(
    qtbot, qapp, settings: Settings, project
) -> None:
    """An empty wallet should not leave the QR panel blank."""
    service = EmptyReceiveService()
    page = make_page(qtbot, qapp, settings, project, service)
    page.refresh()
    qtbot.waitUntil(lambda: len(service.addresses) == 1, timeout=2500)
    qtbot.waitUntil(
        lambda: page.address_label.text().startswith("2NReceive"), timeout=2500
    )
    assert service.created_accounts == ["Основной"]
    assert page.table.rowCount() == 1
    assert page.qr._matrix


def test_receive_generate_and_create_account(
    qtbot, qapp, settings: Settings, project
) -> None:
    """The new-address and new-account buttons must pass account names safely."""
    service = EmptyReceiveService()
    page = make_page(qtbot, qapp, settings, project, service)
    page.refresh()
    qtbot.waitUntil(lambda: len(service.addresses) == 1, timeout=2500)
    qtbot.waitUntil(page.generate_button.isEnabled, timeout=2500)

    page.generate_button.click()
    qtbot.waitUntil(lambda: len(service.addresses) == 2, timeout=2500)

    page.account_input.setText("Работа")
    page.create_account_button.click()
    qtbot.waitUntil(lambda: len(service.addresses) == 3, timeout=2500)
    qtbot.waitUntil(lambda: page.account_filter.count() == 3, timeout=2500)

    assert service.created_accounts == ["Основной", "", "Работа"]
    assert [
        page.account_filter.itemText(i) for i in range(page.account_filter.count())
    ] == [
        "Все счета",
        "Основной",
        "Работа",
    ]
    assert page.table.rowCount() == 3
