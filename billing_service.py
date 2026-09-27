"""Dedicated NIJA Stripe billing authority.

Runs as a separate HTTPS service from the trading runtime. Billing entitlement
never enables broker execution; trading gates remain independently authoritative.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

import stripe
from flask import Flask, jsonify, request
from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("nija.billing.service")
app = Flask(__name__)
Base = declarative_base()


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    return value


engine = create_engine(_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class BillingSession(Base):
    __tablename__ = "billing_sessions"
    id = Column(Integer, primary_key=True)
    application_id = Column(String(191), nullable=False, index=True)
    email = Column(String(320), nullable=False)
    offer_code = Column(String(128), nullable=False)
    expected_price_id = Column(String(191), nullable=False)
    expected_product_id = Column(String(191), nullable=True)
    stripe_session_id = Column(String(191), nullable=False, unique=True, index=True)
    stripe_customer_id = Column(String(191), nullable=True, index=True)
    stripe_subscription_id = Column(String(191), nullable=True, unique=True, index=True)
    status = Column(String(64), nullable=False, default="checkout_created")
    entitlement_active = Column(Boolean, nullable=False, default=False)
    current_period_end = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class StripeEvent(Base):
    __tablename__ = "stripe_events"
    event_id = Column(String(191), primary_key=True)
    event_type = Column(String(128), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(engine)


def _stripe() -> Any:
    key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = key
    return stripe


def _internal_authorized() -> bool:
    expected = os.getenv("NIJA_BILLING_INTERNAL_TOKEN", "").strip()
    supplied = request.headers.get("X-NIJA-Billing-Token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _offer_price(offer_code: str) -> tuple[str, str | None]:
    safe = "".join(c if c.isalnum() else "_" for c in offer_code.upper())
    price = os.getenv(f"STRIPE_PRICE_{safe}", "").strip()
    product = os.getenv(f"STRIPE_PRODUCT_{safe}", "").strip() or None
    if not price:
        raise RuntimeError("Offer is not configured")
    return price, product


def _site_url() -> str:
    return os.getenv("NIJA_PUBLIC_SITE_URL", "https://nijaaitrading.com").rstrip("/")


def _value(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _metadata(obj: Any) -> dict[str, Any]:
    return dict(_value(obj, "metadata", {}) or {})


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _subscription_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    return _value(value, "id") if value else None


def _verify_checkout(record: BillingSession, session_id: str) -> tuple[Any, Any]:
    st = _stripe()
    checkout = st.checkout.Session.retrieve(
        session_id, expand=["line_items.data.price.product", "subscription"]
    )
    metadata = _metadata(checkout)
    if _value(checkout, "client_reference_id") != record.application_id:
        raise ValueError("client_reference_id mismatch")
    if metadata.get("nija_application_id") != record.application_id:
        raise ValueError("application identity mismatch")
    if metadata.get("nija_identity_bound") != "true":
        raise ValueError("unbound checkout")
    if metadata.get("nija_offer_code") != record.offer_code:
        raise ValueError("offer mismatch")

    line_items = _value(_value(checkout, "line_items", {}), "data", []) or []
    if len(line_items) != 1:
        raise ValueError("unexpected checkout line items")
    price = _value(line_items[0], "price", {})
    if _value(price, "id") != record.expected_price_id:
        raise ValueError("price mismatch")
    product = _value(price, "product")
    product_id = product if isinstance(product, str) else _value(product, "id")
    if record.expected_product_id and product_id != record.expected_product_id:
        raise ValueError("product mismatch")

    details = _value(checkout, "customer_details", {}) or {}
    actual_email = _normalize_email(_value(details, "email") or _value(checkout, "customer_email"))
    if not actual_email or actual_email != _normalize_email(record.email):
        raise ValueError("customer identity mismatch")

    subscription = _value(checkout, "subscription")
    sub_id = _subscription_id(subscription)
    if not sub_id:
        raise ValueError("subscription missing")
    if isinstance(subscription, str):
        subscription = st.Subscription.retrieve(sub_id, expand=["items.data.price.product"])
    return checkout, subscription


def _verify_subscription(record: BillingSession, subscription_id: str) -> Any:
    sub = _stripe().Subscription.retrieve(subscription_id, expand=["items.data.price.product"])
    metadata = _metadata(sub)
    if metadata.get("nija_application_id") != record.application_id:
        raise ValueError("subscription identity mismatch")
    if metadata.get("nija_identity_bound") != "true":
        raise ValueError("unbound subscription")
    if str(_value(sub, "customer", "")) != str(record.stripe_customer_id or ""):
        raise ValueError("customer mismatch")
    items = _value(_value(sub, "items", {}), "data", []) or []
    if len(items) != 1 or _value(_value(items[0], "price", {}), "id") != record.expected_price_id:
        raise ValueError("subscription price mismatch")
    return sub


def _set_subscription(record: BillingSession, sub: Any, force_inactive: bool = False) -> None:
    status = str(_value(sub, "status", "unknown"))
    record.status = status
    record.current_period_end = _value(sub, "current_period_end")
    record.stripe_subscription_id = _subscription_id(sub)
    record.entitlement_active = status in {"active", "trialing"} and not force_inactive
    record.updated_at = datetime.now(timezone.utc)


@app.get("/healthz")
def healthz():
    with SessionLocal() as db:
        db.execute(select(StripeEvent.event_id).limit(1))
    return jsonify({"ok": True, "service": "nija-billing"})


@app.post("/v1/checkout/session")
def create_checkout_session():
    if not _internal_authorized():
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    application_id = str(body.get("application_id") or "").strip()
    email = _normalize_email(body.get("email"))
    offer_code = str(body.get("offer_code") or "").strip()
    if not application_id or not email or not offer_code:
        return jsonify({"error": "application_id, email, and offer_code are required"}), 400
    try:
        price_id, product_id = _offer_price(offer_code)
        st = _stripe()
        metadata = {
            "nija_application_id": application_id,
            "nija_offer_code": offer_code,
            "nija_identity_bound": "true",
        }
        checkout = st.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            customer_email=email,
            client_reference_id=application_id,
            metadata=metadata,
            subscription_data={"metadata": metadata},
            success_url=os.getenv(
                "STRIPE_CHECKOUT_SUCCESS_URL",
                f"{_site_url()}/beta-success?session_id={{CHECKOUT_SESSION_ID}}",
            ),
            cancel_url=os.getenv("STRIPE_CHECKOUT_CANCEL_URL", f"{_site_url()}/apply"),
            allow_promotion_codes=False,
        )
        with SessionLocal.begin() as db:
            db.add(BillingSession(
                application_id=application_id,
                email=email,
                offer_code=offer_code,
                expected_price_id=price_id,
                expected_product_id=product_id,
                stripe_session_id=checkout.id,
            ))
        return jsonify({"checkout_url": checkout.url, "checkout_session_id": checkout.id})
    except IntegrityError:
        return jsonify({"error": "checkout session already recorded"}), 409
    except RuntimeError:
        return jsonify({"error": "checkout unavailable"}), 503
    except Exception:
        logger.exception("checkout creation failed")
        return jsonify({"error": "checkout unavailable"}), 502


@app.get("/v1/entitlements/checkout/<session_id>")
def checkout_entitlement(session_id: str):
    with SessionLocal() as db:
        record = db.scalar(select(BillingSession).where(BillingSession.stripe_session_id == session_id))
        if record is None:
            return jsonify({"verified": False, "status": "pending"}), 404
        return jsonify({
            "verified": bool(record.entitlement_active),
            "status": record.status,
            "checkout_session_id": record.stripe_session_id,
        })


@app.post("/v1/stripe/webhook")
def stripe_webhook():
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    signature = request.headers.get("Stripe-Signature", "")
    if not secret:
        return jsonify({"error": "webhook not configured"}), 503
    if not signature:
        return jsonify({"error": "missing signature"}), 400
    try:
        event = _stripe().Webhook.construct_event(request.get_data(cache=False), signature, secret)
    except Exception:
        logger.warning("rejected Stripe webhook with invalid payload/signature")
        return jsonify({"error": "invalid webhook"}), 400

    event_id = str(_value(event, "id", "") or "")
    event_type = str(_value(event, "type", "") or "")
    obj = _value(_value(event, "data", {}), "object", {})
    if not event_id:
        return jsonify({"error": "missing event id"}), 400

    try:
        with SessionLocal.begin() as db:
            if db.get(StripeEvent, event_id) is not None:
                return jsonify({"received": True, "duplicate": True})

            if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
                session_id = str(_value(obj, "id", "") or "")
                record = db.scalar(
                    select(BillingSession)
                    .where(BillingSession.stripe_session_id == session_id)
                    .with_for_update()
                )
                if record is None:
                    logger.warning("ignored generic/unbound Checkout Session %s", session_id)
                else:
                    checkout, sub = _verify_checkout(record, session_id)
                    record.stripe_customer_id = str(_value(checkout, "customer", "") or "") or None
                    payment_status = str(_value(checkout, "payment_status", "unpaid"))
                    _set_subscription(
                        record, sub,
                        force_inactive=payment_status not in {"paid", "no_payment_required"},
                    )

            elif event_type == "checkout.session.async_payment_failed":
                session_id = str(_value(obj, "id", "") or "")
                record = db.scalar(
                    select(BillingSession)
                    .where(BillingSession.stripe_session_id == session_id)
                    .with_for_update()
                )
                if record:
                    record.status = "payment_failed"
                    record.entitlement_active = False

            elif event_type in {
                "customer.subscription.created",
                "customer.subscription.updated",
                "customer.subscription.deleted",
            }:
                sub_id = str(_value(obj, "id", "") or "")
                record = db.scalar(
                    select(BillingSession)
                    .where(BillingSession.stripe_subscription_id == sub_id)
                    .with_for_update()
                )
                if record:
                    sub = _verify_subscription(record, sub_id)
                    _set_subscription(
                        record, sub,
                        force_inactive=event_type == "customer.subscription.deleted",
                    )

            elif event_type in {"invoice.payment_failed", "invoice.payment_action_required"}:
                sub_id = _subscription_id(_value(obj, "subscription"))
                if sub_id:
                    record = db.scalar(
                        select(BillingSession)
                        .where(BillingSession.stripe_subscription_id == sub_id)
                        .with_for_update()
                    )
                    if record:
                        record.status = "payment_failed"
                        record.entitlement_active = False

            elif event_type == "invoice.paid":
                sub_id = _subscription_id(_value(obj, "subscription"))
                if sub_id:
                    record = db.scalar(
                        select(BillingSession)
                        .where(BillingSession.stripe_subscription_id == sub_id)
                        .with_for_update()
                    )
                    if record:
                        _set_subscription(record, _verify_subscription(record, sub_id))

            db.add(StripeEvent(event_id=event_id, event_type=event_type))
        return jsonify({"received": True})
    except IntegrityError:
        return jsonify({"received": True, "duplicate": True})
    except ValueError as exc:
        logger.warning("billing authority mismatch event=%s type=%s: %s", event_id, event_type, exc)
        return jsonify({"error": "authority mismatch"}), 409
    except Exception:
        logger.exception("billing webhook processing failed event=%s type=%s", event_id, event_type)
        return jsonify({"error": "processing failed"}), 500
