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


def test_legacy_sent_forwarding_state_survives_form_agnostic_key_migration(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    payload = _lead()
    canonical, legacy_key, _ = intake.record_lead(payload)
    forward_key = intake._forward_key(payload, canonical, legacy_key)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["email"]) or True)

    with intake._forward_connect() as conn:
        conn.execute(
            "INSERT INTO website_lead_forwarding(event_key, state, lease_until) "
            "VALUES (?, 'sent', 0)",
            (legacy_key,),
        )

    status, result = _request(payload)

    assert status == 200 and result["duplicate"]
    assert not result["forwarded"] and not result["forward_error"]
    assert calls == []
    with sqlite3.connect(intake._forward_db_path()) as conn:
        assert conn.execute(
            "SELECT state FROM website_lead_forwarding WHERE event_key=?",
            (legacy_key,),
        ).fetchone()[0] == "sent"
        assert conn.execute(
            "SELECT state FROM website_lead_forwarding WHERE event_key=?",
            (forward_key,),
        ).fetchone()[0] == "sent"


def test_different_submission_times_still_forward_separately(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["submitted_at"]) or True)

    _request(_lead())
    _request(dict(_lead(), submitted_at="2026-10-11T00:00:00Z"))
    assert len(calls) == 2


def test_forward_includes_stable_event_id_and_consent_provenance(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(dict(lead)) or True)
    lead = {
        "source": "hero-email-optin",
        "email": "hero-qa@example.com",
        "submitted_at": "2026-10-12T14:10:00Z",
        "marketing_consent": True,
        "event_id": "hero-submission-001",
    }
    status, result = _request(lead)
    assert status == 201 and result["forwarded"] and not result["forward_error"]
    assert len(sent) == 1
    assert sent[0]["name"] == "Website Visitor"
    assert sent[0]["event_id"] and len(sent[0]["event_id"]) == 64
    assert sent[0]["communications_consent"] == "true"
    assert sent[0]["consent_source"] == "hero-email-optin"
    assert sent[0]["consent_recorded_at"] == "2026-10-12T14:10:00.000Z"
    replay_status, replay = _request(dict(lead))
    assert replay_status == 200 and replay["duplicate"]
    assert not replay["forwarded"]
    assert len(sent) == 1


def test_distinct_upstream_ids_same_email_and_timestamp_remain_separate(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(lead["event_id"]) or True)
    first = dict(_lead(), submission_id="source-A")
    second = dict(_lead(), submission_id="source-B")
    a_status, a = _request(first)
    b_status, b = _request(second)
    assert a_status == 201 and b_status == 201
    assert a["lead_id"] != b["lead_id"]
    assert a["forwarded"] and b["forwarded"]
    assert len(set(sent)) == 2


def test_same_upstream_id_with_different_source_timestamps_is_a_replay(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(lead["event_id"]) or True)
    first = dict(_lead(), eventId="source-C")
    second = dict(first, submitted_at="2026-10-11T00:00:00Z")
    _, accepted = _request(first)
    status, replay = _request(second)
    assert status == 200 and replay["duplicate"]
    assert accepted["lead_id"] == replay["lead_id"]
    assert len(sent) == 1


def test_same_upstream_id_across_form_aliases_forwards_once(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(dict(lead)) or True)
    first = dict(_lead(), form_name="Lead_Gate", event_id="origin-1")
    second = dict(first, form_name="lead-gate-modal")
    a_status, a = _request(first)
    b_status, b = _request(second)
    assert a_status == 201 and b_status == 201
    assert a["forwarded"] and not b["forwarded"]
    assert len(sent) == 1


def _seed_legacy_timestamp_sent_marker(payload):
    """Set up the old record and old notification state without sending."""
    import hashlib

    canonical = intake.normalize_lead_payload(payload)
    record_identity = (
        f"{canonical['form_name'].casefold()}|"
        f"{canonical['email'].casefold()}|{canonical['submitted_at']}"
    )
    record_key = hashlib.sha256(record_identity.encode("utf-8")).hexdigest()
    old_identity = f"submission|{canonical['email']}|{canonical['submitted_at']}"
    forward_key = hashlib.sha256(old_identity.encode("utf-8")).hexdigest()
    with intake._connect() as conn:
        intake._ensure_schema(conn)
        conn.execute(
            """INSERT INTO website_leads
               (event_key, form_name, name, email, submitted_at, received_at, source_payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (record_key, canonical["form_name"], canonical["name"], canonical["email"],
             canonical["submitted_at"], canonical["submitted_at"], json.dumps(payload)),
        )
    with intake._forward_connect() as conn:
        conn.execute(
            "INSERT INTO website_lead_forwarding(event_key, state, lease_until) "
            "VALUES (?, 'sent', 0)",
            (forward_key,),
        )
    return canonical


def test_new_upstream_id_respects_matching_legacy_sent_marker(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    payload = dict(_lead(), event_id="origin-old")
    canonical = _seed_legacy_timestamp_sent_marker(payload)
    monkeypatch.setattr(
        intake, "_forward",
        lambda lead: (_ for _ in ()).throw(AssertionError("legacy sent lead must not forward")),
    )
    status, result = _request(payload)
    assert status == 201 and result["accepted"] and not result["forwarded"]
    new_key = intake._forward_key(payload, canonical, "unused")
    with sqlite3.connect(intake._forward_db_path()) as conn:
        assert conn.execute(
            "SELECT state FROM website_lead_forwarding WHERE event_key=?", (new_key,)
        ).fetchone()[0] == "sent"


def test_same_timestamp_legacy_marker_does_not_suppress_a_new_event(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    _seed_legacy_timestamp_sent_marker(dict(_lead(), event_id="unrelated-old-event"))
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead["event_id"]) or True)
    status, result = _request(dict(_lead(), event_id="distinct-new-event"))
    assert status == 201 and result["forwarded"] and not result["forward_error"]
    assert len(calls) == 1



def test_legacy_event_replay_migrates_from_changed_form_and_timestamp(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    original = dict(_lead(), form_name="Lead_Gate", event_id="original-source-12")
    _seed_legacy_timestamp_sent_marker(original)
    # The retry's form alias and source timestamp are both different.
    replay = dict(original, form_name="lead-gate-modal", submitted_at="2026-10-12T12:00:00Z")
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead) or True)
    status, result = _request(replay)
    assert status == 201 and result["accepted"] and not result["forwarded"]
    assert calls == []

    new_key = intake._forward_key(replay, intake.normalize_lead_payload(replay), "unused")
    with sqlite3.connect(intake._forward_db_path()) as conn:
        alias = conn.execute(
            "SELECT legacy_key FROM website_lead_forward_aliases WHERE source_key=?",
            (new_key,),
        ).fetchone()
        assert alias is not None
        state = conn.execute(
            "SELECT state FROM website_lead_forwarding WHERE event_key=?", (new_key,)
        ).fetchone()
        assert state == ("sent",)


def test_durable_alias_prevents_replay_after_ephemeral_lead_database_is_replaced(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    original = dict(_lead(), form_name="Lead_Gate", event_id="old-event-111")
    _seed_legacy_timestamp_sent_marker(original)
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead) or True)

    # First retry can prove history while the original intake DB still exists.
    changed = dict(original, form_name="LeadGate", submitted_at="2026-10-12T00:00:00Z")
    _, first = _request(changed)
    assert not first["forwarded"]
    # On a redeploy the local lead store can be lost, but the forwarding DB remains.
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "replacement_intake.sqlite3"))
    later = dict(changed, form_name="another-site-form", submitted_at="2026-10-13T00:00:00Z")
    _, second = _request(later)
    assert not second["forwarded"] and not second["forward_error"]
    assert calls == []


def test_legacy_source_missing_after_db_replacement_requires_migration_preflight(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    original = dict(_lead(), event_id="original-db-lost")
    _seed_legacy_timestamp_sent_marker(original)
    # Without a prior alias, the old forwarding marker alone has no source-ID proof.
    # Predeployment migration must run before the original DB is replaced.
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "replaced_database.sqlite3"))
    new_id = intake._forward_key(original, intake.normalize_lead_payload(original), "")
    with intake._forward_connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM website_lead_forward_aliases WHERE source_key=?", (new_id,)
        ).fetchone() is None



def test_explicit_predeployment_alias_seeding_survives_intake_db_replacement(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    original = dict(_lead(), form_name="Lead_Gate", event_id="already-sent-predeploy")
    _seed_legacy_timestamp_sent_marker(original)

    dry = intake.preseed_legacy_forward_aliases(dry_run=True)
    assert dry["source_rows"] == 1
    assert dry["candidates"] == 1
    assert dry["sent_aliases"] == 1
    assert dry["dry_run"] is True
    with intake._forward_connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM website_lead_forward_aliases").fetchone()[0]
        assert count == 0

    committed = intake.preseed_legacy_forward_aliases(dry_run=False)
    assert committed["sent_aliases"] == 1 and committed["dry_run"] is False
    with intake._forward_connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM website_lead_forward_aliases").fetchone()[0]
        assert count == 1

    # The original source DB is gone before the first post-upgrade event arrives.
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "new_ephemeral_intake.sqlite3"))
    replay = dict(original, form_name="other_alias", submitted_at="2026-10-13T02:00:00Z")
    calls = []
    monkeypatch.setattr(intake, "_forward", lambda lead: calls.append(lead) or True)
    status, result = _request(replay)
    assert status == 201 and not result["forwarded"]
    assert not result["forward_error"]
    assert calls == []


def test_predeploy_alias_migration_does_not_conflate_different_source_ids(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    original = dict(_lead(), event_id="sent-source-a")
    _seed_legacy_timestamp_sent_marker(original)
    result = intake.preseed_legacy_forward_aliases(dry_run=False)
    assert result["sent_aliases"] == 1
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "fresh_db.sqlite3"))

    sent = []
    monkeypatch.setattr(intake, "_forward", lambda lead: sent.append(lead["event_id"]) or True)
    new_event = dict(original, event_id="new-source-b")
    status, reply = _request(new_event)
    assert status == 201 and reply["forwarded"]
    assert len(sent) == 1


def test_predeploy_alias_seeding_requires_existing_source_database(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    import pytest
    with pytest.raises(FileNotFoundError):
        intake.preseed_legacy_forward_aliases(dry_run=True)



def test_predeployment_dryrun_is_read_only_for_forwarding_database(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    old = dict(_lead(), event_id="historical-dryrun")
    _seed_legacy_timestamp_sent_marker(old)
    dest = intake._forward_db_path()
    with sqlite3.connect(dest) as conn:
        conn.execute("DROP TABLE website_lead_forward_aliases")
        schema_before = conn.execute("PRAGMA schema_version").fetchone()[0]

    preview = intake.preseed_legacy_forward_aliases(dry_run=True)
    assert preview["sent_aliases"] == 1
    with sqlite3.connect(dest) as conn:
        assert conn.execute("PRAGMA schema_version").fetchone()[0] == schema_before
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='website_lead_forward_aliases'"
        ).fetchone() is None

    actual = intake.preseed_legacy_forward_aliases(dry_run=False)
    assert actual["sent_aliases"] == 1
    with sqlite3.connect(dest) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM website_lead_forward_aliases"
        ).fetchone()[0] == 1
