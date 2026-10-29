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

## Signed file specification

Each `YYYY-MM.json` must include:

- `reporting_period`: same YYYY-MM as filename.
- `revenue_events`: array of deduplicated `visit`, `qualified_lead`,
  `revenue`, and `refund` events, each with `event_id` and matching `period`.
  Revenue/refund events additionally contain `source` from
  `website_revenue_attribution.REVENUE_SOURCES`, `verified:true`, and
  `amount_usd` as an exact USD string.
- `cost_events`: each with `event_id`, matching `period`, `verified:true`,
  category from `website_net_profit.COST_CATEGORIES`, and exact `amount_usd`.
- `revenue_complete`, `costs_complete`: set to true only after authenticated
  reconciliation and monthly close.
- `certification`: `visitor_counts_verified`,
  `provider_revenue_verified`, and `all_costs_verified`, each true only
  after independent approval.
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
