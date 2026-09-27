"""Standalone NIJA HTTPS billing API.

This process intentionally imports no trading runtime modules.  Stripe is the
authority for web subscription state; billing state is persisted in a durable
SQL store and exposed to the NIJA success page only as a minimal verification
record.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

import jwt
from flask import Flask, current_app, jsonify, request
from flask_cors import CORS

from billing_service_store import BillingIdentityMismatch, BillingServiceStore
from pricing_policy import BETA_TRIAL_DAYS, FOUNDING_BETA_OFFER, STANDARD_BETA_OFFER

logger = logging.getLogger("nija.billing.service")

_BILLING_CONTRACT = "nija_web_subscription_v1"
_ENTITLED_SUBSCRIPTION_STATES = {"active", "trialing"}
_REVOKED_SUBSCRIPTION_STATES = {
    "canceled",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "paused",
    "unpaid",
}
_CHECKOUT_PAID_STATES = {"paid", "no_payment_required"}


@dataclass(frozen=True)
class BillingIdentity:
    """Server-signed NIJA identity accepted for Checkout creation."""

    user_id: str
    email: str
    offer_code: str


@dataclass(frozen=True)
class OfferConfig:
    """Expected Stripe resources for an immutable NIJA commercial offer."""

    offer_code: str
    price_id: str
    product_id: str
    trial_days: int


class BillingContractViolation(ValueError):
    """Raised when Stripe state does not match the NIJA billing contract."""


def _obj_value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _id_value(obj: Any) -> Optional[str]:
    if obj in (None, ""):
        return None
    if isinstance(obj, str):
        return obj
    value = _obj_value(obj, "id")
    return str(value) if value else None


def _string_or_none(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


def _int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalized_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _stripe_module():
    import stripe

    secret = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    stripe.api_key = secret
    return stripe


def _offer_config(offer_code: str) -> OfferConfig:
    env_map = {
        FOUNDING_BETA_OFFER: (
            "STRIPE_PRICE_FOUNDING_BETA",
            "STRIPE_PRODUCT_FOUNDING_BETA",
            BETA_TRIAL_DAYS,
        ),
        STANDARD_BETA_OFFER: (
            "STRIPE_PRICE_STANDARD_BETA",
            "STRIPE_PRODUCT_STANDARD_BETA",
            0,
        ),
    }
    mapping = env_map.get(offer_code)
    if mapping is None:
        raise BillingContractViolation("offer_not_supported_for_web_subscription")
    price_env, product_env, trial_days = mapping
    price_id = os.getenv(price_env, "").strip()
    product_id = os.getenv(product_env, "").strip()
    if not price_id or not product_id:
        raise RuntimeError(f"Stripe Price/Product mapping is incomplete for {offer_code}")
    return OfferConfig(
        offer_code=offer_code,
        price_id=price_id,
        product_id=product_id,
        trial_days=trial_days,
    )


def _store() -> BillingServiceStore:
    return current_app.config["BILLING_STORE"]


def _site_url() -> str:
    return os.getenv("NIJA_PUBLIC_SITE_URL", "https://nijaaitrading.com").rstrip("/")


def _identity_from_request() -> BillingIdentity:
    """Verify the server-issued billing identity assertion.

    The assertion must be minted by NIJA server-side code.  Browser-controlled
    user IDs, emails, prices, and offer codes are never accepted as authority.
    """
    secret = os.getenv("NIJA_BILLING_IDENTITY_SECRET", "").strip()
    if not secret:
        raise RuntimeError("NIJA_BILLING_IDENTITY_SECRET is not configured")

    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise BillingContractViolation("billing_identity_required")

    try:
        payload = jwt.decode(
            parts[1],
            secret,
            algorithms=["HS256"],
            audience="nija-billing",
            issuer="nija-identity",
            options={"require": ["exp", "iat", "sub", "email", "offer_code"]},
        )
    except jwt.PyJWTError as exc:
        raise BillingContractViolation("billing_identity_invalid") from exc

    user_id = str(payload.get("sub") or "").strip()
    email = _normalized_email(payload.get("email"))
    offer_code = str(payload.get("offer_code") or "").strip()
    if not user_id or not email or not offer_code:
        raise BillingContractViolation("billing_identity_incomplete")
    return BillingIdentity(user_id=user_id, email=email, offer_code=offer_code)


def _line_items_data(container: Any) -> list[Any]:
    items = _obj_value(container, "items")
    if items is not None:
        data = _obj_value(items, "data", [])
        return list(data or [])
    line_items = _obj_value(container, "line_items")
    data = _obj_value(line_items, "data", [])
    return list(data or [])


def _validate_single_expected_item(
    container: Any,
    *,
    expected_price_id: str,
    expected_product_id: str,
) -> None:
    items = _line_items_data(container)
    if len(items) != 1:
        raise BillingContractViolation("stripe_line_item_count_mismatch")
    item = items[0]
    quantity = _int_or_none(_obj_value(item, "quantity"))
    price = _obj_value(item, "price", {})
    price_id = _id_value(price)
    product_id = _id_value(_obj_value(price, "product"))
    if quantity != 1:
        raise BillingContractViolation("stripe_quantity_mismatch")
    if price_id != expected_price_id:
        raise BillingContractViolation("stripe_price_mismatch")
    if product_id != expected_product_id:
        raise BillingContractViolation("stripe_product_mismatch")


def _retrieve_customer_email(stripe: Any, customer_id: str) -> str:
    customer = stripe.Customer.retrieve(customer_id)
    if bool(_obj_value(customer, "deleted", False)):
        raise BillingContractViolation("stripe_customer_deleted")
    email = _normalized_email(_obj_value(customer, "email"))
    if not email:
        raise BillingContractViolation("stripe_customer_email_missing")
    return email


def _validate_customer_identity(
    stripe: Any,
    *,
    customer_id: str,
    expected_email: str,
) -> None:
    actual_email = _retrieve_customer_email(stripe, customer_id)
    if actual_email != _normalized_email(expected_email):
        raise BillingContractViolation("stripe_customer_identity_mismatch")


def _validate_checkout_session(
    stripe: Any,
    session: Any,
    record: dict[str, Any],
) -> tuple[str, str, str]:
    session_id = _string_or_none(_obj_value(session, "id"))
    if session_id != record["checkout_session_id"]:
        raise BillingContractViolation("checkout_session_id_mismatch")
    if str(_obj_value(session, "mode", "")) != "subscription":
        raise BillingContractViolation("checkout_mode_mismatch")
    if str(_obj_value(session, "client_reference_id", "")) != record["nija_user_id"]:
        raise BillingContractViolation("checkout_client_reference_mismatch")

    metadata = _obj_value(session, "metadata", {}) or {}
    if str(_obj_value(metadata, "nija_billing_contract", "")) != _BILLING_CONTRACT:
        raise BillingContractViolation("checkout_contract_marker_missing")
    if str(_obj_value(metadata, "nija_user_id", "")) != record["nija_user_id"]:
        raise BillingContractViolation("checkout_metadata_user_mismatch")
    if str(_obj_value(metadata, "nija_offer_code", "")) != record["offer_code"]:
        raise BillingContractViolation("checkout_metadata_offer_mismatch")

    _validate_single_expected_item(
        session,
        expected_price_id=record["expected_price_id"],
        expected_product_id=record["expected_product_id"],
    )

    customer_id = _id_value(_obj_value(session, "customer"))
    subscription_id = _id_value(_obj_value(session, "subscription"))
    if not customer_id or not subscription_id:
        raise BillingContractViolation("checkout_customer_or_subscription_missing")

    customer_details = _obj_value(session, "customer_details", {}) or {}
    checkout_email = _normalized_email(_obj_value(customer_details, "email"))
    if checkout_email and checkout_email != _normalized_email(record["email"]):
        raise BillingContractViolation("checkout_customer_details_mismatch")
    _validate_customer_identity(
        stripe,
        customer_id=customer_id,
        expected_email=record["email"],
    )

    return customer_id, subscription_id, str(_obj_value(session, "payment_status", "unpaid"))


def _subscription_period_end(subscription: Any) -> Optional[int]:
    direct = _int_or_none(_obj_value(subscription, "current_period_end"))
    if direct is not None:
        return direct
    items = _line_items_data(subscription)
    if not items:
        return None
    return _int_or_none(_obj_value(items[0], "current_period_end"))


def _resolve_subscription_user(subscription: Any) -> Optional[str]:
    metadata = _obj_value(subscription, "metadata", {}) or {}
    user_id = _string_or_none(_obj_value(metadata, "nija_user_id"))
    if user_id:
        return user_id
    subscription_id = _id_value(subscription)
    if subscription_id:
        return _store().find_user_by_subscription(subscription_id)
    customer_id = _id_value(_obj_value(subscription, "customer"))
    if customer_id:
        return _store().find_user_by_customer(customer_id)
    return None


def _apply_subscription_object(stripe: Any, subscription: Any, event_created: int) -> None:
    user_id = _resolve_subscription_user(subscription)
    if not user_id:
        return
    record = _store().get_customer(user_id)
    if not record:
        return

    subscription_id = _id_value(subscription)
    customer_id = _id_value(_obj_value(subscription, "customer"))
    metadata = _obj_value(subscription, "metadata", {}) or {}
    offer_code = _string_or_none(_obj_value(metadata, "nija_offer_code"))
    status = str(_obj_value(subscription, "status", "unknown"))

    try:
        if not subscription_id or not customer_id:
            raise BillingContractViolation("subscription_identity_missing")
        if str(_obj_value(metadata, "nija_billing_contract", "")) != _BILLING_CONTRACT:
            raise BillingContractViolation("subscription_contract_marker_missing")
        if str(_obj_value(metadata, "nija_user_id", "")) != user_id:
            raise BillingContractViolation("subscription_user_mismatch")
        if offer_code != record["offer_code"]:
            raise BillingContractViolation("subscription_offer_mismatch")
        if record.get("stripe_customer_id") and record["stripe_customer_id"] != customer_id:
            raise BillingContractViolation("subscription_customer_mismatch")
        if record.get("stripe_subscription_id") and record["stripe_subscription_id"] != subscription_id:
            raise BillingContractViolation("subscription_id_mismatch")
        _validate_single_expected_item(
            subscription,
            expected_price_id=record["expected_price_id"],
            expected_product_id=record["expected_product_id"],
        )
        _validate_customer_identity(
            stripe,
            customer_id=customer_id,
            expected_email=record["email"],
        )
        entitled = status in _ENTITLED_SUBSCRIPTION_STATES
        reason = "authoritative_subscription_state" if entitled else f"subscription_{status}"
    except BillingContractViolation as exc:
        status = "mismatch"
        entitled = False
        reason = str(exc)

    _store().apply_subscription_state(
        user_id=user_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        status=status,
        offer_code=offer_code,
        current_period_end=_subscription_period_end(subscription),
        entitled=entitled,
        reason=reason,
        event_created=event_created,
    )


def _process_checkout_event(stripe: Any, event_type: str, event_obj: Any) -> None:
    session_id = _id_value(event_obj)
    if not session_id:
        return
    record = _store().get_checkout(session_id)
    if not record:
        # Generic Payment Links, including the $99 course, are intentionally
        # unable to create NIJA membership entitlement.
        return

    if event_type in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
        _store().set_checkout_status(
            session_id,
            verification_status="payment_failed" if "failed" in event_type else "expired",
            reason=event_type,
            payment_status=str(_obj_value(event_obj, "payment_status", "unpaid")),
            verified=False,
            revoke_customer=True,
        )
        return

    session = stripe.checkout.Session.retrieve(
        session_id,
        expand=["line_items"],
    )
    try:
        customer_id, subscription_id, payment_status = _validate_checkout_session(
            stripe,
            session,
            record,
        )
    except BillingContractViolation as exc:
        _store().mark_checkout_mismatch(session_id, str(exc))
        return

    if payment_status not in _CHECKOUT_PAID_STATES:
        _store().set_checkout_status(
            session_id,
            verification_status="pending_payment",
            reason="stripe_checkout_not_paid",
            payment_status=payment_status,
            verified=False,
            revoke_customer=False,
        )
        return

    _store().mark_checkout_verified(
        session_id=session_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        payment_status=payment_status,
    )


def _process_invoice_failure(event_obj: Any, event_created: int) -> None:
    subscription_id = _id_value(_obj_value(event_obj, "subscription"))
    customer_id = _id_value(_obj_value(event_obj, "customer"))
    user_id = (
        _store().find_user_by_subscription(subscription_id or "")
        or _store().find_user_by_customer(customer_id or "")
    )
    if not user_id:
        return
    record = _store().get_customer(user_id)
    if not record:
        return
    _store().apply_subscription_state(
        user_id=user_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        status="payment_failed",
        offer_code=record["offer_code"],
        current_period_end=record.get("current_period_end"),
        entitled=False,
        reason="invoice_payment_failed",
        event_created=event_created,
    )


def _process_invoice_paid(stripe: Any, event_obj: Any, event_created: int) -> None:
    subscription_id = _id_value(_obj_value(event_obj, "subscription"))
    if not subscription_id:
        return
    subscription = stripe.Subscription.retrieve(
        subscription_id,
        expand=["items"],
    )
    _apply_subscription_object(stripe, subscription, event_created)


def _process_event(stripe: Any, event_type: str, event_obj: Any, event_created: int) -> None:
    if event_type in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "checkout.session.expired",
    }:
        _process_checkout_event(stripe, event_type, event_obj)
        return

    if event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        _apply_subscription_object(stripe, event_obj, event_created)
        return

    if event_type == "invoice.payment_failed":
        _process_invoice_failure(event_obj, event_created)
        return

    if event_type == "invoice.paid":
        _process_invoice_paid(stripe, event_obj, event_created)


def create_app(store: Optional[BillingServiceStore] = None) -> Flask:
    """Create the standalone billing-only Flask application."""
    app = Flask(__name__)
    app.config["BILLING_STORE"] = store or BillingServiceStore(
        os.getenv("BILLING_DATABASE_URL", "").strip()
    )

    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "NIJA_BILLING_ALLOWED_ORIGINS",
            "https://nijaaitrading.com,https://www.nijaaitrading.com",
        ).split(",")
        if origin.strip()
    ]
    CORS(
        app,
        resources={
            r"/api/billing/verify": {"origins": allowed_origins, "methods": ["GET"]},
            r"/api/billing/checkout": {"origins": allowed_origins, "methods": ["POST"]},
        },
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/healthz")
    def healthz():
        try:
            _store().ping()
        except Exception:
            logger.exception("Billing database health check failed")
            return jsonify({"service": "nija-billing", "status": "unhealthy"}), 503
        return jsonify({"service": "nija-billing", "status": "ok"})

    @app.post("/api/billing/checkout")
    def create_checkout():
        try:
            identity = _identity_from_request()
            offer = _offer_config(identity.offer_code)
            stripe = _stripe_module()
        except BillingContractViolation as exc:
            return jsonify({"error": str(exc)}), 401
        except RuntimeError:
            logger.exception("Billing checkout configuration is incomplete")
            return jsonify({"error": "billing_temporarily_unavailable"}), 503

        existing = _store().get_customer(identity.user_id)
        if existing:
            if _normalized_email(existing["email"]) != identity.email:
                return jsonify({"error": "billing_identity_mismatch"}), 409
            if existing["offer_code"] != identity.offer_code:
                return jsonify({"error": "billing_offer_mismatch"}), 409
            if str(existing["status"]).lower() in {"active", "trialing", "past_due"}:
                return jsonify({"error": "subscription_already_exists"}), 409

        customer_identity: dict[str, str]
        if existing and existing.get("stripe_customer_id"):
            try:
                _validate_customer_identity(
                    stripe,
                    customer_id=existing["stripe_customer_id"],
                    expected_email=identity.email,
                )
            except BillingContractViolation:
                return jsonify({"error": "stripe_customer_identity_mismatch"}), 409
            customer_identity = {"customer": existing["stripe_customer_id"]}
        else:
            customer_identity = {"customer_email": identity.email}

        metadata = {
            "nija_billing_contract": _BILLING_CONTRACT,
            "nija_user_id": identity.user_id,
            "nija_offer_code": identity.offer_code,
        }
        subscription_data: dict[str, Any] = {"metadata": metadata}
        if offer.trial_days > 0:
            subscription_data["trial_period_days"] = offer.trial_days

        success_url = os.getenv(
            "STRIPE_CHECKOUT_SUCCESS_URL",
            f"{_site_url()}/beta-success?session_id={{CHECKOUT_SESSION_ID}}",
        )
        cancel_url = os.getenv(
            "STRIPE_CHECKOUT_CANCEL_URL",
            f"{_site_url()}/apply",
        )

        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                **customer_identity,
                line_items=[{"price": offer.price_id, "quantity": 1}],
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=identity.user_id,
                metadata=metadata,
                subscription_data=subscription_data,
                allow_promotion_codes=False,
                payment_method_collection="always",
            )
        except Exception:
            logger.exception("Stripe Checkout Session creation failed")
            return jsonify({"error": "checkout_creation_failed"}), 502

        session_id = _id_value(session)
        checkout_url = _string_or_none(_obj_value(session, "url"))
        customer_id = _id_value(_obj_value(session, "customer"))
        if not session_id or not checkout_url:
            return jsonify({"error": "stripe_checkout_response_incomplete"}), 502

        try:
            _store().create_checkout(
                user_id=identity.user_id,
                email=identity.email,
                offer_code=identity.offer_code,
                expected_price_id=offer.price_id,
                expected_product_id=offer.product_id,
                session_id=session_id,
                customer_id=customer_id,
            )
        except BillingIdentityMismatch:
            logger.exception("Could not persist Checkout Session identity")
            try:
                stripe.checkout.Session.expire(session_id)
            except Exception:
                logger.exception("Could not expire untracked Stripe Checkout Session")
            return jsonify({"error": "checkout_identity_conflict"}), 409
        except Exception:
            logger.exception("Could not persist Checkout Session")
            try:
                stripe.checkout.Session.expire(session_id)
            except Exception:
                logger.exception("Could not expire untracked Stripe Checkout Session")
            return jsonify({"error": "checkout_persistence_failed"}), 503

        return jsonify(
            {
                "checkout_url": checkout_url,
                "checkout_session_id": session_id,
                "entitlement_granted": False,
            }
        )

    @app.get("/api/billing/verify")
    def verify_checkout():
        session_id = str(request.args.get("session_id") or "").strip()
        if not session_id:
            return jsonify({"error": "session_id_required"}), 400
        record = _store().verification_record(session_id)
        if record is None:
            return jsonify(
                {
                    "checkout_session_id": session_id,
                    "state": "pending",
                    "verified": False,
                    "entitled": False,
                }
            ), 404
        response = jsonify(record)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.post("/api/billing/webhook")
    def stripe_webhook():
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        if not webhook_secret:
            logger.error("Stripe webhook called before STRIPE_WEBHOOK_SECRET was configured")
            return jsonify({"error": "webhook_not_configured"}), 503

        signature = request.headers.get("Stripe-Signature", "").strip()
        if not signature:
            return jsonify({"error": "stripe_signature_required"}), 400

        try:
            stripe = _stripe_module()
            raw_payload = request.get_data(cache=False, as_text=False)
            event = stripe.Webhook.construct_event(raw_payload, signature, webhook_secret)
        except Exception:
            logger.warning("Rejected Stripe webhook with missing/invalid signature or payload")
            return jsonify({"error": "invalid_webhook"}), 400

        event_id = _string_or_none(_obj_value(event, "id"))
        event_type = str(_obj_value(event, "type", ""))
        event_created = _int_or_none(_obj_value(event, "created")) or 0
        if not event_id or not event_type:
            return jsonify({"error": "invalid_stripe_event"}), 400

        if not _store().claim_event(event_id, event_type):
            return jsonify({"received": True, "duplicate": True})

        data = _obj_value(event, "data", {}) or {}
        event_obj = _obj_value(data, "object", {}) or {}
        try:
            _process_event(stripe, event_type, event_obj, event_created)
            _store().finish_event(event_id)
        except Exception:
            _store().release_event(event_id)
            logger.exception("Stripe event processing failed: %s", event_type)
            return jsonify({"error": "webhook_processing_failed"}), 500

        return jsonify({"received": True})

    return app


def _default_app() -> Flask:
    """Expose a Gunicorn app while failing closed when deployment is incomplete."""
    database_url = os.getenv("BILLING_DATABASE_URL", "").strip()
    if database_url:
        return create_app()

    misconfigured = Flask(__name__)

    @misconfigured.get("/healthz")
    def unavailable_healthz():
        return jsonify({"service": "nija-billing", "status": "misconfigured"}), 503

    @misconfigured.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    @misconfigured.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def unavailable(path: str):
        return jsonify({"error": "billing_service_not_configured"}), 503

    return misconfigured


app = _default_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
