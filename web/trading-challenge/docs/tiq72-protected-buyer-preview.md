# Trading IQ: protected TEST buyer return

This proposal adds an unmounted customer ingress and a staging-only return view. It is not a public checkout launch. It reuses v515's 72-decision checkout, verified report retrieval and component instead of the old cookie-only return. Free gameplay, prices and live flags are unchanged.

## What it does

- The staging return view is off unless built with `VITE_TIQ72_TEST_RETURN_ENABLED=true` and opened on `nija-trading-challenge-staging.vercel.app`.
- The TEST bridge is off by default. A reviewed same-origin server must mount it, pass the isolated v515 PostgreSQL store and the exact existing Stripe sandbox offer, supply a fail-closed shared rate limiter, and verify the buyer's session server-side.
- The identity dependency must bind a stable NIJA user ID, an active non-revoked account, approved adult eligibility and a session-bound CSRF token. An email address, browser age checkbox, Stripe session ID, test fixture or Vercel Access cookie alone is not an identity proof. The preview must not expose an endpoint which signs arbitrary user or age assertions.
- The session query parameter is only a pointer. Match both approved owner and TEST checkout ID against the private ledger, require paid state, and use the existing fresh Stripe verification before returning the report. Return only no-store responses. Do not put bearer tokens or buyer data in the redirect, browser storage, or logs.
- The Stripe webhook stays on the existing isolated backend. Do not proxy raw signed deliveries through the buyer bridge or repoint a live endpoint.

## Before protected preview integration

Identify and test the existing trusted account issuer against the canonical NIJA user record, including revocation and adult eligibility. The backend and browser must share the exact protected preview origin; no wildcard CORS, public preview bypass, JWT signing secret in Vercel builds, or app-issued synthetic identities. Explicitly review how to route the two sandbox endpoints while retaining Vercel staging protection and keeping the TEST webhook unchanged. Hand off a completed canonical gameplay payload and CSRF through that trusted session, not through a score supplied by the browser.

## Acceptance before a real-payment proposal

Run a fresh authorized browser TEST with a genuine eligible test account, then reopen the correct report from another authenticated browser and deny anonymous, ineligible, revoked and wrong-owner access. Verify signed Stripe delivery, unpaid and canceled returns, refund and dispute revocation, duplicate delivery and restart persistence. The internal signed payment and refund rehearsal is good backend evidence but does not replace this customer-facing browser test.

A later production review must separately certify the live adapter, ledger, webhook, buyer issuer, shared rate limits, exact build/security checks, rollout and rollback. Do not flip the TEST bridge or legacy five-decision checkout into live operation.

## Reviewed SEO source drift

The standalone CI check failed against the old SEO pin before this preview work: all 56 inherited pinned files were checked individually, and only `src/lib/seo.js` differed. The pinned bytes match production commit `b582df3e`. The current source changes exactly one `/affiliate` metadata entry to remove the discontinued ClickBank 30% offer and state that course affiliate enrollment is unavailable. Preserve the corrected text. Update only the active standalone pin for those reviewed bytes; the original export manifest and all other source hashes and assertions remain unchanged. See [the failing check](https://github.com/dantelrharrell-debug/Nija/actions/runs/46069797514/job/140743741467).
