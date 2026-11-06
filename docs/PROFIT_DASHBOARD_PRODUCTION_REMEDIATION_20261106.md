# NIJA revenue dashboard: production remediation and verification (2026-11-06)

Status: **BLOCKED / NOT DEPLOYED**. This runbook is an operational handoff, not evidence of a production fix.

## Observed, read-only
- Owner selected Render workspace `Nija Ai Trading Live` (`tea-d3nl83idbo4c73d3647g`).
- Render `list_services` for that workspace returned `null`, not an identifiable billing service. Do not infer that no services exist; obtain an explicit service ID or investigate connector visibility before any deployment.
- Repository has a static same-origin `GET /admin/revenue-per-visitor` shell and bearer-authenticated `GET /api/admin/website-profit?period=YYYY-MM`.
- API requires private `NIJA_PROFIT_DASHBOARD_TOKEN`, separate `NIJA_PROFIT_EVIDENCE_HMAC_KEY`, and `NIJA_PROFIT_EVIDENCE_DIR` with signed month-close evidence. A configured dashboard does not establish that evidence exists.
- Current API accepts closed calendar months only. A previous-seven-days report and prior-week comparison are not implemented by this API.

## Non-destructive production sequence
1. Identify the billing service **within the owner-approved workspace** by exact Render service ID and verify its GitHub repository, deployed commit, branch, host, and route registrations. Stop if the service is missing or the workspace differs.
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
