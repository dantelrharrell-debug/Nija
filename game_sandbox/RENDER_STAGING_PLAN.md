# NIJA 72-decision Trading IQ — Render sandbox staging plan

**Workspace selected by owner:** Nija (workspace ID `tea-d3qjmmc9c44c73cqvpug`).
**State:** infrastructure review only. Do not merge into live trading/billing.
**No real customer charges.** The image rejects live Stripe keys and starts with all
payment routes unavailable by default. Its health endpoint reports
`checkout_available=false` until a separately authorized test-mode setup.

## Current account constraint

On 2026-11-05 the only existing `Nija` workspace service
`srv-d3qtoogdl3ps73c7ovog` was reported by Render as
`suspended` with suspender `billing`. Do not deploy to another workspace
implicitly, repurpose that existing service, or attempt workarounds for the
billing hold. Resolve provider billing status before any paid resource apply.

## Reviewed infrastructure definition

The isolated blueprint is `game_sandbox/render.staging.yaml`, on a dedicated
review branch. It defines exactly one Oregon web service with:
- Docker Node.js 22 + Python 3.11 (original 72-decision report code remains JS).
- One starter-tier instance with 1 GB private persistent disk at `/var/data`.
- Manual deploys only (`autoDeployTrigger: off`), no link to existing billing.
- A non-root Gunicorn process; disabled-by-default payment API; /healthz status.
- A pinned 72-decision published-game manifest and a fail-closed entitlement DB.
- No production Stripe secrets, no test secrets in Git, no trading credentials.

**Cost**: Render Starter compute and persistent disk are billable. An operator
must review provider pricing and explicitly authorize the exact costs before
approving the Blueprint plan. Simply selecting the workspace is not cost
approval. Render Blueprint `autoSync=false` means future pushes do not
automatically apply infrastructure changes.

## After authorized infrastructure creation

1. Verify service builds, the published `/healthz` is honest, and every
   `/sandbox/` route rejects requests with 503 in disabled mode.
2. In the **Render Environment page**, configure sandbox-only
   `NIJA_IQ_SANDBOX_ORIGIN` to the service's actual HTTPS origin; set the
   restricted Stripe test key (`rk_test_...` or `sk_test_...`), webhook signing
   secret `whsec_...`, sandbox price ID and product ID. The existing test-mode
   product and price were previously created and verified on Stripe's NIJA
   sandbox account. Do not paste secret values into chat or GitHub.
3. Register a **new Stripe test-mode webhook** for
   `https://<staging-host>/sandbox/stripe/webhook`. Do not repoint NIJA's
   existing live-course webhook.
4. Install the matching **published 72-decision game UI** on the same staging
   origin and connect `SandboxReportClient`; this is not yet done. The API alone
   does not deliver a finished browser game. Confirm the source hash against
   the IONOS editor and the `ionos_published_report.mjs` parity tests.
5. Test a complete real Stripe test-mode run, webhook, report download,
   unpaid/cancel/refund/dispute denial, idempotency, loss of receipt, backup
   and restore, and mobile browser dimensions.
6. Resolve repository-wide security/artifact scan failures before separately
   authorizing a paid production launch. Never use this test-only service for
   live card charges: the server explicitly rejects live Stripe keys/events.

## Rollback

Keep the stage disabled (`NIJA_IQ_SANDBOX_ENABLED=false`) or suspend the
dedicated game service. Retain disk contents for backup/restore. Do not affect
Nija Ai Trading Live, Nija_Trading_Bot, the free game, the $99 course, or
brokerage/trading authority.
