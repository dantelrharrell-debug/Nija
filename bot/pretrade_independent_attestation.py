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

from bot.pretrade_attestation_validation_v452 import IndependentEvidenceRejected, REQUIRED

FIELDS = REQUIRED

# Read-only and separately audited collector must be explicitly installed.
_COLLECTOR: Callable[[str], Mapping[str, Any]] | None = None


def install_authenticated_collector(collector: Callable[[str], Mapping[str, Any]]) -> None:
    """Install a trusted producer; installation alone proves nothing."""
    global _COLLECTOR
    if not callable(collector):
        raise TypeError("authenticated_collector_required")
    _COLLECTOR = collector


def inspect_authenticated_attestations(
    account: str | None = None, *, now: float | None = None,
) -> dict[str, Any]:
    """Collect once and return fixed, non-secret denial diagnostics.

    This is not an activation hook. A process cannot establish authority by
    installing a collector or by submitting its own producer status.
    """
    denied = {field: False for field in FIELDS}

    def report(reason: str, checks: Mapping[str, bool] = denied) -> dict[str, Any]:
        return {
            "checks": dict(checks),
            "producer_status": reason,
            "collector_installed": callable(_COLLECTOR),
            "authorizes_orders": False,
        }

    if (not isinstance(account, str) or not account or account != account.strip()
            or any(char.isspace() for char in account)):
        return report("account_scope_invalid")
    if _COLLECTOR is None:
        return report("collector_missing")
    try:
        raw = _COLLECTOR(account)
        if not isinstance(raw, Mapping):
            return report("collector_result_invalid")
        stamp = raw.get("observed_at_epoch")
        current = time.time() if now is None else now
        if (isinstance(stamp, bool) or isinstance(current, bool)
                or not isinstance(stamp, (int, float))
                or not isinstance(current, (int, float))
                or not math.isfinite(stamp) or not math.isfinite(current)
                or not 0 <= current - stamp <= 60):
            return report("observation_missing_future_or_stale")
        if raw.get("account") != account:
            return report("account_scope_mismatch")
        if raw.get("source") != "authenticated_independent":
            return report("producer_source_untrusted")
        if raw.get("read_only") is not True or raw.get("scope_verified") is not True:
            return report("authenticated_readback_unverified")
        provenance = raw.get("provenance")
        if not isinstance(provenance, Mapping):
            return report("provenance_missing")
        required_provenance = (
            "authenticated_broker_read_verified",
            "ledger_snapshot_verified",
            "complete_pagination_verified",
            "collector_identity_verified",
            "account_scope_verified",
        )
        if not all(provenance.get(key) is True for key in required_provenance):
            return report("provenance_unverified")
        checks = raw.get("checks")
        if not isinstance(checks, Mapping):
            return report("checks_missing")
        accepted = {field: checks.get(field) is True for field in FIELDS}
        return report(
            "checks_passed_diagnostic_only" if all(accepted.values()) else "checks_incomplete",
            accepted,
        )
    except IndependentEvidenceRejected as exc:
        result = report("independent_evidence_rejected")
        result["failed_fields"] = list(exc.failed_fields)
        return result
    except Exception:
        return report("collector_exception")


def current_authenticated_attestations(
    account: str | None = None, *, now: float | None = None,
) -> dict[str, bool]:
    """Preserve the original fail-closed check mapping without a second read."""
    return inspect_authenticated_attestations(account, now=now)["checks"]


__all__ = [
    "FIELDS", "install_authenticated_collector",
    "inspect_authenticated_attestations", "current_authenticated_attestations",
]
