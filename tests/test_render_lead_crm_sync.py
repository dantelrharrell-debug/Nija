from __future__ import annotations

import io
import json
import time


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.zsets = {}
    def ping(self): return True
    def hsetnx(self, key, field, value):
        h = self.hashes.setdefault(key, {})
        if field in h: return 0
        h[field] = str(value); return 1
    def hset(self, key, mapping):
        h = self.hashes.setdefault(key, {})
        h.update({k: str(v) for k, v in mapping.items()})
    def hget(self, key, field): return self.hashes.get(key, {}).get(field)
    def hgetall(self, key): return dict(self.hashes.get(key, {}))
    def zadd(self, key, mapping): self.zsets.setdefault(key, {}).update(mapping)
    def zrem(self, key, member): self.zsets.setdefault(key, {}).pop(member, None)
    def zrangebyscore(self, key, low, high, start=0, num=None):
        rows = [k for k,v in sorted(self.zsets.get(key, {}).items(), key=lambda x:x[1]) if float(low) <= float(v) <= float(high)]
        return rows[start:start+num if num is not None else None]
    def expire(self, key, seconds): return True


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


def test_live_intake_route_enqueues_crm_without_delaying_zapier(monkeypatch, tmp_path):
    import io
    from render_lead_intake import handle_lead_intake_post
    import render_lead_intake as intake

    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "intake.sqlite3"))
    monkeypatch.setenv("NIJA_LEAD_WEBHOOK_TOKEN", "qa-internal-token")
    monkeypatch.setattr(sync, "start_worker", lambda: None)
    forwarded = []
    monkeypatch.setattr(intake, "_forward", lambda lead: forwarded.append(lead["email"]) or True)

    payload = json.dumps({
        "form_name": "free_trader_assessment",
        "name": "NIJA QA Visitor",
        "email": "qa@example.com",
        "submitted_at": sync._now_iso(),
    }).encode("utf-8")

    class Handler:
        path = "/api/leads/intake"
        headers = {"Content-Length": str(len(payload)), "X-NIJA-Lead-Token": "qa-internal-token"}

        def __init__(self):
            self.rfile = io.BytesIO(payload)
            self.wfile = io.BytesIO()
            self.status = None

        def send_response(self, code):
            self.status = code

        def send_header(self, key, value):
            pass

        def end_headers(self):
            pass

    request1 = Handler()
    assert handle_lead_intake_post(request1) is True
    result1 = json.loads(request1.wfile.getvalue())
    assert request1.status == 201
    assert result1["accepted"] and result1["crm_queued"] and result1["forwarded"]
    assert result1["crm_queue_error"] is False

    request2 = Handler()
    assert handle_lead_intake_post(request2) is True
    result2 = json.loads(request2.wfile.getvalue())
    assert request2.status == 200
    assert result2["duplicate"]
    assert result2["lead_id"] == result1["lead_id"]

    with sync._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM website_lead_crm_sync").fetchone()[0] == 1
    assert forwarded


def test_redis_outbox_survives_local_sqlite_loss(monkeypatch, tmp_path):
    fake = FakeRedis()
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "first.sqlite3"))
    monkeypatch.setenv("NIJA_LEAD_APOLLO_SYNC_ENABLED", "true")
    monkeypatch.setenv("APOLLO_API_KEY", "private-credential")
    monkeypatch.setattr(sync, "_redis_client", lambda: fake)
    monkeypatch.setattr(sync, "start_worker", lambda: None)
    assert sync.enqueue_lead({"name": "Durable QA", "email": "durable@example.com"}, "evt_durable")
    assert fake.hget(sync._redis_event_key("evt_durable"), "state") == "pending"

    # Simulate a Render restart with a fresh/empty ephemeral SQLite file.
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "second.sqlite3"))
    monkeypatch.setattr(sync, "_deliver_batch", lambda rows, key: {"durable@example.com"})
    result = sync.sync_pending()
    assert result["attempted"] == 1
    assert result["synced"] == 1
    assert fake.hget(sync._redis_event_key("evt_durable"), "state") == "synced"
    assert fake.zrangebyscore(f"{sync._REDIS_PREFIX}:pending", 0, time.time() + 1000) == []


def test_redis_dedupe_does_not_requeue_synced_event(monkeypatch, tmp_path):
    fake = FakeRedis()
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "dedupe.sqlite3"))
    monkeypatch.setattr(sync, "_redis_client", lambda: fake)
    monkeypatch.setattr(sync, "start_worker", lambda: None)
    lead = {"name": "Dedupe QA", "email": "dedupe@example.com"}
    assert sync.enqueue_lead(lead, "evt_same")
    fake.hset(sync._redis_event_key("evt_same"), mapping={"state": "synced"})
    fake.zrem(f"{sync._REDIS_PREFIX}:pending", "evt_same")
    assert sync.enqueue_lead(lead, "evt_same")
    assert fake.zrangebyscore(f"{sync._REDIS_PREFIX}:pending", 0, time.time() + 1000) == []


def test_redis_retry_remains_pending(monkeypatch, tmp_path):
    fake = FakeRedis()
    monkeypatch.setenv("NIJA_LEAD_DB_PATH", str(tmp_path / "retryredis.sqlite3"))
    monkeypatch.setenv("APOLLO_API_KEY", "private-credential")
    monkeypatch.setattr(sync, "_redis_client", lambda: fake)
    monkeypatch.setattr(sync, "start_worker", lambda: None)
    sync.enqueue_lead({"name": "Retry QA", "email": "retry@example.com"}, "evt_retry_redis")
    monkeypatch.setattr(sync, "_deliver_batch", lambda rows, key: set())
    result = sync.sync_pending()
    assert result["retry"] == 1
    rec = fake.hgetall(sync._redis_event_key("evt_retry_redis"))
    assert rec["state"] == "pending"
    assert int(rec["attempts"]) == 1
    assert float(rec["next_attempt_at"]) > time.time()
