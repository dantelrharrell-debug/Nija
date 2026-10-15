from __future__ import annotations

import render_apollo_feeder as feeder

import pytest


def test_run_sync_rescans_contacts_at_saved_cursor(monkeypatch):
    cursor = "2026-09-05T00:00:00+00:00"
    calls: list[int] = []
    saved: dict[str, object] = {}

    newer = {
        "id": "contact-new",
        "updated_at": "2026-09-05T00:01:00+00:00",
        "label_ids": [],
    }
    at_cursor = {
        "id": "contact-old",
        "updated_at": cursor,
        "label_ids": [],
    }

    def fake_request(path, payload):
        calls.append(payload["page"])
        if payload["page"] == 1:
            return {"contacts": [newer, at_cursor] + [dict(at_cursor) for _ in range(98)]}
        return {"contacts": []}

    monkeypatch.setattr(feeder, "_load_cursor", lambda: cursor)
    monkeypatch.setattr(feeder, "_pages_per_sync", lambda: 5)
    monkeypatch.setattr(feeder, "_apollo_request", fake_request)
    monkeypatch.setattr(feeder, "_mirror_website_lead", lambda contact: "not_website_lead")
    monkeypatch.setattr(feeder, "_contact_payload", lambda contact: (None, "missing_phone"))
    monkeypatch.setattr(
        feeder,
        "_save_state",
        lambda newest, counts, error="": saved.update(
            {"cursor": newest, "counts": dict(counts), "error": error}
        ),
    )

    counts = feeder.run_sync()

    assert calls == [1, 2]
    assert counts["contacts_scanned"] == 100
    assert counts["contacts_seen"] == 100
    assert saved["cursor"] == newer["updated_at"]
    assert counts["audit_missing_ai_consent"] == 100
    assert counts["audit_missing_consent_record"] == 100
    assert counts["audit_missing_jurisdiction"] == 100
    assert counts["audit_missing_phone"] == 100


def test_run_sync_without_cursor_keeps_bootstrap_paging(monkeypatch):
    calls: list[int] = []

    def fake_request(path, payload):
        page = payload["page"]
        calls.append(page)
        if page == 1:
            return {
                "contacts": [
                    {
                        "id": f"contact-{i}",
                        "updated_at": f"2026-09-04T23:{i % 60:02d}:00+00:00",
                        "label_ids": [],
                    }
                    for i in range(100)
                ]
            }
        return {"contacts": []}

    monkeypatch.setattr(feeder, "_load_cursor", lambda: "")
    monkeypatch.setattr(feeder, "_pages_per_sync", lambda: 5)
    monkeypatch.setattr(feeder, "_apollo_request", fake_request)
    monkeypatch.setattr(feeder, "_mirror_website_lead", lambda contact: "not_website_lead")
    monkeypatch.setattr(feeder, "_contact_payload", lambda contact: (None, "missing_phone"))
    monkeypatch.setattr(feeder, "_save_state", lambda newest, counts, error="": None)

    feeder.run_sync()

    assert calls == [1, 2]


def test_empty_first_apollo_page_is_not_reported_as_successful_sync(monkeypatch):
    """NIJA's Apollo account is populated; zero scanned must be an error."""
    monkeypatch.setattr(feeder, "_load_cursor", lambda: "")
    monkeypatch.setattr(feeder, "_pages_per_sync", lambda: 5)
    monkeypatch.setattr(
        feeder,
        "_apollo_request",
        lambda path, payload: {"contacts": [], "pagination": {"total_entries": 0}},
    )
    monkeypatch.setattr(
        feeder, "_save_state",
        lambda *args, **kwargs: pytest.fail("Empty Apollo sync must not checkpoint"),
    )
    with pytest.raises(RuntimeError, match="zero records"):
        feeder.run_sync()


def test_missing_contacts_field_is_not_silently_treated_as_empty(monkeypatch):
    monkeypatch.setattr(feeder, "_load_cursor", lambda: "")
    monkeypatch.setattr(feeder, "_apollo_request", lambda path, payload: {"pagination": {"total_entries": 314}})
    monkeypatch.setattr(
        feeder, "_save_state",
        lambda *args, **kwargs: pytest.fail("Invalid response must not checkpoint"),
    )
    with pytest.raises(RuntimeError, match="invalid contacts field"):
        feeder.run_sync()


def test_empty_later_page_is_valid():
    assert feeder._validated_contact_page({"contacts": []}, page=2) == []


def test_independent_readiness_audit_counts_overlapping_gaps(monkeypatch):
    contact = {"id": "offline-test", "typed_custom_fields": {}, "phone_numbers": []}
    gaps = set(feeder._independent_readiness_gaps(contact))
    assert gaps == {
        "audit_missing_phone",
        "audit_missing_timezone",
        "audit_missing_ai_consent",
        "audit_missing_consent_record",
        "audit_missing_legal_basis",
        "audit_dnc_unverified",
        "audit_missing_jurisdiction",
    }
    # A diagnostic read cannot change the contact or invent calling evidence.
    assert contact["typed_custom_fields"] == {}


def test_independent_readiness_audit_preserves_valid_evidence(monkeypatch):
    fields = {
        "NIJA_APOLLO_CONSENT_FIELD_ID": "consent",
        "NIJA_APOLLO_CONSENT_RECORD_FIELD_ID": "consent_record",
        "NIJA_APOLLO_LEGAL_BASIS_FIELD_ID": "legal_basis",
        "NIJA_APOLLO_RECIPIENT_JURISDICTION_FIELD_ID": "state",
    }
    for name, value in fields.items():
        monkeypatch.setenv(name, value)
    contact = {
        "id": "offline-test",
        "time_zone": "America/Los_Angeles",
        "phone_numbers": [
            {"sanitized_number": "+12065550123", "dnc_status_cd": "not_found"}
        ],
        "typed_custom_fields": {
            "consent": True, "consent_record": "offline-record",
            "legal_basis": "offline-test-basis", "state": "US-WA"
        },
    }
    assert feeder._independent_readiness_gaps(contact) == ()
