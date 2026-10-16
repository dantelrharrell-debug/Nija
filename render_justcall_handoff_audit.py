"""Read-only proof of a completed JustCall AI warm transfer.

This audit fetches finished calls and their voice-agent actions from JustCall's
v2.1 API. It does not dial, alter an agent, expose contact details in logs, or
change NIJA_JUSTCALL_HUMAN_HANDOFF_VERIFIED. It explicitly distinguishes an
answered transfer from proof of the receiving person's identity.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from render_outreach_routes import (
    OutreachConfigurationError,
    OutreachProviderError,
    _provider_request,
)

_MAX_PAGES = 3
_PAGE_SIZE = 100
_MAX_ENRICH = 30


def _voice_agent_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Accept provider response wrappers; never interpret unrelated call data."""
    node: object = payload
    for _ in range(4):
        if not isinstance(node, dict):
            return None
        if "ai_agent_id" in node and isinstance(node.get("actions"), list):
            return node
        node = node.get("data")
    return None


def _answered_warm_transfer(payload: dict[str, Any], configured_agent: str) -> bool:
    """Require explicit success, warm mode, answered human-transfer destination.

    A transferred-to-AI number could also answer. This is transfer evidence,
    NOT independent verification that a human answered.
    """
    data = _voice_agent_data(payload)
    if not data or not configured_agent or data.get("ai_agent_id") != configured_agent:
        return False
    for action in data["actions"][:100]:
        if not isinstance(action, dict):
            continue
        output = action.get("output")
        if not isinstance(output, dict):
            continue
        if (
            str(action.get("type", "")).casefold() in ("call_transfer", "transfer_call")
            and str(action.get("status", "")).casefold() == "success"
            and str(output.get("mode", "")).casefold() == "warm"
            and output.get("is_answered") is True
        ):
            return True
    return False


def _call_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("success") is False or str(payload.get("status", "")).casefold() in ("error", "failed"):
        raise ValueError("provider_reported_failure")
    node: object = payload
    for _ in range(4):
        if not isinstance(node, dict):
            break
        for key in ("calls", "records", "items"):
            rows = node.get(key)
            if isinstance(rows, list):
                if not all(isinstance(row, dict) for row in rows):
                    raise ValueError("malformed_provider_calls")
                return rows
        value = node.get("data")
        if isinstance(value, list):
            if not all(isinstance(row, dict) for row in value):
                raise ValueError("malformed_provider_calls")
            return value
        node = value
    raise ValueError("unsupported_provider_calls_shape")


def _candidate(call: dict[str, Any]) -> bool:
    info = call.get("call_info")
    if not isinstance(info, dict):
        return False
    traits = info.get("call_traits", [])
    if isinstance(traits, str):
        traits = traits.split(",")
    if not isinstance(traits, list):
        return False
    normalized = {str(trait).strip().casefold().replace("_", " ") for trait in traits}
    return bool(normalized.intersection({"voice agent", "transfer"}))


def audit_recent_handoff(now_utc: datetime | None = None) -> dict[str, Any]:
    now_utc = now_utc or datetime.now(timezone.utc)
    agent_id = os.getenv("JUSTCALL_AI_AGENT_ID", "").strip()
    from render_outreach_routes import _AGENT_ID_RE
    if not _AGENT_ID_RE.fullmatch(agent_id):
        return {"state": "unverified", "reason": "selected_agent_id_missing_or_invalid"}
    from_date = (now_utc - timedelta(days=3)).date().isoformat()
    scanned = 0
    candidates = 0
    enriched = 0
    for page in range(_MAX_PAGES):
        query = urlencode({"from_datetime": from_date, "per_page": _PAGE_SIZE, "page": page})
        calls = _call_rows(_provider_request("GET", f"/calls?{query}"))
        scanned += len(calls)
        for call in calls:
            if not _candidate(call):
                continue
            candidates += 1
            if enriched >= _MAX_ENRICH:
                return {"state": "unverified", "reason": "enrichment_sample_limit",
                        "scanned": scanned, "candidates": candidates}
            call_id = str(call.get("id") or call.get("call_id") or call.get("call_sid") or "")
            if not call_id or len(call_id) > 100 or not all(ch.isalnum() or ch in "_-" for ch in call_id):
                return {"state": "unverified", "reason": "missing_call_id",
                        "scanned": scanned, "candidates": candidates}
            try:
                details = _provider_request("GET", f"/calls/{quote(call_id, safe='')}/voice-agent")
            except OutreachProviderError as exc:
                # This endpoint can return 404 for calls without processed
                # voice-agent metadata. Other failures invalidate the audit.
                if exc.status_code == 404:
                    continue
                raise
            enriched += 1
            if _answered_warm_transfer(details, agent_id):
                return {"state": "answered_warm_transfer", "provider_transfer_evidence": True,
                        "scanned": scanned, "candidates": candidates, "enriched": enriched,
                        "human_identity_independently_verified": False}
        if len(calls) < _PAGE_SIZE:
            return {"state": "unverified", "reason": "no_answered_warm_transfer_found",
                    "scanned": scanned, "candidates": candidates, "enriched": enriched}
    return {"state": "unverified", "reason": "call_sample_limit",
            "scanned": scanned, "candidates": candidates, "enriched": enriched}


import threading
import time

_HANDOFF_LOCK = threading.Lock()
_HANDOFF_STARTED = False


def _handoff_worker() -> None:
    while True:
        try:
            run_readonly_handoff_audit()
        except Exception as exc:
            # Provider response anomalies must not terminate the monitoring loop.
            # Never log exception text: upstream payloads may contain PII.
            print(
                f"JUSTCALL_HANDOFF_PROVIDER_AUDIT state=worker_error "
                f"error={type(exc).__name__} fail_closed=true",
                flush=True,
            )
        time.sleep(3600)


def start_readonly_handoff_audit() -> None:
    """Start a single hourly provider-evidence poll, with no outbound calls."""
    global _HANDOFF_STARTED
    with _HANDOFF_LOCK:
        if _HANDOFF_STARTED:
            return
        _HANDOFF_STARTED = True
    threading.Thread(
        target=_handoff_worker,
        name="nija-justcall-handoff-readonly",
        daemon=True,
    ).start()


def run_readonly_handoff_audit() -> dict[str, Any]:
    """Log only non-sensitive counts; never attest to a human recipient."""
    try:
        result = audit_recent_handoff()
    except (OutreachProviderError, OutreachConfigurationError) as exc:
        result = {"state": "unverified", "reason":
                  "provider_error_http_" + str(exc.status_code or "unknown")
                  if isinstance(exc, OutreachProviderError) else "credentials_missing"}
    except (ValueError, TypeError, OSError):
        result = {"state": "unverified", "reason": "unexpected_response_shape"}
    safe_state = result.get("state", "unverified")
    counts = [result.get(field, 0) for field in ("scanned", "candidates", "enriched")]
    print(
        "JUSTCALL_HANDOFF_PROVIDER_AUDIT "
        f"state={safe_state} "
        f"scanned={counts[0]} candidates={counts[1]} enriched={counts[2]} "
        f"answered_warm_transfer={str(result.get('provider_transfer_evidence') is True).lower()} "
        "human_identity_independently_verified=false "
        "production_handoff_flag_unchanged=true read_only=true",
        flush=True,
    )
    return result
