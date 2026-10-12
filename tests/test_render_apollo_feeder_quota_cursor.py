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
