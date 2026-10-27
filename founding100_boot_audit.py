"""Opt-in, read-only Founding 100 certification inside the trusted billing runtime.

This is a diagnostic, not an entitlement grant, member notification or broker
onboarding approval. It never logs identifiers, email addresses or secrets.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, Callable

_LOG = logging.getLogger("nija.billing.founding100_boot_audit")
_FLAG_NAMES = (
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
_SOURCE_CODES = frozenset({
    "onboarding_identity_record_missing_or_unavailable",
    "billing_ledger_record_missing_or_unavailable",
    "missing_authoritative_stripe_binding",
    "verification_source_error",
})


def run_opt_in_audit(*, environ: Mapping[str, str] | None = None,
                     auditor: Callable[..., dict[str, Any]] | None = None,
                     emit: Callable[[str], None] | None = None) -> bool | None:
    """Run a single audited, no-write probe; None means the opt-in is disabled.

    This routine is deliberately invoked only at process startup. The audit
    reads the private billing database and existing onboarding store using
    read-only connections and only retrieves existing Stripe resources.
    """
    env = os.environ if environ is None else environ
    if env.get("NIJA_FOUNDING100_AUDIT_ON_STARTUP") != "true":
        return None
    write = _LOG.warning if emit is None else emit
    member_id = str(env.get("NIJA_FOUNDING100_AUDIT_USER_ID", "") or "").strip()
    application_id = str(env.get("NIJA_FOUNDING100_AUDIT_APPLICATION_ID", "") or "").strip()
    if (not member_id or not application_id or len(member_id) > 128
            or len(application_id) > 128):
        write("NIJA_FOUNDING100_AUDIT result=blocked reason=target_invalid full_onboarding_certified=false")
        return False
    try:
        if auditor is None:
            from scripts.founding100_readonly_certification import audit as auditor
        report = auditor(
            member_id, application_id,
            billing_url=env.get("BILLING_DATABASE_URL", ""),
            onboarding_db_path=env.get("NIJA_ONBOARDING_DB_PATH", ""),
            stripe_key=env.get("STRIPE_SECRET_KEY", ""),
        )
        if not isinstance(report, dict):
            raise ValueError("invalid_audit_result")
        flags = tuple(report.get(name) is True for name in _FLAG_NAMES)
        membership_verified = all(flags) and report.get("authoritative_member_verified") is True
        source_codes = report.get("blocking_sources", [])
        if not isinstance(source_codes, list):
            raise ValueError("invalid_blocking_sources")
        categories = sorted(_SOURCE_CODES.intersection(source_codes))
        code = ",".join(categories) if categories else "checklist_unverified"
        if membership_verified:
            code = "none"
        # Only fixed labels and booleans; no source-provided strings or IDs.
        values = ",".join(name + ":" + ("true" if passed else "false")
                          for name, passed in zip(_FLAG_NAMES, flags))
        write("NIJA_FOUNDING100_AUDIT result=" +
              ("membership_verified" if membership_verified else "blocked") +
              " flags=" + values + " blocking_sources=" + code +
              " full_onboarding_certified=false trading_authorized=false")
        return membership_verified
    except Exception:
        # Never log an exception object, provider response, traceback, token,
        # database URL or customer field from the trusted sources.
        write("NIJA_FOUNDING100_AUDIT result=blocked reason=source_error full_onboarding_certified=false")
        return False


def launch_opt_in_audit(*, environ: Mapping[str, str] | None = None) -> bool:
    """Start the opt-in audit without holding billing request startup hostage.

    Render may run multiple worker processes, so logs may contain more than one
    identical read-only diagnostic. This never sends customer notifications.
    """
    env = os.environ if environ is None else environ
    if env.get("NIJA_FOUNDING100_AUDIT_ON_STARTUP") != "true":
        return False
    from threading import Thread
    Thread(target=run_opt_in_audit, kwargs={"environ": dict(env)},
           name="nija-founding100-readonly-audit", daemon=True).start()
    return True
