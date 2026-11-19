"""Import keys from a legacy NovaCoin wallet and sweep them to Phoenix.

The migration path talks to the daemon directly.  It never asks the Phoenix
proxy to sign anything: legacy keys are ECDSA keys, while Phoenix addresses
are P2SH-Falcon.  A wallet.dat is opened in a private temporary daemon with
networking disabled so the original file is never modified.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Iterator

from .config import ProjectConfig
from .daemon import discover_daemon
from .validation import validate_address
from ..rpc.client import RPCClient, RPCError
from ..settings import Settings

LOGGER = logging.getLogger("phoenix.migration")
MIGRATION_LABEL = "legacy-migration"
WIF_MIN_LENGTH = 50
WIF_MAX_LENGTH = 52


@dataclass(frozen=True)
class MigrationReport:
    """Balance and key information discovered before a sweep."""

    source: str
    balance: Decimal
    inputs: int
    keys: int
    addresses: tuple[str, ...] = ()


def _free_port(start: int = 18400, end: int = 18500) -> int:
    """Return a free local TCP port for the private migration daemon."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("Не удалось найти свободный порт для временного демона")


def _hidden_flags() -> int:
    """Return the platform flag that suppresses a console window."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _direct_client(project: ProjectConfig, timeout: float = 900.0) -> RPCClient:
    """Create a direct daemon client, bypassing the Phoenix proxy."""
    return RPCClient(
        project.daemon_url,
        project.daemon_user,
        project.daemon_password,
        timeout=timeout,
    )


@contextmanager
def _paused_indexer(project: ProjectConfig) -> Iterator[None]:
    """Freeze the proxy UTXO parser while a direct migration RPC runs."""
    marker = Path(project.root) / "parser.pause"
    existed = marker.exists()
    try:
        marker.touch(exist_ok=True)
        yield
    finally:
        if not existed:
            try:
                marker.unlink()
            except FileNotFoundError:
                pass


def _report(client: RPCClient, source: str, keys: int = 0) -> MigrationReport:
    """Read the spendable balance and input count from a daemon."""
    balance = client.call("getbalance")
    unspent = client.call("listunspent", [0])
    items = unspent if isinstance(unspent, list) else []
    addresses = sorted(
        {
            str(item.get("address", ""))
            for item in items
            if isinstance(item, dict) and item.get("address")
        }
    )
    return MigrationReport(
        source=source,
        balance=Decimal(str(balance or 0)),
        inputs=len(items),
        keys=keys,
        addresses=tuple(addresses),
    )


def validate_wif(value: str) -> str:
    """Check the obvious shape of a WIF key without logging its contents."""
    text = (value or "").strip()
    if not text:
        raise ValueError("Введите приватный ключ WIF")
    if not (WIF_MIN_LENGTH <= len(text) <= WIF_MAX_LENGTH):
        raise ValueError("Приватный ключ WIF имеет неверную длину")
    if any(char.isspace() for char in text):
        raise ValueError("Ключ WIF не должен содержать пробелы")
    return text


def validate_destination(address: str, project: ProjectConfig) -> str:
    """Validate a Phoenix destination address before importing any key."""
    check = validate_address(address, expected_network=project.network)
    if not check.valid:
        raise ValueError(check.reason)
    if check.warning:
        raise ValueError(check.warning)
    return address.strip()


def import_wif(project: ProjectConfig, wif: str) -> MigrationReport:
    """Import one WIF key into the running daemon and scan its balance."""
    return import_wif_keys(project, [wif])


def import_wif_keys(project: ProjectConfig, keys: Iterable[str]) -> MigrationReport:
    """Import several WIF keys with one final blockchain rescan.

    Importing every key with ``rescan=True`` forces a full wallet rescan for
    each key.  The last key triggers the single rescan needed for all of them.
    """
    cleaned: list[str] = []
    for value in keys:
        key = validate_wif(value)
        if key not in cleaned:
            cleaned.append(key)
    if not cleaned:
        raise ValueError("Введите хотя бы один приватный ключ WIF")
    LOGGER.info("Importing %d legacy WIF key(s)", len(cleaned))
    with _paused_indexer(project):
        client = _direct_client(project)
        try:
            for index, key in enumerate(cleaned):
                rescan = index == len(cleaned) - 1
                try:
                    client.call("importprivkey", [key, MIGRATION_LABEL, rescan])
                except RPCError as exc:
                    if "already" not in str(exc).casefold():
                        raise
            report = _report(client, "wif", keys=len(cleaned))
            LOGGER.info(
                "Legacy import finished: balance=%s inputs=%d",
                report.balance,
                report.inputs,
            )
            return report
        finally:
            client.close()


@contextmanager
def _legacy_daemon(
    project: ProjectConfig, settings: Settings, wallet_file: Path
) -> Iterator[RPCClient]:
    """Load a copy of a legacy wallet in an isolated, offline daemon."""
    binary = discover_daemon(project, settings.daemon_binary)
    if binary is None:
        raise RuntimeError("novacoind не найден: соберите демон или укажите путь")
    if not wallet_file.is_file():
        raise ValueError("Файл wallet.dat не найден")
    port = _free_port()
    p2p_port = _free_port(18501, 18600)
    with tempfile.TemporaryDirectory(prefix="phoenix-legacy-") as temporary:
        datadir = Path(temporary)
        shutil.copy2(wallet_file, datadir / "wallet.dat")
        user = "phoenix-migration"
        password = os.urandom(24).hex()
        conf = (
            "server=1\n"
            f"rpcuser={user}\n"
            f"rpcpassword={password}\n"
            f"rpcport={port}\n"
            "rpcbind=127.0.0.1\n"
            "rpcallowip=127.0.0.1\n"
            "connect=0\n"
            "listen=0\n"
            "dnsseed=0\n"
            "maxconnections=0\n"
        )
        (datadir / "novacoin.conf").write_text(conf, encoding="utf-8")
        args = [
            str(binary),
            f"-datadir={datadir}",
            f"-rpcport={port}",
            f"-port={p2p_port}",
            "-server=1",
            "-connect=0",
            "-listen=0",
            "-dnsseed=0",
            "-maxconnections=0",
        ]
        if project.testnet:
            args.append("-testnet")
        process = subprocess.Popen(
            args,
            cwd=str(project.root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_hidden_flags(),
        )
        client = RPCClient(f"http://127.0.0.1:{port}", user, password, timeout=30.0)
        try:
            _wait_for_daemon(client, process)
            yield client
        finally:
            try:
                client.call("stop")
            except (RPCError, OSError):
                pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=4)
            client.close()


def _wait_for_daemon(client: RPCClient, process: subprocess.Popen) -> None:
    """Wait until the private daemon answers RPC or exits."""
    import time

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Временный novacoind завершился при открытии wallet.dat. "
                "Проверьте, что файл не поврежден и создан этой сетью."
            )
        try:
            client.call("getinfo")
            return
        except (RPCError, OSError):
            time.sleep(0.4)
    raise RuntimeError("Временный novacoind не открыл wallet.dat за 30 секунд")


def import_wallet_file(
    project: ProjectConfig, settings: Settings, wallet_file: Path, passphrase: str = ""
) -> MigrationReport:
    """Extract all keys from wallet.dat through an offline daemon and import them."""
    with (
        _paused_indexer(project),
        _legacy_daemon(project, settings, wallet_file) as legacy,
    ):
        if passphrase:
            try:
                legacy.call("walletpassphrase", [passphrase, 300])
            except RPCError as exc:
                raise ValueError(
                    "Не удалось разблокировать wallet.dat. Проверьте пароль."
                ) from exc
        with tempfile.TemporaryDirectory(prefix="phoenix-wallet-dump-") as temporary:
            dump = Path(temporary) / "dump.txt"
            legacy.call("dumpwallet", [str(dump)])
            if not dump.is_file():
                raise RuntimeError("Демон не создал дамп ключей")
            text = dump.read_text(encoding="utf-8", errors="replace")
            keys = sum(
                1
                for line in text.splitlines()
                if line and not line.startswith("#") and len(line.split()) >= 3
            )
            main = _direct_client(project)
            try:
                main.call("importwallet", [str(dump)])
                return _report(main, "wallet.dat", keys=keys)
            finally:
                main.close()


def sweep_all(
    project: ProjectConfig, destination: str, fee_reserve: Decimal = Decimal("0.001")
) -> tuple[str, Decimal]:
    """Send the whole imported balance to a Phoenix address.

    A small reserve covers the legacy daemon fee.  The returned amount is
    the value actually sent; the imported keys remain in the daemon wallet
    and can be removed by restoring its backup.
    """
    address = validate_destination(destination, project)
    with _paused_indexer(project):
        client = _direct_client(project)
        try:
            balance = Decimal(str(client.call("getbalance") or 0))
            amount = balance - fee_reserve
            if amount <= Decimal("0.0001"):
                raise ValueError("На перенесенном балансе нет средств для вывода")
            result = client.call("sendtoaddress", [address, float(f"{amount:.8f}")])
            return str(result or ""), amount
        finally:
            client.close()
