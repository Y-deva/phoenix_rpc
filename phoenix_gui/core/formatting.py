"""Formatting helpers shared by the whole application.

All user-facing strings in this module use plain ASCII punctuation on
purpose. The interface must remain readable on keyboards without special
characters, so no emoji, fancy arrows or typographic dashes are used.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

COIN = Decimal("1000000")
SAT = Decimal("0.000001")
MAX_DECIMALS = 8
AMOUNT_QUANT = Decimal("0.00000001")

CATEGORY_LABELS = {
    "receive": "Получено",
    "send": "Отправлено",
    "consolidate": "Объединено",
    "generate": "Награда за блок",
    "immature": "Не созрело",
    "mined_pow": "Награда PoW",
    "mined_pos": "Награда PoS",
    "orphan": "Отменено",
}

CATEGORY_KINDS = {
    "receive": "receive",
    "send": "send",
    "consolidate": "send",
    "generate": "mine",
    "immature": "immature",
    "mined_pow": "mine",
    "mined_pos": "mine",
}


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Convert a loosely typed RPC value to a quantized Decimal amount."""
    if value is None or value == "":
        return default.quantize(AMOUNT_QUANT)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default.quantize(AMOUNT_QUANT)
    if not number.is_finite():
        return default.quantize(AMOUNT_QUANT)
    return number.quantize(AMOUNT_QUANT, rounding=ROUND_HALF_UP)


def to_sat(value: Any) -> int:
    """Convert an amount expressed in coins to an integer number of coins."""
    return int((to_decimal(value) * COIN).to_integral_value(rounding=ROUND_HALF_UP))


def from_sat(value: int) -> Decimal:
    """Convert an integer number of base units back to coins."""
    return (Decimal(int(value)) / COIN).quantize(AMOUNT_QUANT)


def format_amount(
    value: Any,
    places: int = MAX_DECIMALS,
    trim: bool = True,
    group: bool = True,
) -> str:
    """Format a coin amount without the ticker.

    Trailing zeros are removed when ``trim`` is True, but at least two
    decimal places are kept so small values never look like integers.
    """
    amount = to_decimal(value)
    places = max(0, min(MAX_DECIMALS, int(places)))
    quant = Decimal(1).scaleb(-places)
    text = f"{amount.quantize(quant, rounding=ROUND_HALF_UP):,.{places}f}"
    if trim and "." in text:
        whole, fraction = text.split(".", 1)
        fraction = fraction.rstrip("0")
        if len(fraction) < 2:
            fraction = fraction.ljust(2, "0")
        text = f"{whole}.{fraction}"
    return text


def format_nvc(
    value: Any,
    places: int = MAX_DECIMALS,
    trim: bool = True,
    unit: str = "NVC",
) -> str:
    """Format an amount and append the coin ticker."""
    return f"{format_amount(value, places=places, trim=trim)} {unit}"


def format_signed_nvc(value: Any, places: int = MAX_DECIMALS) -> str:
    """Format an amount with an explicit sign for transaction tables."""
    amount = to_decimal(value)
    sign = "+" if amount > 0 else ""
    return f"{sign}{format_amount(amount, places=places)}"


def parse_amount(text: str) -> Decimal:
    """Parse a user-entered amount.

    Both a dot and a comma are accepted as the decimal separator because
    Russian keyboards and habits often produce a comma. Spaces and a
    trailing ticker are ignored.
    """
    cleaned = (text or "").strip().replace(" ", "").replace("\u00a0", "")
    for unit in ("NVC", "nvc"):
        if cleaned.endswith(unit):
            cleaned = cleaned[: -len(unit)].strip()
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    if not cleaned or cleaned in (".", ","):
        raise ValueError("Сумма не указана")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Сумма указана неверно") from exc
    if not amount.is_finite():
        raise ValueError("Сумма должна быть конечным числом")
    if amount < 0:
        raise ValueError("Сумма не может быть отрицательной")
    if amount.as_tuple().exponent < -MAX_DECIMALS:
        raise ValueError("too many decimal places")
    return amount.quantize(AMOUNT_QUANT)


def format_int(value: Any) -> str:
    """Format an integer with thousands separators."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def format_timestamp(timestamp: Any, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Format a UNIX timestamp in the local time zone."""
    try:
        seconds = int(timestamp)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "-"
    try:
        return datetime.fromtimestamp(seconds).strftime(fmt)
    except (OverflowError, OSError, ValueError):
        return "-"


def format_date(timestamp: Any) -> str:
    """Format a UNIX timestamp as a short local date."""
    return format_timestamp(timestamp, "%d.%m.%Y")


def format_relative(timestamp: Any, now: float | None = None) -> str:
    """Return a short human-readable age in Russian."""
    try:
        seconds = int(timestamp)
    except (TypeError, ValueError):
        return "-"
    if seconds <= 0:
        return "-"
    current = int(now) if now is not None else int(datetime.now().timestamp())
    delta = max(0, current - seconds)
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{delta // 60} мин назад"
    if delta < 86400:
        return f"{delta // 3600} ч назад"
    if delta < 86400 * 30:
        return f"{delta // 86400} дн назад"
    return format_date(seconds)


def shorten_middle(text: str, head: int = 8, tail: int = 6) -> str:
    """Shorten a long identifier while keeping both ends readable."""
    value = text or ""
    if len(value) <= head + tail + 3:
        return value
    if tail <= 0:
        return f"{value[:head]}..."
    return f"{value[:head]}...{value[-tail:]}"


def shorten_txid(txid: str, head: int = 10, tail: int = 8) -> str:
    """Shorten a transaction id for compact table cells."""
    return shorten_middle(txid, head, tail)


def shorten_address(address: str, head: int = 10, tail: int = 8) -> str:
    """Shorten a wallet address for compact table cells."""
    return shorten_middle(address, head, tail)


def format_percent(value: Any, digits: int = 1) -> str:
    """Format a fraction (0..1) or an already scaled percentage."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "0.0%"
    if number <= 1.0:
        number *= 100.0
    return f"{number:.{max(0, digits)}f}%"


def format_duration(seconds: Any) -> str:
    """Format a duration in Russian units."""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return "-"
    if total < 60:
        return f"{total} с"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} мин {sec:02d} с"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ч {minutes:02d} мин"
    days, hours = divmod(hours, 24)
    return f"{days} дн {hours:02d} ч"


def format_bytes(size: Any) -> str:
    """Format a byte count with binary units."""
    try:
        value = float(size)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} TiB"


def format_difficulty(value: Any) -> str:
    """Format a network difficulty with an ASCII suffix."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    for suffix, scale in (("T", 1e12), ("G", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(number) >= scale:
            return f"{number / scale:.2f} {suffix}"
    return f"{number:.2f}"


def format_json(value: Any, pretty: bool = True) -> str:
    """Serialize a value to deterministic, human-readable JSON."""
    try:
        if pretty:
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def category_label(category: str) -> str:
    """Return a human label for a daemon transaction category."""
    return CATEGORY_LABELS.get((category or "").lower(), "Другое")


def category_kind(category: str) -> str:
    """Return a coarse kind used to choose colors and icons."""
    return CATEGORY_KINDS.get((category or "").lower(), "other")


def sum_amounts(values: Iterable[Any]) -> Decimal:
    """Sum loosely typed amounts without accumulating binary float errors."""
    total = Decimal("0")
    for value in values:
        total += to_decimal(value)
    return total.quantize(AMOUNT_QUANT)
