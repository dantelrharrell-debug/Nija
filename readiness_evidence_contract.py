"""Pure, read-only readiness decision. No broker imports, I/O, or gate mutation.

This is a candidate contract for the unified NIJA evidence collector, not a
replacement for the production execution controller or an authorization API.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable


class Readiness(str, Enum):
    BLOCKED = "BLOCKED"
    RECOVERING = "RECOVERING"
    CERTIFIED = "CERTIFIED"
    AUTHORIZED = "AUTHORIZED"


@dataclass(frozen=True)
class Evidence:
    provider: str
    source: str
    deployment: str
    observed_at: datetime
    expires_at: datetime
    verified: bool
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    state: Readiness
    failures: tuple[str, ...]
    allow_new_orders: bool = False


def assess(
    records: Iterable[Evidence],
    *,
    required: frozenset[str],
    deployment: str,
    now: datetime,
    recovery_in_progress: bool = False,
    independently_authorized: bool = False,
    kill_switch_clear: bool = False,
) -> Decision:
    """Fail closed on any missing, duplicate, stale, or contradictory evidence.

    AUTHORIZED is an *observational* label only; it never grants permission.
    The production controller must independently enforce every safety gate.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    failures: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not record.provider or record.provider in seen:
            failures.append("duplicate_or_empty_provider")
        seen.add(record.provider)
        if record.provider not in required:
            failures.append("unexpected_provider")
        if not record.source or record.deployment != deployment:
            failures.append("source_or_deployment_mismatch")
        if (record.observed_at.tzinfo is None or record.expires_at.tzinfo is None
                or record.observed_at > now or record.expires_at <= now
                or record.expires_at <= record.observed_at):
            failures.append("stale_or_invalid_timestamp")
        if record.verified is not True:
            failures.append("provider_not_verified:" + record.provider)
    for missing in sorted(required - seen):
        failures.append("missing_provider:" + missing)
    if not deployment or not required:
        failures.append("missing_contract_or_deployment")
    if failures:
        return Decision(Readiness.RECOVERING if recovery_in_progress else Readiness.BLOCKED,
                        tuple(sorted(set(failures))))
    if independently_authorized and kill_switch_clear:
        return Decision(Readiness.AUTHORIZED, ())
    return Decision(Readiness.CERTIFIED, ())
