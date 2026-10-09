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
from datetime import datetime, timedelta, timezone
from typing import Any

_APOLLO_URL = "https://api.apollo.io/api/v1/contacts/bulk_create"
_WORKER_LOCK = threading.RLock()
_DELIVERY_LOCK = threading.RLock()
_WORKER_STARTED = False
_WAKE = threading.Event()


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


def enqueue_lead(canonical: dict[str, str], event_key: str) -> bool:
    """Queue after the website lead has been persisted; never delay HTTP receipt."""
    with _WORKER_LOCK, _connect() as conn:
        _prepare(conn)
        conn.execute(
            """INSERT OR IGNORE INTO website_lead_crm_sync
               (event_key, email, name, updated_at) VALUES (?, ?, ?, ?)""",
            (event_key, canonical["email"].lower(), canonical.get("name", "")[:200], _now_iso()),
        )
        conn.commit()
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


def sync_pending(max_batch: int = 20) -> dict[str, int]:
    """Reconcile pending lead contacts to Apollo, retrying bounded failures.

    Does not mutate promotional sequences or re-write existing Apollo contacts.
    """
    counts = {"attempted": 0, "synced": 0, "retry": 0, "waiting": 0}
    if not _enabled():
        return counts
    key = str(os.getenv("APOLLO_API_KEY", "")).strip()
    if not key:
        counts["waiting"] = 1
        return counts

    # Hold this lock across I/O to prohibit two workers processing the same rows,
    # but do not acquire the writer lock used by live HTTP submissions.
    with _DELIVERY_LOCK:
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
                    # Retry indefinitely with a bounded interval; never discard a lead.
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
        _WORKER_STARTED = True
        threading.Thread(target=_worker_loop, name="nija-lead-apollo-recovery", daemon=True).start()
