"""NIJA website monetization measurement (stdlib only).

This module calculates *verified* revenue per unique visitor and per unique
qualified lead from an export of independently reconciled events. It does not
accept browser-reported purchase amounts as proof of payment, nor send lead
contact details to third parties.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping

REVENUE_SOURCES = frozenset({"stripe", "clickbank", "affiliate_settlement", "sponsor_invoice", "ad_network"})
ALLOWED_EVENT_TYPES = frozenset({"visit", "qualified_lead", "revenue", "refund"})

def _money_cents(value: object) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid monetary amount") from None
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("Amount must be nonnegative USD with at most two decimal places")
    return int(amount * 100)

def summarize(events: Iterable[Mapping[str, object]]) -> dict:
    """Summarize deduplicated, verified events; disallow fabricated revenue.

    Expected fields:
    - visit: event_id, visitor_id
    - qualified_lead: event_id, visitor_id, lead_id
    - revenue/refund: event_id, amount_usd, source, verified=True
      Revenue events MUST originate from a reconciled provider-side feed.
    A lead's visitor_id lets reports attribute conversion without counting it
    as another visit. Missing identity is not counted as a unique visitor/lead.
    """
    seen_ids: set[str] = set()
    visitors: set[str] = set()
    leads: set[str] = set()
    source_cents: dict[str, int] = defaultdict(int)
    rejected = 0
    for e in events:
        if not isinstance(e, Mapping):
            rejected += 1
            continue
        event_id = str(e.get("event_id") or "").strip()
        kind = str(e.get("type") or "").strip()
        if not event_id or kind not in ALLOWED_EVENT_TYPES:
            rejected += 1
            continue
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)
        visitor_id = str(e.get("visitor_id") or "").strip()
        if kind == "visit":
            if not visitor_id:
                rejected += 1
            else:
                visitors.add(visitor_id)
        elif kind == "qualified_lead":
            lead_id = str(e.get("lead_id") or "").strip()
            if not lead_id:
                rejected += 1
            else:
                leads.add(lead_id)
                if visitor_id:
                    visitors.add(visitor_id)
        else:
            source = str(e.get("source") or "")
            if e.get("verified") is not True or source not in REVENUE_SOURCES:
                rejected += 1
                continue
            try:
                cents = _money_cents(e.get("amount_usd"))
            except ValueError:
                rejected += 1
                continue
            source_cents[source] += cents if kind == "revenue" else -cents
    total_cents = sum(source_cents.values())
    def rate(n: int) -> str | None:
        return str((Decimal(total_cents) / Decimal(100) / n).quantize(Decimal("0.01"))) if n else None
    return {
        "unique_visitors": len(visitors),
        "unique_qualified_leads": len(leads),
        "net_verified_revenue_usd": str((Decimal(total_cents) / 100).quantize(Decimal("0.01"))),
        "revenue_per_visitor_usd": rate(len(visitors)),
        "revenue_per_qualified_lead_usd": rate(len(leads)),
        "revenue_by_source_usd": {k: str((Decimal(v) / 100).quantize(Decimal("0.01"))) for k, v in sorted(source_cents.items())},
        "rejected_events": rejected,
        "target_usd_per_visitor": "1.00",
        "target_usd_per_qualified_lead": "1.00",
    }
