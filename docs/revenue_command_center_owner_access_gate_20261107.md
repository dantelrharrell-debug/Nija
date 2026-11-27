# NIJA Revenue Command Center — deployment gate (2026-11-07)

Status: REVIEW ONLY. Do not deploy this dashboard as a public static site. Existing offline HTML prototype is not authenticated and does not contain live data.

## Required before any deployment
1. Server-side SSO and MFA, default-deny. Grant settings mutation only to explicitly verified owner identities; no browser-only email checks. Audit settings mutations.
2. Read-only GA4 metrics, Stripe captured charges/refunds/balance transaction fees, NIJA assessment/waitlist/lead delivery event records, and attributable marketing/operating expenses. Use least-privilege credentials stored server-side.
3. Reconcile event IDs and payment IDs; prevent double counting. Keep missing metrics NULL (not zero). Label verified/provisional with source timestamps and evidence.
4. Previous seven complete days compared with prior seven complete days, in a single approved reporting timezone. Separate $99 course and $1 report purchase branches; do not treat them as a linear funnel.
5. Profit = captured course revenue + captured report revenue - refunds - payment fees - attributable marketing spend - attributable operating costs. Show profit/unique visitor only when denominator and all costs are verified.
6. Verify access denial for unauthenticated users, nonowner users, and nonowner settings writes. Test no access to payment, trading, or production configuration mutation.
7. Verify read-only integration, stale-data handling, export controls, and end-to-end reconciliation before calling the dashboard live.

## Scope restrictions
- No production deploy, no public hosting, no payment or trading changes.
- Do not add secrets, account tokens, or customer-level personal data to this public repository.
- A `noindex` directive is NOT an access-control boundary.
- Existing Render billing services are NOT to be repurposed or modified without a separate review.
