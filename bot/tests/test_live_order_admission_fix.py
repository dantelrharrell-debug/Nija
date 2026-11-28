from types import SimpleNamespace

import pandas as pd

from bot.ai_intelligence_hub import AIIntelligenceHub
from bot.nija_core_loop import CycleSnapshot, NijaCoreLoop
from bot import no_trade_watchdog_runtime_patch as ntw_patch


def _sample_df(rows: int = 120) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [1000.0] * rows,
        }
    )


def test_ai_hub_allows_starter_sector_and_allocates_capital() -> None:
    class DummyRiskEngine:
        hard_sector_limit_pct = 0.20

        @staticmethod
        def get_position_size_adjustment(symbol, base_size_pct, portfolio_value):
            return base_size_pct

        @staticmethod
        def check_sector_limits(symbol, position_size_usd, portfolio_value):
            adjusted = min(float(position_size_usd), float(portfolio_value) * 0.20)
            return True, adjusted, {
                "sector_name": "L1",
                "current_sector_exposure_pct": 0.0,
                "projected_sector_exposure_pct": adjusted / float(portfolio_value),
            }

        @staticmethod
        def calculate_portfolio_metrics(portfolio_value):
            return SimpleNamespace(var_95=0.0)

    hub = AIIntelligenceHub(config={"min_ai_score": 0.0, "live_positions_sync_interval_sec": 3600.0})
    hub.risk_engine = DummyRiskEngine()
    hub.min_ai_score = 0.0
    # Skip live sync in unit test; we want deterministic empty-position behavior.
    hub._last_live_positions_sync_ts = 10**9

    result = hub.evaluate_trade(
        symbol="SOL-USD",
        side="long",
        df=_sample_df(),
        indicators={},
        base_size_pct=0.50,  # intentionally above hard cap; should clamp starter position
        portfolio_value=100.0,
    )

    assert result.exposure_allowed is True
    assert result.ai_approved is True
    assert result.correlation_adjusted_size_pct <= 0.20 + 1e-9
    assert result.allocated_capital > 0.0


def test_clean_signal_submits_order_and_watchdog_counts_success(monkeypatch) -> None:
    from bot import nija_core_loop as ncl

    df = _sample_df()

    class Broker:
        connected = True

        def get_candles(self, symbol, limit=200):
            return df

    class Apex:
        current_regime = "normal"
        broker_client = Broker()

        def calculate_indicators(self, frame):
            return {"adx": pd.Series([5.0] * len(frame)), "score_breakdown": {}}

        def check_market_filter(self, frame, indicators):
            return True, "uptrend", "ok"

        def _get_entry_type_for_regime(self, regime):
            return "swing"

        def _get_broker_name(self):
            return "coinbase"

        def analyze_market(self, frame, symbol, balance):
            return {
                "action": "enter_long",
                "reason": "clean_pass",
                "entry_price": 100.0,
                "position_size": 12.0,
                "capital_allocated": 12.0,
                "min_notional": 1.0,
                "stop_loss": 99.0,
                "take_profit": [101.0, 102.0, 103.0],
            }

        def execute_action(self, analysis, symbol):
            self.last_execution = (analysis, symbol)
            return True

    class PassingAI:
        speed_ctrl = SimpleNamespace(interval=150)

        def evaluate_symbol(self, **kwargs):
            sym = kwargs["symbol"]
            return SimpleNamespace(
                symbol=sym,
                side="long",
                composite_score=80.0,
                threshold_used=10.0,
                metadata={},
                position_multiplier=1.0,
            )

        def _compute_composite(self, *args, **kwargs):
            return 80.0, {"composite_score": 80.0, "score_breakdown": {}}

        def rank_and_select(self, candidates, slots, regime):
            return list(candidates[:slots])

    # Keep this test focused on clean admission→submit path.
    monkeypatch.setattr(ncl, "_TPE_AVAILABLE", False)
    monkeypatch.setattr(ncl, "_PMC_AVAILABLE", False)

    ntw_patch._STATE["execute_attempts"] = 0
    ntw_patch._STATE["execute_successes"] = 0
    ntw_patch._wrap_execute_action(Apex)

    apex = Apex()
    loop = NijaCoreLoop(apex, max_positions=1)
    loop._ai_engine = PassingAI()

    entries, blocked, scored, _gates = loop._phase3_scan_and_enter(
        broker=apex.broker_client,
        snapshot=CycleSnapshot(balance=100.0, current_regime="normal", daily_pnl_usd=0.0, open_positions=0),
        symbols=["BTC-USD"],
        available_slots=1,
        zero_signal_streak=0,
    )

    assert scored == 1
    assert entries == 1  # pairs_submitted increments
    assert blocked == 0
    assert ntw_patch._STATE["execute_attempts"] >= 1
    assert ntw_patch._STATE["execute_successes"] >= 1
    analysis, symbol = apex.last_execution
    assert symbol == "BTC-USD"
    assert float(analysis["capital_allocated"]) > 0.0
