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
WEEKLY_UNIQUE_FIELDS = ("unique_visitors", "qualified_leads", "waitlist_signups")


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite() or result.copy_abs() >= Decimal("1e18"):
        return None
    # Leave room for exact seven-day aggregation and cent rounding.
    return result if result.as_tuple().exponent >= -6 else None


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
    if len(days) != 7 or not all(
        isinstance(item, dict) and isinstance(item.get("date"), str) for item in days
    ):
        return result
    if {item["date"] for item in days} != expected:
        return result
    if not all(item.get("certified") is True and item.get("source_reconciled") is True
               and item.get("analytics_consent_verified") is True for item in days):
        return result
    totals: dict[str, Decimal] = {}
    lower_bounds: dict[str, Decimal] = {}
    for field in FIELDS:
        parsed = [_decimal(item.get(field)) for item in days]
        values = [value for value in parsed if value is not None and value >= 0]
        if len(values) != len(days):
            continue
        if field in COUNTS and any(value != value.to_integral_value() for value in values):
            continue
        totals[field] = sum(values, Decimal(0))
        if field in WEEKLY_UNIQUE_FIELDS:
            lower_bounds[field] = max(values)
        result[field] = int(totals[field]) if field in COUNTS else str(totals[field])
    # The union can be no smaller than any day or larger than the sum of all days.
    # These are consistency checks; the deduplicated weekly count still needs its own evidence.
    for field in WEEKLY_UNIQUE_FIELDS:
        upper_bound = totals.pop(field, None)
        result[field] = None
        if (upper_bound is not None and isinstance(weekly_unique_counts, dict)
                and weekly_unique_counts.get("period_start") == result["start"]
                and weekly_unique_counts.get("period_end") == result["end"]
                and weekly_unique_counts.get("certified") is True
                and weekly_unique_counts.get("source_reconciled") is True):
            value = _decimal(weekly_unique_counts.get(field))
            if (value is not None and lower_bounds[field] <= value <= upper_bound
                    and value == value.to_integral_value()):
                totals[field] = value
                result[field] = int(value)
    if len(totals) == len(FIELDS):
        result["verification_status"] = "VERIFIED"
        profit = totals["attributable_revenue_usd"] - totals["attributable_costs_usd"]
        result["net_profit_usd"] = str(profit)
        if totals["unique_visitors"] > 0:
            ratio = profit / totals["unique_visitors"]
            result["net_profit_per_visitor_usd"] = str(ratio.quantize(Decimal("0.01")))
            result["target_met"] = profit >= totals["unique_visitors"]
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
    valid_dates = (len(actual) == 14 and all(isinstance(value, str) for value in actual)
                   and set(actual) == expected)
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
