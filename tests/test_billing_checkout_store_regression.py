"""Regression tests for safe NIJA checkout persistence during concurrent retries."""
import pytest
from sqlalchemy import update

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


@pytest.mark.parametrize("status", ["mismatch", "failed", "payment_failed"])
def test_failed_checkout_cannot_be_replaced_without_confirmed_expiry(tmp_path, status):
    store = new_store(tmp_path)
    create(store, "cs_1")
    store.set_checkout_status(
        "cs_1", verification_status=status,
        reason="unreconciled_failure", revoke_customer=True,
    )
    with pytest.raises(BillingIdentityMismatch):
        create(store, "cs_2")
    assert store.get_checkout("cs_2") is None


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_delayed_terminal_subscription_does_not_allow_pending_checkout_replacement(tmp_path, status):
    store = new_store(tmp_path)
    create(store, "cs_1")
    with store.engine.begin() as conn:
        conn.execute(update(store.customers).values(status=status))
    with pytest.raises(BillingIdentityMismatch):
        create(store, "cs_2")
    assert store.get_checkout("cs_2") is None


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


@pytest.mark.parametrize("delayed_status", ["expired", "payment_failed"])
def test_delayed_stripe_failure_does_not_revoke_verified_trial(tmp_path, delayed_status):
    store = new_store(tmp_path)
    create(store, "cs_1")
    store.mark_checkout_verified(
        session_id="cs_1", customer_id="cus_1",
        subscription_id="sub_1", payment_status="no_payment_required",
    )
    assert store.apply_subscription_state(
        user_id="app-123", customer_id="cus_1", subscription_id="sub_1",
        status="trialing", offer_code="founding_beta",
        current_period_end=1999999999, entitled=True,
        reason="authoritative_subscription_state", event_created=100,
    )
    assert store.verification_record("cs_1")["verified"] is True

    store.set_checkout_status(
        "cs_1", verification_status=delayed_status,
        reason="out_of_order_stripe_event", verified=False,
        revoke_customer=True,
    )

    customer = store.get_customer("app-123")
    assert customer["status"] == "trialing"
    assert customer["entitled"] is True
    assert customer["stripe_subscription_id"] == "sub_1"
    checkout = store.get_checkout("cs_1")
    assert checkout["verified"] is True
    assert checkout["verification_status"] == "validated"
    assert store.verification_record("cs_1")["verified"] is True


def test_security_mismatch_still_revokes_verified_trial(tmp_path):
    store = new_store(tmp_path)
    create(store, "cs_1")
    store.mark_checkout_verified(
        session_id="cs_1", customer_id="cus_1",
        subscription_id="sub_1", payment_status="no_payment_required",
    )
    assert store.apply_subscription_state(
        user_id="app-123", customer_id="cus_1", subscription_id="sub_1",
        status="trialing", offer_code="founding_beta",
        current_period_end=1999999999, entitled=True,
        reason="authoritative_subscription_state", event_created=100,
    )

    store.mark_checkout_mismatch("cs_1", "stripe_customer_identity_mismatch")

    assert store.get_customer("app-123")["entitled"] is False
    assert store.get_customer("app-123")["status"] == "mismatch"
    assert store.get_checkout("cs_1")["verified"] is False
    assert store.verification_record("cs_1")["verified"] is False
