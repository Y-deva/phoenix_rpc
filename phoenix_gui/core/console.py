"""Parsing helpers for the graphical RPC console."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any


class ConsoleParseError(ValueError):
    """Raised when a console line cannot be converted to an RPC request."""


@dataclass(frozen=True)
class ConsoleCommand:
    """A parsed console command ready for JSON-RPC."""

    method: str
    params: list[Any]
    raw: str

    @property
    def signature(self) -> str:
        """Return a short representation for the output log."""
        if not self.params:
            return self.method
        rendered = " ".join(_render_param(value) for value in self.params)
        return f"{self.method} {rendered}"


def _render_param(value: Any) -> str:
    """Render one parameter for display without breaking quoting."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _parse_token(token: str) -> Any:
    """Convert a shell token to a JSON value when possible."""
    try:
        return json.loads(token)
    except (TypeError, ValueError):
        return token


def parse_command(line: str) -> ConsoleCommand:
    """Parse a console line into a method and positional parameters.

    Supports plain tokens, JSON arrays, and a full JSON-RPC request object.
    """
    text = (line or "").strip()
    if not text:
        raise ConsoleParseError("Введите команду")
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except ValueError as error:
            raise ConsoleParseError(f"Некорректный JSON: {error}") from error
        if not isinstance(payload, dict) or not payload.get("method"):
            raise ConsoleParseError("В JSON-запросе нет поля method")
        params = payload.get("params") or []
        if isinstance(params, dict):
            params = [params]
        if not isinstance(params, list):
            raise ConsoleParseError("Поле params должно быть массивом")
        return ConsoleCommand(str(payload["method"]).strip(), params, text)

    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as error:
        raise ConsoleParseError(f"Ошибка разбора строки: {error}") from error
    if not tokens:
        raise ConsoleParseError("Введите команду")
    method = tokens[0].strip().lower()
    if not method:
        raise ConsoleParseError("Не указано имя метода")
    rest = tokens[1:]
    if len(rest) == 1 and rest[0].startswith("["):
        try:
            payload = json.loads(rest[0])
        except ValueError:
            payload = None
        if isinstance(payload, list):
            return ConsoleCommand(method, payload, text)
    return ConsoleCommand(method, [_parse_token(token) for token in rest], text)
