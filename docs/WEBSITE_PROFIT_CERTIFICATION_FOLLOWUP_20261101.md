# Website profit certification status (2026-11-01)

**Disposition: code regression tests pass; staging and production certification remain unverified.**
No revenue, profit-per-visitor result, or $1-per-visitor target is certified by this record.

## Code and workflow evidence

- Current `main` is `298c46483514a7240ac8bc66cfdd7da2fd96ef46`. The isolated website
  revenue, net-profit, reporting API, dashboard, and persisted-lead matrix passed
  **59/59 tests** against that revision. The local runner used Python 3.12.3 and
  the Flask dependency required by the workflow.
- The merged #3540 main workflow passed at
  [`41320693457`](https://github.com/dantelrharrell-debug/Nija/actions/runs/41320693457)
  on SHA `21dad8e00b81ac10e4ad7b9da78760fb2b80901b`.
- The #3540 PR-head website workflow
  [`41320675974`](https://github.com/dantelrharrell-debug/Nija/actions/runs/41320675974),
  main CI `41320676031`, preflight `41320676108`, security scan `41320676082`,
  and branch policy `41320675728` were reported failed on
  `ef79a09a0888dc5edb4dd11fa0cea92ba455bf38`. Actions returned zero jobs for
  these runs; `get_job_logs` found no failed jobs. These records therefore provide
  no step-level failure or evidence of a test/code defect. The post-merge website
  workflow passed as noted above.

## Staging billing service: not independently validated

The repository's prior operator report identifies staging service
`srv-dasmtjfpn0mc73948r10` (`nija-billing-api-staging`), staging database
`dpg-dbhtsmqjnfac73cbblmg-a`, and deployment `dep-dbjionh42hec73d4uesg`.
It also records production deployment `dep-dbjckenavr4c73bufo3g`. That report
states the deployments were live on the older SHA
`a8c1cc634521b5d9af1ea2d24bc99df2bd061c3c`, but explicitly does **not** prove
database identity. These IDs and status are historical repository records, not
a current authenticated Render readback or proof that this code is deployed.

This run had no authenticated Render or dashboard access. It did not obtain a
current deployment ID/SHA, health response, startup log, effective staging
database identity, or production/staging separation readback. It also did not
call the reporting endpoint. Required evidence remains:

1. An authorized operator's current staging deployment ID/SHA and live status;
   redacted startup proof and restricted read-only `current_database()` readback
   through the service's effective connection, matched privately to the staging
   database resource. Confirm production uses a separate resource.
2. Read-only staging and production `GET /healthz` results.
3. Staging `GET /api/admin/website-profit?period=2026-10` results without
   authorization and with an invalid bearer token (both must return 401 without
   financial data), plus an authenticated read-only dashboard response showing
   only authorized aggregates and `unverified` status when evidence is incomplete.
   The endpoint's documented 503 when reporting is unconfigured is fail-closed,
   but is not configured-reporting acceptance.
4. UTC timestamps, redacted request/status evidence, current deployment IDs/SHA,
   and operator/reviewer approval. Do not share database URLs, dashboard tokens,
   or customer records in this repository.

No staging or production deployment was initiated as part of this review.

## Monthly financial evidence: incomplete / unavailable here

No signed, closed-month source attestations were available to this run. October
2026 revenue or profit must not be inferred from code tests, a live endpoint,
trials, failed charges, clicks, or synthetic fixtures. An authorized finance
owner must provide a consistent cash/accrual basis, post-close signed
reconciliation timestamp, and completeness attestation for the month, covering:

- Consent-aware first-party unique visitors and qualified leads, with matching
  period, deduplication, and bot/data-quality review.
- Stripe settled/recognized payments, refunds/disputes, fees, canonical
  transaction deduplication, and reconciled provider readback.
- Printful earned/settled proceeds, refunds, and fulfillment costs; ClickBank
  settled sales, refunds, fees, and commissions; payable/settled affiliate
  commissions; verified sponsor/ad payments and corresponding expenses.
- Hosting/software, paid acquisition, personnel/service delivery, payment
  processing, fulfillment, support, chargebacks, and other attributable costs,
  reconciled to source records and the bank/accounting close.

Missing access is to the relevant provider read-only records and signed source
attestations, not a request to place test orders or create evidence. The
attestations must come from the authorized source/finance owners; do not generate
or sign them in code or in this repository.

## IONOS integration: separate check not performed

This repository is not the IONOS site builder, and no IONOS administrator or
published-site evidence was available to this run. A separately authorized
operator must verify the live primary CTA (`/enroll`), secondary CTA (`/free`),
distinct free pilot route (`/apply`), consent/privacy behavior, and the published
origin's privacy-respecting visitor measurement. Record the observed origin,
UTC time, and redacted evidence without customer data. Repository instructions
and local tests do not establish that the live site is integrated.

## Handoff and close status

Needed access/approvals are: authorized Render read-only access; a securely
handled staging dashboard credential and current staging origin; provider
read-only evidence from each source owner; signed finance close/completeness
approval; and IONOS site-builder access plus a reviewer for the integration
check. No matching integration credentials were exposed to this agent process.
Do not place credentials or signed financial source records in a PR.

No code defect was found, so no focused implementation PR is warranted by these
tests. Keep the financial certification blocked until the external evidence
above is independently recorded. This follow-up must not be marked verified or
closed as a production/revenue certification based only on the passing tests.

References: [`BILLING_SERVICE_DEPLOYMENT.md`](../BILLING_SERVICE_DEPLOYMENT.md),
[`BILLING_STAGING_DATABASE_IDENTITY.md`](BILLING_STAGING_DATABASE_IDENTITY.md),
[`WEBSITE_NET_PROFIT_PER_VISITOR.md`](WEBSITE_NET_PROFIT_PER_VISITOR.md), and
[`LEAD_MONETIZATION_EVIDENCE_GATES_20261101.md`](LEAD_MONETIZATION_EVIDENCE_GATES_20261101.md).
