"""Discovery and parsing of the Phoenix project configuration.

The GUI must work both when launched from the repository and when the
repository is passed explicitly. Configuration lives in ``config.toml``;
environment variables can override the connection details, which is
useful for portable builds and for tests.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 16666
DEFAULT_DAEMON_PORT = 8344

ENV_PROXY_URL = "PHOENIX_PROXY_URL"
ENV_PROXY_USER = "PHOENIX_PROXY_USER"
ENV_PROXY_PASSWORD = "PHOENIX_PROXY_PASSWORD"
ENV_PROJECT_ROOT = "PHOENIX_PROJECT_ROOT"
ENV_NOVACOIND = "PHOENIX_NOVACOIND"


@dataclass(frozen=True)
class ProjectConfig:
    """Connection settings and wallet-wide defaults for this checkout."""

    root: Path
    proxy_url: str = f"http://{DEFAULT_PROXY_HOST}:{DEFAULT_PROXY_PORT}"
    proxy_user: str = ""
    proxy_password: str = ""
    daemon_url: str = f"http://{DEFAULT_PROXY_HOST}:{DEFAULT_DAEMON_PORT}"
    daemon_user: str = ""
    daemon_password: str = ""
    sat_per_byte: int = 1
    dust_threshold_sat: int = 1000
    testnet: bool = False
    database_path: str = "wallets.db"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def network(self) -> str:
        """Return the configured network name."""
        return "testnet" if self.testnet else "mainnet"

    @property
    def daemon_port(self) -> int:
        """Return the daemon RPC port parsed from its URL."""
        try:
            return int(urlparse(self.daemon_url).port or DEFAULT_DAEMON_PORT)
        except ValueError:
            return DEFAULT_DAEMON_PORT

    @property
    def default_datadir(self) -> Path:
        """Return the conventional NovaCoin data directory for this OS."""
        if os.name == "nt":
            base = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            return Path(base) / "novacoin"
        if os.uname().sysname == "Darwin":
            return Path.home() / "Library" / "Application Support" / "NovaCoin"
        return Path.home() / ".novacoin"

    @property
    def config_path(self) -> Path:
        """Return the path of the TOML configuration file."""
        return self.root / "config.toml"

    def database_full_path(self) -> Path:
        """Resolve the wallet database path relative to the project root."""
        path = Path(self.database_path)
        if path.is_absolute():
            return path
        return self.root / path


def find_project_root(start: str | Path | None = None) -> Path:
    """Find the directory that contains ``config.toml`` or ``main.py``.

    The search walks up a limited number of parents so a frozen build
    cannot accidentally climb to the filesystem root.
    """
    if start is None:
        start = Path.cwd()
    candidate = Path(start).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for _ in range(8):
        if (candidate / "config.toml").exists() or (candidate / "main.py").exists():
            return candidate
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    return Path(start).expanduser().resolve()


def _read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML file, returning an empty mapping when it is absent."""
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Safely fetch a TOML table."""
    value = data.get(name, {})
    return value if isinstance(value, dict) else {}


def _as_int(value: Any, default: int) -> int:
    """Convert a configuration value to an integer."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_project_config(root: str | Path | None = None) -> ProjectConfig:
    """Load the project configuration with environment overrides.

    Missing values fall back to the defaults used by ``conf_gen.py`` so a
    fresh checkout can be opened before ``main.py`` has generated a config.
    """
    env_root = os.environ.get(ENV_PROJECT_ROOT)
    resolved_root = (
        Path(root).expanduser()
        if root
        else Path(env_root).expanduser()
        if env_root
        else find_project_root()
    )
    resolved_root = resolved_root.resolve()
    data = _read_toml(resolved_root / "config.toml")

    daemon = _section(data, "daemon")
    proxy = _section(data, "proxy")
    wallet = _section(data, "wallet")
    network = _section(data, "network")

    daemon_url = str(
        daemon.get("url") or f"http://{DEFAULT_PROXY_HOST}:{DEFAULT_DAEMON_PORT}"
    )
    proxy_host = str(proxy.get("host") or DEFAULT_PROXY_HOST)
    proxy_port = _as_int(proxy.get("port"), DEFAULT_PROXY_PORT)
    proxy_url = f"http://{proxy_host}:{proxy_port}"

    proxy_url = os.environ.get(ENV_PROXY_URL, proxy_url)
    proxy_user = os.environ.get(ENV_PROXY_USER, str(proxy.get("user") or ""))
    proxy_password = os.environ.get(
        ENV_PROXY_PASSWORD, str(proxy.get("password") or "")
    )

    testnet_value = network.get("testnet", False)
    if isinstance(testnet_value, str):
        testnet = testnet_value.strip().lower() in {"1", "true", "yes", "on"}
    else:
        testnet = bool(testnet_value)

    return ProjectConfig(
        root=resolved_root,
        proxy_url=proxy_url.rstrip("/"),
        proxy_user=proxy_user,
        proxy_password=proxy_password,
        daemon_url=daemon_url.rstrip("/"),
        daemon_user=str(daemon.get("user") or ""),
        daemon_password=str(daemon.get("password") or ""),
        sat_per_byte=max(1, _as_int(wallet.get("sat_per_byte"), 1)),
        dust_threshold_sat=max(0, _as_int(wallet.get("dust_threshold"), 1000)),
        testnet=testnet,
        database_path=str(wallet.get("database") or "wallets.db"),
        raw=data,
    )


def parse_connection(text: str) -> tuple[str, str, str]:
    """Parse ``http://user:pass@host:port`` into URL, user and password."""
    parsed = urlparse((text or "").strip())
    if not parsed.scheme:
        parsed = urlparse(f"http://{text.strip()}")
    user = parsed.username or ""
    password = parsed.password or ""
    host = parsed.hostname or DEFAULT_PROXY_HOST
    port = parsed.port or DEFAULT_PROXY_PORT
    return f"{parsed.scheme or 'http'}://{host}:{port}", user, password
