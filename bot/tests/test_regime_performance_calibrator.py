from bot.regime_performance_calibrator import RegimePerformanceCalibrator, normalize_regime


def _record(calibrator, count, net_return, regime="volatile", strategy="APEX_V71"):
    report = None
    for _ in range(count):
        report = calibrator.record_closed_trade(
            symbol="BTC-USD",
            regime=regime,
            strategy=strategy,
            broker="kraken",
            side="long",
            net_return=net_return,
            gross_return=net_return + 0.002,
            execution_cost_return=0.002,
            mfe_return=max(net_return, 0.01),
            mae_return=min(net_return, -0.002),
            exit_reason="test",
        )
    return report


def test_normalizes_runtime_regime_aliases():
    assert normalize_regime("HIGH_VOLATILITY") == "volatile"
    assert normalize_regime("strong_trend") == "trending"
    assert normalize_regime(None) == "default"


def test_cold_start_never_changes_live_parameters(tmp_path):
    calibrator = RegimePerformanceCalibrator(str(tmp_path / "calibration.json"))
    report = _record(calibrator, 19, 0.01)

    assert report["eligible_for_review"] is False
    assert report["position_size_multiplier"] == 1.0
    assert report["confidence_threshold_delta"] == 0.0
    assert report["shadow_only"] is True

    losing = RegimePerformanceCalibrator(str(tmp_path / "losing.json"))
    losing_report = _record(losing, 19, -0.01)
    assert losing_report["freeze_recommended"] is False
    assert losing_report["position_size_multiplier"] == 1.0
    assert losing_report["confidence_threshold_delta"] == 0.0


def test_adjustments_are_sample_bounded_and_persisted(tmp_path):
    state_path = tmp_path / "calibration.json"
    calibrator = RegimePerformanceCalibrator(str(state_path))
    report = _record(calibrator, 25, 0.01)

    assert report["eligible_for_review"] is True
    assert 1.0 <= report["position_size_multiplier"] <= 1.05
    assert -0.05 <= report["confidence_threshold_delta"] <= 0.0

    restored = RegimePerformanceCalibrator(str(state_path))
    assert restored.get_recommendation("volatile", "APEX_V71")["sample_size"] == 25


def test_drawdown_recommends_freeze_without_applying_it(tmp_path):
    calibrator = RegimePerformanceCalibrator(str(tmp_path / "calibration.json"))
    report = _record(calibrator, 20, -0.01, regime="ranging")

    assert report["freeze_recommended"] is True
    assert report["position_size_multiplier"] <= 0.75
    assert report["confidence_threshold_delta"] >= 0.10
    assert report["shadow_only"] is True


def test_buckets_are_isolated_by_regime_and_strategy(tmp_path):
    calibrator = RegimePerformanceCalibrator(str(tmp_path / "calibration.json"))
    _record(calibrator, 3, 0.01, regime="volatile", strategy="momentum")
    _record(calibrator, 2, -0.01, regime="ranging", strategy="mean_reversion")

    assert calibrator.get_recommendation("volatile", "momentum")["sample_size"] == 3
    assert calibrator.get_recommendation("ranging", "mean_reversion")["sample_size"] == 2
    assert len(calibrator.report_all()) == 2


def test_live_controls_require_both_operator_gates(tmp_path, monkeypatch):
    calibrator = RegimePerformanceCalibrator(str(tmp_path / "calibration.json"))
    _record(calibrator, 20, -0.01)

    monkeypatch.setenv("NIJA_REGIME_CALIBRATION_LIVE", "true")
    assert calibrator.get_live_controls("volatile")["active"] is False

    monkeypatch.setenv("NIJA_REGIME_CALIBRATION_APPROVED", "true")
    controls = calibrator.get_live_controls("volatile")
    assert controls["active"] is True
    assert controls["position_size_multiplier"] <= 0.75
    assert controls["confidence_threshold_delta"] >= 0.10


def test_live_controls_never_increase_risk(tmp_path, monkeypatch):
    calibrator = RegimePerformanceCalibrator(str(tmp_path / "calibration.json"))
    _record(calibrator, 25, 0.01)
    monkeypatch.setenv("NIJA_REGIME_CALIBRATION_LIVE", "true")
    monkeypatch.setenv("NIJA_REGIME_CALIBRATION_APPROVED", "true")

    controls = calibrator.get_live_controls("volatile")
    assert controls["active"] is True
    assert controls["position_size_multiplier"] == 1.0
    assert controls["confidence_threshold_delta"] == 0.0
