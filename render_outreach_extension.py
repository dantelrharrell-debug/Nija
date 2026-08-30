"""Signed webhook and compliance-gated campaign routes for NIJA outreach.

This module extends the stdlib Render front door without altering trading
readiness. Controlled test calls remain in render_outreach_routes; production
campaign calls pass stricter compliance attestations here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from render_outreach_routes import (
    OutreachConfigurationError,
    OutreachProviderError,
    _E164_RE,
    _MAX_BODY_BYTES,
    _provider_request,
    _resolve_agent_id,
    _send_json,
    _service_authorized,
)
from render_outreach_store import (
    is_suppressed,
    recent_calls,
    record_outbound_submission,
    record_webhook_event,
    set_suppression,
    webhook_status,
)

_WEBHOOK_PATH = "/api/justcall/webhook"
_ALLOWED_WEBHOOK_TYPES = {
    "call.initiated",
    "call.answered",
    "call.completed",
    "call.updated",
    "call.missed",
    "call.voicemail",
    "call.ai_voice_agent",
    "jc.call_ai_generated",
    "contact.status_updated",
}


def _path(handler: Any) -> str:
    return urllib.parse.urlsplit(str(getattr(handler, "path", "") or "")).path


def _read_raw_json(handler: Any) -> tuple[bytes, dict[str, Any]]:
    raw_length = str(handler.headers.get("Content-Length", "0") or "0")
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length") from exc
    if length <= 0:
        return b"", {}
    if length > _MAX_BODY_BYTES:
        raise ValueError("Request body is too large")
    raw = handler.rfile.read(length)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Request body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    return raw, payload


def _signature_valid(handler: Any, payload: dict[str, Any]) -> bool:
    signature = str(handler.headers.get("x-justcall-signature", "") or "").strip().lower()
    version = str(handler.headers.get("x-justcall-signature-version", "") or "").strip().lower()
    timestamp = str(handler.headers.get("x-justcall-request-timestamp", "") or "").strip()
    webhook_url = str(payload.get("webhook_url", "") or "").strip()
    event_type = str(payload.get("type", "") or "").strip()
    secret = os.getenv("JUSTCALL_API_SECRET", "").strip()
    if not all((signature, timestamp, webhook_url, event_type, secret)):
        return False
    if version and version != "v1":
        return False
    encoded_url = urllib.parse.quote(webhook_url, safe="")
    material = f"{secret}|{encoded_url}|{event_type}|{timestamp}"
    expected = hmac.new(secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _is_validation_probe(payload: dict[str, Any]) -> bool:
    # JustCall validates a newly-added webhook URL with an initial request. The
    # receiver may acknowledge structurally incomplete validation probes, but
    # only if they do not claim to be a normal supported call event.
    event_type = str(payload.get("type", "") or "").strip()
    request_id = str(payload.get("request_id", "") or "").strip()
    return not event_type and not request_id


def _recent_iso(value: object, *, max_age_seconds: int = 900) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return -60 <= age <= max_age_seconds


def _campaign_compliance_errors(body: dict[str, Any], contact_number: str) -> list[str]:
    errors: list[str] = []
    if body.get("has_consent") is not True:
        errors.append("verified_consent_required")
    if not str(body.get("consent_record_id", "") or "").strip():
        errors.append("consent_record_id_required")
    if not str(body.get("legal_basis", "") or "").strip():
        errors.append("legal_basis_required")
    if body.get("dnc_clear") is not True:
        errors.append("dnc_clear_required")
    if not _recent_iso(body.get("dnc_checked_at")):
        errors.append("fresh_dnc_check_required")
    if body.get("suppression_clear") is not True:
        errors.append("suppression_clear_required")
    if body.get("calling_window_allowed") is not True:
        errors.append("calling_window_not_verified")
    if body.get("campaign_enabled") is not True:
        errors.append("campaign_not_enabled")
    if body.get("duplicate_active_call") is not False:
        errors.append("duplicate_call_check_required")
    if body.get("test_mode") is not False:
        errors.append("campaign_endpoint_requires_test_mode_false")
    if is_suppressed(contact_number):
        errors.append("locally_suppressed")
    return errors


def _contact_status_suppression(payload: dict[str, Any]) -> None:
    if str(payload.get("type", "") or "") != "contact.status_updated":
        return
    data = payload.get("data")
    if not isinstance(data, dict):
        return
    number = str(
        data.get("contact_number")
        or data.get("phone")
        or data.get("phone_number")
        or ""
    ).strip()
    if not number:
        return
    serialized = json.dumps(data, separators=(",", ":")).lower()
    blocked = any(token in serialized for token in ("dnd", "dnm", "blacklist", "do_not_call", "do not call"))
    if blocked:
        set_suppression(
            contact_number=number,
            reason="JustCall contact status suppression",
            source="justcall_webhook",
            active=True,
        )


def handle_outreach_extension_get(handler: Any) -> bool:
    path = _path(handler)
    if path not in {"/api/justcall/webhook-status", "/api/justcall/recent-calls"}:
        return False
    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    try:
        if path.endswith("webhook-status"):
            payload = webhook_status()
            payload["signature_validation"] = "hmac_sha256_v1"
            payload["webhook_path"] = _WEBHOOK_PATH
        else:
            payload = {"calls": recent_calls(limit=20)}
    except Exception:
        _send_json(handler, 503, {"error": "Outreach event store unavailable"})
        return True
    _send_json(handler, 200, payload)
    return True


def handle_outreach_extension_post(handler: Any) -> bool:
    path = _path(handler)
    if path not in {_WEBHOOK_PATH, "/api/justcall/campaign-calls"}:
        return False

    if path == _WEBHOOK_PATH:
        try:
            _, payload = _read_raw_json(handler)
        except ValueError as exc:
            _send_json(handler, 400, {"error": str(exc)})
            return True

        if _is_validation_probe(payload):
            _send_json(handler, 200, {"ok": True, "validation": True})
            return True

        event_type = str(payload.get("type", "") or "").strip()
        if event_type not in _ALLOWED_WEBHOOK_TYPES:
            _send_json(handler, 200, {"ok": True, "ignored": True})
            return True
        if not _signature_valid(handler, payload):
            _send_json(handler, 401, {"error": "Invalid JustCall webhook signature"})
            return True
        try:
            result = record_webhook_event(payload)
            _contact_status_suppression(payload)
        except (OSError, ValueError):
            _send_json(handler, 503, {"error": "Unable to persist webhook event"})
            return True
        _send_json(handler, 200, result)
        return True

    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True
    try:
        _, body = _read_raw_json(handler)
    except ValueError as exc:
        _send_json(handler, 400, {"error": str(exc)})
        return True

    contact_number = str(body.get("contact_number", "") or "").strip()
    if not _E164_RE.fullmatch(contact_number):
        _send_json(handler, 422, {"error": "Phone number must be valid E.164"})
        return True

    compliance_errors = _campaign_compliance_errors(body, contact_number)
    if compliance_errors:
        _send_json(
            handler,
            422,
            {
                "error": "Campaign call blocked by compliance gate",
                "blockers": compliance_errors,
            },
        )
        return True

    variables = body.get("dynamic_variables") or []
    if not isinstance(variables, list) or len(variables) > 50:
        _send_json(handler, 422, {"error": "dynamic_variables must be an array of at most 50 items"})
        return True

    try:
        agent_id = _resolve_agent_id(str(body.get("ai_agent_id", "") or ""))
        provider_payload = _provider_request(
            "POST",
            "/voice-agents/calls",
            payload={
                "ai_agent_id": agent_id,
                "contact_number": contact_number,
                "dynamic_variables": variables,
                "has_consent": True,
            },
        )
        record_outbound_submission(
            contact_number=contact_number,
            record_id=str(body.get("record_id", "") or ""),
            campaign=str(body.get("campaign", "") or ""),
            provider_payload=provider_payload,
            request_payload=body,
        )
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
    except OutreachConfigurationError as exc:
        _send_json(handler, 503, {"error": str(exc)})
    except OutreachProviderError as exc:
        _send_json(handler, 502, {"error": str(exc), "provider_status": exc.status_code})
    except OSError:
        _send_json(handler, 503, {"error": "Outreach event store unavailable"})
    else:
        _send_json(handler, 200, provider_payload)
    return True
