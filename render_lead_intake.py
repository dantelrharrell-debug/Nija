"""Canonical website-lead intake for NIJA's Render front door.

The IONOS/website form layer can emit payloads where ``formName`` is a nested
object and email addresses are rendered as Markdown ``[x](mailto:x)`` links.
This module accepts those shapes, normalizes them into a stable schema, stores a
deduplicated local record, and can forward the canonical payload to a configured
server-side webhook without leaking provider secrets.

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
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_LEAD_PATH = "/api/leads/intake"
_MAX_BODY_BYTES = 65536
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


def _normalize_timestamp(value: object) -> str:
    text = _clean_text(value, max_length=128)
    if not text:
        return _utcnow()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _nested_form(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("formName", "form_name", "form", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


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
    raw_submitted_at: object = (
        nested.get("submitted_at")
        or nested.get("submissionDate")
        or payload.get("submitted_at")
        or payload.get("submissionDate")
        or payload.get("submission_date")
        or ""
    )

    form_name = _clean_text(raw_form_name, max_length=160)
    name = _clean_text(raw_name, max_length=200)
    email = normalize_email(raw_email)
    submitted_at = _normalize_timestamp(raw_submitted_at)

    if not email:
        raise ValueError("Lead email is missing or invalid")
    if not form_name:
        form_name = "Website Lead"

    return {
        "form_name": form_name,
        "name": name,
        "email": email,
        "submitted_at": submitted_at,
    }


def _db_path() -> pathlib.Path:
    configured = str(
        os.getenv("NIJA_LEAD_DB_PATH")
        or os.getenv("NIJA_OUTREACH_DB_PATH")
        or "/app/data/nija_outreach.sqlite3"
    ).strip()
    return pathlib.Path(configured)


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


def record_lead(payload: dict[str, Any]) -> tuple[dict[str, str], str, bool]:
    canonical = normalize_lead_payload(payload)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    identity = "|".join(
        (
            canonical["form_name"].casefold(),
            canonical["email"].casefold(),
            canonical["submitted_at"],
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
    """Handle NIJA website lead intake; return whether the request path matched."""
    path = urllib.parse.urlsplit(str(getattr(handler, "path", "") or "")).path
    if path != _LEAD_PATH:
        return False

    authorized, status_code, detail = _authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True

    try:
        payload = _read_json(handler)
        canonical, event_key, duplicate = record_lead(payload)
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
        return True
    except OSError:
        _send_json(handler, 503, {"error": "Lead store unavailable"})
        return True

    forwarded = False
    forward_error = False
    try:
        forwarded = _forward(canonical)
    except OSError:
        # The lead is already safely persisted. Keep the submission successful so
        # an external webhook outage cannot destroy the source lead.
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
        },
    )
    return True
