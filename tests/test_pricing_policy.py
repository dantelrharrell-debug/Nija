from decimal import Decimal

from pricing_policy import (
    BETA_TRIAL_DAYS,
    FOUNDING_BETA_LIMIT,
    FOUNDING_BETA_MONTHLY_USD,
    FULL_RELEASE_MONTHLY_USD,
    LESSONS_ONE_TIME_USD,
    STANDARD_BETA_MONTHLY_USD,
    beta_offer_for_claimed_count,
)


def test_first_beta_user_gets_founding_offer():
    offer = beta_offer_for_claimed_count(0)
    assert offer.amount_usd == Decimal("50.00")
    assert offer.trial_days == 14
    assert offer.cohort_limit == 100


def test_ninety_ninth_claimed_still_has_one_founding_slot():
    offer = beta_offer_for_claimed_count(99)
    assert offer.amount_usd == FOUNDING_BETA_MONTHLY_USD
    assert offer.trial_days == BETA_TRIAL_DAYS


def test_after_first_100_new_beta_users_get_standard_beta_price():
    offer = beta_offer_for_claimed_count(FOUNDING_BETA_LIMIT)
    assert offer.amount_usd == STANDARD_BETA_MONTHLY_USD
    assert offer.amount_usd == Decimal("75.00")
    assert offer.trial_days == 0


def test_lessons_and_full_release_prices_are_distinct_products():
    assert LESSONS_ONE_TIME_USD == Decimal("99.00")
    assert FULL_RELEASE_MONTHLY_USD == Decimal("99.00")
