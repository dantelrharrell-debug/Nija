"""
NIJA Single Execution Authority Kernel (SEAK)
=============================================

The Single Execution Authority Kernel is the **one and only** pathway through
which any trade order may reach an exchange.  All other execution helpers
(ExecutionPipeline, ExecutionRouter, ExecutionEngine, …) must ultimately route
through SEAK; they must never call broker APIs directly.

Why this matters
----------------
The NIJA codebase has grown to include 15+ execution-layer modules.  Without a
central authority, multiple paths can fire simultaneously for the same symbol,
leading to:

* Double-entry (two BUY orders for BTC-USD in the same millisecond)
* Race conditions between ExecutionPipeline and direct broker calls
* Bypassed guards (throttler, hardening, health monitor)
* Inconsistent audit trail

SEAK solves this by enforcing the following invariants:

1. **Single lock point** — a per-symbol ``threading.Lock`` ensures that only
   one order is in-flight for any given symbol at a time.
2. **Claim / release protocol** — callers ``acquire()`` a slot before
   submitting an order; the kernel tracks who holds each slot.
3. **Request fingerprinting** — every execution request is assigned a UUID and
   a content fingerprint; duplicate submissions within the dedup window are
   rejected immediately without touching the exchange.
4. **Authority token** — a short-lived token is issued to the caller that
   claimed the slot; downstream adapters should verify the token before
   executing.
5. **Guard chain** — SEAK runs an ordered guard chain before issuing a token::

       a. Emergency halt check
       b. ExecutionHealthMonitor  (is the exchange API degraded?)
       c. TradeDuplicationGuard   (was this exact fingerprint seen recently?)
       d. ExecutionLayerHardening (position caps, minimum notional, …)

6. **Audit log** — every decision (APPROVED / REJECTED) is written to an
   in-memory ring buffer and optionally to disk, giving a complete audit trail.
7. **Emergency halt** — ``emergency_halt()`` atomically blocks ALL new claims;
   ``resume()`` re-enables them.

Singleton
---------
::

    from bot.single_execution_authority_kernel import get_seak

    seak = get_seak()

High-level API (preferred)
--------------------------
::

    token = seak.acquire(
        strategy="ApexTrend",
        symbol="BTC-USD",
        side="buy",
        size_usd=500.0,
        caller="ApexStrategyV71",
    )

    if not token.granted:
        logger.warning("SEAK rejected: %s", token.reason)
        return

    try:
        broker.place_order(...)
    finally:
        seak.release(token)

Low-level slot API (for callers that cannot easily adopt acquire/release)
-------------------------------------------------------------------------
::

    slot = seak.claim_execution_slot(symbol="BTC-USD", caller="strategy_X")
    if not slot.granted:
        return
    try:
        ...
    finally:
        seak.release_execution_slot(slot)

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("nija.seak")

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Maximum seconds a claimed slot may be held before it is force-released.
_SLOT_TIMEOUT_S: float = 30.0

# Dedup window — requests with the same fingerprint within this window are
# rejected as duplicates (seconds).
_DEDUP_WINDOW_S: float = 60.0

# Maximum number of audit entries kept in the ring buffer.
_AUDIT_RING_SIZE: int = 2_000

# Maximum number of per-symbol lock objects kept (auto-evicted after slots
# are released when total exceeds this threshold).
_MAX_SYMBOL_LOCKS: int = 500


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RejectionReason(str, Enum):
    EMERGENCY_HALT = "EMERGENCY_HALT"
    EXCHANGE_UNHEALTHY = "EXCHANGE_UNHEALTHY"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    HARDENING_VIOLATION = "HARDENING_VIOLATION"
    SLOT_BUSY = "SLOT_BUSY"
    SLOT_TIMEOUT = "SLOT_TIMEOUT"
    INVALID_REQUEST = "INVALID_REQUEST"
    # Guard 6: fires only when a named CRITICAL broker is dead.
    # OPTIONAL broker failures NEVER trigger this code.
    BROKER_CRITICALITY_VIOLATION = "BROKER_CRITICALITY_VIOLATION"


class AuditOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"
    FORCE_RELEASED = "FORCE_RELEASED"
    HALT = "HALT"
    RESUME = "RESUME"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExecutionRequest:
    """Describes a single trade the caller wishes to execute."""

    symbol: str
    side: str          # "buy" / "sell"
    size_usd: float
    strategy: str = ""
    caller: str = ""   # module / class that is requesting execution
    order_type: Optional[str] = None
    account_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    # Auto-assigned by SEAK on receipt; do not set manually.
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    received_at: float = field(default_factory=time.monotonic)


@dataclass
class ExecutionToken:
    """
    Returned by ``SEAK.acquire()``.

    When ``granted=True`` the caller has exclusive execution authority for the
    requested symbol.  The token **must** be passed back to ``SEAK.release()``
    when execution completes (or fails), regardless of the outcome.

    When ``granted=False`` the caller must not submit any order.
    """

    granted: bool
    request_id: str
    symbol: str
    side: str
    size_usd: float
    strategy: str = ""
    caller: str = ""
    reason: str = ""
    rejection_reason: Optional[RejectionReason] = None
    issued_at: float = field(default_factory=time.monotonic)
    expires_at: float = field(default_factory=lambda: time.monotonic() + _SLOT_TIMEOUT_S)
    # Internal — used by release() to locate and free the per-symbol lock.
    _slot_key: str = field(default="", repr=False)


@dataclass
class ExecutionSlot:
    """
    Low-level slot object returned by ``claim_execution_slot()``.

    Mirrors ExecutionToken but is named differently to distinguish the
    lower-level API.
    """

    granted: bool
    symbol: str
    caller: str
    request_id: str
    reason: str = ""
    rejection_reason: Optional[RejectionReason] = None
    acquired_at: float = field(default_factory=time.monotonic)
    expires_at: float = field(default_factory=lambda: time.monotonic() + _SLOT_TIMEOUT_S)
    _slot_key: str = field(default="", repr=False)


@dataclass
class AuditEntry:
    """One record in the SEAK audit ring buffer."""

    ts: str                    # ISO-8601 timestamp
    outcome: AuditOutcome
    request_id: str
    symbol: str
    side: str
    size_usd: float
    strategy: str
    caller: str
    reason: str
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Internal: per-symbol slot tracker
# ---------------------------------------------------------------------------


@dataclass
class _SymbolSlot:
    """Tracks the active holder for a single symbol."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    holder_request_id: Optional[str] = None
    acquired_at: float = 0.0
    expires_at: float = 0.0


# ---------------------------------------------------------------------------
# Single Execution Authority Kernel
# ---------------------------------------------------------------------------


class SingleExecutionAuthorityKernel:
    """
    Central execution authority.  All trade orders must pass through this
    kernel before reaching a broker/exchange.

    Thread-safe.  Singleton via :func:`get_seak`.
    """

    def __init__(self) -> None:
        # Master gate — when set, all new acquisitions are blocked.
        self._halt_event: threading.Event = threading.Event()
        self._halt_reason: str = ""

        # Per-symbol slot registry.
        self._slots_lock: threading.Lock = threading.Lock()
        self._slots: Dict[str, _SymbolSlot] = {}

        # Fingerprint dedup registry.
        self._dedup_lock: threading.Lock = threading.Lock()
        self._dedup_registry: Dict[str, float] = {}  # fingerprint → expiry_ts
        # Side-table: symbol → active fingerprint (for fast clear-on-release).
        self._active_fp_by_symbol: Dict[str, str] = {}

        # Audit ring buffer.
        self._audit_lock: threading.Lock = threading.Lock()
        self._audit_log: Deque[AuditEntry] = deque(maxlen=_AUDIT_RING_SIZE)

        # Metrics.
        self._total_approved: int = 0
        self._total_rejected: int = 0
        self._total_released: int = 0
        self._total_force_released: int = 0

        # Optional subsystem handles (loaded lazily).
        self._health_monitor: Any = None
        self._health_loaded: bool = False
        self._dedup_guard: Any = None
        self._dedup_guard_loaded: bool = False
        self._hardening: Any = None
        self._hardening_loaded: bool = False
        # Guard 6: BrokerFailureManager for criticality checks.
        # OPTIONAL broker failures never trigger a rejection.
        self._bfm: Any = None
        self._bfm_loaded: bool = False

        # Background reaper for stale fingerprints and timed-out slots.
        self._reaper_thread = threading.Thread(
            target=self._reaper_loop, name="seak-reaper", daemon=True
        )
        self._reaper_thread.start()

        logger.info("SingleExecutionAuthorityKernel initialised — all execution must flow through SEAK")

    # ------------------------------------------------------------------
    # Public: emergency controls
    # ------------------------------------------------------------------

    def emergency_halt(self, reason: str = "emergency halt") -> None:
        """Block ALL new execution acquisitions immediately.

        Slots that are already held are not revoked — the current holder
        will complete its order.  Use :meth:`force_release_all` to also
        cancel in-flight slots.
        """
        self._halt_reason = reason
        self._halt_event.set()
        self._audit(
            outcome=AuditOutcome.HALT,
            request_id="",
            symbol="*",
            side="",
            size_usd=0.0,
            strategy="",
            caller="SEAK",
            reason=reason,
        )
        logger.critical("⛔ SEAK EMERGENCY HALT: %s", reason)

    def resume(self, caller: str = "operator") -> None:
        """Lift an emergency halt and allow new acquisitions again."""
        self._halt_event.clear()
        self._halt_reason = ""
        self._audit(
            outcome=AuditOutcome.RESUME,
            request_id="",
            symbol="*",
            side="",
            size_usd=0.0,
            strategy="",
            caller=caller,
            reason="SEAK resumed",
        )
        logger.info("✅ SEAK RESUMED by %s", caller)

    @property
    def is_halted(self) -> bool:
        """Return True when an emergency halt is active."""
        return self._halt_event.is_set()

    # ------------------------------------------------------------------
    # Public: high-level acquire / release
    # ------------------------------------------------------------------

    def acquire(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        strategy: str = "",
        caller: str = "",
        order_type: Optional[str] = None,
        account_id: str = "",
        extra: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> ExecutionToken:
        """Request exclusive execution authority for *symbol*.

        Parameters
        ----------
        symbol:
            Trading pair (e.g. ``"BTC-USD"``).
        side:
            ``"buy"`` or ``"sell"``.
        size_usd:
            Intended order size in USD.
        strategy:
            Name of the calling strategy for audit purposes.
        caller:
            Module or function requesting the slot.
        order_type:
            Optional order type hint (``"MARKET"``, ``"LIMIT"``, …).
        account_id:
            Optional account identifier.
        extra:
            Additional metadata passed through to the audit log.
        timeout:
            Seconds to wait for the per-symbol lock before giving up
            (``RejectionReason.SLOT_BUSY``).

        Returns
        -------
        ExecutionToken
            ``token.granted=True``  → caller may proceed with the order.
            ``token.granted=False`` → caller must NOT submit any order.
        """
        t_start = time.monotonic()
        request = ExecutionRequest(
            symbol=symbol.upper(),
            side=side.lower(),
            size_usd=size_usd,
            strategy=strategy,
            caller=caller,
            order_type=order_type,
            account_id=account_id,
            extra=extra or {},
        )

        def _reject(reason: str, code: RejectionReason) -> ExecutionToken:
            latency_ms = (time.monotonic() - t_start) * 1000
            self._audit(
                outcome=AuditOutcome.REJECTED,
                request_id=request.request_id,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                strategy=request.strategy,
                caller=request.caller,
                reason=reason,
                latency_ms=latency_ms,
            )
            with threading.Lock():
                self._total_rejected += 1
            return ExecutionToken(
                granted=False,
                request_id=request.request_id,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                strategy=strategy,
                caller=caller,
                reason=reason,
                rejection_reason=code,
            )

        # ── Validate request ─────────────────────────────────────────────
        if not request.symbol or not request.side or request.size_usd <= 0:
            return _reject(
                f"Invalid request: symbol={request.symbol!r} side={request.side!r} "
                f"size_usd={request.size_usd}",
                RejectionReason.INVALID_REQUEST,
            )

        # ── Guard 1: Emergency halt ──────────────────────────────────────
        if self._halt_event.is_set():
            return _reject(
                f"SEAK emergency halt active: {self._halt_reason}",
                RejectionReason.EMERGENCY_HALT,
            )

        # ── Guard 2: Exchange health ─────────────────────────────────────
        health_reject = self._check_health_guard(request)
        if health_reject:
            return _reject(health_reject, RejectionReason.EXCHANGE_UNHEALTHY)

        # ── Guard 3: Acquire per-symbol slot ─────────────────────────────
        # The slot lock is acquired BEFORE the dedup check so that a second
        # concurrent request for the same symbol correctly reports SLOT_BUSY
        # rather than DUPLICATE_REQUEST.  The dedup check (guard 4) then
        # catches the same-fingerprint case for requests that arrive after the
        # first has been released (i.e. the slot is free but the fingerprint
        # is still registered within the dedup window).
        slot_key = request.symbol
        slot = self._get_or_create_slot(slot_key)

        acquired = slot.lock.acquire(blocking=True, timeout=timeout)
        if not acquired:
            return _reject(
                f"Symbol {request.symbol} slot busy after {timeout:.1f}s timeout",
                RejectionReason.SLOT_BUSY,
            )

        now = time.monotonic()
        # Check whether the previous holder overstayed.
        if slot.holder_request_id and now > slot.expires_at:
            logger.warning(
                "SEAK: force-releasing timed-out slot for %s (holder=%s)",
                request.symbol,
                slot.holder_request_id,
            )
            self._total_force_released += 1

        # ── Guard 4: Deduplication (slot held) ───────────────────────────
        fingerprint = self._build_fingerprint(request)
        dup_reject = self._check_dedup(request, fingerprint)
        if dup_reject:
            # Release the slot immediately — we are not going to execute.
            slot.lock.release()
            return _reject(dup_reject, RejectionReason.DUPLICATE_REQUEST)

        # ── Guard 5: Execution layer hardening ───────────────────────────
        hardening_reject = self._check_hardening(request)
        if hardening_reject:
            slot.lock.release()
            return _reject(hardening_reject, RejectionReason.HARDENING_VIOLATION)

        # ── Guard 6: Broker criticality ──────────────────────────────────
        # Blocks BUY orders only when the explicitly named broker in
        # request.extra["broker"] is CRITICAL and currently dead.
        # Rules:
        #   • SELL / exit orders → always pass (positions must be closeable).
        #   • OPTIONAL broker failure → always pass (non-blocking by design).
        #   • CRITICAL broker dead → reject BUY until broker recovers.
        #   • No broker named in request → fail open (skip check).
        if request.side == "buy":
            crit_reject = self._check_broker_criticality(request)
            if crit_reject:
                slot.lock.release()
                return _reject(crit_reject, RejectionReason.BROKER_CRITICALITY_VIOLATION)

        slot.holder_request_id = request.request_id
        slot.acquired_at = now
        slot.expires_at = now + _SLOT_TIMEOUT_S

        # Register fingerprint so retries that arrive while this slot is
        # in-flight are rejected as duplicates.  The fingerprint is cleared
        # when the slot is released (see _release_slot).
        with self._dedup_lock:
            self._dedup_registry[fingerprint] = time.time() + _DEDUP_WINDOW_S
            self._active_fp_by_symbol[request.symbol] = fingerprint

        latency_ms = (time.monotonic() - t_start) * 1000
        self._audit(
            outcome=AuditOutcome.APPROVED,
            request_id=request.request_id,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            strategy=request.strategy,
            caller=request.caller,
            reason="",
            latency_ms=latency_ms,
        )
        self._total_approved += 1

        logger.debug(
            "SEAK APPROVED | id=%s | %s %s $%.2f | strategy=%s | caller=%s | %.1fms",
            request.request_id,
            request.side.upper(),
            request.symbol,
            request.size_usd,
            strategy,
            caller,
            latency_ms,
        )

        return ExecutionToken(
            granted=True,
            request_id=request.request_id,
            symbol=request.symbol,
            side=request.side,
            size_usd=request.size_usd,
            strategy=strategy,
            caller=caller,
            issued_at=now,
            expires_at=now + _SLOT_TIMEOUT_S,
            _slot_key=slot_key,
        )

    def release(self, token: ExecutionToken) -> None:
        """Release the execution slot held by *token*.

        Must be called in a ``finally`` block after every :meth:`acquire`
        that returned ``granted=True``.
        """
        if not token.granted:
            return  # Nothing to release for denied tokens.

        slot_key = token._slot_key or token.symbol
        self._release_slot(slot_key, token.request_id)

        self._audit(
            outcome=AuditOutcome.RELEASED,
            request_id=token.request_id,
            symbol=token.symbol,
            side=token.side,
            size_usd=token.size_usd,
            strategy=token.strategy,
            caller=token.caller,
            reason="",
            latency_ms=(time.monotonic() - token.issued_at) * 1000,
        )
        self._total_released += 1

    # ------------------------------------------------------------------
    # Public: low-level slot API
    # ------------------------------------------------------------------

    def claim_execution_slot(
        self,
        symbol: str,
        caller: str = "",
        timeout: float = 5.0,
    ) -> ExecutionSlot:
        """Acquire a per-symbol execution lock without running the full guard chain.

        Prefer :meth:`acquire` for new code.  This lower-level method is
        provided for existing callers that cannot easily adopt the token API
        but still need mutual exclusion.
        """
        symbol = symbol.upper()
        request_id = str(uuid.uuid4())

        if self._halt_event.is_set():
            return ExecutionSlot(
                granted=False,
                symbol=symbol,
                caller=caller,
                request_id=request_id,
                reason=f"SEAK emergency halt: {self._halt_reason}",
                rejection_reason=RejectionReason.EMERGENCY_HALT,
            )

        slot = self._get_or_create_slot(symbol)
        acquired = slot.lock.acquire(blocking=True, timeout=timeout)
        if not acquired:
            return ExecutionSlot(
                granted=False,
                symbol=symbol,
                caller=caller,
                request_id=request_id,
                reason=f"Symbol {symbol} slot busy after {timeout:.1f}s",
                rejection_reason=RejectionReason.SLOT_BUSY,
            )

        now = time.monotonic()
        slot.holder_request_id = request_id
        slot.acquired_at = now
        slot.expires_at = now + _SLOT_TIMEOUT_S

        return ExecutionSlot(
            granted=True,
            symbol=symbol,
            caller=caller,
            request_id=request_id,
            acquired_at=now,
            expires_at=now + _SLOT_TIMEOUT_S,
            _slot_key=symbol,
        )

    def release_execution_slot(self, slot: ExecutionSlot) -> None:
        """Release a slot obtained via :meth:`claim_execution_slot`."""
        if not slot.granted:
            return
        self._release_slot(slot._slot_key or slot.symbol, slot.request_id)

    # ------------------------------------------------------------------
    # Public: force release all active slots
    # ------------------------------------------------------------------

    def force_release_all(self, reason: str = "force release") -> int:
        """Forcibly release every active per-symbol lock.

        Returns the number of slots released.  Typically called after
        :meth:`emergency_halt` to also cancel any in-flight orders.
        """
        count = 0
        with self._slots_lock:
            for sym, slot in list(self._slots.items()):
                if slot.lock.locked():
                    try:
                        slot.lock.release()
                        slot.holder_request_id = None
                        count += 1
                        logger.warning("SEAK force-released slot for %s (%s)", sym, reason)
                    except RuntimeError:
                        pass
        # Clear fingerprints for all released symbols.
        if count:
            with self._dedup_lock:
                self._active_fp_by_symbol.clear()
                self._dedup_registry.clear()
        self._total_force_released += count
        return count

    # ------------------------------------------------------------------
    # Public: status / audit
    # ------------------------------------------------------------------

    def get_audit_log(self, last_n: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent *last_n* audit entries as plain dicts."""
        with self._audit_lock:
            entries = list(self._audit_log)
        entries = entries[-last_n:]
        return [
            {
                "ts": e.ts,
                "outcome": e.outcome.value,
                "request_id": e.request_id,
                "symbol": e.symbol,
                "side": e.side,
                "size_usd": e.size_usd,
                "strategy": e.strategy,
                "caller": e.caller,
                "reason": e.reason,
                "latency_ms": round(e.latency_ms, 2),
            }
            for e in entries
        ]

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of SEAK health and counters."""
        with self._slots_lock:
            active_slots = [
                sym for sym, s in self._slots.items() if s.holder_request_id is not None
            ]
        with self._dedup_lock:
            active_fingerprints = len(self._dedup_registry)

        return {
            "halted": self._halt_event.is_set(),
            "halt_reason": self._halt_reason,
            "active_slots": active_slots,
            "active_slot_count": len(active_slots),
            "active_fingerprints": active_fingerprints,
            "total_approved": self._total_approved,
            "total_rejected": self._total_rejected,
            "total_released": self._total_released,
            "total_force_released": self._total_force_released,
            "audit_log_size": len(self._audit_log),
            "guards": {
                "health_monitor": self._health_loaded,
                "dedup_guard": self._dedup_guard_loaded,
                "hardening": self._hardening_loaded,
                "broker_criticality": self._bfm_loaded,
            },
        }

    # ------------------------------------------------------------------
    # Internal: guard chain helpers
    # ------------------------------------------------------------------

    def _check_health_guard(self, request: ExecutionRequest) -> Optional[str]:
        """Return a rejection reason string if the exchange health gate blocks."""
        monitor = self._load_health_monitor()
        if monitor is None:
            return None
        try:
            decision = monitor.check()
            if not decision.allow_entries:
                return f"ExecutionHealthMonitor: {getattr(decision, 'reason', str(decision))}"
        except Exception as exc:
            logger.warning("SEAK: health monitor check failed: %s", exc)
        return None

    def _check_dedup(self, request: ExecutionRequest, fingerprint: str) -> Optional[str]:
        """Return a rejection reason string if this is a duplicate request."""
        # Internal dedup registry (faster, always available).
        now = time.time()
        with self._dedup_lock:
            expiry = self._dedup_registry.get(fingerprint)
            if expiry is not None and now < expiry:
                return (
                    f"Duplicate execution request within dedup window "
                    f"({_DEDUP_WINDOW_S:.0f}s): {request.symbol} {request.side}"
                )

        # External TradeDuplicationGuard (more sophisticated, optional).
        guard = self._load_dedup_guard()
        if guard is not None:
            try:
                allowed, reason = guard.check_and_register(
                    symbol=request.symbol,
                    side=request.side,
                    size=request.size_usd,
                    account_id=request.account_id or "",
                )
                if not allowed:
                    return f"TradeDuplicationGuard: {reason}"
            except Exception as exc:
                logger.warning("SEAK: dedup guard check failed: %s", exc)

        return None

    def _check_hardening(self, request: ExecutionRequest) -> Optional[str]:
        """Return a rejection reason string if the hardening layer blocks."""
        hardening = self._load_hardening()
        if hardening is None:
            return None
        if request.side not in ("buy", "sell"):
            return None  # Unknown side; let the broker validate.
        try:
            passed, reason, _ = hardening.validate_order_hardening(
                symbol=request.symbol,
                side=request.side.upper(),
                position_size_usd=request.size_usd,
                balance=0.0,          # 0 = skip balance-dependent checks
                current_positions=[],
                user_id=request.account_id or None,
                force_liquidate=(request.side == "sell"),
            )
            if not passed:
                return f"ExecutionLayerHardening: {reason}"
        except Exception as exc:
            logger.warning("SEAK: hardening check failed: %s", exc)
        return None

    def _check_broker_criticality(self, request: ExecutionRequest) -> Optional[str]:
        """Return a rejection reason when a named CRITICAL broker is dead.

        Guard 6 rules (strictly enforced):
        * Only BUY orders are checked — SELL / exits always pass.
        * OPTIONAL brokers (OKX, Binance, Alpaca) are never blocking.
        * CRITICAL broker (Kraken, Coinbase) that is dead blocks the BUY.
        * No ``broker`` key in ``request.extra`` → fail open (skip check).
        * Any import or runtime error → fail open (skip check).
        """
        broker_name = (request.extra.get("broker") or "").lower().strip()
        if not broker_name:
            return None  # Caller did not name a broker — skip check.

        try:
            from bot.broker_registry import get_broker_criticality, BrokerCriticality
        except ImportError:
            try:
                from broker_registry import get_broker_criticality, BrokerCriticality  # type: ignore
            except ImportError:
                return None  # Registry unavailable — fail open.

        crit = get_broker_criticality(broker_name)
        if crit != BrokerCriticality.CRITICAL:
            return None  # OPTIONAL broker — non-blocking by design.

        bfm = self._load_bfm()
        if bfm is None:
            return None  # Failure manager unavailable — fail open.

        try:
            if bfm.is_dead(broker_name):
                delay = bfm.get_retry_delay(broker_name)
                return (
                    f"CRITICAL broker '{broker_name}' is dead "
                    f"(retry in {delay:.0f}s) — BUY blocked until recovery"
                )
        except Exception as exc:
            logger.debug("SEAK: broker criticality check error: %s", exc)

        return None

    # ------------------------------------------------------------------
    # Internal: fingerprinting
    # ------------------------------------------------------------------

    @staticmethod
    def _build_fingerprint(request: ExecutionRequest) -> str:
        """Build a deterministic fingerprint for dedup purposes."""
        raw = (
            f"{request.symbol}|{request.side}|"
            f"{int(request.size_usd * 100)}|{request.strategy}|"
            f"{int(time.time() / _DEDUP_WINDOW_S)}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Internal: slot management
    # ------------------------------------------------------------------

    def _get_or_create_slot(self, symbol: str) -> _SymbolSlot:
        with self._slots_lock:
            if symbol not in self._slots:
                # Evict stale entries when the registry grows too large.
                if len(self._slots) >= _MAX_SYMBOL_LOCKS:
                    self._evict_idle_slots_locked()
                self._slots[symbol] = _SymbolSlot()
            return self._slots[symbol]

    def _evict_idle_slots_locked(self) -> None:
        """Remove unlocked, idle slot entries (called while _slots_lock is held)."""
        to_remove = [
            sym
            for sym, s in self._slots.items()
            if not s.lock.locked() and s.holder_request_id is None
        ]
        for sym in to_remove[:_MAX_SYMBOL_LOCKS // 2]:
            del self._slots[sym]

    def _clear_symbol_fingerprints(self, symbol: str) -> None:
        """Remove the active dedup fingerprint for *symbol*, if any.

        Called after a slot is released so that the next legitimate order
        for the same symbol is not incorrectly blocked as a duplicate.
        """
        with self._dedup_lock:
            fp = self._active_fp_by_symbol.pop(symbol, None)
            if fp is not None:
                self._dedup_registry.pop(fp, None)

    def _release_slot(self, slot_key: str, request_id: str) -> None:
        with self._slots_lock:
            slot = self._slots.get(slot_key)
        if slot is None:
            logger.warning("SEAK.release: no slot found for %s", slot_key)
            return
        slot.holder_request_id = None
        try:
            slot.lock.release()
        except RuntimeError:
            logger.warning("SEAK: attempted to release an unacquired lock for %s", slot_key)
        # Clear fingerprints for this symbol so that the next legitimate
        # order on the same symbol is not falsely rejected as a duplicate.
        self._clear_symbol_fingerprints(slot_key)

    # ------------------------------------------------------------------
    # Internal: audit
    # ------------------------------------------------------------------

    def _audit(
        self,
        outcome: AuditOutcome,
        request_id: str,
        symbol: str,
        side: str,
        size_usd: float,
        strategy: str,
        caller: str,
        reason: str,
        latency_ms: float = 0.0,
    ) -> None:
        entry = AuditEntry(
            ts=datetime.now(timezone.utc).isoformat(),
            outcome=outcome,
            request_id=request_id,
            symbol=symbol,
            side=side,
            size_usd=size_usd,
            strategy=strategy,
            caller=caller,
            reason=reason,
            latency_ms=latency_ms,
        )
        with self._audit_lock:
            self._audit_log.append(entry)

        if outcome == AuditOutcome.REJECTED:
            logger.warning(
                "SEAK REJECTED | id=%s | %s %s $%.2f | reason=%s",
                request_id, side.upper(), symbol, size_usd, reason,
            )

    # ------------------------------------------------------------------
    # Internal: background reaper
    # ------------------------------------------------------------------

    def _reaper_loop(self) -> None:
        """Periodic cleanup of expired fingerprints and timed-out slots."""
        while True:
            try:
                time.sleep(15)
                self._reap_expired_fingerprints()
                self._reap_timed_out_slots()
            except Exception as exc:
                logger.debug("SEAK reaper error: %s", exc)

    def _reap_expired_fingerprints(self) -> None:
        now = time.time()
        with self._dedup_lock:
            expired = [fp for fp, exp in self._dedup_registry.items() if now >= exp]
            for fp in expired:
                del self._dedup_registry[fp]
            # Clean side-table entries whose fingerprint has been reaped.
            stale_syms = [
                sym for sym, fp in self._active_fp_by_symbol.items()
                if fp not in self._dedup_registry
            ]
            for sym in stale_syms:
                del self._active_fp_by_symbol[sym]

    def _reap_timed_out_slots(self) -> None:
        now = time.monotonic()
        with self._slots_lock:
            slots_snapshot = list(self._slots.items())
        for sym, slot in slots_snapshot:
            if slot.holder_request_id and now > slot.expires_at:
                logger.warning(
                    "SEAK reaper: force-releasing timed-out slot for %s (holder=%s, age=%.1fs)",
                    sym, slot.holder_request_id, now - slot.acquired_at,
                )
                slot.holder_request_id = None
                try:
                    slot.lock.release()
                except RuntimeError:
                    pass
                self._total_force_released += 1

    # ------------------------------------------------------------------
    # Internal: lazy subsystem loaders
    # ------------------------------------------------------------------

    def _load_health_monitor(self) -> Any:
        if self._health_loaded:
            return self._health_monitor
        self._health_loaded = True
        try:
            from bot.execution_health_monitor import get_execution_health_monitor  # type: ignore
            self._health_monitor = get_execution_health_monitor()
        except ImportError:
            try:
                from execution_health_monitor import get_execution_health_monitor  # type: ignore
                self._health_monitor = get_execution_health_monitor()
            except ImportError:
                logger.info("SEAK: ExecutionHealthMonitor not available — health gate disabled")
        return self._health_monitor

    def _load_dedup_guard(self) -> Any:
        if self._dedup_guard_loaded:
            return self._dedup_guard
        self._dedup_guard_loaded = True
        try:
            from bot.trade_duplication_guard import get_trade_duplication_guard  # type: ignore
            self._dedup_guard = get_trade_duplication_guard()
        except ImportError:
            try:
                from trade_duplication_guard import get_trade_duplication_guard  # type: ignore
                self._dedup_guard = get_trade_duplication_guard()
            except ImportError:
                logger.info("SEAK: TradeDuplicationGuard not available — using internal dedup only")
        return self._dedup_guard

    def _load_hardening(self) -> Any:
        if self._hardening_loaded:
            return self._hardening
        self._hardening_loaded = True
        try:
            from bot.execution_layer_hardening import get_execution_layer_hardening  # type: ignore
            self._hardening = get_execution_layer_hardening()
        except ImportError:
            try:
                from execution_layer_hardening import get_execution_layer_hardening  # type: ignore
                self._hardening = get_execution_layer_hardening()
            except ImportError:
                logger.info("SEAK: ExecutionLayerHardening not available — hardening gate disabled")
        return self._hardening

    def _load_bfm(self) -> Any:
        """Lazily load BrokerFailureManager for Guard 6 (criticality check)."""
        if self._bfm_loaded:
            return self._bfm
        self._bfm_loaded = True
        try:
            from bot.broker_failure_manager import get_broker_failure_manager  # type: ignore
            self._bfm = get_broker_failure_manager()
        except ImportError:
            try:
                from broker_failure_manager import get_broker_failure_manager  # type: ignore
                self._bfm = get_broker_failure_manager()
            except ImportError:
                logger.info("SEAK: BrokerFailureManager not available — broker criticality gate disabled")
        return self._bfm


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_seak_instance: Optional[SingleExecutionAuthorityKernel] = None
_seak_lock: threading.Lock = threading.Lock()


def get_seak() -> SingleExecutionAuthorityKernel:
    """Return the global SEAK singleton, creating it on first call."""
    global _seak_instance
    if _seak_instance is None:
        with _seak_lock:
            if _seak_instance is None:
                _seak_instance = SingleExecutionAuthorityKernel()
    return _seak_instance


# Convenience alias.
get_single_execution_authority_kernel = get_seak
