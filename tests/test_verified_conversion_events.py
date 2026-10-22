from analytics.verified_conversion_events import (
    verified_course_purchase,
    verified_lead_event,
)


def test_lead_requires_persistence_and_consent():
    assert verified_lead_event({"id": "lead-1", "persisted": False}, consent=True) is None
    assert verified_lead_event({"id": "lead-1", "persisted": True}, consent=False) is None
    assert verified_lead_event({"persisted": True}, consent=True) is None
    event = verified_lead_event({"id": "lead-1", "persisted": True}, consent=True)
    assert event["dedupe_key"] == "lead:lead-1"
    assert "email" not in event["parameters"]


def test_course_requires_paid_entitlement_and_consent():
    paid = {"session_id": "cs_123", "status": "paid", "granted": True}
    assert verified_course_purchase(paid, consent=True)["dedupe_key"] == "course:cs_123"
    assert verified_course_purchase({**paid, "status": "pending"}, consent=True) is None
    assert verified_course_purchase({**paid, "granted": False}, consent=True) is None
    assert verified_course_purchase(paid, consent=False) is None
    assert verified_course_purchase({**paid, "session_id": "not_checkout"}, consent=True) is None
