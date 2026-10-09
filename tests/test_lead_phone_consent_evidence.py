from __future__ import annotations

from render_lead_intake import normalize_lead_payload


def test_apply_phone_and_checked_consent_are_preserved_as_evidence():
    lead = normalize_lead_payload({
        "form_name": "Founding 100 Application",
        "name": "QA Visitor",
        "email": "qa@example.com",
        "submitted_at": "2026-10-09T12:00:00Z",
        "Phone Number": "(425) 555-0100",
        "consent": "on",
    })
    assert lead["phone"] == "(425) 555-0100"
    assert lead["communications_consent"] == "true"


def test_missing_or_unchecked_consent_remains_false():
    lead = normalize_lead_payload({
        "form_name": "Founding 100 Application",
        "name": "QA Visitor",
        "email": "qa@example.com",
        "Phone Number": "425-555-0100",
    })
    assert lead["phone"] == "425-555-0100"
    assert lead["communications_consent"] == "false"


def test_nested_ionos_fields_are_preserved():
    lead = normalize_lead_payload({
        "formName": {
            "form_name": "Founding 100 Application",
            "name": "Nested QA",
            "email": "nested@example.com",
            "Phone Number": "+1 425 555 0100",
            "consent": True,
        }
    })
    assert lead["phone"] == "+1 425 555 0100"
    assert lead["communications_consent"] == "true"
