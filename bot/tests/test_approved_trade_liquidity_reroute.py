from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from bot import approved_trade_liquidity_reroute_patch as patch


@dataclass
class FakeSignal:
    symbol: str = "ARB-USD"
    side: str = "long"
    composite_score: float = 47.3


@dataclass
class FakeSnapshot:
    balance: float = 367.65


def _hold(symbol: str = "ARB-USD") -> dict:
    return {
        "action": "hold",
        "reason": "fallback_illiquid_policy_blocked",
        "filter_stage": "competitive_profitability_policy",
        "detail": "competitive profitability policy blocked illiquid fallback entry: rel_volume=0.11 spread_proxy=0.03%",
        "symbol": symbol,
        "blocked_before_execute_action": True,
        "skip_before_execute_action": True,
        "order_should_not_submit": True,
    }


def _entry(symbol: str = "ARB-USD") -> dict:
    return {
        "action": "enter_long",
        "symbol": symbol,
        "position_size": 29.06,
        "entry_price": 1.0,
        "stop_loss": 0.9975,
        "take_profit": {"tp1": 1.012, "tp2": 1.018, "tp3": 1.026},
        "fallback_entry": True,
        "forced_fallback": True,
        "score": 47.3,
        "expected_win_rate": 0.62,
    }


def _df(price: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame({"close": [price] * 120, "volume": [100.0] * 120})


def test_illiquid_hold_detection():
    assert patch._is_illiquid_hold(_hold()) is True
    assert patch._is_illiquid_hold(_entry()) is False


def test_entry_ready_detection():
    assert patch._entry_ready(_entry()) is True
    bad = _entry()
    bad["take_profit"] = {}
    assert patch._entry_ready(bad) is False


def test_annotate_reroute_clears_hold_flags_and_broker_lock():
    result = patch._annotate_reroute(_entry(), "ARB-USD", 47.3, _hold())

    assert result["action"] == "enter_long"
    assert result["broker_selected"] is None
    assert result["preferred_broker"] is None
    assert result["execution_broker"] is None
    assert result["broker"] == "auto"
    assert result["cross_broker_liquidity_reroute"] is True
    assert result["skip_before_execute_action"] is False
    assert result["blocked_before_execute_action"] is False
    assert result["order_should_not_submit"] is False
    assert result["metadata"]["original_liquidity_block_reason"].startswith("competitive profitability policy")


def test_synthetic_payload_recovery_matches_tpe_sized_min_notional_case(monkeypatch):
    monkeypatch.setenv("NIJA_REROUTE_SYNTHETIC_POSITION_PCT", "0.05")
    sig = FakeSignal(symbol="ALLO-USD", composite_score=37.872)
    payload = patch._synthetic_payload(
        _df(0.50),
        sig,
        FakeSnapshot(balance=367.65),
        action="enter_long",
        symbol="ALLO-USD",
        original_hold=_hold("ALLO-USD"),
        score=37.872,
    )

    assert payload is not None
    assert payload["action"] == "enter_long"
    assert payload["position_size"] >= 10.0
    assert round(payload["position_size"], 2) == 18.38
    assert payload["entry_price"] == 0.50
    assert payload["stop_loss"] < payload["entry_price"] < payload["take_profit"]["tp1"]
    assert payload["reroute_synthetic_payload"] is True
    assert patch._entry_ready(payload) is True


def test_synthetic_payload_rejects_score_below_reroute_floor(monkeypatch):
    sig = FakeSignal(symbol="ACT-USD", composite_score=26.15)
    assert patch._signal_score(sig) == 26.15
    assert patch._signal_score(sig) < 30.0


def test_base_rebuild_failure_recovers_to_reroute_payload(monkeypatch):
    class FakeLoop:
        def _build_forced_fallback_entry_analysis(self, *args, **kwargs):
            return _hold("ALLO-USD")

    class NijaCoreLoop(FakeLoop):
        pass

    module = SimpleNamespace(NijaCoreLoop=NijaCoreLoop, __name__="bot.core_loop")
    assert patch._patch_core_loop_module(module) is True

    def base_raises(*args, **kwargs):
        raise RuntimeError("competitive profitability policy blocked illiquid fallback entry: rel_volume=0.00 spread_proxy=0.09%")

    # Force the wrapper's __wrapped__ base to raise exactly like production logs.
    module.NijaCoreLoop._build_forced_fallback_entry_analysis.__wrapped__ = base_raises
    loop = module.NijaCoreLoop()
    result = loop._build_forced_fallback_entry_analysis(
        df=_df(0.50),
        sig=FakeSignal(symbol="ALLO-USD", composite_score=37.872),
        snapshot=FakeSnapshot(balance=367.65),
        action="enter_long",
        existing_reason="fallback_illiquid_policy_blocked",
    )

    assert result["action"] == "enter_long"
    assert result["cross_broker_liquidity_reroute"] is True
    assert result["broker"] == "auto"
    assert result["skip_before_execute_action"] is False
    assert result["position_size"] >= 10.0
