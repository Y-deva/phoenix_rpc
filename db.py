import sqlite3
import toml

with open("config.toml") as f:
    config = toml.load(f)

DB_PATH = config["database"]["path"]


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def checkpoint_wal():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()


def _column_exists(c, table: str, column: str) -> bool:
    c.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in c.fetchall())


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS wallets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            salt          BLOB NOT NULL,
            redeem_script BLOB NOT NULL,
            script_hash   BLOB NOT NULL,
            address       TEXT NOT NULL UNIQUE,
            account       TEXT DEFAULT '',
            created_at    INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_wallets_address ON wallets(address)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_wallets_script_hash ON wallets(script_hash)"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_wallets_account ON wallets(account)")

    if not _column_exists(c, "wallets", "counter"):
        c.execute("ALTER TABLE wallets ADD COLUMN counter INTEGER")
        print("[DB] Migrated: added wallets.counter")

    c.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wallets_counter
        ON wallets(counter) WHERE counter IS NOT NULL
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS utxos (
            txid          TEXT NOT NULL,
            vout          INTEGER NOT NULL,
            redeem_script BLOB NOT NULL,
            amount        INTEGER NOT NULL,
            block_height  INTEGER,
            spent         INTEGER DEFAULT 0,
            PRIMARY KEY (txid, vout)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_utxos_spent ON utxos(spent)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_utxos_block_height ON utxos(block_height)"
    )

    c.execute("""
        CREATE TABLE IF NOT EXISTS history (
            txid          TEXT PRIMARY KEY,
            category      TEXT NOT NULL,
            amount_net    INTEGER NOT NULL,
            fee           INTEGER DEFAULT 0,
            address       TEXT,
            account       TEXT DEFAULT '',
            block_height  INTEGER,
            block_time    INTEGER,
            n_time        INTEGER,
            comment       TEXT,
            created_at    INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_category ON history(category)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_address ON history(address)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_block ON history(block_height)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_n_time ON history(n_time)")

    if not _column_exists(c, "history", "status"):
        c.execute("ALTER TABLE history ADD COLUMN status TEXT DEFAULT 'confirmed'")
        print("[DB] Migrated: added history.status")
    c.execute("UPDATE history SET status='confirmed' WHERE status IS NULL")

    c.execute("""
        CREATE TABLE IF NOT EXISTS unconfirmed_blocks (
            txid          TEXT PRIMARY KEY,
            block_id      INTEGER NOT NULL,
            input_txid    TEXT NOT NULL,
            input_vout    INTEGER NOT NULL,
            created_at    INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    if not _column_exists(c, "unconfirmed_blocks", "block_hash"):
        c.execute("ALTER TABLE unconfirmed_blocks ADD COLUMN block_hash TEXT")
        print("[DB] Migrated: added unconfirmed_blocks.block_hash")
    if not _column_exists(c, "unconfirmed_blocks", "pstore_txids"):
        c.execute("ALTER TABLE unconfirmed_blocks ADD COLUMN pstore_txids TEXT")
        print("[DB] Migrated: added unconfirmed_blocks.pstore_txids")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_unconfirmed_blocks_height "
        "ON unconfirmed_blocks(block_id)"
    )

    c.execute("""
        CREATE TABLE IF NOT EXISTS priority_txs (
            txid         TEXT PRIMARY KEY,
            chain_id     TEXT NOT NULL,
            kind         TEXT NOT NULL,
            seq          INTEGER NOT NULL,
            raw          BLOB NOT NULL,
            prev_txid    TEXT,
            prev_vout    INTEGER,
            size         INTEGER NOT NULL,
            n_time       INTEGER,
            added_at     INTEGER DEFAULT (strftime('%s','now')),
            comment      TEXT
        )
    """)
    if not _column_exists(c, "priority_txs", "confirmed_height"):
        c.execute("ALTER TABLE priority_txs ADD COLUMN confirmed_height INTEGER")
        print("[DB] Migrated: added priority_txs.confirmed_height")
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_priority_chain
        ON priority_txs(chain_id, seq)
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_priority_confirmed "
        "ON priority_txs(confirmed_height)"
    )

    c.execute("""
        CREATE TABLE IF NOT EXISTS pstore_anchor (
            id            INTEGER PRIMARY KEY CHECK (id = 1),
            txid          TEXT,
            vout          INTEGER DEFAULT 0,
            redeem_script BLOB,
            address       TEXT,
            confirmed     INTEGER DEFAULT 0,
            updated_at    INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    c.execute("INSERT OR IGNORE INTO pstore_anchor (id) VALUES (1)")

    conn.commit()
    conn.close()


def confirm_pstore_package(height: int, txids) -> int:
    """Mark pstore rows confirmed after their block passed membership checks."""
    values = [txid for txid in txids if txid]
    if not values:
        return 0
    placeholders = ",".join("?" for _ in values)
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            f"UPDATE priority_txs SET confirmed_height=? "
            f"WHERE confirmed_height IS NULL AND txid IN ({placeholders})",
            [height, *values],
        )
        changed = c.rowcount
        c.execute(
            """UPDATE pstore_anchor
               SET confirmed=1, updated_at=strftime('%s','now')
               WHERE id=1 AND txid=?""",
            (values[-1],),
        )
        conn.commit()
        return max(0, changed)
    finally:
        conn.close()


def reindex_pstore_after_orphan(block_id: int) -> int:
    """Return a confirmed pstore chain to the pending queue after a reorg."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("BEGIN IMMEDIATE")
        c.execute(
            "SELECT txid, prev_txid, prev_vout FROM priority_txs "
            "WHERE confirmed_height=?",
            (block_id,),
        )
        rows = c.fetchall()
        if not rows:
            conn.commit()
            return 0
        for txid, prev_txid, prev_vout in rows:
            # Remove outputs created by the orphaned pstore chain.
            c.execute("DELETE FROM utxos WHERE txid=?", (txid,))
            if prev_txid is not None:
                c.execute(
                    "UPDATE utxos SET spent=0 WHERE txid=? AND vout=?",
                    (prev_txid, prev_vout),
                )
        txids = [row[0] for row in rows]
        placeholders = ",".join("?" for _ in txids)
        c.execute(
            f"UPDATE history SET status='orphan' WHERE txid IN ({placeholders})",
            txids,
        )
        c.execute(
            "UPDATE priority_txs SET confirmed_height=NULL "
            f"WHERE txid IN ({placeholders})",
            txids,
        )
        c.execute("""UPDATE pstore_anchor
                     SET confirmed=0, updated_at=strftime('%s','now')
                     WHERE id=1""")
        conn.commit()
        print(f"[PSTORE] reindexed {len(rows)} tx from orphan block {block_id}")
        return len(rows)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def prune_confirmed_pstore(current_height: int) -> int:
    """Drop pstore rows only after 520 confirmations."""
    cutoff = current_height - 519
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "DELETE FROM priority_txs "
            "WHERE confirmed_height IS NOT NULL AND confirmed_height <= ?",
            (cutoff,),
        )
        deleted = c.rowcount
        conn.commit()
        return max(0, deleted)
    finally:
        conn.close()
