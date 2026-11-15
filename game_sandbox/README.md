# Isolated Trading IQ payment sandbox

Current recovery evidence and verified-UI startup contract:
[STAGING_RECOVERY_20261111.md](STAGING_RECOVERY_20261111.md). The GitHub account
billing lock, matching frontend package and reviewed paid staging apply remain
external completion requirements.

Preview client and return-page integration are now available on a review branch;
see [CLIENT_INTEGRATION.md](CLIENT_INTEGRATION.md) for exact installation, tests
and current hosting blockers. This is not proof of installation in IONOS or
operational hosted payments.

Sandbox implementation with the recovered existing 72-decision report; **not deployed or connected to the IONOS preview**. No production entrypoint imports this package. Live keys and live events are rejected regardless of feature flags. Existing free game, Academy, $99 course and trading service are unchanged.

## Architecture and current evidence

Use a **dedicated Render game staging service and dedicated persistent disk**, serving the exported existing game and its API from one HTTPS origin. Link to that app from IONOS when approved. This avoids assuming that IONOS supports protected storage, private credentials, webhooks, cross-origin cookies or a reverse proxy. Do not deploy into `nija-billing-api`, `nija-billing-api-staging` or the trading process; these have existing responsibilities and production billing uses an older Stripe SDK. A standalone Render process can reuse the proven price/ownership checks without sharing production credentials or databases.

| Option | Assessment |
| --- | --- |
| Protected IONOS storage | Unsupported/unconfirmed in ticket 6aebeaf870f76ca9e19ceea2; no migration performed or request resent. |
| Existing Render billing process | Existing five-decision/live-only contract does not match this product. Keep intact. |
| Dedicated Render game app | Recommended staging boundary: Flask API, separate Stripe sandbox, private SQLite disk, one instance. Backup/restore verified locally; hosted persistence and off-host backup remain unverified. |
| Other external backend | Adds a provider and migration without resolving missing canonical source. No need at this stage. |

Render inspection in this session found auto-deploy enabled on the existing billing and billing-staging services. Keep this change on a review branch. Do not merge or deploy merely to test it.

The public website provides `assets/TradingIQChallenge-xoOHPSFe.js`, which includes the existing game and report implementation. Its SHA-256 and the extracted pure module's SHA-256 are pinned in `ionos_source.py`. This resolves the served game's structure: **six challenges of twelve rounds = 72 decisions**, with `{action: buy|sell|hold, stop: boolean}`, three difficulty levels and standard/daily modes. The earlier five-, six- and twelve-decision contracts are different products and remain unchanged.

`ionos_published_report.mjs` reuses the existing scoring, assessment, narrative, 72-decision history, adult Academy mapping and script-free HTML export. `ionos.py` validates/stores the real payload and invokes that exact JavaScript using Node. `ionos_parity.test.mjs` compares it against the independently extracted actual UI reducer for all three levels, both modes and four play styles. All scores, final balances, drawdowns, trades, stop usage and 72 feedback messages match. These tests verify the currently served build; equivalence to the latest inaccessible IONOS preview remains unverified.

## Implemented boundaries

- Adult self-attestation required before persisting payment runs; no date of birth collected. This is not independent age verification. Youth free-play behavior is untouched.
- First-party Secure/HttpOnly/SameSite cookie; only its hash is stored. Exact origin and per-run CSRF token required for mutations; no cross-origin access grants. Owner receipt remains stable across runs.
- Immutable server-validated decisions, source/version/manifest pins; no browser scores or report accepted.
- Exactly 100-cent USD one-time sandbox Price/Product validated server-side. No subscriptions or card data handled by this API.
- One durable Checkout reservation per run; fixed Stripe idempotency key. Ambiguous requests stop before Stripe's idempotency retention expires. Expired/cancelled sessions are not automatically replaced, avoiding a second charge.
- Official SDK raw-body signature verification; atomic event deduplication and entitlement transitions. Both completed and async-success events supported; unpaid sessions cannot fulfill. Provider failures roll back event processing.
- Sticky revocation for refunds and disputes, including reversal-before-completion delivery. Conservative policy requires operator review to reinstate after a failed refund or won dispute.
- Reopening requires cookie ownership, durable webhook grant and fresh Stripe checks. A shared return URL alone grants nothing. Receipt loss/expiry requires a future authenticated recovery flow; email alone is never sufficient. No automated second charge.
- Paid reports remain eligible for reopening after the original run's expiration, until buyer-authorized deletion or entitlement revocation; unpaid or revoked runs remain blocked. A fresh Stripe check must still succeed. Document retention and deletion requirements before the live release.
- The served-build integration calls the original report implementation with stored 72-decision selections. The generic pinned-adapter path remains available for a later preview export. No replacement game, fabricated scores or new paid report UI is introduced.
- Private database permissions, transaction constraints, consistent backup and restore tests; persistent rate limits and bounded HTTP payloads. Use verified ingress IP limiting on hosted staging as well.

## Run tests

New hardening checks cover actual source-byte pinning and browser-owned report reopening in addition to the original sandbox suite. Run them against the precise release commit; a local test pass cannot substitute for hosted Stripe Checkout, IONOS-parity testing or production security gates.

Use a separate Python environment; production dependency files are not changed.

```sh
pip install -r game_sandbox/requirements.txt pytest
python -m pytest tests/test_game_sandbox.py -q
node --test game_sandbox/ionos_parity.test.mjs
python -m pytest tests/test_game_sandbox.py tests/test_game_sandbox_source_pin.py -q
node --test tests/test_game_sandbox_client.mjs
node --test web/trading-challenge/tests/*.test.mjs
```

## Staging launch contract

Install Node 22 alongside the isolated Python environment; Node executes the original report without translating its formulas.

`python -m game_sandbox.staging_bootstrap` starts the isolated staging process only after enforcing non-root execution and, when enabled, the dedicated private writable mount. It then launches the single-worker Gunicorn service. Serve the existing exported game at `/` and proxy `/sandbox/` on the **same staging origin**; do not assume IONOS can provide that proxy. Never serve the database, report adapter, manifest or environment files as static assets.

All settings are distinct from existing billing/trading environment variables:

- `NIJA_IQ_SANDBOX_ENABLED=true` (default: disabled)
- `NIJA_IQ_SANDBOX_DATABASE`: absolute path on the dedicated private staging disk, basename `trading_iq_sandbox.sqlite3`
- `NIJA_IQ_SANDBOX_ORIGIN`: exact HTTPS staging origin
- `NIJA_IQ_SANDBOX_STRIPE_KEY`: restricted sandbox key, minimum Price read, Checkout write/read, PaymentIntent/Charge read permissions
- `NIJA_IQ_SANDBOX_WEBHOOK_SECRET`: signing secret for that sandbox endpoint
- `NIJA_IQ_SANDBOX_PRICE_ID`, `NIJA_IQ_SANDBOX_PRODUCT_ID`: dedicated sandbox $1 offer identities
- `NIJA_IQ_SANDBOX_MANIFEST`, `NIJA_IQ_SANDBOX_MANIFEST_SHA256`: private canonical JSON file and digest from `Manifest.digest`
- `NIJA_IQ_SANDBOX_SOURCE_EXPORT`: **required**, private read-only canonical IONOS export file (e.g., a ZIP). The service now streams its SHA-256 at startup and requires an exact match with the manifest's `source_sha256`; missing, symlinked or modified exports fail closed.
- `NIJA_IQ_SANDBOX_REPORT_ADAPTER`, `NIJA_IQ_SANDBOX_REPORT_ADAPTER_SHA256`: private Python adapter exposing `build_report(answers)` and its UTF-8 content digest; adapter must call the exported existing report implementation with verified parity tests

For the recovered existing report, set `NIJA_IQ_SANDBOX_GAME=published72` and pin `NIJA_IQ_SANDBOX_MANIFEST_SHA256` to `PublishedGame().digest`. This path uses bundled integrity-checked game/report logic; no export or custom Python report adapter is required. It returns the original report plus its existing downloadable HTML after verified entitlement. Keep the feature disabled until the staging host, sandbox credentials and signing endpoint are configured.

Generic manifest shape: `version`, `source_sha256` of canonical IONOS export, `structure` (`12_total` or `12_per_challenge`), `challenges` containing ordered `rounds`, each with unique `id` and integer `choices` count. A total-12 manifest can group its decisions across six challenges. Six challenges of twelve each require `12_per_challenge`. Do not configure either shape until the actual source is inspected.

Wire `client.mjs` into the matching existing staging UI only after source-version verification. Use `completePublishedGame({mode, level, dayNum, decisions: decLog})`; the adapter groups the original 72 decisions into six challenges and never submits client scores. `report()` returns the original report for the existing component, and `downloadHtml()` returns its script-free HTML export. Start after adult attestation, save ordered choices with `complete`, open Checkout only after explicit optional-$1 disclosure. On return, `resume(runId)` then `report()`; pending webhook should show a retry state, never another charge. Render the original report using safe text/escaping and its existing responsive layout. The backend report is connected and exercised in local simulated payment tests. The browser adapter is not installed into inaccessible IONOS source.
The browser adapter can save only the opaque non-secret `runId` in first-party localStorage (no owner receipt, CSRF token, answer history or payment data). `resumeSaved()` verifies the existing private HttpOnly cookie with the server before any report is requested; different browsers cannot reuse the run ID. Browser storage can be unavailable, and lost/expired ownership still requires a future authenticated recovery flow.

Wire `client.mjs` into existing preview UI only after export/parity verification. Start after adult attestation, save ordered choices with `complete`, open Checkout only after explicit optional-$1 disclosure. On return, `resume(runId)` then `report()`; pending webhook should show a retry state, never another charge. Render the original report using safe text/escaping and its existing responsive layout. The adapter is delivered but not installed into inaccessible IONOS source.

Required webhook subscriptions: checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed, charge.refunded, charge.dispute.created, charge.dispute.updated, charge.dispute.closed, refund.created, refund.updated, refund.failed. Authenticate signature on the exact raw body. Do not log payloads, receipts or request cookies.

## Remaining verification

Latest IONOS preview equality with the recovered served build; actual sandbox resources and hosted HTTPS webhook; completed hosted Checkout payment and refund/dispute evidence; 375/768/1280 browser layouts on the actual preview; hosted disk restart and off-host restore. Local tests exercise the actual recovered report after signed simulated payment verification, including reopening without a second charge. They do not represent completed Stripe-hosted transactions. Existing-account Stripe test-mode sign-in is the alternative to creating another account; no new account creation is required.

No new IONOS storage request is needed. If direct embedding is later required, ask within the existing ticket whether documented server-side HTTPS proxying can preserve Secure/HttpOnly cookies and raw webhook bodies with exact origins. A normal outbound link to a separately hosted game avoids that dependency.

Provider references: https://render.com/docs/disks and https://render.com/docs/web-services. A persistent disk needs a paid service; no service or spending was provisioned. Use SQLite-consistent backups rather than raw disk restore for database recovery.

Browser evidence: completed the publicly served Standard/Beginner game through all 72 Hold decisions in a 1363x936 desktop viewport. Completion showed Trading IQ 50 and six challenge scores of 50, matching server replay. The report remained locked with Adults 18+ Only — $1 — Coming Soon and no payment button. Page width was 1359px within the 1363px viewport. This is desktop flow evidence, not phone/tablet or preview-report layout certification.

The existing prebuild copy-policy check required shortening one adult Academy lesson caption to “Advanced Investing”. The linked lesson ID, age group, score formulas and decision feedback are unchanged; the Academy itself is not edited.

### Required ingress review before enabling

Set `NIJA_IQ_SANDBOX_INGRESS_MODE` explicitly: `direct` only with verified direct
socket clients, or `proxy` with `NIJA_IQ_SANDBOX_TRUSTED_PROXY_CIDRS` restricted
to the actual peer. The proxy must strip incoming X-Forwarded-For and overwrite
it with one verified client address. Unknown peers, missing or multiple addresses
fail closed; never infer identity from Origin or blindly choose the leftmost
forwarded value. Without that proof leave staging disabled. See
[checkout corrections and release review](../docs/trading_iq_checkout_corrections_20261106.md).
