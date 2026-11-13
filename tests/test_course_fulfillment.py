"""Course verifier regression tests. No Stripe live charges."""
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine

from course_fulfillment import CourseLedger, reconcile_session, COURSE_LINK, COURSE_PRICE, COURSE_PRODUCT


def test_valid_paid_course(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "course.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "amount_subtotal": 9900, "amount_total": 9900,
        "customer": "cus_test", "payment_intent": "pi_test",
        "amount_subtotal": 9900, "amount_total": 9900,
        "total_details": {"amount_tax": 0, "amount_discount": 0},
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "livemode": True, "status": "succeeded", "amount_received": 9900, "currency": "usd", "latest_charge": "ch_test",
    }
    stripe.Charge.retrieve.return_value = {"livemode": True, "paid": True, "status": "succeeded", "amount": 9900,
                                           "currency": "usd", "payment_intent": "pi_test",
                                           "refunded": False, "amount_refunded": 0, "disputed": False}
    result = reconcile_session(stripe, ledger, "cs_test_paid")
    assert result["paid"] is True
    assert ledger.get("cs_test_paid")["granted"] is True


def test_unpaid_course_cannot_grant(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "course.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "open",
        "payment_status": "unpaid", "customer_details": {"email": "buyer@example.com"},
        "amount_subtotal": 9900, "amount_total": 9900,
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
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "amount_subtotal": 9900, "amount_total": 9900,
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
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "amount_subtotal": 9900, "amount_total": 9900,
        "payment_intent": "pi_refunded",
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "livemode": True, "status": "succeeded", "amount_received": 9900, "currency": "usd",
        "latest_charge": "ch_refunded",
    }
    stripe.Charge.retrieve.return_value = {"livemode": True, "paid": True, "status": "succeeded", "amount": 9900,
                                           "currency": "usd", "payment_intent": "pi_refunded",
                                           "refunded": True, "amount_refunded": 9900, "disputed": False}
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


def test_tax_inclusive_course_payment_succeeds(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "tax.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "customer": "cus_tax", "payment_intent": "pi_tax",
        "amount_subtotal": 9900, "amount_total": 10800,
        "total_details": {"amount_tax": 900, "amount_discount": 0},
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "livemode": True, "status": "succeeded", "amount_received": 10800, "currency": "usd",
        "latest_charge": "ch_tax",
    }
    stripe.Charge.retrieve.return_value = {
        "livemode": True, "paid": True, "status": "succeeded", "currency": "usd", "amount": 10800,
        "payment_intent": "pi_tax", "refunded": False, "amount_refunded": 0, "disputed": False,
    }
    assert reconcile_session(stripe, ledger, "cs_tax")["paid"] is True
    assert ledger.get("cs_tax")["granted"] is True


def test_tax_amount_mismatch_denied(tmp_path):
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "mismatch.db")))
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment", "status": "complete",
        "payment_status": "paid", "customer_details": {"email": "buyer@example.com"},
        "payment_intent": "pi_wrong_total", "amount_subtotal": 9900,
        "amount_total": 11800, "total_details": {"amount_tax": 900, "amount_discount": 0},
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    assert reconcile_session(stripe, ledger, "cs_mismatch") is None
    assert ledger.get("cs_mismatch") is None


@pytest.mark.parametrize("resource", ["session", "intent", "charge"])
@pytest.mark.parametrize("mode", [None, False, 0, 1, "true"])
def test_live_course_requires_explicit_boolean_mode(tmp_path, resource, mode):
    """Incomplete or test-mode provider objects never authorize live delivery."""
    stripe = _live_course_provider()
    target = {"session": stripe.checkout.Session.retrieve.return_value,
              "intent": stripe.PaymentIntent.retrieve.return_value,
              "charge": stripe.Charge.retrieve.return_value}[resource]
    target["livemode"] = mode
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "mode.db")))
    result = reconcile_session(stripe, ledger, "cs_live_course")
    assert result is None or result["paid"] is False
    record = ledger.get("cs_live_course")
    assert record is None or record["granted"] is False


@pytest.mark.parametrize("event_type", ["charge.refunded", "charge.dispute.created"])
def test_course_reversal_reconciles_only_matching_purchase(tmp_path, event_type):
    from course_fulfillment import handle_course_event
    stripe = _live_course_provider()
    charge = stripe.Charge.retrieve.return_value
    charge["id"] = "ch_test_foundations"
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "reversal.db")))
    assert reconcile_session(stripe, ledger, "cs_live_course")["paid"] is True
    ledger.upsert("cs_unrelated", "other@example.test", None, "pi_unrelated", "paid", True)
    charge["refunded"] = event_type == "charge.refunded"
    charge["amount_refunded"] = 9900 if charge["refunded"] else 0
    charge["disputed"] = event_type == "charge.dispute.created"
    obj = {"id": "ch_test_foundations" if charge["refunded"] else "dp_test",
           "charge": "ch_test_foundations", "livemode": True}
    handle_course_event(stripe, ledger, event_type, obj)
    handle_course_event(stripe, ledger, event_type, obj)
    assert ledger.get("cs_live_course")["granted"] is False
    assert ledger.get("cs_unrelated")["granted"] is True
    # A delayed completion cannot restore a reversed payment.
    handle_course_event(stripe, ledger, "checkout.session.completed",
                        {"id": "cs_live_course", "livemode": True, "payment_link": COURSE_LINK})
    assert ledger.get("cs_live_course")["granted"] is False


@pytest.mark.parametrize("event_type", ["charge.refunded", "charge.dispute.created"])
def test_course_reversal_rejects_unverified_charge(tmp_path, event_type):
    from course_fulfillment import handle_course_event
    ledger = CourseLedger(create_engine("sqlite:///" + str(tmp_path / "unverified.db")))
    ledger.upsert("cs_existing", "buyer@example.test", None, "pi_existing", "paid", True)
    stripe = Mock()
    stripe.Charge.retrieve.return_value = {"id": "ch_other", "livemode": True,
                                          "payment_intent": "pi_existing"}
    obj = {"id": "ch_expected" if event_type == "charge.refunded" else "dp_test",
           "charge": "ch_expected", "livemode": True}
    handle_course_event(stripe, ledger, event_type, obj)
    assert ledger.get("cs_existing")["granted"] is True
    stripe.checkout.Session.retrieve.assert_not_called()


def _live_course_provider():
    """Self-contained provider fixture; independent of pytest import ordering."""
    stripe = Mock()
    stripe.checkout.Session.retrieve.return_value = {
        "livemode": True, "payment_link": COURSE_LINK, "mode": "payment",
        "status": "complete", "payment_status": "paid", "amount_subtotal": 9900,
        "amount_total": 9900, "total_details": {"amount_tax": 0, "amount_discount": 0},
        "customer_details": {"email": "buyer@example.test"},
        "payment_intent": "pi_test_foundations",
    }
    stripe.checkout.Session.list_line_items.return_value = {
        "data": [{"quantity": 1, "price": {"id": COURSE_PRICE, "product": COURSE_PRODUCT,
                                           "unit_amount": 9900, "currency": "usd"}}],
        "has_more": False,
    }
    stripe.PaymentIntent.retrieve.return_value = {
        "livemode": True, "status": "succeeded", "amount_received": 9900,
        "currency": "usd", "latest_charge": "ch_test_foundations",
    }
    stripe.Charge.retrieve.return_value = {
        "livemode": True, "paid": True, "status": "succeeded", "amount": 9900,
        "currency": "usd", "payment_intent": "pi_test_foundations",
        "refunded": False, "amount_refunded": 0, "disputed": False,
    }
    return stripe
