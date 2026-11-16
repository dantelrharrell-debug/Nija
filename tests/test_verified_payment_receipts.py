"""Offline billing receipt safety and deduplication tests. Never contacts Resend."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from verified_payment_receipts import (
    ReceiptOutbox, VerifiedInvoiceReceipt, process_batch_from_env,
    process_one, verified_invoice_from_stripe,
)


@pytest.fixture()
def identities():
    invoice = dict(
        id="in_unit_1", livemode=True, paid=True, status="paid",
        amount_paid=5000, amount_remaining=0, currency="usd",
        subscription="sub_unit_1", customer="cus_unit_1",
    )
    saved = dict(
        stripe_subscription_id="sub_unit_1", stripe_customer_id="cus_unit_1",
        entitled=True, email="customer@example.com", offer_code="founding_beta",
    )
    stripe = SimpleNamespace(Invoice=SimpleNamespace(retrieve=lambda _id: invoice))
    store = SimpleNamespace(
        find_user_by_subscription=lambda _id: "user-1",
        get_customer=lambda _user: saved,
    )
    return invoice, saved, stripe, store


@pytest.fixture()
def outbox():
    return ReceiptOutbox(create_engine("sqlite+pysqlite:///:memory:", future=True))


def test_authoritative_paid_invoice_is_required(identities):
    invoice, saved, stripe, store = identities
    receipt = verified_invoice_from_stripe(stripe, store, invoice)
    assert receipt is not None
    assert receipt.amount_cents == 5000
    assert receipt.payload()["amount_paid"] == "$50.00"
    assert receipt.email == "customer@example.com"
    for bad in (
        {"livemode": False}, {"paid": False}, {"status": "open"},
        {"amount_paid": 0}, {"amount_paid": -1},
        {"currency": "eur"}, {"amount_remaining": 1},
        {"customer": "cus_wrong"}, {"subscription": ""},
    ):
        stripe.Invoice.retrieve = lambda _id, value={**invoice, **bad}: value
        assert verified_invoice_from_stripe(stripe, store, invoice) is None


def test_identity_and_entitlement_are_required(identities):
    invoice, saved, stripe, store = identities
    saved["entitled"] = False
    assert verified_invoice_from_stripe(stripe, store, invoice) is None
    saved["entitled"] = True
    saved["offer_code"] = "unknown"
    assert verified_invoice_from_stripe(stripe, store, invoice) is None
    saved["offer_code"] = "founding_beta"
    saved["email"] = "customer@example.com\\nBcc:bad@example.com"
    assert verified_invoice_from_stripe(stripe, store, invoice) is None
    saved["email"] = "customer@example.com"
    store.find_user_by_subscription = lambda _id: None
    assert verified_invoice_from_stripe(stripe, store, invoice) is None


def test_one_receipt_row_per_verified_invoice(outbox):
    receipt = VerifiedInvoiceReceipt(
        "in_unit_1", "customer@example.com", 5000, "usd", "NIJA membership")
    assert outbox.enqueue(receipt) is True
    assert outbox.enqueue(receipt) is False
    assert len(outbox.pending()) == 1
    with pytest.raises(ValueError, match="identity_conflict"):
        outbox.enqueue(VerifiedInvoiceReceipt(
            "in_unit_1", "other@example.com", 5000, "usd", "NIJA membership"))


def test_accepted_receipt_cannot_send_twice(outbox):
    receipt = VerifiedInvoiceReceipt(
        "in_unit_1", "customer@example.com", 5000, "usd", "NIJA membership")
    outbox.enqueue(receipt)
    row = outbox.pending()[0]
    assert process_one(outbox, row, sender=lambda _email, _rec: "evt_unit_1")
    assert not process_one(outbox, row, sender=lambda _email, _rec: "evt_unit_2")
    assert outbox.status_counts() == {"accepted": 1}
    assert outbox.pending() == []


def test_timeout_stays_uncertain_and_does_not_retry(outbox):
    receipt = VerifiedInvoiceReceipt(
        "in_unit_1", "customer@example.com", 5000, "usd", "NIJA membership")
    outbox.enqueue(receipt)
    row = outbox.pending()[0]

    def timeout(_email, _receipt):
        raise TimeoutError("unknown provider outcome")

    assert process_one(outbox, row, sender=timeout) is False
    assert outbox.status_counts() == {"uncertain": 1}
    assert outbox.pending() == []


def test_worker_is_fail_closed_before_certification(monkeypatch, outbox):
    monkeypatch.delenv("NIJA_VERIFIED_PAYMENT_SEND_MODE", raising=False)
    with pytest.raises(RuntimeError, match="disabled"):
        process_batch_from_env(outbox)
    monkeypatch.setenv("NIJA_VERIFIED_PAYMENT_SEND_MODE", "controlled")
    monkeypatch.setenv("RESEND_API_KEY", "dummy-not-sent")
    with pytest.raises(RuntimeError, match="not_certified"):
        process_batch_from_env(outbox)
    monkeypatch.setenv("NIJA_VERIFIED_PAYMENT_RECEIPT_CERTIFIED", "true")
    with pytest.raises(RuntimeError, match="allowlist"):
        process_batch_from_env(outbox)
    monkeypatch.setenv("NIJA_PAYMENT_TEST_RECIPIENTS", "qa@example.com")
    outbox.enqueue(VerifiedInvoiceReceipt(
        "in_unit_1", "customer@example.com", 5000, "usd", "NIJA membership"))
    assert process_batch_from_env(outbox) == {"accepted": 0, "uncertain": 0}
    assert len(outbox.pending()) == 1
