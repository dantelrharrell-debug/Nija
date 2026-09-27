"""Offline Break/Retest detector replay using historical OHLCV bars.

This is a research tool, not the live NIJA execution pipeline.  A signal is
observed after its candle closes and an illustrative order enters at the next
candle's open.  Intrabar stop/target ambiguity is resolved against the trade.
"""

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Any

import pandas as pd

from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.trading_context import TradingContext
from bot.unified_backtest_engine import UnifiedBacktestEngine


def _validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(bars.index, pd.DatetimeIndex) or not bars.index.is_monotonic_increasing:
        raise ValueError("bars need an ascending timestamp index")
    if bars.index.has_duplicates or bars.index.hasnans:
        raise ValueError("bar timestamps must be unique and valid")
    required = ("open", "high", "low", "close", "volume")
    if any(column not in bars for column in required):
        raise ValueError("bars need open, high, low, close, and volume")
    frame = bars.loc[:, required].apply(pd.to_numeric, errors="coerce")
    if frame.isna().any().any() or not frame.map(math.isfinite).all().all():
        raise ValueError("OHLCV values must be finite")
    if (frame.loc[:, ("open", "high", "low", "close")] <= 0).any().any():
        raise ValueError("prices must be positive")
    if (frame["volume"] < 0).any():
        raise ValueError("volume must not be negative")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
            (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("inconsistent OHLC bar")
    return frame


def json_safe(value: Any) -> Any:
    """Replace undefined metrics with JSON null and convert numeric scalars."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value) if math.isfinite(float(value)) else None
    return value


def replay_break_retest(
    bars: pd.DataFrame,
    *,
    symbol: str,
    initial_balance: float = 10000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    first_entry_index: int = 0,
) -> dict[str, Any]:
    """Replay the existing detector with next-open entry and conservative exits.

    The 1% risk and 10% cash allocation caps below are illustrative replay
    assumptions. They do not change any NIJA strategy or broker settings.
    """
    frame = _validate_bars(bars)
    if not symbol.strip() or not math.isfinite(initial_balance) or initial_balance <= 0:
        raise ValueError("symbol and positive initial balance are required")
    if not 0 <= commission_pct < 1 or not 0 <= slippage_pct < 1:
        raise ValueError("fee and slippage fractions must be in [0, 1)")
    detector = BreakRetestDetector()
    if len(frame) < detector.lookback + 17:
        raise ValueError("insufficient candles for Break/Retest lookback and next-open execution")
    if not isinstance(first_entry_index, int) or not 0 <= first_entry_index < len(frame) - 1:
        raise ValueError("first_entry_index must leave at least two evaluation bars")

    context = TradingContext(
        user_id="offline-research", trading_account_id="offline-account", broker="paper",
        broker_account_id="offline-broker", strategy_instance_id="BREAK_RETEST",
        portfolio_id="offline-portfolio", request_id="offline-replay",
        correlation_id="offline-replay", environment="backtest", mode="backtest",
    )
    detector_context = DetectorContext(symbol=symbol, broker="paper", trading_context=context)
    engine = UnifiedBacktestEngine(initial_balance, commission_pct, slippage_pct)
    pending = None
    active_id = None
    signals = 0
    rejected_gap = 0

    # The preceding training candle may form a signal for the first held-out
    # opening, but its price is never used to value an evaluation-period trade.
    for index in range(max(0, first_entry_index - 1), len(frame)):
        row = frame.iloc[index]
        timestamp = frame.index[index]
        opening = float(row["open"])
        if pending is not None:
            stop = float(pending.suggested_stop)
            target = float(pending.target_candidates[0])
            side = pending.direction
            # A gap through either protective level has no defensible
            # next-open risk geometry for this simple simulator.
            if ((side == "long" and stop < opening < target) or
                    (side == "short" and target < opening < stop)):
                risk_per_unit = abs(opening - stop)
                size = min(
                    engine.current_balance * 0.01 / risk_per_unit,
                    engine.current_balance * 0.10 / (opening * (1 + slippage_pct + commission_pct)),
                )
                if size > 0 and math.isfinite(size):
                    active_id = engine.open_position(
                        symbol, side, opening, size, stop, target,
                        entry_time=timestamp, regime=pending.market_regime,
                        entry_score=pending.raw_score,
                    )
            else:
                rejected_gap += 1
            pending = None

        if active_id is not None:
            position = engine.positions[active_id]
            stop, target = position["stop_loss"], position["take_profit"]
            side = position["side"]
            if side == "long":
                if opening <= stop:
                    fill, reason = opening, "stop_gap"
                elif opening >= target:
                    fill, reason = opening, "target_gap"
                elif float(row["low"]) <= stop:
                    fill, reason = stop, "stop_loss"
                elif float(row["high"]) >= target:
                    fill, reason = target, "take_profit"
                else:
                    fill, reason = None, ""
            else:
                if opening >= stop:
                    fill, reason = opening, "stop_gap"
                elif opening <= target:
                    fill, reason = opening, "target_gap"
                elif float(row["high"]) >= stop:
                    fill, reason = stop, "stop_loss"
                elif float(row["low"]) <= target:
                    fill, reason = target, "take_profit"
                else:
                    fill, reason = None, ""
            if fill is not None:
                engine.close_position(active_id, fill, timestamp, reason)
                active_id = None

        if index >= first_entry_index:
            engine.update_equity_curve(timestamp, {symbol: float(row["close"])})
        # Never use the current bar to enter at its own opening price.
        if active_id is None and index < len(frame) - 1:
            signal = detector.detect(frame.iloc[:index + 1], detector_context)
            if signal is not None:
                pending = signal
                signals += 1

    if active_id is not None:
        engine.close_position(active_id, float(frame.iloc[-1]["close"]), frame.index[-1], "end_of_data")
        engine.update_equity_curve(frame.index[-1], {symbol: float(frame.iloc[-1]["close"])})

    result = json_safe(engine.calculate_metrics().to_dict())
    summary = result["summary"]
    # The shared engine assumes daily equity observations for Sharpe/Sortino.
    # Bar frequency is arbitrary here; publishing those annualized values
    # would be false precision. No-loss profit factor is undefined as well.
    summary["sharpe_ratio"] = None
    summary["sortino_ratio"] = None
    if summary["losing_trades"] == 0:
        summary["profit_factor"] = None
    if summary["total_trades"] == 0:
        summary["win_rate"] = None
    result["analysis"] = {
        "kind": "detector_replay_only", "strategy": "BREAK_RETEST", "symbol": symbol,
        "signals": signals, "rejected_gap_entries": rejected_gap,
        "from": frame.index[first_entry_index].isoformat(), "through": frame.index[-1].isoformat(),
        "bars": len(frame) - first_entry_index, "warmup_bars": first_entry_index,
        "requires_fvg": detector.require_fvg,
        "lookback": detector.lookback,
        "commission_fraction_per_side": commission_pct,
        "slippage_fraction_per_side": slippage_pct,
        "nominal_risk_fraction_per_entry": 0.01, "cash_allocation_cap": 0.10,
        "live_readiness_granted": False,
        "limitations": [
            "Research replay of one detector, not NIJA's complete execution and risk pipeline.",
            "Entry occurs at next candle open; stop wins when stop and target touch in one candle.",
            "No spread, funding, borrow cost, order-book depth, or broker rejection model.",
            "Stop gaps and execution costs can exceed the nominal risk budget.",
            "In-sample history cannot establish future profitability or grant live readiness.",
            "Annualized Sharpe and Sortino need verified bar frequency and are intentionally omitted.",
        ],
    }
    return result


def replay_break_retest_holdout(
    bars: pd.DataFrame,
    *,
    symbol: str,
    holdout_fraction: float,
    initial_balance: float = 10000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> dict[str, Any]:
    """Evaluate a frozen detector on an untouched chronological final segment.

    There is no parameter search here. Any tuning/strategy selection must use
    only the earlier segment, before viewing the holdout results. Historical
    candles must come from an independently verified source.
    """
    frame = _validate_bars(bars)
    if not math.isfinite(holdout_fraction) or not 0.10 <= holdout_fraction <= 0.50:
        raise ValueError("holdout_fraction must be between 0.10 and 0.50")
    split = int(len(frame) * (1 - holdout_fraction))
    detector = BreakRetestDetector()
    if split < detector.lookback + 17 or len(frame) - split < 20:
        raise ValueError("need sufficient training warmup and at least 20 held-out bars")
    options = {
        "symbol": symbol, "initial_balance": initial_balance,
        "commission_pct": commission_pct, "slippage_pct": slippage_pct,
    }
    training = replay_break_retest(frame.iloc[:split], **options)
    holdout = replay_break_retest(frame, first_entry_index=split, **options)
    count = holdout["summary"]["total_trades"]
    return {
        "analysis": {
            "kind": "chronological_holdout_detector_replay_only",
            "strategy": "BREAK_RETEST", "symbol": symbol,
            "split_timestamp": frame.index[split].isoformat(),
            "training_bars": split, "holdout_bars": len(frame) - split,
            "holdout_fraction": holdout_fraction,
            "holdout_closed_trades": count,
            "evidence_status": "limited_sample" if count < 20 else "requires_independent_review",
            "live_readiness_granted": False,
            "limitations": [
                "This evaluates a detector, not NIJA's full execution and risk pipeline.",
                "Parameter selection must be frozen before viewing holdout results; this tool cannot verify that.",
                "Historical source integrity and representativeness must be checked separately.",
                "Twenty trades is a minimum review flag, not proof of a durable edge.",
            ],
        },
        "training": training,
        "holdout": holdout,
    }
