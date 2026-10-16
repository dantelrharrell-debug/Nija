"""Fresh account-scoped pre-trade evidence evaluator.

Separates current operational facts from the age of the last real trade.
Pure evaluation only: does not modify canonical readiness, dispatch trades,
change kill switches, or grant execution authority.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

CHECKS = (
    "broker_identity", "broker_permissions", "balance",
    "positions", "position_reconciliation", "startup_reconciliation",
    "protective_exits", "ledger_integrity", "ledger_restore",
    "writer_lease", "nonce", "risk_controls", "strategy",
    "execution_pipeline", "emergency_stop_clear",
)


@dataclass(frozen=True)
class EvidenceAssessment:
    pretrade_checks_pass: bool
    missing: tuple[str, ...]
    rejected: tuple[str, ...]
    # This evaluator is not an execution permission source.
    can_submit_orders: bool = False


def assess(
    attestations: Mapping[str, Mapping[str, Any]] | None,
    *,
    account: str,
    now: float,
    ttl_seconds: float = 90.0,
) -> EvidenceAssessment:
    """Accept only current affirmative evidence for the same account.

    Evidence must contain exact verified=True, source, account and observed_at.
    No old fill timestamp is required. This cannot substitute for the canonical
    authorization machine or independently trigger any order.
    """
    records = attestations if isinstance(attestations, Mapping) else {}
    clock_ok = isinstance(now, (int, float)) and not isinstance(now, bool) and math.isfinite(now) and now > 0
    ttl_ok = isinstance(ttl_seconds, (int, float)) and not isinstance(ttl_seconds, bool) and math.isfinite(ttl_seconds) and 0 < ttl_seconds <= 300
    account_ok = isinstance(account, str) and bool(account.strip())
    rejected = []
    missing = []
    if not (clock_ok and ttl_ok and account_ok):
        rejected.append("invalid_request_context")
    for name in CHECKS:
        rec = records.get(name)
        if not isinstance(rec, Mapping):
            missing.append(name)
            continue
        ts = rec.get("observed_at")
        time_ok = (
            clock_ok and ttl_ok
            and isinstance(ts, (int, float)) and not isinstance(ts, bool)
            and math.isfinite(ts)
            and 0 <= now - ts <= ttl_seconds
        )
        if not (
            rec.get("verified") is True
            and account_ok and rec.get("account") == account
            and isinstance(rec.get("source"), str) and bool(rec["source"].strip())
            and time_ok
        ):
            rejected.append(name)
    return EvidenceAssessment(
        pretrade_checks_pass=not (missing or rejected),
        missing=tuple(missing),
        rejected=tuple(rejected),
    )
