from pathlib import Path

from billing_store import BillingStore


def test_billing_store_persists_and_updates_subscription(tmp_path: Path):
    store = BillingStore(str(tmp_path / "billing.db"))

    created = store.upsert(
        user_id="user_1",
        status="checkout_created",
        checkout_session_id="cs_test_1",
        offer_code="founding_beta",
    )
    assert created.user_id == "user_1"
    assert created.status == "checkout_created"
    assert created.offer_code == "founding_beta"

    updated = store.upsert(
        user_id="user_1",
        status="trialing",
        customer_id="cus_test_1",
        subscription_id="sub_test_1",
        current_period_end=2000000000,
    )
    assert updated.customer_id == "cus_test_1"
    assert updated.subscription_id == "sub_test_1"
    assert updated.checkout_session_id == "cs_test_1"
    assert updated.offer_code == "founding_beta"
    assert updated.status == "trialing"
    assert updated.current_period_end == 2000000000
    assert store.find_user_by_subscription("sub_test_1") == "user_1"


def test_billing_store_keeps_users_separate(tmp_path: Path):
    store = BillingStore(str(tmp_path / "billing.db"))
    store.upsert(user_id="user_a", status="active", subscription_id="sub_a")
    store.upsert(user_id="user_b", status="canceled", subscription_id="sub_b")

    assert store.get("user_a").status == "active"
    assert store.get("user_b").status == "canceled"
    assert store.find_user_by_subscription("sub_a") == "user_a"
    assert store.find_user_by_subscription("sub_b") == "user_b"
