# NIJA 12-round Trading IQ — IONOS integration handoff (review-only)

**Status:** PREPARATION ONLY. This document is not a deployment, an implemented payment API, or an authorization to enable Stripe. The canonical 12-round IONOS source is not contained in this repository. The existing six-round app under this directory and five-round Render billing module are DIFFERENT products and must not be silently treated as the IONOS game.

## Product contract
- One unified educational product: twelve fictional rounds **free to play**; optional one-time USD $1 unlock of personalized feedback for **eligible adults age 18+ only**. A visitor who does not buy does not generate $1 revenue.
- The paid results belong to the completed twelve-round run; reopen without a second charge for the permitted entitlement lifetime.
- All transaction amounts, pricing identity, eligibility, report authority and scoring must be enforced on a server with durable storage. No real-money trade, brokerage calls, lotteries, prize draws, live performance claims or customer orders.
- Under-13 Academy programming remains free of this game promotion; ages 13–17 may use approved educational content without payment solicitation. Obtain legal review of parental/age wording before launch.
- Preserve NIJA's existing $99 Trading Foundations checkout, customer records, application timestamps, consent data and trading authorization.

## Files added for review
- server/tiq12-contract.mjs: **pure** private manifest/answer/receipt validators. Provides version-pinned twelve-round scoring and rejects missing buyer proof, inappropriate age declarations, wrong offer or environment, unverified/returned/disputed purchases and malformed answers.
- tests/tiq12-contract.test.mjs: deterministic tests using fictional scenarios and fake payment objects. The test manifest is **not** the IONOS canonical game content.

These functions are **not** wired into server/index.mjs or billing_service.py, and they **must not** be imported into public/scenarios.js, public/app.js or a browser bundle. This deliberate separation avoids changing the currently merged six-round experience or switching on payment under a mismatched configuration.

## Required IONOS source export before implementation
Obtain the current project export from AI App & Site Builder project aibuilder-4dfdf (Code > Export all), excluding secret files and private customer data, then:
1. Locate the actual twelve-round scenario definitions and private scoring rules; compare the published/preview version and age rules.
2. Produce a *server-owned* manifest containing exactly 12 unique ordered round IDs, bounded choices, point values, feedback and lesson mapping; preserve the established content and teaching sequence. Version it and pin its calculated digest.
3. Reconcile public game decisions with the manifest. Never accept client-provided labels, results, prices, manifest digests, admin role, adult status or payment confirmation as authority.
4. Keep the original Academy journeys, mobile styles, saved-progress behavior, youth rules, $99 course and application data intact.

## Minimum approved backend operations (not implemented in this PR)
1. **POST /game/runs**: initialize a cryptographically unique run and HttpOnly first-party ownership receipt, with abuse controls, separate preview/live data and appropriate consent. Do not use email alone as ownership.
2. **POST /game/runs/:id/complete**: validate and save 12 ordered selections against an authenticated server-held ruleset and run; bind age declaration and submission consent. Store completed_at and version/digest. Single run cannot be completed with a different manifest or result.
3. **POST /game/checkout**: require completed adult-owned run; idempotently create a Stripe Checkout Session with **fixed 100-cent USD one-time price** in that environment, signed/opaque run reference and hashed ownership proof. Verify the configured active Stripe Price/Product and attach server-controlled metadata; never embed Stripe secrets or pass calculated scores from the client. Use the latest supported Checkout Sessions integration and dynamic payment methods.
4. **POST /game/stripe/webhook**: use raw request body and Stripe signature verification; persist event IDs uniquely and reconcile checkout.session.completed, checkout.session.async_payment_succeeded / async_payment_failed, refunds, disputes and related reversals. Fulfill only once against the verified paid session, exact line item, amount, currency, mode and buyer/run ownership. Return 2xx to retries only after durable commit; never grant access on success URL alone.
5. **GET /game/report/:runId**: require authenticated browser/account ownership, durable verified entitlement and current refund/dispute status; compute the private report from persisted canonical answers and the matching manifest. Permit authenticated reopening without charging twice for the approved retention period; support receipt recovery or customer support for lost-device access.
6. **GET /game/admin/analytics**: enforce server-side admin access and consent, unique visitor and event deduplication; calculate revenue only from authoritative paid transactions less refunds, fees and documented costs. Emit UNVERIFIED when data is incomplete.
7. Durable storage with additive isolated tables for game_runs, checkout_attempts, stripe_events, verified_payments, report_entitlements, analytics_events. Require unique keys, database transactions, integrity constraints, private access, backups and rollback before any migration.

## Environment/permission gates
- Stripe live product prod_VZI9N8jDpFrQMt and price price_1UY9YmI0gfJjTf3E1h6mYC2S were read back as a USD $1 one-time price, **but the live product description refers to five rounds**. Update/verify the merchant-facing product description and terms in a separate approved change before using it for the twelve-round game. Never silently repurpose a charge intended for different content.
- Prefer a separate Stripe sandbox with a sandbox price ID and restricted key. The old five-round Python module is hardcoded to live-mode Stripe and is **not a valid sandbox backend** for this purpose. Do not turn on NIJA_GAME_REPORTS_ENABLED or NIJA_REPORT_CHECKOUT_ENABLED.
- IONOS support acknowledged it cannot currently confirm custom server-side storage/webhook support or a protected-storage approval procedure. Technical-capability response and safe export/backup method are pending. If unsupported, keep the IONOS frontend but use an isolated externally hosted HTTPS backend with first-party proxy/cookie and strict CORS/CSRF policy.
- Provider secrets, signing secrets and buyer proofs are server-only. Use independent staging/live credentials. No payment secrets, cookies, purchaser data or webhook payloads in PR artifacts, browser or analytics.
- Provisional retention: unpaid attempts 30 days; verified financial records as required by accounting/legal policy (seven years proposed); owned purchased reports accessible for twelve months unless refunded/disputed. Review privacy, refunds, legal age rules and digital-goods purchase terms before launch.

## Release verification — all gates mandatory
- Current 12-round preview source and canonical manifest matched, verified against the IONOS editor with actual export (NOT DONE).
- Real-browser functional/accessibility QA at 375/768/1280, iPhone Safari, iPad and desktop, keyboard/VoiceOver; Academy navigation, resume/refresh/replay and nine lessons (NOT DONE).
- Isolated production-grade database migration, backup and rollback checks; admin analytics denial and consent tests (NOT DONE).
- Stripe sandbox checkout, paid webhook, browser return, page refresh, other-browser denial, buyer recovery, duplicate/reordered webhooks, canceled/async/refunded/disputed payments, outages and chargebacks (NOT DONE).
- Business-review signoff for $1 terms, youth gating, privacy/refunds, fees/tax obligations, revenue-per-visitor reporting (NOT DONE).
- Protected CI/security checks on exact commit, review, controlled staged deployment and release approval (NOT DONE).

**Fail-closed release decision:** No production deployment, no live charges, no reports feature activation, no claims of $1 earned per website visitor. This PR is a safe integration starting point, not a completed game.
