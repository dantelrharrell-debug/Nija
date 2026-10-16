# NIJA member brokerage dashboard integration contract

This document describes the **existing** isolated member credential API in `member_broker_http_api.py`. It does not authorize live trading or certify production readiness.

## Production release gates

- Deploy the isolated credential API with its own process entrypoint. Do not replace the trading bot's secret-mounted bootstrap, persistent disk, or database.
- Verify PocketBase `nija_broker_vault` create/list/view/update/delete ownership rules with two independent test accounts. Create must bind `user_id` to the authenticated user's ID.
- Verify the unique `(user_id, broker, environment)` constraint and that the schema accepts Kraken, Alpaca, Coinbase, and OKX.
- Verify a trusted, current Founding 100 entitlement against the authenticated member and Stripe, including trial access, without changing subscriptions.
- Preserve the existing `NIJA_BROKER_VAULT_KEY_B64` and ciphertexts. Do not generate a replacement key for an existing vault. Independently verify protected key custody, backup, and a successful decrypt of an approved synthetic record. Keep secrets in Render environment configuration, not the website or repository.
- Configure `NIJA_VAULT_ALLOWED_ORIGINS` to the actual published HTTPS member origin(s); verify request-origin policy and token handling.
- Leave `NIJA_VAULT_INTAKE_ENABLED=false` until independent security review and negative cross-account tests pass. Do not set verified flags based on configuration presence alone.
- Complete security scanning, CI, and human review before release.

## Implemented HTTP contract

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `/healthz` | Process liveness only; **not** permission to enable the form |
| GET | `/readyz` | 200 `{"status":"ready"}` only if configured readiness checks pass; otherwise 503 |
| GET | `/api/member/brokers` | Bearer-authenticated member-owned metadata; does not return ciphertext |
| POST | `/api/member/brokers/connect` | Bearer-authenticated JSON enrollment; never returns submitted secrets |
| POST | `/api/member/brokers/verify` | Bearer-authenticated stored Kraken verification; never accepts keys, owner IDs, or record IDs |

The GET/POST member routes require an allowed `Origin` and a PocketBase member Bearer token. The POST payload is exactly:

```json
{"broker":"kraken","environment":"live","credentials":{"api_key":"REDACTED","api_secret":"REDACTED"}}
```

Broker credential fields vary by provider and must be validated per broker before public release. Use dummy credentials only in tests. A successful POST means **credentials stored**, not **broker authenticated** or **trading authorized**.

Verification accepts exactly `{"broker":"kraken","environment":"live"}`. The server refresh-authenticates the
PocketBase member, checks verified identity and authoritative ledger plus current Stripe entitlement on **every**
request, loads owned records with that member's token, rejects duplicates/missing/mismatched records and incomplete
pagination, and decrypts with owner/broker/environment AES-GCM associated data. It calls only Kraken's private
`Balance` endpoint, discards balances, and returns:

```json
{"broker":"kraken","environment":"live","credentials_stored":true,"broker_verified":true,"membership_access":true,"trading_authorized":false}
```

`live` selects stored real-account credentials; it does not enable live trading. Paper verification and other brokers
are rejected. Verification is request-scoped, not persisted as durable authority; subsequent metadata requests
intentionally return `broker_verified:false`. No credentials, ciphertext, account balances, or provider errors
are returned. Provider rejection, rate limiting, timeout, or invalid JSON returns generic HTTP 502; authorization,
vault, or ownership failures return generic 403; missing/malformed bearer authentication returns 401.

## Dashboard requirements

1. After member sign-in, confirm the actual Founding 100 entitlement server-side.
2. Call `GET /readyz` and leave controls disabled on any non-200 response. Independently honor `credential_intake_enabled` for the key form and `verification_enabled` for stored-key verification. Do not interpret `/healthz` as readiness.
3. Display four brokerage choices (Kraken, Alpaca, Coinbase, OKX), plus paper/live selection where supported.
4. Use an authenticated HTTPS request to `POST /api/member/brokers/connect` only after security review. Never store tokens or keys in localStorage, sessionStorage, analytics, logs, URLs, or HTML attributes.
5. Refresh `GET /api/member/brokers` to display stored-credential metadata only; label exchange connection verification separately.
6. Do not publish an API-key entry form that uses unimplemented `/api/member/handoff`, `/connect/{broker}`, or `/api/member/brokers/status` routes. Those require separately reviewed implementation if a redirect flow is chosen.
7. `web/member/MemberBrokerKeyForm.jsx` now offers **Verify stored Kraken credentials** when authenticated owner metadata
   confirms a stored live Kraken record. It uses `web/member/memberBrokerApi.mjs`, passes only the current in-memory
   bearer token and scope, clears state on auth changes, and labels the result as authentication only. Include both
   files in the dashboard build. The external IONOS published dashboard/build pipeline is not in this repository;
   updating this component alone does not publish it. Use a non-persistent PocketBase auth store in the host dashboard.

## Deployment and independent evidence

1. Deploy only the standalone `member_broker_http_api:app` process with `requirements-member-broker.txt`
   (for example `gunicorn --bind 0.0.0.0:$PORT member_broker_http_api:app`). Do not alter trading startup.
   Allow outbound HTTPS to PocketBase, Stripe and `api.kraken.com` and read-only access to the billing ledger.
2. Preserve customers, subscriptions, owner IDs, vault records, encryption key, and existing broker connections.
   No migration, replacement, re-enrollment, or verification-state write is required.
3. Independently collect review evidence for PocketBase ownership rules and unique index, exact PocketBase-user
   to billing `nija_user_id` mapping, authoritative billing/Stripe reconciliation, and key custody/recovery.
   Only after those reviews set all four attestations to exactly `true`:
   `NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED`, `NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED`,
   `NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED`, `NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED`.
   Flags are attestations, not independent evidence. Do not set them merely to make a health check green.
4. Configure `NIJA_POCKETBASE_URL`, the **existing** `NIJA_BROKER_VAULT_KEY_B64`,
   `NIJA_VAULT_BILLING_READONLY_URL`, `NIJA_VAULT_STRIPE_READONLY_KEY`,
   `NIJA_VAULT_FOUNDING_PRICE_ID`, `NIJA_VAULT_FOUNDING_PRODUCT_ID`, and allowed dashboard origins.
   After approval set `NIJA_VAULT_VERIFICATION_ENABLED=true`, but keep `NIJA_VAULT_INTAKE_ENABLED=false`.
   Restart the API after configuration changes. New intake requires separate explicit approval.
5. `/readyz` returns 200 only with a constructed vault, billing configuration, all four review attestations,
   and at least one enabled capability. Verification-only readiness returns
   `{"status":"ready","credential_intake_enabled":false,"verification_enabled":true}`.
   It is a configuration/review-attestation check, not a real broker probe, a membership check, or independent proof.
   Unknown/missing prerequisites must remain 503. `/healthz` remains process liveness only.
6. Apply gateway per-member rate limits and request concurrency limits before public release. Do not retry private
   Kraken checks automatically; coordinate nonce usage with any other process using the same API key. Do not log
   request authorization/body, provider responses, or decrypt exceptions. Existing trader credentials must not be
   altered to resolve nonce failures.
7. Run the dedicated **Secure Member Broker HTTP Isolation Tests** workflow on the PR revision. Publish the reviewed
   component through the existing dashboard host, verify CORS from that origin, and perform a consented read-only
   acceptance check plus negative cross-member tests. Never submit a test order or change trading authorization.
8. Roll back by disabling verification/intake and restoring the prior isolated API/dashboard revision; leave keys,
   ciphertexts, subscriptions, and trading service untouched.

**Release status:** Repository tests use synthetic credentials and mock providers. They cannot verify production
PocketBase rules, identity mapping, billing reconciliation, or key custody. No production deployment or published
dashboard verification is certified by this change. Record reviewed evidence, deployed commit, legitimate `/readyz`
HTTP 200, and published-dashboard acceptance separately before declaring the production definition of done complete.

## Acceptance tests

- Unauthenticated, unverified, inactive-entitlement, invalid-origin, invalid-broker, malformed-payload and cross-member requests fail closed.
- Owner A cannot list, create, view, update or delete owner B's vault records, including by spoofing `user_id`.
- No plaintext keys appear in HTTP responses, application logs, analytics or browser persistence.
- Successful test enrollment survives a backend restart and returns metadata without secrets.
- A disabled readiness gate prevents form submission.
- The published IONOS member dashboard is tested with a test member before inviting Tania or other paying members.

**Operational note:** The production trading kill switch remains unchanged. Credential storage is not authorization to submit orders.
