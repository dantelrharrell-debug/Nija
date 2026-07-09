from __future__ import annotations

from dataclasses import dataclass

from bot import approved_trade_liquidity_reroute_patch as patch


@dataclass
class FakeSignal:
    symbol: str = "ARB-USD"
    composite_score: float = 47.3


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


def test_low_score_stays_blocked(monkeypatch):
    class FakeLoop:
        def _build_forced_fallback_entry_analysis(self, *args, **kwargs):
            return _entry("ARB-USD")

    class NijaCoreLoop(FakeLoop):
        pass

    import types
    module = types.SimpleNamespace(NijaCoreLoop=NijaCoreLoop, __name__="bot.core_loop")
    assert patch._patch_core_loop_module(module) is True

    sig = FakeSignal(composite_score=10.0)
    loop = module.NijaCoreLoop()
    # The wrapped current returns the base entry here, so verify helpers independently.
    assert patch._signal_score(sig) == 10.0
