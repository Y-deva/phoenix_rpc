import os
import threading
import time
import requests

from db import get_db_connection
from helpers import ONE_COIN


LAST_KNOWN_FILE = "last_known_block.txt"
LAST_PARSED_FILE = "last_parsed_block.txt"
WALLET_CHANGED_FLAG = "wallet_changed.flag"

INTERVAL = 2
SCAN_BUDGET_SECONDS = 0.35
RPC_TIMEOUT = 30
PAUSE_EVENT = threading.Event()
_pause_count = 0
_pause_lock = threading.Lock()
PAUSE_FILE = "parser.pause"


# ---------- Файлы высот ----------


def read_height_file(filename, default=0):
    try:
        with open(filename, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return default


def write_height_file(filename, height):
    with open(filename, "w") as f:
        f.write(str(height))


def pause_parser():
    """Ask the background parser to stop issuing RPC calls for now."""
    global _pause_count
    with _pause_lock:
        _pause_count += 1
        PAUSE_EVENT.set()


def resume_parser():
    """Release one pause request; scanning resumes after the last one."""
    global _pause_count
    with _pause_lock:
        _pause_count = max(0, _pause_count - 1)
        if _pause_count == 0:
            PAUSE_EVENT.clear()


def parser_paused():
    """Return whether the interactive RPC gate is closed."""
    return PAUSE_EVENT.is_set() or os.path.exists(PAUSE_FILE)


# ---------- RPC ----------


def rpc_call(rpc_config, method, params=None):
    params = params or []
    resp = requests.post(
        rpc_config["url"],
        headers={"Content-Type": "application/json"},
        auth=(rpc_config["user"], rpc_config["password"]),
        json={"jsonrpc": "1.0", "id": method, "method": method, "params": params},
        timeout=RPC_TIMEOUT,
    )
    data = resp.json()
    if "result" not in data or data.get("error"):
        raise Exception(f"RPC {method} failed: {data}")
    return data["result"]


def get_info(rpc_config):
    return rpc_call(rpc_config, "getinfo")


def get_block_hash(height, rpc_config):
    return rpc_call(rpc_config, "getblockbynumber", [height])["hash"]


def get_block(block_hash, rpc_config):
    return rpc_call(rpc_config, "getblock", [block_hash])


def get_block_by_number(height, rpc_config):
    """Fetch block metadata and its tx ids with one RPC call."""
    return rpc_call(rpc_config, "getblockbynumber", [height])


def get_transaction(txid, rpc_config):
    """Verbose getrawtransaction — работает и для чужих транзакций."""
    return rpc_call(rpc_config, "getrawtransaction", [txid, 1])


def get_mempool_txids(rpc_config):
    return rpc_call(rpc_config, "getrawmempool")


# ---------- Карта адресов ----------


def load_script_map():
    """Возвращает (fwd, rev):
    fwd: script_hash_hex -> redeem_script (bytes)
    rev: script_hash_hex -> address
    """
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT script_hash, redeem_script, address FROM wallets")
        rows = c.fetchall()
        fwd = {bytes(sh).hex(): bytes(rs) for sh, rs, _ in rows}
        rev = {bytes(sh).hex(): addr for sh, _, addr in rows}
        return fwd, rev
    finally:
        conn.close()


# ---------- Определение типа транзакции ----------


def _is_coinbase(tx) -> bool:
    """vtx[0]: 1 вход с null prevout, ненулевой scriptSig."""
    vins = tx.get("vin", [])
    if len(vins) != 1:
        return False
    prev = vins[0]
    prev_txid = prev.get("txid")
    return prev_txid in (None, "0" * 64) and prev.get("vout") in (None, 0xFFFFFFFF)


def _is_coinstake(tx) -> bool:
    """vtx[1]: непустой вход, vout[0] пустой."""
    vins = tx.get("vin", [])
    vouts = tx.get("vout", [])
    if not vins or len(vouts) < 2:
        return False
    if vins[0].get("txid") in (None, "0" * 64):
        return False
    first_vout = vouts[0]
    spk = first_vout.get("scriptPubKey", {})
    return first_vout.get("value", 0) == 0 and spk.get("hex", "") == ""


# ---------- Обработка транзакции ----------


def process_tx(tx, height, tx_index, c, script_map, script_map_rev, block_time):
    """
    tx_index — позиция в блоке (0 = coinbase, 1 = coinstake, >1 = обычные).
    Для мемпула tx_index=None, height=None.
    """
    txid = tx.get("txid", "")
    n_time = tx.get("time", block_time or 0)

    is_coinbase = (tx_index == 0) and _is_coinbase(tx)
    is_coinstake = (tx_index == 1) and _is_coinstake(tx)

    # 1. Наши входы (spent)
    our_inputs_sat = 0
    for vin in tx.get("vin", []):
        prev_txid = vin.get("txid")
        prev_vout = vin.get("vout")
        if prev_txid is None or prev_vout is None:
            continue
        c.execute(
            "UPDATE utxos SET spent=1 WHERE txid=? AND vout=?", (prev_txid, prev_vout)
        )
        if c.rowcount > 0:
            # Наш UTXO — узнаём сумму
            c.execute(
                "SELECT amount FROM utxos WHERE txid=? AND vout=?",
                (prev_txid, prev_vout),
            )
            row = c.fetchone()
            if row:
                our_inputs_sat += row[0]

    # 2. Наши выходы (received)
    our_outputs_sat = 0
    our_addresses = []
    for vout in tx.get("vout", []):
        spk = vout.get("scriptPubKey")
        if not spk:
            continue
        hex_script = spk.get("hex")
        if not hex_script:
            continue
        if not (hex_script.startswith("a914") and hex_script.endswith("87")):
            continue
        script_hash_hex = hex_script[4:-2]
        if script_hash_hex not in script_map:
            continue

        redeem_script = script_map[script_hash_hex]
        address = script_map_rev.get(script_hash_hex, "")
        amount_sat = int(round(float(vout["value"]) * ONE_COIN))
        vout_n = vout["n"]

        c.execute(
            """
            INSERT INTO utxos (txid, vout, redeem_script, amount, block_height)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(txid, vout) DO UPDATE SET
                block_height = excluded.block_height
        """,
            (txid, vout_n, redeem_script, amount_sat, height),
        )

        our_outputs_sat += amount_sat
        our_addresses.append(address)

    # 3. Классификация
    if is_coinbase:
        if our_outputs_sat > 0:
            category = "mined_pow"
            amount_net = our_outputs_sat
            fee = 0
        else:
            return  # не наш блок

    elif is_coinstake:
        if our_outputs_sat > 0:
            category = "mined_pos"
            # reward = outputs - inputs (то, что мы заработали на стейке)
            amount_net = our_outputs_sat - our_inputs_sat
            fee = 0
        else:
            return  # не наш блок

    elif our_inputs_sat > 0 and our_outputs_sat > 0:
        if len(our_addresses) > 0 and our_inputs_sat >= our_outputs_sat:
            # Все выходы наши — это консолидация
            # fee = разница (сожжённые монеты)
            category = "consolidate"
            amount_net = -(our_inputs_sat - our_outputs_sat)
            fee = our_inputs_sat - our_outputs_sat
        else:
            # Есть внешние выходы — отправка
            # amount_net = -(ушло наружу + fee)
            category = "send"
            amount_net = -our_inputs_sat + our_outputs_sat
            fee = 0  # посчитаем ниже, если нужно

    elif our_inputs_sat > 0:
        # Отправка без сдачи
        category = "send"
        amount_net = -our_inputs_sat
        fee = 0

    elif our_outputs_sat > 0:
        category = "receive"
        amount_net = our_outputs_sat
        fee = 0

    else:
        return  # транзакция не касается нас

    # 4. Запись в history
    primary_address = our_addresses[0] if our_addresses else None
    c.execute(
        """
        INSERT INTO history
            (txid, category, amount_net, fee, address, block_height, block_time, n_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(txid) DO UPDATE SET
            category = excluded.category,
            amount_net = excluded.amount_net,
            fee = excluded.fee,
            address = excluded.address,
            block_height = excluded.block_height,
            block_time = excluded.block_time,
            n_time = excluded.n_time
    """,
        (txid, category, amount_net, fee, primary_address, height, block_time, n_time),
    )


# ---------- Начальная точка сканирования ----------

_scan_floor_cache: int | None = None


def _wallet_creation_time():
    """Return the oldest address creation time, or None when unavailable."""
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT MIN(created_at) FROM wallets").fetchone()
        return int(row[0]) if row and row[0] else None
    finally:
        conn.close()


def initial_scan_floor(current_height: int) -> int:
    """Estimate a safe starting block from the oldest wallet creation time.

    The estimate deliberately errs on the side of scanning extra blocks. It
    avoids an RPC-heavy binary search on every startup while still preventing
    a new wallet from replaying the whole chain.
    """
    global _scan_floor_cache
    if _scan_floor_cache is not None:
        return _scan_floor_cache
    created_at = _wallet_creation_time()
    if not created_at:
        _scan_floor_cache = 0
        return 0
    age = max(0, int(time.time()) - created_at)
    # NovaCoin targets one-minute blocks; add two hours of overlap.
    estimated_blocks = age // 60 + 120
    _scan_floor_cache = max(0, current_height - estimated_blocks)
    print(
        f"[UTXO] First address created at {created_at}; start block {_scan_floor_cache}"
    )
    return _scan_floor_cache


# ---------- Сканирование блока ----------


def scan_block(height, rpc_config, script_map, script_map_rev, verbose_log=False):
    """Parse one block and fetch only the transactions it contains."""
    if verbose_log or height % 100 == 0:
        print(f"[UTXO] Scanning block {height}...")
    conn = None
    try:
        block = get_block_by_number(height, rpc_config)
        conn = get_db_connection()
        c = conn.cursor()
        block_time = block.get("time", 0)

        for tx_index, item in enumerate(block.get("tx", [])):
            # getblock(..., 2) returns tx objects; older nodes may only return ids.
            tx = item if isinstance(item, dict) else get_transaction(item, rpc_config)
            process_tx(tx, height, tx_index, c, script_map, script_map_rev, block_time)

        conn.commit()
        write_height_file(LAST_PARSED_FILE, height)
        if verbose_log or height % 100 == 0:
            print(f"[UTXO] Block {height} processed")
    except Exception as e:
        print(f"[UTXO] ERROR in block {height}: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


# ---------- Сканирование мемпула ----------


def scan_mempool(rpc_config, script_map, script_map_rev):
    try:
        txids = get_mempool_txids(rpc_config)
    except Exception as e:
        print(f"[MEMPOOL] Failed to get mempool: {e}")
        return

    if not txids:
        return

    print(f"[MEMPOOL] Transactions in mempool: {len(txids)}")
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        now = int(time.time())

        for txid in txids:
            try:
                tx = get_transaction(txid, rpc_config)
            except Exception as e:
                print(f"[MEMPOOL] Failed to fetch {txid[:10]}: {e}")
                continue
            process_tx(tx, None, None, c, script_map, script_map_rev, now)

        conn.commit()
    except Exception as e:
        print(f"[MEMPOOL] Error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ---------- Очистка сирот ----------


def cleanup_orphans(rpc_config):
    print("[ORPHAN] Checking orphan UTXOs...")
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT DISTINCT txid, block_height FROM utxos ORDER BY block_height DESC"
        )
        rows = c.fetchall()
        if not rows:
            print("[ORPHAN] No UTXOs to check")
            return None

        last_valid = None
        deleted_any = False
        max_orphan_height = None

        for txid, height in rows:
            if height is None:
                continue

            try:
                block = get_block_by_number(height, rpc_config)
            except Exception as e:
                print(f"[ORPHAN] Block {height} unreachable ({e}), skipping cleanup")
                return None

            if txid in block.get("tx", []):
                print(f"[ORPHAN] ✓ {txid[:10]} valid in block {height} — stop")
                last_valid = height
                break
            else:
                print(f"[ORPHAN] ✗ {txid[:10]} missing in block {height} — delete")
                c.execute("DELETE FROM utxos WHERE txid=?", (txid,))
                c.execute("DELETE FROM history WHERE txid=?", (txid,))
                deleted_any = True
                if max_orphan_height is None or height > max_orphan_height:
                    max_orphan_height = height

        conn.commit()

        if not deleted_any:
            print("[ORPHAN] Nothing deleted — no reorg detected")
        else:
            print(f"[ORPHAN] Deleted orphans, max height = {max_orphan_height}")

        return last_valid, deleted_any, max_orphan_height
    finally:
        conn.close()


def _rewind_parser(block_id):
    """Rewind the parser to just before an orphaned block."""
    last_parsed = read_height_file(LAST_PARSED_FILE, 0)
    rewind_to = max(0, block_id - 1)
    if rewind_to < last_parsed:
        write_height_file(LAST_PARSED_FILE, rewind_to)
        print(f"[ORPHAN] parser rewound to {rewind_to}")


def verify_unconfirmed_blocks(rpc_config, current_height=None):
    """Verify recently mined coinstakes and roll back shallow orphans.

    Returns the highest orphaned block height, or None.
    """
    from block_verify import verify_unconfirmed_blocks as verify

    if current_height is None:
        try:
            current_height = int(get_info(rpc_config)["blocks"])
        except Exception as exc:
            print(f"[ORPHAN] height unavailable: {exc}")
            return None
    return verify(
        current_height,
        lambda height: get_block_by_number(height, rpc_config),
        get_block_hash=lambda height: get_block_hash(height, rpc_config),
        on_orphan=_rewind_parser,
    )


# ---------- Основной цикл ----------


def run_parser_loop(rpc_config, interval=INTERVAL):
    print("[UTXO] Parser started")

    script_map, script_map_rev = load_script_map()
    print(f"[UTXO] Loaded {len(script_map)} addresses")

    verify_unconfirmed_blocks(rpc_config)

    result = cleanup_orphans(rpc_config)
    if result is not None:
        last_valid, deleted_any, max_orphan_height = result
        last_parsed = read_height_file(LAST_PARSED_FILE, 0)

        if deleted_any:
            rewind_to = (max_orphan_height - 1) if max_orphan_height is not None else -1
            if rewind_to < last_parsed:
                write_height_file(LAST_PARSED_FILE, rewind_to)
                print(f"[UTXO] Rewound to block {rewind_to} (reorg)")
            else:
                print(
                    "[UTXO] Orphans deleted but last_parsed="
                    f"{last_parsed} is already lower"
                )
        else:
            print(f"[UTXO] Keep last_parsed={last_parsed}")

    while True:
        try:
            try:
                info = get_info(rpc_config)
            except Exception as e:
                print(f"[UTXO] Daemon unavailable: {e}")
                time.sleep(interval)
                continue

            current_height = info["blocks"]
            write_height_file(LAST_KNOWN_FILE, current_height)
            verify_unconfirmed_blocks(rpc_config, current_height)

            if os.path.exists(WALLET_CHANGED_FLAG):
                os.remove(WALLET_CHANGED_FLAG)
                script_map, script_map_rev = load_script_map()
                print(f"[UTXO] Reloaded {len(script_map)} addresses")

            scan_mempool(rpc_config, script_map, script_map_rev)

            last_parsed = read_height_file(LAST_PARSED_FILE, 0)
            floor = initial_scan_floor(current_height)
            if last_parsed < floor:
                print(f"[UTXO] Skipping old blocks up to {floor}")
                write_height_file(LAST_PARSED_FILE, floor)
                last_parsed = floor
            if last_parsed < current_height:
                print(f"[UTXO] New blocks: {last_parsed + 1} -> {current_height}")
                started = time.monotonic()
                for h in range(last_parsed + 1, current_height + 1):
                    # Let send/pstore and the GUI get a turn even on a long catch-up.
                    if parser_paused():
                        break
                    scan_block(h, rpc_config, script_map, script_map_rev)
                    # Keep the node responsive even during a long catch-up.
                    time.sleep(0.02)
                    if time.monotonic() - started >= SCAN_BUDGET_SECONDS:
                        break

        except Exception as e:
            print(f"[UTXO] Loop error: {e}")

        # Keep the parser from monopolising the node's RPC queue.
        while parser_paused():
            time.sleep(0.2)
        time.sleep(interval)
