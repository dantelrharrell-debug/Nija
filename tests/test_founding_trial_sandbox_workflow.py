from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from founding_trial_billing_gate import EnrollmentConsent, TrialNotice
from founding_trial_evidence import BrokerExecution, UnverifiedFill
from founding_trial_ledger import FoundingTrialLedger
from founding_trial_sandbox_workflow import (
    FOUNDING_STRIPE_SANDBOX_ACCOUNT,
    FoundingTrialSandboxWorkflow,
    TrustedBillingEvidence,
)

START = datetime(2026, 11, 1, 10, 30, tzinfo=timezone.utc)
END = START + timedelta(days=14)
MEMBER = "member-fixture"
BROKER = "broker-fixture"
FILL = "fill-fixture"


@pytest.fixture
def flow(tmp_path):
    state = SimpleNamespace(
        now=START,
        owner=MEMBER,
        fill=BrokerExecution(FILL, BROKER, "live", "filled", "1", START),
        evidence=TrustedBillingEvidence(
            EnrollmentConsent(MEMBER, "founding_beta", Decimal("50.00"), "month",
                              START - timedelta(days=1), "fixture-consent-v1", True),
            TrialNotice(MEMBER, START, END, END, START + timedelta(days=1),
                        "https://example.invalid/cancel"),
            True,
            True,
        ),
    )
    db = tmp_path / "founding.sqlite"
    params = dict(
        ledger=FoundingTrialLedger(db),
        executions=SimpleNamespace(retrieve_execution=lambda execution_id: state.fill),
        accounts=SimpleNamespace(owner_of=lambda account_id: state.owner),
        billing_evidence=SimpleNamespace(evidence_for=lambda member_id: state.evidence),
        clock=lambda: state.now,
        stripe_account=FOUNDING_STRIPE_SANDBOX_ACCOUNT,
        livemode=False,
    )
    return FoundingTrialSandboxWorkflow(**params), state, params, db


def record(workflow):
    return workflow.record_verified_fill(member_id=MEMBER, execution_id=FILL, brokerage_account_id=BROKER)


@pytest.mark.parametrize("stripe_account,livemode", [
    ("acct_wrong", False), (FOUNDING_STRIPE_SANDBOX_ACCOUNT, True),
    (FOUNDING_STRIPE_SANDBOX_ACCOUNT, None), (FOUNDING_STRIPE_SANDBOX_ACCOUNT, 0),
])
def test_sandbox_boundary_refuses_nonexact_mode_and_account(flow, stripe_account, livemode):
    _, _, params, _ = flow
    with pytest.raises(ValueError, match="NIJA Stripe sandbox"):
        FoundingTrialSandboxWorkflow(**(params | dict(stripe_account=stripe_account, livemode=livemode)))


def test_actual_reference_ledger_and_gate_across_reopen_and_retry(flow):
    workflow, state, params, db = flow
    assert workflow.evaluate(MEMBER).rehearsal is None
    first = record(workflow)
    assert datetime.fromisoformat(first.ends_at) == END
    assert record(workflow) == first
    state.now = END - timedelta(microseconds=1)
    result = workflow.evaluate(MEMBER)
    assert "trial_not_expired" in result.readiness.reasons
    assert result.rehearsal is None
    state.now = END
    result = workflow.evaluate(MEMBER)
    assert result.readiness.ready
    assert result.rehearsal.amount_usd_cents == 5000
    assert result.rehearsal.first_charge_at == END
    assert len(result.rehearsal.replay_fingerprint) == 64
    new_workflow = FoundingTrialSandboxWorkflow(**(params | dict(ledger=FoundingTrialLedger(db))))
    assert new_workflow.evaluate(MEMBER) == result
    state.now = END + timedelta(seconds=1)
    result = new_workflow.evaluate(MEMBER)
    assert result.rehearsal is None
    assert result.readiness.reasons == ("scheduled_test_charge_time_missed",)


@pytest.mark.parametrize("change", [
    {"environment": "paper"}, {"status": "open"}, {"filled_quantity": "0"},
    {"brokerage_account_id": "another"}, {"execution_id": "another"},
    {"executed_at": START + timedelta(seconds=1)},
])
def test_unverified_execution_never_starts_trial(flow, change):
    workflow, state, params, _ = flow
    state.fill = replace(state.fill, **change)
    with pytest.raises(UnverifiedFill):
        record(workflow)
    assert params["ledger"].get(MEMBER) is None


def test_other_owner_never_starts_trial(flow):
    workflow, state, params, _ = flow
    state.owner = "another"
    with pytest.raises(UnverifiedFill):
        record(workflow)
    assert params["ledger"].get(MEMBER) is None


@pytest.mark.parametrize("change,reason", [
    ({"consent": None}, "consent_missing"),
    ({"notice": None}, "post_fill_notice_missing"),
    ({"legal_approval": "true"}, "jurisdiction_not_approved"),
    ({"cancellation_operational": 1}, "cancellation_not_verified"),
])
def test_matching_billing_evidence_required(flow, change, reason):
    workflow, state, _, _ = flow
    record(workflow)
    state.now = END
    state.evidence = replace(state.evidence, **change)
    result = workflow.evaluate(MEMBER)
    assert result.rehearsal is None
    assert reason in result.readiness.reasons


def test_cancellation_during_evidence_lookup_is_observed_by_latest_trial_read(flow):
    workflow, state, params, _ = flow
    record(workflow)
    state.now = END

    def cancel_then_read(member_id):
        params["ledger"].cancel(member_id)
        return state.evidence

    params["billing_evidence"].evidence_for = cancel_then_read
    result = workflow.evaluate(MEMBER)
    assert result.rehearsal is None
    assert "first_fill_trial_unverified" in result.readiness.reasons


def test_billing_reader_failure_is_fail_closed_without_detail(flow):
    workflow, _, params, _ = flow

    def unavailable(member_id):
        raise RuntimeError("fixture-private-detail")

    params["billing_evidence"].evidence_for = unavailable
    result = workflow.evaluate(MEMBER)
    assert result.rehearsal is None
    assert result.readiness.reasons == ("billing_evidence_unavailable",)
