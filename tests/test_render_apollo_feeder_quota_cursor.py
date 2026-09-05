from __future__ import annotations

import render_apollo_feeder as feeder


def test_run_sync_stops_paging_once_saved_cursor_is_reached(monkeypatch):
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
        if payload["page"] != 1:
            raise AssertionError("run_sync must not request pages older than the saved cursor")
        # Keep the page full-sized so the legacy len(contacts) < 100 shortcut cannot
        # accidentally make this test pass.
        return {"contacts": [newer, at_cursor] + [dict(at_cursor) for _ in range(98)]}

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

    assert calls == [1]
    assert counts["contacts_scanned"] == 1
    assert counts["contacts_seen"] == 1
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
