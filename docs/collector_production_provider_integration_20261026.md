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

## November 2 native startup repair and remaining blockers

The inspected release head is `7a494965d42a549fb287c8cc8e5b90a600220853`.
Its Render path is `scripts/render_entrypoint.sh` →
`scripts/production_bootstrap.sh` → `start.sh` →
`scripts/canonical_runtime_launcher_v26.py` → `main.py` → `bot.bot` → `bot.bot_main`.
The writer-first prebootstrap initializes the canonical
`MultiAccountBrokerManager`; `initialize_platform_brokers()` constructs
`bot.broker_manager.KrakenBroker`, **not** `KrakenBrokerAdapter`.
The earlier adapter connection-state repair therefore did not repair this
native handshake.

Both shell front doors previously promoted keys and secrets separately, and
the native broker independently fell back between namespaces for each value.
A partial platform pair could consequently be combined with a legacy secret
from another account. Shared pair normalization now preserves complete alias
pairs, leaves partial canonical configuration rejected, and never prints values.
Native platform and user loaders likewise select one namespace, validate secret
encoding, and never borrow another namespace's missing credential.

Native handshakes are serialized per broker. The client is not published on
`broker.api` until canonical writer proof and per-key nonce binding succeed.
Failed initialization discards the
client, wrapper and nonce dispatch bindings, invalidates balance freshness,
closes the old session, and revokes the platform startup latch. A reconnect
must complete a new authenticated Balance probe. Successful construction alone,
public market reads and old connectivity latches are not authentication.
`KRAKEN_INITIALIZATION_BLOCKED` reports the failed stage (credentials, clock,
client creation, writer authority, nonce ownership, authenticated balance or
balance hydration) and a fixed diagnostic reason. Writer evidence also rejects
an API-client replacement during its read.

**These are verified code defects, not a verified explanation of the November 1
production authentication failure.** Fresh startup logs and an authenticated
Render interface are required to identify that deployment's failing transition.
The known public health hostname did not resolve from the repair environment;
no Render/Kraken/Redis credentials were available locally.

Collector construction and registration remain explicit trusted-root operations,
with no production caller supplying the required registry. Six source bindings
are still required: `position_ledger_reconciliation`, `duplicate_order_fence`,
`operator_authorization`, `kill_switch_clear`, `risk_limits`, and `position_sync`.
The other seven provider factories do not constitute a complete certification.
The November 1 read-only recovery workflow also reported
`exchange_protective_order_id_mapping_missing` and
`pending_kraken_closes_require_reconciliation`; these historical observations
must be rechecked, not assumed repaired. No synthetic callbacks, environment
approval switches or automatic collector installation have been added.

Registration continues to validate all 13 observations before replacing the
collector. Rejections now identify canonical failed field names in
`PRETRADE_COLLECTOR_INSTALL_REJECTED`; subsequent rejected observations report
`producer_status=independent_evidence_rejected` and `failed_fields`, with every
admission check denied. Provider exceptions and account payloads are not exposed.
Reinstallations must supply the entire reviewed platform/member registry to
preserve account separation.

### Post-approval verification

Do not merge or deploy until required CI, secret and CodeQL checks pass and a
human reviews the broker/startup changes. After approval, verify the deployed
SHA and fresh native-stage logs using the authenticated Render interface. Check
paired credential configuration by presence only. In the actual writer process,
verify the existing nonce-owning client against independently approved key and
account fingerprints using GetApiKeyInfo and the reviewed permission/identity
providers. An authenticated Balance read alone does not prove all permissions.

Obtain independently reviewed implementations of all six missing source
bindings, complete ledger/open-order/protective-exit reconciliation, and obtain
backup/restore and broker/ledger/exit certification. Compose the existing
providers with that exact canonical broker, approved pins and complete vetted
provider IDs. Register all authorized account scopes atomically through v474.
Verify fresh account-bound observations for every field, collector installation,
writer fence/generation/TTL, nonce ownership, legitimate kill-switch clearance
and risk limits. On a disconnected or rotated client, revalidate bindings and
all observations before considering readiness again.

Finally inspect existing execution admission and current genuine order/fill
evidence. Collector certification remains diagnostic-only: existing execution
proof and authority gates are unchanged. No live test order is authorized by
this procedure.
