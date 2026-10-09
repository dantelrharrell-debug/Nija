"""Best-effort, consent-neutral recovery of website leads into Apollo contacts.

Only creates/retains CRM contacts. It never enrolls anyone in an email sequence,
initiates calls, sends texts, or infers marketing consent from a form submission.
The website's primary lead store remains authoritative; this queue is a recovery
mirror on the Render instance and must not be considered durable without a disk.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import threading
import time
import urllib.error
import urllib.request

# The Render liveness/frontdoor process runs with python -S. That deliberately
# skips site initialization and third-party .pth runtime hooks, but also hides
# pip-installed packages. Expose only the installed package directory, without
# executing site.main() or any .pth files (which can alter trading authority).
import sys
import sysconfig

def _load_redis_package():
    try:
        import redis
        return redis
    except ImportError:
        purelib = sysconfig.get_paths().get("purelib", "")
        if purelib and purelib not in sys.path:
            sys.path.append(purelib)
        try:
            import redis
            return redis
        except ImportError:
            return None

redis_lib = _load_redis_package()
from datetime import datetime, timedelta, timezone
from typing import Any

_APOLLO_URL = "https://api.apollo.io/api/v1/contacts/bulk_create"
_WORKER_LOCK = threading.RLock()
_DELIVERY_LOCK = threading.RLock()
_WORKER_STARTED = False
_WAKE = threading.Event()
_REDIS_PREFIX = "nija:lead_crm"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _db_path() -> pathlib.Path:
    return pathlib.Path(str(os.getenv("NIJA_LEAD_DB_PATH") or os.getenv("NIJA_OUTREACH_DB_PATH") or "/app/data/nija_outreach.sqlite3").strip())


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _prepare(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS website_lead_crm_sync (
            event_key TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0,
            last_error_code TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_website_lead_crm_due ON website_lead_crm_sync(state, next_attempt_at)")
    # Recover only recent website leads (not the entire historical contact base).
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    website_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='website_leads'"
    ).fetchone()
    if website_table:
        conn.execute(
            """INSERT OR IGNORE INTO website_lead_crm_sync
               (event_key, email, name, updated_at)
               SELECT event_key, email, name, ? FROM website_leads
               WHERE received_at >= ?""",
            (_now_iso(), cutoff),
        )
    conn.commit()


def _enabled() -> bool:
    return str(os.getenv("NIJA_LEAD_APOLLO_SYNC_ENABLED", "true")).strip().lower() in {"true", "1", "yes", "on"}


def _redis_url() -> str:
    return str(
        os.getenv("NIJA_REDIS_URL")
        or os.getenv("REDIS_URL")
        or os.getenv("NIJA_RENDER_REDIS_FALLBACK_URL")
        or ""
    ).strip()


_REDIS_DIAGNOSTIC_LAST = ""
_REDIS_DIAGNOSTIC_LOCK = threading.Lock()


def _redis_client():
    global _REDIS_DIAGNOSTIC_LAST
    url = _redis_url()
    if redis_lib is None:
        reason = "redis_package_unavailable"
        client = None
    elif not url:
        reason = "redis_url_missing"
        client = None
    else:
        try:
            client = redis_lib.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=3.0,
                socket_timeout=3.0,
                health_check_interval=30,
            )
            client.ping()
            reason = "connected"
        except Exception as exc:
            # Only a bounded exception CLASS is logged: no URL, host, tokens,
            # credentials, exception string, or connection parameters.
            reason = "redis_" + type(exc).__name__
            client = None
    with _REDIS_DIAGNOSTIC_LOCK:
        if reason != _REDIS_DIAGNOSTIC_LAST:
            print(f"NIJA_LEAD_CRM_REDIS_DIAGNOSTIC status={reason}", flush=True)
            _REDIS_DIAGNOSTIC_LAST = reason
    return client


def _redis_event_key(event_key: str) -> str:
    return f"{_REDIS_PREFIX}:event:{event_key}"


def _redis_enqueue(client, canonical: dict[str, str], event_key: str) -> bool:
    key = _redis_event_key(event_key)
    now = _now_iso()
    # hsetnx preserves the first canonical identity while zadd makes the work
    # discoverable after process restarts. No marketing consent is stored here.
    created = client.hsetnx(key, "email", canonical["email"].lower())
    if created:
        client.hset(key, mapping={
            "name": canonical.get("name", "")[:200],
            "state": "pending",
            "attempts": "0",
            "next_attempt_at": "0",
            "last_error_code": "",
            "updated_at": now,
        })
    state = client.hget(key, "state")
    if state != "synced":
        score_raw = client.hget(key, "next_attempt_at") or "0"
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        client.zadd(f"{_REDIS_PREFIX}:pending", {event_key: score})
    return True


def _bootstrap_redis_from_sqlite(client) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    try:
        with _connect() as conn:
            _prepare(conn)
            rows = conn.execute(
                """SELECT event_key, email, name FROM website_leads
                   WHERE received_at >= ? ORDER BY received_at""",
                (cutoff,),
            ).fetchall()
    except sqlite3.Error:
        return 0
    count = 0
    for row in rows:
        try:
            _redis_enqueue(client, {"email": row["email"], "name": row["name"]}, row["event_key"])
            count += 1
        except Exception:
            break
    return count


def enqueue_lead(canonical: dict[str, str], event_key: str) -> bool:
    """Queue after the website lead has been persisted; never delay HTTP receipt.

    Redis is the durable production outbox because NIJA's Render Key Value
    service has persistence enabled. SQLite remains a local fallback/mirror.
    """
    durable = False
    client = _redis_client()
    if client is not None:
        try:
            durable = _redis_enqueue(client, canonical, event_key)
        except Exception:
            durable = False

    local = False
    try:
        with _WORKER_LOCK, _connect() as conn:
            _prepare(conn)
            conn.execute(
                """INSERT OR IGNORE INTO website_lead_crm_sync
                   (event_key, email, name, updated_at) VALUES (?, ?, ?, ?)""",
                (event_key, canonical["email"].lower(), canonical.get("name", "")[:200], _now_iso()),
            )
            conn.commit()
            local = True
    except (sqlite3.Error, OSError):
        local = False

    if not durable and not local:
        return False
    start_worker()
    _WAKE.set()
    return True


def _contact(name: str, email: str) -> dict[str, Any]:
    first, _, last = (name or "").strip().partition(" ")
    return {
        "first_name": first[:100] or "NIJA",
        "last_name": last[:100],
        "email": email,
    }


def _deliver_batch(rows: list[dict[str, Any]], key: str) -> set[str]:
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        email = str(row["email"]).strip().lower()
        if email and email not in unique:
            unique[email] = _contact(str(row["name"]), email)
    body = json.dumps({
        "contacts": list(unique.values()),
        "run_dedupe": True,
        "append_label_names": ["NIJA Website Leads"],
    }, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        _APOLLO_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Api-Key": key,
            "User-Agent": "NIJA-Lead-CRM-Recovery/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=12.0) as response:
        if int(response.status) not in (200, 201):
            raise OSError("unexpected_http_status")
        payload = json.loads(response.read(500000).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("invalid_apollo_response")
    acknowledged: set[str] = set()
    for field in ("created_contacts", "existing_contacts"):
        data = payload.get(field, [])
        if not isinstance(data, list):
            raise ValueError("invalid_apollo_response")
        for contact in data:
            if isinstance(contact, dict) and isinstance(contact.get("email"), str) and contact.get("id"):
                acknowledged.add(contact["email"].strip().lower())
    return acknowledged & set(unique)


def _sync_pending_redis(client, key: str, max_batch: int) -> dict[str, int]:
    counts = {"attempted": 0, "synced": 0, "retry": 0, "waiting": 0}
    now = time.time()
    ids = client.zrangebyscore(
        f"{_REDIS_PREFIX}:pending", 0, now, start=0,
        num=min(max(1, int(max_batch)), 100),
    )
    rows: list[dict[str, Any]] = []
    for event_key in ids:
        record = client.hgetall(_redis_event_key(event_key)) or {}
        if not record.get("email"):
            client.zrem(f"{_REDIS_PREFIX}:pending", event_key)
            continue
        rows.append({
            "event_key": event_key,
            "email": record["email"],
            "name": record.get("name", ""),
            "attempts": int(record.get("attempts", "0") or "0"),
        })
    if not rows:
        return counts
    counts["attempted"] = len(rows)
    error_code = ""
    try:
        confirmed = _deliver_batch(rows, key)
    except urllib.error.HTTPError as exc:
        confirmed = set()
        error_code = f"HTTP_{int(exc.code)}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        confirmed = set()
        error_code = type(exc).__name__
    except (ValueError, UnicodeError) as exc:
        confirmed = set()
        error_code = type(exc).__name__

    for row in rows:
        event_key = row["event_key"]
        rkey = _redis_event_key(event_key)
        if row["email"].lower() in confirmed:
            client.hset(rkey, mapping={
                "state": "synced",
                "last_error_code": "",
                "updated_at": _now_iso(),
            })
            client.zrem(f"{_REDIS_PREFIX}:pending", event_key)
            client.expire(rkey, 90 * 24 * 3600)
            counts["synced"] += 1
        else:
            attempt = int(row["attempts"]) + 1
            wait_seconds = min(3600, 30 * (2 ** min(attempt - 1, 7)))
            next_at = now + wait_seconds
            client.hset(rkey, mapping={
                "attempts": str(attempt),
                "next_attempt_at": str(next_at),
                "last_error_code": error_code or "not_acknowledged",
                "updated_at": _now_iso(),
            })
            client.zadd(f"{_REDIS_PREFIX}:pending", {event_key: next_at})
            counts["retry"] += 1
    return counts


def _sync_pending_sqlite(key: str, max_batch: int) -> dict[str, int]:
    counts = {"attempted": 0, "synced": 0, "retry": 0, "waiting": 0}
    with _connect() as conn:
        _prepare(conn)
        now = time.time()
        selected = conn.execute(
            """SELECT event_key, email, name, attempts
               FROM website_lead_crm_sync
               WHERE state='pending' AND next_attempt_at <= ?
               ORDER BY next_attempt_at, updated_at LIMIT ?""",
            (now, min(max(1, int(max_batch)), 100)),
        ).fetchall()
        rows = [dict(row) for row in selected]
    if not rows:
        return counts
    counts["attempted"] = len(rows)
    error_code = ""
    try:
        confirmed = _deliver_batch(rows, key)
    except urllib.error.HTTPError as exc:
        confirmed = set()
        error_code = f"HTTP_{int(exc.code)}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        confirmed = set()
        error_code = type(exc).__name__
    except (ValueError, UnicodeError) as exc:
        confirmed = set()
        error_code = type(exc).__name__

    with _connect() as conn:
        for row in rows:
            if row["email"].lower() in confirmed:
                conn.execute(
                    """UPDATE website_lead_crm_sync SET state='synced',
                       last_error_code='', updated_at=? WHERE event_key=?""",
                    (_now_iso(), row["event_key"]),
                )
                counts["synced"] += 1
            else:
                attempt = int(row["attempts"]) + 1
                wait_seconds = min(3600, 30 * (2 ** min(attempt - 1, 7)))
                conn.execute(
                    """UPDATE website_lead_crm_sync SET attempts=?,
                       next_attempt_at=?, last_error_code=?, updated_at=?
                       WHERE event_key=?""",
                    (attempt, now + wait_seconds,
                     error_code or "not_acknowledged", _now_iso(), row["event_key"]),
                )
                counts["retry"] += 1
        conn.commit()
    return counts


def sync_pending(max_batch: int = 20) -> dict[str, int]:
    """Reconcile pending lead contacts to Apollo with durable Redis first.

    Does not mutate promotional sequences or re-write existing Apollo contacts.
    """
    counts = {"attempted": 0, "synced": 0, "retry": 0, "waiting": 0}
    if not _enabled():
        return counts
    key = str(os.getenv("APOLLO_API_KEY", "")).strip()
    if not key:
        counts["waiting"] = 1
        return counts

    with _DELIVERY_LOCK:
        client = _redis_client()
        if client is not None:
            try:
                return _sync_pending_redis(client, key, max_batch)
            except Exception:
                # Fail over to the local mirror; never drop the intake path.
                pass
        return _sync_pending_sqlite(key, max_batch)


def _worker_loop() -> None:
    while True:
        try:
            result = sync_pending()
            if result["attempted"]:
                print(
                    "NIJA_LEAD_APOLLO_RECOVERY "
                    f"attempted={result['attempted']} synced={result['synced']} "
                    f"retry={result['retry']} no_marketing_sent=true",
                    flush=True,
                )
        except Exception as exc:
            # Never log email addresses or tokens in process logs.
            print(f"NIJA_LEAD_APOLLO_RECOVERY error={type(exc).__name__}", flush=True)
        _WAKE.wait(timeout=30)
        _WAKE.clear()


def start_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        client = _redis_client()
        if client is not None:
            try:
                backfilled = _bootstrap_redis_from_sqlite(client)
                print(
                    f"NIJA_LEAD_CRM_DURABLE backend=redis backfilled={backfilled} "
                    "persistent=true no_marketing_sent=true",
                    flush=True,
                )
            except Exception as exc:
                print(f"NIJA_LEAD_CRM_DURABLE backend=sqlite reason={type(exc).__name__}", flush=True)
        else:
            print("NIJA_LEAD_CRM_DURABLE backend=sqlite persistent=false", flush=True)
        _WORKER_STARTED = True
        threading.Thread(target=_worker_loop, name="nija-lead-apollo-recovery", daemon=True).start()
