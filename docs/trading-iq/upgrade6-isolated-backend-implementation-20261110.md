# NIJA Trading IQ Upgrade 6 — isolated backend implementation (DRAFT / HOLD)

**Scope:** Github-only test-mode backend module and synthetic tests. No IONOS, Render, Vercel, DNS, production billing, or live trading changes. These source modules are **not imported** by the existing public game or by the Render holding server.

## Source of truth and outstanding evidence

- IONOS project `aibuilder-4dfdf`, reported canonical reference v515 (`4a64f74c`).
- Reported contract in IONOS project save `3092fe6f`: `docs/upgrade6-backend-contract.md`. **Actual file unavailable in GitHub at drafting time**; nine-endpoint names and error-code contract are not certified here.
- Reported archive `nija-trading-iq-4227f20c.zip`, SHA-256 `26a76be9eea78dd21778db12d04e45b54b5931f2a981645c875d0c3ffda72fa9`. **Archive bytes not inspected** and cannot be treated as source parity evidence.
- Reported game asset `TradingIQChallenge-BY_PDlEm.js`, SHA-256 `7f4e0133cb3ff361954b10dca342b829c45c53b956f87cb94b07207ad19f2bae`, not independently retrieved or compared to rebuilt `3092fe6f` output.
- Existing server-owned `tiq12-contract.mjs` accepts a private approved manifest; it is **not** the actual canonical scoring manifest.
- The existing `tiq12-storage.schema.sql` is a review-only migration, not an installed private provider database.

## Concrete code implemented

- `server/tiq12-upgrade6-security.mjs`: strict test-mode-only configuration, exact HTTPS origin, cryptographic owner proofs, fixed server-price checkout identity, raw-body Stripe HMAC signature verification, and timestamp expiration.
- `server/tiq12-upgrade6-store.mjs`: isolated SQLite adapter built on existing schema, one durable reservation/idempotency key per adult run, immutable event journal, atomic payment/grant transition, sticky reversal, private entitlement read. Initialization is explicit and must not be used on existing customer databases.
- `server/tiq12-upgrade6-stripe.mjs`: test-only Stripe REST adapter with product/price verification, Checkout create with stored idempotency key, authoritative session/line item retrieval and charge-to-session reversal resolution.
- `server/tiq12-upgrade6-service.mjs`: service orchestration for optional adult run completion, checkout reservation, authenticated signed webhook reconciliation, refund/dispute revocation, and purchased report access guarded by fresh Stripe state.

**Unwired by design:** No HTTP router, frontend connection, hosted credential, webhook registration, domain, database provisioning, or deployment changes. These methods are not customer-callable in production. No real test Checkout was created.

## Synthetic regression checks

Run using Node 22+ from `web/trading-challenge`:

```sh
node --test tests/tiq12-upgrade6-*.test.mjs
node --test tests/tiq12-contract.test.mjs
python3 -m unittest discover -s tests -p test_tiq12_storage.py
```

Tests exercise invalid live keys, improper origins, test-mode signature tampering/expiry, duplicate session prevention, owner mismatch, simulated payment-to-entitlement, stale refund/dispute behavior, and schema integrity using **fictional in-memory test records and fake Stripe responses only**. They do not establish browser parity, canonical scoring equivalence, a live Stripe sandbox purchase, or a hosting approval.

## Additional engineering required before any test-mode integration

1. Independently obtain and hash-verify the exact IONOS contract and game export; reconcile the **actual nine endpoints**, errors, approved design and 12 authoritative rounds. Run all 12 exact IONOS acceptance tests, including **200 seeded canonical scoring comparisons**. Do not substitute synthetic manifests.
2. Build the separately reviewable HTTP API router with strict raw-body webhook handling, header ownership authentication, CORS/preflight, CSRF controls, body-size and rate limits, no-store/private headers, transaction boundaries and audited admin access.
3. Review backend architecture: the current Node `node:sqlite` adapter uses Node 22 experimental APIs. Verify runtime support, single-writer strategy, managed durable storage, backup/restore and migration/rollback procedures before infrastructure approval.
4. Reconcile behavior for Stripe partial refunds, asynchronous pending/failure, receipt recovery, delayed/lost Checkout responses, and outage recoveries. Verify no repeat Checkout if reconciliation cannot finish.
5. Verify dedicated Render service eligibility and budget; current holding Blueprint `exs-dbp50cmgekts73e81v00` has no resources and `autoSync=false`. **Do not sync it or replace the holding service.**
6. After separate infrastructure approval, configure `sk_test_…` and a distinct `whsec_…` only via protected provider secrets. Verify presence/validity without exposing values. Never use live keys.
7. Run hosted test-mode Checkout → signed webhook → reopen report → refund/dispute end-to-end acceptance, security scan and mobile/browser QA. Obtain business/legal age, privacy, digital-goods terms and retention approvals.
8. Obtain separate owner approvals for the isolated staging deployment, IONOS frontend connection and **test-only** payment activation. Live payment activation requires another explicit decision.

## Mandatory release status

**ENGINEERING IN PROGRESS / NO-GO.** A passing local synthetic test does not mean 12 contract acceptance tests passed, nor that IONOS preview access, production migration, Stripe credential installation or hosted checkout is verified. Preserve the public game and the $1 "Coming Soon" state. Never activate new trading orders.
