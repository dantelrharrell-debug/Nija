"""Fail-closed eligibility checks for NIJA outbound call imports.

This module NEVER initiates calls. It deliberately rejects records without
documented screening evidence. Review jurisdiction-specific requirements
with qualified counsel before activating any dialing.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class CallCandidate:
    contact_id: str
    campaign: str
    phone_e164: str
    purpose: str
    phone_validated: bool = False
    suppression_checked: bool = False
    suppressed: bool = True
    local_hours_allowed: bool = False
    screening_timestamp: Optional[datetime] = None
    consent_verified: bool = False
    consent_scope_matches: bool = False
    business_recipient_verified: bool = False
    human_operated: bool = False


def eligible(candidate: CallCandidate) -> tuple[bool, tuple[str, ...]]:
    reasons = []
    if candidate.campaign not in ("b2b", "consumer"):
        reasons.append("invalid_campaign")
    if not candidate.contact_id or not candidate.phone_e164.startswith("+") or not candidate.phone_e164[1:].isdigit():
        reasons.append("invalid_contact_or_phone")
    if not candidate.phone_validated:
        reasons.append("phone_unvalidated")
    if not candidate.suppression_checked or candidate.suppressed:
        reasons.append("suppression_not_cleared")
    if not candidate.local_hours_allowed:
        reasons.append("outside_verified_calling_hours")
    if not candidate.human_operated:
        reasons.append("human_operated_dialing_required")
    if candidate.screening_timestamp is None or candidate.screening_timestamp.tzinfo is None:
        reasons.append("missing_screening_timestamp")
    elif candidate.screening_timestamp > datetime.now(timezone.utc):
        reasons.append("future_screening_timestamp")
    if candidate.campaign == "b2b":
        if candidate.purpose != "business_partnership" or not candidate.business_recipient_verified:
            reasons.append("b2b_purpose_or_recipient_unverified")
    if candidate.campaign == "consumer":
        if not candidate.consent_verified or not candidate.consent_scope_matches:
            reasons.append("consumer_consent_unverified")
    return (not reasons, tuple(reasons))
