from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from founding_trial_sandbox_receipt import (
    FOUNDING_STRIPE_TEST_PRICE,
    SandboxInvoiceReadback,
    TestBillingRun as BillingRun,
    verify_first_sandbox_invoice,
)
from founding_trial_sandbox_workflow import (
    FOUNDING_STRIPE_SANDBOX_ACCOUNT as ACCOUNT,
    SandboxBillingRehearsal,
)

DUE = datetime(2026, 11, 15, 10, 30, tzinfo=timezone.utc)
RUN = BillingRun(SandboxBillingRehearsal(ACCOUNT, 5000, DUE, "a" * 64),
                 "clock_fixture", "sub_fixture", "in_fixture")
RECEIPT = SandboxInvoiceReadback(
    ACCOUNT, False, RUN.test_clock_id, RUN.subscription_id, RUN.invoice_id,
    (FOUNDING_STRIPE_TEST_PRICE,), (RUN.invoice_id,), DUE, DUE + timedelta(hours=1),
    "paid", "usd", 5000, 5000, 0,
)


def verify(receipt=RECEIPT, run=RUN):
    requested = []
    reader = SimpleNamespace(read_invoice=lambda invoice_id: requested.append(invoice_id) or receipt)
    outcome = verify_first_sandbox_invoice(run, reader)
    if requested:
        assert requested == [run.invoice_id]
    return outcome


def test_matches_first_paid_test_clock_invoice_and_accepts_later_finalization():
    assert verify()


@pytest.mark.parametrize("change", [
    dict(account_id="acct_wrong"), dict(livemode=True), dict(livemode=0),
    dict(test_clock_id="clock_wrong"), dict(subscription_id="sub_wrong"),
    dict(invoice_id="in_wrong"), dict(price_ids=("price_wrong",)),
    dict(price_ids=(FOUNDING_STRIPE_TEST_PRICE, "price_wrong")),
    dict(positive_invoice_ids=("in_earlier", "in_fixture")),
    dict(positive_invoice_ids=("in_earlier",)), dict(positive_invoice_ids=()),
    dict(period_start=DUE - timedelta(seconds=1)),
    dict(period_start=DUE.replace(tzinfo=None)), dict(paid_at=DUE - timedelta(seconds=1)),
    dict(status="open"), dict(currency="cad"), dict(amount_due=0),
    dict(amount_paid=4999), dict(amount_remaining=1), dict(amount_remaining=False),
])
def test_rejects_unrelated_partial_live_or_duplicate_receipts(change):
    assert not verify(replace(RECEIPT, **change))


def test_read_failure_and_missing_evidence_fail_closed():
    def fail(_):
        raise RuntimeError("provider internals not for caller")
    assert not verify(None)
    assert not verify_first_sandbox_invoice(RUN, SimpleNamespace(read_invoice=fail))


def test_invalid_local_ids_do_not_call_provider():
    def fail(_):
        pytest.fail("invalid target should not trigger a provider read")
    reader = SimpleNamespace(read_invoice=fail)
    assert not verify_first_sandbox_invoice(None, reader)
    assert not verify_first_sandbox_invoice(replace(RUN, invoice_id="unknown"), reader)
    invalid = replace(RUN.rehearsal, sandbox_account_id="acct_other")
    assert not verify_first_sandbox_invoice(replace(RUN, rehearsal=invalid), reader)
