from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from bot.control.confirmation_engine import ConfirmationEngine
from bot.control.control_compiler import RawSignal
from bot.control.decision_context import (
    PROTECTION_CONFIRMED,
    PROTECTION_UNVERIFIED,
    UserDecisionContext,
    UserPortfolioSnapshot,
    verify_exit_lifecycle,
    verify_protection_after_fill,
)
from bot.control.risk_engine import RiskEngine
from bot.control.signal_pipeline import SignalPipeline
from bot.control.strategy_detectors import (
    DetectorContext,
    MeanReversionDetector,
    OpeningRangeBreakoutDetector,
    RangeTradingDetector,
    ReversalExhaustionDetector,
    SupportResistanceBounceDetector,
    VolatilityExpansionDetector,
)
from bot.control.control_compiler import ControlCompiler
from bot.control.regime_engine import RegimeEngine
from bot.signal_broadcaster import SignalBroadcaster


NOW = datetime.now(timezone.utc)


def _decision_context(*, user_id: str, account_id: str, broker: str, signal_id: str, trade_id: str) -> UserDecisionContext:
    return UserDecisionContext(
        user_id=user_id,
        account_id=account_id,
        broker=broker,
        portfolio_id=f"{broker}:{account_id}",
        strategy_signal_id=signal_id,
        trade_id=trade_id,
        execution_mode="PAPER",
        asset_class="crypto",
    )


def _snapshot(
    *,
    context: UserDecisionContext,
    equity: float,
    buying_power: float,
    positions=None,
    pending_orders=None,
    daily_realized_pnl: float = 0.0,
    daily_unrealized_pnl: float = 0.0,
    peak_equity: float | None = None,
    kill_switch_active: bool = False,
    platform_kill_switch_active: bool = False,
    broker_healthy: bool = True,
    positions_fresh: bool = True,
    orders_fresh: bool = True,
    protection_state: str = PROTECTION_CONFIRMED,
    authoritative_positions_proven: bool = True,
    margin_enabled: bool = False,
    metadata=None,
) -> UserPortfolioSnapshot:
    snapshot_metadata = dict(metadata or {})
    if context.broker.lower() == "kraken" and "kraken_margin_visibility_proven" not in snapshot_metadata:
        snapshot_metadata["kraken_margin_visibility_proven"] = True
    return UserPortfolioSnapshot(
        user_id=context.user_id,
        account_id=context.account_id,
        broker=context.broker,
        balance=equity,
        equity=equity,
        available_buying_power=buying_power,
        open_positions=tuple(positions or ()),
        pending_orders=tuple(pending_orders or ()),
        portfolio_exposure=sum(float(p.get("size_usd") or p.get("usd_value") or 0.0) for p in (positions or ())),
        daily_realized_pnl=daily_realized_pnl,
        daily_unrealized_pnl=daily_unrealized_pnl,
        peak_equity=peak_equity,
        kill_switch_active=kill_switch_active,
        platform_kill_switch_active=platform_kill_switch_active,
        broker_healthy=broker_healthy,
        positions_fresh=positions_fresh,
        orders_fresh=orders_fresh,
        protection_state=protection_state,
        authoritative_positions_proven=authoritative_positions_proven,
        margin_enabled=margin_enabled,
        metadata=snapshot_metadata,
    )


class StaticBroker:
    def __init__(self, *, user_id: str, broker_name: str, balance: float, positions=None, open_orders=None):
        self.user_id = user_id
        self.broker_name = broker_name
        self.balance = balance
        self._positions = list(positions or [])
        self._open_orders = list(open_orders or [])

    def get_account_balance(self):
        return self.balance

    def get_positions(self):
        return list(self._positions)

    def get_open_orders(self):
        return list(self._open_orders)


class TestV2DetectorCoverage(unittest.TestCase):
    def test_orb_detects_breakout(self):
        index = pd.date_range("2026-01-01 00:00:00+00:00", periods=30, freq="min")
        rows = []
        for i in range(30):
            if i == 0:
                rows.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0})
            elif i == 29:
                rows.append({"open": 100.8, "high": 103.0, "low": 100.7, "close": 102.5, "volume": 4000.0})
            else:
                rows.append({"open": 100.0, "high": 100.8, "low": 99.4, "close": 100.1, "volume": 1000.0})
        df = pd.DataFrame(rows, index=index)
        signal = OpeningRangeBreakoutDetector().detect(df, DetectorContext(symbol="BTC-USD", broker="coinbase", market_regime="trending"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "FIRST_CANDLE_ORB")
        self.assertEqual(signal.direction, "long")

    def test_mean_reversion_detects_oversold_recovery(self):
        close = [100.0] * 45 + [95.0, 92.0, 89.0, 88.0, 94.0]
        df = self._ohlcv(close)
        signal = MeanReversionDetector().detect(df, DetectorContext(symbol="ETH-USD", broker="coinbase", market_regime="mean_reversion"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "MEAN_REVERSION")
        self.assertEqual(signal.direction, "long")

    def test_range_trading_detects_support_bounce_setup(self):
        close = [100.0, 102.0, 104.0, 106.0] * 9 + [100.5, 100.4, 100.3, 100.2]
        df = self._ohlcv(close)
        signal = RangeTradingDetector().detect(df, DetectorContext(symbol="SOL-USD", broker="coinbase", market_regime="ranging"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "RANGE_TRADING")
        self.assertEqual(signal.direction, "long")

    def test_support_resistance_detects_resistance_rejection(self):
        close = [100.0, 101.0, 102.5, 103.5] * 11 + [103.6, 103.7, 103.8, 103.2]
        df = self._ohlcv(close)
        df.iloc[-1, df.columns.get_loc("open")] = 104.2
        df.iloc[-1, df.columns.get_loc("high")] = 104.4
        df.iloc[-1, df.columns.get_loc("low")] = 102.9
        signal = SupportResistanceBounceDetector().detect(df, DetectorContext(symbol="ADA-USD", broker="coinbase", market_regime="ranging"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "SUPPORT_RESISTANCE_BOUNCE")
        self.assertEqual(signal.direction, "short")

    def test_volatility_expansion_detects_breakout_after_compression(self):
        close = [100 + (3 if i % 2 else -3) for i in range(24)] + [
            100.0, 100.05, 100.0, 100.04, 100.02, 100.03, 100.01, 100.02,
            100.0, 100.03, 100.02, 100.01, 100.0, 100.02, 100.03, 104.0,
        ]
        df = self._ohlcv(close, volume=[500.0] * 39 + [5000.0])
        df["spread_bps"] = 5.0
        signal = VolatilityExpansionDetector().detect(df, DetectorContext(symbol="XRP-USD", broker="coinbase", market_regime="breakout"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "VOLATILITY_EXPANSION")
        self.assertEqual(signal.direction, "long")

    def test_reversal_exhaustion_detects_bullish_reversal(self):
        close = [120.0 - i * 0.2 for i in range(55)] + [108.0, 106.0, 104.0, 103.0, 104.5]
        volume = [2000.0] * 59 + [1200.0]
        df = self._ohlcv(close, volume=volume)
        signal = ReversalExhaustionDetector().detect(df, DetectorContext(symbol="DOGE-USD", broker="coinbase", market_regime="mean_reversion"))
        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy, "REVERSAL_EXHAUSTION")
        self.assertEqual(signal.direction, "long")

    def test_orb_rejects_wick_only_breakout(self):
        index = pd.date_range("2026-01-01 00:00:00+00:00", periods=30, freq="min")
        rows = []
        for i in range(30):
            if i == 0:
                rows.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0})
            elif i == 29:
                rows.append({"open": 100.0, "high": 102.0, "low": 99.8, "close": 100.9, "volume": 4000.0})
            else:
                rows.append({"open": 100.0, "high": 100.7, "low": 99.5, "close": 100.0, "volume": 1000.0})
        df = pd.DataFrame(rows, index=index)
        self.assertIsNone(OpeningRangeBreakoutDetector().detect(df, DetectorContext(symbol="BTC-USD", broker="coinbase", market_regime="trending")))

    def test_range_invalidated_by_breakout(self):
        close = [100.0, 101.0, 102.0, 103.0] * 8 + [105.5, 106.0]
        df = self._ohlcv(close)
        self.assertIsNone(RangeTradingDetector().detect(df, DetectorContext(symbol="SOL-USD", broker="coinbase", market_regime="ranging")))

    def test_false_volatility_expansion_rejected_without_volume(self):
        close = [100.0 + ((i % 2) * 0.15) for i in range(35)] + [100.1, 100.0, 100.05, 100.1, 104.0]
        df = self._ohlcv(close, volume=[800.0] * 40)
        df["spread_bps"] = 5.0
        self.assertIsNone(VolatilityExpansionDetector().detect(df, DetectorContext(symbol="XRP-USD", broker="coinbase", market_regime="breakout")))

    def test_reversal_rejected_without_confirmation(self):
        close = [120.0 - i * 0.2 for i in range(55)] + [108.0, 106.0, 104.0, 103.0, 102.5]
        volume = [2000.0] * 59 + [1200.0]
        df = self._ohlcv(close, volume=volume)
        self.assertIsNone(ReversalExhaustionDetector().detect(df, DetectorContext(symbol="DOGE-USD", broker="coinbase", market_regime="mean_reversion")))

    def test_confirmation_rejects_stale_signal(self):
        engine = ConfirmationEngine(max_signal_age_seconds=10)
        from bot.control.strategy_signal import StrategySignal

        signal = StrategySignal(
            strategy="MEAN_REVERSION",
            symbol="BTC-USD",
            broker="coinbase",
            direction="long",
            timestamp=(NOW - timedelta(seconds=60)).isoformat(),
        )
        decision = engine.confirm(
            signal,
            score=0.8,
            checks={"candle_close": True, "volume": True, "trend": True, "market_data_fresh": True, "broker_available": True},
        )
        self.assertFalse(decision.approved)
        self.assertTrue(any("stale_signal" in reason for reason in decision.reasons))

    @staticmethod
    def _ohlcv(close, volume=None):
        volume = volume or [1500.0] * len(close)
        opens = [close[0]] + close[:-1]
        highs = [max(o, c) + 0.6 for o, c in zip(opens, close)]
        lows = [min(o, c) - 0.6 for o, c in zip(opens, close)]
        return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": close, "volume": volume})


class TestV2MultiUserIsolation(unittest.TestCase):
    def setUp(self):
        self.pipeline = SignalPipeline(compiler=ControlCompiler(), regime_engine=RegimeEngine(), risk_engine=RiskEngine())
        self.df = pd.DataFrame({"open": [100.0] * 60, "high": [101.0] * 60, "low": [99.0] * 60, "close": [100.0] * 60, "volume": [1000.0] * 60})

    def test_missing_user_identity_fails_closed(self):
        raw = RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=100.0,
            confidence=0.8,
            regime="trending",
            strategy="swing",
            broker="kraken",
            portfolio_id="kraken:user-a",
            strategy_signal_id="signal-1",
            trade_id="trade-1",
        )
        result = self.pipeline.process_signal(raw, df=self.df, current_positions=[], portfolio_value_usd=1000.0)
        self.assertIsNone(result)

    def test_user_a_duplicate_signal_blocked_without_affecting_user_b(self):
        context_a = _decision_context(user_id="user-a", account_id="acct-a", broker="kraken", signal_id="sig-1", trade_id="trade-a")
        context_b = _decision_context(user_id="user-b", account_id="acct-b", broker="kraken", signal_id="sig-1", trade_id="trade-b")
        snapshot_a = _snapshot(context=context_a, equity=10_000.0, buying_power=8_000.0)
        snapshot_b = _snapshot(context=context_b, equity=500.0, buying_power=400.0)

        raw_a = self._raw(context_a, size_usd=100.0)
        first = self.pipeline.process_signal(raw_a, df=None, decision_context=context_a, portfolio_snapshot=snapshot_a)
        second_snapshot_a = _snapshot(
            context=context_a,
            equity=10_000.0,
            buying_power=8_000.0,
            pending_orders=[{"symbol": "BTC-USD", "side": "buy", "status": "open"}],
        )
        second = self.pipeline.process_signal(raw_a, df=None, decision_context=context_a, portfolio_snapshot=second_snapshot_a)
        third = self.pipeline.process_signal(self._raw(context_b, size_usd=20.0), df=None, decision_context=context_b, portfolio_snapshot=snapshot_b)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNotNone(third)
        self.assertEqual(first.account_id, "acct-a")
        self.assertEqual(third.account_id, "acct-b")

    def test_user_a_authoritative_position_failure_does_not_block_user_b(self):
        context_a = _decision_context(user_id="user-a", account_id="acct-a", broker="kraken", signal_id="sig-2", trade_id="trade-a2")
        context_b = _decision_context(user_id="user-b", account_id="acct-b", broker="coinbase", signal_id="sig-2", trade_id="trade-b2")
        snapshot_a = _snapshot(
            context=context_a,
            equity=10_000.0,
            buying_power=8_000.0,
            authoritative_positions_proven=False,
            margin_enabled=True,
            metadata={"kraken_margin_visibility_proven": False},
        )
        snapshot_b = _snapshot(context=context_b, equity=5_000.0, buying_power=4_000.0)

        result_a = self.pipeline.process_signal(self._raw(context_a, size_usd=100.0), df=None, decision_context=context_a, portfolio_snapshot=snapshot_a)
        result_b = self.pipeline.process_signal(self._raw(context_b, size_usd=100.0), df=None, decision_context=context_b, portfolio_snapshot=snapshot_b)

        self.assertIsNone(result_a)
        self.assertIsNotNone(result_b)
        self.assertEqual(result_b.account_id, "acct-b")

    def test_user_a_loss_and_kill_switch_do_not_halt_user_b(self):
        context_a = _decision_context(user_id="user-a", account_id="acct-a", broker="coinbase", signal_id="sig-3", trade_id="trade-a3")
        context_b = _decision_context(user_id="user-b", account_id="acct-b", broker="okx", signal_id="sig-3", trade_id="trade-b3")
        snapshot_a = _snapshot(context=context_a, equity=1_000.0, buying_power=500.0, daily_realized_pnl=-100.0, kill_switch_active=True)
        snapshot_b = _snapshot(context=context_b, equity=20_000.0, buying_power=19_000.0)

        result_a = self.pipeline.process_signal(self._raw(context_a, size_usd=50.0), df=None, decision_context=context_a, portfolio_snapshot=snapshot_a)
        result_b = self.pipeline.process_signal(self._raw(context_b, size_usd=500.0), df=None, decision_context=context_b, portfolio_snapshot=snapshot_b)

        self.assertIsNone(result_a)
        self.assertIsNotNone(result_b)

    def test_compile_rejection_releases_duplicate_reservation(self):
        context = _decision_context(user_id="user-a", account_id="acct-a", broker="kraken", signal_id="sig-compile", trade_id="trade-compile")
        snapshot = _snapshot(context=context, equity=10_000.0, buying_power=8_000.0)
        raw = RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=100.0,
            confidence=0.0,
            regime="trending",
            strategy="swing",
            user_id=context.user_id,
            account_id=context.account_id,
            broker=context.broker,
            portfolio_id=context.portfolio_id,
            strategy_signal_id=context.strategy_signal_id,
            trade_id=context.trade_id,
            approved=True,
            execution_mode=context.execution_mode,
            asset_class=context.asset_class,
        )

        result = self.pipeline.process_signal(raw, df=None, decision_context=context, portfolio_snapshot=snapshot)
        duplicate_key = self.pipeline._idempotency_registry.build_key(context, symbol="BTC-USD", direction="long")

        self.assertIsNone(result)
        self.assertEqual(self.pipeline._idempotency_registry.get_state(duplicate_key), "released")

    def test_pending_order_direction_normalization_ignores_opposite_side(self):
        context = _decision_context(user_id="user-a", account_id="acct-a", broker="coinbase", signal_id="sig-pending", trade_id="trade-pending")
        snapshot = _snapshot(
            context=context,
            equity=10_000.0,
            buying_power=8_000.0,
            pending_orders=[{"symbol": "BTC-USD", "side": "sell", "status": "open"}],
        )

        notes = snapshot.readiness_notes(symbol="BTC-USD", direction="buy")

        self.assertNotIn("PENDING_ORDER_EXISTS", notes)

    def test_trade_frequency_is_account_scoped(self):
        engine = RiskEngine()
        approved_a, _ = engine.validate_trade(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            portfolio_value_usd=10_000.0,
            current_positions=[],
            account_id="acct-a",
            broker="kraken",
        )
        approved_b, _ = engine.validate_trade(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            portfolio_value_usd=10_000.0,
            current_positions=[],
            account_id="acct-b",
            broker="kraken",
        )
        self.assertTrue(approved_a)
        self.assertTrue(approved_b)

    def test_protection_and_exit_verification_require_broker_proof(self):
        context = _decision_context(user_id="user-a", account_id="acct-a", broker="kraken", signal_id="sig-4", trade_id="trade-a4")
        protection = verify_protection_after_fill(
            context,
            filled_quantity=1.0,
            stop_loss_order_id="sl-1",
            take_profit_order_id="tp-1",
            broker_confirmation={"orders_submitted": True, "stop_loss_verified": True, "take_profit_verified": True},
        )
        self.assertEqual(protection.state, PROTECTION_CONFIRMED)

        unverified = verify_protection_after_fill(
            context,
            filled_quantity=1.0,
            stop_loss_order_id="sl-1",
            take_profit_order_id="tp-1",
            broker_confirmation=None,
        )
        self.assertEqual(unverified.state, PROTECTION_UNVERIFIED)

        exit_result = verify_exit_lifecycle(
            context,
            exit_reason="STOP_LOSS",
            submission_status="accepted",
            broker_fill_state="filled",
            remaining_position_quantity=0.0,
        )
        self.assertEqual(exit_result.state, "POSITION_CLOSED")
        self.assertIn("EXIT_FILLED", exit_result.events)
        self.assertIn("POSITION_CLOSED", exit_result.events)

    def test_signal_broadcaster_builds_isolated_account_decisions(self):
        broadcaster = SignalBroadcaster(risk_fraction=0.1)
        broadcaster.register_account("acct-a", StaticBroker(user_id="user-a", broker_name="kraken", balance=1000.0, positions=[{"symbol": "ETH-USD", "usd_value": 150.0}]), balance=1000.0)
        broadcaster.register_account("acct-b", StaticBroker(user_id="user-b", broker_name="coinbase", balance=100.0), balance=100.0)

        decisions = broadcaster.build_account_decisions({"symbol": "BTC-USD", "action": "enter_long", "strategy_signal_id": "shared-1", "strategy": "RANGE_TRADING", "execution_mode": "PAPER"})

        self.assertEqual(len(decisions), 2)
        by_account = {decision.account_id: decision for decision in decisions}
        self.assertEqual(by_account["acct-a"].decision_context.user_id, "user-a")
        self.assertEqual(by_account["acct-b"].decision_context.user_id, "user-b")
        self.assertGreater(by_account["acct-a"].proposed_size_usd, by_account["acct-b"].proposed_size_usd)
        self.assertEqual(by_account["acct-a"].portfolio_snapshot.open_positions[0]["symbol"], "ETH-USD")
        self.assertEqual(by_account["acct-b"].portfolio_snapshot.open_positions, ())
        self.assertFalse(by_account["acct-a"].portfolio_snapshot.metadata["kraken_margin_visibility_proven"])

    def test_signal_broadcaster_uses_kraken_margin_visibility_metadata(self):
        broadcaster = SignalBroadcaster(risk_fraction=0.1)
        broker = StaticBroker(user_id="user-a", broker_name="kraken", balance=1000.0)
        broker.kraken_margin_visibility_proven = True
        broadcaster.register_account("acct-a", broker, balance=1000.0)

        decisions = broadcaster.build_account_decisions(
            {"symbol": "BTC-USD", "action": "enter_long", "strategy_signal_id": "shared-2", "strategy": "RANGE_TRADING", "execution_mode": "PAPER"}
        )

        self.assertTrue(decisions[0].portfolio_snapshot.metadata["kraken_margin_visibility_proven"])

    @staticmethod
    def _raw(context: UserDecisionContext, *, size_usd: float) -> RawSignal:
        return RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=size_usd,
            confidence=0.8,
            regime="trending",
            strategy="swing",
            user_id=context.user_id,
            account_id=context.account_id,
            broker=context.broker,
            portfolio_id=context.portfolio_id,
            strategy_signal_id=context.strategy_signal_id,
            trade_id=context.trade_id,
            approved=True,
            execution_mode=context.execution_mode,
            asset_class=context.asset_class,
        )


if __name__ == "__main__":
    unittest.main()
