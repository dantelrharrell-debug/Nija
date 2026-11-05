# Production commissioning migration package — NOT a deployment

This is the Priority 4/5 **preparation package**, not permission to migrate,
install a collector, enable dispatch, clear a stop, submit an order or deploy.
Nothing here is startup-installed. No production service, broker, Redis or
database was contacted or changed to prepare this package.

## Engineering complete versus external prerequisites

Engineering artifacts available for review:

- Inert provider factories and explicit six-source composition
  (`bot/kraken_evidence_composition.py`), with account/key/source-object pins.
  Composition is not registration; fabricated callbacks are not genuine sources.
- `bot/commissioning_gate.py` and `bot/commissioning_runtime.py`: explicit
  composition, owner-only signed-record readers, distinct approval/status roots,
  exact-plan validation and durable single-use consumption before transport.
  General authorization and exact first-order authorization remain separate.
- Existing v436 ledger, v447 account-state preservation and v449 off-host
  evidence tools; offline integrity/isolated restore checks, not custody proof.
- `scripts/nija_production_release_manifest.py`: stdlib-only offline inventory
  generator/verifier, create-exclusive output and deterministic content.
- Trusted-mirror Trivy database acquisition with bounded retries and no stale
  fallback; HIGH/CRITICAL Trivy/Grype findings and scanner failures now fail CI.
  pip-audit and high-severity/high-confidence Bandit findings are not suppressed.
  Canary signing verifies the digest against the exact OIDC workflow identity
  and issuer; rollout references the scanned digest, not a mutable tag.
  Hosted review-head scans confirmed successful trusted-mirror acquisition and
  nonzero findings; subsequent heads still require their own evidence.
- Full dependency triage and tested security updates across runtime, billing and
  member-credential manifests: see `security/dependency_remediation_20261104.md`.
  The resolved billing/member scans report no known vulnerabilities. The root
  scan still fails on one moderate model-library advisory; it is not waived.
  PostgreSQL/Redis confinement preserves writable state, and independent image
  scanners retain failure evidence instead of skipping after another finding.

**External evidence and genuine owner approvals remain missing/unverified:**

- [ ] Authenticate the actual production deployment, exact source commit and
  digest-pinned built image; obtain build provenance/image scan evidence and
  required CI, secret-scan and CodeQL results for that exact release.
- [ ] Resolve scikit-learn CVE-2024-5206 with a compatible upgrade or retraining.
  Isolated 1.3.2-to-1.5.0 checks found GradientBoosting load and RandomForest
  prediction failures. Validate authenticated production model artifacts and
  run a representative backtest with authenticated data before rollout.
  Container OS/source findings require fresh exact-image hosted scans too.
- [ ] As GitHub administrator, enable Dependabot alerts/dependency graph and
  enforce the relevant CI/security checks in branch protection. This session
  could read scanning results but could not read/change repository Actions
  permission settings. Reconcile the new alert inventory, not the stale 166 count.
- [ ] Resolve remaining image/vendor findings and specifically disposition the
  legacy credential-candidate inventory in
  `security/hosted_scan_blockers_20261104.json`. These are open security work,
  not missing trading authorization. Investigate/revoke any genuine exposed
  credentials; do not blanket-baseline candidates or ignore unfixed findings.
  Review-head CI and both CodeQL analyses passed, but security gates are not all
  green and each subsequent release needs fresh exact-head/image results.
- [ ] Independent human review authenticates the composition root and actual
  source objects, all thirteen provider IDs, account/key/IIBAN pins, nonce-owning
  canonical broker, Redis coverage/signature verifier and durable ledger path.
  A local boolean, a manifest field, a CI pass or a test fixture is not review.
- [ ] Authenticate fresh read-only broker permissions/account identity,
  balances/holds, complete orders/history, positions, protective-order readback
  and owned-quantity coverage. Resolve pending fills/closes, missing mappings
  and historical cost basis against broker records; do not assume old failures
  have disappeared.
- [ ] Authenticate writer lock/generation/TTL and nonce ownership, complete
  submission-route inventory, durable kill-switch clearance, risk/capital
  snapshots and position synchronization for the same account/key/release.
- [ ] Independent custodian attests encrypted off-host retention and retention
  period, records source archive digests separately, and witnesses an isolated
  restoration/reconciliation rehearsal across every state store.
- [ ] Actual service/account owners separately approve deployment, durable
  schema migration, signing custody/trust roots, rollback and terminal transport
  changes. Record accountable owner identities, scope, time, expiry and
  authenticated evidence in the external review system, not an internal
  reviewer-username request or an assistant-generated approval.
- [ ] Authorized operator provides signed general authorization/current status
  and a **separate** signed exact first-order plan/current status bound to
  account, credential, writer generation, release and all-in cash ceiling.
  Approval is not fabricated to complete this checklist.

No independent approval is claimed. This checklist does not solve the legacy
cold-start order-or-fill dependency or authorize a missing-fill exception.
Historical successful CodeQL/build/signing jobs are not current-release proof;
fresh exact-head hosted scanning, provenance and signature verification remain
external release evidence, not something established by local tooling.
`COMMISSIONING_REVIEW.md` describes the still-required authority/FSM/transport
migration review. PRETRADE_READY grants no orders; POSTTRADE_VERIFIED does not
publish execution readiness or automatically authorize broad automation.

## Exact existing environment and API bindings

Record secret **presence and external secret-version references only**, never
values. Verify effective configuration in the authenticated writer process;
do not infer it from repository defaults or health/liveness responses.

| Existing environment binding | Required review |
| --- | --- |
| `NIJA_REDIS_URL`, `REDIS_URL` | Approved persistent Redis deployment, database and TLS policy; aliases must not route to different stores. Do not copy connection strings into evidence. |
| `NIJA_REQUIRE_DISTRIBUTED_LOCK=true`, `STRICT_REDIS_WRITER_LOCK=true`, `NIJA_REQUIRE_REDIS_FOR_LIVE=true`, `NIJA_STRICT_REDIS_LEASE=true` | Keep fail-closed distributed writer ownership; verify actual generation/TTL, not flags alone. Existing code also accepts `1` for the strict lease. |
| `NIJA_FAIL_CLOSED_EXIT_ON_UNREACHABLE_REDIS=true`, `NIJA_WRITER_RUNTIME_VERIFY_FAIL_CLOSED=true`, `NIJA_REDIS_PERSISTENCE_REQUIRED=true`, `NIJA_REDIS_RESET_POLICY=require_confirmation` | Preserve fail-closed/persistence policy. Never reset Redis to make evidence pass. |
| `NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK`, `NIJA_DISABLE_WRITER_LOCK`, `NIJA_CONFIRM_BYPASS_RISKS` | Absent or false; `NIJA_SKIP_STARTUP_PHASE_GATE` must remain unset. No forced-trade or local-lock fallback substitute. |
| `NIJA_TRADE_LEDGER_DB_PATH` | Explicit canonical persistent SQLite path, e.g. `/data/trade_ledger.db`, identical to the admission/commissioning `ledger` API argument and reviewed ledger binding. Never silently migrate a default `./data/trade_ledger.db` instead of the real ledger. |
| `NIJA_KRAKEN_PENDING_FILL_PROOF_PATH`, `NIJA_EXECUTION_JOURNAL_PATH`, `NIJA_POSITIONS_FILE` | Bind v436 companions to actual runtime paths. Tool fallbacks are respectively `./data/kraken_pending_fill_proof.json`, `./data/execution_journal.jsonl`, `./data/open_positions.json`; verify existence/inventory rather than accepting omitted files. |
| `KRAKEN_PLATFORM_API_KEY`, `KRAKEN_PLATFORM_API_SECRET` | One approved canonical platform credential pair. Existing shell normalization can promote a complete `KRAKEN_API_KEY`/`KRAKEN_API_SECRET` pair; never mix namespaces, repair a partial canonical pair by guessing, log values or instantiate another private client. Authenticate account and credential fingerprints independently. |
| `NIJA_MIN_CASH_RESERVE_USD`, `MIN_NOTIONAL_USD`, `MIN_TRADE_USD`, `MIN_POSITION_USD`, `MIN_CASH_TO_BUY`, `MINIMUM_TRADING_BALANCE`, `KRAKEN_MIN_NOTIONAL_USD` | Retain approved existing limits or stricter ones and all canonical sizing/venue controls. A commissioning budget does not override them. |
| `NIJA_KILL_SWITCH` | Preserve the real stop state. Unset/false is not proof of durable clearance or permission to clear a stop. |
| `NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S` | Existing position-sync freshness limit (default 90 seconds), never a stale-evidence override. |
| `NIJA_STARTUP_APPROVAL_PATH`, `NIJA_STARTUP_MAX_CASH_DEBIT_USD` | Existing legacy startup-plan inputs only; they do not activate commissioning or replace its separate signed-record APIs. |
| `ALLOWED_ORIGINS` | Exact comma-separated HTTP(S) browser origins without wildcards, patterns or paths. Defaults to `https://nijaaitrading.com,https://www.nijaaitrading.com`; explicit development origins such as `http://localhost:3000` remain supported. Private-network CORS grants are disabled on every existing Flask CORS integration. |

Capital-readiness handoff (`CAPITAL_READINESS_HANDOFF_V34_READY`), broker
connectivity snapshot, writer heartbeat, execution-proof/authority gates and
minimum-trade checks must remain genuine runtime proofs, never manually asserted
as evidence. Other enabled brokers retain their existing credential/safety
requirements; this package authorizes only the reviewed Kraken USD-spot envelope,
not broader venue routing.

**These are API arguments, not new environment activation switches:**

- `compose_kraken_evidence(binding, review_binding=..., clock=...)` takes
  `KrakenEvidenceBinding` with the reviewed ledger/Redis/risk/operator
  dependencies and exact account/key/IIBAN hashes. External review authenticates
  those exact objects and pins. Its six-field `collect()` result is not the full
  thirteen-field registry; preserve the other seven authenticated providers.
- `compose_commissioning_runtime(...)` requires `ledger`, `collector`, `fence`,
  `providers`, `trusted_provider_ids`, `execution_reader`,
  `candidate_for_request`, `plan`, `release_id`, `maximum_cash_debit_usd`,
  `account_scope`, `account_fingerprint`, `credential_fingerprint`,
  `general_approval_binding` and genuine `independently_reviewed` evidence.
- The same API takes exact absolute paths `approval_records_path`,
  `general_approval_records_path`, `operator_public_key_path`,
  `status_public_key_path` and `general_status_public_key_path`. Files must be
  owner-owned, owner-only regular JSON, not symlinks. Provision operator public
  keys and distinct exact/general status-signing roots under reviewed custody.
  `SigningKeyCustodian(signer, public_keys)` uses an opaque external Ed25519
  signer; this package generates/stores no private signing keys.
- No invented `COMMISSIONING_*` environment flag enables dispatch. Schema
  installation, collector registration, adapter installation and activation
  are separate reviewed operations, **not performed by this package**.

## Immutable post-commit release inventory

Generate **after** committing the reviewed source on a clean production-source
checkout, never commit the generated manifest into the commit it describes.
The base commit is the full authenticated previous-source commit, an ancestor
of the full source commit. The previous-release image is separately digest-pinned.

The generator binds SHA-256 for provider/evidence/collector/commissioning source
families, core admission/authorization/plan modules, all changed production
Python at repository root and under `bot/` and `scripts/`, changed shell scripts
(including `scripts/run_trivy_scan.sh`), all root `requirements*.txt`, all tracked
workflow files, Docker Compose configuration, Kubernetes manifests (including
the Redis deployment) and explicit source deletions in the base-to-source range.
Uncommitted production changes and new production source files (including
ignored ones) fail closed. It reads local Git and source files only, not services.
Root release/deployment inputs are also protected: `Dockerfile*`, `.dockerignore`,
`railway.json`, `render.yaml`, `runtime.txt`, `main.py`, `bot.py` and `start.sh`.

Commands below use **caller shell placeholders**, not runtime environment
activation settings. Obtain every digest/reference from external authenticated
review; never derive trust by copying the artifact's own claims.

```bash
mkdir -m 700 release-evidence
python -S -B scripts/nija_production_release_manifest.py create \
  --source-commit "$REVIEWED_SOURCE_COMMIT" --base-commit "$PREVIOUS_SOURCE_COMMIT" \
  --image "$REVIEWED_IMAGE_AT_SHA256" --previous-release "$PREVIOUS_IMAGE_AT_SHA256" \
  --reviewed-binding "account=sha256:$ACCOUNT_BINDING_DIGEST" \
  --reviewed-binding "broker=sha256:$BROKER_BINDING_DIGEST" \
  --reviewed-binding "redis=sha256:$REDIS_BINDING_DIGEST" \
  --reviewed-binding "ledger=sha256:$LEDGER_BINDING_DIGEST" \
  --reviewed-binding "signing=sha256:$SIGNING_BINDING_DIGEST" \
  --reviewed-binding "commissioning=sha256:$COMMISSIONING_BINDING_DIGEST" \
  --manifest release-evidence/release.json
python -S -B scripts/nija_production_release_manifest.py verify \
  --source-commit "$REVIEWED_SOURCE_COMMIT" \
  --expected-sha256 "$EXTERNALLY_RETAINED_MANIFEST_DIGEST" \
  --manifest release-evidence/release.json
```

`--image` and `--previous-release` require `repository@sha256:<64 lowercase hex>`;
all six binding references require digest-only `sha256:<64 lowercase hex>`.
No URLs, free-text approval claims, secrets or mutable tags are accepted. Output
is create-exclusive, owner-only and never overwritten; retain it and its digest
in independently controlled immutable storage. Reissue to a new path only.
Verification requires a separately retained manifest digest and source commit.
Changing an external reference and recomputing a hash is not authenticated review.
The tool cannot prove image provenance, binding authenticity or custody; it
explicitly reports approval/mutation authorization as false.

## Backup, independent verification and isolated restoration rehearsal

The following are **future owner-run commands**, not actions performed here.
First inventory actual source directories and the canonical ledger, establish
an approved quiescent/fenced checkpoint (without weakening writer guards), and
record generation/time and broker reconciliation. Create private local evidence
directories outside source data; never archive keys, environment files or logs
containing credentials. `TMPDIR` below only confines existing tools' scratch
storage to the chosen local work directory; it is not a trading setting.

```bash
mkdir -m 700 backup-evidence rehearsal-work
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_trade_ledger_snapshot_v436.py backup \
  --source "$NIJA_TRADE_LEDGER_DB_PATH" --output-dir backup-evidence
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_account_state_preservation_v447.py backup \
  --positions /data/positions --entry-prices /data/entry_prices --output-dir backup-evidence
python -S -B scripts/nija_account_state_offhost_evidence_v449.py snapshot \
  --persistent-root /data --positions-dir /data/positions \
  --entry-prices-dir /data/entry_prices --output-dir backup-evidence
```

These account paths are examples of the existing persistent layout, not proof
that a particular host uses it. v447 is the account JSON preservation/restore
bundle; v449 is additional constrained account-file custody evidence, **not** a
SQLite snapshot or a replacement for v447. Record each tool's exact returned
archive/bundle name and SHA-256 on the original host. Transfer encrypted with
approved SCP/SFTP to an independently controlled host; authenticate destination
identity and attest retained custody separately.

On that **independent isolated host**, with no production credentials, network
access, startup hooks, workers or live mounts:

```bash
mkdir -m 700 rehearsal-work
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_trade_ledger_snapshot_v436.py verify \
  --archive "$COPIED_LEDGER_ARCHIVE"
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_trade_ledger_snapshot_v436.py restore-test \
  --archive "$COPIED_LEDGER_ARCHIVE" --expected-sha256 "$ORIGIN_LEDGER_DIGEST"
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_account_state_preservation_v447.py verify \
  --bundle "$COPIED_ACCOUNT_BUNDLE" --expected-sha256 "$ORIGIN_ACCOUNT_DIGEST"
TMPDIR="$PWD/rehearsal-work" python -S -B scripts/nija_account_state_preservation_v447.py restore-test \
  --bundle "$COPIED_ACCOUNT_BUNDLE" --expected-sha256 "$ORIGIN_ACCOUNT_DIGEST"
python -S -B scripts/nija_account_state_offhost_evidence_v449.py verify \
  --archive "$COPIED_V449_ARCHIVE" --expected-sha256 "$ORIGIN_V449_DIGEST"
```

Run the separately reviewed schema migration **only on isolated copies** for
rehearsal, with synthetic records; validate refusal/replay behavior across
restart, expiry, ambiguous ACK, rejection, key rotation and writer handoff.
`install_schema()` is explicit and mutating; do not run it on production under
this checklist. The backup tools do not migrate or restore into the live ledger.

A transactional SQLite snapshot and independently captured JSON/Redis/broker
state are **not a cross-store atomic snapshot**. Integrity/table counts and JSON
round trips do not prove historical completeness, coherent cost basis, off-host
custody or trading eligibility. Independently reconcile the checkpoint across
SQLite reservations/attempts, journals, pending fills/closes, account JSON,
broker orders/trades/protective exits and Redis ownership state. Document gaps
and stop rather than inventing a coherent snapshot or cloning live Redis locks.

## Rollback without replay

1. Owner authorizes halt of new entries through existing fail-closed controls;
   preserve protective-close handling, current broker visibility and audit
   evidence. Revoke/expire approvals via legitimate signing/status authorities,
   not by editing records to look cleared.
2. Authenticate the manifest's previous digest-pinned image and compatibility
   with the **current** schema and durable state. An old binary unable to enforce
   current admission/commissioning reservations stays stopped, not deployed as
   a bypass.
3. Preserve consumed `account_entry_reservations` and `commissioning_attempts`,
   all tokens, approval hashes, writer/account/key bindings and dispatch facts.
   No rejection, timeout, cancellation, expiry, restart or rollback unconsumes
   permission; the gate intentionally has no reset API.
4. **Never blindly restore an older SQLite snapshot after dispatch**, including
   an uncertain ACK. Doing so can erase the durable pre-dispatch latch and permit
   duplicate spending while the exchange still owns an order/fill. Reconcile
   authenticated broker outcomes and current journals/ledger/JSON first; preserve
   consumed reservations in any owner-reviewed recovery plan.
5. Any destructive recovery requires separate owner-approved forensic
   reconciliation, cross-store recovery design and a new externally reviewed
   release. Restoring a backup or reverting code is never approval to submit
   another controlled first trade or publish `execution_ready`.
