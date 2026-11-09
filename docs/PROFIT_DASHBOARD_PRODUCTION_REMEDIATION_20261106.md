# NIJA revenue dashboard: production remediation and verification (2026-11-06)

Status: **BLOCKED / NOT DEPLOYED**. This runbook is an operational handoff, not evidence of a production fix.

## Observed, read-only
- Owner selected Render workspace `Nija Ai Trading Live` (`tea-d3nl83idbo4c73d3647g`).
- Render `list_services` for that workspace returned `null`. Subsequent read-only inventory of the other workspaces identified production `nija-billing-api` as service `srv-dasn1mbbc2fs738036gg` in workspace `Nija_Trading_Bot` (`tea-d37fhe8gjchc73c8eo0g`), not the selected `Nija Ai Trading Live` workspace. Its repository is `dantelrharrell-debug/Nija`, branch `main`, host `https://nija-billing-api.onrender.com`, and automatic deployment is `checksPass`. The staging billing service is `srv-dasmtjfpn0mc73948r10` in the same trading workspace. These are inventory observations, not a live dashboard health check. Owner confirmation of this different workspace is required before Render writes.
- Repository has a static same-origin `GET /admin/revenue-per-visitor` shell and bearer-authenticated `GET /api/admin/website-profit?period=YYYY-MM`.
- API requires private `NIJA_PROFIT_DASHBOARD_TOKEN`, separate `NIJA_PROFIT_EVIDENCE_HMAC_KEY`, and `NIJA_PROFIT_EVIDENCE_DIR` with signed month-close evidence. A configured dashboard does not establish that evidence exists.
- Current API accepts closed calendar months only. A previous-seven-days report and prior-week comparison are not implemented by this API.

## Non-destructive production sequence
1. Production billing service has been identified in a **different workspace** from the owner-approved one. Confirm authorization for `Nija_Trading_Bot` before any Render writes. Read-only inspect the deployed commit, health, logs, and route responses first; do not infer that a GitHub source route is deployed.
2. Confirm the actual production hostname and TLS. Read-only GET of the dashboard must return HTML, `Cache-Control: no-store`, and CSP. Do not place an admin token in a URL or logs.
3. Check whether the three required environment variables are **present**, without revealing their values. Confirm separate >=32-character secrets and private durable evidence custody. Do not rotate or overwrite existing secrets without a controlled migration.
4. Test a missing/wrong bearer token (401 when configured), missing evidence (UNVERIFIED), and signed closed-month evidence (VERIFIED only with independently reconciled source certifications). Run tests against staging first. Never create fabricated signed financial evidence in production.
5. Reconcile analytics consent and deduplicated unique visitors; CRM leads/waitlist; confirmed course purchases; Stripe settlements/refunds/fees; Printful/Shopify, affiliate and other provider settlements; advertising, hosting, software, fulfilment and support expenses. Confirm cross-provider transaction deduplication and consistent cash/accrual basis.
6. For visitor-to-lead, lead-to-waitlist, and visitor-to-course-purchase rates, define common UTC time windows, consent-aware cohort attribution, qualified event definitions, and stable denominators. Display N/A, not zero, for missing evidence.
7. Implement separate certified **daily** aggregates for rolling seven-day reporting before enabling the Friday review's prior-week comparison. Do not divide monthly net profit by weekly visitor counts.
8. Obtain independent staging verification, owner deployment approval, and a post-deploy read-only check. Preserve checkout, payments, customer communications and trading configuration unchanged.

## Acceptance gates
- Exact approved Render service/host identified and production deployment provenance recorded.
- Authenticated dashboard loads with no credential persistence and no financial data leakage.
- Unauthenticated, missing-evidence, and invalid-evidence paths fail closed.
- Visitor, lead, waitlist and purchase funnels have traceable provider evidence, deduplication and consent checks.
- Monthly profit uses settled/recognized revenue minus refunds and all attributable costs, with fees deducted once.
- Weekly comparisons use a consistent certified seven-day evidence model.
- Tests pass in CI and staging; deployment and read-back are separately documented.

Do not label any gate complete based on this file alone.

## Authenticated Render read-only findings (2026-11-06)

- Production service: `srv-dasn1mbbc2fs738036gg`, owner workspace `tea-d37fhe8gjchc73c8eo0g`; runtime `gunicorn --workers 2 --threads 4 --timeout 60 billing_service:app`, `main`, auto-deploy `checksPass`, health check `/healthz`.
- Latest listed live deployment: `dep-dbmehkgae00c73fasvj0`, commit `e9a33bb2eab43f8119b2c83f756fd5440d901ea1`, completed 2026-11-05 20:37:49 UTC. This does **not** prove that the latest `main` source is deployed.
- Request logs show `GET /admin/revenue-per-visitor` returned HTTP 200 at 2026-11-04 18:41:30 UTC. This proves only that the static shell responded, not authenticated financial access.
- Repeated `GET /api/admin/website-profit?period=2026-09` requests returned HTTP 503 on November 1-4, and October period also returned HTTP 503 on November 4. API code returns 503 if required private reporting configuration is absent/invalid; other invalid-evidence paths also return 503. **Do not claim the exact cause from request status alone.**
- Existing `tests/test_website_profit_dashboard.py` covers fail-closed unconfigured (503), configured unauthorized (401), static shell CSP, no credential persistence, and non-mutating methods. These tests were inspected but **not executed** in this connector session.
- No Render configuration, credentials, payments, trading, or production deployment changed. Do not enable the reporting API by inventing tokens or synthetic signed evidence.

### Next gated work

1. Read-only verify whether all three private configuration keys are present without retrieving their values; confirm restricted durable evidence directory and independent signer. A service inventory and request log cannot verify secret presence.
2. Run isolated dashboard and reporting API unit tests in CI; review any failures before proposing code changes. Do not assert tests passed until a run is observed.
3. Add daily signed evidence contracts and regression tests for 7-day comparisons only after authoritative consent-aware analytics and financial sources are identified. Keep existing monthly API backward compatible.
4. Validate staging with independently approved non-customer fixtures, then obtain deployment approval and perform post-deploy read-back. This PR remains documentation-only and must not be treated as production activation.
