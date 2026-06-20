import pandas as pd

from bot import adaptive_entry_thresholds as aet
from bot.adaptive_entry_thresholds import (
    ADX_CEILING,
    ADX_FLOOR,
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    REL_VOLUME_CEILING,
    REL_VOLUME_FLOOR,
    AdaptiveEntryThresholdEngine,
)
from bot.ai_entry_gate import AIEntryGate


def _market_df(rows: int = 140, volume_start: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0 + i * 0.02 for i in range(rows)],
            "high": [101.0 + i * 0.02 for i in range(rows)],
            "low": [99.0 + i * 0.02 for i in range(rows)],
            "close": [100.0 + i * 0.02 for i in range(rows)],
            "volume": [volume_start + i for i in range(rows)],
        }
    )


def test_thresholds_stay_within_safety_floors_and_ceilings() -> None:
    engine = AdaptiveEntryThresholdEngine()
    df = _market_df()
    indicators = {
        "adx": pd.Series([0.5 + (i * 0.1) for i in range(len(df))]),
        "atr": pd.Series([0.8] * len(df)),
    }

    thresholds = engine.resolve(
        df=df,
        indicators=indicators,
        regime="ranging",
        zero_signal_streak=20,
    )

    assert CONFIDENCE_FLOOR <= thresholds.confidence <= CONFIDENCE_CEILING
    assert ADX_FLOOR <= thresholds.adx <= ADX_CEILING
    assert REL_VOLUME_FLOOR <= thresholds.relative_volume <= REL_VOLUME_CEILING


def test_performance_feedback_reoptimizes_after_configured_trade_window(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_ADAPTIVE_REOPT_TRADE_WINDOW", "100")
    engine = AdaptiveEntryThresholdEngine()
    df = _market_df()
    indicators = {
        "adx": pd.Series([12.0] * len(df)),
        "atr": pd.Series([0.8] * len(df)),
    }

    before = engine.resolve(df=df, indicators=indicators, regime="weak_trend").confidence
    for _ in range(100):
        engine.record_trade_outcome(-1.0)
    after = engine.resolve(df=df, indicators=indicators, regime="weak_trend").confidence

    assert after > before
    assert after <= CONFIDENCE_CEILING


def test_ai_entry_gate_uses_adaptive_confidence_adx_and_volume_thresholds(monkeypatch) -> None:
    class FixedThresholds:
        confidence = 0.12
        adx = 1.5
        relative_volume = 0.20

    monkeypatch.setattr(aet, "get_adaptive_entry_thresholds", lambda **kwargs: FixedThresholds())
    import bot.ai_entry_gate as gate_mod

    monkeypatch.setattr(gate_mod, "get_adaptive_entry_thresholds", lambda **kwargs: FixedThresholds())

    df = _market_df()
    df.loc[df.index[-1], "volume"] = df["volume"].tail(20).mean() * 0.25
    indicators = {
        "adx": pd.Series([2.0] * len(df)),
        "atr": pd.Series([0.8] * len(df)),
    }

    result = AIEntryGate().check(
        df=df,
        indicators=indicators,
        side="long",
        enhanced_score=13.0,
        regime="weak_trend",
        broker="kraken",
        entry_type="swing",
    )

    assert result.gates["gate1_score"].threshold == 12.0
    assert result.gates["gate2_volume"].threshold == 0.20
    assert result.gates["gate3_volatility"].detail.endswith("ADX 2.00 ≥ adaptive 1.50")
