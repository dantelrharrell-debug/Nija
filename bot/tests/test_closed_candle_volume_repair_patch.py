from __future__ import annotations

import pandas as pd

from bot import closed_candle_volume_repair_patch as patch


def test_repair_zero_open_candle_from_previous_closed_volume():
    df = pd.DataFrame({
        "open": [1.0] * 60,
        "high": [1.01] * 60,
        "low": [0.99] * 60,
        "close": [1.0] * 60,
        "volume": [10.0] * 59 + [0.0],
    })

    out = patch.repair_dataframe(df, symbol="ALGO-USD", broker="kraken")

    assert float(out["volume"].iloc[-1]) == 10.0
    assert float(df["volume"].iloc[-1]) == 0.0


def test_price_action_proxy_repairs_all_zero_volume_when_prices_move(monkeypatch):
    monkeypatch.setenv("NIJA_PRICE_ACTION_VOLUME_PROXY", "true")
    df = pd.DataFrame({
        "open": [1.0 + i * 0.001 for i in range(80)],
        "high": [1.01 + i * 0.001 for i in range(80)],
        "low": [0.99 + i * 0.001 for i in range(80)],
        "close": [1.0 + i * 0.001 for i in range(80)],
        "volume": [0.0] * 80,
    })

    out = patch.repair_dataframe(df, symbol="ARX-USD", broker="kraken")

    assert float(out["volume"].tail(20).mean()) > 0.0
    assert float(out["volume"].iloc[-1]) > 0.0


def test_short_data_is_not_repaired():
    df = pd.DataFrame({"close": [1.0] * 10, "volume": [0.0] * 10})

    out = patch.repair_dataframe(df, symbol="AI16Z-USD", broker="kraken")

    assert out is df
    assert float(out["volume"].sum()) == 0.0
