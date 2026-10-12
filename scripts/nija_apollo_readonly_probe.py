"""Read-only NIJA Apollo credential and contact-scope diagnostics.

Run from the existing Render service shell:
    python scripts/nija_apollo_readonly_probe.py

This deliberately never prints an API key, personal information, contact IDs,
the raw API response, or exception text. It does not mutate Apollo or NIJA.
Requires only the Python standard library and an existing APOLLO_API_KEY.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

_BASE = "https://api.apollo.io/api/v1"
_EXPECTED_NIJA_TEAM = "6a92e744cf82cd0010f5753c"


def _safe_request(path: str, *, data: dict | None = None) -> dict:
    """Return bounded JSON or a non-sensitive error category."""
    key = os.getenv("APOLLO_API_KEY", "").strip()
    if not key:
        return {"_error": "key_missing"}
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        _BASE + path,
        data=payload,
        headers={
            "x-api-key": key,
            "accept": "application/json",
            "content-type": "application/json",
            "user-agent": "NIJA-ReadOnly-Apollo-Probe/1.0",
        },
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12.0) as response:
            raw = response.read(100000)
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {"_error": "unexpected_json_shape"}
    except urllib.error.HTTPError as exc:
        return {"_error": f"http_{int(exc.code)}"}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {"_error": "network_unavailable"}
    except (UnicodeError, ValueError):
        return {"_error": "invalid_json"}


def check() -> dict:
    """Show only health, scope and counts; no identifying contact fields."""
    if not os.getenv("APOLLO_API_KEY", "").strip():
        return {"key_present": False, "status": "blocked_missing_key"}

    health = _safe_request("/auth/health")
    healthy = health.get("healthy") is True and health.get("is_logged_in") is True
    health_state = "healthy" if healthy else str(health.get("_error") or "not_healthy")

    profile = _safe_request("/users/api_profile")
    user = profile.get("user") if isinstance(profile.get("user"), dict) else profile
    team_id = user.get("team_id") if isinstance(user, dict) else None
    profile_state = (
        str(profile["_error"]) if "_error" in profile else
        ("expected_workspace" if team_id == _EXPECTED_NIJA_TEAM else
         "other_workspace" if isinstance(team_id, str) and team_id else "unverifiable")
    )

    # Read one saved contact, never print its content or identifying fields.
    contacts = _safe_request(
        "/contacts/search",
        data={
            "sort_by_field": "contact_updated_at",
            "sort_ascending": False,
            "per_page": 1,
            "page": 1,
        },
    )
    if "_error" in contacts:
        search_state = str(contacts["_error"])
        total = None
    elif not isinstance(contacts.get("contacts"), list):
        search_state, total = "invalid_contacts_response", None
    else:
        pagination = contacts.get("pagination")
        total = pagination.get("total_entries") if isinstance(pagination, dict) else None
        total = total if isinstance(total, int) and not isinstance(total, bool) else None
        search_state = "returned_contacts" if contacts["contacts"] else "zero_contacts"

    return {
        "key_present": True,
        "auth": health_state,
        "profile": profile_state,
        "contacts_search": search_state,
        "saved_contacts_reported": total,
        "status": (
            "ok" if healthy and profile_state == "expected_workspace"
            and search_state == "returned_contacts" else "requires_review"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
