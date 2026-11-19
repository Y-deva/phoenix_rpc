"""Regression tests for the aggressive-audit findings (AUD-2026-11)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import format_datetime
from pathlib import Path

import pytest

from phoenix_gui.core.config import parse_connection
from phoenix_gui.core.formatting import (
    format_amount,
    format_percent,
    parse_amount,
)
from phoenix_gui.core.validation import (
    base58_decode,
    base58_encode,
    validate_amount,
)


def test_mixed_separators_are_scaled_correctly():
    """1.000,00 and 1,000.00 both mean one thousand."""
    assert parse_amount("1.000,00") == Decimal("1000.00000000")
    assert parse_amount("1,000.00") == Decimal("1000.00000000")
    assert parse_amount("1.000.000,50") == Decimal("1000000.50000000")
    assert parse_amount("1,000,000.50") == Decimal("1000000.50000000")


def test_ambiguous_mixed_separators_are_rejected():
    """Bad digit grouping must not silently change the amount."""
    for value in ("12.34,56", "1.0000,00", "1,000,00", "1.2.3,4"):
        with pytest.raises(ValueError):
            parse_amount(value)


def test_huge_and_non_finite_amounts_do_not_crash():
    with pytest.raises(ValueError):
        parse_amount("1e100")
    assert format_amount("1e100") == "0.00"
    assert validate_amount(Decimal("NaN")).valid is False
    assert validate_amount(Decimal("Infinity")).valid is False


def test_group_flag_and_percent_fraction():
    assert format_amount("1234.5", group=False) == "1234.50"
    assert format_amount("1234.5") == "1,234.50"
    assert format_percent(Decimal("1.5")) == "150.0%"


def test_base58_zero_payload_roundtrip():
    assert base58_decode(base58_encode(b"\x00")) == b"\x00"
    assert base58_decode(base58_encode(b"\x00\x00")) == b"\x00\x00"
    assert base58_decode("1") == b"\x00"


def test_connection_parser_rejects_bad_port_and_keeps_ipv6_brackets():
    with pytest.raises(ValueError, match="порт"):
        parse_connection("http://127.0.0.1:notaport")
    url, user, password = parse_connection("http://user:pass@[::1]:16666")
    assert url == "http://[::1]:16666"
    assert user == "user"
    assert password == "pass"


def test_retry_after_http_date_is_honoured(monkeypatch):
    """A Retry-After date should produce a useful cooldown, not two seconds."""
    from types import SimpleNamespace

    from phoenix_gui.rpc.client import RPCClient

    client = RPCClient("http://127.0.0.1:1", "user", "pass")
    future = format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=120), usegmt=True
    )
    response = SimpleNamespace(
        status_code=429,
        headers={"Retry-After": future},
        reason="Too Many Requests",
        text="{}",
        json=lambda: {},
    )
    monkeypatch.setattr(
        client,
        "_session",
        lambda: SimpleNamespace(post=lambda *args, **kwargs: response),
    )
    with pytest.raises(Exception) as error:
        client.call("getinfo")
    assert 100 <= error.value.retry_after <= 300


def test_rate_limit_streak_does_not_overflow(monkeypatch):
    """Even an absurd streak must stay capped instead of raising OverflowError."""
    from types import SimpleNamespace

    from phoenix_gui.rpc.client import RPCClient

    client = RPCClient("http://127.0.0.1:1", "user", "pass")
    client._limit_streak = 5000
    response = SimpleNamespace(
        status_code=429,
        headers={},
        reason="Too Many Requests",
        text="{}",
        json=lambda: {},
    )
    monkeypatch.setattr(
        client,
        "_session",
        lambda: SimpleNamespace(post=lambda *args, **kwargs: response),
    )
    with pytest.raises(Exception) as error:
        client.call("getinfo")
    assert error.value.retry_after == 60.0


def test_empty_qr_save_is_rejected(qtbot, tmp_path):
    from phoenix_gui.ui.widgets.qr import QrCode

    qr = QrCode()
    qtbot.addWidget(qr)
    assert qr.save_png(str(tmp_path / "empty.png")) is False
    assert not (tmp_path / "empty.png").exists()


def test_csv_export_neutralizes_formulas_and_has_bom(qtbot, tmp_path):
    from phoenix_gui.ui.widgets.table import Column, SortableTable, text_item

    table = SortableTable([Column("Комментарий", 220)], row_height=32)
    qtbot.addWidget(table)
    table.set_rows([[text_item("=1+1")], [text_item("@SUM(A1)")], [text_item("-5")]])
    target = Path(tmp_path / "safe.csv")
    assert table.export_csv(target) == 3
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "'=1+1" in text
    assert "'@SUM(A1)" in text
    assert "-5" in text


def test_toast_close_button_uses_muted_color(qtbot):
    from PyQt6.QtGui import QColor

    from phoenix_gui.ui.widgets.toast import Toast

    toast = Toast("Title", "Message", "info", colors={"muted": "#00ff00"})
    qtbot.addWidget(toast)
    image = toast.close_button.icon().pixmap(14, 14).toImage()
    colors = [
        QColor(image.pixel(x, y))
        for x in range(image.width())
        for y in range(image.height())
        if QColor(image.pixel(x, y)).alpha() > 0
    ]
    # Anti-aliasing blends the stroke with transparent pixels, so assert the
    # green hue instead of an exact RGB match.
    assert any(color.green() > 200 and color.red() < 20 for color in colors)
