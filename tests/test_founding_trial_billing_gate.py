"""Isolated Founding 100 billing decision tests. No Stripe, no brokerage API."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from founding_trial_billing_gate import (
    EnrollmentConsent, TrialNotice, evaluate_sandbox_billing_candidate,
)
from founding_trial_ledger import TrialRecord

START = datetime(2026, 11, 23, 16, tzinfo=timezone.utc)
END = START + timedelta(days=14)
NOW = END + timedelta(minutes=2)


@pytest.fixture
def fixtures():
    trial = TrialRecord("member-1", "trialing", "broker-fill-1", START.isoformat(), END.isoformat())
    consent = EnrollmentConsent("member-1", "founding_beta", Decimal("50.00"), "month",
                                START - timedelta(days=1), "founding-v1", True)
    notice = TrialNotice("member-1", START, END, END, START + timedelta(minutes=1),
                         "https://nijaaitrading.com/cancel")
    return trial, consent, notice


def decide(fixtures, **overrides):
    trial, consent, notice = fixtures
    args = {"trial": trial, "consent": consent, "notice": notice,
            "now": NOW, "legal_approval": True, "cancellation_operational": True}
    args.update(overrides)
    return evaluate_sandbox_billing_candidate(**args)


def test_all_verified_evidence_creates_only_sandbox_candidate(fixtures):
    result = decide(fixtures)
    assert result.ready
    assert result.status == "sandbox_candidate"
    assert result.reasons == ()


@pytest.mark.parametrize("change,reason", [
    ({"trial": None}, "first_fill_trial_unverified"),
    ({"now": START}, "trial_not_expired"),
    ({"consent": None}, "consent_missing"),
    ({"notice": None}, "post_fill_notice_missing"),
    ({"legal_approval": False}, "jurisdiction_not_approved"),
    ({"cancellation_operational": False}, "cancellation_not_verified"),
    ({"now": datetime(2026, 12, 7, 16)}, "clock_unverified"),
])
def test_required_gate_defaults_to_not_ready(fixtures, change, reason):
    result = decide(fixtures, **change)
    assert result.status == "not_ready"
    assert reason in result.reasons


@pytest.mark.parametrize("patch", [
    {"recurring_charge_accepted": False},
    {"member_id": "someone-else"},
    {"offer_code": "standard_beta_v2"},
    {"amount_usd": Decimal("99.00")},
    {"renewal_interval": "year"},
    {"disclosure_version": ""},
    {"accepted_at": START + timedelta(seconds=1)},
    {"accepted_at": datetime(2026, 11, 22, 16)},
])
def test_invalid_consent_is_rejected(fixtures, patch):
    trial, consent, _ = fixtures
    result = decide(fixtures, consent=replace(consent, **patch))
    assert not result.ready
    assert "consent_missing" in result.reasons or "consent_mismatch" in result.reasons


@pytest.mark.parametrize("patch", [
    {"member_id": "someone-else"},
    {"starts_at": START + timedelta(seconds=1)},
    {"ends_at": END + timedelta(seconds=1)},
    {"first_charge_at": END + timedelta(hours=1)},
    {"acknowledged_at": START - timedelta(seconds=1)},
    {"acknowledged_at": END},
    {"cancellation_url": "http://insecure.example.test/cancel"},
])
def test_incorrect_post_fill_notice_is_rejected(fixtures, patch):
    _, _, notice = fixtures
    result = decide(fixtures, notice=replace(notice, **patch))
    assert "post_fill_notice_mismatch" in result.reasons


def test_cancelled_trial_cannot_become_billable(fixtures):
    trial, _, _ = fixtures
    result = decide(fixtures, trial=replace(trial, state="canceled"))
    assert "first_fill_trial_unverified" in result.reasons
    assert not result.ready


def test_missing_inputs_fail_closed():
    result = evaluate_sandbox_billing_candidate(trial=None, consent=None, notice=None, now=NOW)
    assert result.status == "not_ready"
    assert len(result.reasons) >= 5


@pytest.mark.parametrize("duration_days", [1, 13, 15])
def test_noncanonical_window_is_rejected_even_with_consistent_notice(fixtures, duration_days):
    trial, consent, notice = fixtures
    incorrect_end = START + timedelta(days=duration_days)
    result = decide(
        fixtures,
        trial=replace(trial, ends_at=incorrect_end.isoformat()),
        consent=consent,
        notice=replace(notice, ends_at=incorrect_end, first_charge_at=incorrect_end),
        now=incorrect_end + timedelta(minutes=2),
    )
    assert result.status == "not_ready"
    assert "trial_window_invalid" in result.reasons
