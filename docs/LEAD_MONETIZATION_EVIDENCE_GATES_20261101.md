# Lead monetization evidence gates (2026-11-01)

## Verified live observations

- Apollo NIJA AI — Fintech Executive Outreach is active. Connector reported 42 unique delivered, 0 replies, 0 clicks, 4 bounces (3 hard), and 42 overdue manual tasks. These are sequence-level statistics, not website lead counts.
- Stripe live account returned two failed charges (10930 and 10801 USD cents), no paid charges, and one trialing Founding 100 subscription. The subscription metadata specifies billing paused until secure brokerage setup is verified. Do not change the trial or bill the member automatically.
- Stripe Sigma reporting is unavailable on this account. Standard read-only Stripe API remains available.

## Required implementation acceptance criteria

1. Join canonical persisted website lead submissions to CRM records by durable submission ID; use an internal restricted mapping from customer ID to lead ID. Never infer identity from email opens or analytics event counts. Respect opt-outs and separate consent bases.
2. Reconcile Stripe payment intents, charges, invoices and subscriptions with signed webhooks and provider-side readback. Count revenue only for succeeded/paid, settled payments; exclude failed charges and trials. Deduplicate delivery by provider + event type + provider event ID, and canonicalize all representations of each payment to one verified transaction identity before counting revenue. Validate with multiple event types and provider readback describing the same payment. Process refunds and disputes as negative adjustments with their own canonical adjustment identities. Do not persist payment credentials or PII in analytics events.
3. Link each successful purchase to exactly one originating lead when a verified mapping exists; otherwise classify it as unattributed, not as zero revenue. Keep lead conversion and visitor conversion denominators distinct.
4. Require matching-period first-party visitor evidence and complete attributable costs before reporting net contribution per visitor. If any required evidence is missing, return null/unverified rather than zero or profitability.
5. Verify IONOS live intake, Zapier delivery, Apollo suppression, ClickBank, Printful, referral settlement, and payment sources independently before marking reconciliation complete. No replay of historical leads.
6. Stage conversion events only through existing consent-gated analytics outbox. Never promote GA4 custom lead-form events directly into paid conversions. Keep Google Ads paused until verified conversion and targeting gates pass.
7. Validate in staging with fixtures for duplicate webhook delivery, failed charge, trialing subscription, successful payment, refund, conflicting lead mappings, absent visitor count, absent costs, and opted-out lead. No production deploy without tests and reviewer approval.

## Current status

This is an evidence/acceptance checklist, **not a production implementation or certification**. Existing code paths: `website_revenue_attribution.py`, `website_net_profit.py`, `analytics/verified_conversion_events.py`, `analytics/conversion_outbox.py`, and `stripe_billing_api.py`. Follow existing deployment gates. Never relax trading safety controls or member billing protection to improve revenue metrics.
