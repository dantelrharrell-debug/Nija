# Isolated Trading IQ payment sandbox

Implementation only; **not deployed or connected to the IONOS preview**. No production entrypoint imports this package. Live keys and live events are rejected regardless of feature flags. Existing free game, Academy, $99 course and trading service are unchanged.

## Architecture and current evidence

Use a **dedicated Render game staging service and dedicated persistent disk**, serving the exported existing game and its API from one HTTPS origin. Link to that app from IONOS when approved. This avoids assuming that IONOS supports protected storage, private credentials, webhooks, cross-origin cookies or a reverse proxy. Do not deploy into `nija-billing-api`, `nija-billing-api-staging` or the trading process; these have existing responsibilities and production billing uses an older Stripe SDK. A standalone Render process can reuse the proven price/ownership checks without sharing production credentials or databases.

| Option | Assessment |
| --- | --- |
| Protected IONOS storage | Unsupported/unconfirmed in ticket 6aebeaf870f76ca9e19ceea2; no migration performed or request resent. |
| Existing Render billing process | Existing five-decision/live-only contract does not match this product. Keep intact. |
| Dedicated Render game app | Recommended staging boundary: Flask API, separate Stripe sandbox, private SQLite disk, one instance. Backup/restore verified locally; hosted persistence and off-host backup remain unverified. |
| Other external backend | Adds a provider and migration without resolving missing canonical source. No need at this stage. |

Render inspection in this session found auto-deploy enabled on the existing billing and billing-staging services. Keep this change on a review branch. Do not merge or deploy merely to test it.

The repository at `f814a38` contains five-decision Python billing, a six-decision web game and an unconnected twelve-decision validator. It does **not** contain the current IONOS report implementation. Neither 12 nor 72 decisions has been certified against that source. `Manifest` supports an explicitly selected shape and pins all ordered round IDs/choice bounds. Fixture rules and report output in tests are labelled synthetic; they are not exported game content.

## Implemented boundaries

- Adult self-attestation required before persisting payment runs; no date of birth collected. This is not independent age verification. Youth free-play behavior is untouched.
- First-party Secure/HttpOnly/SameSite cookie; only its hash is stored. Exact origin and per-run CSRF token required for mutations; no cross-origin access grants. Owner receipt remains stable across runs.
- Immutable server-validated decisions, source/version/manifest pins; no browser scores or report accepted.
- Exactly 100-cent USD one-time sandbox Price/Product validated server-side. No subscriptions or card data handled by this API.
- One durable Checkout reservation per run; fixed Stripe idempotency key. Ambiguous requests stop before Stripe's idempotency retention expires. Expired/cancelled sessions are not automatically replaced, avoiding a second charge.
- Official SDK raw-body signature verification; atomic event deduplication and entitlement transitions. Both completed and async-success events supported; unpaid sessions cannot fulfill. Provider failures roll back event processing.
- Sticky revocation for refunds and disputes, including reversal-before-completion delivery. Conservative policy requires operator review to reinstate after a failed refund or won dispute.
- Reopening requires cookie ownership, durable webhook grant and fresh Stripe checks. A shared return URL alone grants nothing. Receipt loss/expiry requires a future authenticated recovery flow; email alone is never sufficient. No automated second charge.
- Reports are delegated to the **original exported server-side report adapter** with stored selections. No replacement game, fabricated scores or new paid report UI is introduced.
- Private database permissions, transaction constraints, consistent backup and restore tests; persistent rate limits and bounded HTTP payloads. Use verified ingress IP limiting on hosted staging as well.

## Run tests

Use a separate Python environment; production dependency files are not changed.

```sh
pip install -r game_sandbox/requirements.txt pytest
python -m pytest tests/test_game_sandbox.py -q
node --test web/trading-challenge/tests/*.test.mjs
```

## Staging launch contract

`gunicorn --workers 1 --threads 2 'game_sandbox.app:from_environment()'` creates the sandbox API only. Serve the existing exported game at `/` and proxy `/sandbox/` on the **same staging origin**; do not assume IONOS can provide that proxy. Never serve the database, report adapter, manifest or environment files as static assets.

All settings are distinct from existing billing/trading environment variables:

- `NIJA_IQ_SANDBOX_ENABLED=true` (default: disabled)
- `NIJA_IQ_SANDBOX_DATABASE`: absolute path on the dedicated private staging disk, basename `trading_iq_sandbox.sqlite3`
- `NIJA_IQ_SANDBOX_ORIGIN`: exact HTTPS staging origin
- `NIJA_IQ_SANDBOX_STRIPE_KEY`: restricted sandbox key, minimum Price read, Checkout write/read, PaymentIntent/Charge read permissions
- `NIJA_IQ_SANDBOX_WEBHOOK_SECRET`: signing secret for that sandbox endpoint
- `NIJA_IQ_SANDBOX_PRICE_ID`, `NIJA_IQ_SANDBOX_PRODUCT_ID`: dedicated sandbox $1 offer identities
- `NIJA_IQ_SANDBOX_MANIFEST`, `NIJA_IQ_SANDBOX_MANIFEST_SHA256`: private canonical JSON file and digest from `Manifest.digest`
- `NIJA_IQ_SANDBOX_REPORT_ADAPTER`, `NIJA_IQ_SANDBOX_REPORT_ADAPTER_SHA256`: private Python adapter exposing `build_report(answers)` and its UTF-8 content digest; adapter must call the exported existing report implementation with verified parity tests

Manifest shape: `version`, `source_sha256` of canonical IONOS export, `structure` (`12_total` or `12_per_challenge`), `challenges` containing ordered `rounds`, each with unique `id` and integer `choices` count. A total-12 manifest can group its decisions across six challenges. Six challenges of twelve each require `12_per_challenge`. Do not configure either shape until the actual source is inspected.

Wire `client.mjs` into existing preview UI only after export/parity verification. Start after adult attestation, save ordered choices with `complete`, open Checkout only after explicit optional-$1 disclosure. On return, `resume(runId)` then `report()`; pending webhook should show a retry state, never another charge. Render the original report using safe text/escaping and its existing responsive layout. The adapter is delivered but not installed into inaccessible IONOS source.

Required webhook subscriptions: checkout.session.completed, checkout.session.async_payment_succeeded, checkout.session.async_payment_failed, charge.refunded, charge.dispute.created, charge.dispute.updated, charge.dispute.closed, refund.created, refund.updated, refund.failed. Authenticate signature on the exact raw body. Do not log payloads, receipts or request cookies.

## Remaining verification

Current IONOS source/export and report parity; original report adapter; actual sandbox resources and hosted HTTPS webhook; completed hosted Checkout payment and refund/dispute evidence; 375/768/1280 browser layouts on the actual preview; hosted disk restart and off-host restore. Existing local tests exercise SDK signature verification and simulated provider states, not Stripe-hosted transactions.

No new IONOS storage request is needed. If direct embedding is later required, ask within the existing ticket whether documented server-side HTTPS proxying can preserve Secure/HttpOnly cookies and raw webhook bodies with exact origins. A normal outbound link to a separately hosted game avoids that dependency.
