"""
Runtime correlation context for deterministic, thread-safe tracing.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

_RUNTIME_CORRELATION: ContextVar[Dict[str, str]] = ContextVar(
    "nija_runtime_correlation",
    default={},
)

_ALLOWED_KEYS = {
    "cycle_id",
    "trace_id",
    "request_id",
    "intent_id",
    "account_id",
    "broker_identity",
}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def set_runtime_correlation(**fields: Any) -> Dict[str, str]:
    """Overwrite correlation envelope for the current context."""
    envelope: Dict[str, str] = {}
    for key in _ALLOWED_KEYS:
        value = _normalize(fields.get(key))
        if value:
            envelope[key] = value
    _RUNTIME_CORRELATION.set(envelope)
    return dict(envelope)


def update_runtime_correlation(**fields: Any) -> Dict[str, str]:
    """Merge fields into current correlation envelope."""
    current = dict(_RUNTIME_CORRELATION.get() or {})
    for key in _ALLOWED_KEYS:
        if key not in fields:
            continue
        value = _normalize(fields.get(key))
        if value:
            current[key] = value
        else:
            current.pop(key, None)
    _RUNTIME_CORRELATION.set(current)
    return dict(current)


def get_runtime_correlation() -> Dict[str, str]:
    """Get a copy of current correlation envelope."""
    return dict(_RUNTIME_CORRELATION.get() or {})


def clear_runtime_correlation() -> None:
    """Clear correlation envelope for the current context."""
    _RUNTIME_CORRELATION.set({})


@contextmanager
def runtime_correlation_scope(**fields: Any) -> Iterator[Dict[str, str]]:
    """Context manager that sets correlation envelope and restores prior state."""
    previous = dict(_RUNTIME_CORRELATION.get() or {})
    updated = dict(previous)
    for key in _ALLOWED_KEYS:
        if key not in fields:
            continue
        value = _normalize(fields.get(key))
        if value:
            updated[key] = value
        else:
            updated.pop(key, None)
    _RUNTIME_CORRELATION.set(updated)
    try:
        yield dict(updated)
    finally:
        _RUNTIME_CORRELATION.set(previous)


def correlation_extra(prefix: str = "runtime_") -> Dict[str, str]:
    """Return logging-extra-safe correlation dictionary."""
    data = get_runtime_correlation()
    return {f"{prefix}{k}": v for k, v in data.items() if v}


def resolve_correlation_id() -> Optional[str]:
    """Return best-available correlation id for current context."""
    data = get_runtime_correlation()
    return data.get("trace_id") or data.get("request_id") or data.get("cycle_id")
