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
    """Legacy direct-call endpoint is disabled in favor of persistent screening."""
    return jsonify({
        "error": "Direct outbound AI calls disabled",
        "detail": "Use NIJA's vetted autodial queue with consent, DNC and local-hours checks.",
    }), 409
