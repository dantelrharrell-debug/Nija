"""
NIJA Rejection Histogram
========================

Thread-safe histogram of trade-candidate rejections across all filter stages.

Tracks why signals are blocked so operators can identify the dominant choke
point and prioritise threshold tuning.  Designed for zero-cost instrumentation:
every rejection in the pipeline calls ``record()`` and the data is available
on demand via ``get_summary()``.

Tracked dimensions
------------------
* **stage** — pipeline layer that issued the rejection:
    smart_filter, market_filter, min_notional, entry_gate,
    ai_gate (gate1–gate4), trade_validation, trade_eligibility, cooldown,
    drawdown_risk, safe_profit_mode, volatility_explosion, …
* **reason** — human-readable label supplied by the rejecting layer
* **regime** — active market regime at rejection time (informational)

Each (stage, reason) pair accumulates a counter.  Per-regime breakdowns are
stored under a nested ``by_regime`` dict so operators can see whether a
specific filter is only noisy in certain market conditions.

Usage
-----
::

    from bot.rejection_histogram import get_rejection_histogram

    hist = get_rejection_histogram()
    hist.record(stage="market_filter", reason="no_trend_signal", regime="ranging")

    summary = hist.get_summary(top_n=10)
    # summary["top_rejections"] — sorted list of (stage, reason, count)
    # summary["by_stage"]       — total count per stage
    # summary["by_regime"]      — total count per regime

Author: NIJA Trading Systems
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

_Key = Tuple[str, str]  # (stage, reason)


class RejectionHistogram:
    """
    Thread-safe rejection event histogram.

    Call ``get_rejection_histogram()`` to obtain the process-wide singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (stage, reason) → count
        self._counts: Dict[_Key, int] = defaultdict(int)
        # (stage, reason, regime) → count
        self._regime_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)
        # per-stage totals for fast summary
        self._stage_totals: Dict[str, int] = defaultdict(int)
        # per-regime totals
        self._regime_totals: Dict[str, int] = defaultdict(int)
        self._total: int = 0
        self._window_start: float = time.time()

    # ------------------------------------------------------------------
    # Record API
    # ------------------------------------------------------------------

    def record(
        self,
        stage: str,
        reason: str,
        regime: str = "unknown",
    ) -> None:
        """
        Record one rejection event.

        Args:
            stage:  Pipeline layer that rejected the candidate
                    (e.g. ``"market_filter"``, ``"ai_gate"``, …).
            reason: Short label for the specific rejection cause
                    (e.g. ``"no_trend_signal"``, ``"low_ai_score"``).
            regime: Active market regime (informational; default ``"unknown"``).
        """
        stage  = (stage  or "unknown")[:64]
        reason = (reason or "unknown")[:128]
        regime = (regime or "unknown")[:32]

        with self._lock:
            self._counts[(stage, reason)] += 1
            self._regime_counts[(stage, reason, regime)] += 1
            self._stage_totals[stage] += 1
            self._regime_totals[regime] += 1
            self._total += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self, top_n: int = 20) -> Dict[str, Any]:
        """
        Return a structured summary of rejection activity.

        Returns::

            {
              "window_start":     <unix ts>,
              "window_seconds":   <elapsed>,
              "total_rejections": <int>,
              "top_rejections":   [
                  {"stage": ..., "reason": ..., "count": ..., "pct": ...},
                  ...   (top_n entries, sorted by count desc)
              ],
              "by_stage":  {"market_filter": 120, ...},
              "by_regime": {"ranging": 80, ...},
              "by_stage_and_reason": {
                  "market_filter": [
                      {"reason": "no_trend", "count": 60, "by_regime": {...}},
                  ],
                  ...
              }
            }
        """
        with self._lock:
            counts       = dict(self._counts)
            regime_counts = dict(self._regime_counts)
            stage_totals  = dict(self._stage_totals)
            regime_totals = dict(self._regime_totals)
            total         = self._total
            window_start  = self._window_start

        # Top N (stage, reason) pairs
        sorted_pairs = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        top_rejections: List[Dict[str, Any]] = []
        for (stage, reason), count in sorted_pairs[:top_n]:
            pct = round(count / total * 100.0, 1) if total > 0 else 0.0
            top_rejections.append({
                "stage":  stage,
                "reason": reason,
                "count":  count,
                "pct":    pct,
            })

        # Nested by_stage_and_reason
        stage_detail: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for (stage, reason), count in sorted_pairs:
            # Collect per-regime breakdown for this (stage, reason) pair
            by_regime_sub: Dict[str, int] = {}
            for (s, r, regime), rc in regime_counts.items():
                if s == stage and r == reason:
                    by_regime_sub[regime] = rc
            stage_detail[stage].append({
                "reason":    reason,
                "count":     count,
                "by_regime": by_regime_sub,
            })

        return {
            "window_start":          window_start,
            "window_seconds":        round(time.time() - window_start, 1),
            "total_rejections":      total,
            "top_rejections":        top_rejections,
            "by_stage":              dict(sorted(
                stage_totals.items(), key=lambda kv: kv[1], reverse=True
            )),
            "by_regime":             dict(sorted(
                regime_totals.items(), key=lambda kv: kv[1], reverse=True
            )),
            "by_stage_and_reason":   dict(stage_detail),
        }

    def reset(self) -> None:
        """Reset all counters and begin a fresh measurement window."""
        with self._lock:
            self._counts.clear()
            self._regime_counts.clear()
            self._stage_totals.clear()
            self._regime_totals.clear()
            self._total = 0
            self._window_start = time.time()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_SINGLETON: Optional[RejectionHistogram] = None
_SINGLETON_LOCK = threading.Lock()


def get_rejection_histogram() -> RejectionHistogram:
    """Return the process-wide singleton :class:`RejectionHistogram`."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = RejectionHistogram()
    return _SINGLETON
