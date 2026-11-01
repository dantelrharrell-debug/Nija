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
    "email_service", "chargeback_fee", "other_operating"
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
    rejected_costs = 0
    categories: dict[str, int] = {}
    cost_records: list[dict[str, object]] = []
    cost_identity_map: dict[tuple[str, ...], int | None] = {}
    duplicate_cost_events = 0
    conflicting_cost_events = 0
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
        try:
            cents = _cents(event.get("amount_usd"))
        except ValueError:
            rejected_costs += 1
            continue
        provider = str(event.get("provider") or event.get("source") or "unattributed").strip()
        identities = [("event", provider, eid)]
        transaction_id = str(
            event.get("provider_transaction_id") or event.get("transaction_id") or ""
        ).strip()
        canonical_id = str(event.get("canonical_transaction_id") or "").strip()
        if transaction_id:
            identities.append(("transaction", provider, transaction_id))
        if canonical_id:
            identities.append(("canonical_transaction", canonical_id))
        fingerprint = (event.get("period"), category, event.get("verified"), provider, cents)
        canonical_fingerprint = (event.get("period"), category, event.get("verified"), cents)
        matches = [
            (identity, cost_identity_map[identity])
            for identity in identities
            if identity in cost_identity_map and cost_identity_map[identity] is not None
        ]
        matching = {index for _, index in matches}
        has_conflicted_identity = any(
            identity in cost_identity_map and cost_identity_map[identity] is None
            for identity in identities
        )
        if has_conflicted_identity or len(matching) > 1 or any(
            cost_records[index]["identity_fingerprints"][identity] != (
                canonical_fingerprint
                if identity[0] == "canonical_transaction"
                else fingerprint
            )
            for identity, index in matches
        ):
            for index in matching:
                cost_records[index]["conflicted"] = True
                for prior_identity in cost_records[index]["identities"]:
                    cost_identity_map[prior_identity] = None
            for identity in identities:
                cost_identity_map[identity] = None
            cost_records.append({
                "category": category,
                "cents": cents,
                "fingerprint": fingerprint,
                "canonical_fingerprint": canonical_fingerprint,
                "identities": identities,
                "identity_fingerprints": {
                    identity: (
                        canonical_fingerprint
                        if identity[0] == "canonical_transaction"
                        else fingerprint
                    )
                    for identity in identities
                },
                "conflicted": True,
            })
            continue
        if matching:
            duplicate_cost_events += 1
            index = next(iter(matching))
            cost_records[index]["identities"].extend(
                identity for identity in identities
                if identity not in cost_records[index]["identities"]
            )
            for identity in identities:
                cost_identity_map[identity] = index
                cost_records[index]["identity_fingerprints"][identity] = (
                    canonical_fingerprint
                    if identity[0] == "canonical_transaction"
                    else fingerprint
                )
            continue
        index = len(cost_records)
        cost_records.append({
            "category": category,
            "cents": cents,
            "fingerprint": fingerprint,
            "canonical_fingerprint": canonical_fingerprint,
            "identities": identities,
            "identity_fingerprints": {
                identity: (
                    canonical_fingerprint
                    if identity[0] == "canonical_transaction"
                    else fingerprint
                )
                for identity in identities
            },
            "conflicted": False,
        })
        for identity in identities:
            cost_identity_map[identity] = index

    for record in cost_records:
        if record["conflicted"]:
            rejected_costs += 1
            conflicting_cost_events += 1
            continue
        cents = record["cents"]
        category = record["category"]
        cost_total += cents
        categories[category] = categories.get(category, 0) + cents

    revenue_stream_complete = (
        revenue_complete is True
        and rejected_period_events == 0
        and revenue["rejected_events"] == 0
    )
    cost_stream_complete = costs_complete is True and rejected_costs == 0
    complete = revenue_stream_complete and cost_stream_complete
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
    processor_fees_cents = categories.get("payment_processing", 0)

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
        "visitor_count_source": (
            "certified_aggregate" if certified_unique_visitors is not None else "event_evidence"
        ),
        "qualified_lead_count_source": (
            "certified_aggregate" if certified_qualified_leads is not None else "event_evidence"
        ),
        "reporting_period": reporting_period,
        "revenue_evidence_complete": revenue_stream_complete,
        "cost_evidence_complete": cost_stream_complete,
        "verified_costs_usd": _usd(cost_total) if cost_stream_complete else None,
        "gross_collected_revenue_usd": (
            revenue["gross_verified_revenue_usd"] if revenue_stream_complete else None
        ),
        "refunds_usd": revenue["verified_refunds_usd"] if revenue_stream_complete else None,
        "processor_fees_usd": _usd(processor_fees_cents) if cost_stream_complete else None,
        "operating_acquisition_costs_usd": (
            _usd(cost_total - processor_fees_cents) if cost_stream_complete else None
        ),
        "costs_by_category_usd": {key: _usd(value) for key, value in sorted(categories.items())},
        "net_profit_usd": _usd(net_cents) if complete else None,
        "net_profit_per_visitor_usd": per(net_cents, visitors),
        "net_profit_per_qualified_lead_usd": per(net_cents, leads),
        "visitor_target_met": (net_cents >= visitors * 100) if complete and visitors else None,
        "rejected_cost_events": rejected_costs,
        "duplicate_cost_events": duplicate_cost_events,
        "conflicting_cost_events": conflicting_cost_events,
        "rejected_period_events": rejected_period_events,
        "status": "verified" if complete else "incomplete_cost_or_revenue_evidence",
    }
