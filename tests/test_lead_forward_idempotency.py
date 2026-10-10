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
    monkeypatch.setenv("NIJA_LEAD_FORWARD_DB_PATH", str(tmp_path / "persistent_forward.sqlite3"))
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

    with sqlite3.connect(intake._forward_db_path()) as conn:
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
    with sqlite3.connect(intake._forward_db_path()) as conn:
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



def test_sent_history_survives_ephemeral_lead_database_replacement(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["email"]) or True)
    status, result = _request(_lead())
    assert status == 201 and result["forwarded"]

    # Simulate a new Render container with an empty nonpersistent intake DB,
    # while the forward-history file survives on the separately mounted disk.
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "replacement_container.sqlite3"))
    replay_status, replay = _request(_lead())
    assert replay_status == 201  # Source DB is fresh; durable forwarding state is not.
    assert replay["accepted"] and not replay["forwarded"]
    assert calls == ["synthetic-idempotency@example.com"]

def test_missing_timestamp_replay_uses_stable_identity(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    lead = _lead()
    lead.pop("submitted_at")
    times = iter([
        "2026-10-10T12:00:00.000Z",
        "2026-10-10T12:05:00.000Z",
        "2026-10-10T12:10:00.000Z",
    ])
    monkeypatch.setattr(intake, "_utcnow", lambda: next(times, "2026-10-10T12:15:00.000Z"))
    forwards = []
    monkeypatch.setattr(intake, "_forward", lambda lead: forwards.append(lead) or True)
    first_code, first = _request(lead)
    second_code, second = _request(lead)
    assert first_code == 201
    assert second_code == 200 and second["duplicate"]
    assert first["lead_id"] == second["lead_id"]
    assert len(forwards) == 1


def test_malformed_timestamp_replay_uses_stable_identity(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    lead = _lead()
    lead["submitted_at"] = "not-a-timestamp"
    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(1) or True)
    _, first = _request(lead)
    status, replay = _request(lead)
    assert status == 200 and replay["duplicate"]
    assert first["lead_id"] == replay["lead_id"] and len(sent) == 1


def test_expired_lease_owner_cannot_override_current_claim(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    key = "a" * 64
    stale = intake._claim_forward(key)
    assert stale
    with sqlite3.connect(intake._forward_db_path()) as conn:
        conn.execute("UPDATE website_lead_forwarding SET lease_until=0 WHERE event_key=?", (key,))
        conn.commit()
    current = intake._claim_forward(key)
    assert current and current != stale

    assert not intake._finish_forward(key, claim_token=stale, sent=False)
    with sqlite3.connect(intake._forward_db_path()) as conn:
        state = conn.execute(
            "SELECT state, lease_token FROM website_lead_forwarding WHERE event_key=?", (key,)
        ).fetchone()
    assert state == ("sending", current)

    assert intake._finish_forward(key, claim_token=current, sent=True)
    assert intake._claim_forward(key) is None


def test_legacy_forwarding_table_migrates_without_losing_sent_rows(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    path = intake._forward_db_path()
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE website_lead_forwarding ("
            "event_key TEXT PRIMARY KEY, state TEXT NOT NULL, "
            "lease_until REAL NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO website_lead_forwarding(event_key, state, lease_until) "
            "VALUES ('legacy-sent', 'sent', 0)"
        )
        conn.commit()
    assert intake._claim_forward("legacy-sent") is None
    with sqlite3.connect(path) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(website_lead_forwarding)")}
        state = conn.execute(
            "SELECT state FROM website_lead_forwarding WHERE event_key='legacy-sent'"
        ).fetchone()[0]
    assert "lease_token" in columns and state == "sent"


def test_same_submission_from_two_form_labels_forwards_once(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["form_name"]) or True)

    first = dict(_lead(), form_name="Lead_Gate")
    second = dict(_lead(), form_name="lead-gate-modal")
    first_status, first_body = _request(first)
    second_status, second_body = _request(second)

    assert first_status == 201 and first_body["forwarded"]
    assert second_status == 201 and not second_body["duplicate"]
    assert not second_body["forwarded"] and not second_body["forward_error"]
    assert calls == ["Lead_Gate"]


def test_different_submission_times_still_forward_separately(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["submitted_at"]) or True)

    _request(_lead())
    _request(dict(_lead(), submitted_at="2026-10-11T00:00:00Z"))
    assert len(calls) == 2
