from __future__ import annotations

import math

from bot import runtime_all_in_profitability_authority_v324_patch as v324


class _Strategy:
    def __init__(self, broker_name: str, broker=None):
        self._broker_name = broker_name
        self.broker_client = broker

    def _get_broker_name(self):
        return self._broker_name


class _RuntimeFeeBroker:
    broker_name = "kraken"

    def get_taker_fee(self, symbol):
        return 0.00125


class _AlpacaAssetBroker:
    broker_name = "alpaca"

    def __init__(self, asset):
        self.asset = asset

    def get_asset(self, symbol):
        return dict(self.asset)


def test_current_base_fee_fallbacks_are_conservative_current_tiers():
    assert v324._current_base_fees("kraken", "BTC-USD")[:2] == (0.0040, 0.0080)
    assert v324._current_base_fees("coinbase", "BTC-USD")[:2] == (0.0040, 0.0060)
    assert v324._current_base_fees("okx", "BTC-USDT")[:2] == (0.0020, 0.0035)
    assert v324._current_base_fees("alpaca", "BTC/USD")[:2] == (0.0015, 0.0025)
    assert v324._current_base_fees("alpaca", "AAPL")[:2] == (0.0, 0.0)


def test_derivative_fee_fallback_is_separate_from_spot():
    maker, taker, source = v324._current_base_fees("kraken", "BTC-PERP")
    assert (maker, taker) == (0.0002, 0.0005)
    assert "derivatives" in source


def test_runtime_account_fee_overrides_static_fallback(monkeypatch):
    monkeypatch.setenv("NIJA_ENTRY_SPREAD_RESERVE_PCT", "0.001")
    strategy = _Strategy("kraken", _RuntimeFeeBroker())
    cost, source = v324._all_in_round_trip_cost(strategy, "BTC-USD")
    assert math.isclose(cost, 0.00125 * 2.0 + 0.001, rel_tol=0.0, abs_tol=1e-12)
    assert source == "broker_runtime_taker_fee_v324"


def test_static_fallback_cannot_use_cached_legacy_kraken_fee(monkeypatch):
    monkeypatch.setenv("NIJA_ENTRY_SPREAD_RESERVE_PCT", "0.001")
    strategy = _Strategy("kraken", None)
    cost, source = v324._all_in_round_trip_cost(strategy, "BTC-USD")
    assert math.isclose(cost, 0.0080 * 2.0 + 0.001, rel_tol=0.0, abs_tol=1e-12)
    assert "kraken_spot_tier1" in source


def test_short_carry_uses_explicit_cost_components_before_reserve():
    carry, source = v324._short_carry_pct(
        None,
        "AAPL",
        {
            "borrow_cost_pct": 0.0015,
            "funding_cost_pct": 0.0005,
            "regulatory_cost_pct": 0.0002,
        },
    )
    assert math.isclose(carry, 0.0022, rel_tol=0.0, abs_tol=1e-12)
    assert source == "position_or_signal_metadata"


def test_short_carry_defaults_to_conservative_reserve(monkeypatch):
    monkeypatch.setenv("NIJA_SHORT_CARRY_RESERVE_PCT", "0.0045")
    carry, source = v324._short_carry_pct(None, "AAPL", {})
    assert math.isclose(carry, 0.0045, rel_tol=0.0, abs_tol=1e-12)
    assert source == "conservative_short_carry_reserve"


def test_alpaca_crypto_short_is_blocked_even_if_generic_spot_capability_is_true():
    broker = _AlpacaAssetBroker({"shortable": True, "easy_to_borrow": True})
    ok, reason = v324._short_capability(_Strategy("alpaca", broker), "BTC-USD", {})
    assert not ok
    assert reason == "alpaca:crypto_shorting_unsupported"


def test_alpaca_equity_short_requires_current_borrow_metadata():
    ok, reason = v324._short_capability(_Strategy("alpaca", None), "AAPL", {})
    assert not ok
    assert reason == "alpaca:borrow_metadata_not_proven"


def test_alpaca_equity_not_shortable_is_blocked():
    broker = _AlpacaAssetBroker({"shortable": False, "easy_to_borrow": False})
    ok, reason = v324._short_capability(_Strategy("alpaca", broker), "AAPL", {})
    assert not ok
    assert reason == "alpaca:asset_not_proven_shortable"


def test_alpaca_easy_to_borrow_equity_short_is_allowed():
    broker = _AlpacaAssetBroker({"shortable": True, "easy_to_borrow": True})
    ok, reason = v324._short_capability(_Strategy("alpaca", broker), "AAPL", {})
    assert ok
    assert reason == "alpaca:easy_to_borrow"


def test_alpaca_hard_to_borrow_requires_locate_proof():
    broker = _AlpacaAssetBroker(
        {"shortable": True, "easy_to_borrow": False, "borrow_status": "hard_to_borrow"}
    )
    ok, reason = v324._short_capability(_Strategy("alpaca", broker), "AAPL", {})
    assert not ok
    assert reason == "alpaca:hard_to_borrow_locate_not_proven"

    ok, reason = v324._short_capability(
        _Strategy("alpaca", broker),
        "AAPL",
        {"metadata": {"locate_available": True}},
    )
    assert ok
    assert reason == "alpaca:hard_to_borrow_locate_proven"


def test_fee_capability_patch_changes_economics_not_short_permissions():
    assert v324._patch_exchange_capabilities()

    from bot import exchange_capabilities as caps

    kraken_spot = caps.get_broker_capabilities("kraken", "BTC-USD")
    assert kraken_spot.supports_short is False
    assert math.isclose(kraken_spot.maker_fee, 0.0040, abs_tol=1e-12)
    assert math.isclose(kraken_spot.taker_fee, 0.0080, abs_tol=1e-12)

    kraken_perp = caps.get_broker_capabilities("kraken", "BTC-PERP")
    assert kraken_perp.supports_short is True
    assert math.isclose(kraken_perp.taker_fee, 0.0005, abs_tol=1e-12)
