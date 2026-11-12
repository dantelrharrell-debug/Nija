# Narrow synthetic test-fixture secret review — 2026-11-12

## Source and scope

Reviewed release: `ef2aa3f7137d5ca2488234083fd096d651061f6e`.
Exact push security workflow: [43206538256](https://github.com/dantelrharrell-debug/Nija/actions/runs/43206538256).
The retained secret-scan report, artifact `13938007242`, identifies that same
checked-out commit and contains 203 unreviewed candidates. Downloaded ZIP SHA-256:
`d0c8fe6816d5fa890e0de357605b89f80ab7a94e1c99fe93e0a89150acf320ac`.

This change classifies 35 Secret Keyword findings in 23 Python test files as
synthetic fixture literals. Each finding was matched to the pinned detector's
exact value and an exact Python AST string constant at the recorded line, in
test/fixture context. Embedded strings without an exact matching constant were
left unreviewed. Production code, documentation examples, private-key markers,
URLs and entropy findings are outside this exception set.

The values are deliberately short dummy/test labels used by the tests, not
verified exchange credentials or production configuration. No raw values or
credential-derived production fingerprints are recorded in this document or
the review manifest. The manifest contains source coordinates and test contexts.

## Enforcement remains active

The baseline adds only the existing detector's filename/type/value-hash identity
for each reviewed finding, with its false-positive audit flag. Existing entries,
scanner filters, plugins, versions and generation metadata are unchanged. There
are no wildcard path exceptions, detector exclusions or inline ignores. A new
value at a reviewed location has a different identity and remains blocking.

Three new tests invoke the real pinned pre-commit detector: they verify the
manifest scope, accept an unchanged reviewed fixture, and reject a replacement
value at that same source location. Test repositories and values are isolated
synthetic data. No provider verification or live credential use is performed.

A targeted rescan of the affected files contains 45 unbaselined identities
before this patch and 10 afterward: exactly these 35 identities are removed.
The complete repository scan has not been certified clean. The expected
remaining total is 168 relative to the 203-candidate source report; a fresh
hosted full scan must establish its actual result on the new integration tree.
No remaining finding is approved or suppressed by this review.

## Validation

- 92 reporting/enforcement tests passed locally, including the changed-value
  negative control using detect-secrets 1.5.0.
- Baseline semantic comparison proves exactly 35 identities added, none removed,
  and all previous entries, filters and plugin settings unchanged.
- Existing test/production source files are unchanged; only baseline metadata,
  review records, regression tests and CI test coverage are modified.
- Independent human review and exact-release security checks remain required.
- This does not rotate any credential, certify trading evidence, install the
  Kraken collector, approve deployment or authorize an order.

## Reviewed coordinates

| File | Line | Test/fixture context |
|---|---:|---|
| `bot/tests/test_alpaca_atomic_protected_entry.py` | 115 | `_broker` |
| `bot/tests/test_broker_auth_recovery_patch.py` | 89 | `test_okx_accepts_passphrase_alias_and_global_region` |
| `bot/tests/test_broker_auth_recovery_patch.py` | 90 | `test_okx_accepts_passphrase_alias_and_global_region` |
| `bot/tests/test_capital_refresh_and_kraken_recovery_v35.py` | 365 | `setUp` |
| `bot/tests/test_capital_refresh_and_kraken_recovery_v35.py` | 366 | `setUp` |
| `bot/tests/test_entrypoint_writer_authority.py` | 54 | `setUp` |
| `bot/tests/test_funded_okx_capital_convergence_v31.py` | 80 | `test_secondary_activation_prefers_authenticated_okx_over_zero_router` |
| `bot/tests/test_funded_okx_capital_convergence_v31.py` | 81 | `test_secondary_activation_prefers_authenticated_okx_over_zero_router` |
| `bot/tests/test_kraken_adapter_connection.py` | 50 | `_configured_adapter` |
| `bot/tests/test_secondary_venue_activation_patch.py` | 109 | `test_coinbase_credential_aliases_are_promoted` |
| `bot/tests/test_secondary_venue_activation_patch.py` | 110 | `test_coinbase_credential_aliases_are_promoted` |
| `bot/tests/test_startup_verification_evidence.py` | 51 | `__init__` |
| `bot/tests/test_writer_authority_lease_invariant.py` | 99 | `setUp` |
| `bot/tests/test_writer_authority_lifecycle_fix.py` | 196 | `setUp` |
| `bot/tests/test_writer_core_thread_lease_regression.py` | 102 | `setUp` |
| `bot/tests/test_writer_generation_tracker.py` | 233 | `test_succeeds_when_manager_returns_valid_version` |
| `bot/tests/test_writer_lease_lifecycle.py` | 101 | `setUp` |
| `test_go_live.py` | 203 | `test_kraken_credentials_check` |
| `test_go_live.py` | 204 | `test_kraken_credentials_check` |
| `test_platform_account_safety.py` | 711 | `test_alpaca_hierarchy_validation` |
| `test_platform_account_safety.py` | 724 | `test_alpaca_hierarchy_validation` |
| `test_platform_account_safety.py` | 725 | `test_alpaca_hierarchy_validation` |
| `test_user_independent_trading.py` | 222 | `test_load_individual_user_config_with_independent_trading` |
| `test_user_independent_trading.py` | 223 | `test_load_individual_user_config_with_independent_trading` |
| `tests/test_conversion_delivery.py` | 22 | `kwargs_for` |
| `tests/test_conversion_delivery.py` | 51 | `test_rejects_invalid_attribution_and_event` |
| `tests/test_conversion_outbox.py` | 161 | `test_invalid_attribution_does_not_claim_pending_conversion` |
| `tests/test_founding_onboarding_api.py` | 22 | `setUp` |
| `tests/test_founding_onboarding_api.py` | 27 | `setUp` |
| `tests/test_founding_onboarding_api.py` | 32 | `setUp` |
| `tests/test_member_broker_onboarding.py` | 29 | `test_secure_connection_does_not_return_keys` |
| `tests/test_member_broker_onboarding_api.py` | 40 | `test_rejects_unauthorized_and_never_returns_secrets` |
| `tests/test_member_broker_verification.py` | 26 | `setUp` |
| `tests/test_paid_user_live_trading_access.py` | 90 | `setUp` |
| `tests/test_paid_user_live_trading_access.py` | 91 | `setUp` |
