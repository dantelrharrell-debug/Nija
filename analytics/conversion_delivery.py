"""Opt-in GA4 Measurement Protocol delivery of previously verified events.

Not wired to billing or website handlers. Caller must enforce consent,
attribution provenance and verified event eligibility before staging.
No outbound request occurs without explicit configuration and invocation.
"""
import re

import requests

_ALLOWED = {"nija_verified_lead", "nija_verified_course_purchase"}
_CLIENT_ID = re.compile(r"^[0-9]{1,20}\.[0-9]{1,20}$")


class DeliveryDisabled(RuntimeError):
    pass


def deliver_ga4(event, *, client_id, measurement_id, api_secret,
                enabled=False, transport=None):
    """Return True only on GA4 transport acceptance, never on event creation.

    HTTP 2xx is not proof of analytics reporting or Google Ads attribution.
    The caller must atomically claim before calling, and acknowledge only after
    True. Uncertain outcomes require reconciliation, not blind retries.
    """
    if not enabled:
        raise DeliveryDisabled("ga4_conversion_delivery_disabled")
    if not isinstance(event, dict) or event.get("event_name") not in _ALLOWED:
        raise ValueError("unsupported_conversion_event")
    if not isinstance(client_id, str) or not _CLIENT_ID.fullmatch(client_id):
        raise ValueError("invalid_client_id")
    if not isinstance(measurement_id, str) or not re.fullmatch(r"G-[A-Z0-9]{5,20}", measurement_id):
        raise ValueError("invalid_measurement_id")
    if not isinstance(api_secret, str) or not api_secret.strip():
        raise ValueError("missing_api_secret")
    params = event.get("parameters")
    if not isinstance(params, dict):
        raise ValueError("invalid_event_parameters")
    if event["event_name"] == "nija_verified_course_purchase":
        if not isinstance(params.get("transaction_id"), str) or not params["transaction_id"].startswith("cs_"):
            raise ValueError("missing_transaction_id")
        if params.get("currency") != "USD" or params.get("value") != 99.0:
            raise ValueError("invalid_course_value")
        safe = {key: params[key] for key in ("transaction_id", "currency", "value")}
    else:
        safe = {"lead_type": "website"}
    sender = transport or requests
    response = sender.post(
        "https://www.google-analytics.com/mp/collect",
        params={"measurement_id": measurement_id, "api_secret": api_secret},
        json={"client_id": client_id, "events": [{"name": event["event_name"], "params": safe}]},
        timeout=8,
    )
    response.raise_for_status()
    return 200 <= response.status_code < 300
