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

## Post-3557 container startup repair

The shared `scripts/kraken_credential_aliases.sh` added by PR #3557 was omitted
from the Docker build context: `.dockerignore` excludes `scripts/*` and did not
re-include this new runtime dependency. A successful image build did not detect
the omission. Both production front doors source it under `set -e`.

An actual Docker-filtered Python 3.11 image reproduced exit code 1:

```text
scripts/render_entrypoint.sh: line 35: /app/scripts/kraken_credential_aliases.sh: No such file or directory
scripts/production_bootstrap.sh: line 14: /app/scripts/kraken_credential_aliases.sh: No such file or directory
```

This failure precedes the canonical Python launcher, native broker connection,
writer/nonce initialization, persistent recovery reads and collector installation.
The repair re-includes only this helper and adds production build-time presence
and Bash syntax checks. No credential selection, broker lifecycle, trading
strategy, order admission or safety guard is changed.

The container regression uses the real `.dockerignore`, Python 3.11, a non-root
user, synthetic credentials and `--network=none`. It runs each real shell front
door, the Render patcher chain and early `/healthz` server, stopping before
`start.sh` executes any Python trading runtime. It verifies restrictive runtime
authority and writer state at that boundary. This proves shell startup and
liveness, **not** full application startup, Kraken authentication or trading
readiness. Run it explicitly (Docker must already be available):

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -S -B -m unittest discover -s tests -p test_render_container_startup.py -v
```

Authenticated Render deployment events/logs remain required to establish the
exact cause of `dep-dbjuc015efls73ef48g0`. In this repair session the Render API
hostname did not resolve and no Render API credential was available. GitHub's
Render integration associates that deployment with commit
`851d41ad289edd7cb18e0c9f6ee3aae8db2b971f`, whereas the supplied failed release
commit is `41b3e91691a59ace61d1591c9032ad127d3f6f58`. Resolve that discrepancy
against authenticated Render metadata before attributing the reproduced failure
to that specific deployment. Do not treat old live-instance logs as new-release
evidence.

Collector installation remains blocked independently of this packaging repair.
The v490 six-source contract and v491 thirteen-source bridge validate wiring;
neither supplies authoritative sources or registers at production startup.
There is no production caller with a complete reviewed registry. Required
dependencies remain: an account-bound reconciled ledger snapshot, a current
writer-owned duplicate-order fence, independently approved operator authority,
durable kill-switch clearance, current risk-governor limits, and a complete
authenticated position-sync observation. Approved account/key pins, vetted
provider identities and backup/restore plus broker/ledger/protection
certification are also required before invoking the existing v474 registration
boundary. No automatic provider, approval flag or fabricated observation is
added. All thirteen checks and `READ_ONLY_RECOVERY allow_new_orders=false`
must remain blocking until genuine account-specific evidence is available.
