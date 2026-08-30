"""Stdlib-only persistence helpers for NIJA's Render outreach front door.

This store is intentionally isolated from the trading runtime. It records JustCall
webhook deliveries, reconciles call state without assuming event order, tracks
local DNC/suppression entries, and keeps enough state for the trusted NIJA
Calling System to synchronize results into its primary CRM.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_DB_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> pathlib.Path:
    configured = os.getenv("NIJA_OUTREACH_DB_PATH", "").strip()
    return pathlib.Path(configured or "/app/data/nija_outreach.sqlite3")


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
            CREATE TABLE IF NOT EXISTS justcall_webhook_events (
                event_key TEXT PRIMARY KEY,
                request_id TEXT,
                event_type TEXT NOT NULL,
                call_key TEXT,
                received_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_justcall_events_call_key
                ON justcall_webhook_events(call_key, received_at);

            CREATE TABLE IF NOT EXISTS outreach_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_key TEXT UNIQUE,
                provider_call_id TEXT,
                call_sid TEXT,
                phone_key TEXT,
                contact_number TEXT,
                record_id TEXT,
                campaign TEXT,
                latest_event_type TEXT,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_outreach_calls_phone
                ON outreach_calls(phone_key, updated_at);

            CREATE TABLE IF NOT EXISTS outreach_suppressions (
                phone_key TEXT PRIMARY KEY,
                contact_number TEXT NOT NULL,
                reason TEXT NOT NULL,
                source TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.commit()
        _SCHEMA_READY.add(key)


def phone_key(number: str) -> str:
    return "".join(ch for ch in str(number or "") if ch.isdigit())


def _find_scalar(value: object, keys: tuple[str, ...]) -> Optional[str]:
    if isinstance(value, dict):
        for key in keys:
            if key in value and value[key] not in (None, ""):
                return str(value[key])
        for item in value.values():
            found = _find_scalar(item, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_scalar(item, keys)
            if found:
                return found
    return None


def _call_identity(data: object) -> tuple[str, str, str]:
    call_sid = _find_scalar(data, ("call_sid", "callSid")) or ""
    provider_id = _find_scalar(data, ("call_id", "callId", "id")) or ""
    if call_sid:
        return f"sid:{call_sid}", provider_id, call_sid
    if provider_id:
        return f"id:{provider_id}", provider_id, call_sid
    return "", provider_id, call_sid


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = value
    return base


def _derive_state(events: dict[str, Any]) -> dict[str, Any]:
    derived: dict[str, Any] = {}
    for event_type in ("call.initiated", "call.answered", "call.completed"):
        event_data = events.get(event_type)
        if isinstance(event_data, dict):
            derived = _deep_merge(derived, dict(event_data))

    updates = events.get("call.updated")
    if isinstance(updates, list):
        for update in updates:
            if isinstance(update, dict):
                derived = _deep_merge(derived, dict(update))

    ai_report = events.get("jc.call_ai_generated")
    if isinstance(ai_report, dict):
        derived = _deep_merge(derived, dict(ai_report))

    voice_agent = events.get("call.ai_voice_agent")
    if isinstance(voice_agent, dict):
        derived["voice_agent_data"] = voice_agent

    for event_type in ("call.missed", "call.voicemail"):
        event_data = events.get(event_type)
        if isinstance(event_data, dict):
            derived = _deep_merge(derived, dict(event_data))

    return derived


def _load_state(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {"events": {}, "derived": {}}
    try:
        state = json.loads(str(row["state_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    if not isinstance(state.get("events"), dict):
        state["events"] = {}
    if not isinstance(state.get("derived"), dict):
        state["derived"] = {}
    return state


def record_outbound_submission(
    *,
    contact_number: str,
    record_id: str,
    campaign: str,
    provider_payload: dict[str, Any],
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    call_key, provider_id, call_sid = _call_identity(provider_payload)
    if not call_key:
        call_key = f"submission:{uuid.uuid4().hex}"
    now = _utcnow()
    state = {
        "events": {},
        "derived": {},
        "submission": {
            "record_id": record_id,
            "campaign": campaign,
            "contact_number": contact_number,
            "test_mode": bool(request_payload.get("test_mode")),
            "submitted_at": now,
            "provider_response": provider_payload,
        },
    }
    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO outreach_calls (
                call_key, provider_call_id, call_sid, phone_key, contact_number,
                record_id, campaign, latest_event_type, state_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(call_key) DO UPDATE SET
                provider_call_id=excluded.provider_call_id,
                call_sid=excluded.call_sid,
                phone_key=excluded.phone_key,
                contact_number=excluded.contact_number,
                record_id=COALESCE(NULLIF(excluded.record_id, ''), outreach_calls.record_id),
                campaign=COALESCE(NULLIF(excluded.campaign, ''), outreach_calls.campaign),
                state_json=excluded.state_json,
                updated_at=excluded.updated_at
            """,
            (
                call_key,
                provider_id,
                call_sid,
                phone_key(contact_number),
                contact_number,
                record_id,
                campaign,
                "submitted",
                json.dumps(state, separators=(",", ":"), ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return {"call_key": call_key, "recorded": True}


def record_webhook_event(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = str(payload.get("request_id", "") or "").strip()
    event_type = str(payload.get("type", "") or "").strip()
    data = payload.get("data")
    metadata = payload.get("metadata")
    if not event_type:
        raise ValueError("Webhook event type is missing")
    if not isinstance(data, dict):
        data = {}
    if not isinstance(metadata, dict):
        metadata = {}

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_key = request_id or hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    call_key, provider_id, call_sid = _call_identity(data)
    contact_number = str(data.get("contact_number", "") or "")
    pkey = phone_key(contact_number)
    now = _utcnow()

    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        existing_event = connection.execute(
            "SELECT 1 FROM justcall_webhook_events WHERE event_key = ?",
            (event_key,),
        ).fetchone()
        if existing_event is not None:
            return {
                "accepted": True,
                "duplicate": True,
                "event_type": event_type,
                "call_key": call_key,
            }

        row: Optional[sqlite3.Row] = None
        if call_key:
            row = connection.execute(
                "SELECT * FROM outreach_calls WHERE call_key = ?",
                (call_key,),
            ).fetchone()
        if row is None and pkey:
            row = connection.execute(
                "SELECT * FROM outreach_calls WHERE phone_key = ? ORDER BY id DESC LIMIT 1",
                (pkey,),
            ).fetchone()

        state = _load_state(row)
        events = state["events"]
        if event_type == "call.updated":
            updates = events.get(event_type)
            if not isinstance(updates, list):
                updates = []
            updates.append(data)
            events[event_type] = updates[-50:]
        else:
            events[event_type] = data
        state["metadata"] = metadata
        state["last_request_id"] = request_id
        state["last_event_type"] = event_type
        state["last_received_at"] = now
        state["derived"] = _derive_state(events)

        connection.execute(
            """
            INSERT INTO justcall_webhook_events (
                event_key, request_id, event_type, call_key, received_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_key, request_id, event_type, call_key, now, canonical),
        )

        serialized = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
        if row is None:
            effective_call_key = call_key or f"event:{event_key}"
            connection.execute(
                """
                INSERT INTO outreach_calls (
                    call_key, provider_call_id, call_sid, phone_key, contact_number,
                    record_id, campaign, latest_event_type, state_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, '', '', ?, ?, ?, ?)
                """,
                (
                    effective_call_key,
                    provider_id,
                    call_sid,
                    pkey,
                    contact_number,
                    event_type,
                    serialized,
                    now,
                    now,
                ),
            )
            call_key = effective_call_key
        else:
            current_key = str(row["call_key"] or "")
            effective_call_key = call_key or current_key
            # Replace a temporary submission key once JustCall supplies a stable ID/SID.
            if call_key and current_key.startswith("submission:"):
                conflicting = connection.execute(
                    "SELECT id FROM outreach_calls WHERE call_key = ? AND id != ?",
                    (call_key, row["id"]),
                ).fetchone()
                if conflicting is None:
                    current_key = call_key
            connection.execute(
                """
                UPDATE outreach_calls SET
                    call_key=?,
                    provider_call_id=COALESCE(NULLIF(?, ''), provider_call_id),
                    call_sid=COALESCE(NULLIF(?, ''), call_sid),
                    phone_key=COALESCE(NULLIF(?, ''), phone_key),
                    contact_number=COALESCE(NULLIF(?, ''), contact_number),
                    latest_event_type=?,
                    state_json=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    current_key,
                    provider_id,
                    call_sid,
                    pkey,
                    contact_number,
                    event_type,
                    serialized,
                    now,
                    row["id"],
                ),
            )
            call_key = effective_call_key

        connection.commit()

    return {
        "accepted": True,
        "duplicate": False,
        "event_type": event_type,
        "call_key": call_key,
    }


def set_suppression(*, contact_number: str, reason: str, source: str, active: bool) -> None:
    pkey = phone_key(contact_number)
    if not pkey:
        raise ValueError("A valid contact number is required")
    now = _utcnow()
    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO outreach_suppressions (
                phone_key, contact_number, reason, source, active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(phone_key) DO UPDATE SET
                contact_number=excluded.contact_number,
                reason=excluded.reason,
                source=excluded.source,
                active=excluded.active,
                updated_at=excluded.updated_at
            """,
            (pkey, contact_number, reason, source, 1 if active else 0, now, now),
        )
        connection.commit()


def is_suppressed(contact_number: str) -> bool:
    pkey = phone_key(contact_number)
    if not pkey:
        return True
    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT active FROM outreach_suppressions WHERE phone_key = ?",
            (pkey,),
        ).fetchone()
    return bool(row and int(row["active"]) == 1)


def webhook_status() -> dict[str, Any]:
    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        totals = connection.execute(
            "SELECT COUNT(*) AS event_count, MAX(received_at) AS last_received_at FROM justcall_webhook_events"
        ).fetchone()
        last = connection.execute(
            "SELECT event_type FROM justcall_webhook_events ORDER BY received_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        call_total = connection.execute("SELECT COUNT(*) AS call_count FROM outreach_calls").fetchone()
    return {
        "receiver_ready": True,
        "event_count": int(totals["event_count"] or 0),
        "call_count": int(call_total["call_count"] or 0),
        "last_received_at": totals["last_received_at"],
        "last_event_type": last["event_type"] if last else None,
    }


def recent_calls(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _DB_LOCK, _connect() as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT call_key, provider_call_id, call_sid, contact_number, record_id,
                   campaign, latest_event_type, state_json, created_at, updated_at
            FROM outreach_calls
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        state = _load_state(row)
        result.append(
            {
                "call_key": row["call_key"],
                "provider_call_id": row["provider_call_id"],
                "call_sid": row["call_sid"],
                "contact_number": row["contact_number"],
                "record_id": row["record_id"],
                "campaign": row["campaign"],
                "latest_event_type": row["latest_event_type"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "state": state,
            }
        )
    return result
