"""Read-only provider observations for independent website-profit reconciliation.

No signing, certification, HTTP routes, scheduled jobs or provider writes.
An authenticated caller supplies read-only transports; credentials never enter
the returned data. Observations are NOT evidence that all NIJA sales/costs exist.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

PRODUCTION_HOSTS = (
    "nijaaitrading.com", "www.nijaaitrading.com",
    "shop.nijaaitrading.com", "game.nijaaitrading.com",
)


def _window(start: str, end: str, reporting_timezone: str) -> tuple[int, int]:
    """Validate complete inclusive calendar days; return half-open timestamps."""
    zone = ZoneInfo(reporting_timezone)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.isoformat() != start or last.isoformat() != end:
        raise ValueError("Use ISO calendar dates")
    if first > last or last >= datetime.now(zone).date():
        raise ValueError("Only complete past calendar days are supported")
    return (
        int(datetime.combine(first, time.min, zone).timestamp()),
        int(datetime.combine(last + timedelta(days=1), time.min, zone).timestamp()),
    )


def collect_ga4(
    run_report: Callable[[str, dict], dict], *, property_id: str,
    start: str, end: str, reporting_timezone: str,
) -> dict:
    """Request one deduplicated total across production hosts, never sum users.

    run_report performs the authenticated read-only Data API runReport call.
    Its OAuth scope must be analytics.readonly. A successful response still
    requires property coverage, consent, identity and bot-quality review.
    """
    _window(start, end, reporting_timezone)
    if not re.fullmatch(r"[0-9]+", property_id):
        raise ValueError("Invalid GA4 property identity")
    body = {
        "dateRanges": [{"startDate": start, "endDate": end}],
        "metrics": [{"name": "totalUsers"}],
        "dimensionFilter": {"filter": {
            "fieldName": "hostName",
            "inListFilter": {"values": list(PRODUCTION_HOSTS), "caseSensitive": False},
        }},
        "limit": "1",
    }
    response = run_report("properties/" + property_id, body)
    if not isinstance(response, dict):
        raise ValueError("Invalid GA4 response")
    metadata = response.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("timeZone") != reporting_timezone:
        raise ValueError("GA4 property timezone must match the requested window")
    if (metadata.get("subjectToThresholding") or metadata.get("dataLossFromOtherRow")
            or metadata.get("samplingMetadatas")):
        raise ValueError("GA4 data quality requires review")
    if response.get("dimensionHeaders"):
        raise ValueError("Grouped user counts cannot be added into unique visitors")
    if response.get("metricHeaders") != [{"name": "totalUsers", "type": "TYPE_INTEGER"}]:
        raise ValueError("GA4 metric identity mismatch")
    rows = response.get("rows", [])
    if not isinstance(rows, list) or len(rows) > 1 or response.get("rowCount", 0) != len(rows):
        raise ValueError("Incomplete GA4 aggregate")
    if rows:
        if not isinstance(rows[0], dict):
            raise ValueError("Invalid GA4 aggregate row")
        values = rows[0].get("metricValues")
        if (not isinstance(values, list) or len(values) != 1
                or not isinstance(values[0], dict)):
            raise ValueError("Invalid GA4 metric values")
        raw = values[0].get("value")
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,13}", raw):
            raise ValueError("Invalid GA4 totalUsers")
        users = int(raw)
    else:
        users = 0
    return {
        "provider": "ga4", "property_id": property_id,
        "start": start, "end": end, "timezone": reporting_timezone,
        "hostname_filter": list(PRODUCTION_HOSTS), "observed_total_users": users,
        "verification_status": "PROVISIONAL",
        "visitor_counts_verified": False, "analytics_consent_verified": False,
    }


def collect_stripe(
    get: Callable[[str, dict], dict], *, expected_account_id: str,
    start: str, end: str, reporting_timezone: str, max_pages: int = 1000,
) -> dict:
    """Collect every balance transaction in a window, with no revenue guessing.

    get performs authenticated GETs ONLY against api.stripe.com. Use a live
    restricted read-only key and verify its mode in the secure caller. This
    transport contract is not production authentication or a live-mode proof.
    Payouts, top-ups and transfers remain separate rows, never customer revenue.
    """
    lower, upper = _window(start, end, reporting_timezone)
    if not re.fullmatch(r"acct_[A-Za-z0-9]+", expected_account_id):
        raise ValueError("Invalid Stripe account identity")
    if type(max_pages) is not int or not 1 <= max_pages <= 1000:
        raise ValueError("Invalid Stripe pagination limit")
    account = get("/v1/account", {})
    if not isinstance(account, dict) or account.get("id") != expected_account_id:
        raise ValueError("Stripe account identity mismatch")
    query = {"limit": 100, "created[gte]": lower, "created[lt]": upper}
    rows, seen = [], set()
    allowed = ("id", "created", "amount", "fee", "net", "currency", "source", "type", "reporting_category")
    for _ in range(max_pages):
        page = get("/v1/balance_transactions", dict(query))
        if (not isinstance(page, dict) or page.get("object") != "list"
                or type(page.get("has_more")) is not bool
                or not isinstance(page.get("data"), list)):
            raise ValueError("Invalid Stripe page")
        data = page["data"]
        if len(data) > 100 or (page["has_more"] and not data):
            raise ValueError("Incomplete Stripe pagination")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Invalid Stripe transaction")
            identity = item.get("id")
            if not isinstance(identity, str) or not re.fullmatch(r"txn_[A-Za-z0-9]+", identity):
                raise ValueError("Invalid Stripe transaction identity")
            if identity in seen:
                raise ValueError("Repeated Stripe page or transaction")
            if any(type(item.get(k)) is not int for k in ("created", "amount", "fee", "net")):
                raise ValueError("Stripe amounts must be integer minor units")
            if not lower <= item["created"] < upper:
                raise ValueError("Stripe transaction outside reporting window")
            if item["net"] != item["amount"] - item["fee"]:
                raise ValueError("Stripe amount/fee/net mismatch")
            if not isinstance(item.get("currency"), str) or not re.fullmatch(r"[a-z]{3}", item["currency"]):
                raise ValueError("Invalid Stripe currency")
            if any(not isinstance(item.get(k), str) or not item[k] for k in ("type", "reporting_category")):
                raise ValueError("Missing Stripe accounting classification")
            source = item.get("source")
            if source is not None and not isinstance(source, str):
                raise ValueError("Expanded Stripe source is not allowed")
            rows.append({key: item.get(key) for key in allowed})
            seen.add(identity)
        if not page["has_more"]:
            return {
                "provider": "stripe", "account_id": expected_account_id,
                "start": start, "end": end, "timezone": reporting_timezone,
                "pagination_complete": True, "transactions": rows,
                "amount_unit": "currency_minor_units", "verification_status": "PROVISIONAL",
                "provider_revenue_verified": False, "livemode_verified": False,
                "revenue_complete": False, "costs_complete": False,
                "net_profit_usd": None, "net_profit_per_visitor_usd": None,
            }
        query["starting_after"] = data[-1]["id"]
    raise ValueError("Stripe pagination limit reached; collection is incomplete")
