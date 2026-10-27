# v480 — independently pinned Kraken account identity producer

This patch contributes **one** source-specific, read-only producer for v452 `account_identity`. It does **not** register or install the collector; it does **not** authorize orders.

From the already-running nonce-owning broker, `make_kraken_account_identity_provider` makes **one** authenticated `GetApiKeyInfo` read using the existing monitoring category. Its account IIBAN fingerprint uses NIJA's canonical `sha256("kraken\\0" + uppercase_iban)` formula from `bot/startup_verification_evidence.py`; the public API-key ID is fingerprinted with SHA-256 as in v477. Both expected hashes **must originate in a separately approved account/key inventory**. Never derive them from the first response. Only a fixed-field v452 observation is returned; no IIBAN, key, broker rows, credentials or response error text are logged or returned.

Checks: exact canonical `platform:kraken` / `user:<id>:kraken` account scope, unique existing connected broker, pre/post read routing, valid approved pins and provider ID, successful authenticated schema, both pin matches, key not expired, maximum 60s observation, and strictly read-only call. An account IIBAN is not by itself legal ownership evidence or an entitlement check; these require independent review.

**Remaining:** independently certify account permissions through v477, broker balances, all history pagination, opening records/intents, complete fill/fee/lot reconciliation, broker-confirmed protective exits, duplicate fence, writer lease, nonce, kill switch, risk and operator approval; off-host backup and isolated restore; independently reviewed two-phase canonical controller admission. Do not enable live trading or member vault intake from this patch. Neither billing nor PocketBase identity can be inferred from this Kraken account check.

Review branch only. Run `python -m pytest -q tests/test_kraken_authenticated_identity_v480.py` with runtime startup hooks deferred. Hosted recovery CI must pass before merging. No production live API calls, credentials, or writes were performed while preparing this change.

Kraken reference: https://docs.kraken.com/api-reference/account-data/get-api-key-info
