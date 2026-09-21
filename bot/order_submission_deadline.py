"""Bounded broker-mutation deadline for execution workers.

The execution pipeline dispatches broker work on a worker thread and applies an
outer ACK timeout. Python cannot cancel a running thread, so a timed-out worker
could otherwise continue through slow pre-order reads and reach a mutating
exchange call after its caller has already returned an indeterminate result.

This module carries an absolute monotonic deadline in the worker's ContextVar.
Broker terminals may assert the deadline immediately before a mutating API call.
It does not authorize execution, change any risk/nonce/writer/kill-switch gate,
or turn an acknowledgement into fill proof.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import time
from typing import Iterator

_DEADLINE_MONOTONIC: ContextVar[float] = ContextVar(
    "nija_order_submission_deadline_monotonic",
    default=0.0,
)


@contextmanager
def order_submission_deadline_scope(timeout_s: float) -> Iterator[float]:
    """Set an absolute mutation deadline for the current execution worker."""
    timeout = max(0.0, float(timeout_s or 0.0))
    deadline = time.monotonic() + timeout if timeout > 0.0 else 0.0
    token = _DEADLINE_MONOTONIC.set(deadline)
    try:
        yield deadline
    finally:
        _DEADLINE_MONOTONIC.reset(token)


def current_deadline_monotonic() -> float:
    try:
        return float(_DEADLINE_MONOTONIC.get() or 0.0)
    except Exception:
        return 0.0


def remaining_s() -> float | None:
    deadline = current_deadline_monotonic()
    if deadline <= 0.0:
        return None
    return max(0.0, deadline - time.monotonic())


def assert_mutation_deadline(operation: str) -> None:
    """Raise before a late mutation when the worker's dispatch budget expired."""
    deadline = current_deadline_monotonic()
    if deadline <= 0.0:
        return
    now = time.monotonic()
    if now >= deadline:
        raise TimeoutError(
            f"order_submission_deadline_expired_before_{str(operation or 'mutation').strip().lower()}"
        )


__all__ = [
    "order_submission_deadline_scope",
    "current_deadline_monotonic",
    "remaining_s",
    "assert_mutation_deadline",
]
