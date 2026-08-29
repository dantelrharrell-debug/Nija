"""Canonical NIJA commercial pricing policy.

Commercial offer pricing is intentionally separate from legacy/internal feature tiers.
Do not use internal access tier names as public prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Any

BETA_TRIAL_DAYS = 14
FOUNDING_BETA_LIMIT = 100
FOUNDING_BETA_MONTHLY_USD = Decimal("50.00")
STANDARD_BETA_MONTHLY_USD = Decimal("75.00")
FULL_RELEASE_MONTHLY_USD = Decimal("99.00")
LESSONS_ONE_TIME_USD = Decimal("99.00")

FOUNDING_BETA_OFFER = "founding_beta"
STANDARD_BETA_OFFER = "standard_beta"
FULL_RELEASE_OFFER = "full_release"
LESSONS_OFFER = "lessons"


@dataclass(frozen=True)
class CommercialOffer:
    code: str
    amount_usd: Decimal
    recurring: bool
    trial_days: int = 0
    cohort_limit: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "amount_usd": float(self.amount_usd),
            "recurring": self.recurring,
            "trial_days": self.trial_days,
            "cohort_limit": self.cohort_limit,
        }


OFFERS = {
    FOUNDING_BETA_OFFER: CommercialOffer(
        code=FOUNDING_BETA_OFFER,
        amount_usd=FOUNDING_BETA_MONTHLY_USD,
        recurring=True,
        trial_days=BETA_TRIAL_DAYS,
        cohort_limit=FOUNDING_BETA_LIMIT,
    ),
    STANDARD_BETA_OFFER: CommercialOffer(
        code=STANDARD_BETA_OFFER,
        amount_usd=STANDARD_BETA_MONTHLY_USD,
        recurring=True,
    ),
    FULL_RELEASE_OFFER: CommercialOffer(
        code=FULL_RELEASE_OFFER,
        amount_usd=FULL_RELEASE_MONTHLY_USD,
        recurring=True,
    ),
    LESSONS_OFFER: CommercialOffer(
        code=LESSONS_OFFER,
        amount_usd=LESSONS_ONE_TIME_USD,
        recurring=False,
    ),
}


def beta_offer_for_claimed_count(claimed_count: int) -> CommercialOffer:
    """Return the public beta offer without repricing prior cohorts."""
    count = max(0, int(claimed_count))
    if count < FOUNDING_BETA_LIMIT:
        return OFFERS[FOUNDING_BETA_OFFER]
    return OFFERS[STANDARD_BETA_OFFER]


def public_pricing() -> Dict[str, Dict[str, Any]]:
    return {code: offer.to_dict() for code, offer in OFFERS.items()}
