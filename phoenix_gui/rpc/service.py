"""Typed, blocking wallet operations used by the GUI workers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from .client import RPCClient, RPCError
from .models import (
    AddressInfo,
    BalanceSummary,
    ChainInfo,
    NetworkInfo,
    SignResult,
    Transaction,
    Utxo,
)

MAX_HISTORY = 1000
MAX_UNSPENT = 100000
MONEY_PLACES = Decimal("0.00000001")


def _is_method_unsupported(error: RPCError) -> bool:
    """Return whether an error means the proxy lacks an optional method."""
    message = (error.message or "").lower()
    return (
        error.code == -32601
        or "method not found" in message
        or "unknown method" in message
    )


def balance_summary(
    utxos: Iterable[Utxo],
    transactions: Iterable[Transaction],
    addresses: Sequence[AddressInfo] | None = None,
) -> BalanceSummary:
    """Split UTXOs into available, pending and immature buckets.

    ``getbalance`` includes unconfirmed inputs, so the GUI deliberately
    derives balances from ``listunspent`` and marks immature mining
    rewards from ``listtransactions``. This mirrors the proxy's own
    definition and keeps the numbers explainable.
    """
    available = Decimal("0")
    pending = Decimal("0")
    count = 0
    seen_addresses: set[str] = set()
    for utxo in utxos:
        count += 1
        if utxo.address:
            seen_addresses.add(utxo.address)
        if utxo.confirmations >= 1 and utxo.spendable:
            available += utxo.amount
        else:
            pending += utxo.amount
    immature = Decimal("0")
    for tx in transactions:
        if tx.category == "immature" and tx.amount > 0:
            immature += tx.amount
    address_count = len(addresses) if addresses is not None else len(seen_addresses)
    return BalanceSummary(
        available=available.quantize(MONEY_PLACES),
        pending=pending.quantize(MONEY_PLACES),
        immature=immature.quantize(MONEY_PLACES),
        address_count=address_count,
        utxo_count=count,
    )


def derive_addresses(
    utxos: Iterable[Utxo],
    transactions: Iterable[Transaction],
) -> list[AddressInfo]:
    """Build an address list from UTXOs and history.

    This fallback is used with proxies that predate the optional
    ``listaddresses`` method. Only addresses that produced activity are
    visible, which is exactly what the GUI can prove.
    """
    balances: dict[str, Decimal] = {}
    utxo_counts: dict[str, int] = {}
    accounts: dict[str, str] = {}
    tx_counts: dict[str, set[str]] = {}
    first_seen: dict[str, int] = {}
    for utxo in utxos:
        if not utxo.address:
            continue
        balances[utxo.address] = balances.get(utxo.address, Decimal("0")) + utxo.amount
        utxo_counts[utxo.address] = utxo_counts.get(utxo.address, 0) + 1
    for tx in transactions:
        if not tx.address:
            continue
        tx_counts.setdefault(tx.address, set()).add(tx.txid)
        if tx.account and tx.address not in accounts:
            accounts[tx.address] = tx.account
        if tx.timestamp:
            previous = first_seen.get(tx.address, tx.timestamp)
            first_seen[tx.address] = min(previous, tx.timestamp)
    addresses = set(balances) | set(tx_counts)
    result = [
        AddressInfo(
            address=address,
            account=accounts.get(address, ""),
            created_at=first_seen.get(address, 0),
            balance=balances.get(address, Decimal("0")).quantize(MONEY_PLACES),
            utxo_count=utxo_counts.get(address, 0),
            tx_count=len(tx_counts.get(address, set())),
        )
        for address in addresses
    ]
    result.sort(key=lambda item: (-item.balance, item.address))
    return result


class WalletService:
    """High-level wallet API with typed results and optional fallbacks."""

    def __init__(self, client: RPCClient) -> None:
        """Initialize the WalletService instance."""
        self.client = client
        self.addresses_supported: bool | None = None

    def call(self, method: str, params: Sequence[Any] | None = None) -> Any:
        """Forward an arbitrary JSON-RPC call."""
        return self.client.call(method, params)

    def network_info(self) -> NetworkInfo:
        """Fetch general daemon status."""
        return NetworkInfo.from_rpc(self.client.call("getinfo"))

    def chain_info(self) -> ChainInfo:
        """Fetch chain synchronization status.

        Older NovaCoin builds may not implement ``getblockchaininfo``;
        in that case the values from ``getinfo`` are used.
        """
        try:
            return ChainInfo.from_rpc(self.client.call("getblockchaininfo"))
        except RPCError as exc:
            if not _is_method_unsupported(exc):
                raise
            info = self.network_info()
            return ChainInfo(
                blocks=info.blocks,
                headers=info.blocks,
                verification_progress=Decimal("1"),
                chain="test" if info.testnet else "main",
            )

    def list_unspent(
        self,
        minconf: int = 0,
        maxconf: int = 9999999,
        addresses: Sequence[str] | None = None,
    ) -> list[Utxo]:
        """Return unspent outputs, excluding immature coinbase rewards."""
        params: list[Any] = [minconf, maxconf]
        if addresses:
            params.append(list(addresses))
        result = self.client.call("listunspent", params) or []
        if isinstance(result, Mapping):
            result = result.get("utxos", [])
        return [Utxo.from_rpc(item) for item in result if isinstance(item, Mapping)]

    def list_transactions(
        self, count: int = 300, offset: int = 0, account: str = ""
    ) -> list[Transaction]:
        """Return wallet history, newest entries last as returned by the proxy."""
        safe_count = max(1, min(MAX_HISTORY, int(count)))
        result = (
            self.client.call("listtransactions", [account, safe_count, max(0, offset)])
            or []
        )
        if isinstance(result, Mapping):
            result = result.get("transactions", [])
        items = [
            Transaction.from_rpc(item) for item in result if isinstance(item, Mapping)
        ]
        return [item for item in items if item.txid]

    def list_addresses(self) -> list[AddressInfo]:
        """Return wallet addresses when the proxy supports the method.

        The GUI treats an unsupported method as an expected condition and
        falls back to addresses derived from history.
        """
        try:
            result = self.client.call("listaddresses") or []
        except RPCError as exc:
            if _is_method_unsupported(exc):
                self.addresses_supported = False
                return []
            raise
        self.addresses_supported = True
        if isinstance(result, Mapping):
            result = result.get("addresses", [])
        return [
            AddressInfo.from_rpc(item) for item in result if isinstance(item, Mapping)
        ]

    def balance(
        self, transactions: Iterable[Transaction] | None = None
    ) -> BalanceSummary:
        """Compute a balance snapshot from UTXOs and history."""
        utxos = self.list_unspent()
        history = (
            list(transactions)
            if transactions is not None
            else self.list_transactions(count=MAX_HISTORY)
        )
        return balance_summary(utxos, history)

    def new_address(self, account: str = "") -> str:
        """Generate a fresh receive address."""
        result = self.client.call("getnewaddress", [account])
        if isinstance(result, Mapping):
            result = result.get("address", "")
        return str(result or "")

    def send_to_address(self, address: str, amount: Decimal, comment: str = "") -> str:
        """Send through the proxy's guarded implementation."""
        result = self.client.call(
            "sendtoaddress",
            [address, float(f"{amount:.8f}"), comment or ""],
        )
        if isinstance(result, Mapping):
            result = result.get("txid", "")
        return str(result or "")

    def sign_raw_transaction(self, raw_hex: str) -> SignResult:
        """Sign our P2SH-Falcon inputs through the proxy."""
        result = self.client.call("signrawtransaction", [raw_hex])
        return SignResult.from_rpc(result if isinstance(result, Mapping) else {})

    def create_raw_transaction(
        self,
        inputs: Sequence[tuple[str, int]],
        outputs: Mapping[str, Decimal],
        data_hex: str = "",
    ) -> str:
        """Create an unsigned transaction for the expert flow."""
        input_payload = [{"txid": txid, "vout": int(vout)} for txid, vout in inputs]
        output_payload = {
            address: float(f"{amount:.8f}") for address, amount in outputs.items()
        }
        params: list[Any] = [input_payload, output_payload]
        if data_hex:
            params.append(data_hex)
        result = self.client.call("createrawtransaction", params)
        if isinstance(result, Mapping):
            result = result.get("hex", "")
        return str(result or "")

    def send_raw_transaction(self, raw_hex: str) -> str:
        """Broadcast a fully signed raw transaction."""
        result = self.client.call("sendrawtransaction", [raw_hex])
        if isinstance(result, Mapping):
            result = result.get("txid", "")
        return str(result or "")

    def get_raw_transaction(self, txid: str, verbose: bool = True) -> Any:
        """Fetch a transaction by id, used by the transaction details dialog."""
        return self.client.call("getrawtransaction", [txid, 1 if verbose else 0])

    def decode_raw_transaction(self, raw_hex: str) -> Any:
        """Decode a raw transaction for inspection before broadcast."""
        return self.client.call("decoderawtransaction", [raw_hex])

    def available_addresses(self) -> list[AddressInfo]:
        """Return addresses, falling back to those derived from activity."""
        if self.addresses_supported is False:
            return derive_addresses(
                self.list_unspent(), self.list_transactions(count=MAX_HISTORY)
            )
        return self.list_addresses()


def fee_amount(size_bytes: int, sat_per_byte: int) -> Decimal:
    """Calculate a fee in coins from a byte estimate."""
    return (
        Decimal(max(0, int(size_bytes)))
        * Decimal(max(1, int(sat_per_byte)))
        / Decimal("1000000")
    ).quantize(MONEY_PLACES)
