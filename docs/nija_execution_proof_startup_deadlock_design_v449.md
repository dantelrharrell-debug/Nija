# NIJA execution-proof startup deadlock: proposed remediation (review required)

## Root cause (confirmed source inspection)

`preactivation_readiness_convergence_v16_patch.py::_genuine_execution_marker_proof`
requires a stage ORDER_VERIFY/FILL_VERIFY, source heartbeat_trade or
canonical_confirmed_fill, proof_kind execution_probe and an event timestamp at
most 1800 seconds old. `_collect_proofs()` includes that predicate in
`execution_ready`, which is needed before activating live order dispatch.
When no authenticated order or fill is possible until activation, this can be
a *circular liveness dependency* even if the execution pipeline is healthy.

This document does not authorize removing execution controls, activating orders,
or changing any currently deployed gate.

## Proposed split (requires design review and testing)

1. **Preflight readiness** (must be true before dispatch): active writer lease,
   nonce sequencing, broker account identity and permissions, current balance
   and positions, reconciliation, protective exits for existing positions,
   configured strategy/risk sizing, kill switch clear, and authenticated
   read-only API check. No order submission required.
2. **Execution evidence** (per actual order, after dispatch): validated broker
   order ID, acknowledged state and independently confirmed fill, tied to
   account/pair/side/size and idempotent ledger intent; enforce expiry of the
   evidence for that order. Failed confirmation halts further new orders.
3. **Continuous freshness**: require current broker account and position state
   before *each* new order, rather than requiring an unrelated trade within
   the last 30 minutes. An idle strategy must not expire solely for having
   placed no trades.
4. **Fault behavior**: reject orders on invalid lease/nonce, missing protective
   exits, unreconciled positions, stale account state or missing permissions.
   Kill switch remains authoritative; do not treat a passing liveness probe
   as permission to trade.
5. **Migration**: add a separately named `preflight_operational_ready` and
   `last_execution_evidence_status` as OBSERVABILITY ONLY first. Test cold
   startup with no historical fills, idle for >30 minutes, actual stale broker
   state, outstanding unmatched close and active kill switch. Only after
   independent risk review decide whether to replace the legacy startup
   `execution_ready` dependency. Never merge/deploy this proposal alone.

References:
- https://render.com/docs/health-checks
- https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-?mode=consumerapp

No live permissions, proof timestamps, risk thresholds, ledger data or order
routing are altered by this documentation.
