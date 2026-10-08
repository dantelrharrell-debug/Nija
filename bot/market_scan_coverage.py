"""Broker-instance scan coverage; admission is never counted as evaluation.

The adapter-advertised universe may itself be a fallback or a regional subset.
These counters do not certify global coverage or candle timestamp freshness.
"""
from __future__ import annotations

import threading
import time
from typing import Any

_STATE_LOCK = threading.Lock()


class MarketScanCoverage:
    """Prioritize symbols skipped by nested scan budgets and expose real coverage."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._universe: set[str] = set()
        self._sequence = 0
        self._evaluated: dict[str, int] = {}
        self._data_available: dict[str, float] = {}

    def select(self, universe: list[str], *, start: int, limit: int) -> list[str]:
        """Select least-recently evaluated instruments; preserve cursor tie order."""
        with self._lock:
            self._universe = set(universe)
            self._evaluated = {s: v for s, v in self._evaluated.items() if s in self._universe}
            self._data_available = {s: v for s, v in self._data_available.items() if s in self._universe}
            rotated = universe[start:] + universe[:start]
            return sorted(rotated, key=lambda s: self._evaluated.get(s, 0))[:max(0, limit)]

    def record_evaluation(self, symbol: str) -> None:
        """Record an actual scoring-loop visit, including a quarantine rejection."""
        with self._lock:
            self._sequence += 1
            self._evaluated[str(symbol)] = self._sequence

    def record_data_result(self, symbol: str, *, available: bool) -> None:
        """Record usable candle-response availability, without claiming freshness."""
        with self._lock:
            if available:
                self._data_available[str(symbol)] = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        """Return process-lifetime coverage of the current advertised universe."""
        with self._lock:
            total = len(self._universe)
            evaluated = len(self._universe.intersection(self._evaluated))
            available = len(self._universe.intersection(self._data_available))
            return {"advertised": total, "evaluated": evaluated,
                    "not_evaluated": total - evaluated, "data_available": available,
                    "coverage_pct": 100.0 * evaluated / total if total else 0.0,
                    "scope": "broker_instance", "source": "adapter_advertised",
                    "candle_freshness_verified": False, "global_coverage_verified": False}


def get_market_scan_coverage(broker: Any) -> MarketScanCoverage:
    """Return instance-local telemetry; never share counters between accounts."""
    with _STATE_LOCK:
        state = getattr(broker, "_nija_market_scan_coverage", None) if broker is not None else None
        if not isinstance(state, MarketScanCoverage):
            state = MarketScanCoverage()
            if broker is not None:
                setattr(broker, "_nija_market_scan_coverage", state)
        return state
