"""Course verifier regression tests. No Stripe live charges."""
from unittest.mock import Mock
from sqlalchemy import create_engine

from course_fulfillment import CourseLedger, reconcile_session, COURSE_LINK, COURSE_PRICE, COURSE_PRODUCT


def test_valid_paid_course(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "course.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "customer": "cus_test", "payment_intent": "pi_test",
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "status": "succeeded", "amount_received": 9900, "currency": "usd", "latest_charge": "ch_test",
    }
    stripe.Charge.retrieve.return_value = {"refunded": False, "amount_refunded": 0, "disputed": False}
    result = reconcile_session(stripe, ledger, "cs_test_paid")
    assert result["paid"] is True
    assert ledger.get("cs_test_paid")["granted"] is True


def test_unpaid_course_cannot_grant(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "course.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "payment_link": COURSE_LINK, "mode": "payment", "status": "open",
        "payment_status": "unpaid", "customer_details": {"email": "buyer@example.com"},
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    assert reconcile_session(stripe, ledger, "cs_test_unpaid")["paid"] is False
    assert ledger.get("cs_test_unpaid")["granted"] is False


def test_wrong_product_never_grants(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "course.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": "prod_wrong",
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    assert reconcile_session(stripe, ledger, "cs_wrong") is None
    assert ledger.get("cs_wrong") is None


def test_refunded_charge_cannot_grant(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "refunded.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "payment_intent": "pi_refunded",
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "status": "succeeded", "amount_received": 9900, "currency": "usd",
        "latest_charge": "ch_refunded",
    }
    stripe.Charge.retrieve.return_value = {"refunded": True, "amount_refunded": 9900, "disputed": False}
    assert reconcile_session(stripe, ledger, "cs_refunded")["paid"] is False
    assert ledger.get("cs_refunded")["granted"] is False


def test_billing_app_registers_course_route_without_flask_context(monkeypatch, tmp_path):
    """Regression: route initialization cannot access current_app before app startup."""
    import billing_service as billing
    from billing_service_store import BillingServiceStore

    monkeypatch.setenv("BILLING_DATABASE_URL", f"sqlite:///{tmp_path / 'billing.db'}")
    store = BillingServiceStore(f"sqlite:///{tmp_path / 'billing.db'}")
    app = billing.create_app(store)
    client = app.test_client()

    response = client.get("/api/billing/course/status")
    assert response.status_code == 403
    assert response.get_json() == {
        "entitled": False,
        "delivery_enabled": False,
        "status": "requires_authenticated_delivery",
    }
    assert "COURSE_LEDGER" in app.config
    assert app.config["COURSE_LEDGER"].engine is store.engine
