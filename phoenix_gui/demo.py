"""In-memory wallet service used by ``--demo`` and interface tests.

The demo keeps every model type intact, so pages behave exactly as they do
against the real proxy, but no daemon, network or keychain is touched.
"""

from __future__ import annotations

import hashlib
import json
import time
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .core.formatting import COIN
from .core.validation import address_from_hash
from .rpc.models import (
    AddressInfo,
    ChainInfo,
    NetworkInfo,
    SignResult,
    Transaction,
    Utxo,
)


def _txid(seed: str) -> str:
    """Return a deterministic hexadecimal transaction id."""
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _address(seed: str) -> str:
    """Return a deterministic testnet P2SH address."""
    payload = hashlib.sha256(seed.encode("utf-8")).digest()[:20]
    return address_from_hash(payload, testnet=True, p2sh=True)


class DemoService:
    """A small, believable wallet with no external dependencies."""

    addresses_supported = True

    def __init__(self) -> None:
        """Initialize the DemoService instance."""
        now = int(time.time())
        self._now = now
        self._addresses = [
            AddressInfo(
                address=_address(f"address-{index}"),
                account="Основной" if index < 2 else "Сбережения",
                counter=index,
                created_at=now - 86400 * (30 - index),
            )
            for index in range(4)
        ]
        amounts = (
            Decimal("12.50000000"),
            Decimal("4.25000000"),
            Decimal("2.00000000"),
            Decimal("0.85000000"),
            Decimal("0.12000000"),
            Decimal("0.05000000"),
        )
        self._utxos = [
            Utxo(
                txid=_txid(f"utxo-{index}"),
                vout=index % 2,
                address=self._addresses[index % len(self._addresses)].address,
                amount=amount,
                confirmations=120 + index * 37,
                script_pubkey="76a914" + "00" * 20 + "88ac",
                spendable=True,
            )
            for index, amount in enumerate(amounts)
        ]
        self._transactions = self._build_history(now)
        self._pending_raw: dict[str, Any] | None = None
        self._refresh_address_totals()

    def _build_history(self, now: int) -> list[Transaction]:
        """Create a month of transactions with Russian categories."""
        templates = (
            ("receive", Decimal("12.50000000"), 7200, 120, "Пополнение"),
            ("send", Decimal("-3.25000000"), 10800, 98, "Оплата сервера"),
            ("generate", Decimal("2.00000000"), 86400, 90, "Награда за блок"),
            ("consolidate", Decimal("-0.85000000"), 172800, 72, "Объединение входов"),
            ("receive", Decimal("0.42000000"), 259200, 61, "Возврат средств"),
            ("send", Decimal("-1.10000000"), 345600, 48, "Подписка"),
            ("immature", Decimal("1.50000000"), 432000, 3, "Не созрело"),
            ("receive", Decimal("4.25000000"), 518400, 35, "Продажа"),
            ("send", Decimal("-0.05000000"), 604800, 20, "Комиссия сети"),
            ("generate", Decimal("0.78000000"), 691200, 12, "Награда PoS"),
            ("receive", Decimal("2.00000000"), 777600, 9, "Перевод"),
            ("consolidate", Decimal("-0.30000000"), 864000, 4, "Слияние"),
        )
        result: list[Transaction] = []
        for index, (category, amount, age, confirmations, comment) in enumerate(
            templates
        ):
            address = self._addresses[index % len(self._addresses)].address
            result.append(
                Transaction(
                    txid=_txid(f"tx-{index}"),
                    category=category,
                    amount=amount,
                    fee=Decimal("0.00012000") if amount < 0 else Decimal("0"),
                    address=address,
                    account="Основной",
                    confirmations=confirmations,
                    block_height=2_456_000 - index * 17,
                    timestamp=now - age,
                    comment=comment,
                    raw={
                        "txid": _txid(f"tx-{index}"),
                        "category": category,
                        "amount": float(amount),
                        "confirmations": confirmations,
                        "comment": comment,
                    },
                )
            )
        return result

    def _refresh_address_totals(self) -> None:
        """Recompute per-address balances for the receive table."""
        updated: list[AddressInfo] = []
        for item in self._addresses:
            matching = [utxo for utxo in self._utxos if utxo.address == item.address]
            updated.append(
                AddressInfo(
                    address=item.address,
                    account=item.account,
                    counter=item.counter,
                    created_at=item.created_at,
                    balance=sum((utxo.amount for utxo in matching), Decimal("0")),
                    utxo_count=len(matching),
                    tx_count=sum(
                        1
                        for tx in self._transactions
                        if tx.address == item.address or tx.category == "consolidate"
                    ),
                    raw=item.raw,
                )
            )
        self._addresses = updated

    def network_info(self) -> NetworkInfo:
        """Return a stable testnet snapshot."""
        return NetworkInfo(
            version=1_200_000,
            protocol_version=70015,
            blocks=2_456_789,
            connections=12,
            difficulty=Decimal("18432.55"),
            testnet=True,
            relay_fee=Decimal("0.00001000"),
            raw={
                "version": 1_200_000,
                "protocolversion": 70015,
                "blocks": 2_456_789,
                "connections": 12,
                "difficulty": 18432.55,
                "testnet": True,
                "relayfee": 0.00001,
                "generate": True,
            },
        )

    def chain_info(self) -> ChainInfo:
        """Return a fully synchronized chain."""
        return ChainInfo(
            blocks=2_456_789,
            headers=2_456_789,
            verification_progress=Decimal("1"),
            initial_block_downloading=False,
            chain="test",
        )

    def list_unspent(
        self,
        minconf: int = 0,
        maxconf: int = 9_999_999,
        addresses: Sequence[str] | None = None,
    ) -> list[Utxo]:
        """Filter demo outputs like the proxy does."""
        selected = set(addresses or ())
        return [
            utxo
            for utxo in self._utxos
            if minconf <= utxo.confirmations <= maxconf
            and (not selected or utxo.address in selected)
        ]

    def list_transactions(
        self, count: int = 300, offset: int = 0, account: str = ""
    ) -> list[Transaction]:
        """Return history newest first with optional account filtering."""
        items = [
            tx for tx in self._transactions if not account or tx.account == account
        ]
        items.sort(key=lambda tx: (tx.timestamp, tx.txid), reverse=True)
        start = max(0, offset)
        return items[start : start + max(1, min(1000, count))]

    def list_addresses(self) -> list[AddressInfo]:
        """Return generated and derived addresses."""
        return list(self._addresses)

    def balance(self, transactions: object = None) -> Decimal:
        """Sum spendable outputs."""
        return sum(
            (utxo.amount for utxo in self._utxos if utxo.spendable), Decimal("0")
        )

    def new_address(self, account: str = "") -> str:
        """Create a deterministic address for the demo wallet."""
        index = len(self._addresses)
        address = _address(f"address-{index}")
        self._addresses.append(
            AddressInfo(
                address=address,
                account=account or "Основной",
                counter=index,
                created_at=int(time.time()),
            )
        )
        return address

    def send_to_address(self, address: str, amount: Decimal, comment: str = "") -> str:
        """Create a pending outgoing transaction and adjust one input."""
        value = Decimal(str(amount))
        fee = self.fee_amount(300, 1)
        txid = _txid(f"sent-{time.time()}-{address}-{value}")
        for index, utxo in enumerate(self._utxos):
            if utxo.amount >= value + fee:
                self._utxos[index] = Utxo(
                    txid=utxo.txid,
                    vout=utxo.vout,
                    address=utxo.address,
                    amount=(utxo.amount - value - fee).quantize(Decimal("0.00000001")),
                    confirmations=utxo.confirmations,
                    script_pubkey=utxo.script_pubkey,
                    spendable=utxo.spendable,
                    raw=utxo.raw,
                )
                break
        self._transactions.insert(
            0,
            Transaction(
                txid=txid,
                category="send",
                amount=-value,
                fee=fee,
                address=address,
                account="Основной",
                confirmations=0,
                block_height=None,
                timestamp=int(time.time()),
                comment=comment,
            ),
        )
        self._refresh_address_totals()
        return txid

    def sign_raw_transaction(self, raw_hex: str) -> SignResult:
        """Pretend to sign every demo input."""
        return SignResult(
            hex=raw_hex,
            complete=True,
            signed_inputs=1,
            unsigned_inputs=0,
            raw={"hex": raw_hex, "complete": True},
        )

    def create_raw_transaction(
        self,
        inputs: Sequence[tuple[str, int]],
        outputs: Mapping[str, Decimal],
        data_hex: str = "",
    ) -> str:
        """Return a deterministic pseudo-raw transaction."""
        payload = {
            "inputs": [list(item) for item in inputs],
            "outputs": {key: str(value) for key, value in outputs.items()},
            "data": data_hex,
        }
        self._pending_raw = payload
        return "00" + json.dumps(payload, sort_keys=True).encode("utf-8").hex()

    def send_raw_transaction(self, raw_hex: str) -> str:
        """Broadcast a demo transaction and update the in-memory wallet."""
        txid = _txid(raw_hex)
        payload = self._pending_raw
        self._pending_raw = None
        if payload is None:
            return txid
        input_keys = {(str(item[0]), int(item[1])) for item in payload["inputs"]}
        spent = [utxo for utxo in self._utxos if (utxo.txid, utxo.vout) in input_keys]
        total_in = sum((utxo.amount for utxo in spent), Decimal("0"))
        outputs = {
            address: Decimal(value) for address, value in payload["outputs"].items()
        }
        self._utxos = [
            utxo for utxo in self._utxos if (utxo.txid, utxo.vout) not in input_keys
        ]
        if outputs:
            recipient, amount = next(iter(outputs.items()))
            fee = max(Decimal("0"), total_in - sum(outputs.values(), Decimal("0")))
            self._transactions.insert(
                0,
                Transaction(
                    txid=txid,
                    category="send",
                    amount=-amount,
                    fee=fee.quantize(Decimal("0.00000001")),
                    address=recipient,
                    account="Основной",
                    confirmations=0,
                    block_height=None,
                    timestamp=int(time.time()),
                    comment="Экспертная отправка",
                ),
            )
        self._refresh_address_totals()
        return txid

    def get_raw_transaction(self, txid: str, verbose: bool = True) -> Any:
        """Return a minimal raw transaction description."""
        payload = {"txid": txid, "confirmations": 0, "hex": "00"}
        return payload if verbose else "00"

    def decode_raw_transaction(self, raw_hex: str) -> dict[str, Any]:
        """Return a minimal decoded transaction."""
        return {
            "txid": _txid(raw_hex),
            "size": len(raw_hex) // 2,
            "vin": [],
            "vout": [],
        }

    def available_addresses(self) -> list[AddressInfo]:
        """Return addresses for receive and expert flows."""
        return list(self._addresses)

    def fee_amount(self, size_bytes: int, sat_per_byte: int) -> Decimal:
        """Convert a byte estimate to an NVC amount."""
        return (
            Decimal(max(0, size_bytes)) * Decimal(max(0, sat_per_byte)) / COIN
        ).quantize(Decimal("0.00000001"))
