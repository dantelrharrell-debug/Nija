"""
Execution authority context
===========================

Provides a thread/task-safe context marker used to assert that broker order
submission is happening through the canonical ExecutionPipeline path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_EXECUTION_AUTHORITY_ACTIVE: ContextVar[bool] = ContextVar(
    "nija_execution_authority_active",
    default=False,
)


@contextmanager
def execution_authority_scope() -> Iterator[None]:
    """Mark the current context as execution-authorized for broker submits."""
    token = _EXECUTION_AUTHORITY_ACTIVE.set(True)
    try:
        yield
    finally:
        _EXECUTION_AUTHORITY_ACTIVE.reset(token)


def has_execution_authority() -> bool:
    """Return True when the current context is authorized for order submit."""
    return bool(_EXECUTION_AUTHORITY_ACTIVE.get())
