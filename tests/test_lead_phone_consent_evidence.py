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


def test_hero_email_only_lead_preserves_explicit_marketing_consent():
    lead = normalize_lead_payload({
        "source": "hero-email-optin",
        "email": "hero-qa@example.com",
        "submitted_at": "2026-10-12T14:00:00Z",
        "marketingConsent": True,
    })
    assert lead["form_name"] == "hero-email-optin"
    assert lead["name"] == "Website Visitor"
    assert lead["communications_consent"] == "true"
    assert lead["consent_source"] == "hero-email-optin"
    assert lead["consent_recorded_at"] == "2026-10-12T14:00:00.000Z"


def test_conflicting_explicit_consent_values_fail_closed():
    lead = normalize_lead_payload({
        "form_name": "hero-email-optin",
        "email": "qa@example.com",
        "submitted_at": "2026-10-12T14:00:00Z",
        "marketing_consent": True,
        "communications_consent": False,
    })
    assert lead["communications_consent"] == "false"
    assert lead["consent_recorded_at"] == ""


def test_explicit_marketing_consent_takes_priority_over_generic_form_checkbox():
    lead = normalize_lead_payload({
        "form_name": "Founding 100 Application",
        "email": "qa@example.com",
        "consent": "on",
        "marketingConsent": False,
    })
    assert lead["communications_consent"] == "false"


def test_no_source_timestamp_does_not_invent_consent_proof():
    lead = normalize_lead_payload({
        "form_name": "hero-email-optin",
        "email": "qa@example.com",
        "communications_consent": "yes",
    })
    assert lead["communications_consent"] == "true"
    assert lead["consent_recorded_at"] == ""


def test_zapier_nested_data_form_fields_and_customer_name():
    lead = normalize_lead_payload({
        "formName": {"form_name": "lead_gate"},
        "data": {"fields": {"Email Address": "NEWQA@example.com", "Name": "New QA Lead"}},
        "submitted_at": "2026-10-14T04:49:29Z",
    })
    assert lead["email"] == "newqa@example.com"
    assert lead["name"] == "New QA Lead"
    assert lead["form_name"] == "lead_gate"
    assert lead["submitted_at"] == "2026-10-14T04:49:29.000Z"
    assert lead["communications_consent"] == "false"


def test_flat_zapier_email_address_and_split_name():
    lead = normalize_lead_payload({
        "form_name": "lead_gate",
        "Email": "split@example.com",
        "firstName": "Split",
        "lastName": "Name",
    })
    assert lead["email"] == "split@example.com"
    assert lead["name"] == "Split Name"


def test_conflicting_nested_customer_emails_fail_closed():
    import pytest
    with pytest.raises(ValueError, match="Conflicting lead email fields"):
        normalize_lead_payload({
            "data": {"email": "customer@example.com"},
            "email": "other@example.com",
        })


def test_no_contact_email_does_not_fall_back_to_metadata_or_headers():
    import pytest
    with pytest.raises(ValueError, match="Lead email is missing or invalid"):
        normalize_lead_payload({
            "to": "owner@nijaaitrading.com",
            "from": "mailer@provider.example",
            "formName": {"form_name": "lead_gate"},
            "data": {"name": "No Email"},
        })


def test_nested_consent_conflict_remains_fail_closed():
    lead = normalize_lead_payload({
        "email": "consentqa@example.com",
        "data": {"marketingConsent": True},
        "communications_consent": False,
    })
    assert lead["communications_consent"] == "false"
    assert lead["consent_recorded_at"] == ""
