# NIJA pre-trade evidence and capital handoff: fail-closed diagnostic release

Date: October 22, 2026. Base: Render production release branch
`release/justcall-handoff-only-20261017` at
`49ab14027c36b4bdee95714aecaed2e4c5f8c9a1`.

## Observed production blockers

Render production reported:
- `PRETRADE_INDEPENDENT_CERTIFICATION_V6 ready=false account_scope_configured=false`.
- `PREACTIVATION_EXECUTION_PROOF_V16 ready=false producer=missing failing_condition=verification_stale`.
- `ACTIVATION_SINGLE_FLIGHT_DEFERRED first_blocker=proof.execution_ready`.
- Intermittent `REGISTERED_PLATFORM_CAPITAL_V270_FAIL_CLOSED registered=3 connected=3 valid_brokers=0` with an upstream refresh pending, even during separately accepted canonical capital publication.

Connectivity, a last-known capital balance, a passing software protection check, and a deployed history-pagination fix do **not** independently prove account reconciliation, current protective coverage, or execution authority.

## What this pull request actually changes

1. Add `inspect_authenticated_attestations` to the existing *non-authorizing* collector boundary. Return literal-True checks only with current, exact-account, read-only, independently authenticated provenance. The diagnostic result has a fixed status such as `collector_missing`, `account_scope_mismatch`, `provenance_unverified`, `observation_missing_future_or_stale`, or `checks_incomplete`. It never returns order authority.
2. Let v16 log that allowlisted producer status and whether a collector is installed, without account IDs, exceptions or credentials. The existing canonical execution proof remains mandatory.
3. Add a fixed `refresh_evidence_stage` to the v270 capital denial log, identifying coalesced or pending coordinator results separately from disconnected brokers and genuinely incomplete contributors. The existing three-broker count, publication freshness, startup lock, and fail-closed action remain unchanged.
4. Extend offline regression tests and the execution-recovery CI security/test workflow.

**Not included:** installing a real broker or ledger evidence producer, assigning an authenticated account scope in production, changing the deployment, clearing a stop, modifying a database, placing an order, or granting execution authority. A configured environment value or synthetic test payload must never qualify as production account identity or provenance.

## Required subsequent engineering and release work

1. Authenticate the exact broker account, audit the existing nonce-owning read client and legal account scope, and provide independent signed/verified producer identities for broker, ledger, writer, risk and operator facts. Use the separate v452/v453 validator contracts; do not promote self-reported booleans or stale observations.
2. Complete Kraken history and account-scoped entry/close/fee reconciliation and independently verify protective exits against exposed broker positions. Unresolved 13 closes, missing cost basis or unknown holdings remain blocked until genuinely resolved.
3. Investigate the actual capital producer after the new v270 stage logs, rather than treating a pending or deduplicated zero-contributor result as a completed refresh. Preserve the capital publication TTL, broker-count denominator, single-writer fencing and fail-closed result.
4. Integrate the reviewed two-phase policy only when the independent pre-trade certificate, durable per-account reservation, exact broker/ledger protection, risk, writer/nonce and operator gates all pass. Update every relevant execution-authority consumer together; never replace post-trade execution proof with readiness or refresh an old broker event timestamp.
5. Require security and broker-integration review plus hosted CI, then controlled deployment after current independently verified off-host backup and rollback planning. Only start 24-hour live observation after a current `LIVE_ACTIVE` and `EXECUTION_ALLOWED: TRUE` without later revocation.

Production must continue to deny new orders if any evidence is missing or stale.
