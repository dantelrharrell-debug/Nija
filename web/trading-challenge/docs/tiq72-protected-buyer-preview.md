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

The default-off private-session reader accepts only the exact `__Host-nija-tiq72-test`
opaque cookie. A separately reviewed host must mint it with Secure, HttpOnly, Path=/,
no Domain attribute, and appropriate same-site settings. Keep the random value
out of logs and deliver it only in the cookie. Resolve only its SHA-256 digest
through an access-controlled, bounded server-side lookup. Preserve explicit
revocation and expiry no greater than 15 minutes, protect the associated issuer
bearer at rest, and never return it to the browser. This code does not provision,
write, or mount a session store or mint and rotate cookies.

## Acceptance before a real-payment proposal

Run a fresh authorized browser TEST with a genuine eligible test account, then reopen the correct report from another authenticated browser and deny anonymous, ineligible, revoked and wrong-owner access. Verify signed Stripe delivery, unpaid and canceled returns, refund and dispute revocation, duplicate delivery and restart persistence. The internal signed payment and refund rehearsal is good backend evidence but does not replace this customer-facing browser test.

A later production review must separately certify the live adapter, ledger, webhook, buyer issuer, shared rate limits, exact build/security checks, rollout and rollback. Do not flip the TEST bridge or legacy five-decision checkout into live operation.

## Reviewed SEO source drift

The standalone CI check failed against the old SEO pin before this preview work: all 56 inherited pinned files were checked individually, and only `src/lib/seo.js` differed. The pinned bytes match production commit `b582df3e`. The current source changes exactly one `/affiliate` metadata entry to remove the discontinued ClickBank 30% offer and state that course affiliate enrollment is unavailable. Preserve the corrected text. Update only the active standalone pin for those reviewed bytes; the original export manifest and all other source hashes and assertions remain unchanged. See [the failing check](https://github.com/dantelrharrell-debug/Nija/actions/runs/46069797514/job/140743741467).

## Owner-operated adult eligibility (TEST only)

Dante selected manual owner review rather than a new verification vendor. The proposed adapter requires the exact designated reviewer’s active authenticated owner session and verified CSRF before appending a per-buyer decision. The buyer’s own active session must match the reviewed NIJA account. Decisions can expire or be revoked. No names, email addresses, document images, birth dates, or payment identifiers are accepted by the decision schema. Do not send those materials in chat. Review evidence only through a separately approved private method. For staging, use synthetic accounts and do not certify real buyers.

The separately reviewed TEST migration must not be appended to the existing four-table migration or run in production. Grant its runtime role only SELECT and INSERT. The new owner adapter is not a login service. Before use, bind the canonical private session authority and owner action UI, configure the preview rate limit and route, then run the browser test. Do not assume a checkbox or the owner’s general approval supplies an individual approval record.

## Canonical sign-in binding

The TEST composition reads an opaque, server-managed same-origin session and uses the existing NIJA `GET /api/user/profile` contract to revalidate the active actor. It verifies the returned opaque subject matches that private session, and the owner POST requires the configured test reviewer, exact origin and session CSRF. The profile adapter drops all other fields; the browser never receives a gateway access token from these routes. The staging host must not depend on a production gateway or customer database. The current connected Render inventory shows the internal Upgrade 6 rehearsal, the separate legacy IQ sandbox service and production/member/billing services, but no verified isolated canonical NIJA sign-in issuer. `nija-auth-staging.onrender.com` in the tests is a fixture, not a deployed service.

Before mounting: identify or explicitly provision the isolated NIJA sign-in issuer with synthetic users, pin its reviewed origin server-side, connect the same-origin private session store and reviewed limiter (including the owner review category), configure the test reviewer’s opaque subject, and apply the separate TEST review-table migration with least privileges under its deployment review. The operator signs in to approve or revoke each synthetic buyer. No live deployment or credential migration is implied by this wiring.

## Isolated issuer candidate

If no isolated NIJA issuer exists, the review-only factory `game_sandbox.tiq72_staging_identity:from_environment()` serves just the canonical login and profile paths using the existing Argon2 account database. It requires independent staging JWT and server-to-server bridge values and allows only synthetic `tiq-stage-…@example.invalid` accounts with matching staging-format subjects. Do not mount the general NIJA gateway, connect a production customer database, or expose registration. Provision only after approving the dedicated isolated service, persistent mount and cost. Use fresh private staging secrets, enforce ingress/rate limits, and bind a private same-origin browser session separately. Configure both `NIJA_USER_DB_PATH` and `NIJA_AUTH_USER_DB_PATH` to the identical mounted `/var/data/tiq72-auth/staging-only-users.sqlite3`; otherwise the existing provisioner can seed the wrong file. No actual accounts, service, secrets, routes or production settings were created or changed. Flask test-client verification used the actual NIJA Argon2 implementation and a disposable on-disk SQLite database, not a hosted issuer or browser sign-in.
