"""
Signal Funnel Diagnostics
==========================

Tracks how many opportunities pass/fail at each filter stage per trading pair,
and provides shadow-paper logging to measure hypothetical PnL vs. executed trades.

Per-pair funnel counters (logged every REPORT_INTERVAL cycles):
  signals_seen       - times analyze_market was called for this pair
  confidence_pass    - passed confidence threshold
  adx_pass           - passed ADX threshold
  volume_pass        - passed volume threshold
  ai_gate_pass       - passed AIEntryGate (gate score ≥ threshold)
  execution_pass     - actually submitted to broker

Rejection events are emitted as structured ``REJECTED_SIGNAL:`` log lines:
  REJECTED_SIGNAL: pair=ETHUSD confidence=0.21 threshold=0.25 adx=9 volume=1.8%

Shadow-paper tracking records every signal that passed all gates, computes
the hypothetical PnL based on subsequent price movement, and compares it
to the actual executed trades.

Usage
-----
::

    from bot.signal_funnel_diagnostics import get_signal_funnel

    funnel = get_signal_funnel()
    funnel.record_signal_seen(symbol)
    funnel.record_confidence_pass(symbol)
    funnel.record_rejected(symbol, confidence=0.21, threshold=0.25, adx=9.0, volume=0.018, reason="low_confidence")
    funnel.record_ai_gate_pass(symbol)
    funnel.record_execution_pass(symbol)
    funnel.maybe_report_and_reset()

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("nija.signal_funnel")

# How often to emit the per-pair funnel summary to the log (seconds)
REPORT_INTERVAL_SECS: float = 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Per-pair funnel statistics
# ---------------------------------------------------------------------------

@dataclass
class FunnelStats:
    """Per-symbol funnel counters for one reporting window."""
    pair: str
    signals_seen: int = 0
    confidence_pass: int = 0
    adx_pass: int = 0
    volume_pass: int = 0
    ai_gate_pass: int = 0
    execution_pass: int = 0

    def as_log_line(self) -> str:
        """Return a formatted one-line summary suitable for log emission."""
        return (
            f"SIGNAL_FUNNEL: PAIR={self.pair} "
            f"signals_seen={self.signals_seen} "
            f"confidence_pass={self.confidence_pass} "
            f"adx_pass={self.adx_pass} "
            f"volume_pass={self.volume_pass} "
            f"ai_gate_pass={self.ai_gate_pass} "
            f"execution_pass={self.execution_pass}"
        )


# ---------------------------------------------------------------------------
# Shadow-paper trade record
# ---------------------------------------------------------------------------

@dataclass
class ShadowTrade:
    """A hypothetical trade that passed all gates but may not have executed."""
    pair: str
    side: str           # 'long' or 'short'
    entry_price: float
    entry_time: float   # unix timestamp
    confidence: float
    adx: float
    volume_ratio: float
    gate_score: float
    executed: bool = False  # True when the live bot also entered
    exit_price: float = 0.0
    exit_time: float = 0.0
    hypothetical_pnl_pct: float = 0.0  # filled on close


# ---------------------------------------------------------------------------
# Main diagnostics class
# ---------------------------------------------------------------------------

class SignalFunnelDiagnostics:
    """
    Thread-safe signal funnel tracker and shadow-paper logger.

    Call ``get_signal_funnel()`` to obtain the global singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: Dict[str, FunnelStats] = {}
        self._shadow_trades: List[ShadowTrade] = []
        self._last_report_time: float = time.monotonic()

    # ------------------------------------------------------------------
    # Funnel stage recorders
    # ------------------------------------------------------------------

    def record_signal_seen(self, pair: str) -> None:
        """Increment signals_seen for this pair."""
        with self._lock:
            self._get_or_create(pair).signals_seen += 1

    def record_confidence_pass(self, pair: str) -> None:
        """Increment confidence_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).confidence_pass += 1

    def record_adx_pass(self, pair: str) -> None:
        """Increment adx_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).adx_pass += 1

    def record_volume_pass(self, pair: str) -> None:
        """Increment volume_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).volume_pass += 1

    def record_ai_gate_pass(self, pair: str) -> None:
        """Increment ai_gate_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).ai_gate_pass += 1

    def record_execution_pass(self, pair: str) -> None:
        """Increment execution_pass for this pair."""
        with self._lock:
            self._get_or_create(pair).execution_pass += 1

    # ------------------------------------------------------------------
    # Rejection logger
    # ------------------------------------------------------------------

    def record_rejected(
        self,
        pair: str,
        *,
        confidence: float = 0.0,
        threshold: float = 0.0,
        adx: float = 0.0,
        volume: float = 0.0,
        reason: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Emit a structured REJECTED_SIGNAL log line.

        Example output::

            REJECTED_SIGNAL: pair=ETHUSD confidence=0.21 threshold=0.25 adx=9 volume=1.8%
        """
        parts = [
            f"pair={pair}",
            f"confidence={confidence:.2f}",
            f"threshold={threshold:.2f}",
            f"adx={adx:.1f}",
            f"volume={volume * 100:.1f}%",
        ]
        if reason:
            parts.append(f"reason={reason}")
        if extra:
            for k, v in extra.items():
                parts.append(f"{k}={v}")
        logger.info("REJECTED_SIGNAL: %s", " ".join(parts))

    # ------------------------------------------------------------------
    # Shadow-paper tracking
    # ------------------------------------------------------------------

    def record_shadow_entry(
        self,
        pair: str,
        side: str,
        entry_price: float,
        confidence: float,
        adx: float,
        volume_ratio: float,
        gate_score: float,
        executed: bool = False,
    ) -> None:
        """
        Record a signal that passed all gates (regardless of whether it executed).
        Used for shadow-paper PnL comparison.
        """
        trade = ShadowTrade(
            pair=pair,
            side=side,
            entry_price=entry_price,
            entry_time=time.time(),
            confidence=confidence,
            adx=adx,
            volume_ratio=volume_ratio,
            gate_score=gate_score,
            executed=executed,
        )
        with self._lock:
            self._shadow_trades.append(trade)
            # Trim to the most recent 500 entries to avoid unbounded growth
            if len(self._shadow_trades) > 500:
                self._shadow_trades = self._shadow_trades[-500:]

    def update_shadow_exit(
        self,
        pair: str,
        exit_price: float,
        side: str = "long",
    ) -> None:
        """
        Update the most recently opened shadow trade for the given pair with an exit
        price and compute hypothetical PnL.  Only the newest still-open trade is
        closed so that multiple open shadow entries for the same pair are not all
        closed at once.
        """
        with self._lock:
            for trade in reversed(self._shadow_trades):
                if trade.pair == pair and trade.exit_price == 0.0:
                    trade.exit_price = exit_price
                    trade.exit_time = time.time()
                    if trade.entry_price > 0:
                        raw_pnl = (exit_price - trade.entry_price) / trade.entry_price
                        trade.hypothetical_pnl_pct = (
                            raw_pnl if trade.side == "long" else -raw_pnl
                        ) * 100.0
                    break  # only close the most recent open trade

    def mark_shadow_executed(self, pair: str) -> None:
        """
        Mark the most recently opened (and not yet executed) shadow trade for
        *pair* as having been actually submitted to the broker.  Thread-safe.
        """
        with self._lock:
            for trade in reversed(self._shadow_trades):
                if trade.pair == pair and not trade.executed:
                    trade.executed = True
                    break

    def get_shadow_summary(self) -> Dict[str, Any]:
        """
        Return a snapshot of shadow-paper statistics for logging or API consumption.
        """
        with self._lock:
            closed = [t for t in self._shadow_trades if t.exit_price > 0.0]
            open_shadow = [t for t in self._shadow_trades if t.exit_price == 0.0]
            executed_closed = [t for t in closed if t.executed]
            shadow_only = [t for t in closed if not t.executed]

            avg_pnl_all = (
                sum(t.hypothetical_pnl_pct for t in closed) / len(closed)
                if closed else 0.0
            )
            avg_pnl_executed = (
                sum(t.hypothetical_pnl_pct for t in executed_closed) / len(executed_closed)
                if executed_closed else 0.0
            )
            avg_pnl_shadow = (
                sum(t.hypothetical_pnl_pct for t in shadow_only) / len(shadow_only)
                if shadow_only else 0.0
            )

            return {
                "shadow_trades_open": len(open_shadow),
                "shadow_trades_closed": len(closed),
                "executed_closed": len(executed_closed),
                "shadow_only_closed": len(shadow_only),
                "avg_hyp_pnl_pct_all": round(avg_pnl_all, 3),
                "avg_hyp_pnl_pct_executed": round(avg_pnl_executed, 3),
                "avg_hyp_pnl_pct_shadow_only": round(avg_pnl_shadow, 3),
            }

    # ------------------------------------------------------------------
    # Periodic reporting
    # ------------------------------------------------------------------

    def maybe_report_and_reset(self) -> None:
        """
        If REPORT_INTERVAL_SECS has elapsed, log a funnel summary for every
        active pair and reset all counters.  Thread-safe.
        """
        now = time.monotonic()
        if now - self._last_report_time < REPORT_INTERVAL_SECS:
            return

        with self._lock:
            if now - self._last_report_time < REPORT_INTERVAL_SECS:
                return  # double-check under lock

            stats_snapshot = list(self._stats.values())
            self._stats.clear()
            self._last_report_time = now

        if not stats_snapshot:
            logger.info("SIGNAL_FUNNEL: no pairs scanned in this window")
            return

        logger.info("=" * 60)
        logger.info("SIGNAL_FUNNEL_REPORT (last %.0fs):", REPORT_INTERVAL_SECS)
        for stat in sorted(stats_snapshot, key=lambda s: s.signals_seen, reverse=True):
            logger.info(stat.as_log_line())
        logger.info("=" * 60)

        # Also emit shadow-paper summary
        shadow = self.get_shadow_summary()
        logger.info(
            "SHADOW_PAPER_SUMMARY: open=%d closed=%d executed=%d shadow_only=%d "
            "avg_hyp_pnl=%.2f%% avg_executed_pnl=%.2f%% avg_shadow_pnl=%.2f%%",
            shadow["shadow_trades_open"],
            shadow["shadow_trades_closed"],
            shadow["executed_closed"],
            shadow["shadow_only_closed"],
            shadow["avg_hyp_pnl_pct_all"],
            shadow["avg_hyp_pnl_pct_executed"],
            shadow["avg_hyp_pnl_pct_shadow_only"],
        )

    def get_pair_stats(self, pair: str) -> FunnelStats:
        """Return a copy of the current funnel stats for a pair (read-only snapshot)."""
        with self._lock:
            s = self._stats.get(pair)
            if s is None:
                return FunnelStats(pair=pair)
            return FunnelStats(
                pair=s.pair,
                signals_seen=s.signals_seen,
                confidence_pass=s.confidence_pass,
                adx_pass=s.adx_pass,
                volume_pass=s.volume_pass,
                ai_gate_pass=s.ai_gate_pass,
                execution_pass=s.execution_pass,
            )

    def get_all_stats(self) -> List[FunnelStats]:
        """Return snapshots of all active pair stats."""
        with self._lock:
            return [
                FunnelStats(
                    pair=s.pair,
                    signals_seen=s.signals_seen,
                    confidence_pass=s.confidence_pass,
                    adx_pass=s.adx_pass,
                    volume_pass=s.volume_pass,
                    ai_gate_pass=s.ai_gate_pass,
                    execution_pass=s.execution_pass,
                )
                for s in self._stats.values()
            ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, pair: str) -> FunnelStats:
        """Return (or create) the FunnelStats entry for this pair. Caller holds lock."""
        if pair not in self._stats:
            self._stats[pair] = FunnelStats(pair=pair)
        return self._stats[pair]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[SignalFunnelDiagnostics] = None
_singleton_lock = threading.Lock()


def get_signal_funnel() -> SignalFunnelDiagnostics:
    """Return the process-level SignalFunnelDiagnostics singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = SignalFunnelDiagnostics()
                logger.info("SignalFunnelDiagnostics initialized (report every %.0fs)", REPORT_INTERVAL_SECS)
    return _singleton
