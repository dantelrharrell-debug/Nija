"""Regression tests for safe NIJA checkout persistence during concurrent retries."""
import pytest

from billing_service_store import BillingIdentityMismatch, BillingServiceStore


def new_store(tmp_path):
    return BillingServiceStore(f"sqlite:///{tmp_path / 'store.db'}")


def create(store, session_id):
    store.create_checkout(
        user_id="app-123", email="member@example.test",
        offer_code="founding_beta", expected_price_id="price_1",
        expected_product_id="prod_1", session_id=session_id,
        customer_id=None,
    )


def test_second_pending_checkout_cannot_replace_first(tmp_path):
    store = new_store(tmp_path)
    create(store, "cs_1")
    with pytest.raises(BillingIdentityMismatch):
        create(store, "cs_2")
    assert store.get_checkout("cs_2") is None
    assert store.latest_checkout_for_user("app-123")["checkout_session_id"] == "cs_1"


def test_expired_checkout_can_be_replaced(tmp_path):
    store = new_store(tmp_path)
    create(store, "cs_1")
    store.set_checkout_status(
        "cs_1", verification_status="expired",
        reason="stripe_checkout_expired", revoke_customer=True,
    )
    create(store, "cs_2")
    assert store.get_checkout("cs_1")["verification_status"] == "expired"
    assert store.latest_checkout_for_user("app-123")["checkout_session_id"] == "cs_2"


def test_verified_trial_is_not_reset_by_checkout_race(tmp_path):
    store = new_store(tmp_path)
    create(store, "cs_1")
    store.mark_checkout_verified(
        session_id="cs_1", customer_id="cus_1",
        subscription_id="sub_1", payment_status="no_payment_required",
    )
    changed = store.apply_subscription_state(
        user_id="app-123", customer_id="cus_1", subscription_id="sub_1",
        status="trialing", offer_code="founding_beta",
        current_period_end=1999999999, entitled=True,
        reason="authoritative_subscription_state", event_created=100,
    )
    assert changed is True
    assert store.get_customer("app-123")["entitled"] is True
    with pytest.raises(BillingIdentityMismatch):
        create(store, "cs_2")
    assert store.get_customer("app-123")["entitled"] is True
    assert store.get_customer("app-123")["stripe_subscription_id"] == "sub_1"
    assert store.get_checkout("cs_2") is None
