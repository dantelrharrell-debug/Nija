"""Canonical end-to-end execution telemetry for NIJA.

Every live trading cycle must produce a verifiable audit trail.
This module defines the canonical event sequence and helpers that emit
structured log lines for each stage.

Canonical success path
----------------------
    SCAN_STARTED
    → SIGNAL_GENERATED
    → RISK_APPROVED
    → ORDER_ATTEMPT
    → BROKER_SUBMIT
    → EXCHANGE_ACK
    → POSITION_OPENED

Canonical rejection path
------------------------
    SCAN_STARTED
    → SIGNAL_GENERATED
    → RISK_REJECTED  reason=<str>

Fail-loud invariant
-------------------
Every ``SignalContext`` that records a ``SIGNAL_GENERATED`` event must be
closed (via ``close()``, a ``with`` block, or garbage-collection) with
either:
- ``ORDER_ATTEMPT`` recorded → validates BROKER_SUBMIT was attempted, or
- ``RISK_REJECTED`` recorded → validates reason was logged.

Failure to satisfy this invariant emits a ``SIGNAL_UNACCOUNTED`` ERROR
log line.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

_log = logging.getLogger("nija.execution_telemetry")
_TRUE = {"1", "true", "yes", "on", "y", "enabled"}
_LOCK = threading.Lock()
_ACTIVE: dict[int, "SignalContext"] = {}   # id(ctx) → ctx


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else str(raw).strip().lower() in _TRUE


def _emit(event: str, **fields: Any) -> None:
    parts = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
    _log.warning("%s %s", event, parts)


# ---------------------------------------------------------------------------
# Public single-shot helpers (no context required)
# ---------------------------------------------------------------------------

def scan_started(*, symbols_total: int = 0, cycle: int = 0, broker: str = "") -> None:
    """Emit SCAN_STARTED at the top of every scan cycle."""
    _emit("SCAN_STARTED", cycle=cycle, symbols_total=symbols_total, broker=broker or None)


def signal_generated(
    symbol: str,
    *,
    action: str = "",
    score: float | None = None,
    strategy: str = "",
    broker: str = "",
    cycle: int = 0,
) -> None:
    """Emit SIGNAL_GENERATED when a symbol passes entry criteria."""
    _emit(
        "SIGNAL_GENERATED",
        symbol=symbol,
        action=action or None,
        score=round(score, 6) if score is not None else None,
        strategy=strategy or None,
        broker=broker or None,
        cycle=cycle or None,
    )


def risk_approved(symbol: str, *, size_usd: float = 0.0, broker: str = "", reason: str = "") -> None:
    """Emit RISK_APPROVED when risk manager allows the trade."""
    _emit("RISK_APPROVED", symbol=symbol, size_usd=round(size_usd, 2), broker=broker or None, reason=reason or None)


def risk_rejected(symbol: str, *, reason: str, broker: str = "", score: float | None = None) -> None:
    """Emit RISK_REJECTED with the specific reason."""
    _emit(
        "RISK_REJECTED",
        symbol=symbol,
        reason=reason,
        broker=broker or None,
        score=round(score, 6) if score is not None else None,
    )


def order_attempt(symbol: str, *, side: str, size_usd: float, broker: str, intent_id: str = "") -> None:
    """Emit ORDER_ATTEMPT immediately before submitting to broker."""
    _emit(
        "ORDER_ATTEMPT",
        symbol=symbol,
        side=side,
        size_usd=round(size_usd, 2),
        broker=broker,
        intent_id=intent_id or None,
    )


def broker_submit(symbol: str, *, side: str, size_usd: float, broker: str, intent_id: str = "") -> None:
    """Emit BROKER_SUBMIT when the request is handed to the exchange client."""
    _emit(
        "BROKER_SUBMIT",
        symbol=symbol,
        side=side,
        size_usd=round(size_usd, 2),
        broker=broker,
        intent_id=intent_id or None,
    )


def exchange_ack(
    symbol: str,
    *,
    order_id: str,
    broker: str,
    fill_price: float = 0.0,
    filled_size_usd: float = 0.0,
    intent_id: str = "",
) -> None:
    """Emit EXCHANGE_ACK when the exchange confirms the order."""
    _emit(
        "EXCHANGE_ACK",
        symbol=symbol,
        order_id=order_id,
        broker=broker,
        fill_price=round(fill_price, 8) if fill_price else None,
        filled_size_usd=round(filled_size_usd, 2) if filled_size_usd else None,
        intent_id=intent_id or None,
    )


def position_opened(
    symbol: str,
    *,
    order_id: str,
    broker: str,
    side: str,
    fill_price: float = 0.0,
    size_usd: float = 0.0,
    intent_id: str = "",
) -> None:
    """Emit POSITION_OPENED when position tracking confirms the trade."""
    _emit(
        "POSITION_OPENED",
        symbol=symbol,
        order_id=order_id,
        broker=broker,
        side=side,
        fill_price=round(fill_price, 8) if fill_price else None,
        size_usd=round(size_usd, 2) if size_usd else None,
        intent_id=intent_id or None,
    )


def broker_reject(symbol: str, *, reason: str, broker: str, intent_id: str = "") -> None:
    """Emit BROKER_REJECT when the broker rejects the submitted order."""
    _emit("BROKER_REJECT", symbol=symbol, reason=reason, broker=broker, intent_id=intent_id or None)


# ---------------------------------------------------------------------------
# SignalContext — tracks one candidate from SIGNAL_GENERATED to resolution
# ---------------------------------------------------------------------------

class SignalContext:
    """Context object that tracks a single signal from generation to resolution.

    Must be closed (via ``.close()`` or used as a ``with`` block).
    If closed without recording ORDER_ATTEMPT or RISK_REJECTED, emits
    ``SIGNAL_UNACCOUNTED`` at ERROR level.

    Example::

        with SignalContext(symbol="BTC-USD", score=0.87) as ctx:
            ctx.signal_generated(action="buy", strategy="apex_v71")
            approved, reason = risk_manager.check(symbol, size_usd)
            if not approved:
                ctx.risk_rejected(reason=reason)
                return
            ctx.risk_approved(size_usd=size_usd)
            ctx.order_attempt(side="BUY", size_usd=size_usd, broker="coinbase")
            result = pipeline.execute(request)
            if result.success:
                ctx.exchange_ack(order_id=result.order_id, broker="coinbase",
                                 fill_price=result.fill_price, filled_size_usd=result.filled_size_usd)
                ctx.position_opened(order_id=result.order_id, broker="coinbase",
                                    side="BUY", fill_price=result.fill_price, size_usd=size_usd)
            else:
                ctx.broker_reject(reason=result.error, broker="coinbase")
    """

    __slots__ = (
        "symbol", "score", "broker", "cycle", "_intent_id", "_ts",
        "_signal_emitted", "_order_attempted", "_risk_rejected", "_closed",
    )

    def __init__(
        self,
        symbol: str,
        *,
        score: float | None = None,
        broker: str = "",
        cycle: int = 0,
        intent_id: str = "",
    ) -> None:
        self.symbol = symbol
        self.score = score
        self.broker = broker
        self.cycle = cycle
        self._intent_id = intent_id
        self._ts = time.monotonic()
        self._signal_emitted = False
        self._order_attempted = False
        self._risk_rejected = False
        self._closed = False
        with _LOCK:
            _ACTIVE[id(self)] = self

    # context-manager support
    def __enter__(self) -> "SignalContext":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if not self._closed:
            self.close()

    # event emitters
    def signal_generated(self, *, action: str = "", strategy: str = "") -> None:
        self._signal_emitted = True
        signal_generated(
            self.symbol,
            action=action,
            score=self.score,
            strategy=strategy,
            broker=self.broker,
            cycle=self.cycle,
        )

    def risk_approved(self, *, size_usd: float = 0.0, reason: str = "") -> None:
        risk_approved(self.symbol, size_usd=size_usd, broker=self.broker, reason=reason)

    def risk_rejected(self, *, reason: str) -> None:
        self._risk_rejected = True
        risk_rejected(self.symbol, reason=reason, broker=self.broker, score=self.score)

    def order_attempt(self, *, side: str, size_usd: float, broker: str = "") -> None:
        self._order_attempted = True
        order_attempt(
            self.symbol,
            side=side,
            size_usd=size_usd,
            broker=broker or self.broker,
            intent_id=self._intent_id,
        )

    def broker_submit(self, *, side: str, size_usd: float, broker: str = "") -> None:
        broker_submit(
            self.symbol,
            side=side,
            size_usd=size_usd,
            broker=broker or self.broker,
            intent_id=self._intent_id,
        )

    def exchange_ack(
        self,
        *,
        order_id: str,
        broker: str = "",
        fill_price: float = 0.0,
        filled_size_usd: float = 0.0,
    ) -> None:
        exchange_ack(
            self.symbol,
            order_id=order_id,
            broker=broker or self.broker,
            fill_price=fill_price,
            filled_size_usd=filled_size_usd,
            intent_id=self._intent_id,
        )

    def position_opened(
        self,
        *,
        order_id: str,
        broker: str = "",
        side: str = "",
        fill_price: float = 0.0,
        size_usd: float = 0.0,
    ) -> None:
        position_opened(
            self.symbol,
            order_id=order_id,
            broker=broker or self.broker,
            side=side,
            fill_price=fill_price,
            size_usd=size_usd,
            intent_id=self._intent_id,
        )

    def broker_reject(self, *, reason: str, broker: str = "") -> None:
        self._order_attempted = True   # an attempt was made; it was rejected at broker level
        broker_reject(self.symbol, reason=reason, broker=broker or self.broker, intent_id=self._intent_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _LOCK:
            _ACTIVE.pop(id(self), None)
        if self._signal_emitted and not self._order_attempted and not self._risk_rejected:
            elapsed = (time.monotonic() - self._ts) * 1000.0
            _log.error(
                "SIGNAL_UNACCOUNTED symbol=%s broker=%s score=%s elapsed_ms=%.0f "
                "reason=signal_generated_with_no_order_attempt_and_no_risk_rejection",
                self.symbol,
                self.broker or "unknown",
                round(self.score, 6) if self.score is not None else "unknown",
                elapsed,
            )


# ---------------------------------------------------------------------------
# Module-identity guard integration
# ---------------------------------------------------------------------------

def check_module_identity_ready() -> tuple[bool, str]:
    """Return ``(ready, reason)`` based on ``NIJA_RUNTIME_MODULE_IDENTITY_READY``.

    Callers should block live trading when ``ready`` is ``False``.
    """
    raw = os.environ.get("NIJA_RUNTIME_MODULE_IDENTITY_READY", "")
    ready = str(raw).strip().lower() in _TRUE
    reason = "" if ready else f"NIJA_RUNTIME_MODULE_IDENTITY_READY={raw!r}"
    return ready, reason


__all__ = [
    "scan_started",
    "signal_generated",
    "risk_approved",
    "risk_rejected",
    "order_attempt",
    "broker_submit",
    "exchange_ack",
    "position_opened",
    "broker_reject",
    "SignalContext",
    "check_module_identity_ready",
]
