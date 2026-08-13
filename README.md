# NIJA AI Trading LLC — Production Success & Recovery Anchor

**Status date:** August 13, 2026

**Known-good deployed checkpoint:** `666ef8893dd491bcd2e52acb6cae8291e61d780e`

**Runtime generation observed healthy:** `3774`

This README is the durable recovery anchor for NIJA. Its purpose is to make it possible to return production to the current known-good state if a future deployment, restart, dependency change, or runtime regression breaks startup, writer authority, broker readiness, or live execution readiness.

> Important: this checkpoint proves NIJA reached and sustained `LIVE_ACTIVE`, with all canonical readiness proofs true, a live registered core thread, healthy writer authority, and all three configured platform brokers execution-ready. It does **not** yet prove a new end-to-end trade lifecycle after this recovery. Do not call the system 100/100 end-to-end verified until a real exchange order is acknowledged/filled and a later exit is also acknowledged/filled.

NIJA does not guarantee trades, fills, profits, income, or returns. Never manufacture readiness with forced activation, synthetic capital, credential bypasses, nonce bypasses, writer-lock deletion, emergency-stop bypasses, or fabricated order/fill state.

---

## 1. Current Known-Good Production State — August 13, 2026

The current production process recovered from the earlier startup/readiness failures and reached a stable live state.

### Proven runtime state

The successful runtime showed all of the following simultaneously:

```text
PREACTIVATION_READY
state=LIVE_ACTIVE
pending=[]
authority_ready=true
nonce_ready=true
writer_authority=confirmed
blockers_cleared=true
current_proofs=true
```

The readiness table was fully true:

```text
broker_connected=True
balance_hydrated=True
authority_ready=True
capital_ready=True
risk_ready=True
strategy_ready=True
execution_ready=True
nonce_ready=True
bootstrap_ready=True
```

Writer authority was healthy and tied to the real core thread:

```text
WRITER_LOCK_RENEWED
writer_generation=3774
core_thread_alive=True
core_thread_registered=True
core_thread_reason=ok
```

Repeated activation reconciliation correctly reported:

```text
ACTIVATION_SINGLE_FLIGHT_RESULT
ok=True
reason=already_live
state_before=LIVE_ACTIVE
```

The main process also reported:

```text
BOT_MAIN_KEEPALIVE_HEARTBEAT
startup_complete=True
writer_authority=True
TradingLoop
```

### Three-venue execution readiness

All three configured platform venues were authenticated, funded, and eligible in the successful runtime:

```text
THREE_VENUE_STAGE venue=kraken ... marked_ready=True eligible=True activation=ready
THREE_VENUE_STAGE venue=coinbase ... marked_ready=True eligible=True activation=ready
THREE_VENUE_STAGE venue=okx ... marked_ready=True eligible=True activation=ready
BROKER_INDEPENDENT_EXECUTION_READY ... all_venues_ready=True execution_enabled=True
THREE_VENUE_EXECUTION_READY ... kraken=True coinbase=True okx=True execution_enabled=True
```

Observed live spendable values in one successful readiness window were approximately:

```text
kraken   154.49
coinbase  95.12
okx      144.96
```

A separate live CapitalAuthority refresh in the same recovered generation showed total portfolio authority around `$467.20` across three connected brokers. Treat balances as dynamic; use current live exchange observations, not these historical numbers, when validating a future recovery.

---

## 2. What Is Still Awaiting Final End-to-End Confirmation

NIJA is currently proven **live and execution-ready**, but the August 13 recovery evidence has not yet shown a complete new entry/exit lifecycle after recovery.

Before calling this checkpoint **100/100 end-to-end verified**, capture real broker evidence for:

1. Strategy/risk decision reaches execution.
2. Order request reaches the selected broker adapter.
3. Exchange returns an order ID / txid / broker acknowledgment.
4. Entry order reaches a confirmed fill state.
5. Position is visible in broker reconciliation.
6. Exit protection tracks the position.
7. Exit order reaches the broker.
8. Exchange acknowledges the exit.
9. Exit reaches confirmed fill/closed state.
10. Position and PnL reconciliation agree with the broker after closure.

Do **not** treat any of the following by itself as proof of a real trade:

```text
LIVE_ACTIVE
execution_ready=True
TRADE DECISION final_decision=EXECUTE
PIPELINE_STAGE risk_governor status=passed
stage=FILL_VERIFY on the authority heartbeat marker
```

The authority-heartbeat `FILL_VERIFY` label refers to heartbeat marker verification, not exchange trade fills.

---

## 3. Canonical Production Startup Path

The production startup path remains:

```text
scripts/production_bootstrap.sh
    -> start.sh
    -> scripts/canonical_runtime_launcher_v26.py
    -> main.py
    -> bot.bot
    -> bot.bot_main
```

The canonical high-level startup order is:

1. Install runtime safety/convergence patches.
2. Acquire the single-writer lease and fencing generation.
3. Start writer and authority heartbeat supervision.
4. Establish nonce protection.
5. Prepare the canonical broker runtime.
6. Hydrate live broker balances and capital authority.
7. Complete SelfHealingStartup.
8. Advance BootstrapFSM toward thread startup.
9. Publish the canonical strategy.
10. Start the real trading engine/core thread.
11. Register that exact live thread with writer authority.
12. Reach `RUNNING_SUPERVISED`.
13. Complete post-core readiness convergence.
14. Only then allow the normal activation path to hold `LIVE_ACTIVE`.

Do not pre-grant or synthesize any of these:

```text
authority_ready
nonce_ready
strategy_ready
execution_ready
bootstrap_ready
NIJA_RUNTIME_EXECUTION_AUTHORITY
LIVE_ACTIVE
```

---

## 4. Exact Recovery Checklist

If NIJA regresses, restore using this checklist in order. Do not skip ahead by forcing later readiness states.

### A. Confirm deployment identity

Known-good checkpoint:

```text
666ef8893dd491bcd2e52acb6cae8291e61d780e
```

A newer commit may be valid, but when debugging compare its runtime behavior against this checkpoint.

Expected release evidence:

```text
NIJA_RUNTIME_RELEASE_MANIFEST ... deployment_sha=<expected sha> ready=true
```

### B. Confirm writer authority

Healthy evidence:

```text
WRITER_LOCK_RENEWED
WRITER_STATE_TRANSITION ... state=ACTIVE
HEARTBEAT_REFRESH
HEARTBEAT_CHECK ... healthy=True authoritative=True
```

Healthy core attachment must show:

```text
core_thread_alive=True
core_thread_registered=True
core_thread_reason=ok
```

If the core is not registered/alive, stop diagnosis there. Do not force authority or execution readiness.

### C. Confirm canonical readiness table

The target known-good table is:

```text
broker_connected=True
balance_hydrated=True
authority_ready=True
capital_ready=True
risk_ready=True
strategy_ready=True
execution_ready=True
nonce_ready=True
bootstrap_ready=True
```

Then v61 should report:

```text
PREACTIVATION_READINESS_V61_TRUTH_SYNC ... state=LIVE_ACTIVE ... pending=[]
PREACTIVATION_READY ... writer_authority=confirmed blockers_cleared=true current_proofs=true
```

### D. Confirm three platform brokers

Expected configured live platform venues:

```text
kraken
coinbase
okx
```

Healthy execution readiness should show each venue ready plus:

```text
BROKER_INDEPENDENT_EXECUTION_READY ... execution_enabled=True
THREE_VENUE_EXECUTION_READY ... execution_enabled=True
```

A degraded optional venue should fail closed/isolate itself rather than fabricate global readiness.

### E. Confirm main/core runtime

Healthy evidence:

```text
BOT_MAIN_KEEPALIVE_HEARTBEAT startup_complete=True writer_authority=True
TradingLoop
BrokerWorker-kraken
BrokerWorker-coinbase
BrokerWorker-okx
```

### F. Confirm activation remains stable

Repeated activation requests after recovery should be idempotent:

```text
ACTIVATION_SINGLE_FLIGHT_RESULT ... ok=True reason=already_live state_before=LIVE_ACTIVE
```

If repeated activation instead revokes proofs or returns to `LIVE_PENDING_CONFIRMATION`, identify the first false proof rather than forcing activation.

### G. Confirm actual execution separately

Only exchange/broker evidence counts as proof of a trade. Look for order submission followed by broker acknowledgment and fill evidence such as an exchange order ID/txid and confirmed filled/closed status.

Do not infer fills from signals, scans, risk approval, or execution readiness.

---

## 5. Recovery Decision Tree

### Case 1 — `LIVE_PENDING_CONFIRMATION`, core not registered

Typical blockers:

```text
core_registered=False
core_alive=False
bootstrap_state=<not RUNNING_SUPERVISED>
```

Action:

- Verify `bot.bot_main` is progressing through the canonical startup sequence.
- Verify canonical broker prebootstrap returned control to `bot_main`.
- Do not weaken v61, writer fencing, nonce rules, risk rules, or kill-switch behavior.
- Do not set `_startup_complete` early.
- Do not fabricate a core thread or mark it registered unless the real thread is alive.

### Case 2 — writer renews but readiness is false

Action:

- Find the first false proof in the readiness table.
- Verify writer generation/token are current.
- Verify heartbeat authority.
- Verify nonce authority.
- Verify broker/capital freshness.
- Let v61 remain fail-closed until every proof is true.

### Case 3 — `EMERGENCY_STOP`

Action:

- Determine the actual stop reason first.
- Never clear operator, kill-switch, loss, liquidation, panic, drawdown, or unknown emergency stops automatically.
- Heartbeat-origin stale-stop recovery is allowed only through the narrow existing recovery path after current writer proof and explicit kill-switch-clear proof.

### Case 4 — live and ready, but no orders

Action:

- Do not modify startup/authority code merely because there is no trade.
- Inspect strategy signals, TPE decision, market-data sufficiency, volume/spread filters, risk governor, exchange minimums, and the execution path after `final_decision=EXECUTE`.
- A lack of valid signals or risk-approved opportunities is not a startup failure.

### Case 5 — `EXECUTE` decision but no broker ACK

Action:

- Trace execution from the final strategy/risk decision into the broker router.
- Confirm selected broker is still connected and execution eligible.
- Confirm order request actually reached the adapter.
- Require broker response evidence before classifying the event as submitted/rejected/filled.
- Do not convert generic false/none returns into fake exchange rejections or fills.

### Case 6 — entry fills but exit does not

Action:

- Verify broker-native position reconciliation.
- Verify cost basis/entry price is trustworthy.
- Verify automatic exit supervisors are registered for that broker/account.
- Verify the exit request reaches the broker and receives acknowledgment.
- Never invent an exit fill or manually mark the position closed without exchange evidence.

---

## 6. Current Recovery/Hardening Milestones

The August recovery sequence that led to the current successful runtime includes these important merged checkpoints:

```text
PR #2504  Fix writer readiness convergence for live activation
merge: 1bf87084ff1c57e0d41bd824e7a92507ee47dae8

PR #2505  Kraken user reconnect hardening
merge: d1baa21c34777727c332ab655431f76d5b544ce9

PR #2506  Generic-false execution circuit-breaker convergence (v88)
merge: 935fb4f90d90f3e46c82a6211e7c3e921ff7fd0a

PR #2507  Kraken reconnect liveness regression coverage
merge: d1721fc55b26417c878f5ecf79fc4bb3c54155a8

PR #2508  Recover stale heartbeat-origin emergency stop after authority returns
merge: 26254d1614533d5a84a575239534e07a6f65ca28

PR #2509  Document fail-closed prebootstrap core handoff repair
merge: 666ef8893dd491bcd2e52acb6cae8291e61d780e
```

Important distinction: PR #2509 was documentation only. The successful production runtime on `666ef889...` therefore proves the runtime recovered without the proposed v94 production handoff change being applied. Do not assume that proposal is required unless a future regression reproduces the canonical prebootstrap stall and the change is separately reviewed and approved.

---

## 7. Safety-Critical Contracts That Must Not Be Weakened

The following remain non-negotiable recovery constraints:

- Single-writer fencing remains authoritative.
- Writer generation/token must be current.
- Nonce protection remains fail-closed.
- Real broker credentials/authentication are required.
- Capital must come from current broker-backed observations.
- Risk governor remains in the execution path.
- Kill switch and genuine emergency stops remain authoritative.
- Core thread readiness must describe the actual real thread.
- `LIVE_ACTIVE` must come only through the canonical state machine.
- Order submission/fill state must come from broker/exchange evidence.
- User accounts must not be marked connected/funded without real proof.
- Do not disable circuit breakers or safety supervisors just to increase trade frequency.

---

## 8. Current Live Broker Contract

NIJA's active platform crypto execution runtime uses:

| Venue | Endpoint / role | Current recovery expectation |
|---|---|---|
| Kraken | Primary supported platform venue | Authenticated, funded, nonce-ready, execution eligible |
| Coinbase Advanced Trade | Independent platform venue | Authenticated ECDSA/CDP credentials, funded, execution eligible |
| OKX US | Independent platform venue | `https://us.okx.com`, authenticated, funded, execution eligible |

Brokerage balances, positions, risk state, and orders remain independent. Do not merge one venue's available cash into another venue's execution budget.

Recommended credential permissions are read/query + trade only. **Do not enable withdrawals.**

---

## 9. Non-Blocking Conditions Seen in the Successful Runtime

These were observed while NIJA remained healthy and `LIVE_ACTIVE`:

```text
DATA_FAILURE_QUARANTINE for symbols with insufficient candle history
VOLUME_TOO_LOW ... decision=BLOCK
BrokerWorker scan TIMED OUT after 5.0s ... Broker available for next cycle
SCAN_GUARD_WAITING
```

These conditions can reduce opportunities or slow individual scan cycles, but they are not automatically startup/readiness failures.

Investigate them if they become persistent enough to prevent all valid execution opportunities, but do not weaken live safety gates to compensate.

---

## 10. Definition of 100/100 Verified Success

NIJA may be called **100/100 verified end-to-end** only when all of the following have been observed in the same current production lineage:

- [x] Canonical deployment starts.
- [x] Writer lease acquired and continuously renewed.
- [x] Writer heartbeat authoritative.
- [x] Real core thread alive and registered.
- [x] `startup_complete=True`.
- [x] Kraken ready.
- [x] Coinbase ready.
- [x] OKX ready.
- [x] Live broker-backed capital hydrated.
- [x] All readiness table proofs true.
- [x] `PREACTIVATION_READY` with no blockers.
- [x] `LIVE_ACTIVE` stable.
- [x] Strategy/trading loop running.
- [x] Execution authorization active through the normal path.
- [ ] New live order receives real exchange acknowledgment/order ID.
- [ ] New live entry reaches confirmed exchange fill.
- [ ] Position reconciliation confirms the entry.
- [ ] Automatic exit path triggers under a valid exit condition.
- [ ] Exit order receives real exchange acknowledgment/order ID.
- [ ] Exit reaches confirmed exchange fill/closed state.
- [ ] Final broker position/PnL reconciliation confirms closure.

Until the unchecked items are proven, the correct status is:

> **NIJA is live, fully ready, and authorized to execute; end-to-end entry/fill/exit confirmation is still pending.**

---

## 11. When Everything Is Working

If the runtime shows the known-good state above, **do not keep patching production simply because no trade has occurred yet**.

Wait for a valid market opportunity. Change code only when logs show a concrete defect such as:

```text
execution decision reaches EXECUTE but never reaches broker adapter
broker returns a real rejection that is mishandled
order is acknowledged but fill state is lost
position is filled but reconciliation misses it
exit supervisor fails to submit a valid exit
exit is acknowledged/filled but position state is not reconciled
writer/core/readiness state regresses from current truth
```

Preserving a proven working live runtime is safer than continuously modifying it without evidence of a defect.

---

## Official NIJA Links

- **Website:** https://nijaaitrading.com
- **Mobile documentation:** `mobile/README.md`
- **Owner:** NIJA AI Trading LLC

## Disclaimer

NIJA AI Trading is not financial advice. Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.
