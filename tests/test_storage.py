"""Storage page error presentation tests."""

from __future__ import annotations

from phoenix_gui.rpc.client import RPCError
from phoenix_gui.settings import Settings
from phoenix_gui.ui.pages.base import PageContext
from phoenix_gui.ui.pages.storage import StoragePage
from phoenix_gui.ui.widgets.theme import ThemeManager


class FakeService:
    """Storage actions are not started by these tests."""


def make_page(qtbot, qapp, settings: Settings, project) -> StoragePage:
    """Build a visible storage page with a minimal context."""
    themes = ThemeManager(settings, qapp)
    themes.apply("novacoin")
    page = StoragePage(
        PageContext(
            service=FakeService(), settings=settings, themes=themes, config=project
        )
    )
    qtbot.addWidget(page)
    page.resize(1000, 800)
    page.show()
    return page


def test_storage_download_error_is_humanized(
    qtbot, qapp, settings: Settings, project
) -> None:
    """Raw daemon errors must not be shown as the primary user message."""
    page = make_page(qtbot, qapp, settings, project)
    page._download_failed(RPCError("no suitable UTXO to split"))
    assert "подтвержденный вход" in page.download_status.text()


def test_storage_cancel_error_is_visible_and_humanized(
    qtbot, qapp, settings: Settings, project
) -> None:
    """A failed cancel should leave an actionable message instead of a toast only."""
    page = make_page(qtbot, qapp, settings, project)
    page._cancel_failed(RPCError("Read timed out"))
    assert page.cancel_status.isVisible()
    assert "синхронизация" in page.cancel_status.text()
