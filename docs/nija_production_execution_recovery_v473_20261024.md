# NIJA Production Execution Recovery v473 — fail-closed checklist

**Scope:** This document accompanies a source-level correction to the v16 execution-proof age check. This change **does not** install broker authentication, start trading, migrate the ledger, change any production configuration, or authorize an observation window.

## Verified incident context (October 25, 2026 UTC)

- Render workspace `tea-d37fhe8gjchc73c8eo0g`, service `srv-d98dsr5aeets73fpbaqg`, last observed deployed SHA `dcac6f295e356f8c6a1c3acf2fa8f256a028436f`.
- Production `STARTUP_STATE_DUMP` reported `execution_ready=False`, `execution_authority=False`, `trading_engine_ready=False`; state `LIVE_PENDING_CONFIRMATION`.
- Independent pretrade certification reported `account_scope_configured=false`, `collector_installed=false`, and missing authenticated identity, permissions, ledger, exits, open orders, duplicate fence, writer, nonce, and operator proof.
- `PREACTIVATION_EXECUTION_PROOF_V16` reported `producer=missing`, `verification_stale` and roughly 1.37 million seconds since verification.
- Fresh three-broker capital snapshots are available, but do not establish execution permission.
- Kraken account-scoped position and exit-coverage diagnostics repeatedly alternated between ready and pending; these are not uninterrupted, independent broker exit certificates.
- The dedicated ledger mount exists, but migration integrity, restored off-host backup, and historical P&L are unverified.

## Source correction

`preactivation_readiness_convergence_v16_patch.py` now rejects a proof whose **actual authenticated broker event** is absent, future-dated, or older than 1,800 seconds, even when a collector wrote a recent verification timestamp. For canonical fills, the heartbeat and v402 verification paths must agree on event time. The logs show both event age and verification age. It also refuses noncanonical account scopes and legacy/uninstalled collector check arrays. These are safety hardening fixes, not an activation path.

## Remaining required production implementation

1. **Approved collector composition root.** An authorized engineer must inventory actual Kraken, Coinbase, OKX, and applicable Alpaca account IDs, credential fingerprints, permissions, and runtime identities without exposing keys. Bind the exact canonical `platform:<broker>` and `user:<id>:<broker>` scopes; reject any scope not in the audited registry. `bot/pretrade_reviewed_registration_v467.py` and `bot/pretrade_composition_bridge_v465.py` require **13 real account-scoped evidence providers**, distinct trusted identities across broker, independent ledger, writer, operator, and risk classes. Do not auto-install placeholder functions or derive trusted identities from the observation itself. The collector must run inside the actual nonce-owning trading process and remain read-only.
2. **Historical ledger reconciliation.** Obtain complete, authenticated, independently account-bound Kraken `QueryOrders`, `TradesHistory`, `OpenOrders`, `ClosedOrders`, positions, and fee/asset records, using documented pagination and retry limits. Reconcile the 13 pending closes and all missing opening orders/intents against durable ledger records with exact order/trade IDs, quantities, fees, and lots. Use `bot/broker_history_reconciliation_plan.py` as a *non-mutating plan* only. Never infer absent openings or invent strategy attribution. Review a reversible accounting migration, then verify on independently backed-up data before any production ledger changes.
3. **Protective exits.** For each authenticated account and actionable position, read back actual broker-confirmed exit orders or separately independently certified active software protection and its exact dispatch authority. Distinguish four configured protection types from four working venue-side orders. Compare quantity, venue, symbol, side, order status, price/trailing policy, OCO linkage where supported, and residual exposure. Treat missing readback, stale tracker objects, unsupported symbols, and unknown cost basis as unresolved; do not claim dust-exempt exposure as protected.
4. **Durable state and off-host certification.** Back up `/data/trade_ledger.db`, current authoritative positions/entry prices, pending intents, and recovery receipts using an approved *read-only* snapshot procedure. Independently transfer off host, hash with SHA-256, perform an isolated restore and SQLite integrity/reconciliation checks, and record manifest, archive timestamp, exact SHA, destination, and reviewer. A mounted disk or successful local integrity check alone is not certified recovery.
5. **Two-phase startup admission.** `bot/startup_two_phase_policy_v8.py`, `bot/startup_authenticated_bridge_v456.py`, and v468 are **diagnostic only**. Any true pretrade startup alternative must be reviewed, tested, and explicitly wired into the single canonical dispatch/controller. It must consume current authenticated account, broker, capital, ledger, risk, position, exit, writer, nonce, circuit-breaker, kill-switch, and operator proof **before** permitting any new entry. Preserve the posttrade order/fill verification requirement and the unchanged maximum 1,800-second broker-event age. An empty history or an unrelated earlier fill is not a pretrade proof.
6. **Release and 24-hour observation.** Pass hosted CI, static/security checks, and independent broker/risk/ledger review before a separately authorized release. Capture the exact deployed SHA, runtime instance identity, first unrevoked `EXECUTION_ALLOWED=true`, `LIVE_ACTIVE`, and authenticated evidence timestamps. Do not start observation if any gate is missing or any deployment/restart interrupts continuity. Record confirmed executions, realized fees and P&L only from durable broker-linked ledger evidence.

## Absolute safety boundary

Do **not** create or cancel orders, use heartbeat/test trades, clear kill switches, suppress circuit breakers, widen freshness TTLs, mint or touch execution proofs, backfill fictional history, enable risk bypasses, disclose secrets, or treat a passing CI run as live authorization.

**Current outcome:** `NOT VERIFIED`. This change is a candidate source repair awaiting test, review, deployment authorization, and independent production certification; live execution remains blocked.
