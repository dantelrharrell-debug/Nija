"""Internal NIJA HTTP bridge for JustCall outreach workflows."""

from __future__ import annotations

import hmac
import os
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from justcall_client import JustCallAPIError, JustCallClient, JustCallConfigurationError

justcall_api = Blueprint("justcall_api", __name__, url_prefix="/api/justcall")


def _service_authorized() -> bool:
    expected = os.getenv("NIJA_OUTREACH_SERVICE_TOKEN", "")
    provided = request.headers.get("X-NIJA-Outreach-Token", "")
    return bool(expected) and bool(provided) and hmac.compare_digest(expected, provided)


@justcall_api.before_request
def justcall_service_authentication():
    if request.method == "OPTIONS":
        return None
    if not os.getenv("NIJA_OUTREACH_SERVICE_TOKEN", ""):
        return jsonify({"error": "Outreach service authentication is not configured"}), 503
    if not _service_authorized():
        return jsonify({"error": "Unauthorized"}), 401
    return None


@justcall_api.get("/status")
def status():
    result = JustCallClient().connection_status()
    return jsonify(result), 200 if result.get("authenticated") else 503


@justcall_api.get("/voice-agents")
def voice_agents():
    try:
        return jsonify(JustCallClient().list_voice_agents()), 200
    except JustCallConfigurationError as exc:
        return jsonify({"error": str(exc)}), 503
    except JustCallAPIError as exc:
        return jsonify({"error": str(exc), "provider_status": exc.status_code}), 502


@justcall_api.post("/calls")
def initiate_call():
    body: Dict[str, Any] = request.get_json(silent=True) or {}
    if body.get("has_consent") is not True:
        return jsonify({
            "error": "Outbound AI call blocked",
            "detail": "A verified consent record is required before has_consent can be true",
        }), 422

    try:
        payload = JustCallClient().initiate_ai_call(
            contact_number=str(body.get("contact_number", "")),
            has_consent=True,
            ai_agent_id=str(body["ai_agent_id"]) if body.get("ai_agent_id") else None,
            dynamic_variables=body.get("dynamic_variables") or [],
        )
        return jsonify(payload), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except JustCallConfigurationError as exc:
        return jsonify({"error": str(exc)}), 503
    except JustCallAPIError as exc:
        return jsonify({"error": str(exc), "provider_status": exc.status_code}), 502
