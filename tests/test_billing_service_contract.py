"""Contract tests for the standalone Stripe-authoritative billing service."""

from __future__ import annotations

from types import SimpleNamespace

import jwt
import pytest
from sqlalchemy import update

import billing_service as billing
from billing_service_store import BillingServiceStore


def _configured_app(monkeypatch, tmp_path):
    # Contract fixtures model a healthy member service; outage cases override it.
    monkeypatch.setattr(billing, "member_broker_setup_available", lambda: True)
    monkeypatch.setenv("NIJA_BILLING_IDENTITY_SECRET", "identity-secret")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setenv("STRIPE_PRICE_FOUNDING_BETA", "price_founder")
    monkeypatch.setenv("STRIPE_PRODUCT_FOUNDING_BETA", "prod_founder")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_BETA_LEGACY_75", "price_standard_legacy")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_BETA_V2_99", "price_standard_v2")
    monkeypatch.setenv("STRIPE_PRODUCT_STANDARD_BETA", "prod_standard")
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'billing.db'}")
    return billing.create_app(store), store


def _identity_token() -> str:
    return jwt.encode(
        {
            "sub": "application-123",
            "email": "member@example.test",
            "offer_code": billing.FOUNDING_BETA_OFFER,
            "iss": "nija-identity",
            "aud": "nija-billing",
            "iat": 1780000000,
            "exp": 1990000000,
        },
        "identity-secret",
        algorithm="HS256",
    )


def _stripe_fixture():
    state = {
        "created": {},
        "session": None,
        "customer_email": "member@example.test",
        "subscription": None,
        "event": None,
        "construct_calls": 0,
    }

    def create_session(**kwargs):
        state["created"] = kwargs
        return {
            "id": "cs_nija_1",
            "url": "https://checkout.stripe.test/cs_nija_1",
            "customer": None,
        }

    def retrieve_session(_session_id, **_kwargs):
        return state["session"]

    def expire_session(_session_id):
        return {"id": _session_id, "status": "expired"}

    def retrieve_customer(customer_id):
        return {"id": customer_id, "email": state["customer_email"], "deleted": False}

    def retrieve_subscription(_subscription_id, **_kwargs):
        return state["subscription"]

    def construct_event(_payload, signature, _secret):
        state["construct_calls"] += 1
        if signature != "valid-signature":
            raise ValueError("bad signature")
        return state["event"]

    stripe = SimpleNamespace(
        checkout=SimpleNamespace(
            Session=SimpleNamespace(
                create=create_session,
                retrieve=retrieve_session,
                expire=expire_session,
            )
        ),
        Customer=SimpleNamespace(retrieve=retrieve_customer),
        Subscription=SimpleNamespace(retrieve=retrieve_subscription),
        Webhook=SimpleNamespace(construct_event=construct_event),
        error=SimpleNamespace(SignatureVerificationError=ValueError),
    )
    return state, stripe


def _create_checkout(client):
    return client.post(
        "/api/billing/checkout",
        headers={"Authorization": f"Bearer {_identity_token()}"},
    )


def _valid_checkout_session(payment_status="paid"):
    return {
        "id": "cs_nija_1",
        "mode": "subscription",
        "client_reference_id": "application-123",
        "metadata": {
            "nija_billing_contract": billing._BILLING_CONTRACT,
            "nija_user_id": "application-123",
            "nija_offer_code": billing.FOUNDING_BETA_OFFER,
        },
        "line_items": {
            "data": [{
                "quantity": 1,
                "price": {"id": "price_founder", "product": "prod_founder"},
            }]
        },
        "customer": "cus_1",
        "subscription": "sub_1",
        "customer_details": {"email": "member@example.test"},
        "payment_status": payment_status,
    }


def _valid_subscription(status="active"):
    return {
        "id": "sub_1",
        "customer": "cus_1",
        "status": status,
        "metadata": {
            "nija_billing_contract": billing._BILLING_CONTRACT,
            "nija_user_id": "application-123",
            "nija_offer_code": billing.FOUNDING_BETA_OFFER,
        },
        "items": {
            "data": [{
                "quantity": 1,
                "current_period_end": 1999999999,
                "price": {"id": "price_founder", "product": "prod_founder"},
            }]
        },
    }


def test_checkout_is_server_bound_and_does_not_grant_entitlement(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)

    response = _create_checkout(app.test_client())
    assert response.status_code == 200
    assert response.get_json()["entitlement_granted"] is False

    created = state["created"]
    assert created["client_reference_id"] == "application-123"
    assert created["metadata"]["nija_user_id"] == "application-123"
    assert created["metadata"]["nija_offer_code"] == billing.FOUNDING_BETA_OFFER
    assert created["metadata"]["nija_billing_contract"] == billing._BILLING_CONTRACT
    assert created["line_items"] == [{"price": "price_founder", "quantity": 1}]
    assert created["customer_email"] == "member@example.test"

    assert store.get_checkout("cs_nija_1")["verified"] is False
    assert store.get_customer("application-123")["entitled"] is False


def test_trial_outage_creates_no_checkout_or_membership(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    monkeypatch.setattr(billing, "member_broker_setup_available", lambda: False)
    response = _create_checkout(app.test_client())
    assert response.status_code == 503
    assert response.get_json()["error"] == "brokerage_setup_temporarily_unavailable"
    assert response.get_json()["checkout_created"] is False
    assert response.headers["Retry-After"] == "300"
    assert response.headers["Cache-Control"] == "no-store"
    assert state["created"] == {}
    assert store.get_customer("application-123") is None


def test_open_trial_checkout_not_reissued_during_setup_outage(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200
    state["created"] = {}
    monkeypatch.setattr(billing, "member_broker_setup_available", lambda: False)
    assert _create_checkout(client).status_code == 503
    assert state["created"] == {}
    assert store.get_customer("application-123")["entitled"] is False


def test_missing_or_invalid_signature_is_rejected(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    state["event"] = {"id": "evt_1", "type": "customer.subscription.updated", "created": 1, "data": {"object": {}}}

    client = app.test_client()
    assert client.post("/api/billing/webhook", data=b"{}").status_code == 400
    assert client.post(
        "/api/billing/webhook",
        data=b"{}",
        headers={"Stripe-Signature": "invalid"},
    ).status_code == 400


def test_generic_payment_link_cannot_create_membership_entitlement(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    state["event"] = {
        "id": "evt_generic",
        "type": "checkout.session.completed",
        "created": 10,
        "data": {"object": {"id": "cs_generic_payment_link", "payment_status": "paid"}},
    }

    response = app.test_client().post(
        "/api/billing/webhook",
        data=b"{}",
        headers={"Stripe-Signature": "valid-signature"},
    )
    assert response.status_code == 200
    assert store.get_checkout("cs_generic_payment_link") is None
    assert store.get_customer("application-123") is None


def test_checkout_stays_pending_until_authoritative_subscription_state(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    state["session"] = _valid_checkout_session()
    state["event"] = {
        "id": "evt_checkout",
        "type": "checkout.session.completed",
        "created": 100,
        "data": {"object": {"id": "cs_nija_1"}},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    pending = client.get("/api/billing/verify?session_id=cs_nija_1").get_json()
    assert pending["checkout_verified"] is True
    assert pending["verified"] is False
    assert pending["state"] == "pending"

    state["event"] = {
        "id": "evt_subscription",
        "type": "customer.subscription.updated",
        "created": 101,
        "data": {"object": _valid_subscription("active")},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    verified = client.get("/api/billing/verify?session_id=cs_nija_1").get_json()
    assert verified["verified"] is True
    assert verified["entitled"] is True
    assert verified["subscription_status"] == "active"


def test_price_or_product_mismatch_revokes_entitlement(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    bad = _valid_checkout_session()
    bad["line_items"]["data"][0]["price"]["id"] = "price_wrong"
    state["session"] = bad
    state["event"] = {
        "id": "evt_bad_price",
        "type": "checkout.session.completed",
        "created": 200,
        "data": {"object": {"id": "cs_nija_1"}},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    record = store.get_customer("application-123")
    assert record["entitled"] is False
    assert record["status"] == "mismatch"


def test_payment_failure_and_cancellation_revoke(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    state["session"] = _valid_checkout_session()
    state["event"] = {
        "id": "evt_checkout_2",
        "type": "checkout.session.completed",
        "created": 300,
        "data": {"object": {"id": "cs_nija_1"}},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    state["event"] = {
        "id": "evt_active_2",
        "type": "customer.subscription.updated",
        "created": 301,
        "data": {"object": _valid_subscription("active")},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200
    assert store.get_customer("application-123")["entitled"] is True

    state["event"] = {
        "id": "evt_failed_2",
        "type": "invoice.payment_failed",
        "created": 302,
        "data": {"object": {"subscription": "sub_1", "customer": "cus_1"}},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200
    assert store.get_customer("application-123")["entitled"] is False
    assert store.get_customer("application-123")["status"] == "payment_failed"

    state["event"] = {
        "id": "evt_canceled_2",
        "type": "customer.subscription.deleted",
        "created": 303,
        "data": {"object": _valid_subscription("canceled")},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200
    assert store.get_customer("application-123")["entitled"] is False
    assert store.get_customer("application-123")["status"] == "canceled"


def test_duplicate_event_id_is_idempotent(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    state["event"] = {
        "id": "evt_duplicate",
        "type": "checkout.session.completed",
        "created": 400,
        "data": {"object": {"id": "cs_generic"}},
    }
    client = app.test_client()

    first = client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    )
    second = client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True


def test_subscription_event_cannot_entitle_before_checkout_validation(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    state["event"] = {
        "id": "evt_subscription_first",
        "type": "customer.subscription.updated",
        "created": 500,
        "data": {"object": _valid_subscription("active")},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    before_checkout = store.get_customer("application-123")
    assert before_checkout["status"] == "active"
    assert before_checkout["entitled"] is False

    state["session"] = _valid_checkout_session()
    state["event"] = {
        "id": "evt_checkout_after_subscription",
        "type": "checkout.session.completed",
        "created": 501,
        "data": {"object": {"id": "cs_nija_1"}},
    }
    assert client.post(
        "/api/billing/webhook",
        data=b"raw",
        headers={"Stripe-Signature": "valid-signature"},
    ).status_code == 200

    after_checkout = store.get_customer("application-123")
    assert after_checkout["entitled"] is True
    verified = client.get("/api/billing/verify?session_id=cs_nija_1").get_json()
    assert verified["state"] == "verified"
    assert verified["verified"] is True
def test_second_checkout_reuses_open_session(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()

    assert _create_checkout(client).status_code == 200
    session = _valid_checkout_session(payment_status="unpaid")
    session.update({
        "status": "open",
        "expires_at": 1999999999,
        "url": "https://checkout.stripe.test/cs_nija_1",
        "customer": None,
        "subscription": None,
    })
    state["session"] = session
    second = _create_checkout(client)
    assert second.status_code == 200
    assert second.get_json()["reused_checkout"] is True
    assert second.get_json()["checkout_session_id"] == "cs_nija_1"


@pytest.mark.parametrize("details,email,customer,expected", [
    (None, "member@example.test", None, 200),
    (None, "other@example.test", None, 409),
    (None, None, None, 409),
    ({"email": "member@example.test"}, "other@example.test", None, 409),
    (None, None, "cus_1", 200),
])
def test_retry_requires_authoritative_customer_identity(
    monkeypatch, tmp_path, details, email, customer, expected,
):
    app, _store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200
    session = _valid_checkout_session(payment_status="unpaid")
    session.update({
        "status": "open", "expires_at": 1999999999,
        "url": "https://checkout.stripe.test/cs_nija_1",
        "customer_details": details, "customer_email": email,
        "customer": customer, "subscription": None,
    })
    state["session"] = session
    stripe.checkout.Session.create = lambda **_kw: pytest.fail("retry created a duplicate checkout")
    response = _create_checkout(client)
    assert response.status_code == expected
    if expected == 200:
        assert response.get_json()["reused_checkout"] is True


@pytest.mark.parametrize("status", [
    "mismatch", "payment_failed", "failed", "unpaid", "unknown", "canceled", "incomplete_expired",
])
def test_unreconciled_customer_state_never_creates_remote_checkout(monkeypatch, tmp_path, status):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200
    with store.engine.begin() as conn:
        conn.execute(update(store.customers).values(status=status))
    stripe.checkout.Session.create = lambda **_kw: pytest.fail("unreconciled state created a remote checkout")
    assert _create_checkout(client).status_code == 409


def test_checkout_with_missing_expiry_fails_closed(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    session = _valid_checkout_session(payment_status="unpaid")
    session.update({
        "status": "open", "expires_at": None,
        "url": "https://checkout.stripe.test/cs_nija_1",
        "customer": None, "subscription": None,
    })
    state["session"] = session
    response = _create_checkout(client)
    assert response.status_code == 503
    assert response.get_json()["error"] == "checkout_recovery_unavailable"


def test_expired_checkout_creates_new_pending_session(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    expired = _valid_checkout_session(payment_status="unpaid")
    expired.update({"status": "expired", "customer": None, "subscription": None})
    state["session"] = expired
    stripe.checkout.Session.create = lambda **kwargs: {
        "id": "cs_nija_2",
        "url": "https://checkout.stripe.test/cs_nija_2",
        "customer": None,
    }
    response = _create_checkout(client)
    assert response.status_code == 200
    assert response.get_json()["checkout_session_id"] == "cs_nija_2"
    assert store.get_checkout("cs_nija_1")["verification_status"] == "expired"
    assert store.latest_checkout_for_user("application-123")["checkout_session_id"] == "cs_nija_2"


def test_idempotent_checkout_collision_never_expires_another_session(monkeypatch, tmp_path):
    app, store = _configured_app(monkeypatch, tmp_path)
    state, stripe = _stripe_fixture()
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)
    client = app.test_client()
    assert _create_checkout(client).status_code == 200

    store.set_checkout_status(
        "cs_nija_1", verification_status="expired",
        reason="stripe_checkout_expired", revoke_customer=True,
    )
    stripe_session = _valid_checkout_session(payment_status="unpaid")
    stripe_session.update({"status": "expired", "customer": None, "subscription": None})
    state["session"] = stripe_session

    def unexpected_expiry(_session_id):
        raise AssertionError("idempotency collision must not expire an existing session")

    stripe.checkout.Session.expire = unexpected_expiry
    response = _create_checkout(client)
    assert response.status_code == 409
    assert response.get_json()["error"] == "checkout_identity_conflict"
    assert store.get_customer("application-123")["status"] == "expired"
    assert store.get_checkout("cs_nija_1")["verification_status"] == "expired"


def test_readyz_verifies_authoritative_billing_dependencies(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_BILLING_PUBLIC_URL", "https://billing.example.test")

    stripe = SimpleNamespace(
        Price=SimpleNamespace(
            retrieve=lambda price_id, **_kwargs: {
                "id": price_id,
                "active": True,
                "type": "recurring",
                "product": {"id": "prod_founder"},
            }
        ),
        WebhookEndpoint=SimpleNamespace(
            list=lambda **_kwargs: {
                "data": [{
                    "url": "https://billing.example.test/api/billing/webhook",
                    "status": "enabled",
                    "enabled_events": list(billing._STRIPE_WEBHOOK_EVENTS),
                }]
            }
        ),
    )
    monkeypatch.setattr(billing, "_stripe_module", lambda: stripe)

    response = app.test_client().get("/readyz")
    assert response.status_code == 200
    assert response.get_json() == {"service": "nija-billing", "status": "ready"}


def test_readyz_fails_closed_when_identity_secret_is_missing(monkeypatch, tmp_path):
    app, _store = _configured_app(monkeypatch, tmp_path)
    monkeypatch.setenv("NIJA_BILLING_PUBLIC_URL", "https://billing.example.test")
    monkeypatch.delenv("NIJA_BILLING_IDENTITY_SECRET")

    response = app.test_client().get("/readyz")
    assert response.status_code == 503
    assert response.get_json() == {"service": "nija-billing", "status": "not_ready"}



def test_versioned_standard_beta_price_mappings_are_distinct(monkeypatch, tmp_path):
    _configured_app(monkeypatch, tmp_path)
    legacy = billing._offer_config(billing.LEGACY_STANDARD_BETA_OFFER)
    current = billing._offer_config(billing.STANDARD_BETA_OFFER)

    assert legacy.offer_code == "standard_beta"
    assert legacy.price_id == "price_standard_legacy"
    assert current.offer_code == "standard_beta_v2"
    assert current.price_id == "price_standard_v2"
    assert legacy.price_id != current.price_id
