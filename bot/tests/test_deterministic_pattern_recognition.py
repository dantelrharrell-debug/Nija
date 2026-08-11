import numpy as np
import pandas as pd

from bot.deterministic_pattern_recognition import DeterministicPatternRecognizer
from bot.enhanced_entry_scoring import EnhancedEntryScorer


def _frame_from_close(close, volume=1000.0):
    close = np.asarray(close, dtype=float)
    open_ = close.copy()
    high = close + 0.4
    low = close - 0.4
    vol = np.full(len(close), float(volume))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol}
    )


def _flat_indicators(n: int):
    return {
        "atr": pd.Series([1.0] * n),
        "rsi": pd.Series([50.0] * n),
        "ema_21": pd.Series([100.0] * n),
        "vwap": pd.Series([100.0] * n),
        "adx": pd.Series([30.0] * n),
        "histogram": pd.Series([0.1] * n),
    }


def test_handles_missing_or_insufficient_data_safely():
    recognizer = DeterministicPatternRecognizer()
    df = pd.DataFrame({"open": [1], "close": [1]})
    result = recognizer.analyze(df, {}, "long", "trending")
    assert result["patterns"] == []
    assert result["score_adjustment"] == 0.0
    assert result["rejection_reason"] == "invalid_or_insufficient_data"


def test_uses_completed_candles_only_and_ignores_latest_inflight_bar():
    recognizer = DeterministicPatternRecognizer()
    base = _frame_from_close(list(np.linspace(100, 104, 48)))
    altered = base.copy()
    altered.loc[len(altered) - 1, ["open", "high", "low", "close", "volume"]] = [
        300.0,
        350.0,
        250.0,
        340.0,
        99999.0,
    ]
    assert recognizer.analyze(base, {}, "long", "trending") == recognizer.analyze(
        altered, {}, "long", "trending"
    )


def test_detects_reversal_patterns_double_and_head_shoulders():
    recognizer = DeterministicPatternRecognizer({"min_pattern_confidence": 0.5})

    close_dt = [
        100, 101, 102, 103, 104, 106, 108, 110, 108, 106, 104, 102,
        104, 106, 108, 110, 108, 106, 104, 102, 100, 98, 96, 95, 94,
        93, 92, 91, 90, 89, 88, 87, 86, 85, 84, 83, 82, 81, 80, 79,
    ]
    dt = recognizer._detect_double_top_bottom(_frame_from_close(close_dt), {})
    assert any(p.pattern_name == "double_top" and p.confirmation_state == "confirmed" for p in dt)

    close_hs = [
        100, 101, 103, 105, 108, 110, 108, 105, 103, 106, 110, 115,
        110, 106, 103, 106, 110, 108, 105, 102, 99, 97, 95, 93, 92,
        91, 90, 89, 88, 87, 86, 85, 84, 83, 82, 81, 80, 79, 78, 77,
    ]
    hs = recognizer._detect_head_shoulders(_frame_from_close(close_hs), {})
    assert any(
        p.pattern_name == "head_and_shoulders" and p.confirmation_state == "confirmed"
        for p in hs
    )


def test_detects_inverse_reversal_patterns():
    recognizer = DeterministicPatternRecognizer({"min_pattern_confidence": 0.5})

    close_db = [
        120, 119, 118, 117, 116, 114, 112, 110, 112, 114, 116, 118,
        116, 114, 112, 110, 112, 114, 116, 118, 120, 122, 124, 125,
        126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137,
        138, 139, 140, 141,
    ]
    db = recognizer._detect_double_top_bottom(_frame_from_close(close_db), {})
    assert any(p.pattern_name == "double_bottom" and p.confirmation_state == "confirmed" for p in db)

    close_ihs = [
        140, 138, 136, 134, 132, 130, 128, 126, 128, 130, 132, 129,
        126, 122, 118, 122, 126, 129, 132, 130, 128, 130, 132, 134,
        136, 138, 140, 142, 144, 145, 146, 147, 148, 149, 150, 151,
        152, 153, 154, 155,
    ]
    ihs = recognizer._detect_head_shoulders(_frame_from_close(close_ihs), {})
    assert any(
        p.pattern_name == "inverse_head_and_shoulders" and p.confirmation_state == "confirmed"
        for p in ihs
    )


def test_detects_triangles_channels_breakouts_divergence_and_volume():
    recognizer = DeterministicPatternRecognizer({"min_pattern_confidence": 0.5})
    n = 50
    x = np.arange(n)

    # Ascending triangle
    high = np.full(n, 110.0)
    low = 95 + x * 0.2
    close = (high + low) / 2.0
    close[-2] = 111.2
    close[-1] = 111.3
    tri_df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": np.full(n, 1200.0)})
    triangles = recognizer._detect_triangle(recognizer._prepare_frame(tri_df), {})
    assert any(p.pattern_name == "ascending_triangle" for p in triangles)

    # Rising channel
    ch_df = _frame_from_close(np.linspace(100, 120, n))
    channels = recognizer._detect_channel(recognizer._prepare_frame(ch_df), {})
    assert any(p.pattern_name == "rising_channel" for p in channels)

    # Breakout + volume confirmation (completed candle is -2; -1 gets dropped)
    bo_close = list(np.linspace(100, 103, n))
    bo_close[-3] = 103.2
    bo_close[-2] = 106.0
    bo_close[-1] = 105.5
    bo_df = _frame_from_close(bo_close)
    bo_df.loc[len(bo_df) - 2, "volume"] = 4000.0
    prepared = recognizer._prepare_frame(bo_df)
    breakouts = recognizer._detect_breakout_breakdown(prepared, {})
    assert any(p.pattern_name == "breakout" and p.confirmation_state == "confirmed" for p in breakouts)
    vol = recognizer._detect_volume_confirmation(prepared, {})
    assert any(p.pattern_name == "volume_confirmation" for p in vol)

    # Momentum divergence
    div_close = [
        100, 99, 98, 97, 96, 95, 96, 97, 96, 95, 94, 93, 92, 93, 94,
        95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107,
        108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120,
    ]
    div_df = _frame_from_close(div_close)
    prep = recognizer._prepare_frame(div_df)
    osc = pd.Series(np.linspace(20, 60, len(prep)))
    divergences = recognizer._detect_momentum_divergence(prep, {"rsi": osc})
    assert any(p.pattern_name == "momentum_divergence" for p in divergences)


def test_regime_weighting_and_exit_plan_are_produced_for_confirmed_patterns():
    recognizer = DeterministicPatternRecognizer({"min_pattern_confidence": 0.5})
    close = list(np.linspace(100, 103, 50))
    close[-3] = 103.2
    close[-2] = 106.0
    close[-1] = 105.5
    df = _frame_from_close(close)
    df.loc[len(df) - 2, "volume"] = 4000.0
    indicators = _flat_indicators(len(df))

    trending = recognizer.analyze(df, indicators, "long", "trending")
    ranging = recognizer.analyze(df, indicators, "long", "ranging")

    assert trending["score_adjustment"] >= ranging["score_adjustment"]
    assert trending["exit_plan"] is not None
    assert "invalidation_price" in trending["exit_plan"]
    assert len(trending["exit_plan"]["targets"]) == 3


def test_unconfirmed_patterns_do_not_bypass_score_limits_or_force_bonus():
    n = 55
    close = np.linspace(100, 101, n)
    df = _frame_from_close(close, volume=900.0)
    indicators = _flat_indicators(n)

    scorer = EnhancedEntryScorer(
        {
            "min_pattern_confidence": 0.95,
            "pattern_lookback": 100,
        }
    )
    score, breakdown = scorer.calculate_entry_score(df, indicators, side="long", regime="trending")

    assert 0.0 <= score <= 100.0
    assert breakdown["price_action"] <= scorer.weights["price_action"]
    assert breakdown["pattern_score_adjustment"] <= 4.0
