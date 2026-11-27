#!/usr/bin/env python3
"""Read GA4 and Stripe into a PRIVATE provisional reconciliation candidate.

Run from the repository root using `python -m scripts.collect_website_profit_sources`.
Credentials are injected through the environment, never command arguments.
This utility does not sign evidence, deploy, or modify any provider resource.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from website_profit_sources import collect_ga4, collect_stripe


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Never forward authorization to a redirect destination."""
        return None


def _request(url: str, token: str, body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, method="GET" if body is None else "POST",
        headers={"Authorization": "Bearer " + token, "Accept": "application/json",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("Provider response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Invalid provider response")
        return result
    except (OSError, ValueError, urllib.error.URLError):
        # Do not include response bodies, request headers, or credential values.
        raise ValueError("Provider read failed; no completed candidate produced") from None


def main(argv: list[str] | None = None) -> int:
    """Collect a matching date window; print no candidate on any failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("property-id", "account-id", "start", "end", "timezone"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    google_token = os.environ.get("NIJA_PROFIT_GA4_ACCESS_TOKEN", "").strip()
    stripe_key = os.environ.get("NIJA_PROFIT_STRIPE_READ_KEY", "").strip()
    if not google_token or not stripe_key.startswith("rk_live_"):
        sys.stderr.write("Inject GA4 read-only access and a Stripe live restricted read-only key securely.\n")
        return 2

    def report(resource: str, body: dict) -> dict:
        return _request("https://analyticsdata.googleapis.com/v1beta/" + resource + ":runReport", google_token, body)

    def get(path: str, query: dict) -> dict:
        if path not in {"/v1/account", "/v1/balance_transactions"}:
            raise ValueError("Unsupported read path")
        suffix = "?" + urllib.parse.urlencode(query) if query else ""
        return _request("https://api.stripe.com" + path + suffix, stripe_key)

    try:
        window = dict(start=args.start, end=args.end, reporting_timezone=args.timezone)
        visitors = collect_ga4(report, property_id=args.property_id, **window)
        ledger = collect_stripe(get, expected_account_id=args.account_id, **window)
        candidate = {
            "schema": "nija-profit-source-observations-v1",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "verification_status": "PROVISIONAL", "ga4": visitors, "stripe": ledger,
            "costs_complete": False, "revenue_complete": False,
            "net_profit_usd": None, "net_profit_per_visitor_usd": None,
            "remaining": ["property/hostname coverage and consent review", "payment mode and product attribution",
                          "Shopify and other revenue sources", "refund/dispute and fee reconciliation",
                          "all attributable expenses", "independent finance reconciliation and signing"],
        }
        print(json.dumps(candidate, allow_nan=False, indent=2))
        return 0
    except Exception:
        # Provider and parser exceptions may contain private response content.
        sys.stderr.write("Source collection incomplete. No financial certification or candidate produced.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
