from scripts.backtest_regime_calibration import evaluate_walk_forward


def _trade(pnl, regime="volatile"):
    return {
        "symbol": "BTC-USD",
        "regime_family": regime,
        "strategy": "APEX_V71",
        "side": "long",
        "pnl": pnl,
    }


def test_walk_forward_uses_only_prior_outcomes_and_reduces_drawdown():
    trades = [_trade(-0.01) for _ in range(25)]
    report = evaluate_walk_forward(trades)

    assert report["calibration_active_trades"] == 5
    assert report["calibrated_max_drawdown"] < report["baseline_max_drawdown"]
    assert report["calibrated_total_return"] > report["baseline_total_return"]
    assert report["passes_non_degradation"] is True


def test_walk_forward_refuses_to_pass_without_eligible_history():
    report = evaluate_walk_forward([_trade(0.01) for _ in range(19)])

    assert report["calibration_active_trades"] == 0
    assert report["passes_non_degradation"] is False
