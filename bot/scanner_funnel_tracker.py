"""
NIJA Scanner Funnel Tracker
============================

Thread-safe rolling tracker for per-cycle alpha-generation metrics.

Captures ``candidates_found`` and ``symbols_scored`` each time the scanner
completes a cycle.  Maintains a configurable rolling window (default 576 cycles
≈ 24 h at 2.5-min intervals) and exposes aggregated statistics that allow the
operator to distinguish two root causes of zero-trade periods:

* **Generation scarcity** — low candidates despite scanning many symbols,
  meaning the market-scan or scoring layer is suppressing signals upstream of
  all filter stages.
* **Filter scarcity** — healthy raw candidates exist, but the rejection
  histogram is concentrated at one or two alpha-eligibility stages (e.g.
  ``smart_filter``, ``market_filter``), meaning the downstream filter gates
  are the bottleneck.

A **rollback signal** is computed from the rejection histogram on demand.  It
triggers when the ``drawdown_risk`` stage accounts for a disproportionate share
of recent rejections — an early-warning indicator that a gate relaxation has
admitted lower-quality signals that are now being blocked downstream.

Usage
-----
::

    from bot.scanner_funnel_tracker import get_scanner_funnel_tracker

    tracker = get_scanner_funnel_tracker()
    tracker.record(candidates_found=3, symbols_scored=200, regime="bull")

    summary = tracker.get_summary()
    # summary["median_candidates"]   — rolling median
    # summary["zero_pct"]            — fraction of zero-candidate cycles
    # summary["scarcity_type"]       — "generation", "filter", or "none"
    # summary["rollback_signal"]     — True when adverse quality spike detected

Author: NIJA Trading Systems
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants — all tunable via environment variables
# ---------------------------------------------------------------------------

import os

# Rolling window: how many recent cycles to consider.
# Default 576 ≈ 24 hours at 2.5-minute scan intervals.
_DEFAULT_WINDOW = int(os.getenv("NIJA_FUNNEL_WINDOW_CYCLES", "576"))

# A cycle is classified as "zero" when candidates < this threshold.
_ZERO_CANDIDATE_THRESHOLD = int(os.getenv("NIJA_FUNNEL_ZERO_THRESHOLD", "1"))

# Generation-scarcity: median candidates below this level with healthy scoring.
_GENERATION_SCARCITY_MEDIAN = float(os.getenv("NIJA_FUNNEL_GEN_SCARCITY_MEDIAN", "2.0"))

# Filter-scarcity: when the two dominant rejection stages are alpha-eligibility
# stages AND rejection volume is above this fraction of total rejections.
_FILTER_SCARCITY_ALPHA_PCT = float(os.getenv("NIJA_FUNNEL_FILTER_SCARCITY_PCT", "50.0"))

# Rollback-signal: drawdown_risk rejections form this fraction of total
# rejections (warning) or this value × 2 (critical).
_ROLLBACK_DRAWDOWN_WARNING_PCT = float(os.getenv("NIJA_FUNNEL_ROLLBACK_DRAWDOWN_PCT", "15.0"))

# Alpha-eligibility stage names used for filter-scarcity classification.
_ALPHA_STAGES = frozenset({
    "smart_filter",
    "market_filter",
    "min_notional",
    "trade_eligibility",
})


# ---------------------------------------------------------------------------
# Rolling-window statistics helper
# ---------------------------------------------------------------------------

def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
    """Return the *pct*-th percentile of a pre-sorted list, or None if empty."""
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = pct / 100.0 * (n - 1)
    lo, hi = int(idx), min(int(idx) + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


# ---------------------------------------------------------------------------
# Core tracker
# ---------------------------------------------------------------------------

class ScannerFunnelTracker:
    """
    Thread-safe rolling tracker for scanner alpha-generation quality.

    Call ``get_scanner_funnel_tracker()`` to obtain the process-wide singleton.
    """

    def __init__(self, window_cycles: int = _DEFAULT_WINDOW) -> None:
        self._window = max(1, window_cycles)
        self._lock = threading.Lock()
        # Per-cycle records: (candidates_found, symbols_scored, regime, ts)
        self._records: Deque[Tuple[int, int, str, float]] = deque(maxlen=self._window)
        self._window_start: float = time.time()
        self._total_cycles: int = 0

    # ------------------------------------------------------------------
    # Record API
    # ------------------------------------------------------------------

    def record(
        self,
        candidates_found: int,
        symbols_scored: int = 0,
        regime: str = "unknown",
    ) -> None:
        """
        Record one scan-cycle result.

        Args:
            candidates_found: Number of candidates above the hard floor after
                              scoring and volume-fallback injection.
            symbols_scored:   Total symbols that entered the scoring loop.
            regime:           Current market regime (informational).
        """
        ts = time.time()
        with self._lock:
            self._records.append((
                max(0, int(candidates_found)),
                max(0, int(symbols_scored)),
                str(regime or "unknown")[:32],
                ts,
            ))
            self._total_cycles += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """
        Return a structured summary of scanner funnel health.

        Returns::

            {
              "window_cycles":        576,
              "recorded_cycles":      <int>,
              "total_cycles_ever":    <int>,
              "window_seconds":       <elapsed>,
              "median_candidates":    <float>,
              "p25_candidates":       <float>,
              "p75_candidates":       <float>,
              "zero_pct":             <float>,   # 0–100
              "mean_symbols_scored":  <float>,
              "recent_regimes":       {...},      # regime → count
              "scarcity_type":        "generation" | "filter" | "none",
              "scarcity_details":     {...},
            }
        """
        with self._lock:
            records = list(self._records)
            total_ever = self._total_cycles
            window_start = self._window_start

        n = len(records)
        if n == 0:
            return {
                "window_cycles":       self._window,
                "recorded_cycles":     0,
                "total_cycles_ever":   total_ever,
                "window_seconds":      round(time.time() - window_start, 1),
                "median_candidates":   None,
                "p25_candidates":      None,
                "p75_candidates":      None,
                "zero_pct":            None,
                "mean_symbols_scored": None,
                "recent_regimes":      {},
                "scarcity_type":       "unknown",
                "scarcity_details":    {"reason": "no_data"},
            }

        candidates = sorted(r[0] for r in records)
        scored_vals = [r[1] for r in records]

        zero_count = sum(1 for v in candidates if v < _ZERO_CANDIDATE_THRESHOLD)
        zero_pct = round(zero_count / n * 100.0, 1)
        median_cand = _percentile(candidates, 50)
        p25 = _percentile(candidates, 25)
        p75 = _percentile(candidates, 75)
        mean_scored = round(sum(scored_vals) / n, 1)

        # Regime counts from recent records
        regime_counts: Dict[str, int] = {}
        for r in records:
            regime_counts[r[2]] = regime_counts.get(r[2], 0) + 1

        # Scarcity classification
        scarcity_type, scarcity_details = self._classify_scarcity(
            median_cand=float(median_cand) if median_cand is not None else 0.0,
            zero_pct=zero_pct,
            mean_scored=mean_scored,
        )

        return {
            "window_cycles":       self._window,
            "recorded_cycles":     n,
            "total_cycles_ever":   total_ever,
            "window_seconds":      round(time.time() - window_start, 1),
            "median_candidates":   round(float(median_cand), 2) if median_cand is not None else None,
            "p25_candidates":      round(float(p25), 2) if p25 is not None else None,
            "p75_candidates":      round(float(p75), 2) if p75 is not None else None,
            "zero_pct":            zero_pct,
            "mean_symbols_scored": mean_scored,
            "recent_regimes":      dict(sorted(regime_counts.items(), key=lambda kv: kv[1], reverse=True)),
            "scarcity_type":       scarcity_type,
            "scarcity_details":    scarcity_details,
        }

    # ------------------------------------------------------------------
    # Rollback-signal check
    # ------------------------------------------------------------------

    def check_rollback_signal(
        self,
        rejection_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate whether a gate-relaxation rollback is warranted.

        Pulls the current rejection histogram when *rejection_summary* is
        omitted.  Returns a dict with:

        * ``triggered``   — True when adverse quality signal is detected.
        * ``level``       — ``"warning"`` or ``"critical"`` or ``"ok"``.
        * ``drawdown_risk_pct`` — drawdown_risk share of total rejections.
        * ``message``     — human-readable explanation.
        """
        if rejection_summary is None:
            try:
                try:
                    from bot.rejection_histogram import get_rejection_histogram
                except ImportError:
                    from rejection_histogram import get_rejection_histogram  # type: ignore[import]
                rejection_summary = get_rejection_histogram().get_summary()
            except Exception:
                return {
                    "triggered": False,
                    "level": "ok",
                    "drawdown_risk_pct": 0.0,
                    "message": "rejection_histogram unavailable",
                }

        total = int(rejection_summary.get("total_rejections", 0))
        if total == 0:
            return {
                "triggered": False,
                "level": "ok",
                "drawdown_risk_pct": 0.0,
                "message": "no_rejections_recorded",
            }

        by_stage: Dict[str, int] = rejection_summary.get("by_stage", {})
        drawdown_count = int(by_stage.get("drawdown_risk", 0))
        drawdown_pct = round(drawdown_count / total * 100.0, 1)

        critical_threshold = _ROLLBACK_DRAWDOWN_WARNING_PCT * 2.0
        if drawdown_pct >= critical_threshold:
            return {
                "triggered": True,
                "level": "critical",
                "drawdown_risk_pct": drawdown_pct,
                "message": (
                    f"drawdown_risk={drawdown_pct}% of total rejections "
                    f"(≥ {critical_threshold}% critical threshold) — "
                    "consider reverting last gate relaxation immediately"
                ),
            }
        if drawdown_pct >= _ROLLBACK_DRAWDOWN_WARNING_PCT:
            return {
                "triggered": True,
                "level": "warning",
                "drawdown_risk_pct": drawdown_pct,
                "message": (
                    f"drawdown_risk={drawdown_pct}% of total rejections "
                    f"(≥ {_ROLLBACK_DRAWDOWN_WARNING_PCT}% warning threshold) — "
                    "monitor closely; consider pausing relaxation"
                ),
            }
        return {
            "triggered": False,
            "level": "ok",
            "drawdown_risk_pct": drawdown_pct,
            "message": f"drawdown_risk={drawdown_pct}% — within acceptable range",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _classify_scarcity(
        self,
        median_cand: float,
        zero_pct: float,
        mean_scored: float,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Classify the dominant scarcity source.

        Returns (scarcity_type, details_dict).
        """
        # No scarcity if candidates are consistently arriving
        if median_cand >= _GENERATION_SCARCITY_MEDIAN and zero_pct < 30.0:
            return "none", {"reason": "candidates_healthy"}

        # Try to determine whether the alpha-eligibility stages dominate
        alpha_pct = self._alpha_stage_pct()

        if alpha_pct is not None and alpha_pct >= _FILTER_SCARCITY_ALPHA_PCT:
            return "filter", {
                "reason": "alpha_stages_dominant",
                "alpha_stage_pct": round(alpha_pct, 1),
                "hint": "rejection_histogram dominated by alpha eligibility stages",
            }

        if median_cand < _GENERATION_SCARCITY_MEDIAN or zero_pct >= 50.0:
            return "generation", {
                "reason": "low_median_candidates",
                "median_candidates": round(median_cand, 2),
                "zero_pct": zero_pct,
                "mean_symbols_scored": mean_scored,
                "hint": (
                    "scanner produces few candidates; "
                    "consider relaxing NIJA_ELIGIBILITY_MIN_ATR_PCT or "
                    "NIJA_ELIGIBILITY_MAX_SPREAD_PCT"
                ),
            }

        return "none", {"reason": "borderline_monitor"}

    def _alpha_stage_pct(self) -> Optional[float]:
        """Return the share (0–100) of rejections in alpha-eligibility stages."""
        try:
            try:
                from bot.rejection_histogram import get_rejection_histogram
            except ImportError:
                from rejection_histogram import get_rejection_histogram  # type: ignore[import]
            summary = get_rejection_histogram().get_summary()
        except Exception:
            return None

        total = int(summary.get("total_rejections", 0))
        if total == 0:
            return None

        by_stage: Dict[str, int] = summary.get("by_stage", {})
        alpha_count = sum(by_stage.get(s, 0) for s in _ALPHA_STAGES)
        return alpha_count / total * 100.0

    def reset(self) -> None:
        """Reset all tracking data and begin a fresh measurement window."""
        with self._lock:
            self._records.clear()
            self._total_cycles = 0
            self._window_start = time.time()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_SINGLETON: Optional[ScannerFunnelTracker] = None
_SINGLETON_LOCK = threading.Lock()


def get_scanner_funnel_tracker() -> ScannerFunnelTracker:
    """Return the process-wide :class:`ScannerFunnelTracker` singleton."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = ScannerFunnelTracker()
    return _SINGLETON
