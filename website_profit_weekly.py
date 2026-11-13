"""Read-only, fail-closed weekly comparison of independently certified daily aggregates.

This module deliberately has no HTTP route, provider credentials, database writes,
or production deployment hook. The trusted importer must authenticate sources,
deduplicate events, and sign each day's evidence before these figures are usable.
"""
from __future__ import annotations

from datetime import date, timedelta
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
    # Unique persons cannot be calculated by summing daily unique counts.\n    # Accept only independently reconciled, period-wide deduplicated counts.\n    for field in ("unique_visitors", "qualified_leads", "waitlist_signups"):\n        totals.pop(field, None)\n        result[field] = None\n        if weekly_unique_counts and weekly_unique_counts.get("period_start") == result["start"] and weekly_unique_counts.get("period_end") == result["end"] and weekly_unique_counts.get("certified") is True and weekly_unique_counts.get("source_reconciled") is True:\n            value = _decimal(weekly_unique_counts.get(field))\n            if value is not None and value >= 0 and value == value.to_integral_value():\n                totals[field] = value\n                result[field] = int(value)\n    if len(totals) == len(FIELDS):
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
    """Compare two non-overlapping seven-day periods without imputing missing days."""
    return {
        "current": summarize_week(days, last_complete_day),
        "previous": summarize_week(days, last_complete_day - timedelta(days=7)),
    }
