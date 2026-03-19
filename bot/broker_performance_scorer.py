"""
NIJA Broker Performance Scorer
================================

Tracks live reliability metrics for every registered broker / exchange and
exposes a composite performance score (0–100) that the execution router uses
to automatically route trades to the most dependable venue.

Architecture
------------
::

  ┌────────────────────────────────────────────────────────────────┐
  │                  BrokerPerformanceScorer                       │
  │                                                                │
  │  Per-broker rolling window (configurable, default 100 events): │
  │                                                                │
  │  • Fill Success Rate  – fraction of orders that filled OK      │
  │  • API Latency p95    – 95th-percentile round-trip ms          │
  │  • Slippage           – average observed slippage (bps)        │
  │  • Rejection Rate     – fraction of orders rejected by venue   │
  │  • Connectivity       – fraction of API calls that returned    │
  │                                                                │
  │  Composite Score (0–100) = weighted EMA of normalised metrics  │
  │                                                                │
  │  Weights (defaults):                                           │
  │    fill_success_rate  30 %                                     │
  │    latency_p95        25 %                                     │
  │    slippage           20 %                                     │
  │    rejection_rate     15 %                                     │
  │    connectivity       10 %                                     │
  │                                                                │
  │  Audit: score changes logged via standard logging              │
  └────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.broker_performance_scorer import get_broker_performance_scorer

    scorer = get_broker_performance_scorer()

    # After every order attempt:
    scorer.record_order_result(
        broker="coinbase",
        success=True,
        latency_ms=84.0,
        slippage_bps=1.2,
        error=None,
    )

    # Before selecting a broker — pick the best candidate:
    best = scorer.get_best_broker(["coinbase", "kraken", "binance"])
    # → "coinbase"  (highest composite score among the three)

    # Inspect scores:
    print(scorer.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("nija.broker_performance_scorer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW: int = 100           # rolling observation window per broker
DEFAULT_MIN_OBSERVATIONS: int = 5   # observations needed before scoring
DEFAULT_EMA_ALPHA: float = 0.15     # EMA smoothing for composite score

# Latency normalisation ceiling (ms) — above this the latency sub-score = 0
LATENCY_CEILING_MS: float = 2_000.0

# Slippage normalisation ceiling (bps) — above this the slippage sub-score = 0
SLIPPAGE_CEILING_BPS: float = 50.0

# Default composite score for brokers with insufficient data
DEFAULT_SCORE: float = 50.0

# Constituent weights (must sum to 1.0)
W_FILL_SUCCESS: float = 0.30
W_LATENCY: float = 0.25
W_SLIPPAGE: float = 0.20
W_REJECTION: float = 0.15
W_CONNECTIVITY: float = 0.10


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class OrderObservation:
    """A single recorded order event for one broker."""

    success: bool           # order filled without error
    latency_ms: float       # end-to-end round-trip time
    slippage_bps: float     # observed slippage in basis points (0 if unknown)
    rejected: bool          # True when the venue actively rejected the order
    connected: bool         # False when a connectivity/network error occurred
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class BrokerScoreSnapshot:
    """Point-in-time performance snapshot for one broker."""

    broker: str
    composite_score: float          # 0–100; higher = more reliable
    fill_success_rate: float        # 0–1
    rejection_rate: float           # 0–1
    connectivity_rate: float        # 0–1
    avg_latency_ms: float           # mean latency over rolling window
    latency_p95_ms: float           # 95th-percentile latency
    avg_slippage_bps: float         # mean slippage over rolling window
    num_observations: int           # events in rolling window
    insufficient_data: bool         # True when below min_observations threshold
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def _p95_index(n: int) -> int:
    """Return the zero-based index of the 95th-percentile element in a sorted list of length *n*."""
    return min(int(math.ceil(0.95 * n)) - 1, n - 1)


# ---------------------------------------------------------------------------
# Per-broker rolling state
# ---------------------------------------------------------------------------


class _BrokerState:
    """
    Maintains rolling observation history and an EMA-smoothed composite score
    for a single broker.
    """

    def __init__(self, broker: str, window: int, ema_alpha: float) -> None:
        self.broker = broker
        self._window = window
        self._ema_alpha = ema_alpha
        self._observations: Deque[OrderObservation] = deque(maxlen=window)
        self._ema_score: Optional[float] = None   # None until first score computed

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, obs: OrderObservation) -> None:
        self._observations.append(obs)
        raw = self._compute_raw_score()
        if raw is not None:
            if self._ema_score is None:
                self._ema_score = raw
            else:
                self._ema_score = (
                    self._ema_alpha * raw
                    + (1.0 - self._ema_alpha) * self._ema_score
                )

    # ------------------------------------------------------------------
    # Score calculation
    # ------------------------------------------------------------------

    def _compute_raw_score(self) -> Optional[float]:
        """
        Compute the raw (non-smoothed) composite score from the current
        rolling window.  Returns None when the window is too small.
        """
        n = len(self._observations)
        if n == 0:
            return None

        obs_list = list(self._observations)

        # ── Sub-metric calculations ──────────────────────────────────

        # 1. Fill success rate (higher = better)
        fill_rate = sum(1 for o in obs_list if o.success) / n

        # 2. Connectivity rate (higher = better)
        conn_rate = sum(1 for o in obs_list if o.connected) / n

        # 3. Rejection rate (lower = better)
        rej_rate = sum(1 for o in obs_list if o.rejected) / n

        # 4. Latency p95 (lower = better)
        latencies = sorted(o.latency_ms for o in obs_list if o.latency_ms >= 0)
        if latencies:
            idx = _p95_index(len(latencies))
            p95_lat = latencies[idx]
            avg_lat = sum(latencies) / len(latencies)
        else:
            p95_lat = 0.0
            avg_lat = 0.0

        # 5. Average slippage (lower = better)
        slippages = [o.slippage_bps for o in obs_list if o.slippage_bps >= 0]
        avg_slip = sum(slippages) / len(slippages) if slippages else 0.0

        # ── Normalise to [0, 1] ──────────────────────────────────────

        norm_fill = fill_rate                                   # already 0–1
        norm_conn = conn_rate                                   # already 0–1
        norm_rej = 1.0 - rej_rate                              # invert
        norm_lat = max(0.0, 1.0 - p95_lat / LATENCY_CEILING_MS)  # invert + clamp
        norm_slip = max(0.0, 1.0 - avg_slip / SLIPPAGE_CEILING_BPS)  # invert + clamp

        # ── Weighted composite ───────────────────────────────────────
        raw = (
            W_FILL_SUCCESS * norm_fill
            + W_LATENCY    * norm_lat
            + W_SLIPPAGE   * norm_slip
            + W_REJECTION  * norm_rej
            + W_CONNECTIVITY * norm_conn
        ) * 100.0

        return max(0.0, min(100.0, raw))

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, min_observations: int) -> BrokerScoreSnapshot:
        obs_list = list(self._observations)
        n = len(obs_list)
        insufficient = n < min_observations

        if n == 0:
            return BrokerScoreSnapshot(
                broker=self.broker,
                composite_score=DEFAULT_SCORE,
                fill_success_rate=0.0,
                rejection_rate=0.0,
                connectivity_rate=0.0,
                avg_latency_ms=0.0,
                latency_p95_ms=0.0,
                avg_slippage_bps=0.0,
                num_observations=0,
                insufficient_data=True,
            )

        fill_rate = sum(1 for o in obs_list if o.success) / n
        conn_rate = sum(1 for o in obs_list if o.connected) / n
        rej_rate = sum(1 for o in obs_list if o.rejected) / n

        latencies = sorted(o.latency_ms for o in obs_list if o.latency_ms >= 0)
        if latencies:
            idx = _p95_index(len(latencies))
            p95_lat = latencies[idx]
            avg_lat = sum(latencies) / len(latencies)
        else:
            p95_lat = 0.0
            avg_lat = 0.0

        slippages = [o.slippage_bps for o in obs_list if o.slippage_bps >= 0]
        avg_slip = sum(slippages) / len(slippages) if slippages else 0.0

        score = (
            self._ema_score
            if (self._ema_score is not None and not insufficient)
            else DEFAULT_SCORE
        )

        return BrokerScoreSnapshot(
            broker=self.broker,
            composite_score=round(score, 2),
            fill_success_rate=round(fill_rate, 4),
            rejection_rate=round(rej_rate, 4),
            connectivity_rate=round(conn_rate, 4),
            avg_latency_ms=round(avg_lat, 2),
            latency_p95_ms=round(p95_lat, 2),
            avg_slippage_bps=round(avg_slip, 4),
            num_observations=n,
            insufficient_data=insufficient,
        )


# ---------------------------------------------------------------------------
# BrokerPerformanceScorer
# ---------------------------------------------------------------------------


class BrokerPerformanceScorer:
    """
    Tracks live reliability metrics for all registered brokers and computes a
    composite performance score (0–100) used to auto-route trades.

    Thread-safe; process-wide singleton via ``get_broker_performance_scorer()``.

    Parameters
    ----------
    window:
        Rolling observation window size per broker.
    min_observations:
        Minimum observations required before returning a data-driven score.
        Brokers below this threshold receive ``DEFAULT_SCORE`` (50).
    ema_alpha:
        EMA smoothing factor for the composite score (0 < alpha ≤ 1).
        Smaller values produce more smoothing.
    """

    def __init__(
        self,
        window: int = DEFAULT_WINDOW,
        min_observations: int = DEFAULT_MIN_OBSERVATIONS,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
    ) -> None:
        self._lock = threading.Lock()
        self._window = window
        self._min_observations = min_observations
        self._ema_alpha = ema_alpha
        self._states: Dict[str, _BrokerState] = {}

        logger.info(
            "BrokerPerformanceScorer initialised | window=%d | min_obs=%d | ema_alpha=%.2f",
            window, min_observations, ema_alpha,
        )

    # ------------------------------------------------------------------
    # Public API — recording
    # ------------------------------------------------------------------

    def record_order_result(
        self,
        broker: str,
        success: bool,
        latency_ms: float = 0.0,
        slippage_bps: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """
        Record the outcome of one order attempt for *broker*.

        Parameters
        ----------
        broker:
            Broker / exchange name (e.g. ``"coinbase"``, ``"kraken"``).
        success:
            ``True`` if the order filled without error.
        latency_ms:
            End-to-end round-trip time in milliseconds.
        slippage_bps:
            Observed slippage in basis points (pass ``0.0`` when unknown).
        error:
            Optional error message string; used to classify the event.
        """
        error_lower = (error or "").lower()

        # Classify the error type for sub-metric tracking
        rejected = _is_rejection_error(error_lower)
        connected = not _is_connectivity_error(error_lower)

        obs = OrderObservation(
            success=success,
            latency_ms=max(0.0, latency_ms),
            slippage_bps=max(0.0, slippage_bps),
            rejected=rejected,
            connected=connected,
        )

        with self._lock:
            if broker not in self._states:
                self._states[broker] = _BrokerState(
                    broker, self._window, self._ema_alpha
                )
            self._states[broker].record(obs)

        logger.debug(
            "BrokerPerformanceScorer | %s | success=%s rejected=%s latency=%.0fms slippage=%.2fbps",
            broker, success, rejected, latency_ms, slippage_bps,
        )

    # ------------------------------------------------------------------
    # Public API — scoring & routing
    # ------------------------------------------------------------------

    def get_score(self, broker: str) -> float:
        """
        Return the current composite performance score (0–100) for *broker*.

        Returns ``DEFAULT_SCORE`` (50) when insufficient data is available.
        """
        with self._lock:
            state = self._states.get(broker)
        if state is None:
            return DEFAULT_SCORE
        return state.snapshot(self._min_observations).composite_score

    def get_best_broker(self, candidates: Sequence[str]) -> Optional[str]:
        """
        Return the name of the highest-scoring broker from *candidates*.

        Parameters
        ----------
        candidates:
            Ordered sequence of broker names to evaluate.  All candidates are
            scored; the one with the highest composite score is returned.

        Returns
        -------
        str | None
            The name of the best broker, or ``None`` if *candidates* is empty.
        """
        if not candidates:
            return None

        scored: List[Tuple[float, str]] = []
        with self._lock:
            for name in candidates:
                state = self._states.get(name)
                score = (
                    state.snapshot(self._min_observations).composite_score
                    if state is not None
                    else DEFAULT_SCORE
                )
                scored.append((score, name))

        # Sort descending by score; break ties by original candidate order
        order_map = {name: i for i, name in enumerate(candidates)}
        scored.sort(key=lambda t: (-t[0], order_map[t[1]]))
        best_score, best_name = scored[0]

        logger.debug(
            "BrokerPerformanceScorer.get_best_broker(%s) → %s (score=%.1f)",
            list(candidates), best_name, best_score,
        )
        return best_name

    def get_snapshot(self, broker: str) -> BrokerScoreSnapshot:
        """Return a full metrics snapshot for *broker*."""
        with self._lock:
            state = self._states.get(broker)
        if state is None:
            return BrokerScoreSnapshot(
                broker=broker,
                composite_score=DEFAULT_SCORE,
                fill_success_rate=0.0,
                rejection_rate=0.0,
                connectivity_rate=0.0,
                avg_latency_ms=0.0,
                latency_p95_ms=0.0,
                avg_slippage_bps=0.0,
                num_observations=0,
                insufficient_data=True,
            )
        return state.snapshot(self._min_observations)

    def get_all_snapshots(self) -> List[BrokerScoreSnapshot]:
        """Return snapshots for every broker seen so far, sorted by score."""
        with self._lock:
            broker_names = list(self._states.keys())
        snapshots = [self.get_snapshot(b) for b in broker_names]
        snapshots.sort(key=lambda s: s.composite_score, reverse=True)
        return snapshots

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable performance table for all tracked brokers."""
        snapshots = self.get_all_snapshots()
        lines = [
            "=" * 80,
            "  NIJA BROKER PERFORMANCE SCORER — LIVE RANKINGS",
            "=" * 80,
            f"  {'Broker':<35} {'Score':>6}  {'FillOK':>6}  {'Rej':>5}  "
            f"{'Lat p95':>8}  {'Slip':>7}  {'Obs':>5}",
            "-" * 80,
        ]
        for s in snapshots:
            flag = "  (low data)" if s.insufficient_data else ""
            lines.append(
                f"  {s.broker:<35} {s.composite_score:>6.1f}  "
                f"{s.fill_success_rate * 100:>5.1f}%  "
                f"{s.rejection_rate * 100:>4.1f}%  "
                f"{s.latency_p95_ms:>7.0f}ms  "
                f"{s.avg_slippage_bps:>6.2f}bp  "
                f"{s.num_observations:>5}{flag}"
            )
        lines.append("=" * 80)
        return "\n".join(lines)

    def get_summary_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable summary of all broker scores."""
        snapshots = self.get_all_snapshots()
        return {
            "engine": "BrokerPerformanceScorer",
            "version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "brokers": [
                {
                    "broker": s.broker,
                    "composite_score": s.composite_score,
                    "fill_success_rate": s.fill_success_rate,
                    "rejection_rate": s.rejection_rate,
                    "connectivity_rate": s.connectivity_rate,
                    "avg_latency_ms": s.avg_latency_ms,
                    "latency_p95_ms": s.latency_p95_ms,
                    "avg_slippage_bps": s.avg_slippage_bps,
                    "num_observations": s.num_observations,
                    "insufficient_data": s.insufficient_data,
                }
                for s in snapshots
            ],
        }


# ---------------------------------------------------------------------------
# Error classification helpers
# ---------------------------------------------------------------------------

# Keywords that indicate the venue itself rejected the order (not a network issue)
_REJECTION_KEYWORDS: Tuple[str, ...] = (
    "insufficient",
    "invalid",
    "notional",
    "market closed",
    "market_closed",
    "not found",
    "rejected",
    "order rejected",
    "permission denied",
    "unsupported",
    "below minimum",
)

# Keywords that indicate a connectivity / network problem
_CONNECTIVITY_KEYWORDS: Tuple[str, ...] = (
    "timeout",
    "connection",
    "network",
    "remote end closed",
    "remotedisconnected",
    "connection reset",
    "broken pipe",
    "service unavailable",
    "503",
    "504",
)


def _is_rejection_error(error_lower: str) -> bool:
    """Return True when the error string looks like a venue-side rejection."""
    return any(kw in error_lower for kw in _REJECTION_KEYWORDS)


def _is_connectivity_error(error_lower: str) -> bool:
    """Return True when the error string looks like a connectivity failure."""
    return any(kw in error_lower for kw in _CONNECTIVITY_KEYWORDS)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[BrokerPerformanceScorer] = None
_instance_lock = threading.Lock()


def get_broker_performance_scorer(**kwargs) -> BrokerPerformanceScorer:
    """
    Return the process-wide ``BrokerPerformanceScorer`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = BrokerPerformanceScorer(**kwargs)
    return _instance


__all__ = [
    "OrderObservation",
    "BrokerScoreSnapshot",
    "BrokerPerformanceScorer",
    "get_broker_performance_scorer",
]


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    scorer = BrokerPerformanceScorer(window=50, min_observations=3)

    random.seed(42)

    # Simulate 40 observations for three brokers with different characteristics
    brokers_cfg = {
        "coinbase": {"fill_p": 0.97, "latency_mu": 80,  "latency_sd": 20,  "slip_mu": 1.0},
        "kraken":   {"fill_p": 0.90, "latency_mu": 120, "latency_sd": 40,  "slip_mu": 2.5},
        "binance":  {"fill_p": 0.85, "latency_mu": 200, "latency_sd": 80,  "slip_mu": 5.0},
    }

    for _ in range(40):
        for broker, cfg in brokers_cfg.items():
            success = random.random() < cfg["fill_p"]
            latency = max(0.0, random.gauss(cfg["latency_mu"], cfg["latency_sd"]))
            slippage = max(0.0, random.gauss(cfg["slip_mu"], cfg["slip_mu"] * 0.3))
            scorer.record_order_result(
                broker=broker,
                success=success,
                latency_ms=latency,
                slippage_bps=slippage,
                error=None if success else "timeout",
            )

    print(scorer.get_report())

    best = scorer.get_best_broker(["coinbase", "kraken", "binance"])
    print(f"\nBest broker: {best}")
    assert best == "coinbase", f"Expected coinbase, got {best}"
    print("✅ Smoke-test passed.")
