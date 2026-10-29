"""Net profitability reporting for NIJA website acquisition cohorts.

Input must contain independently reconciled provider-side revenue events,
refunded amounts and cost evidence. No client-side claim can mark a payment
verified. This report never guesses missing costs.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from website_revenue_attribution import summarize

COST_CATEGORIES = frozenset({
    "advertising", "payment_processing", "refund_handling", "hosting",
    "course_fulfillment", "customer_support", "software", "affiliate_payout",
    "chargeback_fee", "other_operating"
})

def _cents(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid cost amount") from None
    if not value.is_finite() or value < 0 or value.as_tuple().exponent < -2:
        raise ValueError("Costs require nonnegative USD amounts with <=2 decimals")
    return int(value * 100)

def net_profit_report(revenue_events, cost_events, *, costs_complete=False):
    """Report net profit only when period-matched costs have been certified complete.

    Cost events require unique event_id, verified=True, an approved category,
    amount_usd, and period. Duplicate evidence IDs are ignored. Counts and
    revenue come from existing revenue attribution. Reuse the same reporting
    date range for visitors, revenue and costs at the caller.
    """
    revenue = summarize(revenue_events)
    cost_total = 0
    seen = set()
    rejected = 0
    categories = {}
    for event in cost_events:
        if not isinstance(event, dict):
            rejected += 1
            continue
        eid = str(event.get("event_id") or "").strip()
        category = str(event.get("category") or "")
        period = str(event.get("period") or "")
        if not eid or not period or category not in COST_CATEGORIES or event.get("verified") is not True:
            rejected += 1
            continue
        if eid in seen:
            continue
        seen.add(eid)
        try:
            cents = _cents(event.get("amount_usd"))
        except ValueError:
            rejected += 1
            continue
        cost_total += cents
        categories[category] = categories.get(category, 0) + cents
    complete = costs_complete is True and rejected == 0 and revenue["rejected_events"] == 0
    net = int(Decimal(revenue["net_verified_revenue_usd"]) * 100) - cost_total
    def dollars(cents):
        return str((Decimal(cents) / 100).quantize(Decimal("0.01")))
    def per(count):
        return str((Decimal(net) / (100 * count)).quantize(Decimal("0.01"))) if count else None
    visitors = revenue["unique_visitors"]
    leads = revenue["unique_qualified_leads"]
    return {
        **revenue,
        "cost_evidence_complete": complete,
        "verified_costs_usd": dollars(cost_total),
        "costs_by_category_usd": {k: dollars(v) for k,v in sorted(categories.items())},
        "net_profit_usd": dollars(net) if complete else None,
        "net_profit_per_visitor_usd": per(visitors) if complete else None,
        "net_profit_per_qualified_lead_usd": per(leads) if complete else None,
        "visitor_target_met": (net >= visitors * 100) if complete and visitors else None,
        "rejected_cost_events": rejected,
        "status": "verified" if complete else "incomplete_cost_or_revenue_evidence"
    }
