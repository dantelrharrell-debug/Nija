from __future__ import annotations

from bot import expectancy_win_rate_calibration_patch as patch


def test_flat_fifty_percent_is_calibrated_from_score():
    payload = {
        "symbol": "AVAX-USD",
        "expected_win_rate": 0.50,
        "composite_score": 40.032,
        "confidence": 0.50,
        "regime": "trending",
        "spread_pct": 0.001,
        "slippage_pct": 0.001,
        "take_profit": {"tp1": 6.798616},
    }

    out = patch.calibrate_payload(payload)

    assert out["expected_win_rate_calibrated"] is True
    assert out["expected_win_rate"] > 0.5318
    assert out["expected_win_rate_source"].startswith("score_calibrated")
    assert out["take_profit"]["expected_win_rate"] == out["expected_win_rate"]


def test_real_model_probability_is_preserved():
    payload = {
        "symbol": "AVAX-USD",
        "expected_win_rate": 0.62,
        "composite_score": 40.032,
        "confidence": 0.50,
    }

    out = patch.calibrate_payload(payload)

    assert out["expected_win_rate"] == 0.62
    assert "expected_win_rate_calibrated" not in out


def test_low_score_flat_probability_stays_uncalibrated():
    payload = {
        "symbol": "WEAK-USD",
        "expected_win_rate": 0.50,
        "composite_score": 20.0,
        "confidence": 0.50,
    }

    out = patch.calibrate_payload(payload)

    assert out["expected_win_rate"] == 0.50
    assert "expected_win_rate_calibrated" not in out


def test_normalized_score_can_calibrate():
    payload = {
        "symbol": "ARB-USD",
        "expected_win_rate": 0.50,
        "score": 0.473,
        "confidence": 0.50,
        "regime": "trending",
    }

    out = patch.calibrate_payload(payload)

    assert out["expected_win_rate"] > 0.54
    assert out["expected_win_rate_calibrated"] is True
