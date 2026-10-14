"""Fail-closed preflight for reconciling legacy Stripe memberships.

This helper is NOT an entitlement issuer or proof of ownership. A passing
result still requires audited, authenticated administrative authorization.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyBindingPreflight:
    verified: bool
    reasons: tuple[str, ...]


def check_legacy_binding(*, user_id: str, verified_email: str,
                         application_email: str, authenticated_email: str,
                         application_user_id: str, stripe_customer_id: str,
                         subscription_id: str, subscription_customer_id: str,
                         subscription_status: str, expected_price_id: str,
                         actual_price_id: str, existing_subscription_owner: str | None,
                         existing_customer_owner: str | None,
                         identity_proof_complete: bool,
                         application_ownership_verified: bool) -> LegacyBindingPreflight:
    """Compare independent verified identities, never trusting names alone."""
    reasons = []
    if not user_id or user_id != application_user_id:
        reasons.append("application_user_identity")
    normalized = tuple(str(value or "").strip().lower() for value in
                       (verified_email, application_email, authenticated_email))
    if any(not value or "@" not in value for value in normalized) or len(set(normalized)) != 1:
        reasons.append("verified_email_mismatch")
    if not identity_proof_complete or not application_ownership_verified:
        reasons.append("identity_ownership_unverified")
    if not stripe_customer_id or stripe_customer_id != subscription_customer_id:
        reasons.append("stripe_customer_mismatch")
    if not subscription_id or not subscription_id.startswith("sub_"):
        reasons.append("subscription_not_verified")
    if subscription_status not in {"trialing", "active"}:
        reasons.append("subscription_not_entitled")
    if not expected_price_id or actual_price_id != expected_price_id:
        reasons.append("price_mismatch")
    if existing_subscription_owner and existing_subscription_owner != user_id:
        reasons.append("subscription_already_bound")
    if existing_customer_owner and existing_customer_owner != user_id:
        reasons.append("customer_already_bound")
    return LegacyBindingPreflight(not reasons, tuple(reasons))
