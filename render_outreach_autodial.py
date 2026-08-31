"""Durable, compliance-gated JustCall autodial queue for NIJA outreach.

Contacts may enter before every gate is ready. A provider call is submitted only
when stored compliance evidence is valid, the recipient's local calling window
is open, the NIJA daily quota has capacity, no active duplicate exists, local
suppression is clear, and a JustCall AI Voice Agent resolves.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from render_outreach_routes import (
    OutreachConfigurationError,
    OutreachProviderError,
    _E164_RE,
    _provider_request,
    _resolve_agent_id,
    _send_json,
    _service_authorized,
)
from render_outreach_store import is_suppressed, phone_key, record_outbound_submission

_QUEUE_LOCK = threading.RLock()
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_WORKER_LAST_CYCLE_AT: Optional[str] = None
_WORKER_LAST_SUBMISSION_AT: Optional[str] = None
_WORKER_LAST_ERROR: Optional[str] = None

_QUEUE_PATH = "/api/justcall/autodial-queue"
_STATUS_PATH = "/api/justcall/autodial-status"
_MAX_BODY_BYTES = 65536
_TERMINAL_CALL_EVENTS = {
    "call.completed",
    "call.missed",
    "call.voicemail",
    "jc.call_ai_generated",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bool(value: object) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS outreach_autodial_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            queue_key TEXT NOT NULL UNIQUE,
            record_id TEXT NOT NULL,
            contact_number TEXT NOT NULL,
            phone_key TEXT NOT NULL,
            campaign TEXT NOT NULL,
            call_stage TEXT NOT NULL,
            has_consent INTEGER NOT NULL DEFAULT 0,
            consent_record_id TEXT NOT NULL DEFAULT '',
            legal_basis TEXT NOT NULL DEFAULT '',
            dnc_clear INTEGER NOT NULL DEFAULT 0,
            dnc_checked_at TEXT NOT NULL DEFAULT '',
            suppression_clear INTEGER NOT NULL DEFAULT 0,
            contact_timezone TEXT NOT NULL DEFAULT '',
            campaign_enabled INTEGER NOT NULL DEFAULT 0,
            dynamic_variables_json TEXT NOT NULL DEFAULT '[]',
            ai_agent_id TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TEXT NOT NULL,
            lease_until TEXT,
            last_blocker TEXT,
            provider_call_key TEXT,
            submitted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_outreach_autodial_ready
            ON outreach_autodial_queue(state, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_outreach_autodial_phone
            ON outreach_autodial_queue(phone_key, updated_at);

        CREATE TABLE IF NOT EXISTS outreach_autodial_daily_quota (
            quota_date TEXT PRIMARY KEY,
            used_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        """
    )
    connection.commit()


def _queue_key(record_id: str, number: str, campaign: str, call_stage: str) -> str:
    material = "|".join((record_id.strip(), phone_key(number), campaign.strip(), call_stage.strip()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _read_json(handler: Any) -> dict[str, Any]:
    raw_length = str(handler.headers.get("Content-Length", "0") or "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length <= 0:
        return {}
    if length > _MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return payload


def _validate_timezone(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        return ""
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("contact_timezone must be a valid IANA timezone") from exc
    return value


def enqueue_candidate(body: dict[str, Any]) -> dict[str, Any]:
    """Create or refresh a candidate without inventing any compliance evidence."""
    record_id = str(body.get("record_id", "") or "").strip()
    number = str(body.get("contact_number", "") or "").strip()
    campaign = str(body.get("campaign", "") or "").strip() or "NIJA Outreach"
    call_stage = str(body.get("call_stage", "") or "").strip() or "initial"
    if not record_id:
        raise ValueError("record_id is required")
    if not _E164_RE.fullmatch(number):
        raise ValueError("contact_number must be valid E.164")
    if len(call_stage) > 100:
        raise ValueError("call_stage is too long")
    timezone_name = _validate_timezone(str(body.get("contact_timezone", "") or ""))
    variables = body.get("dynamic_variables") or []
    if not isinstance(variables, list) or len(variables) > 50:
        raise ValueError("dynamic_variables must be an array of at most 50 items")
    if _bool(body.get("test_mode")):
        raise ValueError("autodial queue accepts production campaign records only")

    key = _queue_key(record_id, number, campaign, call_stage)
    now = _iso(_utcnow())
    values = (
        key,
        record_id,
        number,
        phone_key(number),
        campaign,
        call_stage,
        1 if _bool(body.get("has_consent")) else 0,
        str(body.get("consent_record_id", "") or "").strip(),
        str(body.get("legal_basis", "") or "").strip(),
        1 if _bool(body.get("dnc_clear")) else 0,
        str(body.get("dnc_checked_at", "") or "").strip(),
        1 if _bool(body.get("suppression_clear")) else 0,
        timezone_name,
        1 if _bool(body.get("campaign_enabled")) else 0,
        json.dumps(variables, separators=(",", ":"), ensure_ascii=False),
        str(body.get("ai_agent_id", "") or "").strip(),
        now,
        now,
        now,
    )

    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        existing = connection.execute(
            "SELECT state, provider_call_key, submitted_at FROM outreach_autodial_queue WHERE queue_key=?",
            (key,),
        ).fetchone()
        if existing is not None and str(existing["state"] or "") == "submitted":
            return {
                "queued": False,
                "duplicate_prevented": True,
                "state": "submitted",
                "queue_key": key,
                "provider_call_key": existing["provider_call_key"],
                "submitted_at": existing["submitted_at"],
            }
        connection.execute(
            """
            INSERT INTO outreach_autodial_queue (
                queue_key, record_id, contact_number, phone_key, campaign, call_stage,
                has_consent, consent_record_id, legal_basis, dnc_clear, dnc_checked_at,
                suppression_clear, contact_timezone, campaign_enabled,
                dynamic_variables_json, ai_agent_id, state, attempts, next_attempt_at,
                lease_until, last_blocker, provider_call_key, submitted_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, NULL, NULL, NULL, NULL, ?, ?)
            ON CONFLICT(queue_key) DO UPDATE SET
                has_consent=excluded.has_consent,
                consent_record_id=excluded.consent_record_id,
                legal_basis=excluded.legal_basis,
                dnc_clear=excluded.dnc_clear,
                dnc_checked_at=excluded.dnc_checked_at,
                suppression_clear=excluded.suppression_clear,
                contact_timezone=excluded.contact_timezone,
                campaign_enabled=excluded.campaign_enabled,
                dynamic_variables_json=excluded.dynamic_variables_json,
                ai_agent_id=excluded.ai_agent_id,
                state=CASE WHEN outreach_autodial_queue.state='review_required' THEN 'review_required' ELSE 'queued' END,
                next_attempt_at=CASE WHEN outreach_autodial_queue.state='review_required' THEN outreach_autodial_queue.next_attempt_at ELSE excluded.next_attempt_at END,
                lease_until=NULL,
                updated_at=excluded.updated_at
            """,
            values,
        )
        connection.commit()
    return {"queued": True, "duplicate_prevented": False, "state": "queued", "queue_key": key}


def _worker_enabled() -> bool:
    return _bool(os.getenv("NIJA_JUSTCALL_AUTODIAL_ENABLED", "0"))


def _poll_seconds() -> float:
    try:
        return max(10.0, min(float(os.getenv("NIJA_JUSTCALL_AUTODIAL_POLL_SECONDS", "30")), 300.0))
    except ValueError:
        return 30.0


def _batch_size() -> int:
    try:
        return max(1, min(int(os.getenv("NIJA_JUSTCALL_AUTODIAL_BATCH_SIZE", "10")), 50))
    except ValueError:
        return 10


def _daily_cap() -> int:
    try:
        return max(1, min(int(os.getenv("NIJA_AUTODIAL_DAILY_CAP", "300")), 5000))
    except ValueError:
        return 300


def _quota_zone() -> ZoneInfo:
    name = os.getenv("NIJA_AUTODIAL_QUOTA_TIMEZONE", "America/Los_Angeles").strip()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Los_Angeles")


def _calling_hours() -> tuple[int, int]:
    try:
        start = int(os.getenv("NIJA_AUTODIAL_LOCAL_START_HOUR", "9"))
        end = int(os.getenv("NIJA_AUTODIAL_LOCAL_END_HOUR", "20"))
    except ValueError:
        return 9, 20
    start = max(8, min(start, 19))
    end = max(start + 1, min(end, 21))
    return start, end


def _weekdays_only() -> bool:
    return _bool(os.getenv("NIJA_AUTODIAL_WEEKDAYS_ONLY", "1"))


def _next_campaign_day_start(now_utc: datetime) -> datetime:
    zone = _quota_zone()
    local = now_utc.astimezone(zone)
    target = (local + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    while _weekdays_only() and target.weekday() >= 5:
        target += timedelta(days=1)
    return target.astimezone(timezone.utc)


def _quota_date(now_utc: datetime) -> tuple[str, bool]:
    local = now_utc.astimezone(_quota_zone())
    return local.date().isoformat(), (not _weekdays_only() or local.weekday() < 5)


def _quota_snapshot(now_utc: datetime) -> dict[str, Any]:
    key, allowed_day = _quota_date(now_utc)
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT used_count FROM outreach_autodial_daily_quota WHERE quota_date=?", (key,)
        ).fetchone()
    used = int(row["used_count"] or 0) if row else 0
    cap = _daily_cap()
    return {
        "date": key,
        "used": used,
        "cap": cap,
        "remaining": max(0, cap - used),
        "weekday_open": allowed_day,
    }


def _reserve_quota(now_utc: datetime) -> tuple[bool, str, str]:
    key, allowed_day = _quota_date(now_utc)
    if not allowed_day:
        return False, key, "campaign_weekend_closed"
    cap = _daily_cap()
    now = _iso(now_utc)
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT OR IGNORE INTO outreach_autodial_daily_quota(quota_date, used_count, updated_at) VALUES (?,0,?)",
            (key, now),
        )
        row = connection.execute(
            "SELECT used_count FROM outreach_autodial_daily_quota WHERE quota_date=?", (key,)
        ).fetchone()
        used = int(row["used_count"] or 0) if row else 0
        if used >= cap:
            connection.commit()
            return False, key, "daily_cap_reached"
        connection.execute(
            "UPDATE outreach_autodial_daily_quota SET used_count=used_count+1, updated_at=? WHERE quota_date=?",
            (now, key),
        )
        connection.commit()
    return True, key, "ok"


def _release_quota(key: str) -> None:
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            "UPDATE outreach_autodial_daily_quota SET used_count=MAX(used_count-1,0), updated_at=? WHERE quota_date=?",
            (_iso(_utcnow()), key),
        )
        connection.commit()


def _calling_window(timezone_name: str, now_utc: datetime) -> tuple[bool, datetime, str]:
    if not timezone_name:
        return False, now_utc + timedelta(minutes=15), "contact_timezone_required"
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return False, now_utc + timedelta(hours=1), "contact_timezone_invalid"
    local = now_utc.astimezone(zone)
    start_hour, end_hour = _calling_hours()
    if _weekdays_only() and local.weekday() >= 5:
        target = (local + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
        while target.weekday() >= 5:
            target += timedelta(days=1)
        return False, target.astimezone(timezone.utc), "outside_calling_day"
    if local.hour < start_hour:
        target = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        return False, target.astimezone(timezone.utc), "outside_calling_window"
    if local.hour >= end_hour:
        target = (local + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
        while _weekdays_only() and target.weekday() >= 5:
            target += timedelta(days=1)
        return False, target.astimezone(timezone.utc), "outside_calling_window"
    return True, now_utc, "ok"


def _dnc_fresh(value: object, now_utc: datetime, max_age_seconds: int = 900) -> bool:
    checked = _parse_iso(value)
    if checked is None:
        return False
    age = (now_utc - checked).total_seconds()
    return -60 <= age <= max_age_seconds


def _active_call_exists(number: str, now_utc: datetime) -> bool:
    pkey = phone_key(number)
    if not pkey:
        return True
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        try:
            row = connection.execute(
                "SELECT latest_event_type, updated_at FROM outreach_calls WHERE phone_key=? ORDER BY id DESC LIMIT 1",
                (pkey,),
            ).fetchone()
        except sqlite3.OperationalError:
            return False
    if row is None:
        return False
    latest = str(row["latest_event_type"] or "")
    if latest in _TERMINAL_CALL_EVENTS:
        return False
    updated = _parse_iso(row["updated_at"])
    if updated is None:
        return True
    return (now_utc - updated).total_seconds() < 7200


def _eligibility(row: sqlite3.Row, now_utc: datetime) -> tuple[list[str], datetime]:
    blockers: list[str] = []
    retry_at = now_utc + timedelta(minutes=15)
    if not bool(row["has_consent"]):
        blockers.append("verified_consent_required")
    if not str(row["consent_record_id"] or "").strip():
        blockers.append("consent_record_id_required")
    if not str(row["legal_basis"] or "").strip():
        blockers.append("legal_basis_required")
    if not bool(row["dnc_clear"]):
        blockers.append("dnc_clear_required")
    if not _dnc_fresh(row["dnc_checked_at"], now_utc):
        blockers.append("fresh_dnc_check_required")
    if not bool(row["suppression_clear"]):
        blockers.append("suppression_clear_required")
    if is_suppressed(str(row["contact_number"] or "")):
        blockers.append("locally_suppressed")
    if not bool(row["campaign_enabled"]):
        blockers.append("campaign_not_enabled")

    quota = _quota_snapshot(now_utc)
    if not quota["weekday_open"]:
        blockers.append("campaign_weekend_closed")
        retry_at = max(retry_at, _next_campaign_day_start(now_utc))
    elif quota["remaining"] <= 0:
        blockers.append("daily_cap_reached")
        retry_at = max(retry_at, _next_campaign_day_start(now_utc))

    allowed, window_retry, window_reason = _calling_window(str(row["contact_timezone"] or ""), now_utc)
    if not allowed:
        blockers.append(window_reason)
        retry_at = max(retry_at, window_retry)
    if _active_call_exists(str(row["contact_number"] or ""), now_utc):
        blockers.append("duplicate_active_call")
        retry_at = max(retry_at, now_utc + timedelta(minutes=10))
    return blockers, retry_at


def _claim_one(now_utc: datetime) -> Optional[sqlite3.Row]:
    now = _iso(now_utc)
    lease = _iso(now_utc + timedelta(minutes=2))
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT * FROM outreach_autodial_queue
            WHERE (state='queued' OR (state='processing' AND COALESCE(lease_until,'') <= ?))
              AND next_attempt_at <= ?
            ORDER BY next_attempt_at ASC, id ASC
            LIMIT 1
            """,
            (now, now),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        changed = connection.execute(
            """
            UPDATE outreach_autodial_queue
            SET state='processing', lease_until=?, attempts=attempts+1, updated_at=?
            WHERE id=? AND (state='queued' OR (state='processing' AND COALESCE(lease_until,'') <= ?))
            """,
            (lease, now, row["id"], now),
        )
        connection.commit()
        if changed.rowcount != 1:
            return None
        return connection.execute("SELECT * FROM outreach_autodial_queue WHERE id=?", (row["id"],)).fetchone()


def _reschedule(queue_id: int, blocker: str, when: datetime, *, state: str = "queued") -> None:
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            "UPDATE outreach_autodial_queue SET state=?, next_attempt_at=?, lease_until=NULL, last_blocker=?, updated_at=? WHERE id=?",
            (state, _iso(when), blocker[:500], _iso(_utcnow()), queue_id),
        )
        connection.commit()


def _mark_submitted(queue_id: int, call_key: str) -> None:
    now = _iso(_utcnow())
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            "UPDATE outreach_autodial_queue SET state='submitted', lease_until=NULL, last_blocker=NULL, provider_call_key=?, submitted_at=?, updated_at=? WHERE id=?",
            (call_key, now, now, queue_id),
        )
        connection.commit()


def _submit_row(row: sqlite3.Row) -> bool:
    global _WORKER_LAST_SUBMISSION_AT, _WORKER_LAST_ERROR
    now_utc = _utcnow()
    blockers, retry_at = _eligibility(row, now_utc)
    if blockers:
        _reschedule(int(row["id"]), ",".join(blockers), retry_at)
        return False
    try:
        variables = json.loads(str(row["dynamic_variables_json"] or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        variables = []
    if not isinstance(variables, list):
        variables = []
    try:
        agent_id = _resolve_agent_id(str(row["ai_agent_id"] or ""))
    except (ValueError, OutreachConfigurationError) as exc:
        _WORKER_LAST_ERROR = type(exc).__name__
        _reschedule(int(row["id"]), "ai_agent_unavailable", now_utc + timedelta(minutes=5))
        return False

    reserved, quota_key, quota_reason = _reserve_quota(now_utc)
    if not reserved:
        _reschedule(int(row["id"]), quota_reason, _next_campaign_day_start(now_utc))
        return False

    request_payload = {
        "record_id": str(row["record_id"] or ""),
        "campaign": str(row["campaign"] or ""),
        "call_stage": str(row["call_stage"] or ""),
        "contact_number": str(row["contact_number"] or ""),
        "has_consent": True,
        "consent_record_id": str(row["consent_record_id"] or ""),
        "legal_basis": str(row["legal_basis"] or ""),
        "dnc_clear": True,
        "dnc_checked_at": str(row["dnc_checked_at"] or ""),
        "suppression_clear": True,
        "campaign_enabled": True,
        "test_mode": False,
        "dynamic_variables": variables,
    }
    try:
        provider_payload = _provider_request(
            "POST",
            "/voice-agents/calls",
            payload={
                "ai_agent_id": agent_id,
                "contact_number": str(row["contact_number"] or ""),
                "dynamic_variables": variables,
                "has_consent": True,
            },
        )
        recorded = record_outbound_submission(
            contact_number=str(row["contact_number"] or ""),
            record_id=str(row["record_id"] or ""),
            campaign=str(row["campaign"] or ""),
            provider_payload=provider_payload,
            request_payload=request_payload,
        )
    except OutreachProviderError as exc:
        _release_quota(quota_key)
        _WORKER_LAST_ERROR = "OutreachProviderError"
        if exc.status_code == 429:
            _reschedule(int(row["id"]), "provider_rate_limited", now_utc + timedelta(minutes=2))
        else:
            _reschedule(
                int(row["id"]),
                "provider_submission_requires_review",
                now_utc + timedelta(days=3650),
                state="review_required",
            )
        return False
    except OSError:
        _release_quota(quota_key)
        _WORKER_LAST_ERROR = "OutreachStoreError"
        _reschedule(
            int(row["id"]),
            "provider_submission_recording_requires_review",
            now_utc + timedelta(days=3650),
            state="review_required",
        )
        return False

    call_key = str(recorded.get("call_key", "") or "")
    _mark_submitted(int(row["id"]), call_key)
    _WORKER_LAST_SUBMISSION_AT = _iso(_utcnow())
    _WORKER_LAST_ERROR = None
    print(
        "JUSTCALL_AUTODIAL_SUBMISSION state=submitted "
        f"queue_id={int(row['id'])} campaign={str(row['campaign'] or '')[:80]} quota_date={quota_key}",
        flush=True,
    )
    return True


def _run_cycle() -> tuple[int, int]:
    global _WORKER_LAST_CYCLE_AT
    attempted = 0
    submitted = 0
    _WORKER_LAST_CYCLE_AT = _iso(_utcnow())
    for _ in range(_batch_size()):
        if _quota_snapshot(_utcnow())["remaining"] <= 0:
            break
        row = _claim_one(_utcnow())
        if row is None:
            break
        attempted += 1
        if _submit_row(row):
            submitted += 1
    return attempted, submitted


def _worker() -> None:
    global _WORKER_LAST_ERROR
    if not _worker_enabled():
        print("JUSTCALL_AUTODIAL_WORKER state=disabled fail_closed=true", flush=True)
        return
    print(
        "JUSTCALL_AUTODIAL_WORKER state=ready fail_closed=true "
        f"poll_s={_poll_seconds():.0f} batch={_batch_size()} daily_cap={_daily_cap()} "
        f"quota_tz={getattr(_quota_zone(), 'key', 'America/Los_Angeles')} "
        f"local_hours={_calling_hours()[0]}-{_calling_hours()[1]} weekdays_only={str(_weekdays_only()).lower()}",
        flush=True,
    )
    while True:
        try:
            attempted, submitted = _run_cycle()
            if attempted:
                print(
                    f"JUSTCALL_AUTODIAL_CYCLE attempted={attempted} submitted={submitted} fail_closed=true",
                    flush=True,
                )
        except Exception as exc:
            _WORKER_LAST_ERROR = type(exc).__name__
            print(
                f"JUSTCALL_AUTODIAL_WORKER state=cycle_error error={type(exc).__name__} fail_closed=true",
                flush=True,
            )
        time.sleep(_poll_seconds())


def start_justcall_autodial() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
    threading.Thread(target=_worker, name="nija-justcall-autodial", daemon=True).start()


def _queue_status() -> dict[str, Any]:
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            "SELECT state, COUNT(*) AS count FROM outreach_autodial_queue GROUP BY state"
        ).fetchall()
        next_row = connection.execute(
            "SELECT MIN(next_attempt_at) AS next_attempt_at FROM outreach_autodial_queue WHERE state IN ('queued','processing')"
        ).fetchone()
        blocker_rows = connection.execute(
            """
            SELECT COALESCE(last_blocker,'') AS blocker, COUNT(*) AS count
            FROM outreach_autodial_queue
            WHERE state='queued' AND COALESCE(last_blocker,'') <> ''
            GROUP BY COALESCE(last_blocker,'')
            ORDER BY count DESC LIMIT 20
            """
        ).fetchall()
    counts = {str(row["state"]): int(row["count"] or 0) for row in rows}
    return {
        "enabled": _worker_enabled(),
        "worker_started": _WORKER_STARTED,
        "poll_seconds": _poll_seconds(),
        "batch_size": _batch_size(),
        "daily_quota": _quota_snapshot(_utcnow()),
        "calling_hours_local": list(_calling_hours()),
        "weekdays_only": _weekdays_only(),
        "counts": counts,
        "blockers": {str(row["blocker"]): int(row["count"] or 0) for row in blocker_rows},
        "next_attempt_at": next_row["next_attempt_at"] if next_row else None,
        "last_cycle_at": _WORKER_LAST_CYCLE_AT,
        "last_submission_at": _WORKER_LAST_SUBMISSION_AT,
        "last_error": _WORKER_LAST_ERROR,
        "fail_closed": True,
    }


def handle_autodial_get(handler: Any) -> bool:
    path = str(getattr(handler, "path", "") or "").split("?", 1)[0]
    if path != _STATUS_PATH:
        return False
    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    try:
        payload = _queue_status()
    except OSError:
        _send_json(handler, 503, {"error": "Autodial queue unavailable"})
    else:
        _send_json(handler, 200, payload)
    return True


def handle_autodial_post(handler: Any) -> bool:
    path = str(getattr(handler, "path", "") or "").split("?", 1)[0]
    if path != _QUEUE_PATH:
        return False
    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    try:
        body = _read_json(handler)
        result = enqueue_candidate(body)
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
    except OSError:
        _send_json(handler, 503, {"error": "Autodial queue unavailable"})
    else:
        _send_json(handler, 200, result)
    return True
