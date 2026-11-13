"""Read-only, fail-closed weekly comparison of independently certified daily aggregates.

This module deliberately has no HTTP route, provider credentials, database writes,
or production deployment hook. The trusted importer must authenticate sources,
deduplicate events, and sign each day's evidence before these figures are usable.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

COUNTS = ("unique_visitors", "qualified_leads", "waitlist_signups", "course_purchases")
MONEY = ("attributable_revenue_usd", "attributable_costs_usd")
FIELDS = COUNTS + MONEY


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def summarize_week(days: list[dict[str, Any]], end: date, weekly_unique_counts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Only return certified totals when seven distinct complete dates are present.

    The calling trusted process must verify evidence signatures independently.
    'certified' here denotes an attestation from that process, not cryptographic
    verification performed by this function.
    """
    expected = {(end - timedelta(days=offset)).isoformat() for offset in range(7)}
    result: dict[str, Any] = {"start": (end - timedelta(days=6)).isoformat(),
                              "end": end.isoformat(), "verification_status": "UNVERIFIED"}
    result.update({field: None for field in FIELDS})
    result["net_profit_usd"] = None
    result["net_profit_per_visitor_usd"] = None
    result["target_met"] = None
    if len(days) != 7 or {item.get("date") for item in days if isinstance(item, dict)} != expected:
        return result
    if not all(item.get("certified") is True and item.get("source_reconciled") is True
               and item.get("analytics_consent_verified") is True for item in days):
        return result
    totals = {}
    for field in FIELDS:
        values = [_decimal(item.get(field)) for item in days]
        if any(value is None or value < 0 for value in values):
            continue
        if field in COUNTS and any(value != value.to_integral_value() for value in values):
            continue
        totals[field] = sum(values, Decimal(0))
        result[field] = int(totals[field]) if field in COUNTS else str(totals[field])
    # Daily unique counts are not additive across a week.
    for field in ("unique_visitors", "qualified_leads", "waitlist_signups"):
        totals.pop(field, None)
        result[field] = None
        if (isinstance(weekly_unique_counts, dict)
                and weekly_unique_counts.get("period_start") == result["start"]
                and weekly_unique_counts.get("period_end") == result["end"]
                and weekly_unique_counts.get("certified") is True
                and weekly_unique_counts.get("source_reconciled") is True):
            value = _decimal(weekly_unique_counts.get(field))
            if value is not None and value >= 0 and value == value.to_integral_value():
                totals[field] = value
                result[field] = int(value)
    if len(totals) == len(FIELDS):
        result["verification_status"] = "VERIFIED"
        profit = totals["attributable_revenue_usd"] - totals["attributable_costs_usd"]
        result["net_profit_usd"] = str(profit)
        if totals["unique_visitors"] > 0:
            ratio = profit / totals["unique_visitors"]
            result["net_profit_per_visitor_usd"] = str(ratio.quantize(Decimal("0.01")))
            result["target_met"] = ratio >= Decimal("1.00")
    else:
        result["verification_status"] = "PARTIAL"
    return result


def compare_weeks(days: list[dict[str, Any]], last_complete_day: date, weekly_unique_counts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compare exactly two complete, non-overlapping seven-day periods."""
    if not isinstance(last_complete_day, date) or isinstance(last_complete_day, datetime):
        raise ValueError("last_complete_day must be a date")
    if not isinstance(days, list) or not all(isinstance(row, dict) for row in days):
        raise ValueError("days must be a list of daily records")
    if weekly_unique_counts is not None and (
            not isinstance(weekly_unique_counts, list)
            or not all(isinstance(row, dict) for row in weekly_unique_counts)):
        raise ValueError("weekly_unique_counts must be a list of records")

    previous_end = last_complete_day - timedelta(days=7)
    expected = {(last_complete_day - timedelta(days=i)).isoformat() for i in range(14)}
    actual = [row.get("date") for row in days]
    valid_dates = (len(actual) == 14 and len(set(actual)) == 14
                   and set(actual) == expected
                   and all(isinstance(value, str) for value in actual))
    counts = weekly_unique_counts or []

    def period(end: date) -> dict[str, Any]:
        start = (end - timedelta(days=6)).isoformat()
        end_str = end.isoformat()
        subset = [row for row in days if isinstance(row.get("date"), str)
                  and start <= row["date"] <= end_str] if valid_dates else []
        matches = [row for row in counts
                   if row.get("period_start") == start and row.get("period_end") == end_str]
        evidence = matches[0] if len(matches) == 1 else None
        return summarize_week(subset, end, evidence)

    return {"current": period(last_complete_day),
            "previous": period(previous_end)}
