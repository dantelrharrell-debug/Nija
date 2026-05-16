"""Regime-conditional AI gate pass calibration for EIL v2."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("nija.regime_gate_calibrator")


@dataclass
class RegimeGateCounts:
    """Bayesian counter bucket for one (regime, path-prefix) key."""

    passes: int = 0
    total: int = 0


class RegimeGateCalibrator:
    """Maintains pass/total counts and exposes Laplace-smoothed probabilities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counts: Dict[Tuple[str, str], RegimeGateCounts] = defaultdict(RegimeGateCounts)

    @staticmethod
    def _norm_regime(value: Any) -> str:
        if value is None:
            return "unknown"
        if hasattr(value, "value"):
            return str(value.value).lower()
        return str(value).lower()

    @staticmethod
    def _path_prefix(trace_path: Any, prefix_len: int = 2) -> str:
        if not trace_path:
            return "empty"
        if isinstance(trace_path, str):
            return trace_path
        if isinstance(trace_path, (list, tuple)):
            return "|".join(str(p) for p in trace_path[: max(1, int(prefix_len))])
        return str(trace_path)

    def update(self, regime: Any, trace_path: Any, passed: bool) -> None:
        """Update Bayesian counts for a regime/path prefix."""
        regime_key = self._norm_regime(regime)
        prefix = self._path_prefix(trace_path)
        with self._lock:
            bucket = self._counts[(regime_key, prefix)]
            bucket.total += 1
            if passed:
                bucket.passes += 1
        self._publish_to_redis(regime_key, prefix)

    def update_from_trace(self, trace: Dict[str, Any]) -> None:
        """Convenience method to update counts from trace payload."""
        path = trace.get("trace_path") or trace.get("path") or trace.get("events")
        if isinstance(path, list) and path and isinstance(path[0], dict):
            path = [f"{(e or {}).get('stage', 'unknown')}:{(e or {}).get('outcome', 'unknown')}" for e in path]

        status = str(trace.get("status") or "").lower()
        terminal_reason = str(trace.get("terminal_reason") or "")
        passed = status == "filled" and "rejected" not in terminal_reason.lower()
        self.update(trace.get("regime"), path, passed)

    def get_gate_pass_probability(self, regime: Any, path_prefix: Any) -> float:
        """Return Laplace-smoothed pass probability for regime/path_prefix."""
        regime_key = self._norm_regime(regime)
        prefix = self._path_prefix(path_prefix)
        with self._lock:
            bucket = self._counts.get((regime_key, prefix), RegimeGateCounts())
            return (bucket.passes + 1.0) / (bucket.total + 2.0)

    def get_regime_heatmap(self) -> Dict[str, Dict[str, float]]:
        """Return nested probability map for dashboard heatmap use."""
        heatmap: Dict[str, Dict[str, float]] = {}
        with self._lock:
            for (regime, prefix), bucket in self._counts.items():
                heatmap.setdefault(regime, {})[prefix] = (bucket.passes + 1.0) / (bucket.total + 2.0)
        return heatmap

    def _publish_to_redis(self, regime: str, prefix: str) -> None:
        try:
            try:
                from bot.redis_runtime import create_redis
            except ImportError:
                from redis_runtime import create_redis  # type: ignore[import]

            client = create_redis(decode_responses=True)
            key = f"nija:eil:regime_gate_counts:{regime}"
            prob = self.get_gate_pass_probability(regime, prefix)
            with self._lock:
                bucket = self._counts.get((regime, prefix), RegimeGateCounts())
                payload = json.dumps(
                    {
                        "passes": bucket.passes,
                        "total": bucket.total,
                        "pass_probability": prob,
                    }
                )
            client.hset(key, prefix, payload)
        except Exception:
            logger.debug("Regime gate redis publish skipped", exc_info=True)


_singleton: Optional[RegimeGateCalibrator] = None
_singleton_lock = threading.Lock()


def get_regime_gate_calibrator() -> RegimeGateCalibrator:
    """Return process singleton RegimeGateCalibrator."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RegimeGateCalibrator()
    return _singleton
