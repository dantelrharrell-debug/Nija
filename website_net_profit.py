"""Evidence-gated monthly net profitability for NIJA website acquisition.

Requires period-matched visitor, lead, verified revenue/refund, and approved
cost evidence. Never guess expenses or promote incomplete estimates to profit.
Only the server-side reconciliation process may set the completeness flags.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from website_revenue_attribution import summarize

COST_CATEGORIES = frozenset({
    "advertising", "payment_processing", "refund_handling", "hosting",
    "course_fulfillment", "customer_support", "software", "affiliate_payout",
    "chargeback_fee", "other_operating"
})


def _cents(amount: object) -> int:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid cost amount") from None
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
        raise ValueError("Costs require nonnegative USD amounts with at most two decimals")
    return int(value * 100)


def _usd(cents: int) -> str:
    return str((Decimal(cents) / 100).quantize(Decimal("0.01")))


def net_profit_report(
    revenue_events,
    cost_events,
    *,
    reporting_period: str,
    revenue_complete: bool = False,
    costs_complete: bool = False,
) -> dict:
    """Produce 2 independent net-profit ratios for a single calendar month.

    Events MUST contain `period: YYYY-MM` and unique event_id. Revenue/refund
    events require approved sources and `verified=True`; costs require
    approved categories, verified=True and an amount. The source adapter must
    authenticate provider evidence, verify monthly settlement, and only then
    set revenue_complete/costs_complete to True. Browser input is never proof.

    Do not add profit-per-visitor to profit-per-lead: the numerator is shared.
    """
    if not re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", reporting_period):
        raise ValueError("reporting_period must be YYYY-MM")

    raw_revenue = list(revenue_events)
    matching_revenue = [
        event for event in raw_revenue
        if isinstance(event, Mapping) and event.get("period") == reporting_period
    ]
    rejected_period_events = len(raw_revenue) - len(matching_revenue)
    revenue = summarize(matching_revenue)

    cost_total = 0
    seen: set[str] = set()
    rejected_costs = 0
    categories: dict[str, int] = {}
    for event in cost_events:
        if not isinstance(event, Mapping):
            rejected_costs += 1
            continue
        eid = str(event.get("event_id") or "").strip()
        category = str(event.get("category") or "")
        if (
            not eid
            or event.get("period") != reporting_period
            or category not in COST_CATEGORIES
            or event.get("verified") is not True
        ):
            rejected_costs += 1
            continue
        if eid in seen:
            continue
        seen.add(eid)
        try:
            cents = _cents(event.get("amount_usd"))
        except ValueError:
            rejected_costs += 1
            continue
        cost_total += cents
        categories[category] = categories.get(category, 0) + cents

    complete = (
        revenue_complete is True
        and costs_complete is True
        and rejected_costs == 0
        and rejected_period_events == 0
        and revenue["rejected_events"] == 0
    )
    visitors = revenue["unique_visitors"]
    leads = revenue["unique_qualified_leads"]
    net_cents = int(Decimal(revenue["net_verified_revenue_usd"]) * 100) - cost_total

    def per(count: int) -> str | None:
        if not complete or not count:
            return None
        return str((Decimal(net_cents) / Decimal(100 * count)).quantize(Decimal("0.01")))

    return {
        **revenue,
        "reporting_period": reporting_period,
        "revenue_evidence_complete": complete and revenue_complete,
        "cost_evidence_complete": complete and costs_complete,
        "verified_costs_usd": _usd(cost_total),
        "costs_by_category_usd": {key: _usd(value) for key, value in sorted(categories.items())},
        "net_profit_usd": _usd(net_cents) if complete else None,
        "net_profit_per_visitor_usd": per(visitors),
        "net_profit_per_qualified_lead_usd": per(leads),
        "visitor_target_met": (net_cents >= visitors * 100) if complete and visitors else None,
        "rejected_cost_events": rejected_costs,
        "rejected_period_events": rejected_period_events,
        "status": "verified" if complete else "incomplete_cost_or_revenue_evidence",
    }
