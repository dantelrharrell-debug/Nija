from __future__ import annotations

import pandas as pd
import pytest

from bot.control.strategy_detectors import BaseDetector, DetectorContext
from bot.shadow_strategy_lab import ShadowStrategyLab


class AlwaysLongDetector(BaseDetector):
    strategy_name = "TEST_LONG"

    def detect(self, df: pd.DataFrame, context: DetectorContext):
        close = float(df["close"].iloc[-1])
        return self._signal(
            strategy=self.strategy_name,
            context=context,
            direction="long",
            confidence=0.70,
            raw_score=0.70,
            invalidation_level=close * 0.98,
            suggested_stop=close * 0.98,
            targets=[close * 1.02],
            support=["test_signal"],
            conflict=[],
        )


class AlwaysShortDetector(BaseDetector):
    strategy_name = "TEST_SHORT"

    def detect(self, df: pd.DataFrame, context: DetectorContext):
        close = float(df["close"].iloc[-1])
        return self._signal(
            strategy=self.strategy_name,
            context=context,
            direction="short",
            confidence=0.65,
            raw_score=0.65,
            invalidation_level=close * 1.02,
            suggested_stop=close * 1.02,
            targets=[close * 0.98],
            support=["test_signal"],
            conflict=[],
        )


def _frame(closes):
    rows = []
    for value in closes:
        rows.append(
            {
                "open": value - 0.2,
                "high": value + 0.5,
                "low": value - 0.5,
                "close": value,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def _lab(tmp_path, *, horizon=2):
    lab = ShadowStrategyLab(
        state_path=str(tmp_path / "state.json"),
        calibration_path=str(tmp_path / "calibration.json"),
        horizon_bars=horizon,
        enabled=True,
    )
    lab._detectors = [AlwaysLongDetector()]
    return lab


def test_shadow_lab_settles_forward_return_net_of_cost(tmp_path):
    df = _frame([100, 101, 102, 103, 104, 105, 106])
    lab = _lab(tmp_path, horizon=2)

    first = lab.observe(
        df.iloc[:4],
        symbol="BTC-USD",
        broker="kraken",
        market_regime="strong_trend",
        round_trip_cost_return=0.001,
    )
    assert first[0]["strategy"] == "TEST_LONG"
    assert first[0]["shadow_only"] is True

    lab.observe(
        df.iloc[:6],
        symbol="BTC-USD",
        broker="kraken",
        market_regime="strong_trend",
        round_trip_cost_return=0.001,
    )

    report = lab.calibrator.get_recommendation("trending", "TEST_LONG")
    assert report["sample_size"] == 1
    expected_gross = (105.0 - 103.0) / 103.0
    assert report["expectancy"] == pytest.approx(expected_gross - 0.001)


def test_shadow_lab_deduplicates_same_strategy_same_bar(tmp_path):
    df = _frame([100, 101, 102, 103])
    lab = _lab(tmp_path)

    lab.observe(
        df,
        symbol="ETH-USD",
        broker="coinbase",
        market_regime="ranging",
    )
    pending_after_first = len(lab._pending)

    lab.observe(
        df,
        symbol="ETH-USD",
        broker="coinbase",
        market_regime="ranging",
    )
    assert len(lab._pending) == pending_after_first


def test_shadow_lab_can_compare_multiple_strategy_directions(tmp_path):
    df = _frame([100, 101, 102, 103])
    lab = _lab(tmp_path)
    lab._detectors = [AlwaysLongDetector(), AlwaysShortDetector()]

    rows = lab.observe(
        df,
        symbol="SOL-USD",
        broker="kraken",
        market_regime="volatile",
    )

    assert {row["strategy"] for row in rows} == {"TEST_LONG", "TEST_SHORT"}
    assert all(row["shadow_only"] for row in rows)
    assert lab.readiness()["live_switching_enabled"] is False


def test_shadow_lab_state_survives_restart(tmp_path):
    df = _frame([100, 101, 102, 103])
    state = tmp_path / "state.json"
    calibration = tmp_path / "calibration.json"

    lab = ShadowStrategyLab(
        state_path=str(state),
        calibration_path=str(calibration),
        horizon_bars=2,
        enabled=True,
    )
    lab._detectors = [AlwaysLongDetector()]
    lab.observe(
        df,
        symbol="BTC-USD",
        broker="kraken",
        market_regime="trending",
    )
    assert len(lab._pending) == 1

    restored = ShadowStrategyLab(
        state_path=str(state),
        calibration_path=str(calibration),
        horizon_bars=2,
        enabled=True,
    )
    assert len(restored._pending) == 1
