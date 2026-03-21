"""
NIJA Broker Performance Tracker
================================

Tracks trading performance *outcomes* (win rate, slippage, execution speed)
per broker and automatically routes new trades to the best-performing venue.

This module is distinct from ``broker_performance_scorer.py`` which tracks
infrastructure reliability (fill rate, API latency, connectivity).
``BrokerPerformanceTracker`` focuses on **trading outcomes** — did this
broker actually produce winning trades? Did the entry price match the signal?
How fast was the real execution?

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │                  BrokerPerformanceTracker                        │
    │                                                                  │
    │  Per-broker rolling trade window (default 200 trades):           │
    │                                                                  │
    │  • Win rate        – fraction of trades that closed in profit    │
    │  • Avg slippage    – mean entry price deviation from signal (bps)│
    │  • Execution speed – mean order-to-fill time in milliseconds     │
    │  • P&L score       – cumulative realised P&L (EMA normalised)    │
    │                                                                  │
    │  Composite routing score (0–100):                                │
    │    win_rate_score   × 0.40                                       │
    │    slippage_score   × 0.30  (lower slippage → higher score)      │
    │    speed_score      × 0.20  (lower latency → higher score)       │
    │    pnl_score        × 0.10                                       │
    │                                                                  │
    │  Route selection:                                                │
    │    get_best_broker(candidates) → str                             │
    │                                                                  │
    └──────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.broker_performance_tracker import get_broker_performance_tracker

    tracker = get_broker_performance_tracker()

    # After every closed trade:
    tracker.record_trade(
        broker="coinbase",
        symbol="BTC-USD",
        signal_price=42_000.0,
        fill_price=42_010.0,    # actual fill (determines slippage)
        execution_ms=95.0,      # time from order submission to fill
        pnl_usd=+120.0,
        is_win=True,
    )

    # Before placing a trade — pick the best broker:
    best = tracker.get_best_broker(["coinbase", "kraken", "binance"])
    # → "coinbase"

    # Detailed report:
    print(tracker.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.broker_performance_tracker")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 200          # rolling trade window per broker
DEFAULT_DATA_DIR: str = "data"

# Score weights
W_WIN_RATE: float = 0.40
W_SLIPPAGE: float = 0.30
W_SPEED: float = 0.20
W_PNL: float = 0.10

# EMA decay for P&L score
EMA_DECAY: float = 0.05

# Slippage / speed normalisation caps (used to map to 0-100 score)
SLIPPAGE_CAP_BPS: float = 50.0    # ≥ 50 bps slippage → score 0
SPEED_CAP_MS: float = 2_000.0     # ≥ 2 000 ms → score 0


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TradeRecord:
    """Single trade outcome attributed to a broker."""
    ts: str
    broker: str
    symbol: str
    signal_price: float
    fill_price: float
    slippage_bps: float           # abs(fill-signal)/signal * 10_000
    execution_ms: float
    pnl_usd: float
    is_win: bool


@dataclass
class BrokerStats:
    """Aggregated performance stats for one broker."""
    broker: str
    trade_count: int
    win_count: int
    win_rate: float                # 0.0 – 1.0
    avg_slippage_bps: float
    avg_execution_ms: float
    total_pnl_usd: float
    ema_pnl_score: float           # normalised EMA P&L signal
    routing_score: float           # composite 0–100


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class BrokerPerformanceTracker:
    """
    Tracks per-broker trading outcomes and provides smart routing decisions.
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        data_dir: Optional[str] = None,
    ) -> None:
        self._window = window
        self._data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Rolling trade windows keyed by broker name
        self._trades: Dict[str, Deque[TradeRecord]] = {}
        # EMA P&L signal per broker
        self._pnl_ema: Dict[str, float] = {}

        self._lock = threading.Lock()
        self._load_state()
        logger.info("BrokerPerformanceTracker initialised (window=%d)", window)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        broker: str,
        symbol: str,
        signal_price: float,
        fill_price: float,
        execution_ms: float,
        pnl_usd: float,
        is_win: bool,
    ) -> None:
        """
        Record the outcome of a completed trade.

        Parameters
        ----------
        broker        : Exchange / broker identifier (e.g. "coinbase").
        symbol        : Trading pair (e.g. "BTC-USD").
        signal_price  : Price at the moment the entry signal fired.
        fill_price    : Actual fill price received from the broker.
        execution_ms  : Milliseconds from order submission to confirmed fill.
        pnl_usd       : Realised profit/loss in USD.
        is_win        : True if the trade closed in profit.
        """
        slippage_bps = (
            abs(fill_price - signal_price) / signal_price * 10_000
            if signal_price > 0 else 0.0
        )
        record = TradeRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            broker=broker,
            symbol=symbol,
            signal_price=signal_price,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            execution_ms=max(execution_ms, 0.0),
            pnl_usd=pnl_usd,
            is_win=is_win,
        )
        with self._lock:
            if broker not in self._trades:
                self._trades[broker] = deque(maxlen=self._window)
                self._pnl_ema[broker] = 0.0
            self._trades[broker].append(record)
            # Update EMA P&L signal
            prev = self._pnl_ema[broker]
            self._pnl_ema[broker] = prev * (1 - EMA_DECAY) + pnl_usd * EMA_DECAY

        self._append_audit(record)
        logger.debug(
            "BrokerPerformanceTracker: %s %s win=%s slip=%.1fbps exec=%dms pnl=$%.2f",
            broker, symbol, is_win, slippage_bps, execution_ms, pnl_usd,
        )

    def get_stats(self, broker: str) -> Optional[BrokerStats]:
        """Return aggregated stats for a single broker (None if unknown)."""
        with self._lock:
            return self._compute_stats(broker)

    def get_all_stats(self) -> List[BrokerStats]:
        """Return stats for all tracked brokers, sorted by routing score."""
        with self._lock:
            stats = [self._compute_stats(b) for b in self._trades]
        return sorted(stats, key=lambda s: s.routing_score, reverse=True)

    def get_best_broker(self, candidates: List[str]) -> Optional[str]:
        """
        Given a list of candidate broker names, return the one with the
        highest composite routing score.  Returns None if no candidates
        have been tracked yet.
        """
        if not candidates:
            return None
        with self._lock:
            scored = []
            for b in candidates:
                stats = self._compute_stats(b)
                if stats is not None:
                    scored.append((b, stats.routing_score))
        if not scored:
            return candidates[0]  # fallback: first in list
        return max(scored, key=lambda x: x[1])[0]

    def get_report(self) -> str:
        """Human-readable performance report for all tracked brokers."""
        stats_list = self.get_all_stats()
        if not stats_list:
            return "BrokerPerformanceTracker: no trades recorded yet."
        lines = [
            "═══════════════════════════════════════════════════════════",
            "  NIJA Broker Performance Tracker",
            "═══════════════════════════════════════════════════════════",
        ]
        for s in stats_list:
            lines += [
                f"  [{s.broker}]",
                f"    Trades       : {s.trade_count}",
                f"    Win rate     : {s.win_rate:.1%}",
                f"    Avg slippage : {s.avg_slippage_bps:.2f} bps",
                f"    Avg exec     : {s.avg_execution_ms:.0f} ms",
                f"    Total P&L    : ${s.total_pnl_usd:,.2f}",
                f"    Routing score: {s.routing_score:.1f}/100",
                "  ─────────────────────────────────────────────────────",
            ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_stats(self, broker: str) -> Optional[BrokerStats]:
        """Compute :class:`BrokerStats` from the rolling window (caller holds lock)."""
        trades = self._trades.get(broker)
        if not trades:
            return None
        n = len(trades)
        wins = sum(1 for t in trades if t.is_win)
        win_rate = wins / n
        avg_slip = sum(t.slippage_bps for t in trades) / n
        avg_exec = sum(t.execution_ms for t in trades) / n
        total_pnl = sum(t.pnl_usd for t in trades)
        ema_pnl = self._pnl_ema.get(broker, 0.0)

        # --- Normalise to 0-100 scores ---
        win_score = win_rate * 100.0
        slip_score = max(0.0, (1 - avg_slip / SLIPPAGE_CAP_BPS)) * 100.0
        speed_score = max(0.0, (1 - avg_exec / SPEED_CAP_MS)) * 100.0
        # P&L score: map EMA into 0-100 range using sigmoid-like clamp
        pnl_norm = max(-1.0, min(1.0, ema_pnl / 100.0))  # $100 reference
        pnl_score = (pnl_norm + 1.0) * 50.0  # maps -1..1 → 0..100

        routing_score = (
            W_WIN_RATE * win_score
            + W_SLIPPAGE * slip_score
            + W_SPEED * speed_score
            + W_PNL * pnl_score
        )

        return BrokerStats(
            broker=broker,
            trade_count=n,
            win_count=wins,
            win_rate=win_rate,
            avg_slippage_bps=avg_slip,
            avg_execution_ms=avg_exec,
            total_pnl_usd=total_pnl,
            ema_pnl_score=ema_pnl,
            routing_score=routing_score,
        )

    def _append_audit(self, record: TradeRecord) -> None:
        """Append one record to the JSONL audit log."""
        try:
            log_path = self._data_dir / "broker_performance_tracker.jsonl"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record)) + "\n")
        except OSError as exc:
            logger.warning("BrokerPerformanceTracker: audit write failed: %s", exc)

    def _load_state(self) -> None:
        """Replay the JSONL audit log to rebuild in-memory state on startup."""
        log_path = self._data_dir / "broker_performance_tracker.jsonl"
        if not log_path.exists():
            return
        loaded = 0
        try:
            with open(log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        broker = d.get("broker", "unknown")
                        if broker not in self._trades:
                            self._trades[broker] = deque(maxlen=self._window)
                            self._pnl_ema[broker] = 0.0
                        rec = TradeRecord(**{k: d[k] for k in TradeRecord.__dataclass_fields__})  # type: ignore[attr-defined]
                        self._trades[broker].append(rec)
                        prev = self._pnl_ema[broker]
                        self._pnl_ema[broker] = prev * (1 - EMA_DECAY) + rec.pnl_usd * EMA_DECAY
                        loaded += 1
                    except Exception:
                        pass
        except OSError:
            pass
        if loaded:
            logger.info("BrokerPerformanceTracker: replayed %d trade records", loaded)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[BrokerPerformanceTracker] = None
_INSTANCE_LOCK = threading.Lock()


def get_broker_performance_tracker(
    window: int = DEFAULT_WINDOW,
    data_dir: Optional[str] = None,
) -> BrokerPerformanceTracker:
    """Thread-safe singleton accessor."""
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = BrokerPerformanceTracker(window=window, data_dir=data_dir)
    return _INSTANCE
