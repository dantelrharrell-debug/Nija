from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger("nija.execution_observer")

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

# Transient errors are infrastructure hiccups that should resolve on their own
# (broker latency, network blip, Redis sync delay).  The strategy is skipped
# for a short window (TRANSIENT_SUPPRESS_S) and then allowed to retry.
# Consecutive transient failures do NOT count toward the deterministic failure
# counter that triggers long-term suppression.
_TRANSIENT_ERROR_SUBSTRINGS: FrozenSet[str] = frozenset({
    "ack_timeout",
    "ack timeout",
    "connection_error",
    "connection error",
    "connectionerror",
    "connection refused",
    "connection reset",
    "redis_timeout",
    "redis timeout",
    "broker_unavailable",
    "broker unavailable",
    "temporarily unavailable",
    "gateway timeout",
    "read timeout",
    "request timeout",
    "network error",
    "socket",
    "ssl error",
    "sslerror",
    "broken pipe",
    "eof",
    "504",
    "503",
    "try again",
    "too many requests",
    "rate limit",
    "429",
})

# Deterministic errors indicate a logic or geometry problem that will not
# resolve by itself.  The strategy is suppressed for a longer window
# (DETERMINISTIC_SUPPRESS_S) after repeated failures.
_DETERMINISTIC_ERROR_SUBSTRINGS: FrozenSet[str] = frozenset({
    "order_compilation_failed",
    "order compilation failed",
    "target_geometry_tp_too_small",
    "target geometry tp too small",
    "quantity_rounds_to_zero",
    "quantity rounds to zero",
    "no_contract_rule",
    "no contract rule",
    "below_min_notional",
    "below min notional",
    "dust_order",
    "dust order",
    "zero_notional",
    "zero notional",
    "zero_qty",
    "zero qty",
    "invalid_symbol_format",
    "invalid symbol format",
    "unsupported_order_type",
    "unsupported order type",
    "unsupported_side",
    "unsupported side",
    "invalid_compiled_price",
    "invalid compiled price",
    "base_step_misaligned",
    "price_step_misaligned",
    "exceeds_max_base_size",
    "ecel reject",
    "order_compilation",
})

# Suppression durations
TRANSIENT_SUPPRESS_S: float = 5.0    # skip symbol for 5 s, then retry
DETERMINISTIC_SUPPRESS_S: float = 300.0  # suppress strategy for 5 min


def classify_error(error: str) -> str:
    """Return ``'transient'``, ``'deterministic'``, or ``'unknown'`` for *error*.

    Classification is case-insensitive substring matching.  Transient patterns
    are checked first so that a generic "timeout" in an ACK-timeout message is
    not accidentally promoted to deterministic.
    """
    if not error:
        return "unknown"
    low = error.lower()
    for substr in _TRANSIENT_ERROR_SUBSTRINGS:
        if substr in low:
            return "transient"
    for substr in _DETERMINISTIC_ERROR_SUBSTRINGS:
        if substr in low:
            return "deterministic"
    return "unknown"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class StrategyExecutionStats:
    successes: int = 0
    failures: int = 0
    # Only deterministic (or unknown) failures count toward consecutive_failures.
    # Transient failures are tracked separately and never trigger long suppression.
    consecutive_failures: int = 0
    consecutive_transient_failures: int = 0
    allocation_multiplier: float = 1.0
    suppressed_until: float = 0.0
    # Per-symbol transient suppression: symbol -> suppressed_until timestamp
    transient_symbol_suppressed_until: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# ExecutionObserver
# ---------------------------------------------------------------------------

class ExecutionObserver:
    """Feed execution outcomes back into allocation weights and suppression.

    Failure classification
    ----------------------
    **Transient errors** (``ack_timeout``, ``connection_error``,
    ``redis_timeout``, ``broker_unavailable``, etc.) are infrastructure
    hiccups that should resolve on their own.  When a transient error is
    observed the affected *symbol* is skipped for
    :data:`TRANSIENT_SUPPRESS_S` seconds (default 5 s) and then allowed to
    retry.  Transient failures do **not** increment the consecutive-failure
    counter that drives long-term strategy suppression.

    **Deterministic errors** (``order_compilation_failed``,
    ``target_geometry_tp_too_small``, ``quantity_rounds_to_zero``,
    ``no_contract_rule``, ``below_min_notional``, etc.) indicate a logic or
    geometry problem that will not resolve by itself.  After
    ``DETERMINISTIC_CONSECUTIVE_THRESHOLD`` (default 3) consecutive
    deterministic failures the strategy is suppressed for
    :data:`DETERMINISTIC_SUPPRESS_S` seconds (default 300 s).

    This distinction prevents Nija from losing the entire strategy due to a
    temporary broker timeout or Redis sync delay.
    """

    # Number of consecutive deterministic failures before long suppression.
    DETERMINISTIC_CONSECUTIVE_THRESHOLD: int = 3

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stats: Dict[str, StrategyExecutionStats] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_strategy_suppressed(self, strategy: str) -> Tuple[bool, str]:
        """Return ``(suppressed, reason)`` for the given strategy name."""
        if not strategy:
            return False, ""
        with self._lock:
            stats = self._stats.get(strategy)
            if stats is None:
                return False, ""
            if stats.suppressed_until > time.time():
                remaining = max(0.0, stats.suppressed_until - time.time())
                return True, (
                    f"[DETERMINISTIC] strategy suppressed for {remaining:.0f}s "
                    "after repeated deterministic failures"
                )
            return False, ""

    def is_symbol_transient_suppressed(self, strategy: str, symbol: str) -> Tuple[bool, str]:
        """Return ``(suppressed, reason)`` for a per-symbol transient window.

        This is a lightweight check callers can use before submitting an order
        for a specific symbol when the strategy itself is not suppressed.
        """
        if not strategy or not symbol:
            return False, ""
        with self._lock:
            stats = self._stats.get(strategy)
            if stats is None:
                return False, ""
            until = stats.transient_symbol_suppressed_until.get(symbol, 0.0)
            if until > time.time():
                remaining = max(0.0, until - time.time())
                return True, (
                    f"[TRANSIENT] symbol={symbol} skipped for {remaining:.1f}s "
                    "after transient infrastructure error — will retry"
                )
            return False, ""

    def get_allocation_multiplier(self, strategy: str) -> float:
        if not strategy:
            return 1.0
        with self._lock:
            return float(self._stats.get(strategy, StrategyExecutionStats()).allocation_multiplier)

    def observe(
        self,
        *,
        strategy: str,
        symbol: str,
        side: str,
        size_usd: float,
        success: bool,
        error: str = "",
    ) -> None:
        """Record an execution outcome and update suppression state.

        Parameters
        ----------
        strategy:
            Strategy name (e.g. ``"ApexTrend"``).
        symbol:
            Trading pair (e.g. ``"BTC-USD"``).
        side:
            ``"buy"`` or ``"sell"``.
        size_usd:
            Requested order size in USD.
        success:
            ``True`` when the order was filled, ``False`` on any rejection.
        error:
            Raw error string from the broker or pipeline.  Used to classify
            the failure as transient or deterministic.
        """
        if not strategy:
            return

        error_class = classify_error(error) if not success else "none"

        with self._lock:
            stats = self._stats.setdefault(strategy, StrategyExecutionStats())

            if success:
                stats.successes += 1
                stats.consecutive_failures = 0
                stats.consecutive_transient_failures = 0
                stats.suppressed_until = 0.0
                # Clear any per-symbol transient suppression on success.
                stats.transient_symbol_suppressed_until.pop(symbol, None)

            elif error_class == "transient":
                # Transient failure: suppress only this symbol for a short window.
                # Do NOT increment consecutive_failures — this must not trigger
                # long-term strategy suppression.
                stats.consecutive_transient_failures += 1
                until = time.time() + TRANSIENT_SUPPRESS_S
                stats.transient_symbol_suppressed_until[symbol] = until
                logger.warning(
                    "⚡ [TRANSIENT] ExecutionObserver: strategy=%s symbol=%s side=%s "
                    "transient_error=%r — skipping symbol for %.0fs then retrying. "
                    "consecutive_transient=%d (strategy suppression NOT triggered)",
                    strategy,
                    symbol,
                    side,
                    error,
                    TRANSIENT_SUPPRESS_S,
                    stats.consecutive_transient_failures,
                )

            else:
                # Deterministic (or unknown) failure: count toward long suppression.
                stats.failures += 1
                stats.consecutive_failures += 1
                if stats.consecutive_failures >= self.DETERMINISTIC_CONSECUTIVE_THRESHOLD:
                    stats.suppressed_until = time.time() + DETERMINISTIC_SUPPRESS_S
                    logger.error(
                        "🚫 [DETERMINISTIC] ExecutionObserver: suppressing strategy=%s "
                        "for %.0fs after %d consecutive deterministic failures. "
                        "error_class=%s last_error=%r",
                        strategy,
                        DETERMINISTIC_SUPPRESS_S,
                        stats.consecutive_failures,
                        error_class,
                        error,
                    )
                else:
                    logger.error(
                        "🔴 [DETERMINISTIC] ExecutionObserver: strategy=%s symbol=%s "
                        "deterministic failure %d/%d. error_class=%s error=%r",
                        strategy,
                        symbol,
                        stats.consecutive_failures,
                        self.DETERMINISTIC_CONSECUTIVE_THRESHOLD,
                        error_class,
                        error,
                    )

            # Recompute allocation multiplier from overall success rate.
            # Transient failures are excluded from the success-rate denominator
            # so that infrastructure blips do not erode the allocation weight.
            total = stats.successes + stats.failures  # failures = deterministic only
            success_rate = (stats.successes / total) if total > 0 else 0.5
            stats.allocation_multiplier = max(0.5, min(1.5, 0.5 + success_rate))

            logger.info(
                "ExecutionObserver: strategy=%s symbol=%s side=%s success=%s "
                "size=$%.2f alloc_mult=%.2f det_failures=%d transient_failures=%d "
                "error_class=%s error=%s",
                strategy,
                symbol,
                side,
                success,
                size_usd,
                stats.allocation_multiplier,
                stats.consecutive_failures,
                stats.consecutive_transient_failures,
                error_class,
                error or "none",
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[ExecutionObserver] = None
_instance_lock = threading.Lock()


def get_execution_observer() -> ExecutionObserver:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExecutionObserver()
    return _instance