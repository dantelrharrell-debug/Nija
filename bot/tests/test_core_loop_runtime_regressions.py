import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bot.nija_core_loop import _cached_broker_balances_for_log


class _BrokerType:
    value = "coinbase"


def test_cached_broker_balances_for_log_does_not_call_exchange_balance_api() -> None:
    broker = SimpleNamespace(
        connected=True,
        _last_known_balance=42.5,
        get_account_balance=Mock(side_effect=AssertionError("live API call not allowed")),
    )
    manager = SimpleNamespace(brokers={_BrokerType(): broker})

    snapshot = _cached_broker_balances_for_log(manager)

    assert snapshot == {
        "coinbase": {"balance": 42.5, "connected": True, "source": "cached"}
    }
    broker.get_account_balance.assert_not_called()


def test_kraken_user_configs_are_independent_not_copy_trading() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    retail_users = json.loads((repo_root / "config/users/retail_kraken.json").read_text())
    individual_users = [
        json.loads((repo_root / "config/users/daivon_frazier.json").read_text()),
        json.loads((repo_root / "config/users/tania_gilbert.json").read_text()),
    ]

    for user in [*retail_users, *individual_users]:
        assert user["enabled"] is True
        assert user["active_trading"] is True
        assert user["independent_trading"] is True
        assert user["copy_from_platform"] is False


def test_force_next_cycle_injects_volume_fallback_before_empty_return(monkeypatch):
    import pandas as pd
    from bot import nija_core_loop as ncl
    from bot.nija_core_loop import CycleSnapshot, NijaCoreLoop

    df = pd.DataFrame(
        {
            "open": [100.0] * 120,
            "high": [101.0] * 120,
            "low": [99.0] * 120,
            "close": [100.0] * 120,
            "volume": [1000.0] * 120,
        }
    )

    class Broker:
        connected = True

        def get_candles(self, symbol, limit=200):
            return df

    class Apex:
        current_regime = "normal"
        broker_client = Broker()

        def calculate_indicators(self, frame):
            return {
                "adx": pd.Series([5.0] * len(frame)),
                "score_breakdown": {},
            }

        def check_market_filter(self, frame, indicators):
            return True, "uptrend", "ok"

        def _get_entry_type_for_regime(self, regime):
            return "swing"

        def _get_broker_name(self):
            return "coinbase"

        def analyze_market(self, frame, symbol, balance):
            return {"action": "hold", "position_size": 10.0, "reason": "no natural setup"}

        def execute_action(self, analysis, symbol):
            required = {"position_size", "entry_price", "stop_loss", "take_profit"}
            missing = required - set(analysis)
            if missing:
                raise AssertionError(f"fallback execution payload missing: {sorted(missing)}")
            self.last_execution = (analysis, symbol)
            return True

    class NoSignalAI:
        def evaluate_symbol(self, **kwargs):
            return None

        def _compute_composite(self, *args, **kwargs):
            return 0.0, {"composite_score": 0.0, "score_breakdown": {}}

        def rank_and_select(self, candidates, slots, regime):
            return candidates[:slots]

    monkeypatch.setattr(ncl, "_TPE_AVAILABLE", False)
    monkeypatch.setattr(ncl, "_PMC_AVAILABLE", False)
    monkeypatch.setattr(ncl, "FORCE_NEXT_CYCLE", True)

    apex = Apex()
    loop = NijaCoreLoop(apex, max_positions=1)
    loop._ai_engine = NoSignalAI()

    entries, blocked, scored, gates = loop._phase3_scan_and_enter(
        broker=apex.broker_client,
        snapshot=CycleSnapshot(balance=100.0, current_regime="normal", daily_pnl_usd=0.0, open_positions=0),
        symbols=["BTC-USD"],
        available_slots=1,
        zero_signal_streak=0,
    )

    assert entries == 1
    assert blocked == 0
    assert scored == 1
    assert ncl.FORCE_NEXT_CYCLE is False
    analysis, symbol = apex.last_execution
    assert symbol == "BTC-USD"
    assert analysis["action"] == "enter_long"
    assert analysis["position_size"] > 0
    assert analysis["entry_price"] == 100.0
    assert analysis["stop_loss"] < analysis["entry_price"]
    assert analysis["take_profit"][0] > analysis["entry_price"]
    assert (analysis["take_profit"][0] - analysis["entry_price"]) / analysis["entry_price"] >= 0.008
    assert "fallback_entry" in analysis["reason"]


def test_always_trade_mode_cold_start_has_no_trade_history(monkeypatch, tmp_path):
    from bot import always_trade_mode as atm_mod

    monkeypatch.setattr(atm_mod, "_STATE_FILE", str(tmp_path / "atm.json"))
    monkeypatch.setattr(atm_mod, "ATM_IDLE_TIMEOUT_S", 120.0)
    monkeypatch.setattr(atm_mod, "ATM_ENABLED", True)

    atm = atm_mod.AlwaysTradeMode()
    decision = atm.run_pre_cycle_check(user_mode=False, open_positions=0, balance=100.0)

    assert decision.force_entry is True
    assert decision.idle_seconds >= 120.0


def test_fetch_df_accepts_ccxt_style_ohlcv_adapter() -> None:
    import pandas as pd
    from bot.nija_core_loop import NijaCoreLoop

    rows = [
        [i, 100.0, 101.0, 99.0, 100.0 + (i * 0.01), 1000.0]
        for i in range(120)
    ]

    class Broker:
        connected = True

        def fetch_ohlcv(self, symbol, timeframe="1m", limit=200):
            assert symbol == "BTC/USD"
            assert timeframe == "1m"
            assert limit == 200
            return rows

    apex = SimpleNamespace(broker_client=Broker())
    loop = NijaCoreLoop(apex, max_positions=1)

    df = loop._fetch_df(apex.broker_client, "BTC/USD")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 120
    assert {"open", "high", "low", "close", "volume"}.issubset(df.columns)
    assert float(df["close"].iloc[-1]) > 100.0


def test_fetch_df_accepts_dict_candle_payload() -> None:
    import pandas as pd
    from bot.nija_core_loop import NijaCoreLoop

    candles = [
        {"open": "100", "high": "101", "low": "99", "close": str(100 + i), "volume": "500"}
        for i in range(20)
    ]

    class Broker:
        connected = True

        def get_market_data(self, symbol, limit=200):
            return {"candles": candles}

    apex = SimpleNamespace(broker_client=Broker())
    loop = NijaCoreLoop(apex, max_positions=1)

    df = loop._fetch_df(None, "ETH-USD")

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 20
    assert float(df["close"].iloc[-1]) == 119.0


def test_apex_execute_action_normalizes_list_take_profit_payload() -> None:
    import sys

    bot_dir = str(Path(__file__).resolve().parents[1])
    if bot_dir not in sys.path:
        sys.path.insert(0, bot_dir)

    from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71

    captured = {}

    class Engine:
        def execute_entry(self, **kwargs):
            captured.update(kwargs)
            return {"id": "pos-1"}

    apex = NIJAApexStrategyV71.__new__(NIJAApexStrategyV71)
    apex.execution_engine = Engine()
    apex.profit_harvest_layer = None

    ok = apex.execute_action(
        {
            "action": "enter_long",
            "position_size": 15.0,
            "entry_price": 100.0,
            "stop_loss": 98.5,
            "take_profit": [100.85, 101.2, 101.8],
            "forced_fallback": True,
            "fallback_entry": True,
        },
        "BTC-USD",
    )

    assert ok is True
    assert captured["take_profit_levels"]["tp1"] == 100.85
    assert captured["take_profit_levels"]["tp2"] == 101.2
    assert captured["take_profit_levels"]["tp3"] == 101.8
    assert captured["take_profit_levels"]["forced_fallback"] is True
