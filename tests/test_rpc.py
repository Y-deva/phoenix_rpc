"""RPC client, models and service parsing."""

from decimal import Decimal


from phoenix_gui.rpc.client import RPCClient, RPCError
from phoenix_gui.rpc.models import Transaction, Utxo
from phoenix_gui.rpc.service import WalletService, balance_summary


def make_client(mapping, calls=None):
    """Build a client backed by a dict of method results."""

    def transport(method, params):
        if calls is not None:
            calls.append((method, params))
        result = mapping[method]
        if isinstance(result, Exception):
            raise result
        return result

    return RPCClient("http://127.0.0.1:1", "user", "pass", transport=transport)


def test_client_returns_result_and_tracks_params():
    calls = []
    client = make_client({"ping": "pong"}, calls)
    assert client.call("ping", ["x", 2]) == "pong"
    assert calls == [("ping", ["x", 2])]


def test_service_network_and_chain():
    client = make_client(
        {
            "getinfo": {
                "version": 1200000,
                "blocks": 100,
                "connections": 4,
                "difficulty": 12.5,
                "testnet": True,
                "generate": True,
            },
            "getblockchaininfo": {
                "blocks": 100,
                "headers": 120,
                "verificationprogress": 0.8,
                "initialblockdownload": True,
                "chain": "test",
            },
        }
    )
    service = WalletService(client)
    network = service.network_info()
    chain = service.chain_info()
    assert network.testnet
    assert network.mining
    assert chain.headers == 120
    assert chain.progress_percent == Decimal("83.33333333333333333333333333")


def test_chain_info_falls_back_to_getinfo():
    client = make_client(
        {
            "getinfo": {"blocks": 42, "testnet": True},
            "getblockchaininfo": RPCError("unsupported", -32601),
        }
    )
    service = WalletService(client)
    assert service.chain_info().blocks == 42


def test_list_unspent_parsing():
    client = make_client(
        {
            "listunspent": [
                {
                    "txid": "a" * 64,
                    "vout": 1,
                    "address": "2NAddress",
                    "amount": 1.25,
                    "confirmations": 3,
                    "scriptPubKey": "00",
                    "spendable": True,
                }
            ]
        }
    )
    utxos = WalletService(client).list_unspent()
    assert utxos[0].key.endswith(":1")
    assert utxos[0].amount == Decimal("1.25")
    assert utxos[0].confirmed


def test_list_transactions_and_balance_summary():
    transactions = [
        Transaction(txid="a", category="receive", amount=Decimal("5"), confirmations=2),
        Transaction(
            txid="b", category="immature", amount=Decimal("1"), confirmations=1
        ),
        Transaction(txid="c", category="send", amount=Decimal("-2"), confirmations=0),
    ]
    utxos = [
        Utxo("a", 0, "A", Decimal("5"), 2),
        Utxo("b", 1, "B", Decimal("1"), 0, spendable=False),
    ]
    summary = balance_summary(utxos, transactions)
    assert summary.available == Decimal("5")
    assert summary.pending == Decimal("1")
    assert summary.immature == Decimal("1")
    assert summary.total == Decimal("7")
    assert summary.utxo_count == 2


def test_address_fallback_when_method_missing():
    client = make_client(
        {
            "listaddresses": RPCError("Method not found", -32601),
            "listunspent": [],
            "listtransactions": [
                {
                    "txid": "a" * 64,
                    "category": "receive",
                    "amount": 2,
                    "address": "2NAddress",
                    "account": "Main",
                    "confirmations": 2,
                    "time": 100,
                }
            ],
        }
    )
    service = WalletService(client)
    assert service.list_addresses() == []
    assert service.addresses_supported is False
    addresses = service.available_addresses()
    assert addresses[0].address == "2NAddress"
    assert addresses[0].balance == Decimal("0")


def test_expert_transaction_payload():
    calls = []
    client = make_client(
        {
            "createrawtransaction": "00ff",
            "signrawtransaction": {"hex": "aabb", "complete": True, "errors": []},
            "sendrawtransaction": "c" * 64,
        },
        calls,
    )
    service = WalletService(client)
    raw = service.create_raw_transaction(
        [("a" * 64, 0)], {"2NRecipient": Decimal("1.25")}, "6869"
    )
    assert raw == "00ff"
    assert calls[0][1][0][0]["vout"] == 0
    assert calls[0][1][1]["2NRecipient"] == 1.25
    assert calls[0][1][2] == "6869"
    signed = service.sign_raw_transaction(raw)
    assert signed.complete
    assert service.send_raw_transaction(signed.hex) == "c" * 64


def test_new_address_and_send_use_expected_arguments():
    calls = []
    client = make_client({"getnewaddress": "2NNew", "sendtoaddress": "deadbeef"}, calls)
    service = WalletService(client)
    assert service.new_address("Main") == "2NNew"
    assert service.send_to_address("2NNew", Decimal("1.5"), "hi") == "deadbeef"
    assert calls[0] == ("getnewaddress", ["Main"])
    assert calls[1][1][:2] == ["2NNew", 1.5]


def test_service_pstore_calls():
    calls = []
    client = make_client(
        {
            "pstore": {"file_id": "a" * 64, "tx_count": 1},
            "pload": {"path": "/tmp/file.bin"},
            "pcancel": {"cancelled": 2},
        },
        calls,
    )
    service = WalletService(client)
    assert service.pstore("/tmp/source.bin", "note")["file_id"] == "a" * 64
    assert service.pload("b" * 64, "bin")["path"] == "/tmp/file.bin"
    assert service.pcancel()["cancelled"] == 2
    assert calls == [
        ("pstore", ["/tmp/source.bin", "note"]),
        ("pload", ["b" * 64, "bin"]),
        ("pcancel", []),
    ]
