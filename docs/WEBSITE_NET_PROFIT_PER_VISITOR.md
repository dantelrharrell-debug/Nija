# NIJA $1 net operating profit per unique visitor — operational activation

## Measurement standard
The goal is **at least $1.00 of net operating profit per distinct website visitor per calendar month**, not $1 of gross revenue and not a guarantee of $1 earned on every individual visit.

Formula: (confirmed recognized/collected revenue - refunds - all attributable operating costs) / deduplicated unique visitors. Report the same net income numerator divided by qualified leads as a *separate* ratio; never add both ratios into revenue.

## Current repository components
- `website_revenue_attribution.py`: count unique visitors and leads, deduplicate provider-confirmed revenue and refunds.
- `website_net_profit.py`: evidence-gated monthly profitability. Call `net_profit_report(revenue_events, cost_events, reporting_period='YYYY-MM', revenue_complete=True, costs_complete=True)` only after server-side reconciliation has certified both streams complete for that month.
- Unit tests: `python -m unittest tests.test_website_revenue_attribution tests.test_website_net_profit`

No public browser form or client code may set `verified` or completeness flags. Revenue and cost evidence require authenticated server-side sources and stable provider event IDs; the module is reporting logic, not itself a scheduled collector or HTTP endpoint.

## Required production data sources (not assumed connected)
- First-party consent-aware website analytics: unique pseudonymous visitor IDs, UTM attribution, qualification state, event timestamps.
- Stripe: settled charges or recognized subscription revenue and refunds; processor fees; trial-only signups are not revenue.
- Printful: recognize only authenticated settled or earned Quick Store merchant proceeds under `printful_settlement`, net of verified refunds, plus separately evidenced `merchandise_fulfillment` costs. An order/shipping email or GA4 checkout event alone is not proof of payment. Do not double-count a Printful payment already represented by the same underlying Stripe transaction.
- ClickBank: settled course sales, refunds, fees, affiliate commissions.
- Affiliate providers: payable or settled commissions **only**, never clicks as earnings.
- Sponsor/ad network: verified payments or earned statements, with corresponding expenses.
- Hosting, software, paid acquisition, personnel/service-delivery cost allocations, processing fees, fulfilment, support, and chargeback costs.

Finance must document whether numbers are on a cash basis or accrual basis and apply the same policy consistently. Do not mix revenue gross of processor fees with net settlement plus a second fee deduction; do not count tax collected on behalf of authorities as revenue. Establish signed-off data completeness for each provider and cost category before marking a reporting month VERIFIED.

## Activation gates
1. Confirm the live IONOS primary CTA points to `/enroll` and the secondary CTA to `/free`. Preserve `/apply` as clearly distinct free pilot enrollment.
2. Verify checkout terms: 14-day trial, $50 recurring after trial; avoid charging any customer during tests.
3. Verify authorized Zapier account, lead deduplication, opt-in disclosures and privacy.
4. Implement an authenticated server-side job to collect visitor/cohort events and financial records into a restricted evidence store; do not send client-provided revenue flags.
5. Verify the actual monthly costs, plus the absence of omissions or duplicate settlement/fee deductions.
6. Expose aggregate-only, authenticated `/admin/revenue` data; show 'Not verified' whenever evidence completeness is false.
7. Compare verified net profit / visitors to $1 and optimize conversion, retention and CAC. Keep paper-trading/live-trading safety and risk controls untouched.
8. Only claim the goal reached when real data proves it; neither this feature nor webpage text makes guaranteed profit.

## Financial-ratio display guard

The reporting API must return `null` for revenue-per-visitor and revenue-per-qualified-lead, in addition to net-profit ratios, when monthly revenue/cost evidence is incomplete. When a reconciled aggregate has been signed off, revenue and profit ratios use the SAME certified visitor/lead denominators, never raw GA4 events from a preview or potentially bot-filled campaign source. This repo is not NIJA's IONOS site builder: deploy and verify a separate privacy-respecting pageview implementation at the published origin before calling the website tracking certified.
