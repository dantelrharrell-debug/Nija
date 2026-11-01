# Billing staging database identity readback

**Status:** implementation and fixture tests only until an authenticated staging Render deployment records a successful probe. This is not evidence of visitor analytics or financial reconciliation.

## Why it exists

The `nija-billing-api-staging` Render service had repeatedly exited during startup after being configured with the bare database name `nija_billing_staging_db` instead of a valid PostgreSQL URL. On November 1, 2026, the operator repaired its URL and deployment `dep-dbjionh42hec73d4uesg` became live, but an HTTP 200 health check alone could not prove that the service was connected to the **staging** database instead of the production database.

## Fail-closed check

On the exact staging Render service ID `srv-dasmtjfpn0mc73948r10`, `billing_service._default_app` invokes `verify_staging_database_binding` **before** creating the SQL-backed billing store and before any table initialization.

The verifier:

1. Parses the configured `BILLING_DATABASE_URL` without logging it.
2. Requires a PostgreSQL URL with the expected staging database `nija_billing_staging_db` and staging Render host `dpg-dbhtsmqjnfac73cbblmg-a` (or that host with a DNS suffix).
3. Uses the configured internal database credentials only inside the service to run **one read-only** `SELECT current_database()`.
4. Fails startup with a generic, non-secret diagnostic if the URL, database identity, or connection is wrong.
5. Emits a non-sensitive `Billing staging database isolation VERIFIED` entry after the readback succeeds.

Other services, including the live `nija-billing-api` service and local test processes, skip the staging-specific verifier. No website forms, customer accounts, payments, ledger writes, Stripe webhooks, analytics consent, or trading functionality are changed by this guard.

**Important:** The guard relies on Render's documented `RENDER_SERVICE_ID` environment variable. The presence of a healthy service without a matching proof log does **not** certify its database binding. If the service is renamed or re-created with a different Render ID, update the source with a review and staged release before considering the proof valid.

## Acceptance checklist

- Staging GitHub SHA matches the reviewed change.
- Focused tests pass (including wrong host/database, malformed URL, production skip, and readback mismatch).
- Render staging deployment status is **live** and `GET /healthz` is HTTP 200.
- Authenticated staging logs contain `Billing staging database isolation VERIFIED` after boot.
- Production billing stays healthy on its own service and is not modified.
- External database IP allowlists remain restricted; no database connection URLs or passwords appear in CI, GitHub, support tickets, chat, or logs.

This implementation does not sign finance records or certify profits. The admin profitability endpoint remains unconfigured (HTTP 503) until private high-entropy tokens, signed durable evidence, source-by-source revenue reconciliation, expense completeness, consent-respecting visitor counts, and authoritative CRM lead reconciliation have been independently established.
