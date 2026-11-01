"""Read-only, fail-closed Stripe charge-to-lead attribution.

Caller must fetch charges from authenticated Stripe API and supply a separately
verified, restricted customer-to-lead mapping. No network, billing or outreach.
Do not pass browser events, email addresses or raw CRM contact data.
"""
from collections import defaultdict
from decimal import Decimal

def _usd(cents):
    return str((Decimal(cents) / 100).quantize(Decimal("0.01")))

def reconcile_stripe_charges(charges, customer_leads, *, mapping_verified=False,
                             charges_complete=False):
    """Return aggregate-only payment attribution; unknown is never zero.

    A mapping is customer_id -> stable lead_id, or a collection of lead IDs
    for ambiguity detection. Only paid, succeeded, nonrefunded charges count.
    Stripe charge.amount is in cents; amount_refunded is reconciled separately.
    Incomplete provider pagination prevents a verified aggregate.
    """
    if not isinstance(customer_leads, dict):
        raise ValueError("customer_leads must be a restricted mapping")
    seen = {}
    invalid = 0
    conflicts = set()
    for charge in charges:
        if not isinstance(charge, dict) or not isinstance(charge.get("id"), str) or not charge["id"]:
            invalid += 1
            continue
        cid = charge["id"]
        if cid in seen:
            if seen[cid] != charge:
                conflicts.add(cid)
            continue
        seen[cid] = charge
    totals = defaultdict(int)
    paid_count = 0
    unattributed_count = 0
    ambiguous_count = 0
    refunds = 0
    for cid, charge in seen.items():
        if cid in conflicts:
            invalid += 1
            continue
        if charge.get("livemode") is not True:
            invalid += 1
            continue
        status = charge.get("status")
        paid = charge.get("paid")
        if status not in ("succeeded", "failed", "pending") or type(paid) is not bool:
            invalid += 1
            continue
        if status != "succeeded" or paid is not True:
            continue
        amount = charge.get("amount")
        refunded = charge.get("amount_refunded")
        if (type(amount) is not int or type(refunded) is not int
                or amount < 0 or refunded < 0 or refunded > amount
                or charge.get("currency") != "usd"):
            invalid += 1
            continue
        paid_count += 1
        refunds += refunded
        customer = charge.get("customer")
        lead = customer_leads.get(customer) if isinstance(customer, str) else None
        if isinstance(lead, (list, tuple, set)):
            values = {v for v in lead if isinstance(v, str) and v.strip()}
            lead = next(iter(values)) if len(values) == 1 else None
            if lead is None:
                ambiguous_count += 1
        if not isinstance(lead, str) or not lead.strip() or not mapping_verified:
            unattributed_count += 1
        else:
            totals[lead] += amount - refunded
    complete = (charges_complete is True and mapping_verified is True
                and invalid == 0 and not conflicts)
    # Never disclose lead/customer identifiers in aggregate reports.
    return {
        "status": "verified" if complete else "unverified",
        "paid_charges": paid_count if charges_complete is True and invalid == 0 else None,
        "refunded_usd": _usd(refunds) if charges_complete is True and invalid == 0 else None,
        "net_collected_usd": _usd(sum(totals.values())) if complete and not unattributed_count else None,
        "attributed_paid_leads": len(totals) if complete else None,
        "unattributed_paid_charges": unattributed_count if charges_complete is True and invalid == 0 else None,
        "ambiguous_mappings": ambiguous_count,
        "invalid_or_conflicting_charges": invalid,
        "duplicate_charge_ids": len(list(charges)) - len(seen) if isinstance(charges, (list, tuple)) else None,
        "all_revenue_attributed": complete and unattributed_count == 0,
    }
