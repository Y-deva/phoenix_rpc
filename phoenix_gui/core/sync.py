"""Synchronization state shared by the status bar and overview page."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import ProjectConfig
from ..rpc.models import ChainInfo, NetworkInfo

LAST_PARSED_FILE = "last_parsed_block.txt"
LAST_KNOWN_FILE = "last_known_block.txt"


@dataclass(frozen=True)
class ParserProgress:
    """Progress of the proxy's local UTXO parser."""

    last_parsed: int = 0
    last_known: int = 0
    available: bool = False

    @property
    def percent(self) -> Decimal:
        """Return parser progress as a 0..100 value."""
        if not self.available or self.last_known <= 0:
            return Decimal("0")
        value = Decimal(self.last_parsed) / Decimal(self.last_known) * Decimal("100")
        return min(Decimal("100"), max(Decimal("0"), value))

    @property
    def synced(self) -> bool:
        """Return whether the parser has reached the known block."""
        return (
            self.available
            and self.last_known > 0
            and self.last_parsed >= self.last_known - 1
        )


@dataclass(frozen=True)
class SyncStatus:
    """Combined daemon and local parser synchronization state."""

    network: NetworkInfo
    chain: ChainInfo
    parser: ParserProgress

    @property
    def daemon_percent(self) -> Decimal:
        """Return daemon synchronization progress as 0..100."""
        headers = self.chain.headers or self.network.blocks
        if headers <= 0:
            return Decimal("100")
        blocks = self.chain.blocks or self.network.blocks
        value = Decimal(blocks) / Decimal(headers) * Decimal("100")
        return min(Decimal("100"), max(Decimal("0"), value))

    @property
    def daemon_synced(self) -> bool:
        """Return whether the daemon has caught up with the chain."""
        headers = self.chain.headers or self.network.blocks
        return headers <= 0 or (self.chain.blocks or self.network.blocks) >= headers - 1

    @property
    def fully_synced(self) -> bool:
        """Return whether both daemon and parser are synchronized."""
        return self.daemon_synced and (not self.parser.available or self.parser.synced)

    @property
    def blocks(self) -> int:
        """Return the best known block height."""
        return max(self.network.blocks, self.chain.blocks)

    @property
    def headers(self) -> int:
        """Return the best known header height."""
        return max(self.chain.headers, self.blocks)


def read_height_file(path: Path) -> int:
    """Read a single integer from a height file, returning zero on error."""
    try:
        text = path.read_text(encoding="utf-8").strip()
        return max(0, int(text))
    except (OSError, ValueError):
        return 0


def load_parser_progress(
    project: ProjectConfig | None, root: str | Path | None = None
) -> ParserProgress:
    """Load the parser height files written by ``utxo_parser.py``."""
    base = Path(root) if root else (project.root if project else Path.cwd())
    parsed = read_height_file(base / LAST_PARSED_FILE)
    known = read_height_file(base / LAST_KNOWN_FILE)
    if parsed == 0 and known == 0:
        return ParserProgress()
    return ParserProgress(last_parsed=parsed, last_known=known, available=True)


def build_sync_status(
    network: NetworkInfo,
    chain: ChainInfo,
    project: ProjectConfig | None = None,
    root: str | Path | None = None,
) -> SyncStatus:
    """Combine RPC and filesystem information into one status object."""
    return SyncStatus(
        network=network, chain=chain, parser=load_parser_progress(project, root)
    )


def network_from_status(status: SyncStatus) -> dict[str, Any]:
    """Return a compact dictionary used by diagnostics."""
    return {
        "blocks": status.blocks,
        "headers": status.headers,
        "daemon_percent": float(status.daemon_percent),
        "parser_last": status.parser.last_parsed,
        "parser_known": status.parser.last_known,
        "fully_synced": status.fully_synced,
    }
