# Kraken activation controller v1 — review-only design and acceptance contract

Status: **PROPOSAL ONLY**. No production code, collector installation, receipt, approval, or trading authority is created by this document. Scope: existing Render service `srv-d98dsr5aeets73fpbaqg`, issue #3890, protected release `release/justcall-handoff-only-20261017`.

## Objective
Turn missing operational evidence into explicit, actionable recovery tasks without treating absence of evidence as permission to trade. Preserve canonical Kraken broker/client, nonce owner, durable intent, writer lease, risk gates, protective exits, kill switch, and `allow_new_orders=false` until independently certified and separately authorized.

## State machine (no new execution path)
- `RECOVERY`: collect redacted failure codes; safe read-only diagnostics and bounded retry of approved probes; orders disabled.
- `VERIFYING`: validate current deployment/image, signatures, 13 account-scoped observations, journal and Kraken ledger reconciliation; orders disabled.
- `READY_FOR_APPROVAL`: all mandatory checks fresh and passing; emit a bounded authorization proposal only; orders disabled.
- `CONTROLLED`: **only after separate operator authorization** for account, pair, notional, type, time window and rollback; route through existing canonical writer.
- `PROTECTIVE_STOP`: material integrity, reconciliation, protective-exit, nonce, lease, kill-switch or risk failure revokes new-order authority; retain authorized management of existing exposure.

No transition to `CONTROLLED` may be triggered by deployment success, service heartbeat, a cached green flag, a retry, a local test, or collector registration alone. Restart/redeploy invalidates runtime evidence until reverified.

## Dependency-driven remediation
1. `protected_startup_artifacts_missing`: report **both** missing private files, expected trust/receipt roles, evidence owner, exact reviewed hashes and approval status. Do not create or install guessed artifacts.
2. `collector_missing`: after independently approved provisioning, check `protected_startup_factory_registered`, then actual `collector_installed=true`; never infer one from the other.
3. `observation_missing`: report each of 13 provider IDs, freshness and source ownership; retry read-only observations with bounded exponential backoff and jitter; never replay an order to recover a probe.
4. `reconciliation_pending`: compare current broker orders, fills, margin/spot positions, exits and fees with durable journal, pending closes and Redis duplicate inventory. Preserve unresolved obligations.
5. `security_gate_failed`: link exact release/image finding and approved remediation PR; do not waive or auto-refresh independently pinned source hashes.
6. `approval_missing`: prepare exact-scope authorization request; do not infer operator approval.

## Proposed implementation boundaries
- Add a **pure, read-only** evaluator of normalized signed evidence and existing canonical gate outputs. No Kraken network client, nonce generator, new writer, side-effectful import, new permission source, or auto-enable path.
- Expose a redacted status report with `state`, `blockers[]` (code, evidence age, owner, next action, verification), exact commit/image pins, `collector_installed`, `observations_verified_count`, `allow_new_orders`, and audit timestamp.
- Keep signed private artifacts and account/key fingerprints out of logs and GitHub.
- Use bounded retries only for idempotent read-only diagnostics. No automatic production deployment, secret provisioning, credential rotation, risk override or live order.
- Treat stale/unsigned/unscoped evidence as unavailable, not passed.

## Test plan before code merge
- Unit tests for every state transition, stale evidence, signature/scope mismatch, missing protected artifacts, missing 1–13 observations, revoked approval, restart and conflicting broker state.
- Offline replay against redacted historical issue #3890 scenarios; no signed Kraken request.
- Assert `allow_new_orders=false` in RECOVERY, VERIFYING, READY_FOR_APPROVAL and PROTECTIVE_STOP.
- Confirm a separate bounded authorization and all fresh mandatory evidence are required for CONTROLLED.
- Regression tests for single canonical nonce/writer, durable order-intent and protective exits.
- Run exact-head CI, source-integrity, security and artifact checks; independent review before any merge/deploy.

## Immediate production dependency
Post-PR #4100 production logs still show `protected_startup_artifacts_missing`, `collector_installed=false`, 0/13 observations and `allow_new_orders=false`. The existing runbook `docs/kraken-3890-production-provisioning-handoff.md` remains authoritative for private artifact review and separately approved installation. This design **does not** unblock trading until those real dependencies are satisfied.
