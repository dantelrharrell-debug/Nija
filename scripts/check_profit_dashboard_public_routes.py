"""Read-only smoke probe for NIJA's public profit dashboard routes.

Never accepts or sends credentials. Does not attest financial correctness.
Run: python scripts/check_profit_dashboard_public_routes.py
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DEFAULT_ORIGIN = "https://nija-billing-api.onrender.com"


def probe(origin: str = DEFAULT_ORIGIN) -> dict:
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Expected an HTTPS origin without credentials, path or query")
    results = {}
    for name, path in (
        ("dashboard", "/admin/revenue-per-visitor"),
        ("profit_api_without_credentials", "/api/admin/website-profit?period=2026-10"),
    ):
        request = Request(origin.rstrip("/") + path, headers={"Accept": "text/html,application/json", "User-Agent": "NIJA-Profit-ReadOnly-Probe/1.0"}, method="GET")
        try:
            with urlopen(request, timeout=12) as response:
                status = response.status
                cache_control = response.headers.get("Cache-Control", "")
                content_type = response.headers.get("Content-Type", "")
        except HTTPError as error:
            status = error.code
            cache_control = error.headers.get("Cache-Control", "")
            content_type = error.headers.get("Content-Type", "")
            error.close()
        results[name] = {"http_status": status, "cache_control": cache_control, "content_type": content_type}
    results["interpretation"] = (
        "No private evidence tested. HTTP 200 on dashboard means static shell only. "
        "HTTP 503 on unauthenticated API may indicate missing reporting configuration; "
        "HTTP 401 means authentication gate is configured. Neither proves financial reconciliation."
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    args = parser.parse_args()
    try:
        result = probe(args.origin)
    except (ValueError, URLError, TimeoutError, OSError) as error:
        print(json.dumps({"status": "probe_failed", "error_type": type(error).__name__}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["dashboard"]["http_status"] == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
