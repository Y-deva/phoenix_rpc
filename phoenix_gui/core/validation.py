"""Address, amount and comment validation.

Phoenix uses NovaCoin-style Base58Check addresses with P2PKH and P2SH
prefixes. The checks here are intentionally complete enough to catch
typos before an RPC call, but they do not attempt to verify that an
address belongs to the current wallet.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from .formatting import MAX_DECIMALS, format_nvc, parse_amount, to_decimal

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
BASE58_INDEX = {char: index for index, char in enumerate(BASE58_ALPHABET)}

MAINNET_P2PKH = 0x08
MAINNET_P2SH = 0x14
TESTNET_P2PKH = 0x6F
TESTNET_P2SH = 0xC4

ADDRESS_PREFIXES = {
    MAINNET_P2PKH: ("mainnet", "P2PKH"),
    MAINNET_P2SH: ("mainnet", "P2SH"),
    TESTNET_P2PKH: ("testnet", "P2PKH"),
    TESTNET_P2SH: ("testnet", "P2SH"),
}


@dataclass(frozen=True)
class AddressCheck:
    """Result of validating a wallet address."""

    valid: bool
    reason: str = ""
    kind: str = ""
    network: str = ""
    warning: str = ""

    @property
    def summary(self) -> str:
        """Return a compact human description for the receive form."""
        if not self.valid:
            return self.reason
        parts = [self.network, self.kind]
        text = " ".join(part for part in parts if part)
        if self.warning:
            return f"{text}. {self.warning}"
        return text


@dataclass(frozen=True)
class AmountCheck:
    """Result of validating a user-entered amount."""

    valid: bool
    amount: Decimal = Decimal("0")
    reason: str = ""
    warning: str = ""


def base58_encode(payload: bytes) -> str:
    """Encode bytes using the Bitcoin Base58 alphabet."""
    if not payload:
        return ""
    number = int.from_bytes(payload, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    leading = len(payload) - len(payload.lstrip(b"\x00"))
    return "1" * leading + (encoded or "")


def base58_decode(value: str) -> bytes:
    """Decode a Base58 string, raising ValueError on invalid characters."""
    if not isinstance(value, str) or not value:
        raise ValueError("address is empty")
    number = 0
    for char in value:
        try:
            digit = BASE58_INDEX[char]
        except KeyError as exc:
            raise ValueError(f"invalid Base58 character: {char!r}") from exc
        number = number * 58 + digit
    length = max(1, (number.bit_length() + 7) // 8)
    decoded = number.to_bytes(length, "big")
    leading = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading + decoded


def base58check_decode(value: str) -> tuple[int, bytes]:
    """Decode and verify a Base58Check string.

    Returns the version byte and the 20-byte payload. Raises ValueError if
    the checksum or the payload length is wrong.
    """
    raw = base58_decode(value.strip())
    if len(raw) < 5:
        raise ValueError("address is too short")
    payload, checksum = raw[:-4], raw[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        raise ValueError("address checksum mismatch")
    version, body = payload[0], payload[1:]
    if len(body) != 20:
        raise ValueError("address payload has an unexpected length")
    return version, body


def base58check_encode(version: int, payload: bytes) -> str:
    """Create a Base58Check string from a version byte and payload."""
    if len(payload) != 20:
        raise ValueError("payload must be exactly 20 bytes")
    body = bytes([version]) + payload
    checksum = hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4]
    return base58_encode(body + checksum)


def address_from_hash(
    script_hash: bytes, testnet: bool = False, p2sh: bool = True
) -> str:
    """Build an address from a 20-byte script hash.

    This helper is also used by the demo data generator and by tests.
    """
    if testnet:
        version = TESTNET_P2SH if p2sh else TESTNET_P2PKH
    else:
        version = MAINNET_P2SH if p2sh else MAINNET_P2PKH
    return base58check_encode(version, script_hash)


def validate_address(
    value: str,
    expected_network: str | None = None,
    allow_empty: bool = False,
) -> AddressCheck:
    """Validate a Phoenix address.

    ``expected_network`` may be "mainnet" or "testnet". A mismatch is
    reported as a warning rather than an error, because a user may
    deliberately paste an address from another network.
    """
    text = (value or "").strip()
    if not text:
        if allow_empty:
            return AddressCheck(True)
        return AddressCheck(False, "Введите адрес получателя")
    if any(char.isspace() for char in text):
        return AddressCheck(False, "Адрес не должен содержать пробелы")
    if len(text) < 26 or len(text) > 40:
        return AddressCheck(False, "Неверная длина адреса")
    try:
        version, _ = base58check_decode(text)
    except ValueError:
        return AddressCheck(False, "Адрес не прошел проверку Base58Check")
    network, kind = ADDRESS_PREFIXES.get(version, ("unknown", "unknown"))
    if network == "unknown":
        return AddressCheck(False, "Неизвестный префикс адреса")
    warning = ""
    if expected_network and network != expected_network:
        warning = (
            f"Адрес относится к сети {network}, "
            f"кошелек работает в сети {expected_network}"
        )
    return AddressCheck(True, kind=kind, network=network, warning=warning)


def validate_amount(
    value: str | Decimal,
    available: Decimal | None = None,
    dust: Decimal = Decimal("0.00001"),
    require_positive: bool = True,
) -> AmountCheck:
    """Validate an amount typed by the user against balance and dust rules."""
    try:
        amount = value if isinstance(value, Decimal) else parse_amount(str(value))
    except ValueError as exc:
        return AmountCheck(False, reason=str(exc))
    if require_positive and amount <= 0:
        return AmountCheck(False, reason="Сумма должна быть больше нуля")
    if amount < 0:
        return AmountCheck(False, reason="Сумма не может быть отрицательной")
    if amount != amount.quantize(Decimal(1).scaleb(-MAX_DECIMALS)):
        return AmountCheck(False, reason="Слишком много знаков после запятой")
    if dust > 0 and 0 < amount < dust:
        return AmountCheck(
            False, reason=f"Сумма ниже пылевого порога {format_nvc(dust)}"
        )
    warning = ""
    if available is not None and amount > available:
        warning = f"Сумма превышает доступный баланс {format_nvc(available)}"
    return AmountCheck(
        True, amount=amount.quantize(to_decimal("0.00000001")), warning=warning
    )


def validate_comment(value: str, max_bytes: int = 80) -> tuple[bool, str]:
    """Check that an OP_RETURN comment fits into the transaction."""
    text = value or ""
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        return False, f"Комментарий слишком длинный: {len(encoded)} из {max_bytes} байт"
    return True, ""


def validate_hex(value: str) -> tuple[bool, str]:
    """Check that a string is a non-empty, even-length hexadecimal blob."""
    text = (value or "").strip()
    if not text:
        return False, "Сырая транзакция пуста"
    if len(text) % 2:
        return False, "Hex-строка должна содержать четное число символов"
    try:
        bytes.fromhex(text)
    except ValueError:
        return False, "Сырая транзакция содержит недопустимые символы"
    return True, ""


def validate_positive_int(value: str, minimum: int = 1) -> tuple[bool, int]:
    """Parse a positive integer form field."""
    try:
        number = int(str(value).strip())
    except ValueError:
        return False, 0
    return (number >= minimum, number)
