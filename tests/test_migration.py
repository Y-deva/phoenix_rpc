"""Tests for legacy wallet migration helpers and the migration dialog."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from phoenix_gui.core import migration
from phoenix_gui.core.config import ProjectConfig
from phoenix_gui.core.migration import (
    import_wif,
    import_wif_keys,
    sweep_all,
    validate_destination,
    validate_wif,
)
from phoenix_gui.core.validation import address_from_hash
from phoenix_gui.settings import Settings
from phoenix_gui.ui.dialogs.migration import MigrationDialog


class FakeClient:
    """Small RPC double that records migration operations."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []
        self.closed = False

    def call(self, method: str, params: list[object] | None = None) -> object:
        """Return deterministic daemon data for the tested methods."""
        self.calls.append((method, list(params or [])))
        if method == "getbalance":
            return 2.5
        if method == "listunspent":
            return [
                {"address": "2NEm3TqQp8", "amount": 1.5},
                {"address": "2NEm3TqQp8", "amount": 1.0},
            ]
        if method == "sendtoaddress":
            return "ab" * 32
        return True

    def close(self) -> None:
        """Mark the fake client as closed."""
        self.closed = True


@pytest.fixture
def project(tmp_path: Path) -> ProjectConfig:
    """Create a minimal mainnet project configuration."""
    return ProjectConfig(root=tmp_path)


def test_validate_wif_rejects_bad_shapes() -> None:
    """Empty, short and spaced keys are rejected before RPC."""
    with pytest.raises(ValueError):
        validate_wif("")
    with pytest.raises(ValueError):
        validate_wif("5short")
    with pytest.raises(ValueError):
        validate_wif("5" * 25 + " " + "5" * 25)


def test_validate_destination_checks_network(project: ProjectConfig) -> None:
    """A testnet address is refused for a mainnet project."""
    mainnet = address_from_hash(b"\x01" * 20)
    testnet = address_from_hash(b"\x01" * 20, testnet=True)
    assert validate_destination(mainnet, project) == mainnet
    with pytest.raises(ValueError):
        validate_destination(testnet, project)


def test_import_wif_reports_balance_and_inputs(
    monkeypatch, project: ProjectConfig
) -> None:
    """Importing a WIF returns a report built from daemon data."""
    client = FakeClient()
    monkeypatch.setattr(migration, "_direct_client", lambda _project: client)

    report = import_wif(project, "5" * 51)

    assert report.source == "wif"
    assert report.balance == Decimal("2.5")
    assert report.inputs == 2
    assert report.keys == 1
    assert client.calls[0][0] == "importprivkey"
    assert client.closed is True


def test_sweep_all_reserves_fee_and_uses_destination(
    monkeypatch, project: ProjectConfig
) -> None:
    """The sweep sends almost the whole balance to a validated address."""
    client = FakeClient()
    monkeypatch.setattr(migration, "_direct_client", lambda _project: client)
    destination = address_from_hash(b"\x02" * 20)

    txid, amount = sweep_all(project, destination)

    assert txid == "ab" * 32
    assert amount == Decimal("2.499")
    assert client.calls[-1][0] == "sendtoaddress"
    assert client.calls[-1][1][0] == destination
    assert client.closed is True


def test_migration_dialog_validates_empty_wif(qtbot, project: ProjectConfig) -> None:
    """The dialog shows a friendly validation error before starting a worker."""
    settings = Settings(project.root / "settings.ini")
    dialog = MigrationDialog(project, settings, {})
    qtbot.addWidget(dialog)
    dialog.show()

    dialog._scan()

    assert "Введите" in dialog.result_label.text()
    assert dialog.sweep_button.isEnabled() is False


def test_migration_dialog_switches_sources(qtbot, project: ProjectConfig) -> None:
    """Switching between WIF and wallet.dat resets the staged report."""
    settings = Settings(project.root / "settings.ini")
    dialog = MigrationDialog(project, settings, {})
    qtbot.addWidget(dialog)

    dialog.mode.set_value("wallet")
    dialog._on_mode_changed("wallet")

    assert dialog.pages.currentIndex() == 2
    assert dialog.sweep_button.isEnabled() is False


def test_import_wif_keys_rescans_once(monkeypatch, project: ProjectConfig) -> None:
    """A batch import delays the expensive rescan until the last key."""
    client = FakeClient()
    monkeypatch.setattr(migration, "_direct_client", lambda _project: client)

    report = import_wif_keys(project, ["5" * 51, "5" * 50, "5" * 50])

    imports = [call for call in client.calls if call[0] == "importprivkey"]
    assert len(imports) == 2
    assert [call[1][2] for call in imports] == [False, True]
    assert report.keys == 2
    assert client.closed is True


def test_migration_dialog_manual_route_copies_address(
    qtbot, project: ProjectConfig
) -> None:
    """The manual route explains the legacy-client transfer and copies it."""
    settings = Settings(project.root / "settings.ini")
    destination = address_from_hash(b"" * 20)
    dialog = MigrationDialog(project, settings, {}, destination=destination)
    qtbot.addWidget(dialog)

    dialog._show_manual()

    assert not dialog.manual_hint.isHidden()
    assert destination in dialog.manual_hint.text()
    assert QApplication.clipboard().text() == destination
