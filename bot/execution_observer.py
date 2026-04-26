from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple

logger = logging.getLogger("nija.execution_observer")


@dataclass
class StrategyExecutionStats:
    successes: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    allocation_multiplier: float = 1.0
    suppressed_until: float = 0.0


class ExecutionObserver:
    """Feed execution outcomes back into allocation weights and suppression."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stats: Dict[str, StrategyExecutionStats] = {}

    def is_strategy_suppressed(self, strategy: str) -> Tuple[bool, str]:
        if not strategy:
            return False, ""
        with self._lock:
            stats = self._stats.get(strategy)
            if stats is None:
                return False, ""
            if stats.suppressed_until > time.time():
                remaining = max(0.0, stats.suppressed_until - time.time())
                return True, f"strategy suppressed for {remaining:.0f}s after repeated failures"
            return False, ""

    def get_allocation_multiplier(self, strategy: str) -> float:
        if not strategy:
            return 1.0
        with self._lock:
            return float(self._stats.get(strategy, StrategyExecutionStats()).allocation_multiplier)

    def observe(self, *, strategy: str, symbol: str, side: str, size_usd: float, success: bool, error: str = "") -> None:
        if not strategy:
            return

        with self._lock:
            stats = self._stats.setdefault(strategy, StrategyExecutionStats())
            if success:
                stats.successes += 1
                stats.consecutive_failures = 0
            else:
                stats.failures += 1
                stats.consecutive_failures += 1

            total = stats.successes + stats.failures
            success_rate = (stats.successes / total) if total > 0 else 0.5
            stats.allocation_multiplier = max(0.5, min(1.5, 0.5 + success_rate))

            if not success and stats.consecutive_failures >= 3:
                stats.suppressed_until = time.time() + 300.0
                logger.warning(
                    "ExecutionObserver: suppressing strategy=%s after %d consecutive failures",
                    strategy,
                    stats.consecutive_failures,
                )
            elif success:
                stats.suppressed_until = 0.0

            logger.info(
                "ExecutionObserver: strategy=%s symbol=%s side=%s success=%s size=$%.2f alloc_mult=%.2f failures=%d error=%s",
                strategy,
                symbol,
                side,
                success,
                size_usd,
                stats.allocation_multiplier,
                stats.consecutive_failures,
                error or "none",
            )


_instance: ExecutionObserver | None = None
_instance_lock = threading.Lock()


def get_execution_observer() -> ExecutionObserver:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExecutionObserver()
    return _instance