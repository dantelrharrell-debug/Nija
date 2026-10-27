# NIJA v478 — independent Kraken account identity evidence (review only)

This provider supplies **only** v452's `account_identity` field. It reads Kraken's `GetApiKeyInfo` using the *existing* nonce-owning Kraken client and its approved monitoring category. Its verified output requires **two independently reviewed, exact SHA-256 pins**: the API key's public identifier and the Kraken account IIBAN (`SHA256(b"kraken\\x00" + uppercased IIBAN as UTF-8)` with an actual NUL separator, matching `read_startup_broker_identity`). Pins must come from independent operator approval, not environment readiness flags, a broker response being validated, a same-process self-report, or historical data. Credentials and IIBAN are never included in the output or denial messages.

Kraken documents `GetApiKeyInfo` as returning `apiKey` and `iban`. The IIBAN pins the authenticated **account identity** but does not prove legal/beneficial ownership, company ownership, paid member entitlement, trade/ledger reconciliation, or authorization to place orders. The older v477 key-permission producer remains separate. Both are candidates for the actual reviewed `providers_by_account` registry; neither self-registers. The other twelve v452 fields remain mandatory. The provider must not be called unless an authorized production reviewer independently establishes the API key and IIBAN pins and exact account scope.

## Acceptance / safety

- Same exact broker software scope before and after the private read; connected existing client and canonical monitoring category, no new nonce owner.
- Read-only `GetApiKeyInfo` only. No `AddOrder`, cancel, ledger writes, credential changes, new deployments, or fresh-fill assertions.
- Account and key hashes checked in constant time; deny missing/mismatched pins and IIBAN, API errors, slow responses (>60s), account switches, and invalid scopes.
- Evidence timestamps use the **start** of I/O; v452 validates after I/O and still requires all 13 independent fields with source separation and <=60 seconds observation age.
- CI tests cover missing pins, account/user isolation, account switch, redaction, stale reads, and partial-certificate denial. Never treat this PR as installation or live readiness.

Source: https://docs.kraken.com/api/docs/rest-api/get-api-key-info .

This is a reviewed-code candidate, **not** an authenticated production certification. `collector_installed` and `account_scope_configured` remain dependent on independently reviewed production bindings. Existing execution and posttrade proof gates are unchanged.
