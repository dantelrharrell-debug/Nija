# ClickBank Foundations repair acceptance

Scope: existing $99 course only. Reuse CourseLedger and PortalStore; never invoke member trading activation or subscription billing.

## Implementation gates
- Confirm seller nickname, course item ID, currency, price/tax policy and actual Orders API response schema using authorized read-only seller access. Never infer paid status from receipt existence.
- Authenticate INS 8.0 according to provider documentation; treat notifications as reconciliation triggers, not independent grants. Reject malformed or unauthenticated payloads. Never log secrets or buyer data.
- Use provider-namespaced canonical receipt IDs, durable unique transaction identity and atomic entitlement/outbox writes. Preserve Stripe session IDs and existing access.
- Verify vendor, item, buyer identity, sale status, amount, currency, live/test mode and reversal history before granting; fail closed on ambiguous evidence or provider outage. Revalidate on access and process reversals.
- Reuse private portal assets and email recovery; never grant brokerage or subscription permissions.
- Reconcile the two dashboard records individually against authoritative provider receipts; do not mark approved solely from redirects.
- Test valid sale, invalid notification, wrong vendor/item, test/live mismatch, duplicate/concurrent events, refund, chargeback, provider timeout, recovery, and Stripe regression. Verify no real customer email in tests.
- Identify deployed IONOS dashboard source and synchronize verified course status only after staging acceptance.

## Evidence required before production
Exact source diff, passing isolated tests, seller API schema and credentials configured securely, dashboard source mapping, rollback plan, verified pending-order evidence, and production release approval. This document does not implement or certify fulfillment.
