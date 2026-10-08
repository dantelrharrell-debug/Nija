"""Fail-closed course payment verification, independent of subscription/broker entitlements."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, select, update, insert

COURSE_PRICE = "price_1U02soI0gfJjTf3EFtISyrYf"
COURSE_PRODUCT = "prod_V01AbvtwLMQPkn"
COURSE_LINK = "plink_1UEtWDI0gfJjTf3E5L0wb3K9"
course_routes = Blueprint("course_fulfillment", __name__)


class CourseLedger:
    def __init__(self, engine):
        self.engine = engine
        self.metadata = MetaData()
        self.table = Table(
            "billing_course_entitlements", self.metadata,
            Column("session_id", String(128), primary_key=True),
            Column("customer_email", String(320), nullable=False, index=True),
            Column("customer_id", String(128), nullable=True),
            Column("payment_intent", String(128), nullable=True),
            Column("status", String(32), nullable=False),
            Column("granted", Boolean, nullable=False, default=False),
            Column("updated_at", DateTime(timezone=True), nullable=False),
        )
        self.metadata.create_all(engine)

    def get(self, session_id):
        with self.engine.connect() as conn:
            row = conn.execute(select(self.table).where(self.table.c.session_id == session_id)).first()
            return dict(row._mapping) if row else None

    def upsert(self, session_id, email, customer_id, payment_intent, status, granted):
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            current = conn.execute(select(self.table).where(self.table.c.session_id == session_id)).first()
            values = dict(customer_email=email, customer_id=customer_id,
                          payment_intent=payment_intent, status=status,
                          granted=granted, updated_at=now)
            if current:
                conn.execute(update(self.table).where(self.table.c.session_id == session_id).values(**values))
            else:
                conn.execute(insert(self.table).values(session_id=session_id, **values))


def reconcile_session(stripe, ledger, session_id):
    """Never trust browser success redirects or the webhook event payload as payment proof."""
    session = stripe.checkout.Session.retrieve(session_id)
    if session.get("payment_link") != COURSE_LINK or session.get("mode") != "payment":
        return None
    lines = stripe.checkout.Session.list_line_items(session_id, limit=10, expand=["data.price.product"])
    items = lines.get("data", [])
    if len(items) != 1 or lines.get("has_more"):
        return None
    price = items[0].get("price") or {}
    product = price.get("product")
    product_id = product if isinstance(product, str) else (product or {}).get("id")
    if (items[0].get("quantity") != 1 or price.get("id") != COURSE_PRICE
            or product_id != COURSE_PRODUCT or price.get("unit_amount") != 9900
            or price.get("currency") != "usd"):
        return None
    email = ((session.get("customer_details") or {}).get("email") or "").strip().lower()
    if not email or "@" not in email:
        return None
    paid = session.get("status") == "complete" and session.get("payment_status") == "paid"
    intent = session.get("payment_intent")
    intent_id = intent if isinstance(intent, str) else (intent or {}).get("id")
    if intent_id:
        intent_obj = stripe.PaymentIntent.retrieve(intent_id)
        charge_paid = (intent_obj.get("status") == "succeeded"
                       and intent_obj.get("amount_received") == 9900
                       and intent_obj.get("currency") == "usd"
                       and intent_obj.get("amount_refunded", 0) == 0)
        # Stripe PaymentIntent objects do not always expose amount_refunded.
        # A charge must be checked separately before releasing course access.
        charge_id = intent_obj.get("latest_charge")
        if isinstance(charge_id, dict):
            charge_id = charge_id.get("id")
        if charge_id:
            charge = stripe.Charge.retrieve(charge_id)
            charge_paid = charge_paid and not charge.get("refunded") and charge.get("amount_refunded", 0) == 0 and not charge.get("disputed")
        else:
            charge_paid = False
        paid = paid and charge_paid
    else:
        paid = False
    ledger.upsert(session_id, email, session.get("customer"), intent_id,
                  "paid" if paid else "pending", paid)
    return {"session_id": session_id, "paid": paid}


def handle_course_event(stripe, ledger, event_type, obj):
    """Invoke only after the parent webhook verifies Stripe's signature."""
    if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded",
                          "checkout.session.async_payment_failed", "checkout.session.expired"}:
        return
    session_id = obj.get("id")
    if not session_id or not session_id.startswith("cs_"):
        return
    # Ignore every other Stripe product without changing its subscription state.
    if obj.get("payment_link") != COURSE_LINK:
        return
    reconcile_session(stripe, ledger, session_id)


def register_course_routes(app, store):
    # Disabled until the IONOS customer-auth integration is deployed and tested.
    ledger = CourseLedger(store.engine)
    app.config["COURSE_LEDGER"] = ledger

    @course_routes.get("/api/billing/course/status")
    def course_status():
        # This endpoint is informational only: it does not distribute content.
        # A Checkout Session ID is NOT sufficient authorization to receive lessons.
        return jsonify({"entitled": False, "delivery_enabled": False,
                        "status": "requires_authenticated_delivery"}), 403

    app.register_blueprint(course_routes)
    return ledger
