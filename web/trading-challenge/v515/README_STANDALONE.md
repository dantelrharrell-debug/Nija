# Verified v515 standalone adaptation — payment hold

Approved archive SHA-256: `77079538953000d0ebbd741665c081820de3a8c6f60debc0cb6c72502f99d224`.

The canonical exported game has six scenarios, each with twelve rounds, for 72 decisions. The JSX game, educational content, scoring, report engine, visuals and original offline tests are byte-identical to the approved archive (protected by `approved-source-hashes.json`). The existing six-decision MVP and test-only backend are retained untouched.

Adaptations: portable Vite/React/Tailwind build, standalone React entrypoint, no-op IONOS telemetry, local-only simulated report preview, explicit fail-closed payment routes and security headers. Academy links forward to the main website. No customer records, Stripe keys or trading imports are added. Existing export README/PROVENANCE describes the original archive; this document describes the adaptation.

## Run
`npm ci`, `npm test`, `npm run build`. Deploy this directory as the existing Vercel project's Root Directory only after required checks pass. Keep the legacy directory and production deployment available for rollback.

## Current payment boundary
This version deliberately cannot charge or grant purchased reports, even if `NIJA_REPORT_CHECKOUT_ENABLED=true` is injected. Health reports checkout unavailable. `/api/checkout`, `/api/results`, `/api/recovery` and `/api/webhook` return 503. Public gameplay and free feedback work independently. This is an education-only candidate, not payment certification.

Existing live account: `acct_1Tzy0bI0gfJjTf3E`; one-time USD 100-cent report product `prod_VZI9N8jDpFrQMt`, price `price_1UY9YmI0gfJjTf3E1h6mYC2S`.
Sandbox account: `acct_1Tzy1CRS5Ezp77RQ`; existing product `prod_nija_iq72_sandbox_v1`, price `price_1UYToJRS5Ezp77RQVkx96eS5`. Both accounts and catalog identities were read through authenticated Stripe tools on 2026-11-11; no catalog mutations or purchases.

The existing `../server/tiq12-upgrade6-*` backend is test-only and depends on private durable SQLite storage plus a different manifest contract. It must not be enabled against this game by setting a flag. The approved `offline_tiq_premium/tiq_engine.mjs` can replay the canonical decisions server-side; `tiq_report.mjs` can generate the canonical report after verified entitlement. Integration, durable recovery and real sandbox purchase/reversal tests remain unfinished.

## Required release evidence
- Exact-commit CI and required repository secret/CodeQL checks. Named runtime-tools scanners and CodeQL tools were not available in this session; an ordinary text scan is not equivalent certification.
- Real sandbox browser checkout, server-side price/amount verification, successful report delivery/reload/recovery, cancellation, failure, refunds/disputes and retry/idempotency tests.
- Durable run/payment ledger, atomically unique checkout reservation, signed raw-body webhook verification, current provider reconciliation, private report-access proof and recoverable receipt flow.
- Desktop/tablet/mobile browser QA and review of customer disclosures.
- Verified public production game, DNS/TLS, and link from the IONOS site.

No production activation is authorized by this README. Owner authorization is conditional on passing the above checks. No trading runtime or Founding 100 setting is changed.
