"""Fail-closed billing admission and independent exposure reconciliation policy.

This module does not connect to Stripe or brokers and does not authorize execution.
A caller must supply independently verified billing and exposure evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AccountEvidence:
    # Only a trusted server-side billing verifier may set this True.
    billing_verified: bool = False
    subscription_status: Optional[str] = None
    # True only after a separate, authenticated broker/ledger exposure audit.
    exposure_verified: bool = False
    has_open_exposure: Optional[bool] = None


@dataclass(frozen=True)
class AccountPolicy:
    may_admit_new_trades: bool
    must_reconcile_exposure: bool
    reason: str


def evaluate_account_policy(evidence: AccountEvidence) -> AccountPolicy:
    """Separate subscription admission from continuing risk obligations.

    Unknown exposure is never assumed flat, even for suspended users.
    An active/trialing billing state is necessary but never sufficient for
    execution authorization; independent execution gates still apply.
    """
    if not evidence.exposure_verified or evidence.has_open_exposure is None:
        reconcile = True
    else:
        reconcile = bool(evidence.has_open_exposure)

    if not evidence.billing_verified:
        return AccountPolicy(False, reconcile, "billing_unverified")
    status = (evidence.subscription_status or "").strip().lower()
    if status not in {"active", "trialing"}:
        return AccountPolicy(False, reconcile, "subscription_not_entitled")
    return AccountPolicy(True, reconcile, "billing_entitled_execution_gates_required")
