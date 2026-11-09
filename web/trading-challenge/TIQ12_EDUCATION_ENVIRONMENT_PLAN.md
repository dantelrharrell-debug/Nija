# NIJA Trading IQ 12 — separate Render education environment

**Status: review/plan only. No service, disk, database, webhook, or payment checkout is provisioned or authorized by these files.**

## Destination and explicit separation

- **Target workspace:** Render `Nija` (`tea-d3qjmmc9c44c73cqvpug`), separate from the trading-bot workspace. The existing `Nija` service `srv-d3qtoogdl3ps73c7ovog` is billing-suspended as last verified. Do **not** borrow a production/trading workspace to bypass the provider hold.
- **Protected trading workspace:** `Nija_Trading_Bot` (`tea-d37fhe8gjchc73c8eo0g`) — unchanged; do not adopt, retarget, restart, or redeploy any existing bot, member, billing, or IQ72 service.
- **Other workspace:** `Nija Ai Trading Live` (`tea-d3nl83idbo4c73d3647g`) — unchanged.
- **Reviewable proposal:** `web/trading-challenge/render.tiq12-education.yaml` declares one **new** Starter Docker web service with a separate 1-GB disk, `autoDeployTrigger: off`, `/healthz`, and only public nonsecret flags set to `NIJA_TIQ12_ENABLED=false`, `NIJA_TIQ12_MODE=holding`.
- **No existing service adoption:** The Render Blueprint must use `existingResources=create_new`, `autoSync=false`, its own ID and path. Do not change the separate `game_sandbox/render.staging.yaml` Blueprint: that is for the unrelated **72-decision** prototype.
- **Build boundary:** `Dockerfile.tiq12-education` copies **only two holding-server source files** from the education project, runs Node 22 as unprivileged UID 10001, and has no imported trading, brokerage, billing, game report, or Stripe code.

## Actual functionality — intentionally nothing billable to a customer

`GET /healthz` returns 200 `status=holding` with explicit false capability fields so the hosting provider can observe a safe stopped project. `GET /readyz` and all `/game`, `/api`, `/checkout`, `/stripe`, `/report`, and `/admin` paths return HTTP 503. Any attempt to set a non-holding mode or enable flag **throws at startup**, not merely enables unfinished checkout. No CORS authorization is emitted. No public game, buyer account, report, Stripe session, payment secret, live market order, or customer data is accessible.

The 1-GB disk in the proposed Blueprint is reserved for a possible future private state store. This holding service **does not mount/use SQLite for live run or purchase storage**, perform a migration, declare storage certified, or read the original IONOS twelve-round source.

## Independent certification gates (all required)

1. Obtain the authenticated source export for IONOS AI Builder `aibuilder-4dfdf`, pin the exact 12-round preview build and canonical scoring rules, validate mobile/browser behavior and original Academy links. The public site currently shows **six** challenges; repository IQ72 tests are not 12-round source parity.
2. Restore provider billing eligibility for the **correct, separate** `Nija` workspace. Review the **exact recurring billed Starter service and persistent disk cost** and any tax/usage before approving provisioning. The proposal can be evaluated with Render planning; the provider's plan is not cost approval or permission to deploy.
3. Review disk ownership, mounted private directory, `fsync`/WAL semantics, single-writer protection, off-host backup/restore, retention, and an isolated additive migration plan. The separate `server/tiq12-storage.schema.sql` is **not applied**.
4. Independently implement and review an authenticated test-only run/checkout/webhook/report API, durable idempotent Stripe events and revocations, first-party browser proof, strict Origin/CSRF and request limits. The holding server deliberately offers none of these features.
5. Independently approve a dedicated **12-round** Stripe sandbox product/price and tax policy; the existing sandbox Price `price_1UYToJRS5Ezp77RQVkx96eS5` belongs to a different IQ72 product and MUST NOT be repurposed. Install restricted **test-mode** credentials and distinct webhook signing secret only through the new backend's protected provider settings after a separately approved architecture; never paste credentials into chat, GitHub or browser code.
6. Run signed Stripe test payments/retries/refunds/disputes, idempotent entitlement ownership, revoked and expired access, crash/restart/restore, browser/mobile/assistive technology tests, and clear all mandatory CI/security/artifact gates on the exact release SHA.
7. Obtain a separate, explicit production-release approval before any game publication, infrastructure sync, customer payment or live report activation. NIJA's existing $99 Foundations service and all real-money trading controls remain untouched.

## Manual, non-destructive verification

Tests run via `cd web/trading-challenge && npm test`. The CI workflow picks up `tests/tiq12-education-staging.test.mjs`. A future approved Render plan should use only the dedicated YAML, its own feature branch, `existingResources=create_new`, and `autoSync=false`. **Never call Render `approve_blueprint` before reviewing the resulting resource diff and obtaining deployment and recurring-cost approval.**

If the `Nija` workspace remains billing-suspended, leave the plan unapplied; do not route this staging workload to `Nija_Trading_Bot` or `Nija Ai Trading Live` as a workaround.
