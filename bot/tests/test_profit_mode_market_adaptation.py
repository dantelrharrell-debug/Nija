from bot import profit_mode_controller as pmc
from bot.profit_mode_controller import MarketConditionSnapshot, ProfitModeController


def _controller(monkeypatch, level="2"):
    monkeypatch.setenv("NIJA_PROFIT_MODE", level)
    monkeypatch.setattr(pmc, "_controller", None)
    return ProfitModeController()


def test_degraded_market_data_disables_fallback_and_slows_scans(monkeypatch):
    controller = _controller(monkeypatch, "3")
    controller.update_market_conditions(
        MarketConditionSnapshot(data_success_rate=0.20, candidate_rate=0.0, avg_abs_return_pct=0.1)
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is False
    assert params.interval_normal >= 180
    assert params.min_score_hard_floor >= 18.0


def test_quiet_healthy_market_lowers_floor_and_enables_volume_fallback(monkeypatch):
    controller = _controller(monkeypatch, "2")
    controller.update_market_conditions(
        MarketConditionSnapshot(
            data_success_rate=0.95,
            candidate_rate=0.0,
            avg_abs_return_pct=0.15,
            zero_signal_streak=4,
        )
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is True
    assert params.forced_entry_streak_threshold <= 2
    assert params.min_score_hard_floor < pmc._LEVELS[2].min_score_hard_floor
    assert params.interval_normal <= 90


def test_high_volatility_keeps_bot_selective(monkeypatch):
    controller = _controller(monkeypatch, "2")
    controller.update_market_conditions(
        MarketConditionSnapshot(data_success_rate=0.90, candidate_rate=0.02, avg_abs_return_pct=3.0)
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is False
    assert params.min_score_hard_floor >= 16.0
    assert params.pass_percentile >= 0.45
