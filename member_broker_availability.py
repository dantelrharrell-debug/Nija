"""Public capability check before issuing a new brokerage trial checkout."""
from __future__ import annotations

import requests


READINESS_URL = "https://nija-member-broker-api.onrender.com/readyz"


def member_broker_setup_available() -> bool:
    """Require both secure intake and verification; never send member data."""
    try:
        response = requests.get(
            READINESS_URL,
            timeout=3.0,
            allow_redirects=False,
            headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        )
        if response.status_code != 200:
            return False
        result = response.json()
        return (
            isinstance(result, dict)
            and result.get("status") == "ready"
            and result.get("credential_intake_enabled") is True
            and result.get("verification_enabled") is True
        )
    except (requests.RequestException, ValueError, TypeError):
        return False
