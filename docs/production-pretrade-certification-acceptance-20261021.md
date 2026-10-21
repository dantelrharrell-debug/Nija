# Production pre-trade certification and release acceptance (2026-10-21)

Target Render workspace: `tea-d37fhe8gjchc73c8eo0g`; trading service: `srv-d98dsr5aeets73fpbaqg`.
Deployed production commit observed: `1568a9ea19f0c4e93a86cdcaeb5f0211a68cc32c`.
Main comparison head: `1ac93564e2d8a56355207279141e6034c8efc080` (38 commits ahead).

## Observed blockers

- Production: `PREACTIVATION_EXECUTION_PROOF_V16 ready=false producer=missing failing_condition=verification_stale`; never relabel historical evidence as fresh.
- Production: `PRETRADE_INDEPENDENT_CERTIFICATION_V6 ready=false account_scope_configured=false diagnostic_only=true legacy_execution_gate_unchanged=true`.
- Production: `ACTIVATION_SINGLE_FLIGHT_DEFERRED first_blocker=proof.execution_ready`.
- Position coverage logs include `protective_exit_verified=false` for some positions. Broker readback is mandatory.
- `bot/startup_authenticated_bridge_v456.py` is a diagnostic bridge, not a dispatch hook; `bot/startup_two_phase_policy_v8.py` explicitly returns `activation_allowed=False`.
- `bot/pretrade_independent_attestation.py` defaults to no collector and denies every attestation until a separately audited producer is installed.

## Fail-closed acceptance criteria

1. **Release isolation:** Port only reviewed execution-recovery changes to the production release branch. Do not blindly deploy all main commits, which include billing and Academy changes. Require green execution-recovery CI and explicit review of the actual release diff.
2. **Authenticated account identity:** Verify credential fingerprint, API permissions, account scope, pagination completeness and collector provenance. Do not log secrets.
3. **Reconciliation:** Read broker orders, fills, fees, ledger, balances/holds, positions and open orders through the existing nonce-owning authenticated client. Match exact broker order IDs, executed volume, cost, fees and ledger postings; flag unmatched or pending orders. Never generate a test fill.
4. **Protective exits:** For every non-dust position, independently read back exchange-side stop/exit orders, reconcile quantity and ownership, and block new entries on absent or ambiguous coverage. Preserve emergency exit paths.
5. **Authority:** Verify a single active writer lease and generation, monotonic nonce ownership, durable duplicate-intent fence, kill switch, circuit breakers, per-account capital and operator authorization.
6. **Backup:** Require a current off-host backup with an independently tested restore, version/checksum, scope and age before asserting `backup_restore_certified`.
7. **Two-phase admission:** Connect audited current facts to the canonical pre-dispatch gate only after review. Fresh pre-trade readiness may admit a candidate without a prior fill, but must not claim execution proof; after any real order, enforce post-trade broker fill verification within the 1,800-second limit. Pending/unknown execution remains blocked.
8. **Proof of release:** Record CI results, reviewer, commit SHA, Render deploy ID, fresh account-scoped attestation, ledger/protection readbacks, backup restore receipt and post-deploy log checks. Do not mark LIVE until all gates pass.

## Explicit prohibitions

No fabricated trades, reused verification markers, unconditional readiness booleans, bypassed kill switch, unreviewed admission activation, additional nonce-writing client, or test orders.

This document is an operational acceptance checklist, **not** a claim that any certification has passed or that trading is authorized.
