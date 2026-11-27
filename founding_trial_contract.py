"""Pure, non-billing trial date calculation for the proposed Founding 100 offer.

This module neither authenticates a broker fill nor creates or changes Stripe
subscriptions. Call it only after separate trusted services have validated the
member binding, live executed fill, and first-event idempotency. It deliberately
does not interpret checkout completion, registration, or paper trades as proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TRIAL_DURATION_DAYS = 14


@dataclass(frozen=True)
class TrialWindow:
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("trial timestamps must be timezone-aware")
        if self.starts_at.utcoffset() != timedelta(0) or self.ends_at.utcoffset() != timedelta(0):
            raise ValueError("trial timestamps must use UTC")
        if self.ends_at - self.starts_at != timedelta(days=TRIAL_DURATION_DAYS):
            raise ValueError("trial duration must be exactly 14 days")


def trial_window_from_authoritative_fill(executed_at: datetime) -> TrialWindow:
    """Calculate a window from a *previously verified*, first live broker fill.

    The caller must authenticate the account and broker record, ensure the fill
    is live/executed (not submitted or simulated), atomically preserve the first
    eligible fill per member, and reject replayed/out-of-order notifications.
    No payment may be scheduled solely from this calculation. The separate
    consent, notice, eligibility, and jurisdiction checks must pass.
    """
    if not isinstance(executed_at, datetime) or executed_at.tzinfo is None:
        raise ValueError("verified fill time must be a timezone-aware datetime")
    if executed_at.utcoffset() is None:
        raise ValueError("verified fill time must have a valid offset")
    start = executed_at.astimezone(timezone.utc)
    return TrialWindow(starts_at=start, ends_at=start + timedelta(days=TRIAL_DURATION_DAYS))
