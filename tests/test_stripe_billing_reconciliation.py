"""Focused checks for repeat checkout identity and signed webhook state."""

from types import SimpleNamespace

from flask import Flask, request

import stripe_billing_api as billing
from billing_store import BillingStore


def _client(monkeypatch, store):
    app = Flask(__name__)
    app.register_blueprint(billing.stripe_billing_api)

    @app.before_request
    def authenticate_test_user():
        if request.path == "/api/billing/checkout":
            request.user_id = "nija-user-1"

    monkeypatch.setattr(billing, "get_billing_store", lambda: store)
    return app.test_client()


def test_repeat_checkout_reuses_recorded_customer(monkeypatch, tmp_path):
    store = BillingStore(str(tmp_path / "users.db"))
    store.upsert(user_id="nija-user-1", status="checkout_completed", customer_id="cus_existing")
    client = _client(monkeypatch, store)
    assignment = SimpleNamespace(offer_code=billing.FOUNDING_BETA_OFFER, trial_days=0, to_dict=lambda: {})
    monkeypatch.setattr(billing, "get_commercial_offer_store", lambda: SimpleNamespace(get_assignment=lambda _: assignment))
    monkeypatch.setattr(billing, "get_user_database", lambda: SimpleNamespace(get_user=lambda _: {"email": "user@example.test"}))
    monkeypatch.setattr(billing, "_price_id_for_offer", lambda _: "price_test")
    captured = {}

    def create_session(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="cs_test", url="https://checkout.stripe.test/test")

    monkeypatch.setattr(billing, "_stripe_module", lambda: SimpleNamespace(
        checkout=SimpleNamespace(Session=SimpleNamespace(create=create_session))
    ))
    response = client.post("/api/billing/checkout")
    assert response.status_code == 200
    assert captured["customer"] == "cus_existing"
    assert "customer_email" not in captured


def test_active_subscription_cannot_be_reset_by_repeat_checkout(monkeypatch, tmp_path):
    store = BillingStore(str(tmp_path / "users.db"))
    store.upsert(user_id="nija-user-1", status="active", customer_id="cus_existing", subscription_id="sub_live")
    client = _client(monkeypatch, store)
    assignment = SimpleNamespace(offer_code=billing.FOUNDING_BETA_OFFER, trial_days=0, to_dict=lambda: {})
    monkeypatch.setattr(billing, "get_commercial_offer_store", lambda: SimpleNamespace(get_assignment=lambda _: assignment))
    monkeypatch.setattr(billing, "get_user_database", lambda: SimpleNamespace(get_user=lambda _: {"email": "user@example.test"}))
    monkeypatch.setattr(billing, "_price_id_for_offer", lambda _: "price_test")
    monkeypatch.setattr(billing, "_stripe_module", lambda: SimpleNamespace(
        checkout=SimpleNamespace(Session=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(
            AssertionError("Active subscriber must not create another checkout")
        )))
    ))
    assert client.post("/api/billing/checkout").status_code == 409
    record = store.get("nija-user-1")
    assert (record.status, record.subscription_id) == ("active", "sub_live")


def test_signed_checkout_events_do_not_mark_unpaid_payment_complete(monkeypatch, tmp_path):
    store = BillingStore(str(tmp_path / "users.db"))
    client = _client(monkeypatch, store)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "id": "cs_test", "customer": "cus_test", "subscription": "sub_test",
            "payment_status": "unpaid", "metadata": {"nija_user_id": "nija-user-1"},
        }},
    }
    monkeypatch.setattr(billing, "_stripe_module", lambda: SimpleNamespace(
        Webhook=SimpleNamespace(construct_event=lambda *_: event)
    ))
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "test"}).status_code == 200
    assert store.get("nija-user-1").status == "checkout_unpaid"

    event["type"] = "checkout.session.async_payment_succeeded"
    event["data"]["object"]["payment_status"] = "paid"
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "test"}).status_code == 200
    assert store.get("nija-user-1").status == "checkout_completed"

    event["type"] = "customer.subscription.updated"
    event["data"]["object"] = {
        "id": "sub_test", "customer": "cus_test", "status": "active",
        "metadata": {"nija_user_id": "nija-user-1"},
    }
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "test"}).status_code == 200
    event["type"] = "checkout.session.completed"
    event["data"]["object"] = {
        "id": "cs_test", "customer": "cus_test", "subscription": "sub_test",
        "payment_status": "unpaid", "metadata": {"nija_user_id": "nija-user-1"},
    }
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "test"}).status_code == 200
    assert store.get("nija-user-1").status == "active"


def test_checkout_event_cannot_replace_existing_customer(monkeypatch, tmp_path):
    store = BillingStore(str(tmp_path / "users.db"))
    store.upsert(user_id="nija-user-1", status="active", customer_id="cus_first", subscription_id="sub_first")
    client = _client(monkeypatch, store)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    event = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_other", "customer": "cus_other", "subscription": "sub_other",
        "payment_status": "paid", "metadata": {"nija_user_id": "nija-user-1"},
    }}}
    monkeypatch.setattr(billing, "_stripe_module", lambda: SimpleNamespace(
        Webhook=SimpleNamespace(construct_event=lambda *_: event)
    ))
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "test"}).status_code == 200
    record = store.get("nija-user-1")
    assert (record.customer_id, record.subscription_id, record.status) == ("cus_first", "sub_first", "active")


def test_generic_payment_link_and_bad_signature_cannot_grant_billing_state(monkeypatch, tmp_path):
    store = BillingStore(str(tmp_path / "users.db"))
    client = _client(monkeypatch, store)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    event = {"type": "checkout.session.completed", "data": {"object": {
        "id": "cs_generic", "customer": "cus_generic", "payment_status": "paid", "metadata": {},
    }}}

    def construct_event(_payload, signature, _secret):
        if signature != "valid-test-signature":
            raise ValueError("Invalid signature")
        return event

    monkeypatch.setattr(billing, "_stripe_module", lambda: SimpleNamespace(
        Webhook=SimpleNamespace(construct_event=construct_event)
    ))
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "bad"}).status_code == 400
    assert client.post("/api/billing/webhook", headers={"Stripe-Signature": "valid-test-signature"}).status_code == 200
    assert store.list_by_status(["active", "checkout_completed"]) == []
