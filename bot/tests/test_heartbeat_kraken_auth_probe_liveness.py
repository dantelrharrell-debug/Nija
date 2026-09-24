"""Regression tests for bounded Kraken heartbeat AUTH_VERIFY."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from bot import trading_strategy as ts


class KrakenBroker:
    def __init__(self) -> None:
        self._kraken_private_call = MagicMock()


class CoinbaseBroker:
    pass


def test_kraken_heartbeat_auth_reuses_recent_authenticated_balance_without_new_io():
    broker = KrakenBroker()
    recent = {
        "response": {"error": [], "result": {"ZUSD": "43.61", "USDT": "0"}},
        "age_s": 2.0,
    }
    with (
        patch("bot.runtime_kraken_recent_balance_prewait_v319_patch._recent_observation", return_value=recent),
        patch("bot.runtime_heartbeat_auth_probe_bound_v210_patch._reassert_kraken_read_bounds") as reassert,
    ):
        ok, detail = ts._kraken_heartbeat_auth_probe(broker)

    assert ok is True
    assert detail == "kraken_recent_authenticated_balance"
    reassert.assert_not_called()
    broker._kraken_private_call.assert_not_called()


def test_kraken_heartbeat_auth_defers_without_fresh_observation_and_does_no_io():
    broker = KrakenBroker()
    with patch(
        "bot.runtime_kraken_recent_balance_prewait_v319_patch._recent_observation",
        return_value=None,
    ):
        ok, detail = ts._kraken_heartbeat_auth_probe(broker)

    assert ok is False
    assert detail == "kraken_recent_authenticated_balance_unavailable"
    broker._kraken_private_call.assert_not_called()


def test_kraken_heartbeat_auth_rejects_error_observation_without_new_io():
    broker = KrakenBroker()
    recent = {
        "response": {"error": ["EAPI:Invalid key"], "result": {}},
        "age_s": 2.0,
    }
    with patch(
        "bot.runtime_kraken_recent_balance_prewait_v319_patch._recent_observation",
        return_value=recent,
    ):
        ok, detail = ts._kraken_heartbeat_auth_probe(broker)

    assert ok is False
    assert detail == "kraken_recent_authenticated_balance_unavailable"
    broker._kraken_private_call.assert_not_called()


def test_non_kraken_broker_keeps_existing_auth_path():
    assert ts._kraken_heartbeat_auth_probe(CoinbaseBroker()) is None
