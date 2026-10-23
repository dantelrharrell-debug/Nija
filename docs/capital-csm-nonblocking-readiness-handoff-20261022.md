# NIJA capital CSM ingestion: nonblocking venue-readiness reevaluation

Date: 2026-10-22 PDT / 2026-10-23 UTC. Based on production release SHA
`bb44154fe7ff4c00bf7cb0c4ced7b2b676d7cd44` (Render service
`srv-d98dsr5aeets73fpbaqg`).

## Live evidence and call-chain finding

The previous read-only diagnostic release #3337 was deployed, and Render logged
`CAPITAL_PIPELINE_SUBSTAGE_V142 stage=csm_ingest status=done` with durations
**98,520.7 ms**, **107,823.8 ms** and **121,705.4 ms**. The capital worker's
existing deadline remains **50–80 seconds** and a post-deploy v142 timeout
occurred with `stage_hint=csm_ingest`.

In the first event, `CAPITAL_READINESS_HANDOFF_V34_READY` logged at
03:54:20.743 UTC, immediately after CSM ingestion began, while
`BROKER_INDEPENDENT_EXECUTION_WAITING` from the three-venue verifier logged at
03:55:59.263 UTC, immediately before that ingestion returned (98.5 seconds).
The other two ingestion stalls correlate with venue verifier completions at
03:58:16.236 and 04:00:24.043 UTC respectively.

Source call chain:

`CapitalRefreshCoordinator._pipeline` -> `CapitalCSMv2.ingest_snapshot`
-> patched `capital_readiness_handoff_v34._publish_ready`
-> **synchronous** `three_venue_execution_readiness.publish_once(force=True)`
-> `evaluate_all` -> `evaluate_venue` -> authenticated
`broker.get_account_balance[_detailed]` and market metadata methods.

The synchronous call creates a plausible and strongly correlated contributor
to the 50–80 second capital refresh timeout. It is not proof that every prior
runtime-FSM timeout has the same cause.

## Minimal correction

- v34 still publishes its existing capital-handoff telemetry only after its
  existing CSM READY, positive, fresh snapshot check (and the stricter canonical
  gate from v170 when installed). **No new capital facts are manufactured.**
- v34 no longer imports the venue module on the writer/coordinator thread and
  never calls the network-facing evaluator inline. Instead it requests a
  nonblocking wake-up on the already installed three-venue monitor. If the
  verifier module is unavailable, the request is deferred, without fallback
  synchronous broker I/O or altered execution authority.
- The existing three-venue verifier monitor continues doing the same
  independent broker, capital and writer assessment in its own worker. A
  `threading.Event` coalesces wake-ups and keeps the existing periodic polling
  fallback. No additional per-request threads, snapshot writers, bypasses, or
  concurrent duplicate verifier workers are created.
- Regression tests require nonblocking calls, unchanged capital handoff
  fields, no immediate publication from the caller, coalesced requests,
  periodic monitor handling, and prevention of wake signals for stale/zero/
  unaccepted snapshots. The recovery CI compiles, secret-scans and tests every
  changed runtime file.

## Release hold and required verification

This correction is **not** trading certification and does not authorize orders.
The 1,800-second genuine broker-event execution proof remains mandatory under
the unchanged legacy gate. Verified broker-origin execution identity, writer
lease, nonce sequence, kill-switch and circuit-breaker state, account-level
positions/exit readback, Kraken fills and fees, complete fresh three-platform
capital, and any required member-account protections must be independently
proven.

No deployment is authorized solely by this PR. The current instance still
reports `TRADE_LEDGER_V435_STORAGE_EVIDENCE backup_restore_verified=false`,
and the historical Oct 11 backup does not prove the current state was
preserved. Follow the no-restart owner-shell v441/v436/v449 recovery runbook,
preserve any verified legacy files, transfer encrypted archives to an off-host
custodian, compare source/destination SHA-256, independently test isolated
restoration, and record private receipts. Do not upload archives to GitHub or
issue comments or restart merely to install a fix.

After independent security and broker-integration review, verified current
off-host recovery evidence, and all required CI checks pass, a controlled
release may be considered. Inspect new `CAPITAL_PIPELINE_SUBSTAGE_V142` records
for persistent `csm_ingest` stalls and timeouts. If it still stalls, inspect
the v170 canonical identity and capital-authority lock boundaries in a
separate reviewed change. Never extend stale publication expiry or treat
mere connectivity or intermediate zero-contributor refresh results as capital.

Live trading observation remains **NOT STARTED** until all live authority,
protection and reconciliation gates independently pass.
