# NIJA member broker vault integration (review required)

The isolated HTTP service uses root `member_broker_vault.py`, `member_broker_onboarding.py`,
`member_broker_http_api.py`, and `member_broker_kraken_readonly.py`. The legacy `bot/` adapters remain unchanged.
Neither path grants trading authority. See `NIJA_MEMBER_DASHBOARD_API_CONTRACT.md` for deployment gates and endpoints.

## Mandatory PocketBase rule change BEFORE enabling member writes

The supplied collection create rule only checks verified authentication and permits a member to *request* an arbitrary `user_id`. Update **create** in the actual PocketBase collection to:

```
@request.auth.id != "" && @request.auth.verified = true && @request.body.user_id = @request.auth.id
```

Keep list/view/update/delete owner-bound. Test cross-user create, read, update and deletion denial with actual member tokens. Verify server implementation accepts the exact PocketBase rule syntax. Do not expose the service AES key or decrypted secrets through PocketBase APIs or browser assets.

## Service setup

Set **only in the isolated trusted Python backend**:
- `NIJA_POCKETBASE_URL`: HTTPS host; the adapter appends `/.sfs-be/api/...`. Verify server routing on target deployment.
- `NIJA_BROKER_VAULT_KEY_B64`: existing protected 32-byte AES-256 key encoded as Base64. Do not replace it, commit it to GitHub, or print it. Secure backup and reviewed rotation plan required.

Inject `entitlement_check(user_id)` backed by the authoritative Founding 100 member-to-Stripe subscription mapping, with verified signature / protected server-to-server records, handling trialing, active, canceled, past_due and revoked statuses by business policy. Never take entitlement status from member input. Reject on timeout, stale cache or lookup failure.

The caller supplies a short-lived PocketBase member token. The module refresh-authenticates it with PocketBase,
checks verified identity + entitlement, then encrypts and stores an owner-bound ciphertext. Member passwords must
never pass through or be logged by the trading service. Intake remains disabled by default. `create()` rejects
duplicates through PocketBase's unique index; no overwrite or retry-on-conflict.

`retrieve_credentials()` is a server-only boundary: it rechecks identity and entitlement, loads only owner-filtered
records using that member token, validates returned ownership, uniqueness and pagination, and decrypts exactly one
matching scope. Only `MemberBrokerOnboarding.verify()` consumes this plaintext, invokes the Kraken read-only
authentication helper, and returns booleans/labels. There is no HTTP credential retrieval endpoint and verification
does not mutate any record. New verification and intake remain independently gated on all four security reviews.

## Optional Render configuration diagnostic

Run **NIJA member broker Render readiness diagnostic** from GitHub Actions
(`.github/workflows/member-broker-render-readiness.yml`) using **Run workflow**.
It is a manual, read-only configuration diagnostic, not a deployment or trading
authorization gate.

Configure `RENDER_API_KEY` under repository **Settings → Secrets and variables →
Actions → New repository secret**. Use a Render API key with the minimum available
permissions needed to read environment variables for `nija-member-broker-api`
(`srv-db84gj5g1s2s7390mrp0`). Restrict access to the intended service/workspace
where supported. Never put the key in workflow inputs, repository variables,
source files or logs.

- Without the secret, the diagnostic exits successfully with an explicit
  **SKIPPED** notice and job summary. This does **not** establish readiness.
- With the secret, it calls the Render service's environment-variable endpoint.
  API/authentication errors, unexpected responses and missing required variable
  names still fail the job. For HTTP 401/403, check the key's validity and access.
- It checks names only: `NIJA_POCKETBASE_URL`, `NIJA_BROKER_VAULT_KEY_B64`,
  `NIJA_VAULT_BILLING_READONLY_URL`, `NIJA_VAULT_STRIPE_READONLY_KEY`,
  `NIJA_VAULT_FOUNDING_PRICE_ID`, `NIJA_VAULT_FOUNDING_PRODUCT_ID`,
  `NIJA_VAULT_INTAKE_ENABLED`, `NIJA_VAULT_VERIFICATION_ENABLED`,
  `NIJA_MEMBER_BROKER_VAULT_RULES_VERIFIED`, `NIJA_MEMBER_BROKER_IDENTITY_MAPPING_VERIFIED`,
  `NIJA_MEMBER_BROKER_BILLING_ENTITLEMENT_VERIFIED` and `NIJA_MEMBER_BROKER_KEY_CUSTODY_VERIFIED`.
  It never prints their values.
- A passing diagnostic does not verify nonempty values, security flag truth,
  vault ACLs, entitlement or identity mapping. All mandatory reviews below still
  apply. After configuring the secret or fixing service configuration, start a
  new workflow run on the updated revision; retrying the old failed run uses its
  original workflow.

## Important limits

- The envelope is versioned, includes random 96-bit nonce and AES-GCM tag. Associated data is `{user_id}:{broker}:{environment}`; cross-account replay fails, but replay of a previous valid ciphertext under the *same* scope is not prevented. Add server-side immutable revision/rollback tracking before enabling replacements.
- Vault data encryption alone does not constitute a complete broker credential lifecycle: key rotation/recovery, audit logs without secrets, gateway rate limits, token lifetimes, revocation and published-dashboard acceptance still require review. No trading-service read/decrypt authority is introduced.
- Do NOT send a member's PocketBase bearer token to unrelated services, expose it to logs, or reuse it as standing trading authorization.
- Credentials must have minimum broker privileges; withdraw/transfer permissions disabled. No auto-trading activation.
- **Do not deploy or merge** until tests, owner-rule enforcement, security review, payment entitlement reconciliation and deployment routing are verified.
- Test locally with `NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -B -m unittest discover -s tests -p 'test_member_broker_verification.py'` in an isolated environment with `requirements-member-broker.txt`; no production imports or real credentials needed. CI also explicitly runs the existing vault/onboarding/HTTP tests and Kraken-helper pytest tests.
