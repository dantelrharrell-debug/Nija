"""
NIJA Multi-Venue Execution Calibrator
=======================================

Connects to multiple brokers/exchanges and measures real execution quality:
- Slippage (expected vs. actual fill price)
- Fill rate and partial-fill frequency
- Execution latency
- TWAP / VWAP / Iceberg order efficiency

After each calibration run the module emits routing-parameter recommendations
that the execution router can consume to optimise future orders.

Architecture
------------
Each ``VenueProfile`` stores rolling statistics for one broker/exchange.
``MultiVenueCalibrator`` orchestrates calibration sessions, aggregates
metrics, and produces ``RoutingRecommendation`` objects.

Integration points
------------------
- ``bot.execution_optimizer``  – order slicing strategies (TWAP/VWAP)
- ``bot.broker_adapters``      – per-broker validated orders
- ``bot.execution_intelligence`` – slippage tracking

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.multi_venue_calibrator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_VENUES: List[str] = ["coinbase", "kraken", "binance", "alpaca", "okx"]
SUPPORTED_EXECUTION_METHODS: List[str] = ["market", "limit", "twap", "vwap", "iceberg"]

MAX_HISTORY_PER_VENUE: int = 500          # samples retained per venue
LATENCY_WARN_MS: float = 500.0            # warn if latency exceeds this
SLIPPAGE_WARN_BPS: float = 20.0           # warn if slippage exceeds 20 bps
FILL_RATE_WARN: float = 0.90              # warn if fill rate drops below 90 %


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExecutionSample:
    """One execution measurement from a calibration session."""
    venue: str
    symbol: str
    side: str                              # 'buy' | 'sell'
    execution_method: str
    intended_price: float
    actual_price: float
    intended_size: float
    filled_size: float
    latency_ms: float
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def slippage_bps(self) -> float:
        """Slippage in basis points (positive = unfavourable)."""
        if self.intended_price <= 0:
            return 0.0
        raw = (self.actual_price - self.intended_price) / self.intended_price * 10_000
        # For sells, adverse slippage is a negative move in actual price
        return raw if self.side == "buy" else -raw

    @property
    def fill_rate(self) -> float:
        """Fraction of intended size that was actually filled."""
        if self.intended_size <= 0:
            return 0.0
        return min(self.filled_size / self.intended_size, 1.0)


@dataclass
class VenueStats:
    """Rolling statistics for a single venue."""
    venue: str
    sample_count: int = 0
    avg_slippage_bps: float = 0.0
    p95_slippage_bps: float = 0.0
    avg_fill_rate: float = 1.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    # Per execution-method breakdown
    method_stats: Dict[str, Dict] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "venue": self.venue,
            "sample_count": self.sample_count,
            "avg_slippage_bps": round(self.avg_slippage_bps, 3),
            "p95_slippage_bps": round(self.p95_slippage_bps, 3),
            "avg_fill_rate": round(self.avg_fill_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "method_stats": self.method_stats,
        }


@dataclass
class RoutingRecommendation:
    """
    Routing parameter recommendations produced after calibration.

    The execution router should prefer venues with lower scores.
    Score = avg_slippage_bps + (latency_penalty) + (fill_penalty)
    """
    timestamp: str
    recommended_primary_venue: str
    venue_scores: Dict[str, float]          # lower = better
    preferred_method_per_venue: Dict[str, str]
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "recommended_primary_venue": self.recommended_primary_venue,
            "venue_scores": self.venue_scores,
            "preferred_method_per_venue": self.preferred_method_per_venue,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Internal per-venue profile
# ---------------------------------------------------------------------------

class VenueProfile:
    """Maintains a rolling window of execution samples for one venue."""

    def __init__(self, venue: str) -> None:
        self.venue = venue
        self._samples: Deque[ExecutionSample] = deque(maxlen=MAX_HISTORY_PER_VENUE)
        self._lock = threading.Lock()

    def add_sample(self, sample: ExecutionSample) -> None:
        with self._lock:
            self._samples.append(sample)

    def compute_stats(self) -> VenueStats:
        with self._lock:
            samples = list(self._samples)

        if not samples:
            return VenueStats(venue=self.venue)

        slippages = [s.slippage_bps for s in samples]
        fills = [s.fill_rate for s in samples]
        latencies = [s.latency_ms for s in samples]

        slippages_sorted = sorted(slippages)
        latencies_sorted = sorted(latencies)
        n = len(samples)
        p95_idx = int(n * 0.95)

        # Per-method breakdown
        method_groups: Dict[str, List[ExecutionSample]] = {}
        for s in samples:
            method_groups.setdefault(s.execution_method, []).append(s)

        method_stats: Dict[str, Dict] = {}
        for method, ms in method_groups.items():
            ms_slippages = [x.slippage_bps for x in ms]
            ms_fills = [x.fill_rate for x in ms]
            method_stats[method] = {
                "count": len(ms),
                "avg_slippage_bps": round(sum(ms_slippages) / len(ms_slippages), 3),
                "avg_fill_rate": round(sum(ms_fills) / len(ms_fills), 4),
            }

        return VenueStats(
            venue=self.venue,
            sample_count=n,
            avg_slippage_bps=sum(slippages) / n,
            p95_slippage_bps=slippages_sorted[min(p95_idx, n - 1)],
            avg_fill_rate=sum(fills) / n,
            avg_latency_ms=sum(latencies) / n,
            p95_latency_ms=latencies_sorted[min(p95_idx, n - 1)],
            method_stats=method_stats,
        )


# ---------------------------------------------------------------------------
# Main calibrator
# ---------------------------------------------------------------------------

class MultiVenueCalibrator:
    """
    Orchestrates execution calibration across multiple brokers/exchanges.

    Usage
    -----
    calibrator = MultiVenueCalibrator()

    # Record a real or simulated execution
    calibrator.record_execution(ExecutionSample(
        venue="coinbase",
        symbol="BTC-USD",
        side="buy",
        execution_method="twap",
        intended_price=50_000.0,
        actual_price=50_010.0,   # 2 bps slippage
        intended_size=0.1,
        filled_size=0.1,
        latency_ms=120.0,
    ))

    stats = calibrator.get_venue_stats("coinbase")
    recommendations = calibrator.compute_recommendations()
    """

    def __init__(self, venues: Optional[List[str]] = None) -> None:
        self._venues = venues or SUPPORTED_VENUES
        self._profiles: Dict[str, VenueProfile] = {
            v: VenueProfile(v) for v in self._venues
        }
        self._lock = threading.Lock()
        logger.info(
            "MultiVenueCalibrator initialised — venues: %s",
            ", ".join(self._venues),
        )

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def record_execution(self, sample: ExecutionSample) -> None:
        """
        Record a single execution sample.

        Logs warnings when slippage, fill rate, or latency exceeds thresholds.
        """
        if sample.venue not in self._profiles:
            logger.warning("Unknown venue '%s'; sample ignored.", sample.venue)
            return

        self._profiles[sample.venue].add_sample(sample)

        # Emit warnings for concerning metrics
        if sample.slippage_bps > SLIPPAGE_WARN_BPS:
            logger.warning(
                "⚠️  High slippage on %s/%s via %s: %.1f bps",
                sample.venue, sample.symbol, sample.execution_method, sample.slippage_bps,
            )
        if sample.fill_rate < FILL_RATE_WARN:
            logger.warning(
                "⚠️  Low fill rate on %s/%s via %s: %.1f%%",
                sample.venue, sample.symbol, sample.execution_method,
                sample.fill_rate * 100,
            )
        if sample.latency_ms > LATENCY_WARN_MS:
            logger.warning(
                "⚠️  High latency on %s/%s via %s: %.0f ms",
                sample.venue, sample.symbol, sample.execution_method, sample.latency_ms,
            )

    def record_executions(self, samples: List[ExecutionSample]) -> None:
        """Batch record multiple execution samples."""
        for sample in samples:
            self.record_execution(sample)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_venue_stats(self, venue: str) -> Optional[VenueStats]:
        """Return rolling statistics for a single venue."""
        if venue not in self._profiles:
            return None
        return self._profiles[venue].compute_stats()

    def get_all_stats(self) -> Dict[str, VenueStats]:
        """Return statistics for all venues."""
        return {venue: self._profiles[venue].compute_stats() for venue in self._venues}

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def compute_recommendations(self) -> RoutingRecommendation:
        """
        Analyse calibration data and produce routing recommendations.

        Scoring formula (lower = better):
            score = avg_slippage_bps
                    + (avg_latency_ms / 100)          # 100ms ≈ 1 bps equivalent
                    + (1 - avg_fill_rate) * 50         # 1% fill shortfall ≈ 0.5 bps
        """
        all_stats = self.get_all_stats()
        venue_scores: Dict[str, float] = {}
        preferred_methods: Dict[str, str] = {}
        notes: List[str] = []

        for venue, stats in all_stats.items():
            if stats.sample_count == 0:
                venue_scores[venue] = float("inf")
                notes.append(f"{venue}: no data yet")
                continue

            score = (
                stats.avg_slippage_bps
                + stats.avg_latency_ms / 100.0
                + (1.0 - stats.avg_fill_rate) * 50.0
            )
            venue_scores[venue] = round(score, 3)

            # Pick best execution method for this venue
            if stats.method_stats:
                best_method = min(
                    stats.method_stats.items(),
                    key=lambda kv: kv[1].get("avg_slippage_bps", 999),
                )[0]
                preferred_methods[venue] = best_method
            else:
                preferred_methods[venue] = "limit"

        # Best venue = lowest score (exclude inf)
        finite_scores = {v: s for v, s in venue_scores.items() if s != float("inf")}
        best_venue = (
            min(finite_scores, key=finite_scores.get) if finite_scores else "coinbase"
        )

        if not finite_scores:
            notes.append("No calibration data available; defaulting to coinbase.")

        return RoutingRecommendation(
            timestamp=datetime.utcnow().isoformat(),
            recommended_primary_venue=best_venue,
            venue_scores=venue_scores,
            preferred_method_per_venue=preferred_methods,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Supported venues / methods
    # ------------------------------------------------------------------

    def list_venues(self) -> List[str]:
        return list(self._venues)

    def sample_count(self, venue: str) -> int:
        if venue not in self._profiles:
            return 0
        return len(self._profiles[venue]._samples)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_calibrator_instance: Optional[MultiVenueCalibrator] = None
_calibrator_lock = threading.Lock()


def get_multi_venue_calibrator() -> MultiVenueCalibrator:
    """Return the global MultiVenueCalibrator singleton."""
    global _calibrator_instance
    with _calibrator_lock:
        if _calibrator_instance is None:
            _calibrator_instance = MultiVenueCalibrator()
        return _calibrator_instance
