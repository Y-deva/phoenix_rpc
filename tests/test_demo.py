"""The demo backend must satisfy the real page contracts."""

from decimal import Decimal

from phoenix_gui.core.formatting import COIN
from phoenix_gui.demo import DemoService
from phoenix_gui.rpc.service import balance_summary, derive_addresses


def test_demo_initial_balances(demo: DemoService):
    utxos = demo.list_unspent()
    history = demo.list_transactions()
    addresses = demo.list_addresses()
    summary = balance_summary(utxos, history, addresses)
    assert summary.available == Decimal("19.77")
    assert summary.immature == Decimal("1.50")
    assert summary.address_count == 4
    assert summary.utxo_count == 6


def test_demo_history_categories(demo: DemoService):
    history = demo.list_transactions(count=100)
    assert len(history) == 12
    assert {tx.category for tx in history} >= {
        "receive",
        "send",
        "generate",
        "immature",
    }
    assert history == sorted(
        history, key=lambda tx: (tx.timestamp, tx.txid), reverse=True
    )


def test_demo_new_address_and_send(demo: DemoService):
    address = demo.new_address("Тест")
    assert address
    before = demo.balance()
    txid = demo.send_to_address(address, Decimal("1"))
    assert len(txid) == 64
    assert demo.balance() < before
    assert demo.list_transactions()[0].category == "send"


def test_demo_expert_roundtrip(demo: DemoService):
    raw = demo.create_raw_transaction(
        [(demo.list_unspent()[0].txid, 0)],
        {"2NRecipient": Decimal("1")},
        "68656c6c6f",
    )
    signed = demo.sign_raw_transaction(raw)
    assert signed.complete
    txid = demo.send_raw_transaction(signed.hex)
    assert txid


def test_derive_addresses_fallback(demo: DemoService):
    addresses = derive_addresses(demo.list_unspent(), demo.list_transactions())
    assert addresses
    assert all(item.address for item in addresses)


def test_demo_fee_uses_base_units(demo: DemoService):
    assert demo.fee_amount(1000, 1) == Decimal(1000) / COIN


def test_demo_pstore_roundtrip(demo: DemoService, tmp_path):
    source = tmp_path / "demo.txt"
    source.write_text("demo pstore", encoding="utf-8")
    result = demo.pstore(str(source), "comment")
    assert len(result["file_id"]) == 64
    assert result["size"] > 0
    download = demo.pload(result["file_id"], "txt")
    assert download["path"].endswith(".txt")
    assert demo.pcancel()["cancelled"] == 0
