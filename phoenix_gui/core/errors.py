"""Convert backend and OS exceptions into concise Russian messages."""

from __future__ import annotations

from typing import Any


def humanize_error(error: BaseException | Any) -> str:
    """Return a user-facing explanation for a background failure."""
    from ..rpc.client import (
        RPCAuthError,
        RPCConnectionError,
        RPCProtocolError,
        RPCError,
    )

    if isinstance(error, RPCConnectionError):
        return (
            "Нет связи с прокси. Проверьте, что main.py запущен, "
            "а адрес и порт в настройках совпадают."
        )
    if isinstance(error, RPCAuthError):
        return "Прокси отклонил логин или пароль. Проверьте настройки подключения."
    if isinstance(error, RPCProtocolError):
        return "Прокси вернул неожиданный ответ. Повторите запрос или проверьте журнал."
    if isinstance(error, RPCError):
        message = str(error.message or error)
        return message[:400]
    if isinstance(error, TimeoutError):
        return (
            "Операция заняла слишком много времени. Проверьте соединение и повторите."
        )
    if isinstance(error, ConnectionError):
        return "Соединение прервано. Проверьте сеть и повторите попытку."
    if isinstance(error, FileNotFoundError):
        return "Файл не найден. Проверьте путь в настройках."
    if isinstance(error, PermissionError):
        return "Недостаточно прав для доступа к файлу или папке."
    if isinstance(error, ValueError):
        return str(error)
    text = str(error).strip()
    return (
        text[:400]
        if text
        else "Неизвестная ошибка. Подробности можно увидеть в консоли."
    )
