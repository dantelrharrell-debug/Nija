from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bot.regime_performance_calibrator import RegimePerformanceCalibrator, normalize_regime


def _record(
    calibrator: RegimePerformanceCalibrator,
    count: int,
    net_return: float,
    regime: str = "volatile",
    strategy: str = "APEX_V71",
) -> dict[str, object] | None:
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


class RegimePerformanceCalibratorTests(unittest.TestCase):
    """Exercise persistence, sample bounds, and fail-closed live gating."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_normalizes_runtime_regime_aliases(self) -> None:
        self.assertEqual(normalize_regime("HIGH_VOLATILITY"), "volatile")
        self.assertEqual(normalize_regime("strong_trend"), "trending")
        self.assertEqual(normalize_regime(None), "default")

    def test_cold_start_never_changes_live_parameters(self) -> None:
        calibrator = RegimePerformanceCalibrator(str(self.temp_path / "calibration.json"))
        report = _record(calibrator, 19, 0.01)
        self.assertIsNotNone(report)
        assert report is not None

        self.assertFalse(report["eligible_for_review"])
        self.assertEqual(report["position_size_multiplier"], 1.0)
        self.assertEqual(report["confidence_threshold_delta"], 0.0)
        self.assertTrue(report["shadow_only"])

        losing = RegimePerformanceCalibrator(str(self.temp_path / "losing.json"))
        losing_report = _record(losing, 19, -0.01)
        self.assertIsNotNone(losing_report)
        assert losing_report is not None
        self.assertFalse(losing_report["freeze_recommended"])
        self.assertEqual(losing_report["position_size_multiplier"], 1.0)
        self.assertEqual(losing_report["confidence_threshold_delta"], 0.0)

    def test_adjustments_are_sample_bounded_and_persisted(self) -> None:
        state_path = self.temp_path / "calibration.json"
        calibrator = RegimePerformanceCalibrator(str(state_path))
        report = _record(calibrator, 25, 0.01)
        self.assertIsNotNone(report)
        assert report is not None

        self.assertTrue(report["eligible_for_review"])
        self.assertGreaterEqual(report["position_size_multiplier"], 1.0)
        self.assertLessEqual(report["position_size_multiplier"], 1.05)
        self.assertGreaterEqual(report["confidence_threshold_delta"], -0.05)
        self.assertLessEqual(report["confidence_threshold_delta"], 0.0)

        restored = RegimePerformanceCalibrator(str(state_path))
        self.assertEqual(restored.get_recommendation("volatile", "APEX_V71")["sample_size"], 25)

    def test_drawdown_recommends_freeze_without_applying_it(self) -> None:
        calibrator = RegimePerformanceCalibrator(str(self.temp_path / "calibration.json"))
        report = _record(calibrator, 20, -0.01, regime="ranging")
        self.assertIsNotNone(report)
        assert report is not None

        self.assertTrue(report["freeze_recommended"])
        self.assertLessEqual(report["position_size_multiplier"], 0.75)
        self.assertGreaterEqual(report["confidence_threshold_delta"], 0.10)
        self.assertTrue(report["shadow_only"])

    def test_buckets_are_isolated_by_regime_and_strategy(self) -> None:
        calibrator = RegimePerformanceCalibrator(str(self.temp_path / "calibration.json"))
        _record(calibrator, 3, 0.01, regime="volatile", strategy="momentum")
        _record(calibrator, 2, -0.01, regime="ranging", strategy="mean_reversion")

        self.assertEqual(calibrator.get_recommendation("volatile", "momentum")["sample_size"], 3)
        self.assertEqual(calibrator.get_recommendation("ranging", "mean_reversion")["sample_size"], 2)
        self.assertEqual(len(calibrator.report_all()), 2)

    def test_live_controls_require_both_operator_gates(self) -> None:
        calibrator = RegimePerformanceCalibrator(str(self.temp_path / "calibration.json"))
        _record(calibrator, 20, -0.01)

        with patch.dict(
            os.environ,
            {
                "NIJA_REGIME_CALIBRATION_LIVE": "true",
                "NIJA_REGIME_CALIBRATION_APPROVED": "false",
            },
            clear=False,
        ):
            self.assertFalse(calibrator.get_live_controls("volatile")["active"])

        with patch.dict(
            os.environ,
            {
                "NIJA_REGIME_CALIBRATION_LIVE": "true",
                "NIJA_REGIME_CALIBRATION_APPROVED": "true",
            },
            clear=False,
        ):
            controls = calibrator.get_live_controls("volatile")
            self.assertTrue(controls["active"])
            self.assertLessEqual(controls["position_size_multiplier"], 0.75)
            self.assertGreaterEqual(controls["confidence_threshold_delta"], 0.10)

    def test_live_controls_never_increase_risk(self) -> None:
        calibrator = RegimePerformanceCalibrator(str(self.temp_path / "calibration.json"))
        _record(calibrator, 25, 0.01)
        with patch.dict(
            os.environ,
            {
                "NIJA_REGIME_CALIBRATION_LIVE": "true",
                "NIJA_REGIME_CALIBRATION_APPROVED": "true",
            },
            clear=False,
        ):
            controls = calibrator.get_live_controls("volatile")

        self.assertTrue(controls["active"])
        self.assertEqual(controls["position_size_multiplier"], 1.0)
        self.assertEqual(controls["confidence_threshold_delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
