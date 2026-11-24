"""TEST-only Founding 100 activation boundary. Never imported by production billing.

No Stripe SDK calls, network access, or live brokerage integration.
The caller must supply authenticated evidence, consent, and a TEST-only provider.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

class ActivationDenied(ValueError):
    pass

@dataclass(frozen=True)
class Enrollment:
    member_id: str
    offer: str
    existing_subscription_id: str | None
    consent_at: datetime | None
    consent_expires_at: datetime | None
    canceled: bool = False

@dataclass(frozen=True)
class VerifiedFirstFill:
    member_id: str
    execution_id: str
    executed_at: datetime
    live: bool
    filled: bool

class Ledger(Protocol):
    def claim_once(self, member_id: str, execution_id: str, starts_at: datetime, ends_at: datetime) -> bool: ...
    def get_activation(self, member_id: str) -> str | None: ...
    def record_activation(self, member_id: str, subscription_id: str) -> None: ...

class TestProvider(Protocol):
    mode: str
    def create_subscription(self, *, member_id: str, trial_end: datetime, amount_cents: int, currency: str, idempotency_key: str) -> str: ...

def checkout_allowed(enrollment: Enrollment) -> bool:
    """Old checkout subscription creation must never serve Founding 100."""
    return enrollment.offer != "founding100"

def activate_test_only(enrollment: Enrollment, fill: VerifiedFirstFill, ledger: Ledger, provider: TestProvider, *, now: datetime) -> str:
    if provider.mode != "test":
        raise ActivationDenied("Stripe TEST mode required")
    if enrollment.offer != "founding100" or enrollment.canceled:
        raise ActivationDenied("not eligible")
    if enrollment.existing_subscription_id:
        raise ActivationDenied("existing subscription must remain untouched")
    if enrollment.member_id != fill.member_id or not fill.live or not fill.filled:
        raise ActivationDenied("authenticated live fill required")
    for dt in (now, fill.executed_at, enrollment.consent_at, enrollment.consent_expires_at):
        if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
            raise ActivationDenied("timezone-aware evidence and consent required")
    now_utc = now.astimezone(timezone.utc)
    start = fill.executed_at.astimezone(timezone.utc)
    consent_at = enrollment.consent_at.astimezone(timezone.utc)
    consent_expiry = enrollment.consent_expires_at.astimezone(timezone.utc)
    if not fill.execution_id or start > now_utc or consent_at > start or consent_expiry <= now_utc:
        raise ActivationDenied("invalid fill timing or expired consent")
    end = start + timedelta(days=14)
    if end <= now_utc:
        raise ActivationDenied("trial already expired; re-consent required")
    existing = ledger.get_activation(enrollment.member_id)
    if existing:
        return existing
    if not ledger.claim_once(enrollment.member_id, fill.execution_id, start, end):
        raise ActivationDenied("claim already exists; reconcile before retry")
    # A production implementation must reconcile uncertain provider outcomes
    # before retrying; stable key protects against duplicate TEST requests.
    subscription_id = provider.create_subscription(
        member_id=enrollment.member_id, trial_end=end,
        amount_cents=5000, currency="usd",
        idempotency_key="founding100:test:" + enrollment.member_id,
    )
    if not subscription_id:
        raise ActivationDenied("provider did not confirm subscription")
    ledger.record_activation(enrollment.member_id, subscription_id)
    return subscription_id
