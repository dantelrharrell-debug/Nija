"""Isolated, fail-closed WSGI entrypoint for the legacy Nija Render web service.

This module intentionally imports no trading, broker, billing, customer, or
education packages. The historical public account-listing endpoint is NOT
restored; it remains unavailable until a separate authenticated design is
reviewed. Gunicorn can load this callable via ``nija_app:app``.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

_HEADERS = (
    ("Content-Type", "application/json; charset=utf-8"),
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)


def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
    """Serve minimal public liveness; never fetch or disclose private data."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()
    path = str(environ.get("PATH_INFO", ""))
    headers = list(_HEADERS)

    if method not in {"GET", "HEAD"}:
        status = "405 Method Not Allowed"
        headers.append(("Allow", "GET, HEAD"))
        payload = {"error": "method_not_allowed"}
    elif path in {"/health", "/healthz"}:
        status = "200 OK"
        payload = {"service": "nija", "status": "ok", "component": "http_liveness"}
    elif path == "/status":
        status = "200 OK"
        payload = {
            "service": "nija",
            "status": "maintenance",
            "account_listing": "disabled",
            "trading_execution": "not_available_here",
            "billing": "not_available_here",
        }
    elif path == "/":
        status = "503 Service Unavailable"
        payload = {"service": "nija", "status": "maintenance", "error": "private_account_listing_disabled"}
    else:
        status = "404 Not Found"
        payload = {"error": "not_found"}

    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers.append(("Content-Length", str(len(body))))
    start_response(status, headers)
    return [b"" if method == "HEAD" else body]
