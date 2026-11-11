# Trading IQ payment contract — production release gate

This branch documents a verified mismatch; it does **not** activate payments.

## Source-of-truth check (2026-11-11)

- Approved deployed game-only archive: SHA-256 `77079538953000d0ebbd741665c081820de3a8c6f60debc0cb6c72502f99d224`.
- Vercel preview `/api/health`: 6 scenarios × 12 rounds = **72 decisions**, `checkout_available=false`, `report_fulfillment_verified=false`.
- Existing repository `web/trading-challenge/public/scenarios.js`: **6** scenarios, one answer each.
- Existing `server/scoring.mjs`: **6** answers; `server/index.mjs` checkout and metadata verification: **6** answers.
- These are distinct implementations. Do not deploy the six-answer checkout backend over the approved 72-decision build.

## Release-blocking acceptance tests

1. Obtain and verify the **actual approved** 72-decision source. Confirm the gameplay answer schema and scoring rubric from that source, not from guesses.
2. Implement server-side validation of exactly the approved game answer payload; reject incomplete, oversized, altered, or replayed requests.
3. Use the existing Stripe $1 product/price for the correct environment. Verify active, USD 100 cents, one-time, exact product ID.
4. Persist checkout intent, payment event and fulfillment idempotently in durable storage. Verify Stripe webhook signatures and reject replays; no duplicate charges or reports.
5. Recover paid reports securely across browsers/devices with authenticated or signed receipt recovery. No raw proof or payment secret in URLs or logs.
6. Run sandbox tests: success, cancellation, timeout, duplicate clicks, webhook retry, partial failure, refunded/disputed charge, and receipt recovery.
7. Require hosted CI/security checks and reviewed deployment; stage and test production build before promotion.
8. Only after all gates pass set `NIJA_REPORT_CHECKOUT_ENABLED=true` in **production** and verify a real production health check. No unauthorized live test charge.

Related issue: #3754.

## Preserve

Free game, existing Stripe accounts/products, NIJA Academy, trading safety controls, and all existing customer records. Do not create a new game, Stripe product, or payment account.

## Verified approved archive inspection (2026-11-11)

- Original owner-supplied `nija-trading-iq-game-only-v515-77079538(1).zip` SHA-256 **matches** `77079538953000d0ebbd741665c081820de3a8c6f60debc0cb6c72502f99d224`.
- The archive includes `offline_tiq_premium/tiq_engine.mjs`, `tiq_scoring.mjs`, `tiq_report.mjs`, `payment_flow_6b.mjs`, `storage_spec_6b.mjs`, and `GAME_BACKEND_INTEGRATION_SPEC.md`.
- Local `node --test *_test.mjs` in `offline_tiq_premium/` completed **7/7 test-file subtests passing**, zero failures. These are offline tests, **not** Stripe sandbox E2E tests.
- `GAME_BACKEND_INTEGRATION_SPEC.md` explicitly states **SPECIFICATION ONLY. NOT IMPLEMENTED** for server integration; `LAUNCH_VERIFICATION_20261109.md` states preview-only and paid report coming soon. The included payment flow and storage modules are not proof of deployed durable payment infrastructure.
- Implement the new payment backend against this verified archive; do not reuse the older six-answer `web/trading-challenge` checkout without adaptation and independent test certification.
