"""Formatting helpers keep money exact and labels ASCII-friendly."""

from decimal import Decimal

import pytest

from phoenix_gui.core.formatting import (
    COIN,
    category_label,
    format_amount,
    format_bytes,
    format_duration,
    format_json,
    format_nvc,
    format_percent,
    format_signed_nvc,
    from_sat,
    parse_amount,
    shorten_address,
    shorten_middle,
    shorten_txid,
    to_sat,
)


def test_coin_constant_is_six_decimals():
    assert COIN == Decimal("1000000")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", Decimal("1000000")),
        ("0.000001", Decimal("1")),
        ("12.345678", Decimal("12345678")),
        (Decimal("0.1"), Decimal("100000")),
    ],
)
def test_to_sat(value, expected):
    assert to_sat(value) == expected


def test_from_sat_roundtrip():
    assert from_sat(12345678) == Decimal("12.345678")
    assert from_sat("1000000") == Decimal("1")


def test_format_amount_trims_but_keeps_two_places():
    assert format_amount(Decimal("12.50000000")) == "12.50"
    assert format_amount(Decimal("0.00000001")) == "0.00000001"
    assert format_amount(Decimal("1.00000000"), trim=True) == "1.00"


def test_format_nvc_contains_unit_once():
    text = format_nvc(Decimal("19.77"))
    assert text == "19.77 NVC"
    assert "NVC NVC" not in text


def test_format_signed_amount():
    assert format_signed_nvc(Decimal("2.5")).startswith("+")
    assert format_signed_nvc(Decimal("-2.5")).startswith("-")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,5", Decimal("1.5")),
        ("0.000001", Decimal("0.000001")),
        (" 2.25 ", Decimal("2.25")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "--1"])
def test_parse_amount_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_shorten_helpers():
    txid = "a" * 64
    assert shorten_txid(txid) == "aaaaaaaaaa...aaaaaaaa"
    assert shorten_txid(txid, 4, 4) == "aaaa...aaaa"
    assert shorten_address("2NEm3TqPq8gkFdGJGLUaZTk1gAhNubUurb9", 6, 4).endswith("urb9")
    assert shorten_middle("short", 10, 10) == "short"
    assert shorten_middle("abcdefghijklmnop", 4, 0) == "abcd..."


def test_human_labels_are_russian_and_ascii():
    assert category_label("receive") == "Получено"
    assert category_label("unknown") == "Другое"
    assert format_percent(Decimal("0.5")) == "50.0%"
    assert format_duration(61).startswith("1 мин")
    assert format_bytes(2048) == "2.0 KiB"
    assert format_json({"b": 1, "a": 2}).splitlines()[0] == "{"


def test_json_is_readable():
    data = {"address": "x", "items": [1, 2, 3]}
    text = format_json(data)
    assert '"address": "x"' in text
    assert "\n" in text
