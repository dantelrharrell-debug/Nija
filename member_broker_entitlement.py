"""Read-only, fail-closed verification of Founding 100 billing entitlement.

This service is deliberately separate from NIJA's trading engine. A customer
may save broker keys only when the authoritative billing ledger and Stripe's
current LIVE subscription both agree on the same owner and original offer.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _resource_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    return str(_field(value, "id", "") or "")


def check_founding_entitlement(
    member_id: str, *, settings: Mapping[str, str] | None = None,
    ledger_row: Mapping[str, Any] | None = None,
    stripe_subscription: Any = None, now: int | None = None,
) -> bool:
    """Return False on missing, stale, mismatched, sandbox, or revoked state.

    Caller-supplied ledger_row/stripe_subscription are exclusively for unit
    tests. Production callers load both independently from trusted servers.
    """
    config = settings if settings is not None else os.environ
    price_id = str(config.get("NIJA_VAULT_FOUNDING_PRICE_ID", "")).strip()
    product_id = str(config.get("NIJA_VAULT_FOUNDING_PRODUCT_ID", "")).strip()
    if not isinstance(member_id, str) or not member_id or not price_id or not product_id:
        return False
    if ledger_row is None or stripe_subscription is None:
        return False
    row = ledger_row
    sub = stripe_subscription
    try:
        if str(row["nija_user_id"]) != member_id:
            return False
        if row["offer_code"] != "founding_beta" or row["status"] not in ("active", "trialing"):
            return False
        if row["entitled"] not in (True, 1):
            return False
        if row["expected_price_id"] != price_id or row["expected_product_id"] != product_id:
            return False
        if not row.get("stripe_subscription_id") or not row.get("stripe_customer_id"):
            return False
        clock = int(time.time()) if now is None else int(now)
        if int(row.get("current_period_end") or 0) <= clock:
            return False
        if _field(sub, "livemode") is not True:
            return False
        if _field(sub, "status") not in ("active", "trialing"):
            return False
        if _resource_id(sub) != row["stripe_subscription_id"]:
            return False
        if _resource_id(_field(sub, "customer")) != row["stripe_customer_id"]:
            return False
        items = _field(_field(sub, "items", {}), "data", [])
        if not isinstance(items, (list, tuple)) or len(items) != 1:
            return False
        item = items[0]
        period_end = _field(sub, "current_period_end")
        if period_end is None:
            period_end = _field(item, "current_period_end")
        if int(period_end or 0) <= clock:
            return False
        metadata = _field(sub, "metadata", {})
        if (_field(metadata, "nija_user_id") != member_id
                or _field(metadata, "nija_offer_code") != "founding_beta"):
            return False
        if int(_field(item, "quantity", 0) or 0) != 1:
            return False
        price = _field(item, "price", {})
        if _resource_id(price) != price_id:
            return False
        if _resource_id(_field(price, "product")) != product_id:
            return False
        return True
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def trusted_founding_entitlement(member_id: str) -> bool:
    """Read-only Stripe + SQL check; no membership writes or new subscriptions."""
    database_url = os.environ.get("NIJA_VAULT_BILLING_READONLY_URL", "").strip()
    stripe_key = os.environ.get("NIJA_VAULT_STRIPE_READONLY_KEY", "").strip()
    if not member_id or not database_url or not stripe_key:
        return False
    try:
        import stripe
        from sqlalchemy import create_engine, text
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                row = connection.execute(
                    text("""SELECT nija_user_id, offer_code, status, entitled,
                                 expected_price_id, expected_product_id,
                                 stripe_subscription_id, stripe_customer_id,
                                 current_period_end
                          FROM billing_customers WHERE nija_user_id=:uid"""),
                    {"uid": member_id},
                ).mappings().first()
        finally:
            engine.dispose()
        if row is None or not row.get("stripe_subscription_id"):
            return False
        # Read-only account credential, not the billing service's write key.
        sub = stripe.Subscription.retrieve(
            str(row["stripe_subscription_id"]), api_key=stripe_key
        )
        return check_founding_entitlement(
            member_id, ledger_row=dict(row), stripe_subscription=sub
        )
    except Exception:
        # Missing billing history, API timeout, mismatch and provider outage
        # must never be converted into entitlement approval.
        return False
