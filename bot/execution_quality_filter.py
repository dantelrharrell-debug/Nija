"""
NIJA Execution Quality Filter
================================

AI-driven pre-trade gate that scores an incoming trade request against
historical execution quality for the same symbol × broker pair and
against live broker health.  Returns an APPROVE / DEFER / REJECT verdict
before the order is dispatched.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────┐
  │                ExecutionQualityFilter                        │
  │                                                              │
  │  filter_trade(symbol, broker, side, size_usd, urgency, ...)  │
  │      │                                                       │
  │      ├─ 1. Broker composite score  (BrokerPerformanceScorer) │
  │      ├─ 2. Local fill rate         (symbol × broker history) │
  │      ├─ 3. Local avg slippage      (symbol × broker history) │
  │      ├─ 4. Liquidity quality       (volume vs rolling mean)  │
  │      └─ 5. Time-of-day factor      (UTC hour penalty)        │
  │                                                              │
  │  Composite quality score (0–100)                             │
  │      ≥ APPROVE_THRESHOLD  → APPROVE                          │
  │      ≥ DEFER_THRESHOLD    → DEFER (with back-off delay)      │
  │      <  DEFER_THRESHOLD   → REJECT                           │
  │                                                              │
  │  Urgency override: high-urgency trades bypass DEFER → APPROVE │
  └──────────────────────────────────────────────────────────────┘

Factor Weights (defaults)
--------------------------
  Broker composite score    35 %
  Local fill rate           25 %
  Local slippage quality    20 %
  Liquidity quality         15 %
  Time-of-day factor         5 %

Verdict Thresholds (defaults)
------------------------------
  APPROVE_THRESHOLD   65 / 100
  DEFER_THRESHOLD     40 / 100

Usage
-----
::

    from bot.execution_quality_filter import (
        get_execution_quality_filter,
        FilterVerdict,
    )

    eqf = get_execution_quality_filter()

    # Before sending an order:
    decision = eqf.filter_trade(
        symbol="BTC-USD",
        broker="coinbase",
        side="buy",
        size_usd=500.0,
        urgency=0.4,
        market_volume_usd=1_200_000.0,
    )

    if decision.verdict == FilterVerdict.APPROVE:
        submit_order(...)
    elif decision.verdict == FilterVerdict.DEFER:
        schedule_retry(delay_seconds=decision.defer_seconds)
    else:
        logger.warning("Trade rejected: %s", decision.reason)

    # Feed back actual execution outcomes to improve future decisions:
    eqf.record_execution(
        symbol="BTC-USD",
        broker="coinbase",
        success=True,
        slippage_bps=1.4,
        latency_ms=95.0,
    )

    # Per-pair quality snapshot:
    score = eqf.get_symbol_quality("BTC-USD", "coinbase")

    # Full dashboard:
    print(eqf.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.execution_quality_filter")

# ---------------------------------------------------------------------------
# Optional: BrokerPerformanceScorer
# ---------------------------------------------------------------------------

try:
    from bot.broker_performance_scorer import get_broker_performance_scorer
    _BPS_AVAILABLE = True
except ImportError:
    try:
        from broker_performance_scorer import get_broker_performance_scorer
        _BPS_AVAILABLE = True
    except ImportError:
        _BPS_AVAILABLE = False
        get_broker_performance_scorer = None  # type: ignore
        logger.warning(
            "⚠️  BrokerPerformanceScorer not available — "
            "execution quality filter will use fallback broker scores"
        )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rolling history size per (symbol, broker) pair
DEFAULT_HISTORY_WINDOW: int = 50

# Default verdict thresholds
DEFAULT_APPROVE_THRESHOLD: float = 65.0
DEFAULT_DEFER_THRESHOLD: float   = 40.0

# Slippage ceiling used to normalise local slippage sub-score (bps)
SLIPPAGE_CEILING_BPS: float = 30.0

# Volume ratio for liquidity quality: ratio of current_volume / mean_volume
# A ratio ≥ 1.0 receives full score; below this it is penalised linearly.
LIQUIDITY_FLOOR_RATIO: float = 0.10  # at or below this the liquidity score = 0

# UTC hours considered "low liquidity" (0–4 inclusive)
_LOW_LIQUIDITY_HOURS: frozenset = frozenset(range(0, 5))  # 00:00–04:59 UTC
_LOW_LIQUIDITY_PENALTY: float   = 0.80  # multiply time-of-day score by this

# Factor weights (must sum to 1.0)
W_BROKER_SCORE:    float = 0.35
W_LOCAL_FILL:      float = 0.25
W_LOCAL_SLIPPAGE:  float = 0.20
W_LIQUIDITY:       float = 0.15
W_TIME_OF_DAY:     float = 0.05

# Urgency threshold above which a DEFER verdict is upgraded to APPROVE
URGENCY_DEFER_OVERRIDE: float = 0.75

# Defer back-off parameters
_DEFER_BASE_SECONDS:  int = 30
_DEFER_MAX_SECONDS:   int = 300

# Maximum tracked (symbol, broker) pairs (LRU eviction when exceeded)
MAX_TRACKED_PAIRS: int = 500


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class FilterVerdict(str, Enum):
    """Pre-trade filter decision."""
    APPROVE = "approve"
    DEFER   = "defer"
    REJECT  = "reject"


@dataclass
class ExecutionObservation:
    """One recorded execution outcome for a (symbol, broker) pair."""
    timestamp:    str
    success:      bool
    slippage_bps: float   # ≥ 0; 0.0 if unknown
    latency_ms:   float   # ≥ 0


@dataclass
class FilterDecision:
    """
    Result of a single ``filter_trade()`` call.

    Attributes
    ----------
    symbol:
        Trading pair evaluated.
    broker:
        Broker / exchange evaluated.
    verdict:
        :class:`FilterVerdict` — APPROVE, DEFER, or REJECT.
    quality_score:
        Composite quality score 0–100 used to reach the verdict.
    score_breakdown:
        Per-factor scores contributing to *quality_score*.
    defer_seconds:
        Back-off delay in seconds (only meaningful when verdict is DEFER).
    reason:
        Human-readable explanation.
    suggested_broker:
        Alternative broker to consider when broker health is the main drag.
    """
    symbol:           str
    broker:           str
    verdict:          FilterVerdict
    quality_score:    float
    score_breakdown:  Dict[str, float]
    defer_seconds:    int
    reason:           str
    suggested_broker: Optional[str] = None


# ---------------------------------------------------------------------------
# Per-pair history store
# ---------------------------------------------------------------------------


class _PairHistory:
    """Rolling history for a single (symbol, broker) pair."""

    __slots__ = ("_window", "_obs", "last_access_ts")

    def __init__(self, window: int) -> None:
        self._window = window
        self._obs: Deque[ExecutionObservation] = deque(maxlen=window)
        self.last_access_ts: float = 0.0

    def record(self, obs: ExecutionObservation) -> None:
        import time as _time
        self._obs.append(obs)
        self.last_access_ts = _time.monotonic()

    @property
    def count(self) -> int:
        return len(self._obs)

    def fill_rate(self) -> float:
        """Fraction of successful fills (0–1). Returns 1.0 when empty."""
        if not self._obs:
            return 1.0
        return sum(1 for o in self._obs if o.success) / len(self._obs)

    def avg_slippage_bps(self) -> float:
        """Mean slippage in basis points. Returns 0.0 when empty."""
        slippages = [o.slippage_bps for o in self._obs if o.slippage_bps >= 0]
        return sum(slippages) / len(slippages) if slippages else 0.0


# ---------------------------------------------------------------------------
# ExecutionQualityFilter
# ---------------------------------------------------------------------------


class ExecutionQualityFilter:
    """
    AI-driven pre-trade gate based on historical execution quality.

    Thread-safe; process-wide singleton via ``get_execution_quality_filter()``.

    Parameters
    ----------
    history_window:
        Number of recent executions tracked per (symbol, broker) pair.
    approve_threshold:
        Minimum composite quality score to APPROVE a trade (default 65).
    defer_threshold:
        Minimum score to DEFER a trade; below this the trade is REJECTED
        (default 40).
    """

    def __init__(
        self,
        history_window:   int   = DEFAULT_HISTORY_WINDOW,
        approve_threshold: float = DEFAULT_APPROVE_THRESHOLD,
        defer_threshold:   float = DEFAULT_DEFER_THRESHOLD,
    ) -> None:
        if not (0.0 <= defer_threshold < approve_threshold <= 100.0):
            raise ValueError(
                "Thresholds must satisfy 0 ≤ defer_threshold < "
                "approve_threshold ≤ 100"
            )

        self._lock             = threading.Lock()
        self._window           = history_window
        self._approve_thresh   = approve_threshold
        self._defer_thresh     = defer_threshold

        # (symbol, broker) → _PairHistory
        self._histories: Dict[Tuple[str, str], _PairHistory] = {}

        # Per-symbol rolling volume window for liquidity estimation
        self._volume_window: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=20)
        )

        # Filter decision stats
        self._stats: Dict[str, int] = {
            "total_evaluated": 0,
            "approved": 0,
            "deferred": 0,
            "rejected": 0,
        }

        logger.info("=" * 70)
        logger.info("🧠 ExecutionQualityFilter initialised")
        logger.info(
            "   approve_threshold=%.0f  defer_threshold=%.0f  window=%d",
            approve_threshold, defer_threshold, history_window,
        )
        logger.info(
            "   weights: broker=%.0f%%  fill=%.0f%%  "
            "slippage=%.0f%%  liquidity=%.0f%%  tod=%.0f%%",
            W_BROKER_SCORE * 100, W_LOCAL_FILL * 100,
            W_LOCAL_SLIPPAGE * 100, W_LIQUIDITY * 100, W_TIME_OF_DAY * 100,
        )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API — pre-trade gate
    # ------------------------------------------------------------------

    def filter_trade(
        self,
        symbol:           str,
        broker:           str,
        side:             str,
        size_usd:         float,
        urgency:          float = 0.5,
        market_volume_usd: Optional[float] = None,
    ) -> FilterDecision:
        """
        Evaluate an incoming trade request and return a filter decision.

        Parameters
        ----------
        symbol:
            Trading pair, e.g. ``"BTC-USD"``.
        broker:
            Broker / exchange the order would be sent to.
        side:
            ``"buy"`` or ``"sell"`` (informational; affects logging only).
        size_usd:
            Notional order value in USD (used for risk-scaled reasoning).
        urgency:
            Caller-supplied urgency 0–1.  Values ≥ ``URGENCY_DEFER_OVERRIDE``
            (0.75) upgrade a DEFER verdict to APPROVE.
        market_volume_usd:
            Current market volume in USD.  Used to compute liquidity quality.
            If ``None``, the liquidity factor defaults to full (100 %).

        Returns
        -------
        :class:`FilterDecision`
        """
        urgency = max(0.0, min(1.0, urgency))

        with self._lock:
            key  = (symbol, broker)
            hist = self._histories.get(key)

            # Update rolling volume window
            if market_volume_usd is not None and market_volume_usd > 0:
                self._volume_window[symbol].append(market_volume_usd)

            vol_window = list(self._volume_window.get(symbol, []))

        # ── 1. Broker composite score (0–100) ────────────────────────
        broker_score = self._get_broker_score(broker)

        # ── 2. Local fill rate (0–1 → scaled to 0–100) ──────────────
        if hist and hist.count >= 3:
            fill_rate_raw = hist.fill_rate()
        else:
            fill_rate_raw = 1.0   # full score when no history
        local_fill_score = fill_rate_raw * 100.0

        # ── 3. Local slippage quality (0–100, higher = less slippage) ──
        if hist and hist.count >= 3:
            avg_slip = hist.avg_slippage_bps()
        else:
            avg_slip = 0.0
        slippage_score = max(
            0.0, (1.0 - avg_slip / SLIPPAGE_CEILING_BPS) * 100.0
        )

        # ── 4. Liquidity quality (0–100) ─────────────────────────────
        liquidity_score = self._compute_liquidity_score(
            market_volume_usd, vol_window
        )

        # ── 5. Time-of-day factor (0–100) ────────────────────────────
        tod_score = self._compute_time_of_day_score()

        # ── Weighted composite ────────────────────────────────────────
        quality_score = (
            W_BROKER_SCORE   * broker_score
            + W_LOCAL_FILL   * local_fill_score
            + W_LOCAL_SLIPPAGE * slippage_score
            + W_LIQUIDITY    * liquidity_score
            + W_TIME_OF_DAY  * tod_score
        )
        quality_score = max(0.0, min(100.0, quality_score))

        breakdown = {
            "broker_score":     round(broker_score, 1),
            "local_fill_score": round(local_fill_score, 1),
            "slippage_score":   round(slippage_score, 1),
            "liquidity_score":  round(liquidity_score, 1),
            "tod_score":        round(tod_score, 1),
        }

        # ── Verdict ───────────────────────────────────────────────────
        verdict, defer_secs, reason = self._compute_verdict(
            quality_score, urgency, breakdown
        )

        # ── Broker recommendation ─────────────────────────────────────
        suggested_broker = self._suggest_broker(broker, broker_score, quality_score)

        decision = FilterDecision(
            symbol=symbol,
            broker=broker,
            verdict=verdict,
            quality_score=round(quality_score, 2),
            score_breakdown=breakdown,
            defer_seconds=defer_secs,
            reason=reason,
            suggested_broker=suggested_broker,
        )

        with self._lock:
            self._stats["total_evaluated"] += 1
            _verdict_key = {
                FilterVerdict.APPROVE: "approved",
                FilterVerdict.DEFER:   "deferred",
                FilterVerdict.REJECT:  "rejected",
            }.get(verdict, "approved")
            self._stats[_verdict_key] = self._stats.get(_verdict_key, 0) + 1

        logger.debug(
            "🔍 %s %s %s $%.0f | quality=%.1f | verdict=%s | %s",
            side.upper(), symbol, broker, size_usd,
            quality_score, verdict.value.upper(), reason,
        )

        return decision

    # ------------------------------------------------------------------
    # Public API — feedback
    # ------------------------------------------------------------------

    def record_execution(
        self,
        symbol:       str,
        broker:       str,
        success:      bool,
        slippage_bps: float = 0.0,
        latency_ms:   float = 0.0,
    ) -> None:
        """
        Record the outcome of a completed execution.

        Call this after every order attempt — both successes and failures —
        to keep the quality model current.

        Parameters
        ----------
        symbol:       Trading pair.
        broker:       Broker used.
        success:      ``True`` if the order filled without error.
        slippage_bps: Observed slippage in basis points (0 if unknown).
        latency_ms:   End-to-end latency in milliseconds.
        """
        obs = ExecutionObservation(
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=success,
            slippage_bps=max(0.0, slippage_bps),
            latency_ms=max(0.0, latency_ms),
        )

        with self._lock:
            key = (symbol, broker)
            if key not in self._histories:
                if len(self._histories) >= MAX_TRACKED_PAIRS:
                    # LRU eviction: remove the pair that was accessed least recently
                    oldest = min(
                        self._histories,
                        key=lambda k: self._histories[k].last_access_ts,
                    )
                    del self._histories[oldest]
                self._histories[key] = _PairHistory(self._window)
            self._histories[key].record(obs)

        logger.debug(
            "📝 ExecQuality recorded: %s@%s | success=%s slip=%.2fbps lat=%.0fms",
            symbol, broker, success, slippage_bps, latency_ms,
        )

    # ------------------------------------------------------------------
    # Public API — queries
    # ------------------------------------------------------------------

    def get_symbol_quality(self, symbol: str, broker: str) -> float:
        """
        Return the current composite quality score (0–100) for the
        (symbol, broker) pair based on local history and live broker health.

        Returns 100.0 when no history is available (neutral/new pair).
        """
        with self._lock:
            hist = self._histories.get((symbol, broker))

        broker_score   = self._get_broker_score(broker)
        fill_score     = (hist.fill_rate() if hist and hist.count >= 3 else 1.0) * 100.0
        slip_score     = max(
            0.0,
            (1.0 - (hist.avg_slippage_bps() if hist and hist.count >= 3 else 0.0)
             / SLIPPAGE_CEILING_BPS) * 100.0,
        )

        return round(
            W_BROKER_SCORE * broker_score
            + W_LOCAL_FILL * fill_score
            + W_LOCAL_SLIPPAGE * slip_score
            + (W_LIQUIDITY + W_TIME_OF_DAY) * 100.0,   # neutral for static query
            2,
        )

    def get_all_pair_stats(self) -> List[Dict[str, Any]]:
        """Return quality stats for all tracked (symbol, broker) pairs."""
        rows = []
        with self._lock:
            pairs = list(self._histories.items())
        for (sym, brk), hist in sorted(pairs, key=lambda x: x[0]):
            rows.append({
                "symbol":           sym,
                "broker":           brk,
                "observations":     hist.count,
                "fill_rate":        round(hist.fill_rate(), 4),
                "avg_slippage_bps": round(hist.avg_slippage_bps(), 3),
                "quality_score":    self.get_symbol_quality(sym, brk),
            })
        return rows

    def get_stats(self) -> Dict[str, int]:
        """Return aggregate filter decision statistics."""
        with self._lock:
            return dict(self._stats)

    def get_report(self) -> str:
        """Return a human-readable quality summary for all tracked pairs."""
        rows = self.get_all_pair_stats()
        lines = [
            "=" * 80,
            "  NIJA EXECUTION QUALITY FILTER — PAIR QUALITY REPORT",
            "=" * 80,
            f"  {'Symbol':<20} {'Broker':<20} {'Obs':>5} "
            f"{'FillOK':>7} {'Slip(bp)':>9} {'QScore':>8}",
            "-" * 80,
        ]
        for r in rows:
            lines.append(
                f"  {r['symbol']:<20} {r['broker']:<20} "
                f"{r['observations']:>5} "
                f"{r['fill_rate'] * 100:>6.1f}% "
                f"{r['avg_slippage_bps']:>8.2f} "
                f"{r['quality_score']:>8.1f}"
            )
        with self._lock:
            stats = dict(self._stats)
        lines += [
            "-" * 80,
            f"  Totals: evaluated={stats['total_evaluated']}  "
            f"approved={stats.get('approved', 0)}  "
            f"deferred={stats.get('deferred', 0)}  "
            f"rejected={stats.get('rejected', 0)}",
            f"  Thresholds: approve≥{self._approve_thresh:.0f}  "
            f"defer≥{self._defer_thresh:.0f}  "
            f"(reject below {self._defer_thresh:.0f})",
            "=" * 80,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_broker_score(self, broker: str) -> float:
        """Fetch composite broker score (0–100) from BrokerPerformanceScorer."""
        if _BPS_AVAILABLE:
            try:
                return get_broker_performance_scorer().get_score(broker)
            except Exception:
                pass
        return 50.0   # neutral fallback

    @staticmethod
    def _compute_liquidity_score(
        current_vol: Optional[float],
        vol_window: List[float],
    ) -> float:
        """
        Compute a 0–100 liquidity quality score.

        Compares *current_vol* to the rolling mean of the *vol_window*.
        Returns 100 when current volume meets or exceeds the historical mean,
        scaling down to 0 at ``LIQUIDITY_FLOOR_RATIO`` × mean.
        """
        if current_vol is None or current_vol <= 0 or not vol_window:
            return 100.0   # neutral when no data

        mean_vol = sum(vol_window) / len(vol_window)
        if mean_vol <= 0:
            return 100.0

        ratio = current_vol / mean_vol
        if ratio >= 1.0:
            return 100.0
        if ratio <= LIQUIDITY_FLOOR_RATIO:
            return 0.0

        # Linear interpolation between floor and 1.0
        return ((ratio - LIQUIDITY_FLOOR_RATIO)
                / (1.0 - LIQUIDITY_FLOOR_RATIO)) * 100.0

    @staticmethod
    def _compute_time_of_day_score() -> float:
        """
        Return a 0–100 time-of-day quality factor.

        UTC hours 00:00–04:59 (low-liquidity window) receive a penalty;
        all other hours return 100.
        """
        hour = datetime.now(timezone.utc).hour
        if hour in _LOW_LIQUIDITY_HOURS:
            return 100.0 * _LOW_LIQUIDITY_PENALTY
        return 100.0

    def _compute_verdict(
        self,
        quality_score: float,
        urgency: float,
        breakdown: Dict[str, float],
    ) -> Tuple[FilterVerdict, int, str]:
        """
        Map *quality_score* + *urgency* to a :class:`FilterVerdict`.

        Returns (verdict, defer_seconds, reason).
        """
        if quality_score >= self._approve_thresh:
            return (
                FilterVerdict.APPROVE,
                0,
                f"quality={quality_score:.1f} ≥ approve_threshold={self._approve_thresh:.0f}",
            )

        if quality_score >= self._defer_thresh:
            # High-urgency override: promote DEFER → APPROVE
            if urgency >= URGENCY_DEFER_OVERRIDE:
                return (
                    FilterVerdict.APPROVE,
                    0,
                    f"quality={quality_score:.1f} in defer range but urgency={urgency:.2f} "
                    f"≥ override_threshold={URGENCY_DEFER_OVERRIDE:.2f} — approved",
                )

            # Compute back-off delay proportional to score deficit
            deficit_fraction = (
                (self._approve_thresh - quality_score)
                / (self._approve_thresh - self._defer_thresh)
            )
            defer_secs = int(
                _DEFER_BASE_SECONDS
                + deficit_fraction * (_DEFER_MAX_SECONDS - _DEFER_BASE_SECONDS)
            )
            worst_factor = min(breakdown, key=breakdown.get)
            return (
                FilterVerdict.DEFER,
                defer_secs,
                f"quality={quality_score:.1f} in defer range — "
                f"retry in {defer_secs}s (weak factor: {worst_factor}={breakdown[worst_factor]:.1f})",
            )

        worst_factor = min(breakdown, key=breakdown.get)
        return (
            FilterVerdict.REJECT,
            0,
            f"quality={quality_score:.1f} < reject_threshold={self._defer_thresh:.0f} "
            f"(weak factor: {worst_factor}={breakdown[worst_factor]:.1f})",
        )

    def _suggest_broker(
        self,
        current_broker: str,
        broker_score: float,
        quality_score: float,
    ) -> Optional[str]:
        """
        Suggest an alternative broker when broker health is the main bottleneck.

        Returns ``None`` when no better alternative is visible or when the
        quality score is already adequate.
        """
        if quality_score >= self._approve_thresh:
            return None
        if not _BPS_AVAILABLE:
            return None
        try:
            scorer = get_broker_performance_scorer()
            all_snaps = scorer.get_all_snapshots()
            better = [
                s.broker for s in all_snaps
                if s.broker != current_broker
                and s.composite_score > broker_score + 5.0   # meaningfully better
                and not s.insufficient_data
            ]
            return better[0] if better else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExecutionQualityFilter] = None
_instance_lock = threading.Lock()


def get_execution_quality_filter(**kwargs) -> ExecutionQualityFilter:
    """
    Return the process-wide :class:`ExecutionQualityFilter` singleton.

    Keyword arguments are forwarded to the constructor on the first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ExecutionQualityFilter(**kwargs)
    return _instance


__all__ = [
    "FilterVerdict",
    "ExecutionObservation",
    "FilterDecision",
    "ExecutionQualityFilter",
    "get_execution_quality_filter",
]


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if _BPS_AVAILABLE:
        scorer = get_broker_performance_scorer()
        random.seed(7)
        for _ in range(25):
            for bname, fill_p, lat_mu, slip_mu in [
                ("coinbase", 0.97, 75,  1.0),
                ("kraken",   0.85, 140, 3.0),
            ]:
                ok = random.random() < fill_p
                scorer.record_order_result(
                    bname, ok,
                    latency_ms=max(0, random.gauss(lat_mu, 20)),
                    slippage_bps=max(0, random.gauss(slip_mu, 0.5)),
                )

    eqf = ExecutionQualityFilter()

    # Seed some local history for BTC-USD @ coinbase
    random.seed(42)
    for _ in range(20):
        eqf.record_execution(
            "BTC-USD", "coinbase",
            success=random.random() < 0.97,
            slippage_bps=max(0, random.gauss(1.2, 0.4)),
            latency_ms=max(0, random.gauss(80, 15)),
        )

    # And worse history for a low-quality pair
    for _ in range(10):
        eqf.record_execution(
            "SHIB-USD", "kraken",
            success=random.random() < 0.60,
            slippage_bps=max(0, random.gauss(15, 5)),
            latency_ms=max(0, random.gauss(300, 80)),
        )

    print("\n--- filter_trade: BTC-USD @ coinbase (good pair) ---")
    d = eqf.filter_trade("BTC-USD", "coinbase", "buy", 500.0, urgency=0.4,
                         market_volume_usd=1_500_000.0)
    print(f"  verdict={d.verdict.value}  score={d.quality_score}  reason={d.reason}")

    print("\n--- filter_trade: SHIB-USD @ kraken (low quality) ---")
    d2 = eqf.filter_trade("SHIB-USD", "kraken", "buy", 500.0, urgency=0.3,
                          market_volume_usd=50_000.0)
    print(f"  verdict={d2.verdict.value}  score={d2.quality_score}  reason={d2.reason}")
    if d2.suggested_broker:
        print(f"  suggested_broker={d2.suggested_broker}")

    print("\n--- filter_trade: low quality but high urgency (DEFER→APPROVE) ---")
    d3 = eqf.filter_trade("SHIB-USD", "kraken", "sell", 100.0, urgency=0.9)
    print(f"  verdict={d3.verdict.value}  score={d3.quality_score}  reason={d3.reason}")

    print("\n" + eqf.get_report())
    print("✅ Smoke-test complete.")
