from __future__ import annotations

import logging
import os
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

# Internal/non-exchange blockers must never poison the strategy-wide
# deterministic counter.  These failures mean the order did not reach the
# exchange boundary, or the observer is seeing its own suppression message.
# Counting them as deterministic caused live runs to enter a self-reinforcing
# 300-second strategy cooldown even after the original dispatch/authority bug
# had been repaired.
_NEUTRAL_ERROR_SUBSTRINGS: FrozenSet[str] = frozenset({
    "orderfeasibility deny: [deterministic] strategy suppressed",
    "strategy suppressed for",
    "dispatch.enabled",
    "dispatch_scope_missing",
    "dispatch scope missing",
    "dispatch_scope_bridged",
    "execution authority violation",
    "executionauthority reject",
    "execution_authority_blocked",
    "execution_authority_runtime",
    "broker order submission blocked",
    "order submission blocked (reason=dispatch.enabled)",
    "fatal: execution authority violation",
    "runtime authority convergence lost",
    "seak halted",
    "state_machine=emergency_stop",
    "blocked by state_machine",
    "trading blocked",
    "broker_empty_response",
    "empty broker response",
    "empty broker result",
    "unknown exchange rejection",
    "ecel failure — invalid order escaped",
    "ecel failure - invalid order escaped",
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

# Suppression durations.  Keep defaults conservative but configurable so live
# ops can tune without a code change.
def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


TRANSIENT_SUPPRESS_S: float = max(0.0, _float_env("NIJA_OBSERVER_TRANSIENT_SUPPRESS_S", 5.0))
DETERMINISTIC_SUPPRESS_S: float = max(5.0, _float_env("NIJA_OBSERVER_DETERMINISTIC_SUPPRESS_S", 300.0))


def classify_error(error: str) -> str:
    """Return ``'transient'``, ``'neutral'``, ``'deterministic'``, or ``'unknown'``.

    Classification is case-insensitive substring matching.  Transient patterns
    are checked first so that a generic "timeout" in an ACK-timeout message is
    not accidentally promoted to deterministic.  Neutral internal blockers are
    checked before deterministic patterns so repaired authority/dispatch issues
    cannot trigger strategy-wide deterministic cooldowns.
    """
    if not error:
        return "unknown"
    low = error.lower()
    for substr in _TRANSIENT_ERROR_SUBSTRINGS:
        if substr in low:
            return "transient"
    for substr in _NEUTRAL_ERROR_SUBSTRINGS:
        if substr in low:
            return "neutral"
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
    # Only deterministic failures count toward consecutive_failures.
    # Transient, neutral, and unknown failures are tracked separately and never
    # trigger long strategy suppression.
    consecutive_failures: int = 0
    consecutive_transient_failures: int = 0
    consecutive_neutral_failures: int = 0
    consecutive_unknown_failures: int = 0
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

    **Neutral/internal errors** (dispatch-scope misses, authority convergence,
    observer self-suppression messages, blank broker results that never reached
    a real exchange boundary) do not trigger strategy suppression.

    **Deterministic errors** (``order_compilation_failed``,
    ``target_geometry_tp_too_small``, ``quantity_rounds_to_zero``,
    ``no_contract_rule``, ``below_min_notional``, etc.) indicate a logic or
    geometry problem that will not resolve by itself.  After
    ``DETERMINISTIC_CONSECUTIVE_THRESHOLD`` (default 3) consecutive
    deterministic failures the strategy is suppressed for
    :data:`DETERMINISTIC_SUPPRESS_S` seconds (default 300 s).
    """

    # Number of consecutive deterministic failures before long suppression.
    DETERMINISTIC_CONSECUTIVE_THRESHOLD: int = int(
        _float_env("NIJA_OBSERVER_DETERMINISTIC_THRESHOLD", 3.0)
    )

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

    def reset_strategy_suppression(self, strategy: str, *, reason: str = "manual_reset") -> bool:
        """Clear strategy-wide suppression without touching broker/risk gates."""
        if not strategy:
            return False
        with self._lock:
            stats = self._stats.get(strategy)
            if stats is None:
                return False
            if stats.suppressed_until <= 0 and stats.consecutive_failures <= 0:
                return False
            stats.suppressed_until = 0.0
            stats.consecutive_failures = 0
            logger.warning(
                "ExecutionObserver: reset strategy suppression strategy=%s reason=%s",
                strategy,
                reason,
            )
            return True

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
            the failure as transient, neutral, deterministic, or unknown.
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
                stats.consecutive_neutral_failures = 0
                stats.consecutive_unknown_failures = 0
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

            elif error_class == "neutral":
                # Internal/non-exchange failure: do not suppress strategy or symbol.
                # Clear deterministic streak because this failure cannot prove the
                # strategy itself is invalid.
                stats.consecutive_neutral_failures += 1
                if stats.consecutive_failures:
                    logger.warning(
                        "🟦 [NEUTRAL] ExecutionObserver: clearing deterministic streak for strategy=%s "
                        "after non-exchange/internal error=%r previous_det_failures=%d",
                        strategy,
                        error,
                        stats.consecutive_failures,
                    )
                stats.consecutive_failures = 0
                logger.info(
                    "🟦 [NEUTRAL] ExecutionObserver: strategy=%s symbol=%s side=%s "
                    "internal/non-exchange error=%r — no strategy suppression",
                    strategy,
                    symbol,
                    side,
                    error,
                )

            elif error_class == "unknown":
                # Unknown is not proof of deterministic strategy failure. Apply a
                # short symbol-only pause to avoid a hot loop, but never trip the
                # strategy-wide deterministic cooldown.
                stats.consecutive_unknown_failures += 1
                until = time.time() + TRANSIENT_SUPPRESS_S
                stats.transient_symbol_suppressed_until[symbol] = until
                logger.warning(
                    "🟨 [UNKNOWN] ExecutionObserver: strategy=%s symbol=%s side=%s error=%r — "
                    "symbol-only %.0fs pause, strategy suppression NOT triggered",
                    strategy,
                    symbol,
                    side,
                    error,
                    TRANSIENT_SUPPRESS_S,
                )

            else:
                # Deterministic failure: count toward long suppression.
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
            # Transient/neutral/unknown failures are excluded from the success-rate
            # denominator so infrastructure/internal blips do not erode allocation.
            total = stats.successes + stats.failures  # failures = deterministic only
            success_rate = (stats.successes / total) if total > 0 else 0.5
            stats.allocation_multiplier = max(0.5, min(1.5, 0.5 + success_rate))

            logger.info(
                "ExecutionObserver: strategy=%s symbol=%s side=%s success=%s "
                "size=$%.2f alloc_mult=%.2f det_failures=%d transient_failures=%d "
                "neutral_failures=%d unknown_failures=%d error_class=%s error=%s",
                strategy,
                symbol,
                side,
                success,
                size_usd,
                stats.allocation_multiplier,
                stats.consecutive_failures,
                stats.consecutive_transient_failures,
                stats.consecutive_neutral_failures,
                stats.consecutive_unknown_failures,
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
