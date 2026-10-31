"""Read, export and clear the application log without a terminal."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

LOG_FILENAME = "phoenix-wallet.log"
MAX_TAIL_CHARS = 240_000


def log_directory() -> Path:
    """Return the writable folder used by the rotating application log."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    folder = Path(base or Path.home() / ".local" / "share" / "phoenix")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def log_file() -> Path:
    """Return the current log file path."""
    return log_directory() / LOG_FILENAME


def log_files() -> list[Path]:
    """Return the current log and all rotated files, newest first."""
    folder = log_directory()
    files = list(folder.glob("phoenix-wallet.log*"))
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)


def read_log(limit: int = MAX_TAIL_CHARS) -> str:
    """Read the newest part of the current log file."""
    path = log_file()
    if not path.is_file():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max(1000, int(limit))))
        return handle.read()


def clear_log() -> None:
    """Empty the current log and its rotated backups."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            handler.flush()
    for path in log_files():
        try:
            path.write_text("", encoding="utf-8")
        except OSError:
            continue


def export_log(target: Path) -> Path:
    """Write the current log and rotated backups into one text file."""
    destination = Path(target).expanduser()
    if not destination.suffix:
        destination = destination.with_suffix(".log")
    destination.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    for path in log_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if text:
            chunks.append(f"===== {path.name} =====\n{text.rstrip()}\n")
    destination.write_text("\n".join(chunks), encoding="utf-8")
    return destination


_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def clean_output(text: str) -> list[str]:
    """Split process output into printable, size-limited log lines."""
    clean = _ANSI.sub("", text).replace("\r", "")
    return [line[:2000] for line in clean.splitlines() if line.strip()]
