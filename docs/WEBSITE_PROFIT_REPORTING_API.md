# NIJA signed website-profit reporting endpoint

This endpoint is an additive, **GET-only** administrative reporting surface on the
existing standalone billing application. It does not modify checkout, subscriptions,
webhooks, onboarding, or trading. Missing evidence must never display as profit.

Endpoint: `GET /api/admin/website-profit?period=YYYY-MM`
Authorization: `Authorization: Bearer <NIJA_PROFIT_DASHBOARD_TOKEN>`

## Required private configuration

Provision via Render's protected environment settings, *not* GitHub, IONOS JavaScript,
logs, email, or the visitor form:

- `NIJA_PROFIT_DASHBOARD_TOKEN`: unique high-entropy token, >=32 characters.
- `NIJA_PROFIT_EVIDENCE_HMAC_KEY`: separate high-entropy HMAC key, >=32 characters.
- `NIJA_PROFIT_EVIDENCE_DIR`: restricted private directory containing signed `YYYY-MM.json` files.

Do not send these values to clients or public pages. Restrict directory ownership and
permissions. Use encrypted, durable private storage and independent evidence custody.
Render's default ephemeral filesystem is **not** sufficient for durable evidence custody.
Ensure the authenticated finance importer signs files after independent verification.
Never treat user-submitted amounts, page clicks or trial signups as authenticated sales.

If the keys or directory are missing, the API returns HTTP 503 rather than
asserting a financial result. If the bearer token is missing or wrong, returns 401.
If the evidence is missing or tampered with, the status is `unverified`, with
null profit and target-met values. Only closed monthly reporting periods may be
certified. Response is aggregate-only and uses `Cache-Control: no-store`.
`verification_status` is `VERIFIED`, `PARTIAL`, or `UNVERIFIED`; absent visitor
evidence never becomes a zero count. Gross revenue, refunds, and cost totals
are null unless the corresponding stream is complete. Confirmed partial
revenue may remain visible in `net_verified_revenue_usd`, alongside explicit
stream-completeness flags. `reconciliation_freshness` reports the optional
signed `reconciled_at` timestamp and is null when the importer did not provide it.

The current interface accepts closed calendar months only. It does not provide
7-, 30-, or 90-day windows, a browser dashboard, provider collectors, or GA4
ingestion. The repository has no production IONOS site-builder source to wire
to `/admin/revenue-per-visitor`; those pieces require the authorized site and
provider integrations, consent policy, and durable evidence storage before
deployment. Do not label those unavailable surfaces as verified.

## Signed file specification

Each `YYYY-MM.json` must include:

- `reporting_period`: same YYYY-MM as filename.
- `revenue_events`: array of deduplicated `visit`, `qualified_lead`,
  `revenue`, and `refund` events, each with `event_id` and matching `period`.
  Revenue/refund events additionally contain `source` from
  `website_revenue_attribution.REVENUE_SOURCES`, `verified:true`, and
  `amount_usd` as an exact USD string. Provider imports should include
  `provider_transaction_id` (or `transaction_id`) to collapse webhook, order,
  settlement, and import retries within a provider. When two providers report
  the same underlying transaction, include the same independently reconciled
  `canonical_transaction_id`; provider IDs alone are deliberately not
  cross-deduplicated. Duplicate identities with conflicting amounts or
  evidence are excluded and prevent certification.
- `cost_events`: each with `event_id`, matching `period`, `verified:true`,
  category from `website_net_profit.COST_CATEGORIES`, and exact `amount_usd`.
  Cost imports may use the same provider/canonical transaction identity fields
  for duplicate detection; conflicting duplicates block the cost certification.
- `revenue_complete`, `costs_complete`: set to true only after authenticated
  reconciliation and monthly close.
- `certification`: `visitor_counts_verified`,
  `provider_revenue_verified`, `qualified_leads_verified`, and `all_costs_verified`,
  each true only after independent approval. Uncertified qualified leads never
  receive a net-profit-per-lead ratio.
- Optional `aggregate_counts`: `unique_visitors` and `unique_qualified_leads`
  as nonnegative integers from independently reconciled first-party analytics
  and CRM sources, plus explanatory `visitor_source` and `lead_source`.
  The signed aggregate overrides an event-based denominator without generating
  fake pageview events; the aggregate must not be lower than deduplicated
  evidence events. Only use this after the corresponding certification flags
  are approved.
- `signature`: lower-case hex HMAC-SHA256 of canonical JSON excluding signature.

Canonical JSON format is `json.dumps(obj, sort_keys=True, separators=(',', ':'),
ensure_ascii=True, allow_nan=False).encode('utf-8')`. The independent finance
process may use `website_profit_reporting_api.sign_evidence(obj, key)` but must
never expose the key, signer, or completeness controls over HTTP.

## Verification sources to connect separately

1. First-party privacy-consented unique website visitors and verified qualified leads.
2. Stripe's reconciled balance transactions, refunds and fees for NIJA's account.
3. ClickBank course settlements and refunds, once available.
4. Approved affiliate and sponsor settlements and ad-network statements.
5. Website hosting, marketing spend, payment fees, software, support, and delivery
   expenses allocated consistently to the same calendar month.
6. Finance close and documented completeness for all relevant provider and cost sources.

**No provider collectors or evidence transfer are installed by this PR.**
Do not mark a month complete without these controls. The user goal is >=$1 net
operating profit per unique website visitor; no feature guarantees that result.

## Regression tests

The isolated `NIJA Website Revenue and Net Profit Tests` GitHub Actions job runs
all `tests/test_website*.py` unit tests, including authentication, signed-file
tampering, missing evidence, profit accounting, data minimization and reporting
period boundaries. The existing billing service readiness checks remain unchanged.

## Data-quality gate before certifying October 2026

Connected GA4 currently reports more new users than total users for October 1–29.
GA4/Google Ads also report thousands of advertising conversion events without
matching independently verified NIJA lead records. Several large referral
sources are not obviously relevant to trading education. These are unresolved
data-quality and attribution anomalies, **not proof of fraud**. Do not
approve `visitor_counts_verified` or `qualified_leads_verified` until
analytics coverage, bot filtering, referral quality and canonical lead
submissions are independently reconciled. Treat the current period as OPEN.

The reporting endpoint is not a collector, campaign controller or database
query proxy. It cannot fix advertising attribution or generate paid customers.

## Read-only browser dashboard (same-origin)

The Flask billing service mounts `website_profit_dashboard.create_dashboard_blueprint()`
at **`GET /admin/revenue-per-visitor`**, alongside the existing
`GET /api/admin/website-profit?period=YYYY-MM` on the **billing service origin**.
The route is a static HTML/CSS/JavaScript shell; no payment evidence, visitor
identifiers, admin token, or live financial records appear in the HTML.
The reporting data requires the same existing bearer token and independently
signed, closed-month evidence as the reporting API.

- The dashboard defaults to the previous **UTC calendar month**, not a rolling
  30-day or 7-day metric. There is no automatic fallback to missing or fake data.
- Administrator enters the private token only into the exact billing-hostname
  page; JavaScript submits it in a same-origin `Authorization: Bearer` header
  and immediately clears the password field. Nothing is stored in localStorage,
  cookies, URL query parameters, browser analytics, or an external script.
- A strict, nonce-based Content-Security-Policy limits scripts and styles to
  the response, blocks frames and third-party requests, and prevents form
  posts. Response is `no-store`; unsupported HTTP methods return 405.
- **All financial totals remain UNVERIFIED unless** API `status=verified`,
  `verification_status=VERIFIED`, all three independent visitor/revenue/cost
  certifications are true, the month is closed, and revenue and cost evidence
  completeness are true. The optional lead count requires its separate flag.
- No request from the dashboard creates an event, sends an email, submits an
  order, calls a broker, restarts trading, or modifies any provider record.
- The dashboard is **not** the IONOS site builder's existing
  `/admin/revenue-per-visitor` UI. To link or embed it under
  `https://nijaaitrading.com`, the authenticated IONOS editor must first
  implement an authenticated server-to-server integration. Never redirect
  untrusted website visitors into an admin-token entry form.

### Activation is a separate, evidence-gated step

A successful deploy makes the safe review interface available but does **not**
activate certified financial reporting. Configure
`NIJA_PROFIT_DASHBOARD_TOKEN`, `NIJA_PROFIT_EVIDENCE_HMAC_KEY`, and a durable
`NIJA_PROFIT_EVIDENCE_DIR` in restricted Render production settings only
after the independent revenue/visitor/cost evidence and custodian approval
exist. The two secret strings must be independent, at least 32 characters
each, and never written to GitHub or website HTML. Missing evidence must
remain null/UNVERIFIED, not coerced to $0 or certified true.

Track full GA4/consent-aware source reconciliation, actual processor payouts,
refunds and all attributable expenses separately before announcing NIJA has
achieved $1 net profit per visitor.

