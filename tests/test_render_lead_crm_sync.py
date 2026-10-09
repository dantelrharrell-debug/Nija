from __future__ import annotations

import io
import json
import time

import render_lead_crm_sync as sync


def create_site_event(monkeypatch, tmp_path, *, event_key="evt_1", email="qa@example.com"):
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "leads.sqlite3"))
    monkeypatch.setenv("NIJA_LEAD_APOLLO_SYNC_ENABLED", "true")
    monkeypatch.setenv("APOLLO_API_KEY", "private-credential")
    with sync._connect() as conn:
        conn.execute("CREATE TABLE website_leads (event_key TEXT PRIMARY KEY, email TEXT, name TEXT, received_at TEXT)")
        conn.execute(
            "INSERT INTO website_leads (event_key,email,name,received_at) VALUES (?,?,?,?)",
            (event_key, email, "QA Website", sync._now_iso()),
        )
        conn.commit()


class FakeHTTP:
    status = 200

    def __init__(self, obj):
        self.obj = obj

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size=None):
        return json.dumps(self.obj).encode("utf-8")


def test_sync_creates_contact_once_without_sequence(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    calls = []

    def request(req, timeout):
        calls.append(req)
        payload = json.loads(req.data)
        assert set(payload) == {"contacts", "run_dedupe", "append_label_names"}
        assert payload["run_dedupe"] is True
        assert payload["append_label_names"] == ["NIJA Website Leads"]
        assert set(payload["contacts"][0]) == {"first_name", "last_name", "email"}
        assert b"sequence" not in req.data.lower()
        assert req.get_header("X-api-key") == "private-credential"
        assert timeout == 12
        return FakeHTTP(
            {"created_contacts": [{"id": "apollo-1", "email": "qa@example.com"}], "existing_contacts": []}
        )

    monkeypatch.setattr(sync.urllib.request, "urlopen", request)
    assert sync.sync_pending() == {"attempted": 1, "synced": 1, "retry": 0, "waiting": 0}
    assert sync.sync_pending() == {"attempted": 0, "synced": 0, "retry": 0, "waiting": 0}
    assert len(calls) == 1


def test_retry_when_apollo_did_not_acknowledge(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sync.urllib.request, "urlopen",
        lambda req, timeout: FakeHTTP({"created_contacts": [], "existing_contacts": []}),
    )
    assert sync.sync_pending()["retry"] == 1
    with sync._connect() as conn:
        rec = conn.execute(
            "SELECT state, attempts, last_error_code, next_attempt_at FROM website_lead_crm_sync"
        ).fetchone()
    assert rec["state"] == "pending"
    assert rec["attempts"] == 1
    assert rec["last_error_code"] == "not_acknowledged"
    assert rec["next_attempt_at"] >= time.time()
    assert sync.sync_pending()["attempted"] == 0


def test_disable_or_missing_key_sends_nothing(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sync.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not call")),
    )
    monkeypatch.delenv("APOLLO_API_KEY")
    assert sync.sync_pending()["waiting"] == 1
    monkeypatch.setenv("NIJA_LEAD_APOLLO_SYNC_ENABLED", "false")
    assert sync.sync_pending()["waiting"] == 0


def test_created_and_existing_both_count_as_acknowledged(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sync.urllib.request, "urlopen",
        lambda req, timeout: FakeHTTP(
            {"created_contacts": [], "existing_contacts": [{"id": "ex1", "email": "qa@example.com"}]}
        ),
    )
    assert sync.sync_pending()["synced"] == 1


def test_backfill_recent_only(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    with sync._connect() as conn:
        conn.execute(
            "INSERT INTO website_leads VALUES('old', 'old@example.com', 'Old Contact', '2020-01-01T00:00:00.000Z')"
        )
        conn.commit()
        sync._prepare(conn)
        count = conn.execute("SELECT count(*) FROM website_lead_crm_sync").fetchone()[0]
    assert count == 1


def test_apollo_latency_does_not_block_new_intake(monkeypatch, tmp_path):
    import threading
    create_site_event(monkeypatch, tmp_path)
    entered = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(sync, "start_worker", lambda: None)

    def slow_delivery(rows, key):
        entered.set()
        release.wait(timeout=3)
        return {"qa@example.com"}

    monkeypatch.setattr(sync, "_deliver_batch", slow_delivery)
    thread = threading.Thread(target=sync.sync_pending, daemon=True)
    thread.start()
    assert entered.wait(timeout=1)
    start = time.monotonic()
    result = sync.enqueue_lead({"name": "New Visitor", "email": "new@example.com"}, "evt_2")
    elapsed = time.monotonic() - start
    release.set()
    thread.join(timeout=2)
    assert result is True
    assert elapsed < 0.5, f"Apollo must not block website lead intake: took {elapsed:.3f}s"


def test_retries_http_errors_without_leaking_key(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)

    def blocked(req, timeout):
        raise sync.urllib.error.HTTPError(sync._APOLLO_URL, 403, "secret private-credential", {}, io.BytesIO(b"oops"))

    monkeypatch.setattr(sync.urllib.request, "urlopen", blocked)
    assert sync.sync_pending()["retry"] == 1
    with sync._connect() as conn:
        row = conn.execute("SELECT last_error_code FROM website_lead_crm_sync").fetchone()
    assert row["last_error_code"] == "HTTP_403"
    assert "private-credential" not in row["last_error_code"]


def test_clean_start_without_website_table(monkeypatch, tmp_path):
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "fresh.sqlite3"))
    with sync._connect() as conn:
        sync._prepare(conn)
        assert conn.execute("SELECT COUNT(*) FROM website_lead_crm_sync").fetchone()[0] == 0


def test_old_failures_remain_retryable_after_twelve_attempts(monkeypatch, tmp_path):
    create_site_event(monkeypatch, tmp_path)
    with sync._connect() as conn:
        sync._prepare(conn)
        conn.execute("UPDATE website_lead_crm_sync SET attempts=12,next_attempt_at=0")
        conn.commit()
    monkeypatch.setattr(sync, "_deliver_batch", lambda rows, key: {"qa@example.com"})
    assert sync.sync_pending()["synced"] == 1
