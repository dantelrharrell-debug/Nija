"""Read-only Kraken public valuation recovery must preserve fail-closed position truth."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bot import runtime_kraken_position_refresh_liveness_v286_patch as v286


def test_strict_public_quote_rejects_errors_and_invalid_data():
    assert v286._strict_public_quote_payload({"error": [], "result": {"BABYUSD": {"c": ["0.02", "1"]}}}) == 0.02
    assert v286._strict_public_quote_payload({"error": ["EQuery:Unknown asset pair"], "result": {"BABYUSD": {"c": ["0.02"]}}}) == 0.0
    assert v286._strict_public_quote_payload({"error": [], "result": {"BABYUSD": {"c": ["nan"]}}}) == 0.0
    assert v286._strict_public_quote_payload({"error": [], "result": {"BABYUSD": {"c": ["0"]}}}) == 0.0
    assert v286._strict_public_quote_payload({"error": [], "result": {}}) == 0.0


def test_unpriced_authoritative_balance_keeps_quantity_and_source():
    broker = SimpleNamespace(_FIAT_ASSETS=set(), _price_cache={},
                             supports_symbol=lambda _: True)
    with patch.object(v286, "_bounded_public_usd_quote", return_value=0.02) as read:
        rows = v286._build_authoritative_rows(broker, {"BABY": "0.00142"})
    assert len(rows) == 1
    assert rows[0]["quantity"] == 0.00142
    assert rows[0]["current_price"] == 0.02
    assert rows[0]["size_usd"] == 0.00142 * 0.02
    assert rows[0]["authoritative_balance"] is True
    assert "entry_price" not in rows[0]
    read.assert_called_once_with(broker, "BABY-USD")


def test_missing_price_keeps_position_unpriced():
    broker = SimpleNamespace(_FIAT_ASSETS=set(), _price_cache={},
                             supports_symbol=lambda _: True)
    with patch.object(v286, "_bounded_public_usd_quote", return_value=0.0):
        rows = v286._build_authoritative_rows(broker, {"BABY": "0.00142"})
    assert rows[0]["pricing_verified"] is False
    assert rows[0]["size_usd"] == 0.0
    assert "entry_price" not in rows[0]
