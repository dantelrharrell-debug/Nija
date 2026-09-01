"""Automatic Apollo -> NIJA outreach feeder and website-lead recovery mirror.

Poll saved Apollo contacts, mirror NIJA website-lead contacts into the durable
Render lead store, normalize phone/timezone data, and feed NIJA's
compliance-gated autodial queue. Cold Apollo contacts are never promoted to
CALL READY without explicit consent/legal/DNC/suppression evidence.
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
from datetime import datetime, timezone
from typing import Any, Optional

from render_lead_intake import record_lead
from render_outreach_autodial import enqueue_candidate
from render_outreach_routes import _E164_RE, _send_json, _service_authorized
from render_outreach_store import is_suppressed, set_suppression

APOLLO_API_BASE = "https://api.apollo.io/api/v1"
_STATUS_PATH = "/api/apollo/feeder-status"
_SYNC_PATH = "/api/apollo/sync-now"
_DEFAULT_WEBSITE_LEAD_LABEL_ID = "6a95ec5c651e97000cd9a898"
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False
_LAST_SYNC_AT: Optional[str] = None
_LAST_ERROR: Optional[str] = None
_LAST_COUNTS: dict[str, int] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _bool(value: object) -> bool:
    return value is True or str(value or "").strip().lower() in {
        "1", "true", "yes", "on", "qualified", "clear", "passed"
    }


def _enabled() -> bool:
    return _bool(os.getenv("NIJA_APOLLO_FEED_ENABLED", "0"))


def _poll_seconds() -> float:
    try:
        return max(60.0, min(float(os.getenv("NIJA_APOLLO_FEED_POLL_SECONDS", "300")), 3600.0))
    except ValueError:
        return 300.0


def _pages_per_sync() -> int:
    try:
        return max(1, min(int(os.getenv("NIJA_APOLLO_FEED_MAX_PAGES", "5")), 50))
    except ValueError:
        return 5


def _api_key() -> str:
    return os.getenv("APOLLO_API_KEY", "").strip()


def _website_lead_label_id() -> str:
    return (
        os.getenv("NIJA_APOLLO_WEBSITE_LEAD_LABEL_ID", "").strip()
        or _DEFAULT_WEBSITE_LEAD_LABEL_ID
    )


def _website_lead_form_name() -> str:
    return (
        os.getenv("NIJA_APOLLO_WEBSITE_LEAD_FORM_NAME", "Intro Lead Gate").strip()
        or "Intro Lead Gate"
    )


def _db_path() -> pathlib.Path:
    return pathlib.Path(
        os.getenv("NIJA_OUTREACH_DB_PATH", "").strip()
        or "/app/data/nija_outreach.sqlite3"
    )


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS outreach_apollo_sync_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            last_contact_updated_at TEXT NOT NULL DEFAULT '',
            last_sync_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            last_counts_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO outreach_apollo_sync_state(singleton) VALUES (1)"
    )
    connection.commit()


def _load_cursor() -> str:
    with _connect() as connection:
        _ensure_schema(connection)
        row = connection.execute(
            "SELECT last_contact_updated_at FROM outreach_apollo_sync_state WHERE singleton=1"
        ).fetchone()
    return str(row["last_contact_updated_at"] or "") if row else ""


def _save_state(cursor: str, counts: dict[str, int], error: str = "") -> None:
    global _LAST_SYNC_AT, _LAST_ERROR, _LAST_COUNTS
    now = _iso(_utcnow())
    with _connect() as connection:
        _ensure_schema(connection)
        connection.execute(
            "UPDATE outreach_apollo_sync_state SET last_contact_updated_at=?,last_sync_at=?,last_error=?,last_counts_json=? WHERE singleton=1",
            (cursor, now, error, json.dumps(counts, separators=(",", ":"))),
        )
        connection.commit()
    _LAST_SYNC_AT = now
    _LAST_ERROR = error or None
    _LAST_COUNTS = dict(counts)


def _apollo_request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("APOLLO_API_KEY is not configured")
    request = urllib.request.Request(
        f"{APOLLO_API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": key,
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "NIJA-Apollo-Feeder/1.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20.0) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Apollo API HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Apollo API unavailable") from exc
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Apollo API returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Apollo API returned unexpected data")
    return result


def _custom_field(contact: dict[str, Any], env_name: str) -> object:
    field_id = os.getenv(env_name, "").strip()
    fields = contact.get("typed_custom_fields")
    if not field_id or not isinstance(fields, dict):
        return None
    return fields.get(field_id)


def _is_website_lead(contact: dict[str, Any]) -> bool:
    expected = _website_lead_label_id()
    labels = contact.get("label_ids")
    if not expected or not isinstance(labels, list):
        return False
    return expected in {str(value or "").strip() for value in labels}


def _mirror_website_lead(contact: dict[str, Any]) -> str:
    """Persist Apollo-recovered website leads before phone/calling gates apply."""
    if not _is_website_lead(contact):
        return "not_website_lead"

    email = str(contact.get("email", "") or "").strip()
    if not email:
        return "website_lead_missing_email"

    name = str(contact.get("name", "") or "").strip()
    if name == "(No Name)":
        name = ""
    submitted_at = str(
        contact.get("created_at")
        or contact.get("updated_at")
        or _iso(_utcnow())
    ).strip()
    contact_id = str(contact.get("id", "") or "").strip()

    payload = {
        "form_name": _website_lead_form_name(),
        "name": name,
        "email": email,
        "submitted_at": submitted_at,
        "source": "apollo_recovery",
        "apollo_contact_id": contact_id,
    }
    try:
        _, _, duplicate = record_lead(payload)
    except (OSError, ValueError):
        return "website_lead_error"
    return "website_lead_existing" if duplicate else "website_lead_mirrored"


def _phone(contact: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    numbers = contact.get("phone_numbers")
    if not isinstance(numbers, list):
        return "", {}
    items = [item for item in numbers if isinstance(item, dict)]
    items.sort(
        key=lambda item: 0
        if str(item.get("type", "")).lower() in {"mobile", "direct", "work_direct"}
        else 1
    )
    for item in items:
        number = str(item.get("sanitized_number", "") or "").strip()
        if _E164_RE.fullmatch(number):
            return number, item
    return "", {}


def _evidence(contact: dict[str, Any], phone_meta: dict[str, Any]) -> dict[str, Any]:
    has_consent = _bool(_custom_field(contact, "NIJA_APOLLO_CONSENT_FIELD_ID"))
    consent_record_id = str(
        _custom_field(contact, "NIJA_APOLLO_CONSENT_RECORD_FIELD_ID") or ""
    ).strip()
    legal_basis = str(
        _custom_field(contact, "NIJA_APOLLO_LEGAL_BASIS_FIELD_ID") or ""
    ).strip()
    dnc_value = str(
        _custom_field(contact, "NIJA_APOLLO_DNC_STATUS_FIELD_ID") or ""
    ).strip().lower()
    dnc_checked_at = str(
        _custom_field(contact, "NIJA_APOLLO_DNC_CHECKED_AT_FIELD_ID") or ""
    ).strip()
    suppression_clear = _bool(
        _custom_field(contact, "NIJA_APOLLO_SUPPRESSION_CLEAR_FIELD_ID")
    )
    explicit_campaign_enabled = _bool(
        _custom_field(contact, "NIJA_APOLLO_CAMPAIGN_ENABLED_FIELD_ID")
    )

    provider_dnc = str(phone_meta.get("dnc_status_cd", "") or "").strip().lower()
    if provider_dnc == "found":
        return {
            "has_consent": has_consent,
            "consent_record_id": consent_record_id,
            "legal_basis": legal_basis,
            "dnc_clear": False,
            "dnc_checked_at": dnc_checked_at,
            "suppression_clear": False,
            "campaign_enabled": False,
            "provider_dnc_found": True,
        }

    dnc_clear = dnc_value in {
        "qualified", "clear", "not_found", "not found", "passed", "true", "1"
    }
    complete = bool(
        has_consent
        and consent_record_id
        and legal_basis
        and dnc_clear
        and dnc_checked_at
        and suppression_clear
    )
    campaign_enabled = explicit_campaign_enabled or (
        _bool(os.getenv("NIJA_APOLLO_AUTO_ENABLE_QUALIFIED", "1")) and complete
    )
    return {
        "has_consent": has_consent,
        "consent_record_id": consent_record_id,
        "legal_basis": legal_basis,
        "dnc_clear": dnc_clear,
        "dnc_checked_at": dnc_checked_at,
        "suppression_clear": suppression_clear,
        "campaign_enabled": campaign_enabled,
        "provider_dnc_found": False,
    }


def _dynamic_variables(contact: dict[str, Any]) -> list[dict[str, str]]:
    pairs = (
        ("first_name", contact.get("first_name")),
        ("full_name", contact.get("name")),
        ("company", contact.get("organization_name")),
        ("title", contact.get("title")),
        ("email", contact.get("email")),
    )
    return [
        {"name": key, "value": str(value).strip()[:500], "type": "string"}
        for key, value in pairs
        if str(value or "").strip()
    ]


def _contact_payload(contact: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    contact_id = str(contact.get("id", "") or "").strip()
    if not contact_id:
        return None, "missing_contact_id"
    number, phone_meta = _phone(contact)
    if not number:
        return None, "missing_phone"
    timezone_name = str(contact.get("time_zone", "") or "").strip()
    if not timezone_name:
        return None, "missing_timezone"

    evidence = _evidence(contact, phone_meta)
    if evidence.pop("provider_dnc_found", False):
        try:
            set_suppression(
                contact_number=number,
                reason="apollo_dnc_found",
                source="apollo",
                active=True,
            )
        except (OSError, ValueError):
            pass
    if is_suppressed(number):
        evidence["suppression_clear"] = False
        evidence["campaign_enabled"] = False

    return {
        "record_id": f"apollo:{contact_id}",
        "contact_number": number,
        "campaign": os.getenv("NIJA_APOLLO_CAMPAIGN", "NIJA Apollo Outbound").strip()
        or "NIJA Apollo Outbound",
        "call_stage": "initial",
        "contact_timezone": timezone_name,
        "dynamic_variables": _dynamic_variables(contact),
        "test_mode": False,
        **evidence,
    }, "ok"


def run_sync() -> dict[str, int]:
    cursor = _load_cursor()
    newest_seen = cursor
    counts = {
        "contacts_scanned": 0,
        "contacts_seen": 0,
        "website_leads_mirrored": 0,
        "website_leads_existing": 0,
        "website_lead_errors": 0,
        "website_lead_missing_email": 0,
        "queued_or_refreshed": 0,
        "missing_phone": 0,
        "missing_timezone": 0,
        "missing_contact_id": 0,
        "already_submitted": 0,
        "errors": 0,
    }

    for page in range(1, _pages_per_sync() + 1):
        response = _apollo_request(
            "/contacts/search",
            {
                "sort_by_field": "contact_updated_at",
                "sort_ascending": False,
                "per_page": 100,
                "page": page,
            },
        )
        contacts = response.get("contacts")
        if not isinstance(contacts, list) or not contacts:
            break

        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            counts["contacts_scanned"] += 1
            updated_at = str(contact.get("updated_at", "") or "")
            if updated_at and (not newest_seen or updated_at > newest_seen):
                newest_seen = updated_at

            mirror_result = _mirror_website_lead(contact)
            if mirror_result == "website_lead_mirrored":
                counts["website_leads_mirrored"] += 1
            elif mirror_result == "website_lead_existing":
                counts["website_leads_existing"] += 1
            elif mirror_result == "website_lead_error":
                counts["website_lead_errors"] += 1
            elif mirror_result == "website_lead_missing_email":
                counts["website_lead_missing_email"] += 1

            if cursor and updated_at and updated_at <= cursor:
                continue

            counts["contacts_seen"] += 1
            payload, reason = _contact_payload(contact)
            if payload is None:
                counts[reason] = counts.get(reason, 0) + 1
                continue
            try:
                result = enqueue_candidate(payload)
            except (OSError, ValueError):
                counts["errors"] += 1
                continue
            if result.get("duplicate_prevented"):
                counts["already_submitted"] += 1
            else:
                counts["queued_or_refreshed"] += 1

        if len(contacts) < 100:
            break

    _save_state(newest_seen, counts)
    return counts


def _worker() -> None:
    global _LAST_ERROR
    if not _enabled():
        print("APOLLO_NIJA_FEEDER state=disabled fail_closed=true", flush=True)
        return
    if not _api_key():
        _LAST_ERROR = "APOLLO_API_KEY_missing"
        print(
            "APOLLO_NIJA_FEEDER state=blocked reason=api_key_missing fail_closed=true",
            flush=True,
        )
        return
    print(
        f"APOLLO_NIJA_FEEDER state=ready poll_s={_poll_seconds():.0f} "
        f"max_pages={_pages_per_sync()} cold_contacts_call_ready=false "
        "website_lead_mirror=true fail_closed=true",
        flush=True,
    )
    while True:
        try:
            counts = run_sync()
            _LAST_ERROR = None
            print(
                "APOLLO_NIJA_FEEDER_SYNC "
                f"scanned={counts.get('contacts_scanned', 0)} "
                f"seen={counts.get('contacts_seen', 0)} "
                f"lead_mirrored={counts.get('website_leads_mirrored', 0)} "
                f"lead_existing={counts.get('website_leads_existing', 0)} "
                f"queued={counts.get('queued_or_refreshed', 0)} "
                f"missing_phone={counts.get('missing_phone', 0)} "
                f"errors={counts.get('errors', 0) + counts.get('website_lead_errors', 0)}",
                flush=True,
            )
        except Exception as exc:
            _LAST_ERROR = type(exc).__name__
            print(
                f"APOLLO_NIJA_FEEDER state=sync_error error={type(exc).__name__} fail_closed=true",
                flush=True,
            )
        time.sleep(_poll_seconds())


def start_apollo_feeder() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        _WORKER_STARTED = True
    threading.Thread(
        target=_worker,
        name="nija-apollo-feeder",
        daemon=True,
    ).start()


def status() -> dict[str, Any]:
    return {
        "enabled": _enabled(),
        "worker_started": _WORKER_STARTED,
        "api_key_configured": bool(_api_key()),
        "poll_seconds": _poll_seconds(),
        "max_pages_per_sync": _pages_per_sync(),
        "last_sync_at": _LAST_SYNC_AT,
        "last_error": _LAST_ERROR,
        "last_counts": _LAST_COUNTS,
        "website_lead_mirror": True,
        "website_lead_label_id_configured": bool(_website_lead_label_id()),
        "cold_contacts_call_ready": False,
        "requires_authoritative_consent_and_compliance_evidence": True,
        "fail_closed": True,
    }


def handle_apollo_feeder_get(handler: Any) -> bool:
    path = str(getattr(handler, "path", "") or "").split("?", 1)[0]
    if path != _STATUS_PATH:
        return False
    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    _send_json(handler, 200, status())
    return True


def handle_apollo_feeder_post(handler: Any) -> bool:
    path = str(getattr(handler, "path", "") or "").split("?", 1)[0]
    if path != _SYNC_PATH:
        return False
    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    if not _api_key():
        _send_json(handler, 503, {"error": "APOLLO_API_KEY is not configured"})
        return True
    try:
        counts = run_sync()
    except RuntimeError as exc:
        _send_json(handler, 502, {"error": str(exc)})
    except OSError:
        _send_json(handler, 503, {"error": "Apollo feeder storage unavailable"})
    else:
        _send_json(handler, 200, {"ok": True, "counts": counts})
    return True
