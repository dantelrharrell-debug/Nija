"""Fail-closed, read-only NIJA Founding 100 identity/billing reconciliation.

Run only inside the trusted billing environment. It never writes account data,
starts Checkout, resumes billing, enables broker intake, or authorizes trading.
Its result is NOT a substitute for authenticated dashboard and vault acceptance.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any

from sqlalchemy import create_engine, text


FIELDS = (
    "application_binding_verified",
    "registration_approved",
    "registered_account",
    "canonical_email_matches_billing",
    "authoritative_entitlement_current",
    "stripe_customer_identity_verified",
    "stripe_subscription_consistent",
    "single_subscription_confirmed",
    "legacy_checkout_identity_reconciled",
)


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalized(email: Any) -> str:
    return str(email or "").strip().lower()


def _read_onboarding(path: str, member_id: str) -> dict[str, Any] | None:
    # Never instantiate InvitationOutbox; its constructor creates/updates tables.
    if not path or not Path(path).is_absolute() or not Path(path).is_file():
        return None
    uri = Path(path).as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT application_id,member_id,recipient,approved,registered "
            "FROM onboarding_members WHERE member_id=? LIMIT 2", (member_id,)
        ).fetchall()
    if len(rows) != 1:
        return None
    a, u, email, approved, registered = rows[0]
    return dict(application_id=a, member_id=u, email=email,
                approved=bool(approved), registered=bool(registered))


def _read_billing(url: str, member_id: str) -> dict[str, Any] | None:
    # Never instantiate BillingServiceStore; its constructor invokes create_all.
    # Set transaction read-only BEFORE selecting, including on SQLite test DBs.
    if not url:
        return None
    engine = create_engine(url, future=True, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            if engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            elif engine.dialect.name == "sqlite":
                conn.exec_driver_sql("PRAGMA query_only=ON")
            else:
                # Unknown SQL dialect cannot be certified read-only.
                return None
            rows = conn.execute(text(
                "SELECT nija_user_id,email,offer_code,expected_price_id,expected_product_id,"
                "stripe_customer_id,stripe_subscription_id,status,entitled,current_period_end "
                "FROM billing_customers WHERE nija_user_id=:member_id LIMIT 2"
            ), {"member_id": member_id}).mappings().all()
        return dict(rows[0]) if len(rows) == 1 else None
    finally:
        engine.dispose()


def _fetch_stripe(secret: str, *, stripe_api: Any = None):
    if stripe_api is None:
        import stripe as stripe_api  # Import only in trusted backend runtime.
    if not secret:
        raise RuntimeError("stripe_key_not_available")
    stripe_api.api_key = secret
    return stripe_api


def audit(member_id: str, application_id: str, *, billing_url: str,
          onboarding_db_path: str, stripe_key: str,
          stripe_api: Any = None, now: int | None = None) -> dict[str, Any]:
    """Only boolean evidence; no PII, keys, customer IDs or exceptions in output."""
    result: dict[str, Any] = {name: False for name in FIELDS}
    result.update(
        authoritative_member_verified=False,
        authenticated_dashboard_verified=False,
        secure_broker_onboarding_verified=False,
        full_onboarding_certified=False,
        conclusion="blocked",
        blocking_sources=[],
    )
    if (not member_id or not application_id or len(member_id) > 128
            or len(application_id) > 128):
        return result
    try:
        registered = _read_onboarding(onboarding_db_path, member_id)
        billing = _read_billing(billing_url, member_id)
        if not registered:
            result["blocking_sources"].append("onboarding_identity_record_missing_or_unavailable")
        if not billing:
            result["blocking_sources"].append("billing_ledger_record_missing_or_unavailable")
        if not registered or not billing:
            return result
        result["application_binding_verified"] = (
            registered["member_id"] == member_id
            and registered["application_id"] == application_id
            and billing["nija_user_id"] == member_id
        )
        result["registration_approved"] = registered["approved"]
        result["registered_account"] = registered["registered"]
        canonical_email = _normalized(registered["email"])
        result["canonical_email_matches_billing"] = (
            bool(canonical_email) and "@" in canonical_email
            and canonical_email == _normalized(billing["email"])
        )
        now_ts = int(time.time()) if now is None else now
        result["authoritative_entitlement_current"] = (
            billing["offer_code"] == "founding_beta"
            and billing["status"] in ("trialing", "active")
            and billing["entitled"] in (True, 1)
            and isinstance(billing["current_period_end"], int)
            and billing["current_period_end"] > now_ts
        )
        customer_id = billing["stripe_customer_id"]
        subscription_id = billing["stripe_subscription_id"]
        if not customer_id or not subscription_id:
            result["blocking_sources"].append("missing_authoritative_stripe_binding")
            return result
        stripe = _fetch_stripe(stripe_key, stripe_api=stripe_api)
        customer = stripe.Customer.retrieve(customer_id)
        subscription = stripe.Subscription.retrieve(subscription_id)
        customer_metadata = _value(customer, "metadata", {}) or {}
        sub_metadata = _value(subscription, "metadata", {}) or {}
        result["stripe_customer_identity_verified"] = (
            _value(customer, "livemode") is True
            and _value(customer, "id") == customer_id
            and _normalized(_value(customer, "email")) == canonical_email
            and _normalized(_value(customer_metadata, "nija_verified_email")) == canonical_email
            and _value(customer_metadata, "nija_application_id") == application_id
            and bool(_value(customer_metadata, "nija_verification_source"))
        )
        items = list(_value(_value(subscription, "items", {}), "data", []) or [])
        item = items[0] if len(items) == 1 else {}
        price = _value(item, "price", {})
        stripe_status = _value(subscription, "status")
        result["stripe_subscription_consistent"] = (
            _value(subscription, "livemode") is True
            and _value(subscription, "id") == subscription_id
            and _value(subscription, "customer") == customer_id
            and stripe_status == billing["status"]
            and stripe_status in ("trialing", "active")
            and _value(item, "current_period_end") == billing["current_period_end"]
            and (stripe_status != "trialing" or
                 _value(_value(subscription, "pause_collection", {}), "behavior") == "void")
            and _value(sub_metadata, "nija_user_id") == member_id
            and _value(sub_metadata, "nija_application_id") == application_id
            and _value(sub_metadata, "nija_offer_code") == "founding_beta"
            and _value(price, "id") == billing["expected_price_id"]
            and _value(price, "product") == billing["expected_product_id"]
            and _value(item, "quantity", 1) == 1
        )
        listed = stripe.Subscription.list(customer=customer_id, status="all", limit=100)
        subscriptions = list(_value(listed, "data", []) or [])
        result["single_subscription_confirmed"] = (
            not bool(_value(listed, "has_more")) and len(subscriptions) == 1
            and _value(subscriptions[0], "id") == subscription_id
        )
        # A generic Payment Link checkout can have no NIJA reference. In that
        # legacy case require the independently signed approved/registered
        # application and matching operator-verified Stripe identity chain.
        checkouts = stripe.checkout.Session.list(subscription=subscription_id, limit=100)
        sessions = list(_value(checkouts, "data", []) or [])
        if not _value(checkouts, "has_more") and len(sessions) == 1:
            session = sessions[0]
            session_metadata = _value(session, "metadata", {}) or {}
            checkout_has_owner = (
                _value(session, "client_reference_id") == application_id
                or (_value(session_metadata, "nija_application_id") == application_id
                    and _value(session_metadata, "nija_user_id") == member_id)
            )
            result["legacy_checkout_identity_reconciled"] = (
                _value(session, "livemode") is True
                and _value(session, "subscription") == subscription_id
                and _value(session, "customer") == customer_id
                and _value(session, "status") == "complete"
                and (checkout_has_owner or (
                    result["application_binding_verified"]
                    and result["registration_approved"]
                    and result["registered_account"]
                    and result["canonical_email_matches_billing"]
                    and result["stripe_customer_identity_verified"]
                    and _value(sub_metadata, "nija_link_method") == "operator_verified_existing_trial"
                ))
            )
        result["authoritative_member_verified"] = all(result[name] for name in FIELDS)
        result["conclusion"] = (
            "membership_verified_but_dashboard_and_broker_unchecked"
            if result["authoritative_member_verified"] else "blocked"
        )
    except Exception:
        # No exception type, URL, provider reply or secret in stdout/logs.
        result["blocking_sources"].append("verification_source_error")
        return result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Founding 100 membership check")
    parser.add_argument("--user-id", required=True, help="Trusted immutable NIJA user ID")
    parser.add_argument("--application-id", required=True, help="Trusted immutable NIJA application ID")
    args = parser.parse_args()
    report = audit(args.user_id, args.application_id,
                   billing_url=os.getenv("BILLING_DATABASE_URL", ""),
                   onboarding_db_path=os.getenv("NIJA_ONBOARDING_DB_PATH", ""),
                   stripe_key=os.getenv("STRIPE_SECRET_KEY", ""))
    # Print only one of two fixed string constants. Do not serialize source-derived
    # reports or tokens into stdout, shell transcripts, or CI logs.
    if report["authoritative_member_verified"] is True:
        print('{"authoritative_member_verified":true,"full_onboarding_certified":false}')
    else:
        print('{"authoritative_member_verified":false,"full_onboarding_certified":false}')
    # Zero only means membership verified, NOT onboarding/trading ready.
    return 0 if report["authoritative_member_verified"] else 2


if __name__ == "__main__":
    sys.exit(main())
