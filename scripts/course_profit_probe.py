"""Classify anonymous access to the optional profit-reporting API.

A disabled reporting service is safe but NOT proof that authorization works.
"""
def classify_profit_probe(code, payload):
    if code == 401 and isinstance(payload, dict) and payload.get("error") == "administrator_authorization_required":
        return "configured_auth_denied"
    if code == 503 and isinstance(payload, dict) and payload.get("status") == "unavailable" and payload.get("reason") == "profit_reporting_not_configured" and set(payload) <= {"status", "reason"}:
        return "reporting_disabled_fail_closed"
    return "failed"
