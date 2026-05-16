"""
Pipeline Funnel Counter
=======================

Tracks the 5-stage trading pipeline to expose the choke point quickly:

  1. signals_generated   – market scanned; a candidate signal was produced
  2. signals_approved    – signal cleared all strategy gates (confidence, ADX,
                           volume, AI entry gate)
  3. risk_passed         – cleared all execution-layer risk gates (bootstrap
                           authority, balance, minimum notional, expectancy,
                           edge score, kill switches …)
  4. execution_attempted – order dispatched to the broker
  5. orders_routed       – broker confirmed with a valid order_id

Usage
-----
::

    from bot.pipeline_funnel import get_pipeline_funnel

    pf = get_pipeline_funnel()
    pf.record_signal_generated(symbol)
    pf.record_signal_approved(symbol)
    pf.record_risk_passed(symbol)
    pf.record_execution_attempted(symbol)
    pf.record_orders_routed(symbol)

    summary = pf.get_summary()
    # summary["choke_point"] tells you which stage has the biggest drop-off.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_STAGE_NAMES: Tuple[str, ...] = (
    "signals_generated",
    "signals_approved",
    "risk_passed",
    "execution_attempted",
    "orders_routed",
)


class PipelineFunnelCounter:
    """
    Thread-safe global 5-stage pipeline funnel counter with drop-off analytics.

    Call ``get_pipeline_funnel()`` to obtain the process-wide singleton.
    """

    STAGE_NAMES = _STAGE_NAMES

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: Dict[str, int] = {s: 0 for s in _STAGE_NAMES}
        self._last_ts: Dict[str, float] = {s: 0.0 for s in _STAGE_NAMES}
        self._window_start: float = time.time()

    # ------------------------------------------------------------------
    # Stage recorders
    # ------------------------------------------------------------------

    def record_signal_generated(self, symbol: str = "") -> None:
        """Increment signals_generated counter."""
        self._inc("signals_generated")

    def record_signal_approved(self, symbol: str = "") -> None:
        """Increment signals_approved counter."""
        self._inc("signals_approved")

    def record_risk_passed(self, symbol: str = "") -> None:
        """Increment risk_passed counter."""
        self._inc("risk_passed")

    def record_execution_attempted(self, symbol: str = "") -> None:
        """Increment execution_attempted counter."""
        self._inc("execution_attempted")

    def record_orders_routed(self, symbol: str = "") -> None:
        """Increment orders_routed counter."""
        self._inc("orders_routed")

    def _inc(self, stage: str) -> None:
        with self._lock:
            self._counts[stage] += 1
            self._last_ts[stage] = time.time()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def get_summary(self) -> Dict[str, Any]:
        """
        Return pipeline funnel with counts, inter-stage drop-off percentages,
        the identified choke point, and the end-to-end conversion rate.

        Example output::

            {
              "window_start": 1747432448.2,
              "window_seconds": 305.1,
              "stages": [
                {"stage": "signals_generated",   "count": 1000, "drop_off_pct": null},
                {"stage": "signals_approved",     "count": 450,  "drop_off_pct": 55.0},
                {"stage": "risk_passed",          "count": 200,  "drop_off_pct": 55.6},
                {"stage": "execution_attempted",  "count": 150,  "drop_off_pct": 25.0},
                {"stage": "orders_routed",        "count": 120,  "drop_off_pct": 20.0}
              ],
              "choke_point": "risk_passed",
              "choke_drop_pct": 55.6,
              "conversion_rate_pct": 12.0
            }
        """
        with self._lock:
            counts = dict(self._counts)
            last_ts = dict(self._last_ts)
            window_start = self._window_start

        stages: List[Dict[str, Any]] = []
        prev_count: Optional[int] = None
        choke_stage: Optional[str] = None
        choke_drop: float = 0.0

        for name in _STAGE_NAMES:
            count = counts[name]
            drop_pct: Optional[float] = None
            if prev_count is not None and prev_count > 0:
                drop_pct = round((1.0 - count / prev_count) * 100.0, 1)
                if drop_pct > choke_drop:
                    choke_drop = drop_pct
                    choke_stage = name
            stages.append({
                "stage": name,
                "count": count,
                "drop_off_pct": drop_pct,
                "last_seen": last_ts[name] if last_ts[name] > 0.0 else None,
            })
            prev_count = count

        gen = counts["signals_generated"]
        routed = counts["orders_routed"]
        conversion_pct: Optional[float] = round(routed / gen * 100.0, 2) if gen > 0 else None

        return {
            "window_start": window_start,
            "window_seconds": round(time.time() - window_start, 1),
            "stages": stages,
            "choke_point": choke_stage,
            "choke_drop_pct": round(choke_drop, 1) if choke_stage else None,
            "conversion_rate_pct": conversion_pct,
        }

    def reset(self) -> None:
        """Reset all counters and start a new measurement window."""
        with self._lock:
            for s in _STAGE_NAMES:
                self._counts[s] = 0
                self._last_ts[s] = 0.0
            self._window_start = time.time()


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_SINGLETON: Optional[PipelineFunnelCounter] = None
_SINGLETON_LOCK = threading.Lock()


def get_pipeline_funnel() -> PipelineFunnelCounter:
    """Return the process-wide singleton :class:`PipelineFunnelCounter`."""
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = PipelineFunnelCounter()
    return _SINGLETON
