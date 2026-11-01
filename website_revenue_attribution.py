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

REVENUE_SOURCES = frozenset({
    "stripe", "clickbank", "printful_settlement", "affiliate_settlement", "sponsor_invoice", "ad_network"
})
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
    identity_map: dict[tuple[str, ...], int | None] = {}
    records: list[dict[str, object]] = []
    visitors: set[str] = set()
    leads: set[str] = set()
    source_cents: dict[str, int] = defaultdict(int)
    gross_cents = 0
    refund_cents = 0
    rejected = 0
    duplicate_events = 0
    conflicting_events = 0

    def fingerprint(
        event: Mapping[str, object], kind: str, source: str
    ) -> tuple[tuple[object, ...], tuple[object, ...]]:
        amount: object = None
        if kind in {"revenue", "refund"}:
            try:
                amount = _money_cents(event.get("amount_usd"))
            except ValueError:
                amount = ("invalid", str(event.get("amount_usd")))
        canonical = (
            kind,
            str(event.get("period") or ""),
            event.get("verified"),
            amount,
            str(event.get("visitor_id") or "").strip(),
            str(event.get("lead_id") or "").strip(),
        )
        return (kind, str(event.get("period") or ""), source, *canonical[2:]), canonical

    for e in events:
        if not isinstance(e, Mapping):
            rejected += 1
            continue
        event_id = str(e.get("event_id") or "").strip()
        kind = str(e.get("type") or "").strip()
        if not event_id or kind not in ALLOWED_EVENT_TYPES:
            rejected += 1
            continue

        source = str(e.get("source") or "")
        scope = source if kind in {"revenue", "refund"} else ""
        identities = [("event", kind, scope, event_id)]
        if kind in {"revenue", "refund"}:
            transaction_id = str(
                e.get("provider_transaction_id") or e.get("transaction_id") or ""
            ).strip()
            canonical_id = str(e.get("canonical_transaction_id") or "").strip()
            if transaction_id:
                identities.append(("transaction", kind, source, transaction_id))
            if canonical_id:
                identities.append(("canonical_transaction", kind, canonical_id))

        event_fingerprint, canonical_fingerprint = fingerprint(e, kind, source)
        matches = [
            (identity, identity_map[identity])
            for identity in identities
            if identity in identity_map and identity_map[identity] is not None
        ]
        matching = {index for _, index in matches}
        has_conflicted_identity = any(
            identity in identity_map and identity_map[identity] is None
            for identity in identities
        )
        if has_conflicted_identity or len(matching) > 1 or any(
            records[index]["identity_fingerprints"][identity] != (
                canonical_fingerprint
                if identity[0] == "canonical_transaction"
                else event_fingerprint
            )
            for identity, index in matches
        ):
            for index in matching:
                records[index]["conflicted"] = True
                for prior_identity in records[index]["identities"]:
                    identity_map[prior_identity] = None
            for identity in identities:
                identity_map[identity] = None
            # Keep conflict accounting on the pending record so later duplicates
            # cannot silently restore either version.
            records.append({
                "event": e,
                "fingerprint": event_fingerprint,
                "canonical_fingerprint": canonical_fingerprint,
                "identities": identities,
                "identity_fingerprints": {
                    identity: (
                        canonical_fingerprint
                        if identity[0] == "canonical_transaction"
                        else event_fingerprint
                    )
                    for identity in identities
                },
                "conflicted": True,
            })
            continue

        if matching:
            duplicate_events += 1
            index = next(iter(matching))
            records[index]["identities"].extend(
                identity for identity in identities
                if identity not in records[index]["identities"]
            )
            for identity in identities:
                identity_map[identity] = index
                records[index]["identity_fingerprints"][identity] = (
                    canonical_fingerprint
                    if identity[0] == "canonical_transaction"
                    else event_fingerprint
                )
            continue

        index = len(records)
        records.append({
            "event": e,
            "fingerprint": event_fingerprint,
            "canonical_fingerprint": canonical_fingerprint,
            "identities": identities,
            "identity_fingerprints": {
                identity: (
                    canonical_fingerprint
                    if identity[0] == "canonical_transaction"
                    else event_fingerprint
                )
                for identity in identities
            },
            "conflicted": False,
        })
        for identity in identities:
            identity_map[identity] = index

    for record in records:
        if record["conflicted"]:
            conflicting_events += 1
            rejected += 1
            continue
        e = record["event"]
        kind = str(e.get("type") or "").strip()
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
            if kind == "revenue":
                gross_cents += cents
            else:
                refund_cents += cents
    total_cents = sum(source_cents.values())
    def rate(n: int) -> str | None:
        return str((Decimal(total_cents) / Decimal(100) / n).quantize(Decimal("0.01"))) if n else None
    return {
        "unique_visitors": len(visitors),
        "unique_qualified_leads": len(leads),
        "gross_verified_revenue_usd": str((Decimal(gross_cents) / 100).quantize(Decimal("0.01"))),
        "verified_refunds_usd": str((Decimal(refund_cents) / 100).quantize(Decimal("0.01"))),
        "net_verified_revenue_usd": str((Decimal(total_cents) / 100).quantize(Decimal("0.01"))),
        "revenue_per_visitor_usd": rate(len(visitors)),
        "revenue_per_qualified_lead_usd": rate(len(leads)),
        "revenue_by_source_usd": {
            key: str((Decimal(value) / 100).quantize(Decimal("0.01")))
            for key, value in sorted(source_cents.items())
        },
        "rejected_events": rejected,
        "duplicate_events": duplicate_events,
        "conflicting_events": conflicting_events,
        "target_usd_per_visitor": "1.00",
        "target_usd_per_qualified_lead": "1.00",
    }
