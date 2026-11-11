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
