# NIJA Reconciliation Refresh Stability v410

## Production symptom

The live Render service repeatedly reached `CLEAN_START`, then regressed to `PENDING` while both platform brokers still reported position-sync ready. This caused execution authority to flap and blocked new entries; protective exits could also be rejected while authority was lost.

## Root cause

`runtime_reconciliation_shutdown_v146_patch.py` required the legacy `_startup_position_sync_fetch_ok` flag to remain `True` continuously. Newer Kraken refresh logic intentionally clears that legacy flag during a bounded authenticated refresh. The v285/v399 strong-proof layer already distinguishes a current in-flight refresh from a completed failure, but v146 did not consult it.

## Repair

When the legacy fetch bit is not true, v146 now asks v285 for the current strong broker proof. In production, v399 permits that proof only when the existing authenticated snapshot is still current under the unchanged TTL, the exact Kraken refresh flight is still active, prior-good proof exists, and the flight has no error.

The repair does **not** extend snapshot freshness, mutate positions, clear the emergency stop, relax drawdown/risk limits, grant execution authority, or submit orders.

## Safety behavior retained

- stale snapshots remain fail closed
- completed exchange/transport failures remain fail closed
- disconnected/missing brokers remain fail closed
- explicit discrepancy/failure reconciliation states are preserved
- zero-broker startup remains fail closed
- terminal-risk emergency-stop state is not altered

## Validation

Regression tests cover transient strong-proof acceptance, stale/completed failure rejection, and the unchanged legacy-success path.
