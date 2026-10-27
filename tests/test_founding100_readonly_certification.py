"""Offline regression checks: no real Stripe calls, payments or trading."""
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, text

from scripts.founding100_readonly_certification import audit


class FakeStripe:
    def __init__(self, expires, *, duplicate=False, status="trialing", email="member@example.test",
                 checkout_email="member@example.test", checkout_reference=None,
                 checkout_metadata=None, checkout_link="plink_synthetic",
                 checkout_mode="subscription", checkout_has_more=False,
                 checkout_count=1, supplied_email=None):
        self.api_key = None
        self.Customer = SimpleNamespace(retrieve=lambda _: dict(
            id="cus1", livemode=True, email=email, metadata={
                "nija_application_id": "app1",
                "nija_verified_email": "member@example.test",
                "nija_verification_source": "confirmed_identity"}))
        self.Subscription = SimpleNamespace(
            retrieve=lambda _: dict(
                id="sub1", customer="cus1", livemode=True, status=status,
                pause_collection={"behavior": "void"},
                metadata={"nija_user_id": "member1",
                          "nija_application_id": "app1",
                          "nija_offer_code": "founding_beta",
                          "nija_link_method": "operator_verified_existing_trial"},
                items={"data": [{"price": {"id": "price1", "product": "product1"},
                                 "current_period_end": expires, "quantity": 1}]}),
            list=lambda **_: {"data": [{"id": "sub1"}] + ([{"id": "sub2"}] if duplicate else []),
                              "has_more": False})
        session = {
            "livemode": True, "mode": checkout_mode, "subscription": "sub1",
            "customer": "cus1", "status": "complete", "payment_link": checkout_link,
            "client_reference_id": checkout_reference,
            "metadata": {} if checkout_metadata is None else checkout_metadata,
            "customer_details": {"email": checkout_email},
            "customer_email": supplied_email,
        }
        self.checkout = SimpleNamespace(Session=SimpleNamespace(
            list=lambda **_: {"data": [session] * checkout_count,
                              "has_more": checkout_has_more}))


def test_approved_existing_trial_is_not_full_onboarding():
    with tempfile.TemporaryDirectory() as directory:
        onboarding_path = str(Path(directory) / "onboarding.db")
        billing_url = f"sqlite:///{directory}/billing.db"
        expires = int(time.time()) + 86400
        with sqlite3.connect(onboarding_path) as db:
            db.execute("CREATE TABLE onboarding_members (application_id TEXT,member_id TEXT,"
                       "recipient TEXT,approved INTEGER,registered INTEGER)")
            db.execute("INSERT INTO onboarding_members VALUES "
                       "('app1','member1','member@example.test',1,1)")
        engine = create_engine(billing_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE billing_customers (nija_user_id TEXT,email TEXT,"
                              "offer_code TEXT,expected_price_id TEXT,expected_product_id TEXT,"
                              "stripe_customer_id TEXT,stripe_subscription_id TEXT,status TEXT,"
                              "entitled INTEGER,current_period_end INTEGER)"))
            conn.execute(text("INSERT INTO billing_customers VALUES "
                              "('member1','member@example.test','founding_beta','price1',"
                              "'product1','cus1','sub1','trialing',1,:end)"), {"end": expires})
        with engine.connect() as conn:
            before = conn.execute(text("SELECT * FROM billing_customers")).all()
        def check(api, application_id="app1"):
            return audit("member1", application_id, billing_url=billing_url,
                         onboarding_db_path=onboarding_path,
                         stripe_key="fake-test-key", stripe_api=api)
        valid = check(FakeStripe(expires))
        assert valid["authoritative_member_verified"] is True
        assert valid["full_onboarding_certified"] is False
        assert valid["authenticated_dashboard_verified"] is False
        assert valid["secure_broker_onboarding_verified"] is False
        assert check(FakeStripe(expires, duplicate=True))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, status="canceled"))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, email="wrong@example.test"))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires), application_id="wrong")["authoritative_member_verified"] is False
        # Legacy generic Payment Links cannot prove a different email merely
        # through mutable subscription operator-link metadata.
        assert check(FakeStripe(expires, checkout_email="other@example.test"))[
            "legacy_checkout_identity_reconciled"] is False
        assert check(FakeStripe(expires, checkout_email="other@example.test"))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_email=None))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_email="MEMBER@EXAMPLE.TEST"))[
            "authoritative_member_verified"] is True
        assert check(FakeStripe(expires, supplied_email="other@example.test"))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_link=None))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_metadata={"nija_user_id": "member1"}))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_reference="app1"))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_count=2))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_count=0))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_has_more=True))["authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_mode="payment"))["authoritative_member_verified"] is False

        # An authoritative NIJA checkout references the immutable user ID
        # rather than the application ID and carries the complete contract.
        signed_metadata = {
            "nija_billing_contract": "nija_web_subscription_v1",
            "nija_user_id": "member1",
            "nija_offer_code": "founding_beta",
        }
        assert check(FakeStripe(expires, checkout_reference="member1",
                                checkout_metadata=signed_metadata, checkout_email=None))[
            "authoritative_member_verified"] is True
        assert check(FakeStripe(expires, checkout_reference="app1",
                                checkout_metadata=signed_metadata))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_reference="member1",
                                checkout_metadata={"nija_user_id": "member1"}))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_reference="member1",
                                checkout_metadata=signed_metadata, checkout_email="other@example.test"))[
            "authoritative_member_verified"] is False
        assert check(FakeStripe(expires, checkout_reference="member1",
                                checkout_metadata={**signed_metadata, "nija_application_id": "wrong-app"}))[
            "authoritative_member_verified"] is False
        with engine.connect() as conn:
            assert conn.execute(text("SELECT * FROM billing_customers")).all() == before
        engine.dispose()


def test_missing_trusted_sources_fail_closed():
    result = audit("member1", "app1", billing_url="", onboarding_db_path="",
                   stripe_key="")
    assert result["authoritative_member_verified"] is False
    assert result["full_onboarding_certified"] is False
