"""Privacy-safe conversion payloads from already verified application records.

These pure builders do not send data to GA4 or Google Ads. Callers must persist
and publish via a transactional outbox with consent and attribution checks.
"""
from typing import Mapping, Optional


def verified_lead_event(lead: Mapping, *, consent: bool) -> Optional[dict]:
    """Return an event only for a persisted, uniquely identified lead."""
    lead_id = lead.get("id")
    if not consent or not lead_id or lead.get("persisted") is not True:
        return None
    return {
        "event_name": "nija_verified_lead",
        "dedupe_key": f"lead:{lead_id}",
        "parameters": {"lead_type": "website"},
    }


def verified_course_purchase(ledger_record: Mapping, *, consent: bool) -> Optional[dict]:
    """Only a course-ledger paid entitlement can be considered for attribution.

    A publisher must additionally verify the record's provenance and ensure
    refund/revocation checks, persistent deduplication and consent gating.
    """
    sid = ledger_record.get("session_id")
    if (not consent or not isinstance(sid, str) or not sid.startswith("cs_")
            or ledger_record.get("status") != "paid"
            or ledger_record.get("granted") is not True):
        return None
    return {
        "event_name": "nija_verified_course_purchase",
        "dedupe_key": f"course:{sid}",
        "parameters": {"currency": "USD", "value": 99.0, "transaction_id": sid},
    }
