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
    assert params.volume_gate_multiplier >= 0.45


def test_quiet_healthy_market_lowers_floor_and_enables_volume_fallback(monkeypatch):
    controller = _controller(monkeypatch, "2")
    controller.update_market_conditions(
        MarketConditionSnapshot(
            data_success_rate=0.95,
            candidate_rate=0.0,
            avg_abs_return_pct=0.15,
            avg_adx=4.0,
            avg_volume_pct=5.0,
            market_filter_pass_rate=0.95,
            zero_signal_streak=4,
        )
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is True
    assert params.forced_entry_streak_threshold <= 1
    assert params.hard_bypass_streak_threshold <= 4
    assert params.min_score_absolute <= 6.0
    assert params.min_score_hard_floor <= 5.0
    assert params.interval_normal <= 60
    assert params.volume_gate_multiplier <= 0.30


def test_high_volatility_keeps_bot_selective(monkeypatch):
    controller = _controller(monkeypatch, "2")
    controller.update_market_conditions(
        MarketConditionSnapshot(data_success_rate=0.90, candidate_rate=0.02, avg_abs_return_pct=3.0)
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is False
    assert params.min_score_hard_floor >= 16.0
    assert params.pass_percentile >= 0.45
    assert params.volume_gate_multiplier >= 0.45


def test_healthy_zero_signal_market_continuously_relaxes_with_adx_and_volume(monkeypatch):
    controller = _controller(monkeypatch, "1")
    controller.update_market_conditions(
        MarketConditionSnapshot(
            data_success_rate=0.98,
            candidate_rate=0.0,
            avg_abs_return_pct=0.30,
            zero_signal_streak=2,
            avg_adx=8.0,
            avg_volume_pct=20.0,
            market_filter_pass_rate=0.90,
        )
    )

    params = controller.market_adjusted_params

    assert params.enable_volume_fallback is True
    assert params.min_score_absolute < controller.params.min_score_absolute
    assert params.min_score_hard_floor < controller.params.min_score_hard_floor
    assert params.hard_bypass_streak_threshold <= 8
    assert params.volume_gate_multiplier <= 0.35


def test_active_candidate_market_tightens_selectivity(monkeypatch):
    controller = _controller(monkeypatch, "1")
    controller.update_market_conditions(
        MarketConditionSnapshot(
            data_success_rate=0.98,
            candidate_rate=0.20,
            avg_abs_return_pct=0.60,
            zero_signal_streak=0,
            avg_adx=18.0,
            avg_volume_pct=60.0,
            market_filter_pass_rate=0.95,
        )
    )

    params = controller.market_adjusted_params

    assert params.min_score_absolute >= 8.0
    assert params.min_score_hard_floor >= 6.0
    assert params.pass_percentile >= 0.35
    assert params.volume_gate_multiplier >= 0.35


def test_ai_engine_uses_market_adjusted_floor_and_volume_gate(monkeypatch):
    import pandas as pd
    from types import SimpleNamespace
    from bot.nija_ai_engine import NijaAIEngine

    controller = _controller(monkeypatch, "2")
    controller.update_market_conditions(
        MarketConditionSnapshot(
            data_success_rate=0.95,
            candidate_rate=0.0,
            avg_abs_return_pct=0.15,
            avg_adx=4.0,
            avg_volume_pct=5.0,
            market_filter_pass_rate=0.95,
            zero_signal_streak=5,
        )
    )
    monkeypatch.setattr(pmc, "_controller", controller)

    captured = {}

    class Gate:
        def check(self, **kwargs):
            captured["volume_gate_multiplier"] = kwargs.get("volume_gate_multiplier")
            return SimpleNamespace(
                passed=True,
                reason="ok",
                gate_max=10.0,
                gate_score=10.0,
                gates={},
            )

    engine = NijaAIEngine()
    assert engine._score_floor <= 6.0
    engine._enhanced_scorer = SimpleNamespace(
        calculate_entry_score=lambda df, indicators, side: (50.0, {})
    )
    engine._entry_optimizer = SimpleNamespace(
        analyze_entry=lambda df, indicators, side: SimpleNamespace(score_delta=0.0, reason="none")
    )
    engine._ai_entry_gate = Gate()

    df = pd.DataFrame({"close": [100, 101, 102], "volume": [10, 12, 11]})
    engine._compute_composite(df, {}, "buy", None, "kraken", "spot")

    assert captured["volume_gate_multiplier"] <= 0.30
