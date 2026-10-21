"""Coin selection and fee estimation for the expert send flow.

The constants deliberately match ``unlock.py`` in the proxy: a Falcon
signature makes each input roughly 1800 bytes, so using Bitcoin-sized
estimates would underestimate the fee by orders of magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence

from .formatting import AMOUNT_QUANT, to_decimal
from ..rpc.models import Utxo

SIZE_OVERHEAD = 50
SIZE_PER_INPUT = 1800
SIZE_PER_P2PKH_OUTPUT = 34
SIZE_PER_OPRETURN = 15
SIZE_CHANGE_OUTPUT = 34

MONEY_PLACES = AMOUNT_QUANT


class InsufficientFunds(ValueError):
    """Raised when the selected inputs cannot cover amount plus fee."""

    def __init__(self, required: Decimal, available: Decimal) -> None:
        """Store the required and available amounts for the message."""
        super().__init__(f"Нужно {required} NVC, доступно {available} NVC")
        self.required = required
        self.available = available


@dataclass(frozen=True)
class CoinSelection:
    """Result of a coin selection strategy."""

    selected: tuple[Utxo, ...] = ()
    total: Decimal = Decimal("0")
    found: bool = False
    strategy: str = ""
    shortfall: Decimal = Decimal("0")

    @property
    def count(self) -> int:
        """Return the number of selected outputs."""
        return len(self.selected)


@dataclass(frozen=True)
class SendPlan:
    """A fee-checked transaction plan for preview and raw construction."""

    inputs: tuple[Utxo, ...]
    amount: Decimal
    fee: Decimal
    change: Decimal
    has_change: bool
    size: int
    has_comment: bool
    target: Decimal
    total_input: Decimal
    strategy: str = ""
    recipients: tuple[tuple[str, Decimal], ...] = field(default_factory=tuple)

    @property
    def input_count(self) -> int:
        """Return the number of transaction inputs."""
        return len(self.inputs)

    @property
    def fee_sat(self) -> int:
        """Return the absolute fee in base units."""
        return int((self.fee * Decimal("1000000")).to_integral_value())

    def outputs(self, recipient: str, change_address: str = "") -> dict[str, Decimal]:
        """Return the address-to-amount mapping for a raw transaction."""
        result = {recipient: self.amount}
        if self.has_change and change_address and self.change > 0:
            result[change_address] = self.change
        return result


def estimate_tx_size(
    input_count: int,
    output_count: int = 1,
    has_op_return: bool = False,
    has_change: bool = True,
) -> int:
    """Estimate the serialized transaction size in bytes."""
    size = SIZE_OVERHEAD
    size += max(0, int(input_count)) * SIZE_PER_INPUT
    size += max(0, int(output_count)) * SIZE_PER_P2PKH_OUTPUT
    if has_op_return:
        size += SIZE_PER_OPRETURN
    if has_change:
        size += SIZE_CHANGE_OUTPUT
    return size


def estimate_fee(size_bytes: int, sat_per_byte: int = 1) -> Decimal:
    """Convert a byte estimate into a coin-denominated fee."""
    sat = Decimal(max(0, int(size_bytes))) * Decimal(max(1, int(sat_per_byte)))
    return (sat / Decimal("1000000")).quantize(MONEY_PLACES)


def select_coins(
    utxos: Iterable[Utxo],
    target: Decimal,
    only_confirmed: bool = False,
    strategy: str = "auto",
) -> CoinSelection:
    """Select UTXOs using exact-single, minimum-single or greedy strategy.

    ``auto`` tries an exact match first, then the smallest sufficient
    output, then a descending greedy accumulation. This is wallet UX,
    not consensus code: the goal is to minimize fees and avoid needless
    address exposure without surprising the user.
    """
    target = to_decimal(target)
    candidates = [
        utxo
        for utxo in utxos
        if utxo.amount > 0
        and utxo.spendable
        and (utxo.confirmations >= 1 or not only_confirmed)
    ]
    if target <= 0:
        return CoinSelection(found=True, strategy="empty")
    candidates.sort(key=lambda item: item.amount, reverse=True)
    if not candidates:
        return CoinSelection(found=False, shortfall=target, strategy="none")

    def result(items: Sequence[Utxo], name: str) -> CoinSelection:
        """Return a selection for one strategy."""
        total = sum((item.amount for item in items), Decimal("0")).quantize(
            MONEY_PLACES
        )
        return CoinSelection(
            selected=tuple(items),
            total=total,
            found=total >= target,
            strategy=name,
            shortfall=max(Decimal("0"), target - total),
        )

    if strategy in {"auto", "exact_single"}:
        for utxo in candidates:
            if utxo.amount == target:
                return result([utxo], "exact_single")
        if strategy == "exact_single":
            return CoinSelection(found=False, strategy="exact_single", shortfall=target)

    if strategy in {"auto", "min_single"}:
        eligible = [utxo for utxo in candidates if utxo.amount >= target]
        if eligible:
            return result([min(eligible, key=lambda item: item.amount)], "min_single")
        if strategy == "min_single":
            return CoinSelection(found=False, strategy="min_single", shortfall=target)

    selected: list[Utxo] = []
    total = Decimal("0")
    for utxo in candidates:
        selected.append(utxo)
        total += utxo.amount
        if total >= target:
            break
    return result(selected, "greedy_desc")


def plan_send(
    utxos: Iterable[Utxo],
    amount: Decimal,
    sat_per_byte: int = 1,
    comment: str = "",
    only_confirmed: bool = False,
    fixed_inputs: Sequence[Utxo] | None = None,
    dust_threshold_sat: int = 1000,
) -> SendPlan:
    """Build a fully costed send plan.

    ``fixed_inputs`` powers expert coin control. Without it, the planner
    performs the same two-pass selection as ``unlock.handle_sendtoaddress``:
    estimate with one input, select, recompute the fee, and retry once if
    the actual input count made the transaction more expensive.
    """
    value = to_decimal(amount)
    if value <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    has_comment = bool(comment)
    dust = (Decimal(max(0, int(dust_threshold_sat))) / Decimal("1000000")).quantize(
        MONEY_PLACES
    )

    if fixed_inputs is not None:
        inputs = tuple(fixed_inputs)
        if not inputs:
            raise InsufficientFunds(value, Decimal("0"))
        total = sum((item.amount for item in inputs), Decimal("0")).quantize(
            MONEY_PLACES
        )
        size = estimate_tx_size(len(inputs), 1, has_comment, True)
        fee = estimate_fee(size, sat_per_byte)
        if total < value + fee:
            raise InsufficientFunds(value + fee, total)
        change = (total - value - fee).quantize(MONEY_PLACES)
        has_change = change >= dust
        if not has_change:
            fee += change
            change = Decimal("0")
        return SendPlan(
            inputs=inputs,
            amount=value,
            fee=fee,
            change=change,
            has_change=has_change,
            size=size,
            has_comment=has_comment,
            target=value + fee,
            total_input=total,
            strategy="fixed",
        )

    fee_guess = estimate_fee(estimate_tx_size(1, 1, has_comment, True), sat_per_byte)
    selection = select_coins(utxos, value + fee_guess, only_confirmed=only_confirmed)
    if not selection.found:
        raise InsufficientFunds(value + fee_guess, selection.total)
    size = estimate_tx_size(selection.count, 1, has_comment, True)
    fee = estimate_fee(size, sat_per_byte)
    if selection.total < value + fee:
        retry = select_coins(
            utxos,
            value + fee + dust,
            only_confirmed=only_confirmed,
        )
        if not retry.found:
            raise InsufficientFunds(value + fee, selection.total)
        selection = retry
        size = estimate_tx_size(selection.count, 1, has_comment, True)
        fee = estimate_fee(size, sat_per_byte)
    if selection.total < value + fee:
        raise InsufficientFunds(value + fee, selection.total)

    change = (selection.total - value - fee).quantize(MONEY_PLACES)
    has_change = change >= dust
    if not has_change:
        fee += change
        change = Decimal("0")
    return SendPlan(
        inputs=selection.selected,
        amount=value,
        fee=fee,
        change=change,
        has_change=has_change,
        size=size,
        has_comment=has_comment,
        target=value + fee,
        total_input=selection.total,
        strategy=selection.strategy,
    )
