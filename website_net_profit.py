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
    "course_fulfillment", "merchandise_fulfillment", "customer_support", "software", "affiliate_payout",
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
    certified_unique_visitors: int | None = None,
    certified_qualified_leads: int | None = None,
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
    for label, value in (("visitors", certified_unique_visitors), ("leads", certified_qualified_leads)):
        if value is not None and (type(value) is not int or value < 0 or value > 10**12):
            raise ValueError("Certified " + label + " must be a nonnegative integer")

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
    observed_visitors = revenue["unique_visitors"]
    observed_leads = revenue["unique_qualified_leads"]
    if certified_unique_visitors is not None and certified_unique_visitors < observed_visitors:
        raise ValueError("Certified visitor aggregate cannot be below logged visitor count")
    if certified_qualified_leads is not None and certified_qualified_leads < observed_leads:
        raise ValueError("Certified lead aggregate cannot be below logged lead count")
    visitors = certified_unique_visitors if certified_unique_visitors is not None else observed_visitors
    leads = certified_qualified_leads if certified_qualified_leads is not None else observed_leads
    net_revenue_cents = int(Decimal(revenue["net_verified_revenue_usd"]) * 100)
    net_cents = net_revenue_cents - cost_total

    def per(amount_cents: int, count: int) -> str | None:
        # Never expose a financial ratio based on unclosed or unreconciled data.
        if not complete or not count:
            return None
        return str((Decimal(amount_cents) / Decimal(100 * count)).quantize(Decimal("0.01")))

    return {
        **revenue,
        # Override summarize() rates, which use only observed event counts and
        # cannot know whether independently certified denominator counts exist.
        "revenue_per_visitor_usd": per(net_revenue_cents, visitors),
        "revenue_per_qualified_lead_usd": per(net_revenue_cents, leads),
        "unique_visitors": visitors,
        "unique_qualified_leads": leads,
        "visitor_count_source": "certified_aggregate" if certified_unique_visitors is not None else "event_evidence",
        "qualified_lead_count_source": "certified_aggregate" if certified_qualified_leads is not None else "event_evidence",
        "reporting_period": reporting_period,
        "revenue_evidence_complete": complete and revenue_complete,
        "cost_evidence_complete": complete and costs_complete,
        "verified_costs_usd": _usd(cost_total),
        "costs_by_category_usd": {key: _usd(value) for key, value in sorted(categories.items())},
        "net_profit_usd": _usd(net_cents) if complete else None,
        "net_profit_per_visitor_usd": per(net_cents, visitors),
        "net_profit_per_qualified_lead_usd": per(net_cents, leads),
        "visitor_target_met": (net_cents >= visitors * 100) if complete and visitors else None,
        "rejected_cost_events": rejected_costs,
        "rejected_period_events": rejected_period_events,
        "status": "verified" if complete else "incomplete_cost_or_revenue_evidence",
    }
