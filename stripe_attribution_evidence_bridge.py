"""Read-only bridge from authenticated Stripe charge evidence to monthly finance events.

Requires independently verified restricted customer-to-lead mapping. Never
promotes partial attribution, test charges, or incomplete pagination to revenue.
The caller must reconcile all other providers, expenses and visitors separately.
"""
from decimal import Decimal
from lead_payment_attribution import reconcile_stripe_charges


def stripe_attributed_events(charges, customer_leads, *, period,
                             mapping_verified=False, charges_complete=False):
    """Return aggregate-safe events or an explicit unverified result."""
    charges = list(charges)
    report = reconcile_stripe_charges(
        charges, customer_leads, mapping_verified=mapping_verified,
        charges_complete=charges_complete,
    )
    if report["status"] != "verified" or not report["all_revenue_attributed"]:
        return {"status": "unverified", "attribution": report, "revenue_events": []}
    events = []
    seen = set()
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
        if amount == 0:
            continue
        base = {
            "source": "stripe", "verified": True, "period": period,
            "provider_transaction_id": cid,
        }
        events.append({**base, "type": "revenue", "event_id": "stripe-charge:" + cid,
                       "amount_usd": str((Decimal(amount) / 100).quantize(Decimal("0.01")))})
        if refunded:
            events.append({**base, "type": "refund", "event_id": "stripe-refund:" + cid,
                           "amount_usd": str((Decimal(refunded) / 100).quantize(Decimal("0.01")))})
    return {"status": "verified", "attribution": report, "revenue_events": events}
