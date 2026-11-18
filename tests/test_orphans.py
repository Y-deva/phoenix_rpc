"""Tests for coinstake orphan tracking and pstore rollback."""

import sqlite3

import pytest

import block_verify
import db


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Use a temporary wallet database for each test."""
    path = tmp_path / "wallet.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    yield path


def _insert_coinstake(txid="cc" * 32, kernel="kk" * 32, height=100):
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO utxos "
            "(txid, vout, redeem_script, amount, block_height, spent) "
            "VALUES (?, 0, ?, 100, ?, 0)",
            (txid, b"script", height),
        )
        conn.execute(
            "INSERT INTO utxos "
            "(txid, vout, redeem_script, amount, block_height, spent) "
            "VALUES (?, 0, ?, 100, 90, 1)",
            (kernel, b"script"),
        )
        conn.execute(
            "INSERT INTO history "
            "(txid, category, amount_net, block_height, block_time, status) "
            "VALUES (?, 'stake', 100, ?, '2026-01-01', 'confirmed')",
            (txid, height),
        )
        conn.execute(
            "INSERT INTO unconfirmed_blocks "
            "(txid, block_id, input_txid, input_vout) VALUES (?, ?, ?, 0)",
            (txid, height, kernel),
        )
        conn.commit()
    finally:
        conn.close()


def test_orphan_rolls_back_coinstake_and_kernel(temp_db):
    _insert_coinstake()
    block = {"tx": ["other"]}
    rewound = []
    result = block_verify.verify_unconfirmed_blocks(
        101, lambda _height: block, on_orphan=rewound.append
    )
    assert result == 100
    assert rewound == [100]
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM utxos WHERE txid=?", ("cc" * 32,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT spent FROM utxos WHERE txid=?", ("kk" * 32,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT status FROM history WHERE txid=?", ("cc" * 32,)
            ).fetchone()[0]
            == "orphan"
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM unconfirmed_blocks").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_valid_block_stays_until_finality(temp_db):
    _insert_coinstake(height=100)
    body = {"tx": ["cc" * 32]}
    assert block_verify.verify_unconfirmed_blocks(618, lambda _h: body) is None
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM unconfirmed_blocks").fetchone()[0] == 1
        )
    finally:
        conn.close()
    assert block_verify.verify_unconfirmed_blocks(619, lambda _h: body) is None
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM unconfirmed_blocks").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_pstore_reindex_restores_pending_anchor(temp_db):
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            "INSERT INTO utxos "
            "(txid, vout, redeem_script, amount, block_height, spent) "
            "VALUES (?, 0, ?, 1, 90, 1)",
            ("aa" * 32, b"script"),
        )
        conn.execute(
            "INSERT INTO priority_txs "
            "(txid, chain_id, kind, seq, raw, prev_txid, prev_vout, size, "
            "confirmed_height) VALUES (?, 'chain', 'pstore', 1, ?, ?, 0, 10, 100)",
            ("bb" * 32, b"raw", "aa" * 32),
        )
        conn.execute(
            "INSERT INTO history "
            "(txid, category, amount_net, block_height, block_time, status) "
            "VALUES (?, 'pstore', 0, 100, '2026-01-01', 'confirmed')",
            ("bb" * 32,),
        )
        conn.execute("UPDATE pstore_anchor SET confirmed=1 WHERE id=1")
        conn.commit()
    finally:
        conn.close()

    assert db.reindex_pstore_after_orphan(100) == 1
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute(
                "SELECT confirmed_height FROM priority_txs WHERE txid=?",
                ("bb" * 32,),
            ).fetchone()[0]
            is None
        )
        assert (
            conn.execute(
                "SELECT spent FROM utxos WHERE txid=?", ("aa" * 32,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT status FROM history WHERE txid=?", ("bb" * 32,)
            ).fetchone()[0]
            == "orphan"
        )
        assert (
            conn.execute("SELECT confirmed FROM pstore_anchor WHERE id=1").fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_block_hash_mismatch_rolls_back(temp_db):
    """A re-minted block at the same height must not keep the coinstake."""
    _insert_coinstake()
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("UPDATE unconfirmed_blocks SET block_hash='expected'")
        conn.commit()
    finally:
        conn.close()
    result = block_verify.verify_unconfirmed_blocks(
        101,
        lambda _h: {"tx": ["cc" * 32]},
        get_block_hash=lambda _h: "different",
    )
    assert result == 100
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute("SELECT COUNT(*) FROM unconfirmed_blocks").fetchone()[0] == 0
        )
    finally:
        conn.close()


def test_pstore_package_only_confirms_when_txids_are_in_block(temp_db):
    """A canonical coinstake does not confirm a package it omitted."""
    import json

    _insert_coinstake()
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute(
            "UPDATE unconfirmed_blocks SET block_hash='hash', pstore_txids=?",
            (json.dumps(["dd" * 32]),),
        )
        conn.execute(
            "INSERT INTO priority_txs "
            "(txid, chain_id, kind, seq, raw, prev_txid, prev_vout, size) "
            "VALUES (?, 'chain', 'pstore', 1, ?, ?, 0, 10)",
            ("dd" * 32, b"raw", "aa" * 32),
        )
        conn.commit()
    finally:
        conn.close()
    block_verify.verify_unconfirmed_blocks(
        101,
        lambda _h: {"tx": ["cc" * 32, "dd" * 32]},
        get_block_hash=lambda _h: "hash",
    )
    conn = sqlite3.connect(temp_db)
    try:
        assert (
            conn.execute(
                "SELECT confirmed_height FROM priority_txs WHERE txid=?",
                ("dd" * 32,),
            ).fetchone()[0]
            == 100
        )
    finally:
        conn.close()
