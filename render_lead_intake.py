"""Canonical website-lead intake for NIJA's Render front door.

The IONOS/website form layer can emit payloads where ``formName`` is a nested
object and email addresses are rendered as Markdown ``[x](mailto:x)`` links.
This module accepts those shapes, normalizes them into a stable schema, stores a
deduplicated local record, and can forward the canonical payload to a configured
server-side webhook without leaking provider secrets.

It also exposes a narrow authenticated account-existence check for trusted
server-to-server automation. The lookup never accepts passwords and never
returns password hashes or broker credentials.

The module is stdlib-only because ``render_liveness_server.py`` runs under
``python -S`` during early Render startup.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_LEAD_PATH = "/api/leads/intake"
_ACCOUNT_CHECK_PATH = "/api/leads/account-check"
_MAX_BODY_BYTES = 65536
_FORWARD_LOCK_LEASE_SECONDS = 120
_FORWARD_RETRY_BACKOFF_SECONDS = 60
_DB_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()
_EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+", re.IGNORECASE)
_MARKDOWN_MAILTO_RE = re.compile(r"^\s*\[([^\]]+)\]\(\s*mailto:([^\s)]+)\s*\)\s*$", re.IGNORECASE)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clean_text(value: object, *, max_length: int) -> str:
    text = html.unescape(str(value or "")).replace("\x00", " ")
    return " ".join(text.split())[:max_length]


def _valid_email(candidate: str) -> bool:
    if not candidate or len(candidate) > 254 or candidate.count("@") != 1:
        return False
    return _EMAIL_RE.fullmatch(candidate) is not None


def normalize_email(value: object) -> str:
    """Return a lowercase raw email address from plain/mailto/Markdown input."""
    text = _clean_text(value, max_length=1024)
    if not text:
        return ""

    markdown = _MARKDOWN_MAILTO_RE.fullmatch(text)
    if markdown:
        for candidate in (markdown.group(2), markdown.group(1)):
            cleaned = urllib.parse.unquote(candidate).strip().strip("<>\"'").lower()
            if _valid_email(cleaned):
                return cleaned

    if text.lower().startswith("mailto:"):
        text = text[7:]
    match = _EMAIL_RE.search(urllib.parse.unquote(text))
    if not match:
        return ""
    candidate = match.group(0).strip().lower()
    return candidate if _valid_email(candidate) else ""


def _parse_timestamp(value: object) -> str | None:
    """Return a stable ISO timestamp only when the source supplied one."""
    text = _clean_text(value, max_length=128)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_timestamp(value: object) -> str:
    return _parse_timestamp(value) or _utcnow()


def _nested_form(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("formName", "form_name", "form", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _raw_submission_timestamp(payload: dict[str, Any]) -> object:
    nested = _nested_form(payload)
    return (
        nested.get("submitted_at")
        or nested.get("submissionDate")
        or payload.get("submitted_at")
        or payload.get("submissionDate")
        or payload.get("submission_date")
        or ""
    )


def _stable_event_fallback(payload: dict[str, Any], serialized: str) -> str:
    """Provide a deterministic replay key when the upstream timestamp is missing.

    Source IDs are preferred. With neither a source ID nor a usable timestamp,
    identical JSON is treated as one event (fail closed against double sends).
    """
    nested = _nested_form(payload)
    for key in ("event_id", "eventId", "submission_id", "submissionId"):
        value = nested.get(key) or payload.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            cleaned = _clean_text(value, max_length=160)
            if cleaned:
                return "upstream:" + cleaned
    return "payload-sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def normalize_lead_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Flatten website-form payload variants into NIJA's canonical lead schema."""
    if not isinstance(payload, dict):
        raise ValueError("Lead payload must be a JSON object")

    nested = _nested_form(payload)
    raw_form_name: object = (
        nested.get("form_name")
        or nested.get("formName")
        or payload.get("form_name")
        or (payload.get("formName") if isinstance(payload.get("formName"), str) else "")
        or "Website Lead"
    )
    raw_name: object = (
        nested.get("name")
        or nested.get("full_name")
        or payload.get("name")
        or payload.get("full_name")
        or ""
    )
    raw_email: object = (
        nested.get("email")
        or nested.get("email_address")
        or payload.get("email")
        or payload.get("email_address")
        or ""
    )
    raw_submitted_at: object = _raw_submission_timestamp(payload)

    form_name = _clean_text(raw_form_name, max_length=160)
    name = _clean_text(raw_name, max_length=200)
    email = normalize_email(raw_email)
    submitted_at = _normalize_timestamp(raw_submitted_at)

    if not email:
        raise ValueError("Lead email is missing or invalid")
    if not form_name:
        form_name = "Website Lead"

    raw_phone = (
        nested.get("Phone Number")
        or nested.get("phone")
        or nested.get("phone_number")
        or payload.get("Phone Number")
        or payload.get("phone")
        or payload.get("phone_number")
        or ""
    )
    raw_consent = (
        nested.get("consent")
        if "consent" in nested
        else payload.get("consent", "")
    )
    phone = _clean_text(raw_phone, max_length=80)
    consent_text = _clean_text(raw_consent, max_length=32).casefold()
    communications_consent = consent_text in {
        "1", "true", "yes", "on", "checked", "agree", "agreed"
    }

    return {
        "form_name": form_name,
        "name": name,
        "email": email,
        "submitted_at": submitted_at,
        "phone": phone,
        "communications_consent": "true" if communications_consent else "false",
    }


def _db_path() -> pathlib.Path:
    configured = str(
        os.getenv("NIJA_LEAD_DB_PATH")
        or os.getenv("NIJA_OUTREACH_DB_PATH")
        or "/app/data/nija_outreach.sqlite3"
    ).strip()
    return pathlib.Path(configured)


def _user_db_path() -> pathlib.Path:
    configured = str(os.getenv("NIJA_USER_DB_PATH") or "users.db").strip()
    return pathlib.Path(configured).expanduser()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    key = str(_db_path())
    with _DB_LOCK:
        if key in _SCHEMA_READY:
            return
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS website_leads (
                event_key TEXT PRIMARY KEY,
                form_name TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                source_payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_website_leads_email
                ON website_leads(email, submitted_at);
            """
        )
        connection.commit()
        _SCHEMA_READY.add(key)


def _forward_key(payload: dict[str, Any], canonical: dict[str, str], event_key: str) -> str:
    """Form-agnostic key so one submission relabelled by two forms forwards once.

    Only a stable source timestamp is trusted; without one, fall back to the
    per-form event key rather than risk suppressing distinct submissions.
    """
    stable_timestamp = _parse_timestamp(_raw_submission_timestamp(payload))
    if not stable_timestamp:
        return event_key
    identity = f"submission|{canonical['email'].casefold()}|{stable_timestamp}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def record_lead(payload: dict[str, Any]) -> tuple[dict[str, str], str, bool]:
    canonical = normalize_lead_payload(payload)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    # Canonical submitted_at is the current time if the source omits it,
    # so never use that dynamic fallback in the deduplication key.
    stable_timestamp = _parse_timestamp(_raw_submission_timestamp(payload))
    source_reference = stable_timestamp or _stable_event_fallback(payload, raw)
    identity = "|".join(
        (
            canonical["form_name"].casefold(),
            canonical["email"].casefold(),
            source_reference,
        )
    )
    event_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    received_at = _utcnow()

    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO website_leads (
                event_key, form_name, name, email, submitted_at, received_at, source_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                canonical["form_name"],
                canonical["name"],
                canonical["email"],
                canonical["submitted_at"],
                received_at,
                raw,
            ),
        )
        connection.commit()
        duplicate = cursor.rowcount == 0
    return canonical, event_key, duplicate


def _forward_db_path() -> pathlib.Path:
    """Keep notification history on Render's mounted disk across bot redeploys.

    NIJA's live Render bot mounts persistent storage at /data, while /app/data
    may be replaced when a new container is deployed. A test/operator override
    permits an isolated location without affecting the trade ledger database.
    """
    override = str(os.getenv("NIJA_LEAD_FORWARD_DB_PATH") or "").strip()
    if override:
        return pathlib.Path(override)
    mount = pathlib.Path("/data")
    return mount / "nija_lead_forwarding.sqlite3" if mount.is_dir() else _db_path()


def _forward_connect() -> sqlite3.Connection:
    path = _forward_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS website_lead_forwarding (
            event_key TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            lease_until REAL NOT NULL DEFAULT 0,
            lease_token TEXT NOT NULL DEFAULT ''
        )"""
    )
    # Preserve existing durable records; upgrade a pre-fencing table in place.
    # BEGIN IMMEDIATE serializes the migration between service processes.
    with _DB_LOCK:
        conn.execute("BEGIN IMMEDIATE")
        try:
            columns = {row["name"] for row in conn.execute(
                "PRAGMA table_info(website_lead_forwarding)"
            )}
            if "lease_token" not in columns:
                conn.execute(
                    "ALTER TABLE website_lead_forwarding "
                    "ADD COLUMN lease_token TEXT NOT NULL DEFAULT ''"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            conn.close()
            raise
    return conn


def _claim_forward(event_key: str, *, legacy_event_key: str | None = None) -> str | None:
    """Claim a uniquely fenced lease; stale senders cannot finish a newer claim.

    A provider can still receive a duplicate after a network-ambiguous failure;
    the lease protects local state and confirmed outcomes, not exactly-once email.
    """
    now = time.time()
    token = secrets.token_hex(16)
    with _DB_LOCK, _forward_connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            if legacy_event_key and legacy_event_key != event_key:
                legacy_sent = connection.execute(
                    "SELECT 1 FROM website_lead_forwarding WHERE event_key=? AND state='sent'",
                    (legacy_event_key,),
                ).fetchone()
                if legacy_sent:
                    migrated = connection.execute(
                        "UPDATE website_lead_forwarding "
                        "SET state='sent', lease_until=0, lease_token='' WHERE event_key=?",
                        (event_key,),
                    )
                    if migrated.rowcount == 0:
                        connection.execute(
                            "INSERT INTO website_lead_forwarding "
                            "(event_key, state, lease_until, lease_token) VALUES (?, 'sent', 0, '')",
                            (event_key,),
                        )
                    connection.commit()
                    return None

            connection.execute(
                "INSERT OR IGNORE INTO website_lead_forwarding (event_key, state, lease_until) "
                "VALUES (?, 'pending', 0)",
                (event_key,),
            )
            claimed = connection.execute(
                """UPDATE website_lead_forwarding
                   SET state='sending', lease_until=?, lease_token=?
                   WHERE event_key=?
                     AND state IN ('pending', 'sending')
                     AND lease_until <= ?""",
                (now + _FORWARD_LOCK_LEASE_SECONDS, token, event_key, now),
            )
            connection.commit()
            return token if claimed.rowcount == 1 else None
        except Exception:
            connection.rollback()
            raise


def _finish_forward(event_key: str, *, claim_token: str, sent: bool) -> bool:
    """Only the current lease holder can record completion or retry state."""
    retry_at = 0 if sent else time.time() + _FORWARD_RETRY_BACKOFF_SECONDS
    with _DB_LOCK, _forward_connect() as connection:
        finished = connection.execute(
            """UPDATE website_lead_forwarding
               SET state=?, lease_until=?, lease_token=''
               WHERE event_key=? AND state='sending' AND lease_token=?""",
            ("sent" if sent else "pending", retry_at, event_key, claim_token),
        )
        connection.commit()
        return finished.rowcount == 1


def _lookup_user_by_email(email: str) -> dict[str, Any]:
    """Return the minimum account state required by trusted lifecycle automation."""
    path = _user_db_path()
    if not path.is_file():
        raise OSError("NIJA user database is unavailable")

    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if table is None:
            raise OSError("NIJA users table is unavailable")
        row = connection.execute(
            """
            SELECT user_id, enabled, email_verified
            FROM users
            WHERE lower(email) = ?
            LIMIT 1
            """,
            (email.lower(),),
        ).fetchone()
        connection.close()
    except (sqlite3.Error, OSError) as exc:
        raise OSError("NIJA user lookup is unavailable") from exc

    if row is None:
        return {"exists": False}
    return {
        "exists": True,
        "user_id": str(row["user_id"] or ""),
        "enabled": bool(row["enabled"]),
        "email_verified": bool(row["email_verified"]),
    }


def _configured_token() -> str:
    return str(
        os.getenv("NIJA_LEAD_WEBHOOK_TOKEN")
        or os.getenv("NIJA_OUTREACH_SERVICE_TOKEN")
        or ""
    ).strip()


def _authorized(handler: Any) -> tuple[bool, int, str]:
    expected = _configured_token()
    if not expected:
        return False, 503, "Lead intake authentication is not configured"
    provided = str(handler.headers.get("X-NIJA-Lead-Token", "") or "").strip()
    if not provided:
        authorization = str(handler.headers.get("Authorization", "") or "").strip()
        if authorization.lower().startswith("bearer "):
            provided = authorization[7:].strip()
    if not provided or not hmac.compare_digest(expected, provided):
        return False, 401, "Unauthorized"
    return True, 200, "ok"


def _read_json(handler: Any) -> dict[str, Any]:
    raw_length = str(handler.headers.get("Content-Length", "0") or "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length <= 0:
        raise ValueError("Lead payload is empty")
    if length > _MAX_BODY_BYTES:
        raise ValueError("Lead payload is too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Lead payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Lead payload must be a JSON object")
    return payload


def _send_json(handler: Any, status_code: int, payload_obj: dict[str, Any]) -> None:
    body = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    try:
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        return


def _forward(canonical: dict[str, str]) -> bool:
    url = str(os.getenv("NIJA_LEAD_FORWARD_URL", "") or "").strip()
    if not url:
        return False
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise OSError("NIJA_LEAD_FORWARD_URL must be an HTTPS URL")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "NIJA-Lead-Intake/1.0",
    }
    bearer = str(os.getenv("NIJA_LEAD_FORWARD_BEARER", "") or "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(
        url,
        data=json.dumps(canonical, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            status = int(response.status)
            response.read(4096)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OSError("Unable to forward canonical lead payload") from exc
    if not 200 <= status < 300:
        raise OSError(f"Lead forwarder returned HTTP {status}")
    return True


def handle_lead_intake_post(handler: Any) -> bool:
    """Handle protected NIJA lead intake/account lookup POST routes."""
    path = urllib.parse.urlsplit(str(getattr(handler, "path", "") or "")).path
    if path not in {_LEAD_PATH, _ACCOUNT_CHECK_PATH}:
        return False

    authorized, status_code, detail = _authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True

    try:
        payload = _read_json(handler)
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
        return True

    if path == _ACCOUNT_CHECK_PATH:
        email = normalize_email(payload.get("email"))
        if not email:
            _send_json(handler, 422, {"error": "A valid email is required"})
            return True
        try:
            account = _lookup_user_by_email(email)
        except OSError:
            # Account lookup is enrichment for lead routing, not a prerequisite
            # for acknowledging and emailing a valid lead. Report degraded state
            # without fabricating whether the account exists, and avoid provider
            # retry loops that can duplicate downstream customer messages.
            _send_json(
                handler,
                200,
                {
                    "lookup_available": False,
                    "exists": None,
                    "email_normalized": True,
                    "warning": "NIJA account lookup is temporarily unavailable",
                },
            )
            return True
        response: dict[str, Any] = {
            "lookup_available": True,
            "email_normalized": True,
            **account,
        }
        _send_json(handler, 200, response)
        return True

    try:
        canonical, event_key, duplicate = record_lead(payload)
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
        return True
    except OSError:
        _send_json(handler, 503, {"error": "Lead store unavailable"})
        return True

    # Keep a retryable Apollo CRM mirror separate from the existing Zapier
    # delivery path. Successful submission must not depend on Apollo uptime.
    crm_queued = False
    crm_error = False
    try:
        from render_lead_crm_sync import enqueue_lead
        crm_queued = enqueue_lead(canonical, event_key)
    except Exception as exc:
        crm_error = True
        print(f"NIJA_LEAD_CRM_QUEUE_FAILED reason={type(exc).__name__}", flush=True)

    forwarded = False
    forward_error = False
    forward_key = _forward_key(payload, canonical, event_key)
    try:
        # A Zapier replay must not resend the same customer-facing notification.
        # Failed attempts may retry after a bounded delay without repeating a
        # previously confirmed successful forward.
        claim_token = _claim_forward(
            forward_key,
            legacy_event_key=event_key if forward_key != event_key else None,
        )
    except (OSError, sqlite3.Error):
        claim_token = None
        forward_error = True
    if claim_token:
        try:
            forwarded = _forward(canonical)
        except Exception as exc:
            # The canonical lead is already persisted; never expose webhook
            # URL, provider credentials, or payloads in error logs.
            forward_error = True
            print(f"NIJA_LEAD_FORWARD_FAILED reason={type(exc).__name__}", flush=True)
        finally:
            try:
                _finish_forward(forward_key, claim_token=claim_token, sent=forwarded)
            except (OSError, sqlite3.Error):
                forward_error = True

    _send_json(
        handler,
        200 if duplicate else 201,
        {
            "accepted": True,
            "duplicate": duplicate,
            "lead_id": event_key[:16],
            "form_name": canonical["form_name"],
            "email_normalized": True,
            "forwarded": forwarded,
            "forward_error": forward_error,
            "crm_queued": crm_queued,
            "crm_queue_error": crm_error,
        },
    )
    return True
