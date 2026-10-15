# NIJA member brokerage dashboard integration contract

This document describes the **existing** isolated member credential API in `member_broker_http_api.py`. It does not authorize live trading or certify production readiness.

## Production release gates

- Deploy the isolated credential API with its own process entrypoint. Do not replace the trading bot's secret-mounted bootstrap, persistent disk, or database.
- Verify PocketBase `nija_broker_vault` create/list/view/update/delete ownership rules with two independent test accounts. Create must bind `user_id` to the authenticated user's ID.
- Verify the unique `(user_id, broker, environment)` constraint and that the schema accepts Kraken, Alpaca, Coinbase, and OKX.
- Verify a trusted, current Founding 100 entitlement against the authenticated member and Stripe, including trial access, without changing subscriptions.
- Set a server-generated 32-byte AES-GCM key encoded as Base64 in `NIJA_BROKER_VAULT_KEY_B64`. Keep secrets in Render environment configuration, not the website or repository.
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

The GET/POST member routes require an allowed `Origin` and a PocketBase member Bearer token. The POST payload is exactly:

```json
{"broker":"kraken","environment":"paper","credentials":{"api_key":"REDACTED","secret":"REDACTED"}}
```

Broker credential fields vary by provider and must be validated per broker before public release. Use dummy credentials only in tests. A successful POST means **credentials stored**, not **broker authenticated** or **trading authorized**.

## Dashboard requirements

1. After member sign-in, confirm the actual Founding 100 entitlement server-side.
2. Call `GET /readyz` and leave Connect controls disabled on any non-200 response. Do not interpret `/healthz` as readiness.
3. Display four brokerage choices (Kraken, Alpaca, Coinbase, OKX), plus paper/live selection where supported.
4. Use an authenticated HTTPS request to `POST /api/member/brokers/connect` only after security review. Never store tokens or keys in localStorage, sessionStorage, analytics, logs, URLs, or HTML attributes.
5. Refresh `GET /api/member/brokers` to display stored-credential metadata only; label exchange connection verification separately.
6. Do not publish an API-key entry form that uses unimplemented `/api/member/handoff`, `/connect/{broker}`, or `/api/member/brokers/status` routes. Those require separately reviewed implementation if a redirect flow is chosen.

## Acceptance tests

- Unauthenticated, unverified, inactive-entitlement, invalid-origin, invalid-broker, malformed-payload and cross-member requests fail closed.
- Owner A cannot list, create, view, update or delete owner B's vault records, including by spoofing `user_id`.
- No plaintext keys appear in HTTP responses, application logs, analytics or browser persistence.
- Successful test enrollment survives a backend restart and returns metadata without secrets.
- A disabled readiness gate prevents form submission.
- The published IONOS member dashboard is tested with a test member before inviting Tania or other paying members.

**Operational note:** The production trading kill switch remains unchanged. Credential storage is not authorization to submit orders.
