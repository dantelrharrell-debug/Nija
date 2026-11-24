"""Founding 100 sandbox-only readiness decision. NEVER authorizes a real charge.

Trade evidence is necessary but insufficient for recurring billing. This pure
function checks a trusted immutable enrollment consent and a separately
acknowledged post-fill calendar-date notice. It does not call Stripe, determine
legal jurisdiction, or create a billable entitlement. Production use is forbidden
until the full legally approved billing lifecycle is implemented and certified.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from founding_trial_ledger import TrialRecord

FOUNDING_MONTHLY_USD = Decimal("50.00")


@dataclass(frozen=True)
class EnrollmentConsent:
    member_id: str
    offer_code: str
    amount_usd: Decimal
    renewal_interval: Literal["month"]
    accepted_at: datetime
    disclosure_version: str
    recurring_charge_accepted: bool


@dataclass(frozen=True)
class TrialNotice:
    member_id: str
    starts_at: datetime
    ends_at: datetime
    first_charge_at: datetime
    acknowledged_at: datetime
    cancellation_url: str


@dataclass(frozen=True)
class SandboxReadiness:
    status: Literal["not_ready", "sandbox_candidate"]
    reasons: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == "sandbox_candidate"


def _utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def evaluate_sandbox_billing_candidate(
    *,
    trial: TrialRecord | None,
    consent: EnrollmentConsent | None,
    notice: TrialNotice | None,
    now: datetime,
    legal_approval: bool = False,
    cancellation_operational: bool = False,
) -> SandboxReadiness:
    """Reject incomplete evidence; approval means TEST-only candidate, not permission to charge."""
    reasons = []
    current = _utc(now)
    if current is None:
        reasons.append("clock_unverified")
    if trial is None or trial.state != "trialing" or not trial.execution_id:
        reasons.append("first_fill_trial_unverified")
        start = end = None
    else:
        try:
            start = _utc(datetime.fromisoformat(trial.starts_at or ""))
            end = _utc(datetime.fromisoformat(trial.ends_at or ""))
        except ValueError:
            start = end = None
        if start is None or end is None or end <= start:
            reasons.append("trial_window_invalid")
        elif current is not None and current < end:
            reasons.append("trial_not_expired")
    if consent is None or not consent.recurring_charge_accepted:
        reasons.append("consent_missing")
    elif (
        trial is None or consent.member_id != trial.member_id
        or consent.offer_code != "founding_beta"
        or consent.amount_usd != FOUNDING_MONTHLY_USD
        or consent.renewal_interval != "month"
        or not consent.disclosure_version.strip()
        or _utc(consent.accepted_at) is None
        or (start is not None and _utc(consent.accepted_at) > start)
    ):
        # Initial authorization must be established before any trial begins;
        # additional post-trigger consumer acknowledgment is checked below.
        reasons.append("consent_mismatch")
    if notice is None:
        reasons.append("post_fill_notice_missing")
    elif (
        trial is None or notice.member_id != trial.member_id
        or start is None or end is None
        or _utc(notice.starts_at) != start
        or _utc(notice.ends_at) != end
        or _utc(notice.first_charge_at) != end
        or _utc(notice.acknowledged_at) is None
        or not (start <= _utc(notice.acknowledged_at) < end)
        or not notice.cancellation_url.startswith("https://")
    ):
        reasons.append("post_fill_notice_mismatch")
    if not legal_approval:
        reasons.append("jurisdiction_not_approved")
    if not cancellation_operational:
        reasons.append("cancellation_not_verified")
    return SandboxReadiness("not_ready" if reasons else "sandbox_candidate", tuple(reasons))
