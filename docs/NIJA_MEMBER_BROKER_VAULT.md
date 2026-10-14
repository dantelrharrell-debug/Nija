# NIJA member broker vault integration (review required)

Isolated implementation: `bot/member_broker_vault.py`. It does not import the NIJA trading runtime, submit orders or modify trading authorization.

## Mandatory PocketBase rule change BEFORE enabling member writes

The supplied collection create rule only checks verified authentication and permits a member to *request* an arbitrary `user_id`. Update **create** in the actual PocketBase collection to:

```
@request.auth.id != "" && @request.auth.verified = true && @request.body.user_id = @request.auth.id
```

Keep list/view/update/delete owner-bound. Test cross-user create, read, update and deletion denial with actual member tokens. Verify server implementation accepts the exact PocketBase rule syntax. Do not expose the service AES key or decrypted secrets through PocketBase APIs or browser assets.

## Service setup

Set **only in the isolated trusted Python backend**:
- `NIJA_POCKETBASE_URL`: HTTPS host; the adapter appends `/.sfs-be/api/...`. Verify server routing on target deployment.
- `NIJA_BROKER_VAULT_KEY_B64`: KMS-protected random 32-byte AES-256 key encoded as Base64. Do not commit to GitHub or print. Secure backup and rotation plan required.

Inject `entitlement_check(user_id)` backed by the authoritative Founding 100 member-to-Stripe subscription mapping, with verified signature / protected server-to-server records, handling trialing, active, canceled, past_due and revoked statuses by business policy. Never take entitlement status from member input. Reject on timeout, stale cache or lookup failure.

The caller supplies a short-lived PocketBase member token. The module refresh-authenticates it with PocketBase, checks verified identity + entitlement, then encrypts and stores an owner-bound ciphertext. Member passwords must never pass through or be logged by the trading service. No browser endpoint or automatic credential enrollment is introduced by this branch. `create()` rejects duplicates through PocketBase's unique index; no overwrite or retry-on-conflict.

## Important limits

- The envelope is versioned, includes random 96-bit nonce and AES-GCM tag. Associated data is `{user_id}:{broker}:{environment}`; cross-account replay fails, but replay of a previous valid ciphertext under the *same* scope is not prevented. Add server-side immutable revision/rollback tracking before enabling replacements.
- Vault data encryption alone does not constitute a complete broker credential lifecycle: key rotation/recovery, audit logs without secrets, rate limits, token lifetimes, managed read/decrypt for trading service identities, revocation and safe dashboard wiring still require review.
- Do NOT send a member's PocketBase bearer token to unrelated services, expose it to logs, or reuse it as standing trading authorization.
- Credentials must have minimum broker privileges; withdraw/transfer permissions disabled. No auto-trading activation.
- **Do not deploy or merge** until tests, owner-rule enforcement, security review, payment entitlement reconciliation and deployment routing are verified.
- Test locally with `python -S -B -m unittest tests.test_member_broker_vault` in an isolated environment; no production imports or real credentials needed.
