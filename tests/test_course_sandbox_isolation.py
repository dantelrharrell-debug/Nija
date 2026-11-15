"""Sandbox-only NIJA Foundations checkout contract tests.

Tests use SQLite and in-process mocks. No Stripe charges, customer email,
Render writes, or broker/trading operations are performed.
"""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine

import billing_service as billing
import course_fulfillment as course
import course_portal as portal
from billing_service_store import BillingServiceStore


@pytest.fixture
def isolated_sandbox(monkeypatch, tmp_path):
    db = "sqlite:///" + str(tmp_path / "nija_course_sandbox.db")
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "true")
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_DB_ISOLATED", "true")
    monkeypatch.setenv("BILLING_DATABASE_URL", db)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_sandbox_only_not_real")
    monkeypatch.setenv("NIJA_COURSE_PUBLIC_URL", "https://nija-course-sandbox.onrender.com")
    return db


def fake_stripe(*, link=None, price=None, product=None, session_live=False,
                intent_live=False, charge_live=False, refunded=False):
    """Mock precise matching test-mode Stripe session, intent and charge."""
    link = course.SANDBOX_COURSE_LINK if link is None else link
    price = course.SANDBOX_COURSE_PRICE if price is None else price
    product = course.SANDBOX_COURSE_PRODUCT if product is None else product
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "id": "cs_test_foundations_sandbox",
        "livemode": session_live,
        "payment_link": link,
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "customer_details": {"email": "buyer@example.test"},
        "amount_subtotal": 9900,
        "amount_total": 9900,
        "total_details": {"amount_tax": 0, "amount_discount": 0},
        "customer": "cus_test_foundations",
        "payment_intent": "pi_test_foundations",
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {
            "id": price, "product": product, "unit_amount": 9900,
            "currency": "usd",
        }}], "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "livemode": intent_live, "status": "succeeded",
        "amount_received": 9900, "currency": "usd",
        "latest_charge": "ch_test_foundations",
    }
    stripe.Charge.retrieve.return_value = {
        "livemode": charge_live, "paid": True, "status": "succeeded",
        "currency": "usd", "amount": 9900, "amount_refunded": 9900 if refunded else 0,
        "payment_intent": "pi_test_foundations",
        "refunded": refunded, "disputed": False,
    }
    return stripe


def test_matching_sandbox_course_paid(isolated_sandbox):
    ledger = course.CourseLedger(create_engine(isolated_sandbox))
    outcome = course.reconcile_session(fake_stripe(), ledger, "cs_test_foundations_sandbox")
    assert outcome == {"session_id": "cs_test_foundations_sandbox", "paid": True}
    assert ledger.get("cs_test_foundations_sandbox")["granted"] is True


@pytest.mark.parametrize("override", [
    {"link": course.COURSE_LINK},
    {"price": course.COURSE_PRICE},
    {"product": "prod_mismatched"},
    {"session_live": True},
    {"intent_live": True},
    {"charge_live": True},
    {"refunded": True},
])
def test_sandbox_rejects_wrong_identity_mode_and_refunds(isolated_sandbox, override):
    ledger = course.CourseLedger(create_engine(isolated_sandbox))
    result = course.reconcile_session(fake_stripe(**override), ledger, "cs_test_foundations_sandbox")
    assert result is None or result["paid"] is False
    record = ledger.get("cs_test_foundations_sandbox")
    assert record is None or record["granted"] is False


@pytest.mark.parametrize("key,value", [
    ("STRIPE_SECRET_KEY", "sk_live_would_never_be_used"),
    ("BILLING_DATABASE_URL", "sqlite:////tmp/production_billing.db"),
    ("NIJA_COURSE_SANDBOX_DB_ISOLATED", "false"),
    ("NIJA_COURSE_PUBLIC_URL", "https://nija-billing-api.onrender.com"),
])
def test_sandbox_fails_closed_on_incomplete_isolation(isolated_sandbox, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    ledger = course.CourseLedger(create_engine(isolated_sandbox))
    assert course.expected_course_identity() is None
    assert course.reconcile_session(fake_stripe(), ledger, "cs_test_foundations_sandbox") is None
    assert ledger.get("cs_test_foundations_sandbox") is None


def test_live_identity_does_not_accept_sandbox_link(isolated_sandbox, monkeypatch):
    monkeypatch.setenv("NIJA_COURSE_SANDBOX_MODE", "false")
    assert course.expected_course_link() == course.COURSE_LINK
    ledger = course.CourseLedger(create_engine(isolated_sandbox))
    assert course.reconcile_session(fake_stripe(), ledger, "cs_test_foundations_sandbox") is None
    assert ledger.get("cs_test_foundations_sandbox") is None


def test_sandbox_signed_webhook_entitlement_claim_and_refund(
        isolated_sandbox, monkeypatch):
    monkeypatch.setenv("NIJA_COURSE_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("NIJA_COURSE_SESSION_SECRET", "only-for-testing-" * 4)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_sandbox_only")
    monkeypatch.setenv("RESEND_API_KEY", "re_sandbox_fake")
    store = BillingServiceStore(isolated_sandbox)
    app = billing.create_app(store)
    client = app.test_client()
    course_store = app.config["COURSE_PORTAL_STORE"]
    monkeypatch.setattr(course_store, "has_bundle", lambda: True)
    monkeypatch.setattr(
        course_store, "asset_bytes",
        lambda filename: b"%PDF-1.4 test" if filename.endswith(".pdf")
        else b"ID3 sandbox audiobook" if filename.endswith(".mp3") else None,
    )

    state = {"refunded": False}
    stripe = fake_stripe()
    charge = stripe.Charge.retrieve.return_value
    charge["id"] = "ch_test_foundations"
    def retrieve_charge(_id):
        charge["refunded"] = state["refunded"]
        charge["amount_refunded"] = 9900 if state["refunded"] else 0
        return charge
    stripe.Charge.retrieve.side_effect = retrieve_charge
    stripe.error = SimpleNamespace(SignatureVerificationError=ValueError)
    event = {
        "id": "evt_test_sandbox_foundations",
        "livemode": False,
        "type": "checkout.session.completed",
        "created": 1780000000,
        "data": {"object": {
            "id": "cs_test_foundations_sandbox",
            "livemode": False,
            "payment_link": course.SANDBOX_COURSE_LINK,
        }},
    }

    def construct_event(raw, signature, secret):
        assert raw == b"synthetic-verified"
        assert secret == "whsec_sandbox_only"
        if signature != "sandbox-valid":
            raise ValueError("bad signature")
        return event

    stripe.Webhook.construct_event.side_effect = construct_event
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    monkeypatch.setattr(portal, "_stripe", lambda: stripe)
    sent = []

    def send_email(url, *, json, headers, timeout):
        assert url == "https://api.resend.com/emails"
        assert json["to"] == ["buyer@example.test"]
        assert headers["Idempotency-Key"] == "nija-foundations-delivery-v1-cs_test_foundations_sandbox"
        sent.append(json)
        return SimpleNamespace(status_code=201, json=lambda: {"id": "email_sandbox_fake"})

    monkeypatch.setattr(portal.requests, "post", send_email)
    assert client.post("/api/billing/webhook", data=b"synthetic-verified").status_code == 400
    assert client.post("/api/billing/webhook", data=b"synthetic-verified",
                       headers={"Stripe-Signature": "invalid"}).status_code == 400
    assert app.config["COURSE_LEDGER"].get("cs_test_foundations_sandbox") is None

    # Signed live event is denied with no entitlement or delivery.
    event["livemode"] = True
    assert client.post("/api/billing/webhook", data=b"synthetic-verified",
                       headers={"Stripe-Signature": "sandbox-valid"}).status_code == 400
    event["livemode"] = False
    assert sent == []

    # Non-course signed subscription events cannot mutate the membership ledger.
    event["type"] = "customer.subscription.created"
    ignored = client.post("/api/billing/webhook", data=b"synthetic-verified",
                          headers={"Stripe-Signature": "sandbox-valid"})
    assert ignored.status_code == 200 and ignored.get_json()["ignored"] is True
    event["type"] = "checkout.session.completed"

    accepted = client.post("/api/billing/webhook", data=b"synthetic-verified",
                           headers={"Stripe-Signature": "sandbox-valid"})
    assert accepted.status_code == 200, accepted.get_json()
    assert app.config["COURSE_LEDGER"].get("cs_test_foundations_sandbox")["granted"] is True
    assert len(sent) == 1

    duplicate = client.post("/api/billing/webhook", data=b"synthetic-verified",
                            headers={"Stripe-Signature": "sandbox-valid"})
    assert duplicate.status_code == 200
    assert duplicate.get_json().get("duplicate") is True
    assert len(sent) == 1

    token = re.search(r"/course-portal/claim\?token=([^\"< ]+)", sent[0]["html"]).group(1)
    claimed = client.get("/course-portal/claim?token=" + token, base_url="https://localhost")
    assert claimed.status_code == 303
    protected = client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf",
                           base_url="https://localhost")
    assert protected.status_code == 200
    assert client.get("/course-portal/claim?token=" + token,
                      base_url="https://localhost").status_code == 403
    state["refunded"] = True
    # Signed provider refund revokes the DURABLE ledger immediately, before
    # any further customer download request; one previously-sent email remains.
    event.update(id="evt_test_sandbox_refund", type="charge.refunded",
                 data={"object": {"id": "ch_test_foundations", "livemode": False}})
    refunded = client.post("/api/billing/webhook", data=b"synthetic-verified",
                           headers={"Stripe-Signature": "sandbox-valid"})
    assert refunded.status_code == 200
    event.update(id="evt_test_sandbox_refund", type="charge.refunded",
                 data={"object": {"id": "ch_test_foundations", "livemode": False}})
    reversal = client.post("/api/billing/webhook", data=b"synthetic-verified",
                           headers={"Stripe-Signature": "sandbox-valid"})
    assert reversal.status_code == 200
    assert app.config["COURSE_LEDGER"].get("cs_test_foundations_sandbox")["granted"] is False
    assert client.get("/course-portal/file/NIJA_Trading_Foundations_eBook.pdf",
                      base_url="https://localhost").status_code == 403
    assert len(sent) == 1
    repeat = client.post("/api/billing/webhook", data=b"synthetic-verified",
                         headers={"Stripe-Signature": "sandbox-valid"})
    assert repeat.status_code == 200 and repeat.get_json()["duplicate"] is True
    assert len(sent) == 1


def test_verified_charge_dispute_revokes_only_own_course_entitlement(isolated_sandbox):
    """Provider-refetched charge dispute revokes the matching course intent only."""
    ledger = course.CourseLedger(create_engine(isolated_sandbox))
    ledger.upsert("cs_test_own", "own@example.test", None,
                  "pi_test_foundations", "paid", True)
    ledger.upsert("cs_test_other", "other@example.test", None,
                  "pi_test_unrelated", "paid", True)
    stripe = fake_stripe()
    charge = stripe.Charge.retrieve.return_value
    charge["id"] = "ch_test_foundations"
    charge["payment_intent"] = "pi_test_foundations"
    charge["disputed"] = True
    stripe.Charge.retrieve.return_value = charge
    # Match only one test-mode course session on revalidation.
    course.handle_course_event(
        stripe, ledger, "charge.dispute.created",
        {"charge": "ch_test_foundations", "livemode": False}
    )
    assert ledger.get("cs_test_own")["granted"] is False
    assert ledger.get("cs_test_other")["granted"] is True
    # A live-mode charge cannot touch an isolated TEST entitlement.
    ledger.upsert("cs_test_own", "own@example.test", None,
                  "pi_test_foundations", "paid", True)
    charge["livemode"] = True
    course.handle_course_event(
        stripe, ledger, "charge.dispute.created",
        {"charge": "ch_test_foundations", "livemode": False}
    )
    assert ledger.get("cs_test_own")["granted"] is True


def _course_readiness_fixture(monkeypatch, isolated_sandbox, *, events=None,
                              price_patch=None, link_patch=None):
    """Provider-shaped test sandbox; never contacts Stripe or sends email."""
    monkeypatch.setenv("NIJA_BILLING_PUBLIC_URL", "https://nija-course-sandbox.onrender.com")
    monkeypatch.setenv("NIJA_BILLING_IDENTITY_SECRET", "test_identity_secret")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_fake_no_network")
    app = billing.create_app(BillingServiceStore(isolated_sandbox))
    price = {
        "id": course.SANDBOX_COURSE_PRICE, "product": course.SANDBOX_COURSE_PRODUCT,
        "livemode": False, "active": True, "type": "one_time",
        "unit_amount": 9900, "currency": "usd",
    }
    link = {"id": course.SANDBOX_COURSE_LINK, "livemode": False, "active": True}
    price.update(price_patch or {})
    link.update(link_patch or {})
    provider = SimpleNamespace(
        Price=SimpleNamespace(retrieve=lambda _id, **_opts: price),
        PaymentLink=SimpleNamespace(retrieve=lambda _id: link),
        WebhookEndpoint=SimpleNamespace(list=lambda **_opts: {"data": [{
            "url": "https://nija-course-sandbox.onrender.com/api/billing/webhook",
            "status": "enabled",
            "enabled_events": (list(billing._COURSE_SANDBOX_WEBHOOK_EVENTS)
                               if events is None else events),
        }]}),
    )
    monkeypatch.setattr(billing, "_stripe_module", lambda: provider)
    return app.test_client()


def test_course_sandbox_readyz_requires_only_course_checkout_and_reversal_events(
        isolated_sandbox, monkeypatch):
    client = _course_readiness_fixture(monkeypatch, isolated_sandbox)
    response = client.get("/readyz")
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"service": "nija-billing", "status": "ready"}
    assert not (billing._COURSE_SANDBOX_WEBHOOK_EVENTS &
                {"customer.subscription.created", "invoice.paid"})


@pytest.mark.parametrize("event", sorted([
    "checkout.session.completed", "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed", "checkout.session.expired",
    "charge.refunded", "charge.dispute.created",
]))
def test_course_sandbox_readyz_rejects_missing_required_webhook_event(
        isolated_sandbox, monkeypatch, event):
    events = sorted(billing._COURSE_SANDBOX_WEBHOOK_EVENTS - {event})
    client = _course_readiness_fixture(monkeypatch, isolated_sandbox, events=events)
    assert client.get("/readyz").status_code == 503


@pytest.mark.parametrize("price_patch", [
    {"livemode": True}, {"active": False}, {"type": "recurring"},
    {"currency": "eur"}, {"unit_amount": 100},
    {"product": "prod_wrong"}, {"id": "price_wrong"},
])
def test_course_sandbox_readyz_rejects_bad_price_identity(
        isolated_sandbox, monkeypatch, price_patch):
    client = _course_readiness_fixture(
        monkeypatch, isolated_sandbox, price_patch=price_patch)
    assert client.get("/readyz").status_code == 503


@pytest.mark.parametrize("link_patch", [
    {"livemode": True}, {"active": False}, {"id": "plink_wrong"},
])
def test_course_sandbox_readyz_rejects_bad_payment_link_identity(
        isolated_sandbox, monkeypatch, link_patch):
    client = _course_readiness_fixture(
        monkeypatch, isolated_sandbox, link_patch=link_patch)
    assert client.get("/readyz").status_code == 503


@pytest.mark.parametrize("name,value", [
    ("NIJA_COURSE_SANDBOX_DB_ISOLATED", "false"),
    ("STRIPE_SECRET_KEY", "sk_live_wrong_mode"),
    ("NIJA_COURSE_PUBLIC_URL", "https://production.example.test"),
])
def test_course_sandbox_readyz_rejects_invalid_isolation(
        isolated_sandbox, monkeypatch, name, value):
    client = _course_readiness_fixture(monkeypatch, isolated_sandbox)
    monkeypatch.setenv(name, value)
    assert client.get("/readyz").status_code == 503
