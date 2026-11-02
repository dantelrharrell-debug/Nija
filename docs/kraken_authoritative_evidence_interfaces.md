# Kraken authoritative evidence interfaces

## Status and authority boundary

These are opt-in, read-only certification implementations, **not production
certification, activation, or independent approval**. Nothing imports them from
startup, installs a collector, changes execution admission, submits orders, or
modifies production SQLite/Redis. Existing `READ_ONLY_RECOVERY`,
`allow_new_orders=false`, kill-switch, protective/emergency exit, writer lease,
nonce, minimum-notional, and per-order risk checks remain unchanged.

The target is `release/justcall-handoff-only-20261017`. This work is separate
from the earlier diagnostic-only draft #3566. Neither PR is approval to trade.

## Files and implemented interfaces

| File | Interface |
|---|---|
| `bot/kraken_ledger_evidence.py` | `ReviewedLedgerBinding`, `make_kraken_ledger_evidence_provider` |
| `bot/kraken_redis_evidence.py` | `ReviewedBinding`, `ScopeObservation`, `RedisEvidenceReader.collect`, inert offline inventory plans |
| `bot/kraken_operator_authorization.py` | `GeneralApprovalBinding`, `make_general_operator_authorization_provider` |
| `bot/kraken_risk_evidence.py` | `AccountRiskSnapshotSource`, `make_kraken_risk_limits_provider` |
| `bot/tests/test_kraken_ledger_evidence.py` | Ledger/history/protection regression fixtures |
| `bot/tests/test_kraken_redis_evidence.py` | Distributed-state, inventory and offline-plan regressions |
| `bot/tests/test_kraken_operator_authorization.py` | Synthetic Ed25519 approval/revocation and registration regressions |
| `bot/tests/test_kraken_risk_evidence.py` | Account-risk, provenance, freshness and limit regressions |
| `.github/workflows/ci.yml` | Explicit mandatory execution of all four regression files |
| `bot/pretrade_attestation_validation_v452.py` | Reject expired or malformed optional source expiry |
| `bot/pretrade_composition_bridge_v465.py` | Preserve earliest source expiry in aggregate evidence |
| `bot/pretrade_independent_attestation.py` | Deny cached aggregate evidence after source expiry |
| `bot/pretrade_multi_account_registration_v474.py` | Reject expiry during collector registration |
| `bot/tests/test_pretrade_attestation_validation_v452.py` | Short signed-lifetime regression tests |
| This document | Contracts, dependencies, limits and review handoff |

### Ledger reconciliation

The provider uses the supplied existing Kraken broker's
`_kraken_private_call(..., category=monitoring_category)`, retaining its nonce,
request serialization, rate controls and gateway routing. Only identity,
balances, history, ledgers and open-order read endpoints are permitted.
`GetApiKeyInfo` authenticates externally pinned API-key SHA-256 and canonical
IIBAN SHA-256. Identity and balances bracket the collection. Complete history
pages require explicit cursor exhaustion, no repeated cursors, and consistent
counts/IDs. Missing cursor capability is a denial, not an offset fallback or
assumption that a short page is complete.

The SQLite reader uses read-only connections to a reviewed persistent path.
It reconciles exact exchange trade/order IDs, quantities, cost, fees, signed
asset movements, current balances/positions, pending closes and native
protective IDs. NIJA internal IDs are never treated as exchange IDs.
Duplicates, missing fills/fees, unmatched orders, unresolved submissions,
missing genesis history, stale snapshots and concurrent changes deny evidence.
Current accounting coverage is deliberately limited to fully attributed long
BTC/USD and ETH/USD spot inventory with USD fees. Unsupported assets, margin
and fee currencies deny rather than receive approximate accounting.

The existing `trade_ledger_db.py` schema cannot establish this provenance:
`open_positions` has no broker/account-key attribution, and accounting trade
IDs do not establish exchange-fill identity. The new reader requires an
independently persisted scoped ledger with:

- Every row: `broker`, `account_scope`, `api_key_sha256`, `account_sha256`.
- `trade_ledger`: exchange trade/order identity and independently attributed lot.
- `open_positions`: actual stop/take-profit exchange order IDs.
- `ledger_open_orders`: independently persisted exact outstanding-order terms.
- `pending_kraken_closes`: exact exchange order, lot, executed amounts and fees.
- `ledger_evidence_state`: schema/revision, original observation time,
  genesis-history completeness and unresolved-submission count.

Existing records are not relabeled, migrated, or repaired. A separately
reviewed persistence/import implementation must establish ownership from real
authenticated records. Snapshot matching is not a cross-store atomicity proof.
Production cursor/gateway compatibility and complete history remain unverified.
`offline_ledger_schema_sql()` supplies inert DDL for a **separate certification
database**, with no history, identity, genesis, revision or freshness defaults.
It is not a migration of the operational ledger and is never executed at startup.

### Redis inventory, fencing, writer and nonce evidence

`RedisEvidenceReader.collect()` returns separate v452 observations for
`duplicate_order_fence`, `writer_lease`, and `nonce_sequence`.
It reads the actual `decision_context` `token|state` fences, global writer lock
and generation, and distributed nonce owner/version/fingerprint/counter keys
using read-only transactional pipelines. Nonce lineage is explicitly distinct
from process generation. Ownership, expiry, generation, fingerprint or scope
changes, missing fences, unresolved outcomes and connection errors deny.
All three observations expire conservatively at read-start plus the shortest
relevant observed lease/fence PTTL, never later than 60 seconds. A cached fresh
observation cannot outlive the distributed lease it describes.

The legacy TTL/deleted fences and local retry records are not an enumerable
historical inventory. The compatible opt-in design uses durable manifest,
member set and records under:

```text
nija:kraken:evidence:inventory:v1:<sha256(account)>:
```

`inventory_keys`, `offline_manifest`, `plan_offline_inventory_record`,
`OFFLINE_RESERVE_LUA` and `OFFLINE_FINALIZE_LUA` describe an inert, atomic,
additive inventory design. There is no execution/activation API. Offline
manifests cannot certify. Existing production intent records are untouched.

Certification requires separately signed reviewed-cutover coverage binding
the account/key, complete submission/retry routes, deployment, provider IDs,
source-binding digest, historical boundary and reconciliation reference,
disabled legacy paths, complete sorted inventory digest and count. The
externally pinned digest and coverage-specific verifier must match.
Every inventory change invalidates the signed inventory digest.

**This coverage signature is not general live-order operator approval.**
Production cutover, historical reconciliation, complete route instrumentation,
and the separately reviewed coverage verifier are missing dependencies. No
production migration was activated.

### Independent operator authorization

General permission uses two detached Ed25519 signatures with separate,
out-of-band pinned public trust roots:

1. `nija.general-live-approval.v1`: exact approval ID, Kraken account scope,
   canonical IIBAN SHA-256, API-key SHA-256, trading mode, exact sorted scope,
   authorized operator ID, approval/expiry times and release identity.
2. `nija.general-live-approval-status.v1`: exact approval ID and canonical
   approval SHA-256, positive generation, explicit `active`/revoked status,
   observation time and expiry.

Canonical signature bytes are UTF-8 JSON with sorted keys, separators
`(",", ":")`, and nonfinite numbers forbidden. Signatures are strict base64.
Public keys are raw 32-byte Ed25519 keys, pinned by independent review, never
taken from the signed record. No signing/issuance or private-key API exists.
`read_records()` supplies `{"approval": envelope, "status": envelope}`; each
envelope contains exactly `payload` and `signature`.

The status must positively attest active membership of the exact digest,
be no more than 60 seconds old, and remain unexpired through collection.
Evidence lifetime is bounded by the original status timestamp plus 60 seconds
as well as both signed expirations; collection never renews status freshness.
Absence from a revocation list does not imply authorization. Two reads reject
record replacement during collection; unavailable, forged, revoked, expired,
wrong-account/key/mode/scope/release or startup-only approvals deny.
SHA-256 API-key pins match v478, not the startup plan's SHA-512 field.

There is no established general approval issuance/revocation service in the
inspected runtime. Independently vetted operator keys, status-signer custody,
legitimate signed records and a separately reviewed uncached record source
remain external dependencies. Startup-plan approval is never consulted.

### Account-level risk clearance

`AccountRiskSnapshotSource.read_snapshot(account, api_key_sha256)` supplies a
reviewed account snapshot containing separately pinned `capital`, `exposure`,
and `policy` records. Each record requires exact account/key/broker/source
identity, positive revision, complete provenance and original timestamp.
The maximum age is 60 seconds; partial hydration and nonfinite or ambiguous
numeric values deny. Two reads reject account/revision/content changes.
The oldest original record timestamp and stricter source expirations are
preserved through certification; reading a snapshot never extends its TTL.
The source must monotonically advance revisions on every change, including
changes later reverted.

Capital must be real, positive, hydrated and registered; usable capital cannot
exceed real capital. Exposure includes every open position **and pending or
reserved intent**, without long/short netting. Position counts, total risk,
concentration, gross exposure, leverage, short policy, drawdown, daily loss,
consecutive losses and verified protective coverage are checked against the
current policy. Equality is rejected for admission-stop thresholds such as
position count, total risk, drawdown, daily loss and consecutive losses.

Optional `CapitalAuthority` read APIs cross-check registered, hydrated,
fresh, complete account-bound capital. Optional
`GlobalRiskGovernor.get_status()` is an additional veto only: health is not
account risk clearance. Existing global reports lack authenticated account/key
provenance and atomic complete account exposure revisions; a separately
reviewed account snapshot producer remains required.
This evidence cannot replace per-order authorization or reserve capital.

## Existing source contracts and registration

Results retain v452 source ownership: independent ledger, writer authority,
operator authority and risk governor. Evidence IDs are field-specific;
provider IDs and account/key pins come from reviewed external bindings.
Provenance includes scope, source proof, completeness, read-only status and
original timestamps. Providers deny or raise sanitized fixed denial codes;
exceptions cannot produce successful evidence. All outputs are non-authorizing.
Optional `expires_at_epoch` is validated independently of the 60-second
observation ceiling. Signed approval/status expiry survives aggregation,
cached diagnostic reads and reviewed registration; a fresh observation cannot
extend a signed authorization's lifetime.

These providers can be supplied to the existing v490 six-source contract and
v474 reviewed account registry without replacing v452, v465, v468 or the
execution-admission pipeline. They do **not** fill the remaining independent
kill-switch, authenticated broker/protection/open-order/position-sync and
permission sources merely because their own checks pass.

**Collector registration is not currently safe.** No providers were installed.
All thirteen checks, independent provider identities, complete source bindings
and authenticated fresh production evidence must pass the existing registration
boundary after independent review. An evidence result never grants dispatch.

## Backup, restore and production-access evidence

Only repository code, sanitized historical Actions outcome lines and artifact
metadata were inspected. No Render shell, Kraken credential, production ledger,
Redis state, backup decryption key or live-order access was used.

Historical recovery run `40994049361` (source commit
`86025246f00f12b35db2ea92bcf0ae7667061b1f`, 2026-10-30) contains actual
`OFF_HOST_SOURCE_SEAL`, archive/receipt hashes, pinned verifiers, and
`OFF_HOST_RESTORE_AND_ARCHIVE_VERIFICATION=PASS` output. Its encrypted backup
artifact was reported available and unexpired during inspection. These are
historical workflow observations, not a new independent restore.
The subsequent run `40994062244` failed with
`BLOCKED: Render instance or commit changed during transfer`.

Encryption-key custody/recovery, cross-store atomicity and authenticated
historical broker reconciliation were explicitly **UNVERIFIED** even in the
successful run. They remain blockers. Current service/deployment identity and
current recoverability have not been independently established.

## Required independent review before any production binding

Review Kraken endpoint compatibility and full-history limits; independently
establish persistent account/lot attribution; review and authorize Redis
cutover and all submission/retry routes; approve public-key custody and
operator issuance/revocation; and validate complete account risk/exposure
snapshots against authenticated broker and capital sources.

Infrastructure/code review and synthetic passing tests are not independent
production approval. No merge or deployment is authorized by this work.
Live-order controls remain unchanged; actual production block state is not
claimed from an offline checkout.

## Validation evidence

Validation used restored Python **3.11.16**, existing `requirements.txt`,
and `NIJA_DEFER_RUNTIME_SITE_HOOKS=1`. No dependency manifest changed.

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 /tmp/nija-evidence-venv/bin/python -u scripts/run_unittest_partitioned.py --baseline .github/ci_known_test_failures.txt --preload-module requests --preload-module bot --traceback-after 120 --max-files 25 --min-tests 2554
```

Result: baseline ratchet passed; **2,823 tests run, zero unexpected failures**,
31 isolated processes. The existing known-failure baseline was not changed;
this is not a claim that every legacy test passes individually.

The exact mandatory fail-closed selectors from `.github/workflows/ci.yml`
were executed with the same Python 3.11 interpreter: **812 passed**.
The four new provider files alone passed **145 tests** with:

```bash
NIJA_DEFER_RUNTIME_SITE_HOOKS=1 /tmp/nija-evidence-venv/bin/python -m pytest -q bot/tests/test_kraken_ledger_evidence.py bot/tests/test_kraken_redis_evidence.py bot/tests/test_kraken_risk_evidence.py bot/tests/test_kraken_operator_authorization.py
```

The expanded provider/source registration, composition, expiration, admission
and backup regression selection passed **301 tests**.
The Redis tests include a real private, ephemeral Redis 7.0.15 Unix-socket
subprocess with port 0 and persistence disabled; no shared Redis was accessed.

Changed Python files compile cleanly. Changed-file `detect-secrets==1.5.0`
and Bandit checks passed. Synthetic invalid-fingerprint fixtures have only
exact-literal secret-scanner allowances. Three Bandit SQL identifier warnings
are narrowly annotated: table/column names come solely from static schema
constants and account values remain parameter-bound.

The named `runtime-tools-secret_scanning` and `codeql_checker` tools were not
available locally. Existing hosted CodeQL/security workflows must pass on the
new pull request; results for older drafts are not evidence for this commit.
Hosted CI/security checks passed for the initial implementation head except
one CodeQL HIGH finding, `py/weak-sensitive-data-hashing`, at the API-key
SHA-256 fingerprint comparison. This is identity fingerprinting of a
high-entropy Kraken API key, not password storage; changing the algorithm
would break independently pinned identity compatibility. The site explains
the distinction. The alert was **not suppressed or dismissed** and requires
external false-positive review before merge. Later head statuses must be
checked separately.
Human independent infrastructure, accounting, authorization and risk review
remains required even after CI succeeds.
