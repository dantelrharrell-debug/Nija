# NIJA authenticated collector: production integration acceptance

Target: Render `Nija_Trading_Bot`, service `srv-d98dsr5aeets73fpbaqg`, release branch `release/justcall-handoff-only-20261017`.

## Integration contract

The production composition root must obtain the actual broker-account registry from independently authenticated, read-only account discovery, not from environment readiness booleans or cached order evidence. Each account key must be `platform:<broker>` or `user:<member-id>:<broker>` with an actual verified identity. Member entitlement and credential custody must be checked separately; a disconnected/unpaid member is excluded.

For each verified account, provide all fields defined by `bot.pretrade_attestation_validation_v452.REQUIRED` as separately reviewed read-only callables. Map each field to a vetted `trusted_provider_ids` entry with source/authority separation. Provider observations must contain current authenticated account-bound evidence and pass v452 provenance validation; no dummy or self-attested providers.

At the trusted composition root, and **only after independent review** of actual providers and accounts, call `register_reviewed_account_registry(providers_by_account=..., trusted_provider_ids=..., independently_reviewed=True)` from `bot.pretrade_multi_account_registration_v474`. Do not invoke this from module import or from an unauthenticated web request. Installation is diagnostic-only and must not authorize orders.

## Release acceptance

1. Verify real broker permissions, account identity, balances and complete pagination, and independently reconcile the persistent ledger, opening records, intents, fills, open orders, and protective exits.
2. Verify independent writer lease, duplicate-order fence, nonce sequence, operator authorization, risk limits, kill switch and position sync. Complete off-host backup and isolated restore certification before mutating production trading state.
3. Verify collector status with a fresh scoped production readback: `collector_installed=true`, `account_scope_configured=true`, and independent certification ready for each authorized account. Never set these fields manually.
4. Only then allow the existing controller to reevaluate `execution_ready`, `execution_authority`, and `trading_engine_ready`. Do not place test orders, bypass kill switches, relax freshness, synthesize fills, or grant authority based on service liveness.
5. If any check fails, keep execution disabled and report the exact missing evidence, without secrets.

This document does not assert that the required provider implementations, production account bindings, or certifications currently exist. Deployment alone does not install the collector.
