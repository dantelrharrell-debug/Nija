# Upgrade 6 — authoritative 72-decision adapter and payment HOLD

**Status: GitHub-only implementation for review. NOT deployed, not linked to IONOS, not authorized to charge.**

## Corrected source of truth

The verified approved v515 export under `web/trading-challenge/v515/offline_tiq_premium/` defines **six challenges, twelve rounds each, 72 decisions**. The older `server/tiq12-contract.mjs` accepts a different **twelve-answer** manifest and **must not** be connected to the 72-decision game.

The new `server/tiq72-authoritative-adapter.mjs` imports the v515 `tiq_engine.mjs` directly, validates exactly 72 action/stop decisions using `validateRun`, rejects browser-supplied score fields, and recomputes the official results via `replayRun`. It is pure, offline-only code, not an HTTP service. `tests/tiq72-authoritative-adapter.test.mjs` provides 200 seeded comparisons with the approved engine plus invalid-payload checks. Hosted CI must execute and pass before any certification claim.

## Required backend integration plan (not implemented)

1. Confirm actual authenticated IONOS project `aibuilder-4dfdf` preview, including its exact current source and the Upgrade 6 nine-endpoint contract. A GitHub source archive and SHA do not establish IONOS preview access.
2. Establish **one dedicated, private, isolated** preview database and approved migration/rollback; do not reuse the website, course, trading, or lead stores. The existing `STORAGE_DESIGN_5D.md` is a design, **not** an applied migration.
3. Add an authenticated HTTPS server route to accept only adult-eligible 72-decision runs; server issues an opaque owner credential, hashes it privately, and stores the validated decisions and authoritative replay results. Free guest play stays local with no backend collection.
4. Persist one stable Stripe Checkout reservation and idempotency key per completed run. Server verifies existing **test-mode** USD 100-cent one-time price/product. Never accept a browser amount or score. Handle crash/retry reconciliation.
5. Verify the **raw-body** Stripe signature and independently retrieve the Checkout Session, line items, payment intent and charge. Grant only after verified test-mode paid status; never grant from a redirect. Process async failures, expiration, refunds, disputes and duplicate deliveries idempotently.
6. Deliver the paid report only when a private entitlement is active and the requester presents the server-issued owner credential. Provide a separate, approved receipt-recovery design that does not leak codes or payment identifiers.
7. Install `STRIPE_TEST_SECRET_KEY` and `STRIPE_TEST_WEBHOOK_SECRET` only in the approved hosting provider's protected environment settings. **Presence and validity are unverified**; never request, reveal, or copy secret values to chat, GitHub or the browser.
8. Test hosted checkout, cancellation, duplicate clicks, retries, refunds, disputes, report reopening, youth exclusion, mobile QA, backup restore and no-cache/CORS/rate limits. Obtain owner approval before deploying, connecting IONOS, enabling test checkout, or activating any live payment.

**Release gate: NO-GO** until these requirements pass. The `$1 Coming Soon` state must remain unchanged.
