"""Production Stripe Checkout integration for NIJA web subscriptions.

Secrets and Stripe Price IDs are read only from environment variables. The API
uses the user's already-locked NIJA commercial offer so Stripe cannot become a
second source of pricing truth.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from auth.user_database import get_user_database
from billing_store import get_billing_store
from commercial_offer_store import get_commercial_offer_store
from pricing_policy import FOUNDING_BETA_OFFER, STANDARD_BETA_OFFER

logger = logging.getLogger("nija.billing.stripe")

stripe_billing_api = Blueprint("stripe_billing_api", __name__)

_PRICE_ENV = {
    FOUNDING_BETA_OFFER: "STRIPE_PRICE_FOUNDING_BETA",
    STANDARD_BETA_OFFER: "STRIPE_PRICE_STANDARD_BETA",
}


def _stripe_module():
    import stripe

    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("Stripe is not configured")
    stripe.api_key = secret
    return stripe


def _site_url() -> str:
    return os.getenv("NIJA_PUBLIC_SITE_URL", "https://nijaaitrading.com").rstrip("/")


def _price_id_for_offer(offer_code: str) -> str:
    env_name = _PRICE_ENV.get(offer_code)
    if not env_name:
        raise RuntimeError("This NIJA offer is not available for web subscription checkout")
    value = os.getenv(env_name, "").strip()
    if not value:
        raise RuntimeError(f"Stripe Price ID is not configured for {offer_code}")
    return value


def _obj_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


@stripe_billing_api.post("/api/billing/checkout")
def create_checkout_session():
    """Create Stripe Checkout for the authenticated user's locked beta offer."""
    user_id = getattr(request, "user_id", None)
    if not isinstance(user_id, str) or not user_id:
        return jsonify({"error": "Authentication required"}), 401

    assignment = get_commercial_offer_store().get_assignment(user_id)
    if assignment is None:
        return jsonify({"error": "Commercial offer not assigned"}), 409

    try:
        price_id = _price_id_for_offer(assignment.offer_code)
        stripe = _stripe_module()
    except RuntimeError as exc:
        logger.error("Stripe checkout configuration error: %s", exc)
        return jsonify({"error": "Checkout is temporarily unavailable"}), 503

    user = get_user_database().get_user(user_id)
    if not user or not user.get("email"):
        return jsonify({"error": "User account email is unavailable"}), 409

    success_url = os.getenv(
        "STRIPE_CHECKOUT_SUCCESS_URL",
        f"{_site_url()}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
    )
    cancel_url = os.getenv(
        "STRIPE_CHECKOUT_CANCEL_URL",
        f"{_site_url()}/checkout/cancelled",
    )

    metadata = {
        "nija_user_id": user_id,
        "nija_offer_code": assignment.offer_code,
        "nija_price_locked": "true",
    }
    subscription_data: dict[str, Any] = {"metadata": metadata}
    if assignment.trial_days > 0:
        subscription_data["trial_period_days"] = assignment.trial_days

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=user["email"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=False,
            client_reference_id=user_id,
            metadata=metadata,
            subscription_data=subscription_data,
        )
    except Exception as exc:
        logger.exception("Stripe Checkout Session creation failed for user %s", user_id)
        return jsonify({"error": "Checkout could not be created"}), 502

    session_id = str(_obj_value(session, "id", ""))
    checkout_url = _obj_value(session, "url")
    if not session_id or not checkout_url:
        logger.error("Stripe returned an incomplete checkout session for user %s", user_id)
        return jsonify({"error": "Checkout could not be created"}), 502

    get_billing_store().upsert(
        user_id=user_id,
        checkout_session_id=session_id,
        status="checkout_created",
        offer_code=assignment.offer_code,
    )

    return jsonify(
        {
            "checkout_url": checkout_url,
            "checkout_session_id": session_id,
            "commercial_offer": assignment.to_dict(),
        }
    )


@stripe_billing_api.get("/api/billing/status")
def billing_status():
    user_id = getattr(request, "user_id", None)
    if not isinstance(user_id, str) or not user_id:
        return jsonify({"error": "Authentication required"}), 401
    record = get_billing_store().get(user_id)
    if record is None:
        return jsonify({"status": "not_started"})
    return jsonify(record.to_dict())


@stripe_billing_api.post("/api/billing/webhook")
def stripe_webhook():
    """Verify Stripe signature and persist authoritative subscription status."""
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        logger.error("Stripe webhook received before webhook secret was configured")
        return jsonify({"error": "Webhook is not configured"}), 503

    try:
        stripe = _stripe_module()
    except RuntimeError:
        return jsonify({"error": "Webhook is not configured"}), 503

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(request.get_data(), signature, secret)
    except Exception:
        logger.warning("Rejected Stripe webhook with invalid payload or signature")
        return jsonify({"error": "Invalid webhook"}), 400

    event_type = _obj_value(event, "type", "")
    data = _obj_value(event, "data", {})
    obj = _obj_value(data, "object", {})

    if event_type == "checkout.session.completed":
        metadata = _obj_value(obj, "metadata", {}) or {}
        user_id = _obj_value(metadata, "nija_user_id")
        offer_code = _obj_value(metadata, "nija_offer_code")
        if user_id:
            get_billing_store().upsert(
                user_id=str(user_id),
                customer_id=_string_or_none(_obj_value(obj, "customer")),
                subscription_id=_string_or_none(_obj_value(obj, "subscription")),
                checkout_session_id=_string_or_none(_obj_value(obj, "id")),
                status="checkout_completed",
                offer_code=_string_or_none(offer_code),
            )

    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        subscription_id = _string_or_none(_obj_value(obj, "id"))
        metadata = _obj_value(obj, "metadata", {}) or {}
        user_id = _obj_value(metadata, "nija_user_id")
        if not user_id and subscription_id:
            user_id = get_billing_store().find_user_by_subscription(subscription_id)
        if user_id:
            get_billing_store().upsert(
                user_id=str(user_id),
                customer_id=_string_or_none(_obj_value(obj, "customer")),
                subscription_id=subscription_id,
                status=str(_obj_value(obj, "status", "unknown")),
                offer_code=_string_or_none(_obj_value(metadata, "nija_offer_code")),
                current_period_end=_int_or_none(_obj_value(obj, "current_period_end")),
            )

    return jsonify({"received": True})


def _string_or_none(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
