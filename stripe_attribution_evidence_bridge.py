"""Read-only bridge from authenticated Stripe charge evidence to monthly finance events.

Requires independently verified restricted customer-to-lead mapping. Never
promotes partial attribution, test charges, or incomplete pagination to revenue.
The caller must reconcile all other providers, expenses and visitors separately.
"""
from datetime import datetime, timezone
from decimal import Decimal
from lead_payment_attribution import reconcile_stripe_charges


def stripe_attributed_events(charges, customer_leads, *, period,
                             mapping_verified=False, charges_complete=False,
                             refunds_complete=False):
    """Return aggregate-safe period events or an explicit unverified result.

    Include every charge created in the period and every charge with refunds in
    the period. ``refunds_complete`` attests that the period's refund evidence is
    complete; each charge's expanded refunds must also be fully paginated.
    """
    charges = list(charges)
    report = reconcile_stripe_charges(
        charges, customer_leads, mapping_verified=mapping_verified,
        charges_complete=charges_complete,
    )
    try:
        period_start = datetime.strptime(period, "%Y-%m").replace(tzinfo=timezone.utc)
        if period_start.strftime("%Y-%m") != period:
            raise ValueError("period must use YYYY-MM format")
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)
    except (TypeError, ValueError):
        return {"status": "unverified", "attribution": report, "revenue_events": []}
    period_start = int(period_start.timestamp())
    period_end = int(period_end.timestamp())
    if (report["status"] != "verified" or not report["all_revenue_attributed"]
            or refunds_complete is not True):
        return {"status": "unverified", "attribution": report, "revenue_events": []}
    events = []
    seen = set()
    refund_ids = set()
    for charge in charges:
        cid = charge["id"]
        if cid in seen:
            continue
        seen.add(cid)
        if (charge["livemode"] is not True or charge["status"] != "succeeded"
                or charge["paid"] is not True or charge["captured"] is not True):
            continue
        amount = charge["amount"]
        refunded = charge["amount_refunded"]
        if amount > 0 and amount == refunded:
            customer = charge.get("customer")
            lead = customer_leads.get(customer) if isinstance(customer, str) else None
            if isinstance(lead, (list, tuple, set)):
                values = {value for value in lead if isinstance(value, str) and value.strip()}
                lead = next(iter(values)) if len(values) == 1 else None
            if not isinstance(lead, str) or not lead.strip():
                return {"status": "unverified", "attribution": report, "revenue_events": []}
        created = charge.get("created")
        refund_evidence = charge.get("refunds")
        if (type(created) is not int or created < 0
                or not isinstance(refund_evidence, dict)
                or refund_evidence.get("has_more") is not False
                or not isinstance(refund_evidence.get("data"), list)):
            return {"status": "unverified", "attribution": report, "revenue_events": []}
        succeeded_refunds = 0
        for refund in refund_evidence["data"]:
            if (not isinstance(refund, dict) or not isinstance(refund.get("id"), str)
                    or not refund["id"] or type(refund.get("amount")) is not int
                    or refund["amount"] <= 0 or type(refund.get("created")) is not int
                    or refund["created"] < 0 or refund.get("currency") != "usd"
                    or refund.get("status") not in ("succeeded", "pending", "failed", "canceled")
                    or refund["id"] in refund_ids):
                return {"status": "unverified", "attribution": report, "revenue_events": []}
            refund_ids.add(refund["id"])
            if refund["status"] == "succeeded":
                succeeded_refunds += refund["amount"]
        if succeeded_refunds != refunded:
            return {"status": "unverified", "attribution": report, "revenue_events": []}
        base = {
            "source": "stripe", "verified": True, "period": period,
            "provider_transaction_id": cid,
        }
        if amount and period_start <= created < period_end:
            events.append({**base, "type": "revenue", "event_id": "stripe-charge:" + cid,
                           "amount_usd": str((Decimal(amount) / 100).quantize(Decimal("0.01")))})
        for refund in refund_evidence["data"]:
            if (refund["status"] == "succeeded"
                    and period_start <= refund["created"] < period_end):
                events.append({
                    **base, "type": "refund", "event_id": "stripe-refund:" + refund["id"],
                    "provider_adjustment_id": refund["id"],
                    "amount_usd": str((Decimal(refund["amount"]) / 100).quantize(Decimal("0.01"))),
                })
    return {"status": "verified", "attribution": report, "revenue_events": events}
