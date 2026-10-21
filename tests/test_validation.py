"""Address, amount and OP_RETURN validation."""

from decimal import Decimal

import pytest

from phoenix_gui.core.validation import (
    address_from_hash,
    base58check_decode,
    base58check_encode,
    validate_address,
    validate_amount,
    validate_comment,
    validate_hex,
    validate_positive_int,
)


def test_base58check_roundtrip():
    payload = bytes(range(20))
    encoded = base58check_encode(0x14, payload)
    version, decoded = base58check_decode(encoded)
    assert version == 0x14
    assert decoded == payload


def test_mainnet_and_testnet_addresses():
    payload = bytes(range(20))
    mainnet = address_from_hash(payload, testnet=False, p2sh=True)
    testnet = address_from_hash(payload, testnet=True, p2sh=True)
    assert mainnet != testnet
    assert validate_address(mainnet).valid
    assert validate_address(mainnet).network == "mainnet"
    assert validate_address(testnet).network == "testnet"


def test_network_mismatch_is_warning_not_error():
    address = address_from_hash(b"x" * 20, testnet=True)
    result = validate_address(address, expected_network="mainnet")
    assert result.valid
    assert result.warning


def test_bad_checksum_and_characters():
    address = address_from_hash(b"x" * 20, testnet=True)
    replacement = "1" if address[-1] != "1" else "2"
    broken = address[:-1] + replacement
    assert not validate_address(broken).valid
    assert not validate_address("0OIl").valid
    assert not validate_address("").valid
    assert not validate_address("has space").valid


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", True),
        ("0.00001", True),
        ("0.000001", False),
        ("0", False),
        ("-1", False),
        ("abc", False),
        ("1.123456789", False),
    ],
)
def test_amount_bounds(value, expected):
    result = validate_amount(value)
    assert result.valid is expected


def test_amount_available_and_warning():
    result = validate_amount("5", available=Decimal("4"))
    assert result.valid
    assert "превышает" in result.warning
    warning = validate_amount("3.999999", available=Decimal("4"))
    assert warning.valid
    assert warning.warning == ""


def test_comment_counts_utf8_bytes():
    assert validate_comment("hello")[0]
    assert validate_comment("привет")[0]
    assert not validate_comment("ы" * 41)[0]
    assert validate_comment("x" * 81)[0] is False


def test_hex_validation():
    assert validate_hex("00ff")[0]
    assert not validate_hex("00f")[0]
    assert not validate_hex("zz")[0]
    assert validate_hex("")[0] is False


def test_positive_integer():
    assert validate_positive_int("10")[0]
    assert not validate_positive_int("0")[0]
    assert not validate_positive_int("-2")[0]
