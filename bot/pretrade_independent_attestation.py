"""Fail-closed boundary for independently authenticated pre-trade evidence.

A caller must supply a trusted, account-scoped producer. No environment,
runtime health flag, remembered trade, or order-submission side effect can
certify an account. This module is intentionally NOT an activation hook.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from typing import Any

FIELDS = (
    "account_permissions", "account_identity", "broker_balances",
    "position_ledger_reconciliation", "protective_exit_readback",
    "open_order_reconciliation", "duplicate_order_fence",
    "writer_lease", "nonce_sequence", "operator_authorization",
)

# Read-only and separately audited collector must be explicitly installed.
_COLLECTOR: Callable[[str], Mapping[str, Any]] | None = None


def install_authenticated_collector(collector: Callable[[str], Mapping[str, Any]]) -> None:
    """Install a trusted producer; installation alone proves nothing."""
    global _COLLECTOR
    if not callable(collector):
        raise TypeError("authenticated_collector_required")
    _COLLECTOR = collector


def current_authenticated_attestations(
    account: str | None = None, *, now: float | None = None,
) -> dict[str, bool]:
    """Require exact account, source provenance, fresh evidence and all checks.

    A valid result is diagnostic only. This module never authorizes trading.
    """
    denied = {field: False for field in FIELDS}
    if not isinstance(account, str) or not account.strip() or account != account.strip():
        return denied
    if _COLLECTOR is None:
        return denied
    try:
        raw = _COLLECTOR(account)
        if not isinstance(raw, Mapping):
            return denied
        stamp = raw.get("observed_at_epoch")
        current = time.time() if now is None else now
        if (isinstance(stamp, bool) or isinstance(current, bool)
                or not isinstance(stamp, (int, float))
                or not isinstance(current, (int, float))
                or not math.isfinite(stamp) or not math.isfinite(current)
                or not 0 <= current - stamp <= 60):
            return denied
        if raw.get("account") != account or raw.get("source") != "authenticated_independent":
            return denied
        if raw.get("read_only") is not True or raw.get("scope_verified") is not True:
            return denied
        checks = raw.get("checks")
        if not isinstance(checks, Mapping):
            return denied
        return {field: checks.get(field) is True for field in FIELDS}
    except Exception:
        return denied


__all__ = ["FIELDS", "install_authenticated_collector", "current_authenticated_attestations"]
