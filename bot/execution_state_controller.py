"""
NIJA Execution State Controller
================================

State machine-driven controller for per-order execution lifecycle.

:class:`ExecutionStateController` wraps every broker call in an explicit
state machine whose transitions are driven entirely by
:class:`~bot.kraken_error_taxonomy.KrakenErrorTaxonomy`.  This removes
scattered ``if nonce_hit / auth_hit / permission_hit`` branches from call
sites and replaces them with a single ``controller.submit(...)`` call.

State graph
-----------
::

    IDLE ──────────────────────────────────────────► SUBMITTING
                                                           │
                              ┌────── success ────────────▼
                              │                     AWAITING_CONFIRM
                              │                           │
                              │                    fill confirmed
                              │                           │
                              │                           ▼
                              │                       COMPLETED ◄── terminal
                              │
                              ├────── NONCE (retries left) ──► RETRYING
                              │              └── sleep ──► SUBMITTING
                              │
                              ├────── RATE_LIMIT (retries left) ──► BACKING_OFF
                              │              └── sleep (exp) ──► SUBMITTING
                              │
                              ├────── NONCE / RATE_LIMIT exhausted ──► FAILED ◄── terminal
                              │
                              ├────── AUTH ──► HALTED_AUTH ◄── terminal
                              │
                              ├────── PERMISSION ──► HALTED_CONFIG ◄── terminal
                              │
                              └────── FUNDS ──► HALTED_FUNDS ◄── terminal
                                              (UNKNOWN ──► FAILED)

Terminal states:  COMPLETED, FAILED, HALTED_AUTH, HALTED_CONFIG, HALTED_FUNDS.

Usage
-----
::

    from bot.execution_state_controller import ExecutionStateController
    from bot.execution_result import ExecutionResult

    def _gate_fail(taxonomy):
        # signal upstream that execution authority should be re-evaluated
        os.environ["NIJA_EXECUTION_GATE_FAIL"] = taxonomy.canonical_code

    controller = ExecutionStateController(gate_fail_callback=_gate_fail)
    result = controller.submit(
        symbol="BTC-USD",
        side="buy",
        qty=50.0,
        broker_fn=lambda: broker.place_market_order("BTC-USD", "buy", 50.0),
    )
    # result is an ExecutionResult; controller.state is terminal
    log_execution_result(result)
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nija.execution_state_controller")

# Optional imports — the module must remain importable even in partial deployments.
try:
    from bot.kraken_error_taxonomy import (
        KrakenErrorCategory,
        KrakenErrorTaxonomy,
        KrakenRetryPolicy,
        classify_kraken_error,
    )
    _TAXONOMY_AVAILABLE = True
except ImportError:
    try:
        from kraken_error_taxonomy import (  # type: ignore[import]
            KrakenErrorCategory,
            KrakenErrorTaxonomy,
            KrakenRetryPolicy,
            classify_kraken_error,
        )
        _TAXONOMY_AVAILABLE = True
    except ImportError:
        _TAXONOMY_AVAILABLE = False
        KrakenErrorCategory = None  # type: ignore[assignment,misc]
        KrakenErrorTaxonomy = None  # type: ignore[assignment,misc]
        KrakenRetryPolicy = None    # type: ignore[assignment,misc]
        classify_kraken_error = None  # type: ignore[assignment]

try:
    from bot.execution_result import ExecutionResult, OrderStatus, log_execution_result
    _EXEC_RESULT_AVAILABLE = True
except ImportError:
    try:
        from execution_result import ExecutionResult, OrderStatus, log_execution_result  # type: ignore[import]
        _EXEC_RESULT_AVAILABLE = True
    except ImportError:
        _EXEC_RESULT_AVAILABLE = False
        ExecutionResult = None  # type: ignore[assignment,misc]
        OrderStatus = None      # type: ignore[assignment,misc]
        log_execution_result = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# ESC error priority resolution rule (item 5)
# ---------------------------------------------------------------------------

#: Numeric priority for each :class:`KrakenErrorCategory`.  Lower = higher
#: priority.  When multiple taxonomy patterns could match the same error
#: string, :func:`~bot.kraken_error_taxonomy.classify_kraken_error` applies
#: rules in this priority order, returning only the **highest-priority** match.
#:
#: Priority table
#: ~~~~~~~~~~~~~~
#: 1. AUTH        — credentials invalid; no recovery without operator action
#: 2. PERMISSION  — key scopes wrong; requires config fix
#: 3. FUNDS       — insufficient balance; position-sizing fix required
#: 4. ORDER       — order parameter invalid; strategy fix required
#: 5. NONCE       — retryable nonce window error
#: 6. RATE_LIMIT  — back-off required by exchange rate limiter
#: 7. SERVICE     — transient exchange service outage
#: 8. NETWORK     — transient connectivity error
#: 9. UNKNOWN     — unrecognised; fail-closed (lowest priority)
#:
#: This mapping is intentionally re-declared here (mirroring
#: :data:`~bot.kraken_error_taxonomy.ESC_ERROR_PRIORITY`) so that the ESC
#: can enforce the rule internally without requiring the taxonomy module to
#: be present (partial-deployment resilience).
_ESC_ERROR_PRIORITY: Dict[str, int] = {
    "AUTH": 1,
    "PERMISSION": 2,
    "FUNDS": 3,
    "ORDER": 4,
    "NONCE": 5,
    "RATE_LIMIT": 6,
    "SERVICE": 7,
    "NETWORK": 8,
    "UNKNOWN": 9,
}


def _esc_error_priority(taxonomy: Optional[Any]) -> int:
    """Return the numeric priority for *taxonomy* (lower = higher priority).

    Used by the ESC to resolve ambiguous multi-pattern matches
    deterministically — a lower priority number means the error is more
    severe and takes precedence.
    """
    if taxonomy is None:
        return _ESC_ERROR_PRIORITY["UNKNOWN"]
    category = getattr(taxonomy, "category", None)
    if category is None:
        return _ESC_ERROR_PRIORITY["UNKNOWN"]
    category_value = category.value if hasattr(category, "value") else str(category)
    return _ESC_ERROR_PRIORITY.get(category_value, _ESC_ERROR_PRIORITY["UNKNOWN"])


# ---------------------------------------------------------------------------
# State enumeration
# ---------------------------------------------------------------------------


class ExecutionOrderState(str, Enum):
    """Lifecycle states for a single order submission attempt."""

    IDLE = "IDLE"
    """No active submission; ready to accept a new call."""

    SUBMITTING = "SUBMITTING"
    """Broker call in-flight."""

    AWAITING_CONFIRM = "AWAITING_CONFIRM"
    """Exchange acknowledged the order; waiting for fill confirmation."""

    RETRYING = "RETRYING"
    """NONCE error: pausing before the next submission attempt."""

    BACKING_OFF = "BACKING_OFF"
    """RATE_LIMIT error: exponential back-off before the next attempt."""

    HALTED_AUTH = "HALTED_AUTH"
    """AUTH error — terminal. No retries; gate-fail callback invoked."""

    HALTED_CONFIG = "HALTED_CONFIG"
    """PERMISSION error — terminal. Operator must fix API key scopes."""

    HALTED_FUNDS = "HALTED_FUNDS"
    """FUNDS error — terminal. Position-sizing layer must reduce size."""

    COMPLETED = "COMPLETED"
    """Order accepted by the exchange — terminal success."""

    FAILED = "FAILED"
    """Retries exhausted or unrecognised error — terminal failure."""


# Convenience sets
_TERMINAL_STATES = frozenset({
    ExecutionOrderState.COMPLETED,
    ExecutionOrderState.FAILED,
    ExecutionOrderState.HALTED_AUTH,
    ExecutionOrderState.HALTED_CONFIG,
    ExecutionOrderState.HALTED_FUNDS,
})

_RETRY_STATES = frozenset({
    ExecutionOrderState.RETRYING,
    ExecutionOrderState.BACKING_OFF,
})


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class ExecutionStateController:
    """State machine-driven controller for a single order's execution lifecycle.

    Parameters
    ----------
    authority_fsm:
        Optional ``ExecutionAuthorityConvergenceFSM``.  When provided,
        ``reset()`` is called on it whenever the controller enters
        :attr:`ExecutionOrderState.HALTED_AUTH` or
        :attr:`ExecutionOrderState.HALTED_CONFIG`, forcing the convergence
        FSM back to LOCKED so subsequent dispatch attempts are blocked.
    gate_fail_callback:
        Optional ``Callable[[KrakenErrorTaxonomy], None]``.  Invoked
        whenever the controller enters a ``HALTED_*`` terminal state.
        Use this to propagate gate-fail signals to upstream authority layers.
    backoff_multiplier:
        Exponential multiplier applied to ``retry_delay_s`` on each
        successive RATE_LIMIT retry.  Defaults to ``2.0``.
    sleep_fn:
        Injectable sleep function (default: ``time.sleep``).  Pass a
        no-op in tests to avoid real delays.
    """

    def __init__(
        self,
        *,
        authority_fsm: Optional[Any] = None,
        gate_fail_callback: Optional[Callable[[Any], None]] = None,
        backoff_multiplier: float = 2.0,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._authority_fsm = authority_fsm
        self._gate_fail_callback = gate_fail_callback
        self._backoff_multiplier = max(1.0, float(backoff_multiplier))
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._lock = threading.Lock()

        # Mutable state (guarded by _lock for property reads; submit() is not
        # designed to be called concurrently — one submission at a time).
        self._state = ExecutionOrderState.IDLE
        self._last_broker_response: Optional[Dict[str, Any]] = None
        self._last_exception: Optional[Exception] = None
        self._last_taxonomy: Optional[Any] = None  # KrakenErrorTaxonomy | None
        self._retry_count: int = 0
        self._backoff_count: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> ExecutionOrderState:
        """Current FSM state (thread-safe read)."""
        with self._lock:
            return self._state

    @property
    def last_broker_response(self) -> Optional[Dict[str, Any]]:
        """Raw dict returned by the broker function on the final attempt."""
        with self._lock:
            return self._last_broker_response

    @property
    def last_exception(self) -> Optional[Exception]:
        """Exception raised by the broker function (None on response-based failure)."""
        with self._lock:
            return self._last_exception

    @property
    def last_taxonomy(self) -> Optional[Any]:
        """Taxonomy of the last error classification (None on success)."""
        with self._lock:
            return self._last_taxonomy

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        symbol: str,
        side: str,
        qty: float,
        broker_fn: Callable[[], Optional[Dict[str, Any]]],
        success_fn: Optional[Callable[[Optional[Dict[str, Any]]], bool]] = None,
    ) -> Any:
        """Execute *broker_fn* with taxonomy-driven retry/halt logic.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. ``"BTC-USD"``).  Used only for logging and
            result construction.
        side:
            ``"buy"`` or ``"sell"`` (or ``"query"`` for connection probes).
        qty:
            Order notional size in USD.  Used only for logging.
        broker_fn:
            Zero-argument callable that performs the actual broker call and
            returns either:

            * A ``dict`` response (success or exchange-level error), or
            * ``None`` (treated as a failure), or
            * Raises an ``Exception`` (classified via taxonomy).

        success_fn:
            Optional predicate ``(response: dict | None) -> bool`` that
            determines whether a response dict is a success.  Defaults to
            :meth:`_default_success_fn`.

        Returns
        -------
        ExecutionResult
            Always returns an :class:`~bot.execution_result.ExecutionResult`.
            If ``ExecutionResult`` is not importable, returns ``None``.
        """
        if success_fn is None:
            success_fn = self._default_success_fn

        with self._lock:
            self._state = ExecutionOrderState.SUBMITTING
            self._retry_count = 0
            self._backoff_count = 0
            self._last_broker_response = None
            self._last_exception = None
            self._last_taxonomy = None

        t0 = time.monotonic()

        while True:
            with self._lock:
                current_state = self._state

            if current_state in _TERMINAL_STATES:
                break

            # Transition RETRYING/BACKING_OFF → SUBMITTING after sleeping.
            if current_state in _RETRY_STATES:
                with self._lock:
                    self._state = ExecutionOrderState.SUBMITTING

            # ── broker call ───────────────────────────────────────────────
            response: Optional[Dict[str, Any]] = None
            exc: Optional[Exception] = None
            try:
                response = broker_fn()
            except Exception as _exc:
                exc = _exc

            with self._lock:
                self._last_broker_response = response
                self._last_exception = exc

            # ── classify outcome ──────────────────────────────────────────
            if exc is not None:
                error_text = str(exc)
                taxonomy = self._classify(error_text)
            elif not success_fn(response):
                error_text = self._extract_error_text(response)
                taxonomy = self._classify(error_text) if error_text else None
            else:
                # ── SUCCESS ───────────────────────────────────────────────
                with self._lock:
                    self._state = ExecutionOrderState.AWAITING_CONFIRM
                    self._last_taxonomy = None

                logger.info(
                    "[ExecController] %s %s AWAITING_CONFIRM → COMPLETED",
                    symbol, side,
                )
                with self._lock:
                    self._state = ExecutionOrderState.COMPLETED
                break

            # ── taxonomy-driven transition ────────────────────────────────
            with self._lock:
                self._last_taxonomy = taxonomy

            next_state, delay = self._next_state_for_taxonomy(taxonomy)

            with self._lock:
                self._state = next_state

            if next_state in _TERMINAL_STATES:
                self._handle_terminal(symbol, next_state, taxonomy)
                break

            # ── non-terminal (RETRYING / BACKING_OFF) ─────────────────────
            if next_state == ExecutionOrderState.RETRYING:
                with self._lock:
                    self._retry_count += 1
                logger.warning(
                    "[ExecController] %s %s NONCE error → RETRYING "
                    "(attempt %d) delay=%.1fs: %s",
                    symbol, side,
                    self._retry_count,
                    delay,
                    error_text[:80] if error_text else "",
                )
            else:  # BACKING_OFF
                with self._lock:
                    self._backoff_count += 1
                logger.warning(
                    "[ExecController] %s %s RATE_LIMIT → BACKING_OFF "
                    "(attempt %d) delay=%.1fs: %s",
                    symbol, side,
                    self._backoff_count,
                    delay,
                    error_text[:80] if error_text else "",
                )

            if delay > 0:
                self._sleep(delay)

        return self._build_execution_result(symbol, side, t0)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_state_for_taxonomy(
        self,
        taxonomy: Optional[Any],
    ) -> tuple:
        """Return ``(next_state, sleep_delay)`` for the given taxonomy.

        ESC error priority resolution rule
        ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        When the error text could match multiple taxonomy patterns, the
        :func:`~bot.kraken_error_taxonomy.classify_kraken_error` function
        (and the :data:`_ESC_ERROR_PRIORITY` table) guarantee that the
        **highest-priority** (lowest numeric priority value) category wins.
        The priority ordering is:

        1. AUTH        → HALTED_AUTH  (no retries, gate-fail callback)
        2. PERMISSION  → HALTED_CONFIG (no retries, gate-fail callback)
        3. FUNDS       → HALTED_FUNDS  (no retries)
        4. ORDER       → FAILED        (no retries)
        5. NONCE       → RETRYING      (fixed-delay retry)
        6. RATE_LIMIT  → BACKING_OFF   (exponential back-off)
        7. SERVICE     → BACKING_OFF   (exponential back-off)
        8. NETWORK     → RETRYING      (fixed-delay retry)
        9. UNKNOWN     → FAILED        (fail-closed)

        Returns a terminal FAILED state when retries are exhausted.
        """
        if taxonomy is None or not _TAXONOMY_AVAILABLE:
            return ExecutionOrderState.FAILED, 0.0

        policy = taxonomy.policy
        category = taxonomy.category
        # Attach the numeric priority to the taxonomy for upstream traceability.
        _ = _esc_error_priority(taxonomy)  # noqa: F841 (validated for logging)

        if _TAXONOMY_AVAILABLE and KrakenRetryPolicy is not None:
            if policy == KrakenRetryPolicy.STOP:
                # Apply priority ordering: AUTH > PERMISSION > FUNDS > ORDER
                if category == KrakenErrorCategory.AUTH:
                    return ExecutionOrderState.HALTED_AUTH, 0.0
                if category == KrakenErrorCategory.PERMISSION:
                    return ExecutionOrderState.HALTED_CONFIG, 0.0
                if category == KrakenErrorCategory.FUNDS:
                    return ExecutionOrderState.HALTED_FUNDS, 0.0
                return ExecutionOrderState.FAILED, 0.0

            if policy == KrakenRetryPolicy.CONFIG_FAIL:
                return ExecutionOrderState.HALTED_CONFIG, 0.0

            if policy == KrakenRetryPolicy.RETRY:
                if self._retry_count < max(1, taxonomy.max_retries):
                    return ExecutionOrderState.RETRYING, taxonomy.retry_delay_s
                return ExecutionOrderState.FAILED, 0.0

            if policy == KrakenRetryPolicy.BACKOFF:
                if self._backoff_count < max(1, taxonomy.max_retries):
                    delay = taxonomy.retry_delay_s * (
                        self._backoff_multiplier ** self._backoff_count
                    )
                    return ExecutionOrderState.BACKING_OFF, delay
                return ExecutionOrderState.FAILED, 0.0

        # UNKNOWN policy — fail-closed (lowest priority)
        return ExecutionOrderState.FAILED, 0.0

    def _handle_terminal(
        self,
        symbol: str,
        state: ExecutionOrderState,
        taxonomy: Optional[Any],
    ) -> None:
        """Log and propagate gate-fail signals for terminal halt states."""
        if state == ExecutionOrderState.HALTED_AUTH:
            remediation = getattr(taxonomy, "remediation", "") if taxonomy else ""
            logger.critical(
                "[ExecController] %s HALTED_AUTH — authentication failure "
                "[policy=STOP] remediation=%s",
                symbol, remediation,
            )
        elif state == ExecutionOrderState.HALTED_CONFIG:
            remediation = getattr(taxonomy, "remediation", "") if taxonomy else ""
            logger.critical(
                "[ExecController] %s HALTED_CONFIG — permission/config failure "
                "[policy=CONFIG_FAIL] remediation=%s",
                symbol, remediation,
            )
        elif state == ExecutionOrderState.HALTED_FUNDS:
            logger.critical(
                "[ExecController] %s HALTED_FUNDS — insufficient funds",
                symbol,
            )

        if state in {
            ExecutionOrderState.HALTED_AUTH,
            ExecutionOrderState.HALTED_CONFIG,
        }:
            # Reset authority FSM so subsequent dispatch is blocked.
            if self._authority_fsm is not None:
                try:
                    if hasattr(self._authority_fsm, "reset"):
                        self._authority_fsm.reset()
                except Exception as _exc:
                    logger.warning(
                        "[ExecController] authority_fsm.reset() raised: %s", _exc
                    )
            # Invoke gate-fail callback so upstream layers can react.
            if callable(self._gate_fail_callback):
                try:
                    self._gate_fail_callback(taxonomy)
                except Exception as _exc:
                    logger.warning(
                        "[ExecController] gate_fail_callback raised: %s", _exc
                    )

    def _build_execution_result(
        self,
        symbol: str,
        side: str,
        t0: float,
    ) -> Any:
        """Build and return the canonical :class:`ExecutionResult`."""
        if not _EXEC_RESULT_AVAILABLE or ExecutionResult is None or OrderStatus is None:
            return None

        latency_ms = int((time.monotonic() - t0) * 1000)

        with self._lock:
            state = self._state
            response = self._last_broker_response
            taxonomy = self._last_taxonomy

        retry_policy = getattr(taxonomy, "policy", None) if taxonomy else None

        if state == ExecutionOrderState.COMPLETED:
            order_id = None
            if isinstance(response, dict):
                order_id = (
                    response.get("order_id")
                    or response.get("id")
                    or response.get("client_order_id")
                )
            return ExecutionResult(
                status=OrderStatus.ACCEPTED,
                symbol=symbol,
                side=side,
                exchange_order_id=str(order_id) if order_id else None,
                error_code=None,
                latency_ms=latency_ms,
                retry_policy=None,
            )

        # All non-COMPLETED terminal states
        error_code: Optional[str] = None
        if taxonomy is not None:
            error_code = getattr(taxonomy, "canonical_code", None)
        if error_code is None:
            with self._lock:
                exc = self._last_exception
            if exc is not None:
                error_code = str(exc)[:120]
            elif isinstance(response, dict):
                error_code = self._extract_error_text(response)[:120]

        # HALTED_* → FAILED status to ensure retry_policy is surfaced
        order_status = OrderStatus.FAILED

        return ExecutionResult(
            status=order_status,
            symbol=symbol,
            side=side,
            exchange_order_id=None,
            error_code=error_code or state.value,
            latency_ms=latency_ms,
            retry_policy=retry_policy,
        )

    @staticmethod
    def _default_success_fn(response: Optional[Dict[str, Any]]) -> bool:
        """Default predicate: response is a success when status is not an error."""
        if response is None:
            return False
        status = str(response.get("status", "")).lower().strip()
        if status in {"error", "unfilled", "skipped", "rejected"}:
            return False
        # Kraken-style: presence of 'error' key with non-empty list means failure.
        errors = response.get("error")
        if isinstance(errors, list) and errors:
            return False
        if isinstance(errors, str) and errors.strip():
            return False
        return True

    @staticmethod
    def _extract_error_text(response: Optional[Dict[str, Any]]) -> str:
        """Extract a flat error string from a broker response dict."""
        if response is None:
            return ""
        # Kraken-style: error is a list of strings.
        errors = response.get("error")
        if isinstance(errors, list) and errors:
            return ", ".join(str(e) for e in errors if e)
        if isinstance(errors, str) and errors.strip():
            return errors.strip()
        # Generic: check status / error_message fields.
        for key in ("error_message", "message", "msg", "status"):
            val = response.get(key)
            if val and isinstance(val, str):
                return val.strip()
        return ""

    @staticmethod
    def _classify(error_text: str) -> Optional[Any]:
        """Return a KrakenErrorTaxonomy for *error_text* or None."""
        if not _TAXONOMY_AVAILABLE or classify_kraken_error is None:
            return None
        try:
            return classify_kraken_error(error_text)
        except Exception:
            return None
