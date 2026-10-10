"""Regression checks for safe, idempotent forwarding of authenticated web leads.

No real Zapier, Apollo, email, or trading API is contacted.
"""
from __future__ import annotations

import io
import json
import sqlite3
import threading

import render_lead_intake as intake
import render_lead_crm_sync as sync


def _request(payload: dict[str, str] | None):
    body = b"" if payload is None else json.dumps(payload).encode("utf-8")

    class Handler:
        path = "/api/leads/intake"
        headers = {
            "Content-Length": str(len(body)),
            "X-NIJA-Lead-Token": "local-test-secret",
        }

        def __init__(self):
            self.rfile = io.BytesIO(body)
            self.wfile = io.BytesIO()
            self.status = None

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    handler = Handler()
    assert intake.handle_lead_intake_post(handler) is True
    return handler.status, json.loads(handler.wfile.getvalue())


def _lead():
    # Preserve the original submission time across retries.
    return {
        "form_name": "free_assessment",
        "name": "Synthetic QA",
        "email": "synthetic-idempotency@example.com",
        "submitted_at": "2026-10-10T00:00:00Z",
    }


def _config(monkeypatch, tmp_path):
    monkeypatch.setenv("NIJA_LEAD_WEBHOOK_TOKEN", "local-test-secret")
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "web_leads.sqlite3"))
    # CRM queue has its own existing idempotency and is not under test here.
    monkeypatch.setattr(sync, "enqueue_lead", lambda canonical, key: True)


def test_identical_webhook_replays_send_one_notification(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["email"]) or True)

    first_status, first = _request(_lead())
    replay_status, replay = _request(_lead())

    assert first_status == 201 and first["accepted"] and first["forwarded"]
    assert replay_status == 200 and replay["accepted"] and replay["duplicate"]
    assert not replay["forwarded"] and not replay["forward_error"]
    assert first["lead_id"] == replay["lead_id"]
    assert calls == ["synthetic-idempotency@example.com"]

    with sqlite3.connect(intake._db_path()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM website_lead_forwarding").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM website_lead_forwarding").fetchone()[0] == "sent"


def test_failed_forward_is_retryable_but_never_spammed(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []

    def flaky_forward(lead):
        calls.append(lead["email"])
        if len(calls) == 1:
            raise OSError("synthetic provider failure")
        return True

    monkeypatch.setattr(intake, "_forward", flaky_forward)
    first_status, first = _request(_lead())
    replay_status, replay = _request(_lead())
    assert first_status == 201 and first["forward_error"]
    assert replay_status == 200 and replay["duplicate"]
    assert len(calls) == 1, "Immediate replay must obey retry backoff"

    # Simulate passing the backoff without sleeping.
    with sqlite3.connect(intake._db_path()) as conn:
        conn.execute("UPDATE website_lead_forwarding SET lease_until=0")
        conn.commit()
    retry_status, retry = _request(_lead())
    assert retry_status == 200 and retry["forwarded"]
    assert not retry["forward_error"]

    last_status, last = _request(_lead())
    assert last_status == 200 and last["duplicate"]
    assert not last["forwarded"]
    assert len(calls) == 2, "Confirmed delivery must never be resent"


def test_concurrent_duplicate_cannot_send_twice(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_forward(lead):
        calls.append(lead["email"])
        started.set()
        assert release.wait(timeout=4)
        return True

    monkeypatch.setattr(intake, "_forward", slow_forward)
    holder = []

    def first_request():
        holder.append(_request(_lead()))

    worker = threading.Thread(target=first_request, daemon=True)
    worker.start()
    assert started.wait(timeout=4)
    second_status, second = _request(_lead())
    assert second_status == 200 and second["duplicate"] and not second["forwarded"]
    release.set()
    worker.join(timeout=4)
    assert not worker.is_alive()
    assert holder[0][0] == 201
    assert len(calls) == 1


def test_empty_body_remains_rejected_without_forward(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    monkeypatch.setattr(
        intake, "_forward",
        lambda lead: (_ for _ in ()).throw(AssertionError("empty payload must not forward")),
    )
    status, result = _request(None)
    assert status == 422
    assert "empty" in result["error"].lower()
