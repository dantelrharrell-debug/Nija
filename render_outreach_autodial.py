"""Durable, compliance-gated JustCall autodial queue for NIJA outreach.

Contacts may enter before every gate is ready. A provider call is submitted only
when stored compliance evidence is valid, the recipient's local calling window
is open, the NIJA daily quota has capacity, no active duplicate exists, local
suppression is clear, and a JustCall AI Voice Agent resolves.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import pathlib
import re
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
            weekend_evidence_json TEXT NOT NULL DEFAULT '{}',
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
            updated_at TEXT NOT NULL,
            last_reserved_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # Existing production databases must migrate before the worker reads weekend evidence.
    columns = {
        str(field["name"])
        for field in connection.execute("PRAGMA table_info(outreach_autodial_queue)")
    }
    if "weekend_evidence_json" not in columns:
        connection.execute(
            "ALTER TABLE outreach_autodial_queue "
            "ADD COLUMN weekend_evidence_json TEXT NOT NULL DEFAULT '{}'"
        )
    quota_columns = {
        str(field["name"])
        for field in connection.execute("PRAGMA table_info(outreach_autodial_daily_quota)")
    }
    if "last_reserved_at" not in quota_columns:
        connection.execute(
            "ALTER TABLE outreach_autodial_daily_quota "
            "ADD COLUMN last_reserved_at TEXT NOT NULL DEFAULT ''"
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


def _static_readiness(body: dict[str, Any]) -> tuple[bool, str]:
    """Evaluate only durable, non-time-window call-readiness evidence."""
    checks = (
        (_bool(body.get("has_consent")), "verified_consent_required"),
        (bool(str(body.get("consent_record_id", "") or "").strip()), "consent_record_id_required"),
        (bool(str(body.get("legal_basis", "") or "").strip()), "legal_basis_required"),
        (_bool(body.get("dnc_clear")), "dnc_clear_required"),
        (bool(str(body.get("dnc_checked_at", "") or "").strip()), "dnc_checked_at_required"),
        (_bool(body.get("suppression_clear")), "suppression_clear_required"),
        (_bool(body.get("campaign_enabled")), "campaign_not_enabled"),
    )
    blockers = [reason for passed, reason in checks if not passed]
    return (not blockers, ",".join(blockers))


def _quarantine_static_nonready() -> int:
    """Move stale unqualified rows out of the active worker loop.

    A future qualified refresh through enqueue_candidate reactivates the same
    queue key automatically; submitted rows are never changed.
    """
    now = _iso(_utcnow())
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        changed = connection.execute(
            """
            UPDATE outreach_autodial_queue
            SET state='review_required',
                lease_until=NULL,
                last_blocker=CASE
                    WHEN has_consent=0 THEN 'verified_consent_required'
                    WHEN TRIM(COALESCE(consent_record_id,''))='' THEN 'consent_record_id_required'
                    WHEN TRIM(COALESCE(legal_basis,''))='' THEN 'legal_basis_required'
                    WHEN dnc_clear=0 THEN 'dnc_clear_required'
                    WHEN TRIM(COALESCE(dnc_checked_at,''))='' THEN 'dnc_checked_at_required'
                    WHEN suppression_clear=0 THEN 'suppression_clear_required'
                    WHEN campaign_enabled=0 THEN 'campaign_not_enabled'
                    ELSE 'static_readiness_review_required'
                END,
                next_attempt_at=?,
                updated_at=?
            WHERE state IN ('queued','processing')
              AND (
                    has_consent=0
                 OR TRIM(COALESCE(consent_record_id,''))=''
                 OR TRIM(COALESCE(legal_basis,''))=''
                 OR dnc_clear=0
                 OR TRIM(COALESCE(dnc_checked_at,''))=''
                 OR suppression_clear=0
                 OR campaign_enabled=0
              )
            """,
            (now, now),
        )
        connection.commit()
        return int(changed.rowcount or 0)

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

    raw_weekend = body.get("weekend_evidence") or {}
    if not isinstance(raw_weekend, dict):
        raise ValueError("weekend_evidence must be an object")
    # Store only audit identifiers, never treat missing evidence as weekend consent.
    weekend_evidence = {
        "approved": raw_weekend.get("approved") is True,
        "recipient_jurisdiction": str(raw_weekend.get("recipient_jurisdiction") or "").strip().upper()[:16],
        "recipient_timezone": str(raw_weekend.get("recipient_timezone") or "").strip()[:128],
        "clearance_id": str(raw_weekend.get("clearance_id") or "").strip()[:128],
        "cleared_local_date": str(raw_weekend.get("cleared_local_date") or "").strip()[:10],
        "checked_at": str(raw_weekend.get("checked_at") or "").strip()[:40],
        "signature": str(raw_weekend.get("signature") or "").strip()[:64],
    }
    weekend_evidence_json = json.dumps(weekend_evidence, separators=(",", ":"))

    static_ready, static_blocker = _static_readiness(body)
    desired_state = "queued" if static_ready else "review_required"
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
        weekend_evidence_json,
        1 if _bool(body.get("campaign_enabled")) else 0,
        json.dumps(variables, separators=(",", ":"), ensure_ascii=False),
        str(body.get("ai_agent_id", "") or "").strip(),
        desired_state,
        now,
        static_blocker or None,
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
                suppression_clear, contact_timezone, weekend_evidence_json, campaign_enabled,
                dynamic_variables_json, ai_agent_id, state, attempts, next_attempt_at,
                lease_until, last_blocker, provider_call_key, submitted_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, NULL, NULL, ?, ?)
            ON CONFLICT(queue_key) DO UPDATE SET
                has_consent=excluded.has_consent,
                consent_record_id=excluded.consent_record_id,
                legal_basis=excluded.legal_basis,
                dnc_clear=excluded.dnc_clear,
                dnc_checked_at=excluded.dnc_checked_at,
                suppression_clear=excluded.suppression_clear,
                contact_timezone=excluded.contact_timezone,
                weekend_evidence_json=excluded.weekend_evidence_json,
                campaign_enabled=excluded.campaign_enabled,
                dynamic_variables_json=excluded.dynamic_variables_json,
                ai_agent_id=excluded.ai_agent_id,
                state=CASE
                    WHEN outreach_autodial_queue.state='review_required'
                         AND COALESCE(outreach_autodial_queue.last_blocker,'') IN (
                             'provider_submission_requires_review',
                             'provider_submission_recording_requires_review'
                         )
                    THEN 'review_required'
                    ELSE excluded.state
                END,
                attempts=CASE
                    WHEN outreach_autodial_queue.state='review_required'
                         AND COALESCE(outreach_autodial_queue.last_blocker,'') IN (
                             'provider_submission_requires_review',
                             'provider_submission_recording_requires_review'
                         )
                    THEN outreach_autodial_queue.attempts
                    WHEN excluded.state='queued' THEN 0
                    ELSE outreach_autodial_queue.attempts
                END,
                next_attempt_at=CASE
                    WHEN outreach_autodial_queue.state='review_required'
                         AND COALESCE(outreach_autodial_queue.last_blocker,'') IN (
                             'provider_submission_requires_review',
                             'provider_submission_recording_requires_review'
                         )
                    THEN outreach_autodial_queue.next_attempt_at
                    ELSE excluded.next_attempt_at
                END,
                lease_until=NULL,
                last_blocker=CASE
                    WHEN outreach_autodial_queue.state='review_required'
                         AND COALESCE(outreach_autodial_queue.last_blocker,'') IN (
                             'provider_submission_requires_review',
                             'provider_submission_recording_requires_review'
                         )
                    THEN outreach_autodial_queue.last_blocker
                    ELSE excluded.last_blocker
                END,
                updated_at=excluded.updated_at
            """,
            values,
        )
        connection.commit()
    return {
        "queued": static_ready,
        "duplicate_prevented": False,
        "state": desired_state,
        "queue_key": key,
        "blocker": static_blocker or None,
    }

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


def _min_submission_interval_seconds() -> int:
    # 2 minutes = at most 30 submitted calls per hour; 300/day needs about
    # 10 recipient-local calling hours if every recipient is eligible.
    try:
        return max(60, min(int(os.getenv("NIJA_AUTODIAL_MIN_SUBMISSION_INTERVAL_SECONDS", "120")), 3600))
    except ValueError:
        return 120


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
            "SELECT used_count, last_reserved_at FROM outreach_autodial_daily_quota WHERE quota_date=?", (key,)
        ).fetchone()
    used = int(row["used_count"] or 0) if row else 0
    last_text = str(row["last_reserved_at"] or "").strip() if row else ""
    last = _parse_iso(last_text) if last_text else None
    if last_text and last is None:
        pacing_ready = False
        next_allowed = None
    else:
        next_allowed = last + timedelta(seconds=_min_submission_interval_seconds()) if last else now_utc
        pacing_ready = now_utc >= next_allowed
    cap = _daily_cap()
    return {
        "date": key,
        "used": used,
        "cap": cap,
        "remaining": max(0, cap - used),
        "weekday_open": allowed_day,
        "pacing_ready": pacing_ready,
        "next_allowed_at": _iso(next_allowed) if next_allowed else None,
        "min_submission_interval_seconds": _min_submission_interval_seconds(),
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
            "INSERT OR IGNORE INTO outreach_autodial_daily_quota("
            "quota_date, used_count, updated_at, last_reserved_at) VALUES (?,0,?,'')",
            (key, now),
        )
        row = connection.execute(
            "SELECT used_count, last_reserved_at FROM outreach_autodial_daily_quota WHERE quota_date=?", (key,)
        ).fetchone()
        used = int(row["used_count"] or 0) if row else 0
        if used >= cap:
            connection.commit()
            return False, key, "daily_cap_reached"
        last_text = str(row["last_reserved_at"] or "").strip() if row else ""
        last = _parse_iso(last_text) if last_text else None
        if last_text and last is None:
            connection.commit()
            return False, key, "quota_state_invalid"
        if last and (now_utc - last).total_seconds() < _min_submission_interval_seconds():
            connection.commit()
            return False, key, "pacing_interval_not_elapsed"
        connection.execute(
            "UPDATE outreach_autodial_daily_quota SET used_count=used_count+1, "
            "last_reserved_at=?, updated_at=? WHERE quota_date=?",
            (now, now, key),
        )
        connection.commit()
    return True, key, "ok"


def _release_quota(key: str) -> None:
    with _QUEUE_LOCK, _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            "UPDATE outreach_autodial_daily_quota SET used_count=MAX(used_count-1,0), "
            "updated_at=? WHERE quota_date=?",
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


_VALID_US_JURISDICTIONS = {
    "US-" + state for state in (
        "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA "
        "MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX "
        "UT VT VA WA WV WI WY"
    ).split()
}


def _weekend_clearance_valid(
    evidence: dict[str, Any], number: str, campaign: str, consent_record_id: str
) -> bool:
    """Verify a second-party signature bound to THIS recipient, jurisdiction, timezone and day.

    Only an external compliance reviewer with access to the separately managed
    signing key may authorize weekend outreach. API callers cannot self-approve
    by setting `approved` or selecting a convenient state.
    """
    secret = os.getenv("NIJA_JUSTCALL_WEEKEND_CLEARANCE_SECRET", "").strip()
    signature = str(evidence.get("signature") or "").strip().lower()
    if len(secret) < 32 or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    signed_fields = {
        "phone_digits": phone_key(number),
        "campaign": campaign,
        "consent_record_id": consent_record_id,
        "jurisdiction": str(evidence.get("recipient_jurisdiction") or "").strip().upper(),
        "timezone": str(evidence.get("recipient_timezone") or "").strip(),
        "clearance_id": str(evidence.get("clearance_id") or "").strip(),
        "local_date": str(evidence.get("cleared_local_date") or "").strip(),
        "checked_at": str(evidence.get("checked_at") or "").strip(),
    }
    message = json.dumps(
        signed_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verified_weekend_evidence(
    evidence_json: object, number: str, campaign: str, consent_record_id: str
) -> tuple[Optional[dict[str, Any]], str, str]:
    try:
        evidence = json.loads(str(evidence_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, "", "jurisdiction_evidence_invalid"
    if not isinstance(evidence, dict):
        return None, "", "jurisdiction_evidence_invalid"

    jurisdiction = str(evidence.get("recipient_jurisdiction") or "").strip().upper()
    if jurisdiction not in _VALID_US_JURISDICTIONS:
        return None, "", "recipient_jurisdiction_required"

    timezone_name = str(evidence.get("recipient_timezone") or "").strip()
    if not timezone_name:
        return None, "", "recipient_timezone_required"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None, "", "contact_timezone_invalid"
    if not _weekend_clearance_valid(evidence, number, campaign, consent_record_id):
        return None, "", "weekend_clearance_signature_invalid"
    return evidence, timezone_name, ""


def _weekend_call_eligibility(
    evidence_json: object, now_utc: datetime,
    *, number: str, campaign: str, consent_record_id: str
) -> tuple[bool, str]:
    """Every day: require signed recipient jurisdiction/timezone; weekends: signed clearance.

    A signed clearance is necessary but not sufficient: fresh verified AI consent,
    DNC and suppression rules, human handoff and local hours still apply.
    """
    evidence, verified_timezone, reason = _verified_weekend_evidence(
        evidence_json, number, campaign, consent_record_id
    )
    if reason:
        return False, reason
    assert evidence is not None
    local = now_utc.astimezone(ZoneInfo(verified_timezone))
    jurisdiction = str(evidence.get("recipient_jurisdiction") or "").strip().upper()

    # Pennsylvania Act 47 of July 20, 2026 takes effect on October 18, 2026.
    if jurisdiction == "US-PA" and local.date().isoformat() >= "2026-10-18":
        if local.hour < 9 or local.hour >= 19:
            return False, "jurisdiction_hours_prohibited"
        if local.weekday() == 6:
            return False, "jurisdiction_sunday_prohibited"

    # Conservative hard stops for known Sunday bans, regardless of consent.
    if local.weekday() == 6 and jurisdiction in {"US-AL", "US-MS", "US-PA"}:
        return False, "jurisdiction_sunday_prohibited"
    if local.weekday() < 5:
        return True, "ok"

    if evidence.get("approved") is not True:
        return False, "weekend_clearance_required"
    if not str(evidence.get("clearance_id") or "").strip():
        return False, "weekend_clearance_record_required"
    if str(evidence.get("cleared_local_date") or "") != local.date().isoformat():
        return False, "weekend_clearance_date_required"
    checked = _parse_iso(evidence.get("checked_at"))
    if checked is None:
        return False, "weekend_clearance_timestamp_required"
    age = (now_utc - checked).total_seconds()
    if not -60 <= age <= 86400:
        return False, "weekend_clearance_expired"
    return True, "ok"


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
    if not quota.get("pacing_ready", True):
        blockers.append("pacing_interval_not_elapsed")
        retry_after = _parse_iso(quota.get("next_allowed_at"))
        if retry_after:
            retry_at = max(retry_at, retry_after)

    weekend_allowed, weekend_reason = _weekend_call_eligibility(
        row["weekend_evidence_json"], now_utc,
        number=str(row["contact_number"] or ""),
        campaign=str(row["campaign"] or ""),
        consent_record_id=str(row["consent_record_id"] or ""),
    )
    if not weekend_allowed:
        blockers.append(weekend_reason)
        retry_at = max(retry_at, now_utc + timedelta(minutes=15))
    else:
        evidence = json.loads(str(row["weekend_evidence_json"] or "{}"))
        verified_timezone = str(evidence["recipient_timezone"])
        allowed, window_retry, window_reason = _calling_window(verified_timezone, now_utc)
        if not allowed:
            blockers.append(window_reason)
            retry_at = max(retry_at, window_retry)
    if _bool(os.getenv("NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF", "1")) and not _bool(
        os.getenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED", "0")
    ):
        blockers.append("human_handoff_not_verified")
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
        retry_at = (
            now_utc + timedelta(seconds=_min_submission_interval_seconds())
            if quota_reason == "pacing_interval_not_elapsed"
            else _next_campaign_day_start(now_utc)
        )
        _reschedule(int(row["id"]), quota_reason, retry_at)
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
        quota = _quota_snapshot(_utcnow())
        if quota["remaining"] <= 0 or not quota["pacing_ready"]:
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
    quarantined = _quarantine_static_nonready()
    print(
        "JUSTCALL_AUTODIAL_WORKER state=ready fail_closed=true "
        f"poll_s={_poll_seconds():.0f} batch={_batch_size()} daily_cap={_daily_cap()} "
        f"min_submission_interval_s={_min_submission_interval_seconds()} "
        f"quota_tz={getattr(_quota_zone(), 'key', 'America/Los_Angeles')} "
        f"local_hours={_calling_hours()[0]}-{_calling_hours()[1]} "
        f"weekdays_only={str(_weekdays_only()).lower()} weekend_per_recipient_gate=true "
        f"human_handoff_required={str(_bool(os.getenv('NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF', '1'))).lower()} "
        f"quarantined={quarantined}",
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
            WHERE state IN ('queued','review_required') AND COALESCE(last_blocker,'') <> ''
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
        "seven_day_mode": not _weekdays_only(),
        "weekend_recipient_clearance_required": True,
        "human_handoff_required": _bool(os.getenv("NIJA_JUSTCALL_REQUIRE_HUMAN_HANDOFF", "1")),
        "human_handoff_verified": _bool(os.getenv("NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED", "0")),
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
