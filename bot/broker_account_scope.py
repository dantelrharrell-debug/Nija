"""Context-local broker/account identity for one NIJA execution cycle."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_BROKER: ContextVar[Optional[str]] = ContextVar("nija_scope_broker", default=None)
_ACCOUNT: ContextVar[Optional[str]] = ContextVar("nija_scope_account", default=None)


def current_broker_name(default: str = "") -> str:
    return str(_BROKER.get() or default)


def current_account_scope(default: str = "platform") -> str:
    return str(_ACCOUNT.get() or default)


@contextmanager
def broker_account_scope(broker_name: str, account_scope: str) -> Iterator[None]:
    broker_token = _BROKER.set(str(broker_name or "unknown").strip().lower())
    account_token = _ACCOUNT.set(str(account_scope or "platform").strip().lower())
    try:
        yield
    finally:
        _ACCOUNT.reset(account_token)
        _BROKER.reset(broker_token)


__all__ = ["broker_account_scope", "current_broker_name", "current_account_scope"]
