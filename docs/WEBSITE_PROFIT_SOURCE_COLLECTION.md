# Website profit source collection

Status: review-only implementation. Source collection is not production deployment,
financial certification, or proof of the $1 net-profit-per-visitor target.

## Problem and behavior

The offline revenue prototype does not collect data. The existing private reporting
API accepts only signed, reconciled **closed calendar months in UTC**. The new
collector supplies private provisional GA4/Stripe observations for reconciliation.
It does not feed, sign or enable the reporting API automatically.

- GA4 requests `totalUsers` for one complete window with an exact production
  hostname allowlist and no dimensions. It excludes preview hosts and never sums
  daily or hostname user counts, which could count a returning user repeatedly.
- The response timezone must match the requested reporting timezone. Thresholded,
  sampled, grouped or incomplete responses require review instead of certification.
- Stripe identity is checked before retrieving **all** balance-transaction pages.
  No type or currency filter hides refunds, fees or other currencies. Amounts remain
  integer minor units; no automatic currency conversion or sale classification.
- Payouts, transfers and top-ups are not counted as customer revenue. Transactions
  still need product attribution and deduplication against Shopify/provider records.
- Empty results are observations only; they never mean all-source zero revenue.
  Unknown expenses and profit remain null. Transport failures produce no candidate.
- CLI output omits customer names, emails and descriptions. Transaction identifiers
  remain private financial records: never commit output or publish it as a Site.

## Secure execution

In the authenticated finance environment, inject `NIJA_PROFIT_GA4_ACCESS_TOKEN`
using Google's `analytics.readonly` scope and `NIJA_PROFIT_STRIPE_READ_KEY` using a
live **restricted read-only** Stripe key with Account and Balance Transaction read
access only. The `rk_live_` prefix is a guard, not proof of read-only permissions;
verify actual grants securely before execution. Never enter credentials in chat,
source, command arguments or reports. Google access tokens expire; this utility
does not create or store refresh credentials.

Run from the repository root:

```sh
python -m scripts.collect_website_profit_sources \
  --property-id YOUR_VERIFIED_PROPERTY_ID \
  --account-id YOUR_VERIFIED_STRIPE_ACCOUNT_ID \
  --start 2026-10-01 --end 2026-10-31 --timezone UTC
```

The GA4 property's response timezone must be UTC for this example. If the property
uses a different timezone, collect an explicitly matching observational window;
do not relabel it UTC or import it as certified monthly UTC evidence. Resolve the
reporting basis separately without changing property settings merely to pass.
Seven-day candidates can be collected with matching explicit dates/timezone, but
**cannot be fed to the current month-only endpoint**.

## Completion steps

1. Validate authenticated property/account identities and least-privilege grants.
2. Confirm every production hostname is instrumented, including shop/game, with
   appropriate cross-domain identity and consent. An allowlist does not install tags.
3. Run the collector and reconcile totals to the source dashboards. Review GA4
   identity/consent coverage, bot traffic and missing purchase instrumentation.
4. Reconcile live captured sales, taxes, refunds, disputes, fees, Shopify/Printful
   fulfillment, affiliate/sponsor/ad proceeds and all attributable operating costs.
   Match provider/order/payment IDs to avoid counting Shopify and processor receipts twice.
5. Use one reporting basis, currency and timezone. Approve coverage including
   explicit evidence for inactive/zero sources, rather than treating unavailable as zero.
6. The authenticated finance process separately signs a complete monthly envelope
   for the existing API. This collector deliberately cannot issue that approval.
7. Complete the existing owner-access and deployment review, verify authenticated
   report delivery end to end, then compare actual profit/unique visitors to $1.

No production services, payment availability, pricing, advertising budgets or trading
controls change in this implementation. Deployment still requires review under AGENTS.md.

## Official implementation references

- GA4 user metrics: https://support.google.com/analytics/answer/12253918
- Data API: https://developers.google.com/analytics/devguides/reporting/data/v1/basics
- Cross-domain measurement: https://support.google.com/analytics/answer/10071811
- Ecommerce: https://developers.google.com/analytics/devguides/collection/ga4/ecommerce
- Stripe balance transactions: https://docs.stripe.com/api/balance_transactions/list
- Stripe reconciliation: https://docs.stripe.com/reports/balance
- Shopify costs: https://help.shopify.com/en/manual/products/details/product-pricing/cost-per-item
