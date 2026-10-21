"""Typed models for data returned by the Phoenix proxy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from ..core.formatting import category_kind, category_label, to_decimal


def _int(value: Any, default: int = 0) -> int:
    """Convert a loosely typed value to an integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    """Convert a loosely typed value to a stripped string."""
    return "" if value is None else str(value).strip()


@dataclass(frozen=True)
class NetworkInfo:
    """General daemon status returned by ``getinfo``."""

    version: int = 0
    protocol_version: int = 0
    blocks: int = 0
    connections: int = 0
    difficulty: Decimal = Decimal("0")
    testnet: bool = False
    relay_fee: Decimal = Decimal("0")
    errors: str = ""
    warning: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any] | None) -> "NetworkInfo":
        """Build a network snapshot from a raw RPC dictionary."""
        payload = dict(data or {})
        return cls(
            version=_int(payload.get("version")),
            protocol_version=_int(payload.get("protocolversion")),
            blocks=_int(payload.get("blocks")),
            connections=_int(payload.get("connections")),
            difficulty=to_decimal(payload.get("difficulty")),
            testnet=bool(payload.get("testnet", False)),
            relay_fee=to_decimal(payload.get("relayfee")),
            errors=_text(payload.get("errors")),
            warning=_text(payload.get("warning")),
            raw=payload,
        )

    @property
    def mining(self) -> bool:
        """Return whether the daemon reports an active miner."""
        return bool(self.raw.get("generate") or self.raw.get("mining"))

    @property
    def online(self) -> bool:
        """Return whether the daemon reports at least one block."""
        return self.blocks > 0


@dataclass(frozen=True)
class ChainInfo:
    """Synchronization status returned by ``getblockchaininfo``."""

    blocks: int = 0
    headers: int = 0
    verification_progress: Decimal = Decimal("0")
    initial_block_downloading: bool = False
    chain: str = ""

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any] | None) -> "ChainInfo":
        """Build a chain snapshot from a raw RPC dictionary."""
        payload = dict(data or {})
        progress = payload.get("verificationprogress")
        return cls(
            blocks=_int(payload.get("blocks")),
            headers=_int(payload.get("headers")),
            verification_progress=to_decimal(progress),
            initial_block_downloading=bool(payload.get("initialblockdownload", False)),
            chain=_text(payload.get("chain")),
        )

    @property
    def progress_percent(self) -> Decimal:
        """Return synchronization progress as a 0..100 value."""
        if self.headers > 0:
            value = Decimal(self.blocks) / Decimal(self.headers) * Decimal("100")
        else:
            value = self.verification_progress * Decimal("100")
        return min(Decimal("100"), max(Decimal("0"), value))

    @property
    def synced(self) -> bool:
        """Return whether the chain is effectively fully synchronized."""
        return self.headers > 0 and self.blocks >= self.headers - 1


@dataclass(frozen=True)
class Transaction:
    """One wallet transaction entry."""

    txid: str
    category: str
    amount: Decimal
    fee: Decimal = Decimal("0")
    address: str = ""
    account: str = ""
    confirmations: int = 0
    block_height: int | None = None
    timestamp: int = 0
    comment: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any]) -> "Transaction":
        """Build a transaction from a ``listtransactions`` entry."""
        payload = dict(data or {})
        timestamp = (
            _int(payload.get("blocktime"))
            or _int(payload.get("time"))
            or _int(payload.get("timereceived"))
        )
        height = payload.get("blockheight")
        return cls(
            txid=_text(payload.get("txid")),
            category=_text(payload.get("category")).lower() or "unknown",
            amount=to_decimal(payload.get("amount")),
            fee=to_decimal(payload.get("fee")),
            address=_text(payload.get("address")),
            account=_text(payload.get("account")),
            confirmations=_int(payload.get("confirmations")),
            block_height=_int(height) if height is not None else None,
            timestamp=timestamp,
            comment=_text(payload.get("comment")),
            raw=payload,
        )

    @property
    def label(self) -> str:
        """Return a human label for the transaction category."""
        return category_label(self.category)

    @property
    def kind(self) -> str:
        """Return the coarse kind used for colors and icons."""
        return category_kind(self.category)

    @property
    def is_incoming(self) -> bool:
        """Return whether the transaction added coins to the wallet."""
        return self.kind in {"receive", "mine"} and self.amount >= 0

    @property
    def is_outgoing(self) -> bool:
        """Return whether the transaction removed coins from the wallet."""
        return self.kind == "send" or self.amount < 0

    @property
    def status(self) -> str:
        """Return one of confirmed, pending, immature or conflicted."""
        if self.category == "immature":
            return "immature"
        if self.confirmations < 0:
            return "conflicted"
        if self.confirmations == 0:
            return "pending"
        return "confirmed"

    @property
    def status_label(self) -> str:
        """Return a short human status label."""
        return {
            "confirmed": "Подтверждено",
            "pending": "В обработке",
            "immature": "Не созрело",
            "conflicted": "Конфликт",
        }.get(self.status, self.status)

    @property
    def status_level(self) -> str:
        """Return the semantic pill level for this status."""
        return {
            "confirmed": "success",
            "pending": "warning",
            "immature": "warning",
            "conflicted": "danger",
        }.get(self.status, "neutral")


@dataclass(frozen=True)
class Utxo:
    """One unspent transaction output."""

    txid: str
    vout: int
    address: str = ""
    amount: Decimal = Decimal("0")
    confirmations: int = 0
    script_pubkey: str = ""
    spendable: bool = True
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any]) -> "Utxo":
        """Build a UTXO from a ``listunspent`` entry."""
        payload = dict(data or {})
        return cls(
            txid=_text(payload.get("txid")),
            vout=_int(payload.get("vout")),
            address=_text(payload.get("address")),
            amount=to_decimal(payload.get("amount")),
            confirmations=_int(payload.get("confirmations")),
            script_pubkey=_text(payload.get("scriptPubKey")),
            spendable=bool(payload.get("spendable", True)),
            raw=payload,
        )

    @property
    def key(self) -> str:
        """Return a stable identifier for Qt models."""
        return f"{self.txid}:{self.vout}"

    @property
    def confirmed(self) -> bool:
        """Return whether the output has at least one confirmation."""
        return self.confirmations >= 1


@dataclass(frozen=True)
class AddressInfo:
    """A wallet address with a summarized balance."""

    address: str
    account: str = ""
    counter: int | None = None
    created_at: int = 0
    balance: Decimal = Decimal("0")
    utxo_count: int = 0
    tx_count: int = 0
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any]) -> "AddressInfo":
        """Build an address entry from the proxy response."""
        payload = dict(data or {})
        counter = payload.get("counter")
        return cls(
            address=_text(payload.get("address")),
            account=_text(payload.get("account")),
            counter=_int(counter) if counter is not None else None,
            created_at=_int(payload.get("created_at")),
            balance=to_decimal(payload.get("balance")),
            utxo_count=_int(payload.get("utxo_count")),
            tx_count=_int(payload.get("tx_count")),
            raw=payload,
        )


@dataclass(frozen=True)
class BalanceSummary:
    """Spendable, pending and immature parts of the wallet balance."""

    available: Decimal = Decimal("0")
    pending: Decimal = Decimal("0")
    immature: Decimal = Decimal("0")
    address_count: int = 0
    utxo_count: int = 0

    @property
    def total(self) -> Decimal:
        """Return the full balance including unconfirmed coins."""
        return (self.available + self.pending + self.immature).quantize(
            Decimal("0.00000001")
        )

    @property
    def spendable(self) -> Decimal:
        """Return coins that can be spent immediately."""
        return self.available


@dataclass(frozen=True)
class SignResult:
    """Result of signing a raw transaction through the proxy."""

    hex: str
    complete: bool
    signed_inputs: int
    unsigned_inputs: int
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_rpc(cls, data: Mapping[str, Any] | None) -> "SignResult":
        """Build a signing result from a proxy dictionary."""
        payload = dict(data or {})
        return cls(
            hex=_text(payload.get("hex")),
            complete=bool(payload.get("complete", False)),
            signed_inputs=_int(payload.get("signed_inputs")),
            unsigned_inputs=_int(payload.get("unsigned_inputs")),
            raw=payload,
        )
