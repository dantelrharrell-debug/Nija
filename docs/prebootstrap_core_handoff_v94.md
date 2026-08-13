# Prebootstrap Core Handoff Repair v94

## Production evidence

Deployment `26254d1614533d5a84a575239534e07a6f65ca28` acquires and renews writer generation 3771, then remains in `LIVE_PENDING_CONFIRMATION` while `bot_main` is still inside Canonical Broker Prebootstrap. Background convergence proves `broker_connected=True`, `balance_hydrated=True`, `capital_ready=True`, and `risk_ready=True`, but the real core thread is never started/registered and BootstrapFSM remains at `CAPITAL_READY`.

Observed terminal startup blockers:

- `core_registered=False`
- `core_alive=False`
- `bootstrap_state=CAPITAL_READY`
- `CORE_THREAD_REGISTRATION_PRECONDITION_FAILED ... detail=startup_not_complete`

The important sequencing fact is that `EntrypointWriterAuthority.register_core_thread()` itself does **not** require `_startup_complete`. `bot_main.main()` starts the trading engine, registers the returned real thread, advances BootstrapFSM to `RUNNING_SUPERVISED`, performs post-core activation convergence, and only then sets `_startup_complete=True`. Therefore the writer heartbeat's recovery message is a downstream symptom; the actual liveness defect is that synchronous Canonical Broker Prebootstrap prevents `bot_main` from reaching Step 3.

## Required production change

Modify `bot/canonical_broker_prebootstrap_v22.py` only. Do not change `bot_main`, v61 activation checks, writer fencing, nonce rules, kill-switch behavior, risk thresholds, or execution authorization.

In live mode, run `MultiAccountBrokerManager.initialize()` in one daemon initialization worker. The bootstrap thread may stop waiting for that worker only when **all** of these current proofs are true:

1. `NIJA_WRITER_LEASE_ACQUIRED` is truthy.
2. `NIJA_WRITER_FENCING_TOKEN` is non-empty.
3. `NIJA_WRITER_LEASE_GENERATION` parses to an integer greater than zero.
4. `_manager_contract(manager)` passes (`_fsm_initialized`, registered source, registration finalized).
5. `_platform_counts(manager)` reports at least one connected platform broker.
6. `bot.readiness_table.snapshot()` currently reports all of:
   - `broker_connected=True`
   - `balance_hydrated=True`
   - `capital_ready=True`
   - `risk_ready=True`

This is a **prebootstrap liveness handoff only**. It must not set or synthesize any of:

- `authority_ready`
- `nonce_ready`
- `strategy_ready`
- `execution_ready`
- `bootstrap_ready`
- `NIJA_RUNTIME_EXECUTION_AUTHORITY`
- `LIVE_ACTIVE`

The initializer thread may continue its remaining non-dispatch checks. `bot_main` then proceeds through the existing canonical sequence: SelfHealingStartup -> BootstrapFSM `THREADS_STARTING` -> canonical strategy publication -> `start_trading_engine(strategy)` -> exact real-thread registration -> `RUNNING_SUPERVISED` -> post-core convergence. v61 remains the sole activation guard and must continue to fail closed until every current proof is true.

If initialization finishes normally before the handoff proof, preserve existing behavior. If initialization raises, propagate the exact error and fail closed. If neither completion nor the strict handoff proof occurs within a bounded window (recommended default: 45 seconds), fail startup closed and release only this process's writer lease through the existing wrapper.

## Regression coverage

Extend `bot/tests/test_canonical_broker_prebootstrap_v22.py` with the following cases:

1. Non-live mode remains synchronous and preserves all current tests.
2. Live initialization that blocks after manager/connected-broker/readiness proof returns control from Step 0.5 without granting execution authority.
3. Missing fencing token prevents early handoff.
4. Generation zero prevents early handoff.
5. Missing manager contract prevents early handoff.
6. No connected platform broker prevents early handoff.
7. Any false broker/balance/capital/risk readiness key prevents early handoff.
8. Initialization exception still propagates and remains fail closed.
9. Bounded timeout fails closed when neither completion nor proof occurs.
10. Early handoff does not mutate authority/nonce/strategy/execution/bootstrap readiness.

## Expected production validation

After deployment, logs should show the normal writer generation followed by either normal prebootstrap completion or a v94 early-handoff marker, then:

- `STEP 1` Self-Healing Bootstrap
- BootstrapFSM reaches `THREADS_STARTING`
- canonical strategy publication succeeds
- `CORE_LOOP_STARTED`
- `CORE_THREAD_REGISTRATION_SUCCEEDED`
- `CANONICAL_CORE_THREAD_REGISTERED`
- BootstrapFSM reaches `RUNNING_SUPERVISED`

Only after those events may v61 restore `authority_ready`, `nonce_ready`, `strategy_ready`, `execution_ready`, and `bootstrap_ready`, and only the existing activation path may enter `LIVE_ACTIVE`.
