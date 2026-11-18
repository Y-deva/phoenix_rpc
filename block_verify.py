"""Verification and rollback of locally mined coinstake blocks.

A stake transaction can be accepted by the daemon but disappear from the
chain after a shallow reorg.  The wallet must not keep its outputs or the
spent kernel locked in that case.  This module works only with the local
SQLite database, so it can be tested without a running daemon.
"""

from db import (
    confirm_pstore_package,
    get_db_connection,
    prune_confirmed_pstore,
    reindex_pstore_after_orphan,
)

FINALITY_CONFIRMATIONS = 520


def rollback_unconfirmed(txid, block_id, input_txid, input_vout):
    """Undo local state for one coinstake missing from its block."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("BEGIN IMMEDIATE")
        c.execute("DELETE FROM utxos WHERE txid=?", (txid,))
        c.execute("UPDATE history SET status='orphan' WHERE txid=?", (txid,))
        c.execute(
            "UPDATE history SET status='orphan' WHERE block_height=?",
            (block_id,),
        )
        c.execute(
            "UPDATE utxos SET spent=0 WHERE txid=? AND vout=?",
            (input_txid, input_vout),
        )
        c.execute("DELETE FROM unconfirmed_blocks WHERE txid=?", (txid,))
        conn.commit()
        print(
            f"[ORPHAN] coinstake {txid[:12]} missing in block {block_id}; "
            f"kernel {input_txid[:12]}:{input_vout} returned"
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        reindex_pstore_after_orphan(block_id)
    except Exception as exc:
        print(f"[ORPHAN] pstore reindex failed for block {block_id}: {exc}")


def verify_unconfirmed_blocks(
    current_height,
    get_block,
    get_block_hash=None,
    finality=FINALITY_CONFIRMATIONS,
    on_orphan=None,
):
    """Verify mined coinstakes and roll back shallow orphans.

    ``get_block(height)`` returns a daemon block dict with a ``tx`` list.
    Rows stay until ``finality`` confirmations; an orphaned row is removed
    immediately and its kernel output is made spendable again.
    """
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT txid, block_id, input_txid, input_vout, "
            "block_hash, pstore_txids "
            "FROM unconfirmed_blocks ORDER BY block_id ASC"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    orphan_height = None
    for row in rows:
        txid, block_id, input_txid, input_vout, block_hash, raw_txids = row
        if block_id > current_height:
            continue
        if get_block_hash is not None and block_hash:
            try:
                if get_block_hash(block_id) != block_hash:
                    rollback_unconfirmed(txid, block_id, input_txid, input_vout)
                    if orphan_height is None or block_id > orphan_height:
                        orphan_height = block_id
                    continue
            except Exception as exc:
                print(f"[ORPHAN] block hash {block_id} unavailable: {exc}")
                continue
        try:
            block = get_block(block_id)
        except Exception as exc:
            print(f"[ORPHAN] block {block_id} unavailable: {exc}")
            continue
        txids = set(block.get("tx") or [])
        if txid in txids:
            try:
                import json

                package = json.loads(raw_txids) if raw_txids else []
            except Exception:
                package = []
            if package and all(item in txids for item in package):
                confirm_pstore_package(block_id, package)
            confirmations = current_height - block_id + 1
            if confirmations >= finality:
                conn = get_db_connection()
                try:
                    conn.execute("DELETE FROM unconfirmed_blocks WHERE txid=?", (txid,))
                    conn.commit()
                finally:
                    conn.close()
            continue

        rollback_unconfirmed(txid, block_id, input_txid, input_vout)
        if orphan_height is None or block_id > orphan_height:
            orphan_height = block_id

    try:
        prune_confirmed_pstore(current_height)
    except Exception as exc:
        print(f"[ORPHAN] pstore prune failed: {exc}")

    if orphan_height is not None and on_orphan is not None:
        on_orphan(orphan_height)
    return orphan_height
