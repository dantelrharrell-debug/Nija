"""
Score Distribution Debugger
============================

Logs a per-cycle score histogram and, when zero signals are produced,
prints an exact root-cause breakdown showing *which* filter eliminated
every candidate symbol.

Typical output (every cycle):

    📊 Score Histogram — cycle 12 | 148 scored  37 skipped  0 entered
       🟢 ELITE  (≥75):  ██░░░░░░░░░░░░░░░░░░   2   1.4%
       🟡 GOOD  (50-74): ████░░░░░░░░░░░░░░░░   6   4.1%
       🟠 FAIR  (34-49): ██████░░░░░░░░░░░░░░  10   6.8%
       🔴 FLOOR (20-33): ████████░░░░░░░░░░░░  18  12.2%
       ⛔ <FLOOR  (<20): ████████████████████ 112  75.7%

    ⚠️  ZERO SIGNALS — root-cause breakdown:
       ├─  112 × scored below AI floor (20.0) — weak setup quality
       ├─   18 × passed floor but rejected by ranking/gate filters
       ├─   21 × insufficient candle data (df too short or missing)
       ├─   14 × blocked by market-direction filter (downtrend/sideways)
       └─    2 × indicator calculation failed

Integration
-----------
``nija_core_loop._phase3_scan_and_enter()``:

    debugger = _get_sdd()
    if debugger:
        debugger.start_cycle()
    ...
    if debugger:
        debugger.record_skip(symbol, "data_insufficient")
    ...
    if debugger:
        debugger.emit_histogram(entries_taken, candidates_found, rank_threshold)

``nija_ai_engine.evaluate_symbol()``:

    _sdd = _get_sdd()
    if _sdd is not None:
        _sdd.record_score(symbol, composite)

Environment variables
---------------------
NIJA_SCORE_DEBUG          Set to "0" to disable all output (default: enabled).
NIJA_SCORE_DEBUG_BAR_WIDTH Width of histogram bars in characters (default: 20).

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""
from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.score_debugger")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_ENABLED: bool = os.getenv("NIJA_SCORE_DEBUG", "1") not in ("0", "false", "False", "no")
_BAR_WIDTH: int = max(5, int(os.getenv("NIJA_SCORE_DEBUG_BAR_WIDTH", "20")))

# Score floor thresholds — kept in sync with nija_ai_engine.py TIER_* constants
# via the same env vars so the histogram always reflects the live tier boundaries.
_FLOOR_ELITE: float = float(os.getenv("NIJA_SCORE_FLOOR_ELITE", "75"))
_FLOOR_GOOD:  float = float(os.getenv("NIJA_SCORE_FLOOR_GOOD",  "50"))
_FLOOR_FAIR:  float = float(os.getenv("NIJA_SCORE_FLOOR_FAIR",  "48"))
_FLOOR_HARD:  float = 20.0   # absolute minimum — always fixed

# Score bins — derived from the floor constants so they never drift out of sync.
# FAIR is the critical "candidates just below GOOD" borderline band.
_BINS: List[Tuple[float, float, str, str]] = [
    (_FLOOR_ELITE, 101.0,        f"ELITE  (≥{_FLOOR_ELITE:.0f})  ", "🟢"),
    (_FLOOR_GOOD,  _FLOOR_ELITE, f"GOOD  ({_FLOOR_GOOD:.0f}–{_FLOOR_ELITE:.0f})", "🟡"),
    (_FLOOR_FAIR,  _FLOOR_GOOD,  f"FAIR  ({_FLOOR_FAIR:.0f}–{_FLOOR_GOOD:.0f}) ", "🟠"),
    (_FLOOR_HARD,  _FLOOR_FAIR,  f"FLOOR ({_FLOOR_HARD:.0f}–{_FLOOR_FAIR:.0f})", "🔴"),
    (0.0,          _FLOOR_HARD,  f"<FLOOR  (<{_FLOOR_HARD:.0f}) ",  "⛔"),
]

# Human-readable labels for skip reasons recorded by nija_core_loop.
_SKIP_LABELS: Dict[str, str] = {
    "data_insufficient": "insufficient candle data (df too short or missing)",
    "indicators_failed": "indicator calculation failed",
    "market_filter":     "blocked by market-direction filter (downtrend/sideways)",
    "exception":         "unhandled exception during symbol evaluation",
    "cap_reached":       "candidate cap reached (10× slots) — symbol not evaluated",
}


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class ScoreDistributionDebugger:
    """
    Thread-safe per-cycle score histogram and zero-signal root-cause reporter.

    Usage pattern (one instance shared across all modules via the singleton)::

        debugger = get_score_debugger()

        # Start of scan cycle:
        debugger.start_cycle()

        # For each symbol dropped before the AI engine:
        debugger.record_skip(symbol, "data_insufficient")

        # For each symbol that reached the AI engine (pass OR fail):
        debugger.record_score(symbol, composite_score)

        # End of scan cycle:
        debugger.emit_histogram(entries_taken, candidates_found, rank_threshold)
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cycle_num: int = 0
        # Per-cycle state (reset by start_cycle)
        self._scores: List[Tuple[str, float]] = []   # (symbol, composite_score)
        self._skip_counter: Counter = Counter()       # reason → count
        self._floor: float = 20.0                    # AI engine floor this cycle

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_cycle(self, floor: float = 20.0) -> None:
        """Reset per-cycle state.  Call at the very start of each scan cycle."""
        with self._lock:
            self._cycle_num += 1
            self._scores = []
            self._skip_counter = Counter()
            self._floor = floor

    def record_score(self, symbol: str, score: float) -> None:
        """
        Record a symbol that reached the AI engine and received a composite
        score (regardless of whether it passed the floor gate).
        """
        if not _ENABLED:
            return
        with self._lock:
            self._scores.append((symbol, float(score)))

    def record_skip(self, symbol: str, reason: str) -> None:
        """
        Record a symbol that was dropped *before* reaching the AI engine.

        Common reasons
        --------------
        ``"data_insufficient"``  — df is None or has < 100 candles
        ``"indicators_failed"``  — ``calculate_indicators`` returned nothing
        ``"market_filter"``      — ``check_market_filter`` blocked the symbol
        ``"exception"``          — unexpected exception in the scoring loop
        ``"cap_reached"``        — candidate cap (10× slots) hit; symbol not scored
        """
        if not _ENABLED:
            return
        with self._lock:
            self._skip_counter[reason] += 1

    def emit_histogram(
        self,
        entries_taken: int,
        candidates_found: int,
        rank_threshold: Optional[float] = None,
    ) -> None:
        """
        Emit the score histogram for this cycle.

        When ``entries_taken == 0``, also prints a root-cause breakdown that
        shows exactly which filter eliminated every candidate symbol.

        Parameters
        ----------
        entries_taken    : Number of trades actually executed this cycle.
        candidates_found : Number of symbols that survived the AI floor gate
                           and became ranking candidates.
        rank_threshold   : Score threshold used by ``rank_and_select``; pass
                           ``None`` if unavailable (e.g. no candidates existed).
        """
        if not _ENABLED:
            return

        with self._lock:
            scores_snapshot = list(self._scores)
            skip_snapshot   = dict(self._skip_counter)
            floor           = self._floor
            cycle           = self._cycle_num

        total_scored  = len(scores_snapshot)
        total_skipped = sum(skip_snapshot.values())

        # -- Bin the scores --------------------------------------------------
        bin_counts: List[int] = [0] * len(_BINS)
        for _, sc in scores_snapshot:
            for i, (lo, hi, _label, _emoji) in enumerate(_BINS):
                if lo <= sc < hi:
                    bin_counts[i] += 1
                    break

        # -- Header ----------------------------------------------------------
        logger.info(
            "📊 Score Histogram — cycle %d | %d scored  %d skipped  %d entered",
            cycle, total_scored, total_skipped, entries_taken,
        )

        if total_scored == 0 and total_skipped == 0:
            logger.info("   (no symbols evaluated this cycle)")
        else:
            # -- Histogram bars ----------------------------------------------
            max_count = max(bin_counts) if any(bin_counts) else 1
            for (lo, hi, label, emoji), count in zip(_BINS, bin_counts):
                pct    = (count / total_scored * 100.0) if total_scored > 0 else 0.0
                filled = round(_BAR_WIDTH * count / max_count) if max_count > 0 else 0
                bar    = "█" * filled + "░" * (_BAR_WIDTH - filled)
                logger.info(
                    "   %s %s  %s  %4d  %5.1f%%",
                    emoji, label, bar, count, pct,
                )

        # -- Zero-signal root-cause analysis ---------------------------------
        if entries_taken == 0:
            logger.warning("   ⚠️  ZERO SIGNALS — root-cause breakdown:")

            # Symbols below the AI floor (last bin = <floor)
            below_floor = bin_counts[-1] if bin_counts else 0

            # Symbols that passed the floor but were not selected for execution.
            # This covers rank_and_select dropping them or apex.analyze_market
            # returning "hold".
            above_floor_total = total_scored - below_floor
            ranked_out = max(0, above_floor_total - entries_taken)

            reasons: List[Tuple[int, str]] = []

            if below_floor:
                reasons.append((
                    below_floor,
                    f"scored below AI floor ({floor:.0f}) — weak setup quality",
                ))

            if ranked_out > 0:
                if rank_threshold is not None:
                    reasons.append((
                        ranked_out,
                        f"passed floor but below rank threshold ({rank_threshold:.0f}) "
                        "or blocked by market/gate filters",
                    ))
                else:
                    reasons.append((
                        ranked_out,
                        "passed floor but rejected by ranking/gate/market filters",
                    ))

            # Skip reasons from nija_core_loop (data issues, filter blocks, etc.)
            for reason, count in sorted(skip_snapshot.items(), key=lambda x: -x[1]):
                label = _SKIP_LABELS.get(reason, reason)
                reasons.append((count, label))

            if not reasons:
                logger.warning(
                    "   └─ no symbols were evaluated — check broker connectivity"
                )
            else:
                for idx, (count, label) in enumerate(reasons):
                    prefix = "└─" if idx == len(reasons) - 1 else "├─"
                    logger.warning("   %s %4d × %s", prefix, count, label)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------
_debugger: Optional[ScoreDistributionDebugger] = None
_debugger_lock = threading.Lock()


def get_score_debugger() -> Optional[ScoreDistributionDebugger]:
    """
    Return the module-level singleton :class:`ScoreDistributionDebugger`.

    Returns ``None`` when ``NIJA_SCORE_DEBUG=0`` so callers can guard with a
    simple ``if _sdd:`` check.
    """
    if not _ENABLED:
        return None
    global _debugger
    if _debugger is None:
        with _debugger_lock:
            if _debugger is None:
                _debugger = ScoreDistributionDebugger()
                logger.debug("ScoreDistributionDebugger singleton created")
    return _debugger
