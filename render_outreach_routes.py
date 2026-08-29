"""Protected JustCall outreach routes for NIJA's Render front-door server.

This module is intentionally stdlib-only because ``render_liveness_server.py``
runs under ``python -S`` before NIJA's trading runtime imports site packages.
It exposes only server-to-server outreach endpoints protected by
``NIJA_OUTREACH_SERVICE_TOKEN`` and never logs or returns provider credentials.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

JUSTCALL_API_BASE = "https://api.justcall.io/v2.1"
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_AGENT_ID_RE = re.compile(r"^agent_[A-Za-z0-9_-]+$")
_MAX_BODY_BYTES = 32768


class OutreachConfigurationError(RuntimeError):
    pass


class OutreachProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _path(handler: Any) -> str:
    return urllib.parse.urlsplit(str(getattr(handler, "path", "") or "")).path


def _send_json(handler: Any, status_code: int, payload_obj: dict[str, Any]) -> None:
    payload = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
    try:
        handler.send_response(status_code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(payload)
    except (BrokenPipeError, ConnectionResetError):
        return


def _service_authorized(handler: Any) -> tuple[bool, int, str]:
    expected = os.getenv("NIJA_OUTREACH_SERVICE_TOKEN", "").strip()
    if not expected:
        return False, 503, "Outreach service authentication is not configured"
    provided = str(handler.headers.get("X-NIJA-Outreach-Token", "") or "")
    if not provided or not hmac.compare_digest(expected, provided):
        return False, 401, "Unauthorized"
    return True, 200, "ok"


def _credentials() -> tuple[str, str]:
    api_key = os.getenv("JUSTCALL_API_KEY", "").strip()
    api_secret = os.getenv("JUSTCALL_API_SECRET", "").strip()
    if not api_key or not api_secret:
        raise OutreachConfigurationError(
            "JUSTCALL_API_KEY and JUSTCALL_API_SECRET must be configured as deployment secrets"
        )
    return api_key, api_secret


def _timeout_seconds() -> float:
    raw = os.getenv("JUSTCALL_API_TIMEOUT_SECONDS", "15").strip()
    try:
        return max(1.0, min(float(raw), 60.0))
    except ValueError:
        return 15.0


def _provider_request(
    method: str,
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    api_key, api_secret = _credentials()
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{JUSTCALL_API_BASE}{path}",
        data=body,
        headers={
            "Authorization": f"{api_key}:{api_secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "NIJA-Outreach-Render/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
            response_body = response.read()
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        # Provider bodies can contain phone/contact data. Do not echo them.
        raise OutreachProviderError(
            f"JustCall API request failed with HTTP {exc.code}",
            status_code=int(exc.code),
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OutreachProviderError("Unable to reach JustCall API") from exc

    if not 200 <= status < 300:
        raise OutreachProviderError(
            f"JustCall API request failed with HTTP {status}",
            status_code=status,
        )
    if not response_body:
        return {}
    try:
        decoded = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OutreachProviderError(
            "JustCall returned an invalid JSON response",
            status_code=status,
        ) from exc
    if not isinstance(decoded, dict):
        raise OutreachProviderError("JustCall returned an unexpected response format")
    return decoded


def _list_voice_agents(*, per_page: int = 100) -> dict[str, Any]:
    per_page = max(1, min(int(per_page), 100))
    return _provider_request(
        "GET",
        f"/voice-agents/list?page=0&per_page={per_page}&order=desc",
    )


def _collect_agent_ids(value: object) -> set[str]:
    """Collect JustCall AI-agent identifiers without depending on response nesting."""
    found: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            found.update(_collect_agent_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_agent_ids(item))
    elif isinstance(value, str) and _AGENT_ID_RE.fullmatch(value):
        found.add(value)
    return found


def _resolve_agent_id(explicit_agent_id: str = "") -> str:
    explicit = str(explicit_agent_id or "").strip()
    if explicit:
        if not _AGENT_ID_RE.fullmatch(explicit):
            raise ValueError("Invalid JustCall AI agent ID format")
        return explicit

    configured = os.getenv("JUSTCALL_AI_AGENT_ID", "").strip()
    if configured:
        if not _AGENT_ID_RE.fullmatch(configured):
            raise OutreachConfigurationError("JUSTCALL_AI_AGENT_ID has an invalid format")
        return configured

    agents = _list_voice_agents(per_page=100)
    agent_ids = sorted(_collect_agent_ids(agents))
    if len(agent_ids) == 1:
        return agent_ids[0]
    if not agent_ids:
        raise OutreachConfigurationError(
            "No JustCall AI Voice Agent is available; create or enable an outbound AI agent"
        )
    raise OutreachConfigurationError(
        "Multiple JustCall AI Voice Agents are available; set JUSTCALL_AI_AGENT_ID explicitly"
    )


def _read_json_body(handler: Any) -> dict[str, Any]:
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


def handle_outreach_get(handler: Any) -> bool:
    """Handle a protected JustCall GET route; return whether the path matched."""
    path = _path(handler)
    if path not in {"/api/justcall/status", "/api/justcall/voice-agents"}:
        return False

    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True

    if path == "/api/justcall/status":
        configured = bool(
            os.getenv("JUSTCALL_API_KEY", "").strip()
            and os.getenv("JUSTCALL_API_SECRET", "").strip()
        )
        result: dict[str, Any] = {
            "configured": configured,
            "authenticated": False,
            "ai_agent_configured": bool(os.getenv("JUSTCALL_AI_AGENT_ID", "").strip()),
            "outbound_number_configured": bool(
                os.getenv("JUSTCALL_OUTBOUND_NUMBER", "").strip()
            ),
        }
        if not configured:
            result["state"] = "credentials_missing"
            _send_json(handler, 503, result)
            return True
        try:
            agents = _list_voice_agents(per_page=100)
            agent_ids = sorted(_collect_agent_ids(agents))
        except OutreachProviderError as exc:
            result["state"] = "authentication_or_api_failed"
            result["provider_status"] = exc.status_code
            _send_json(handler, 503, result)
            return True
        except OutreachConfigurationError:
            result["state"] = "credentials_missing"
            _send_json(handler, 503, result)
            return True

        result.update(
            {
                "authenticated": True,
                "state": "connected",
                "voice_agents_response_received": bool(agents),
                "voice_agent_count": len(agent_ids),
                "voice_agent_auto_resolvable": len(agent_ids) == 1,
            }
        )
        _send_json(handler, 200, result)
        return True

    try:
        payload = _list_voice_agents(per_page=100)
    except OutreachConfigurationError as exc:
        _send_json(handler, 503, {"error": str(exc)})
    except OutreachProviderError as exc:
        _send_json(
            handler,
            502,
            {"error": str(exc), "provider_status": exc.status_code},
        )
    else:
        _send_json(handler, 200, payload)
    return True


def handle_outreach_post(handler: Any) -> bool:
    """Handle a protected JustCall POST route; return whether the path matched."""
    if _path(handler) != "/api/justcall/calls":
        return False

    authorized, status_code, detail = _service_authorized(handler)
    if not authorized:
        _send_json(handler, status_code, {"error": detail})
        return True

    try:
        body = _read_json_body(handler)
    except ValueError as exc:
        _send_json(handler, 400, {"error": str(exc)})
        return True

    if body.get("has_consent") is not True:
        _send_json(
            handler,
            422,
            {
                "error": "Outbound AI call blocked",
                "detail": "A verified consent record is required before has_consent can be true",
            },
        )
        return True

    contact_number = str(body.get("contact_number", "") or "").strip()
    if not _E164_RE.fullmatch(contact_number):
        _send_json(
            handler,
            422,
            {"error": "Phone number must be in E.164 format, for example +15551234567"},
        )
        return True

    variables = body.get("dynamic_variables") or []
    if not isinstance(variables, list):
        _send_json(handler, 422, {"error": "dynamic_variables must be an array"})
        return True
    if len(variables) > 50:
        _send_json(handler, 422, {"error": "Too many dynamic variables"})
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
    except ValueError as exc:
        _send_json(handler, 422, {"error": str(exc)})
    except OutreachConfigurationError as exc:
        _send_json(handler, 503, {"error": str(exc)})
    except OutreachProviderError as exc:
        _send_json(
            handler,
            502,
            {"error": str(exc), "provider_status": exc.status_code},
        )
    else:
        _send_json(handler, 200, provider_payload)
    return True
