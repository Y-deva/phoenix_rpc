"""Coin selection and fee planning mirror the proxy's rules."""

from decimal import Decimal

import pytest

from phoenix_gui.core.coinselect import (
    InsufficientFunds,
    estimate_fee,
    estimate_tx_size,
    plan_send,
    select_coins,
)
from phoenix_gui.rpc.models import Utxo


def utxo(
    amount: str, vout: int = 0, confirmations: int = 10, spendable: bool = True
) -> Utxo:
    """Build a compact UTXO for selection tests."""
    return Utxo(
        txid=f"{vout:064x}",
        vout=vout,
        address="2NExampleAddress",
        amount=Decimal(amount),
        confirmations=confirmations,
        script_pubkey="00",
        spendable=spendable,
    )


def test_size_and_fee_formula():
    assert estimate_tx_size(1, 1) == 50 + 1800 + 34 + 34
    assert estimate_tx_size(2, 2, has_op_return=True) == 50 + 3600 + 68 + 15 + 34
    assert estimate_fee(1000, 2) == Decimal("0.00200000")


def test_exact_single_selection():
    result = select_coins([utxo("1"), utxo("2"), utxo("3")], Decimal("2"))
    assert result.found
    assert result.total == Decimal("2")
    assert result.strategy == "exact_single"


def test_min_single_selection():
    result = select_coins([utxo("1"), utxo("5"), utxo("9")], Decimal("3"))
    assert result.found
    assert result.total == Decimal("5")
    assert result.strategy == "min_single"


def test_greedy_descending_selection():
    result = select_coins([utxo("1"), utxo("2"), utxo("3")], Decimal("4"))
    assert result.found
    assert result.strategy == "greedy_desc"
    assert result.total >= Decimal("4")


def test_unconfirmed_outputs_are_excluded_when_requested():
    only_confirmed = [utxo("1", confirmations=10), utxo("5", confirmations=0)]
    result = select_coins(only_confirmed, Decimal("4"), only_confirmed=True)
    assert not result.found
    assert all(item.confirmed for item in result.selected)
    assert result.shortfall == Decimal("3")


def test_plan_send_reports_insufficient_funds():
    with pytest.raises(InsufficientFunds) as info:
        plan_send([utxo("1")], Decimal("2"))
    assert "Нужно" in str(info.value)


def test_selection_reports_shortfall():
    result = select_coins([utxo("1")], Decimal("2"))
    assert not result.found
    assert result.shortfall == Decimal("1")


def test_plan_send_fee_and_change():
    plan = plan_send([utxo("5")], Decimal("1"), sat_per_byte=1)
    expected_fee = Decimal(estimate_tx_size(1, 1)) / Decimal("1000000")
    assert plan.has_change
    assert plan.fee == expected_fee
    assert plan.change == Decimal("5") - Decimal("1") - expected_fee
    assert plan.fee_sat == 1918
    outputs = plan.outputs("2NRecipient", "2NChange")
    assert outputs["2NRecipient"] == Decimal("1")
    assert outputs["2NChange"] == plan.change


def test_plan_send_with_comment_and_change():
    plain = plan_send([utxo("5")], Decimal("1"))
    commented = plan_send([utxo("5")], Decimal("1"), comment="invoice 42")
    assert commented.has_comment
    assert commented.fee > plain.fee
    assert commented.size == plain.size + 15


def test_plan_send_fixed_inputs():
    plan = plan_send(
        [utxo("2", 0), utxo("3", 1), utxo("100", 2)],
        Decimal("4"),
        fixed_inputs=[utxo("2", 0), utxo("3", 1)],
    )
    assert plan.input_count == 2
    assert plan.total_input == Decimal("5")
    assert plan.has_change


def test_dust_change_is_absorbed():
    # 5.0 input, 4.998 output leaves less than the 0.001 dust floor.
    plan = plan_send([utxo("5")], Decimal("4.998"))
    assert not plan.has_change
    assert plan.change == Decimal("0")
    assert plan.fee > Decimal(estimate_tx_size(1, 1)) / Decimal("1000000")
