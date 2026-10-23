# Capital runtime-FSM timeout substage diagnostic handoff

October 22, 2026 (PDT). Scoped to Render service `srv-d98dsr5aeets73fpbaqg`, release `release/justcall-handoff-only-20261017` at SHA `6f05e89a71b6dcbbf5c5dfc59db8e3828e70842a`.

## Reproduced production observations (read-only)

- The v142 coordinator repeatedly expired generations after **50–80 seconds**, with `stage_hint=runtime_fsm`, while previous accepted broker-capital snapshots could still appear current.
- v270 logged `registered=3 connected=3 valid_brokers=0` and `upstream_refresh_pending` for overlapping/failed refresh results. That intermediate result is **not** a complete three-broker snapshot.
- The capital authority publication TTL and v142 retired-generation fence correctly prevented stale worker completions from being treated as current capital. Do **not** weaken or suppress those denials.
- `execution_ready=false` and `execution_authority=false`. The pre-trade evidence source remained uninstalled/unconfigured in production. None of the capital observations proves `LIVE_ACTIVE`.

The existing `runtime_fsm` breadcrumb covered `CapitalRuntimeStateMachine.transition`, `on_snapshot_received`, and CSM-v2 snapshot ingest. This PR narrows the diagnostic phase to distinguish those operations; it does not infer which of these actually caused the production stall without new deployed data.

## Source changes

- Retain the old `runtime_fsm` breadcrumb and add **fixed** labels `runtime_transition`, `snapshot_received`, `csm_ingest`. Log bounded, non-secret start/done records and elapsed milliseconds in the existing coordinator worker; no additional broker calls, publication writes, refreshes, or new threads.
- Extend only the v142 allowlisted stage-hint vocabulary. Preserve exact-worker attribution, static labels, frame safety, 50/80-second deadlines, single-flight serialization, retired-generation fence, and the immutable CapitalAuthority TTL.
- Add offline stage-sequence and worker-identity tests; include changed runtime and test files in the recovery workflow's compile, secret scan, and pytest jobs.

## Post-review release / evidence requirements

1. Complete CI, CodeQL, secrets and independent broker/security review, plus current off-host backup/isolated restore verification before deployment. Do not restart or redeploy just to clear a denial.
2. Review new `CAPITAL_PIPELINE_SUBSTAGE_V142` records alongside the matching `CAPITAL_RUNTIME_PIPELINE_V142_TIMEOUT` generation to see which substage started but did not complete. If it is `runtime_transition`, examine FSM lock owners; if `snapshot_received`, examine capital authority and transition/status contention; if `csm_ingest`, examine CA read/CSM state lock. Never infer a lock failure from one marker alone.
3. Implement the *actual* producer/concurrency fix in a separately reviewed PR once the blocked operation and its owner are evidenced. Demonstrate consecutive fully current broker snapshots, generation ownership and no repeated timeout before any re-authorization work.
4. Independently certify per-account broker/ledger/fee reconciliations, genuine protective exits, signed writer/nonce authority, verified off-host backup, and the reviewed pre-trade admission hook. Preserve genuine post-trade 1,800-second broker-event verification and fail-closed historical evidence. No test orders.

No production or trading-authority change is included in this PR. Do not start or claim the 24-hour observation.
