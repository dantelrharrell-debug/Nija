# Kraken production recovery evidence - 2026-11-02

## Outcome and scope

Production is **not independently certified**. This change improves denial
diagnostics and safe investigation; it does not supply missing authorities,
install a collector, enable orders, merge, or deploy.

The inspected Render service is `srv-d98dsr5aeets73fpbaqg`, live deployment
`dep-dbk18d6417fc73bf4alg`, commit
`cd174134ff4a61824322cecc042d1548bd938a34`. The canonical process remained on
instance `srv-d98dsr5aeets73fpbaqg-7d458c8976-zsc58` throughout inspection.
No Docker/startup repair was repeated.

## Authenticated current-instance evidence

Actions run `41393718060` used the existing dedicated SSH credential, pinned
Render SSH host fingerprint and authorized Render API credential. The helper
ran from stdin with `python -B -S`; it did not import NIJA or construct a broker.
Only fixed labels, public deployment/source identifiers and presence booleans
were returned. No keys, account identifiers, API payloads or raw log messages
were exported.

The Render API reports the instance label as
`srv-d98dsr5aeets73fpbaqg-zsc58`. The inspector matches that exact current-instance
label, not arbitrary suffix matches or logs from overlapping deployments.
The full environment instance ID is not a valid server-side log filter.

Current-instance log counts at 05:27 UTC:

| Fixed diagnostic | Count | Interpretation |
|---|---:|---|
| PLATFORM_AUTHENTICATED_BALANCE_SUCCEEDED | 5 | Native success branch requires `error == []` and a dictionary Balance result. |
| AUTHENTICATED_RECOVERY_SUCCEEDED | 1 | Existing platform recovery reported success; not independent certification. |
| CLOCK_GATE_VERIFIED | 1 | Startup clock gate passed. |
| CUSTOMER_CREDENTIALS_MISSING | 14 | Customer-namespace credential configuration failures, not platform-key failures. |
| MISSING_CUSTOMER_NAMESPACE | 14 | Confirms the namespace of those missing pairs. Counts are events, not accounts. |
| COLLECTOR_MISSING | 100 | Bounded log result; not a complete event count. Collector remains absent. |
| PRICE_CLIENT_DISCONNECTED | 100 | Missing `self.api` in a price caller; legacy message does not identify its account. |

Canonical platform key/secret and Redis variables are present; legacy platform
aliases are absent. Presence alone proves neither authentication nor approval.
Source inspection follows the Render entrypoint, bootstrap, `start.sh`,
canonical launcher, `main.py`, `bot.bot`, `bot.bot_main`, account manager and
native `KrakenBroker` lifecycle. Connection serialization, credential-pair
selection, writer checks, nonce binding and failed-client cleanup already exist.
They were not replaced.

**Root-cause boundary:** missing customer credential pairs explain the scoped
customer initialization failures. Platform Balance authentication succeeded in
this running process. Existing generic price logs cannot establish whether the
disconnected object is a customer broker or an obsolete platform reference.
The new price diagnostic adds fixed account-role and lifecycle-stage labels,
without changing fetching behavior or exposing account material. It is not yet
deployed. No invalid-signature, invalid-key or nonce diagnosis is inferred from
the generic price message.

### Single-use authenticated identity request

The user-authorized read-only probe published one request,
`85c2521edd9754d6f6f7df677f8d6231`, into the existing private recovery directory.
The pinned existing v491 consumer claimed it and used the already-connected
platform broker's serialized private-call path for `GetApiKeyInfo`.
No second client, nonce owner, writer lease or approval record was created.

The request was published at 05:23:37 UTC, was observed claimed at 05:23:56,
and produced a denied receipt by 05:27:04:

```text
status=IDENTITY_RECEIPT
reason=observation_clock_invalid_or_stale
configured_account_key_match=false
independent_certification_complete=false
```

The existing provider rejects reads exceeding 60 seconds before accepting
response identity. This is a timing/freshness refusal, **not proof that pins
mismatch or Kraken rejected authentication**. Queue, lock, network and
transport contributions are not separately measured, so no finer cause is
claimed. The request and receipt remain immutable; no replay or freshness
relaxation occurred. Rerunning the workflow only reads that receipt.

Permissions, restrictions, approved account/key identity and current balances,
orders and ledgers therefore remain uncertified. The saved binding is
comparison input, not independently established operator approval.

### Local ledger inspection

Authenticated release-branch recovery run `41391845949` confirmed:

```text
sqlite_integrity_ok=true
exchange_protective_order_id_mapping_missing
pending_kraken_closes_require_reconciliation
```

That workflow subsequently failed its obsolete history-source digest pin.
This is a diagnostic-workflow prerequisite failure, not exchange authentication.
No historical recovery request was replayed and no ledger row was changed.

## Six missing authoritative integrations

The existing v487-v491 modules validate supplied providers; they do not
manufacture production authorities. The following bindings cannot safely be
installed from the interfaces currently available:

| Required provider | Concrete remaining prerequisite |
|---|---|
| Ledger reconciliation | Broker-scoped exchange/ledger provenance, complete fee/partial-fill reconciliation, protective-order identifiers and resolved pending closes. Core ledger position rows lack broker scope. |
| Duplicate-order fence | Install the real transactional admission/intent system across every live dispatch path under canonical writer fencing. `account_order_admission.py` explicitly is not installed; table existence is insufficient. |
| Operator authorization | An independently approved, authenticated account-scoped approval producer. Configuration flags and saved comparison pins are insufficient. |
| Kill-switch clearance | Durable readback distinguishing verified clearance from absent, unreadable or malformed state, with account and writer provenance. `_read_durable_stop()` currently conflates these as `None`. Never clear an active stop. |
| Risk limits | An authoritative account-scoped exposure/drawdown/order snapshot with timestamp and writer provenance. Global `get_status()` alone cannot certify this. |
| Position synchronization | Fresh authenticated account positions, orders, pending closes and exchange-confirmed protection reconciled with independently scoped internal lots. |

No partial registry was installed. All thirteen fields remain denied when the
collector is missing. The implemented reason propagation distinguishes missing
or failed readers, scope/source/provider conflicts, incomplete snapshots or
pagination, stale/future clocks and reused evidence identities. Rejection of a
collection does not convert other fields into successful evidence.

## Changes and safety properties

Changed runtime surfaces are limited to certificate-denial reasons and
role-scoped missing-price-client logging. Acceptance conditions and all order,
risk, stop, writer, nonce, capital and execution-proof gates remain intact.
No strategy, sizing, entry/exit, stop-loss or trailing logic changed; a strategy
backtest is not applicable.

The diagnostic workflow optionally publishes exactly one private identity
request under the existing collector lock. It refuses changed service/commit,
consumer source hashes, unsafe paths/permissions, competing request modes and
replay. Default inspection and receipt reads do not write state.
The diagnostic `allow_new_orders=false` output is not a mutation of live
admission; it cannot grant trading authority.

Nonce coverage executes the actual production Redis Lua on an isolated Unix
socket: 1,000 concurrent threaded calls, 400 calls from four independent
processes, persisted high-water continuity, replacement backend objects,
writer handoff and stale/absent ownership. A future synthetic high-water
requires exact contiguous increments even when wall-clock time is behind it.
No production Redis state is reset or accessed.

An initially failing existing nonce-handoff test mocked the obsolete startup
authority function. Its four handoff/denial fixtures now mock the actual
`assert_distributed_writer_authority` boundary. Assertions and runtime guards
are preserved; the previously failing handoff and negative ownership tests now
exercise the intended canonical authority path.

## Validation commands and results

The commands below used an isolated **Python 3.11.16** environment, not the
host's Python 3.12. Dependencies came from existing project/CI test pins.
All fixtures are synthetic and local; no order endpoint was called.

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -m pytest -q \
  tests/test_kraken_native_runtime_connection.py \
  tests/test_kraken_instance_diagnostic.py \
  tests/test_kraken_nonce_redis_concurrency.py \
  tests/test_pretrade_failure_reasons.py \
  tests/test_pretrade_multi_account_registration_v474.py \
  tests/test_pretrade_composition_bridge_v465.py \
  tests/test_execution_admission_acceptance_v468.py \
  tests/test_kraken_authenticated_key_info_v477.py \
  tests/test_kraken_authenticated_identity_v480.py \
  tests/test_kraken_authenticated_balance_provider.py \
  tests/test_kraken_authenticated_open_order_integration_v482.py \
  tests/test_kraken_protective_exit_readback_v485.py \
  tests/test_kraken_writer_nonce_evidence_v488.py \
  tests/test_kraken_collector_composition_v487.py \
  tests/test_kraken_sqlite_readonly_preflight_v488.py \
  tests/test_kraken_authenticated_ledger_gap_audit_v489.py \
  tests/test_kraken_six_source_binding_contract_v490.py \
  tests/test_kraken_thirteen_source_reviewed_bridge_v491.py \
  tests/test_kill_switch_redis_durability.py \
  tests/test_preactivation_preflight_observability_v450.py \
  bot/tests/test_distributed_nonce_manager_authority.py \
  bot/tests/test_kraken_writer_authority_gate_v91.py \
  bot/tests/test_render_entrypoint_launcher_v26.py \
  bot/tests/test_render_canonical_startup_v24.py --tb=short
```

Result: **317 passed**.

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 python -S -m py_compile \
  $(git diff --name-only cd174134ff4a61824322cecc042d1548bd938a34 -- '*.py')
git diff --check
git diff cd174134ff4a61824322cecc042d1548bd938a34 | \
  gitleaks stdin --redact --config .gitleaks.toml
```

Results: **passed** for changed Python syntax, whitespace and secret scanning.
The specifically named `runtime-tools-secret_scanning` and local
`codeql_checker` executables are unavailable. Repository-standard Gitleaks and
GitHub CodeQL were used instead; no unavailable tool is represented as run.

```bash
gh workflow run kraken-recovery-gate-diagnostics.yml \
  --ref copilot/kraken-production-recovery \
  -f current_instance=true -f identity_compare=true
gh run watch 41393718060 --exit-status
gh pr checks 3560 --json name,state,workflow,link
```

The diagnostic run completed successfully; its identity observation was
**denied**, as recorded above. Successful workflow execution is not successful
certification. Before the final regression/documentation update, all 20 checks
on `fd1efd6013a3560656d184cfdea3e76270375507` passed, including main CI, native
regressions, image build, CodeQL, Bandit and secret scanning. Final-head check
results are recorded in the pull request; they must pass before review.

## Risk, rollback and post-deployment criteria

Risk is medium: these surfaces feed production safety observability. Principal
risks are secret leakage, stale/overlapping-instance evidence, false authority
and diagnostic-request replay. Bounded reads, fixed vocabularies, source pins,
private files, freshness checks and one-shot claims address those risks.

No merge or deployment was performed. Revert this focused change through a
reviewed release-branch revert if necessary. There are no schema migrations,
credential changes, nonce resets or order changes to undo. Preserve diagnostic
claims/receipts for audit; do not delete them to retry.

After authorized review and a separately approved deployment, verify the exact
commit live and stable, freshly authenticate through the existing nonce owner,
verify permissions/restrictions and independently approved bindings, reconcile
complete balances/orders/fills/ledgers and actual protective orders, supply all
six authoritative providers, and require all thirteen fresh independent checks
plus canonical execution proof. Until then retain `READ_ONLY_RECOVERY` and
`allow_new_orders=false`. No live test order is authorized.
