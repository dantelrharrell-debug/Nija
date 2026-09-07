# NIJA AI Trading LLC — Current Success State & Recovery Anchor

**Status date:** September 7, 2026 (UTC)

**Preferred current recovery checkpoint:** `3b48c533d191d8ce81d2166b14d3ef0946600c92`

**September 7 v382 verified hardening candidate:** `b003b7a0faa9bea9a68b884f3b4460a05bbf7608`

**September 7 candidate writer generation:** `5472`

**September 7 candidate instance:** `srv-d98dsr5aeets73fpbaqg-rhv5q`

**Kraken ECEL exit-symbol repair parent:** `09f13a0f2b4f189e7fb76de0cdb0035552f9b8ed`

**Verified production writer generation for preferred recovery anchor:** `5460`

**Verified production instance for preferred recovery anchor:** `srv-d98dsr5aeets73fpbaqg-xdvzm`

**Immutable August 22 explicit-gate checkpoint:** `740c98dc94374bb1ed770ff96a5eafabfd32681b`

**Immutable recovery branch:** `recovery/100-prod-readiness-20260822`

This README is the durable production and recovery anchor for **Nija_Trading_Bot**. Its purpose is to make it possible to return to the September 6 verified success state without forcing trades, weakening safety controls, fabricating readiness, or reintroducing the heartbeat duplicate-order problem.

The September 7 v382 deployment is documented separately as a verified hardening candidate. It has proved writer acquisition, canonical installer wiring, metadata-only authority epoch stability, live capital hydration, Kraken execution-proof recovery without a new order, and preserved safety gates. It has **not yet replaced the September 6 preferred recovery checkpoint** because the fresh generation-5472 process had not yet independently re-proven the full `STARTUP_VALIDATED -> core registered -> position_sync_ready -> EXECUTION_ALLOWED -> LIVE_ACTIVE -> live scan` chain at the time of this update.

NIJA does not guarantee trades, fills, profits, income, or returns. A healthy live system may correctly submit no order when market, risk, liquidity, capital, broker-minimum, position, or safety gates reject all candidates.

---

## 1. September 6, 2026 — Preferred Verified Success Point

The preferred repository recovery checkpoint is:

```text
commit=3b48c533d191d8ce81d2166b14d3ef0946600c92
short_commit=3b48c53
date=2026-09-06
change=Harden restart proof broker and writer discovery
```

This checkpoint includes the September 6 restart-proof recovery hardening and contains the prior Kraken ECEL symbol-normalization repair from:

```text
09f13a0f2b4f189e7fb76de0cdb0035552f9b8ed
```

The production runtime was then verified on writer generation:

```text
writer_generation=5460
writer_token_prefix=4147
instance=srv-d98dsr5aeets73fpbaqg-xdvzm
```

This is now the **preferred recovery target** because it proved all of the following in one fresh Render container after a clean writer handoff:

- authenticated Kraken execution-proof recovery after restart,
- no new heartbeat/test order required,
- authoritative position reconciliation,
- bootstrap advancement through `STARTUP_VALIDATED` and `CAPITAL_READY`,
- canonical core registration,
- writer authority held and renewed,
- `EXECUTION_ALLOWED: TRUE`,
- `LIVE_ACTIVE`,
- execution authority ready,
- live trading loop reached first tick,
- live market scan completed,
- signals generated and candidates evaluated,
- unsafe/undersized entries blocked by the normal risk path,
- exit supervision active,
- Kraken ECEL native-symbol normalization installed,
- safety gates preserved.

Do not replace this recovery anchor merely because a later commit exists. Promote a newer checkpoint only after the same complete evidence chain is independently re-proven.

---

## 1A. September 7, 2026 — Authority Epoch Stability v382 Hardening

The September 7 repair addresses a separate runtime-stability defect that appeared **after** the bot had already reached `LIVE_ACTIVE`: the canonical dispatch commit could repeatedly fall from a positive commit version to `0`, after which the existing v92 repair rebuilt it.

### Root cause

`StartupCoordinator.record_authority()` treated both of these as safety-authority changes:

1. an actual boolean authority truth change (`ready=True <-> False`), and
2. a diagnostic `authority_status` dictionary change while `ready` remained the same.

Healthy publishers legitimately report different metadata dictionaries, for example:

```text
ready=True status={'source': 'authority_heartbeat'}
ready=True status={'current_state': 'LIVE_ACTIVE'}
```

Before v382, that metadata-only alternation could advance `global_epoch` and revoke the canonical activation commit even though authority had never become false.

### v382 safety semantics

The repair keeps metadata observable while restoring correct edge-trigger semantics:

```text
metadata-only status change:
  authority_version increments
  AUTHORITY_REFRESHED remains published
  global_epoch does NOT advance
  activation commit is preserved

actual authority truth change:
  authority_version increments
  global_epoch advances
  prior activation commit is revoked
  runtime remains fail-closed until canonical gates reconverge
```

No kill-switch, nonce, dispatch-health, capital, position, risk, execution-proof, minimum-order, ACK, fill, or protective-exit gate is weakened.

### Commit lineage

The September 7 hardening lineage is:

```text
3fa52ef5b28251c971735142363623b2f4fd9a07  Harden authority status epoch stability
be59020c5539fd1dfaec74c9557369dec7dcdce9  Add focused metadata-preserve / authority-loss tests
38230c81e73a9587f82de500e1cc3c2b3aba5d24  Initial pre-bot wiring
4b39d9c5bc8358735a26d52fd406c64d6ec55211  Source/heartbeat-scope wiring hardening
b003b7a0faa9bea9a68b884f3b4460a05bbf7608  Canonical launcher wiring used by production
```

`b003b7a0faa9bea9a68b884f3b4460a05bbf7608` is the first September 7 candidate that production proved was installing v382 from the actual canonical runtime launcher before `StartupCoordinator` import.

### Production proof on generation 5472

The replacement container waited for the prior Render writer to exit and for the Redis lease TTL to expire normally. The lock was **not** force-cleared. It then acquired:

```text
WRITER_LOCK_ACQUIRED
writer_generation=5472
writer_token_prefix=4159
instance=srv-d98dsr5aeets73fpbaqg-rhv5q
```

The canonical front door attested the guard:

```text
CANONICAL_AUTHORITY_STATUS_EPOCH_V382_READY
marker=20260907-authority-status-epoch-stability-v382
status_metadata_noninvalidating=true
authority_truth_edge_invalidating=true
forced_activation=false
safety_gates_bypassed=false
```

After the coordinator loaded, the class itself was patched:

```text
AUTHORITY_STATUS_EPOCH_STABILITY_V382_PATCHED
status_metadata_noninvalidating=true
authority_truth_edge_invalidating=true
forced_activation=false
safety_gates_bypassed=false
```

A real metadata-only authority refresh then exercised the repaired path:

```text
AUTHORITY_STATUS_METADATA_STABLE_V382
ready=True
authority_version=2
global_epoch=3
commit_version=0
status_keys=['source']
commit_preserved=true
safety_gates_preserved=true
```

The commit version was still `0` in that line because the fresh replacement had **not yet earned its first activation commit**. The important proof is that the metadata-only update did not revoke or mutate the commit latch and explicitly reported `commit_preserved=true`.

### Execution proof recovered without a verification order

The fresh generation-5472 runtime recovered a genuine historical Kraken fill:

```text
CANONICAL_FILL_EXECUTION_PROOF_V346_RECORDED
order_id=OOB2WA-467F2-AMNXTN
symbol=XETHZUSD
side=sell
fill_price=2517.3808304423
filled_usd=57.41179000
source=canonical_confirmed_fill
execution_proof_fabricated=false
safety_gates_bypassed=false
```

Then:

```text
EXECUTION_PROOF_RESTART_V346_RECOVERED
order_id=OOB2WA-467F2-AMNXTN
writer_generation=5472
authenticated_history=true
exact_order_id=true
final_status=true
positive_fill_quantity=true
positive_fill_cost=true
no_order_submitted=true
heartbeat_trade_required=false
execution_proof_fabricated=false
safety_gates_bypassed=false
```

The live heartbeat order runner remained explicitly prevented from placing a capital-bearing verification order:

```text
HEARTBEAT_RUNNER_V374_STOPPED
reason=NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS_false
capital_bearing_retry_loop=false
order_submitted=false
read_only_execution_proof_recovery_preserved=true
```

### Current candidate state when this README was updated

The generation-5472 process had current Kraken capital and platform connectivity, including approximately:

```text
Kraken capital=$207.07
capital snapshot accepted=true
Capital CSM READY
platform Kraken connected=true
platform Coinbase connected=true
```

However, full production success had **not** yet been re-certified because current readiness still showed:

```text
ACTIVATION_COMMIT_V116_PENDING
pending=['bootstrap_ready', 'position_sync_ready']
direct_live_bypass=false

RUNTIME_AUTHORITY_CONVERGENCE_WAITING
detail=core_thread_not_alive:startup_not_complete

WRITER_LOCK_RENEWED
generation=5472
core_thread_alive=False
core_thread_registered=False
core_thread_reason=startup_not_registered
```

and the latest Kraken position-sync freshness path had temporarily returned:

```text
POSITION_SYNC_V96_READINESS
ready=false
pending=['platform:kraken']
activation_blocked=true
```

That is the correct fail-closed behavior. **Do not force `LIVE_ACTIVE`, fabricate `position_sync_ready`, or mark b003 as the preferred rollback checkpoint until the full success chain is re-proven on a fresh process.**

---

## 2. Exact Proof That the September 6 Recovery Worked

### Writer and canonical core

The fresh process acquired and continuously renewed the single-writer lease:

```text
WRITER_LOCK_RENEWED
generation=5460
token_prefix=4147
core_thread_alive=True
core_thread_registered=True
core_thread_reason=ok
```

The trading core registered successfully:

```text
CORE_THREAD_REGISTRATION_SUCCEEDED
thread=TradingLoop
generation=5460

CANONICAL_CORE_THREAD_REGISTERED
thread=TradingLoop
writer_generation=5460

WRITER_STATE_TRANSITION
state=ACTIVE
reason=core_thread_registered
```

Never delete, bypass, or manually fake the writer lease to recover faster. A second container must remain fail-closed until the active writer releases the lease.

### Bootstrap convergence

The fresh container naturally crossed the bootstrap states:

```text
BootstrapFSM SNAPSHOT_EVALUATING -> READY
BootstrapFSM LOCK_ACQUIRED -> HEALTH_BOUND
BootstrapFSM CAPABILITY_VERIFIED -> STARTUP_VALIDATED
BootstrapFSM STARTUP_VALIDATED -> CAPITAL_REFRESHING
BootstrapFSM CAPITAL_REFRESHING -> CAPITAL_READY
```

The successful live capital snapshot observed in this window was approximately:

```text
capital=$274.52
valid_brokers=3
```

That dollar amount is historical evidence, not a recovery target. Recovery must always use current broker-backed balances.

### Authoritative position synchronization

Kraken position sync ultimately completed successfully:

```text
EXCHANGE_POSITION_SYNC
broker=platform:kraken
fetched=1
reconciled=0
unchanged=1
marked_synced=True

PLATFORM_POSITION_SYNC_V108_COMPLETE
broker=kraken
synced=true
fetch_ok=True
```

Coinbase and OKX were also brought through the platform startup/reconciliation path. Temporary read contention or a retry is not by itself a failure; final authoritative sync is what matters.

### Genuine execution proof recovered after restart

The key September 6 repair is that a fresh Render container can rebuild execution proof from authenticated Kraken history instead of placing another test order.

The verified historical Kraken order was:

```text
order_id=OKOA5D-5TKGR-VEXQCF
symbol=XETHZUSD
side=buy
status=closed
fill_price=2509.9899968411
filled_usd=28.60485000
```

The runtime proved it through the canonical verifier:

```text
CANONICAL_FILL_EXECUTION_PROOF_V346_RECORDED
order_id=OKOA5D-5TKGR-VEXQCF
source=canonical_confirmed_fill
proof_kind=execution_probe
ack_alone_not_proof=true
execution_proof_fabricated=false
safety_gates_bypassed=false
```

Then the restart recovery succeeded:

```text
EXECUTION_PROOF_RESTART_V346_RECOVERED
order_id=OKOA5D-5TKGR-VEXQCF
writer_generation=5460
authenticated_history=true
exact_order_id=true
final_status=true
positive_fill_quantity=true
positive_fill_cost=true
no_order_submitted=true
heartbeat_trade_required=false
execution_proof_fabricated=false
safety_gates_bypassed=false
```

This is the preferred restart behavior.

**Do not re-enable heartbeat trading merely to recreate execution proof if authenticated history can recover it.**

### Canonical readiness and live activation

After the core registered, the readiness proof converged with no pending blockers:

```text
proofs={
  broker_connected: True,
  balance_hydrated: True,
  authority_ready: True,
  capital_ready: True,
  risk_ready: True,
  strategy_ready: True,
  execution_ready: True,
  nonce_ready: True,
  bootstrap_ready: True
}
pending=[]
```

The runtime then emitted:

```text
EXECUTION_ALLOWED: TRUE
```

and transitioned normally:

```text
LIVE_PENDING_CONFIRMATION -> LIVE_ACTIVE
LIVE_STATE_ENTERED state=LIVE_ACTIVE
ACTIVATION_COMMITTED — LIVE_ACTIVE confirmed
ACTIVATION_SUCCESS
```

The dispatch epoch was re-anchored without weakening gates:

```text
LIVE_ACTIVE_ACTIVATION_EPOCH_REANCHORED
canonical_proof_passed=true
safety_gates_preserved=true

LIVE_ACTIVE_DISPATCH_COMMIT_REPAIRED
runtime_authority=EXECUTING
safety_gates_preserved=true
```

Finally:

```text
EXECUTION_AUTHORITY_READY
writer_generation=5460
convergence_ok=True

EXIT_SUPERVISION_ACTIVE

TRADING LOOP ACTIVE — FIRST TICK REACHED
MARKET_SCAN_STARTED cycle=1
TRADE LOOP HEARTBEAT: active=True
```

That is the canonical September 6 success state.

---

## 3. Live Scan Proof — Trading Ready Does Not Mean Force a Trade

The verified live cycle completed with the bot active and permitted to execute:

```text
NIJA_CYCLE_TELEMETRY
runtime_state=LIVE_ACTIVE
execution_authority=1
market_data_healthy=True
new_entry_allowed=True
```

One completed scan showed:

```text
symbols_scanned=45
signals_generated=26
entry_candidates=3
orders_attempted=0
orders_submitted=0
orders_accepted=0
fills_received=0
```

The cycle accounting showed:

```text
candidates_selected=3
orders_submitted=0
fills=0
```

The candidates were not ordered because the normal Kraken minimum-notional risk gate rejected the computed position size:

```text
BROKER_MIN_NOTIONAL_BLOCK
broker=kraken
required=$23.10
computed_min_size=$5.49
```

Additional candidate logging showed the same safety conclusion before `execute_action`:

```text
ENTRY BLOCKED: insufficient capital for this strategy
signal will NOT reach execute_action this cycle
```

This is **correct live trading behavior**. Do not lower the Kraken minimum, weaken sizing, bypass risk, or force an order simply to make the logs show a trade.

---

## 4. Heartbeat / Verification Trade Safety Contract

During the September 6 investigation, heartbeat verification was temporarily enabled to establish a real broker execution path. Kraken private-read contention caused acknowledgments to arrive later than the heartbeat runner expected, which allowed retries and duplicate small buys before success was recognized.

After genuine live fills were proven, heartbeat trading was intentionally disabled again.

The preferred production environment state is:

```text
HEARTBEAT_TRADE=false
NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false
```

Keep these disabled during normal recovery unless there is a separately reviewed reason to perform a new live verification trade.

If execution proof is missing after restart, first use the authenticated-history recovery path in the September 6 checkpoint. Do **not** blindly re-enable heartbeat orders.

Never solve a proof problem by:

- lowering the ACK/fill standard to acknowledgment-only proof,
- fabricating an order id,
- treating a balance or position as fill proof,
- setting readiness flags manually,
- forcing `LIVE_ACTIVE`,
- bypassing writer/nonce/risk/capital/position gates.

---

## 5. Kraken ETH Position / Cost-Basis Recovery

The platform Kraken ETH position was authoritatively synchronized as:

```text
symbol=ETH-USD
quantity=0.02280640
```

The trusted cost basis was later recovered from broker trade history:

```text
KRAKEN_COST_BASIS_V288_VERIFIED
account=PLATFORM
symbol=ETH-USD
entry_price=2506.77110913
source=bulk_trade_history
broker_history_required=true
synthetic_entry=false
current_price_fallback=false
safety_gates_bypassed=false
```

The position then synchronized with:

```text
entry=$2506.77110913
qty=0.02280640
entry_source=trade_history
cost_basis_verified=True
```

Profit targets were applied without replacing existing protections:

```text
ALL_ACCOUNT_PROFIT_TARGETS_V239_APPLIED
symbol=ETH-USD
side=long
entry=2506.77110913
quantity=0.02280640
synthesized=take_profit_1,take_profit_2,take_profit_3
existing_targets_preserved=true
fee_aware_floor_preserved=true
```

Never invent or substitute a current market price as cost basis just to unblock automatic exits.

---

## 6. Kraken ECEL Exit-Symbol Repair — Must Remain Installed

A separate protection defect was found during this recovery: a Kraken ETH exit could reach ECEL as the Kraken-native symbol:

```text
XETHZUSD
```

instead of NIJA's canonical:

```text
ETH-USD
```

That caused a legitimate exit path to be rejected as `NO_CONTRACT_RULE` even though the `ETH-USD` rule already existed.

The existing v206 canonicalizer already knew the correct mapping, but its installer was chained behind an unrelated heartbeat re-arm path. The September 6 repair decoupled the canonicalizer so the exit-safety mapping installs independently.

The repair parent is:

```text
09f13a0f2b4f189e7fb76de0cdb0035552f9b8ed
```

and it is contained in the preferred checkpoint:

```text
3b48c533d191d8ce81d2166b14d3ef0946600c92
```

Expected proof marker on a healthy runtime:

```text
KRAKEN_ECEL_SYMBOL_V206_READY
```

Expected canonical behavior:

```text
XETHZUSD -> ETH-USD
```

Do not add a duplicate ECEL contract merely to accommodate `XETHZUSD`. Preserve canonical normalization and use the existing `ETH-USD` rule.

---

## 7. Exact Recovery Procedure to Return to This Success State

### A. Preserve evidence first

Before changing code or redeploying, save the failing production logs and identify the **first false proof**. Do not patch based only on the last downstream error.

### B. Restore the preferred code checkpoint when a code rollback is actually required

Preferred checkpoint:

```text
3b48c533d191d8ce81d2166b14d3ef0946600c92
```

Use the normal Git/GitHub and Render deployment path. Do not rewrite or delete writer state to accelerate handoff.

### C. Keep verification heartbeat orders disabled

Confirm:

```text
HEARTBEAT_TRADE=false
NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false
```

### D. Let the new container acquire writer authority normally

A replacement container may remain in fail-closed standby while the old writer holds the Redis lease. This is correct zero-downtime behavior.

Wait for a clean sequence equivalent to:

```text
old writer receives SIGTERM
old trading engine stops cleanly
old writer releases lease
new container acquires next writer generation
```

Never force-clear the writer lock.

### E. Re-establish platform truth

Require current evidence for:

```text
Kraken connected
Coinbase connected
OKX connected
capital ready
position sync authoritative
kill switch clear
risk ready
strategy ready
```

Temporary retries are acceptable. Final current truth must converge.

### F. Recover execution proof without a new trade

Preferred proof:

```text
EXECUTION_PROOF_RESTART_V346_RECOVERED
authenticated_history=true
exact_order_id=true
final_status=true
positive_fill_quantity=true
positive_fill_cost=true
no_order_submitted=true
heartbeat_trade_required=false
```

If this does not appear, diagnose writer proof, platform Kraken broker discovery, authenticated private-read serialization, and trade-history availability. Do not immediately turn heartbeat orders back on.

### G. Require the full core/readiness chain

Recovery is not complete until all of the following appear through the normal canonical path:

```text
STARTUP_VALIDATED
CAPITAL_READY
CORE_THREAD_REGISTRATION_SUCCEEDED
CANONICAL_CORE_THREAD_REGISTERED
core_thread_alive=True
core_thread_registered=True
execution_ready=True
nonce_ready=True
authority_ready=True
bootstrap_ready=True
pending=[]
EXECUTION_ALLOWED: TRUE
LIVE_ACTIVE
ACTIVATION_COMMITTED
EXECUTION_AUTHORITY_READY
TRADING LOOP ACTIVE — FIRST TICK REACHED
```

For September 7 v382 descendants, additionally require:

```text
CANONICAL_AUTHORITY_STATUS_EPOCH_V382_READY
AUTHORITY_STATUS_EPOCH_STABILITY_V382_PATCHED
```

After the first positive activation commit exists, observe metadata-only authority refreshes and confirm they do not repeatedly drive the canonical commit version to `0`. An actual authority loss must still revoke the commit and fail closed.

### H. Verify the exit stack

Require:

```text
EXIT_SUPERVISION_ACTIVE
KRAKEN_ECEL_SYMBOL_V206_READY
XETHZUSD -> ETH-USD canonicalization
```

For held positions, require trusted cost basis before basis-dependent automatic exit decisions.

### I. Verify at least one completed market scan

A healthy cycle should show real scan accounting, for example:

```text
signals_generated > 0 or a truthful no-signal result
orders_submitted may be 0
```

`orders_submitted=0` is not a failure when candidates are legitimately filtered or risk-blocked.

---

## 8. Definition of September 6 Production Success

Use this checklist before declaring Nija_Trading_Bot fully restored:

- [x] Preferred deployment/recovery lineage known.
- [x] Single writer owns the current generation.
- [x] Writer heartbeat renews successfully.
- [x] Real `TradingLoop` core thread alive and registered.
- [x] Kraken platform broker connected/authenticated.
- [x] Coinbase platform broker connected.
- [x] OKX platform broker connected.
- [x] Broker-backed capital hydrated.
- [x] Authoritative position sync completes.
- [x] Genuine historical fill recovered from authenticated Kraken history.
- [x] Exact Kraken order id verified.
- [x] Final status verified.
- [x] Positive executed quantity verified.
- [x] Positive executed cost verified.
- [x] No new order submitted merely to recreate proof.
- [x] `execution_ready=True`.
- [x] `nonce_ready=True`.
- [x] `authority_ready=True`.
- [x] `bootstrap_ready=True`.
- [x] `pending=[]`.
- [x] `EXECUTION_ALLOWED: TRUE`.
- [x] `LIVE_ACTIVE`.
- [x] Activation committed.
- [x] Execution authority ready.
- [x] Exit supervision active.
- [x] Kraken ECEL symbol normalization installed.
- [x] Live market scan starts and completes.
- [x] Risk/minimum-notional gates remain authoritative.
- [x] No safety gate is bypassed.

This is stronger than the earlier September 3 v188 README state because the September 6 runtime additionally proved `EXECUTION_ALLOWED: TRUE`, restart-proof recovery from authenticated history, a fresh writer/core startup on generation 5460, and a completed live scan on the repaired runtime.

### September 7 v382 promotion checklist

Do **not** promote `b003b7a0faa9bea9a68b884f3b4460a05bbf7608` or a descendant over the September 6 anchor until a single fresh writer generation proves all of these together:

- [x] Canonical v382 launcher marker present.
- [x] v382 patched `StartupCoordinator.record_authority`.
- [x] Metadata-only authority refresh observed with `commit_preserved=true`.
- [x] Clean writer handoff; no forced Redis lock clear.
- [x] Authenticated execution proof recovered with `no_order_submitted=true`.
- [x] Broker-backed capital hydrated.
- [ ] `STARTUP_VALIDATED` on the same fresh process.
- [ ] Real core thread registered and alive.
- [ ] Current authoritative Kraken position sync ready.
- [ ] `bootstrap_ready=True` and `position_sync_ready=True`.
- [ ] `pending=[]`.
- [ ] `EXECUTION_ALLOWED: TRUE`.
- [ ] Positive activation commit remains stable across metadata-only status changes.
- [ ] `LIVE_ACTIVE` with runtime authority `EXECUTING`.
- [ ] Live market scan completed.
- [ ] Kraken held-position protection re-verified on the fully active process.

---

## 9. Safety-Critical Contracts — Never Weaken These to Recover Faster

- Single-writer fencing remains authoritative.
- Writer generation/token must be current.
- Nonce protection remains fail-closed.
- Real broker credentials/authentication are required.
- Capital must come from current broker-backed observations.
- Complete broker aggregation rules remain truthful.
- Freshness TTLs must not be extended to hide failures.
- Stale or partial snapshots must not be promoted to current.
- Position readiness must come from authoritative broker snapshots.
- Execution proof must come from a real confirmed fill, including the authenticated-history restart path.
- ACK-only state is not fill proof.
- Risk governor remains in the execution path.
- Kraken minimum-notional enforcement remains intact.
- Kill switch and genuine emergency stops remain authoritative.
- Core-thread readiness must describe the actual live thread.
- `EXECUTION_ALLOWED` must come only through the canonical state machine/gates.
- Order submission/fill state must come from broker/exchange evidence.
- User capital must never be mixed into platform capital.
- Authority diagnostic metadata must not invalidate the safety epoch while boolean authority truth is unchanged.
- A real boolean authority loss must still invalidate the epoch and revoke the prior activation commit.
- Do not lower market-quality, risk, spread, volume, signal, or minimum-order thresholds merely to force a trade.
- Do not create duplicate exit workers that could double-sell.
- Do not create duplicate heartbeat verification trades to prove liveness.
- Absence of trades by itself is not a bug.

---

## 10. Known Transient / Non-Fatal Signals

The September 6 startup and live scan included transient messages such as:

```text
Price fetch failed for ETH-USD — Kraken API not connected
CANONICAL_STRATEGY_V124_SYMBOL_DISCOVERY_FAILED ... fallback=true
Kraken authoritative position Balance pending ... retry
```

These messages must be interpreted in context.

They are **not automatically a production failure** when current authoritative evidence simultaneously shows:

```text
Kraken authenticated private reads succeeding
platform:kraken position sync complete
writer lease renewing
core_thread_alive=True
core_thread_registered=True
LIVE_ACTIVE
execution_authority=1
market_data_healthy=True
```

A transient local/ancillary Kraken adapter price failure is different from loss of the canonical platform Kraken broker. Judge final current truth, not one isolated log line.

For the September 7 generation-5472 candidate, `position_sync_ready` and `bootstrap_ready` are currently genuine blockers, not signals to suppress. The runtime is expected to remain fail-closed until they become current and true.

---

## 11. Historical Recovery Anchors

### August 22 immutable explicit-gate baseline

```text
commit=740c98dc94374bb1ed770ff96a5eafabfd32681b
runtime_generation=4629
branch=recovery/100-prod-readiness-20260822
```

This remains an immutable historical baseline and must not be rewritten.

### September 3 v188 operational baseline

```text
commit=6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e
runtime_generation=4648
```

This remains historical context.

### September 6 preferred recovery anchor

```text
commit=3b48c533d191d8ce81d2166b14d3ef0946600c92
runtime_generation=5460
```

**This remains the preferred current recovery point.**

### September 7 v382 verified hardening candidate

```text
commit=b003b7a0faa9bea9a68b884f3b4460a05bbf7608
runtime_generation=5472
instance=srv-d98dsr5aeets73fpbaqg-rhv5q
status=verified_v382_wiring_and_partial_startup_evidence_not_yet_full_recovery_anchor
```

This candidate must not replace the September 6 anchor until the unchecked promotion criteria in Section 8 are proven on one fresh process.

If a later deployment regresses, first determine whether the cause is transient broker latency, stale state, deployment handoff, account-side behavior, market quality, or a real code defect. Roll back only when evidence supports it.

---

## 12. When Everything Is Working

When production matches the September 6 success chain, **stop patching unless a concrete defect appears**.

Do not treat these as reasons to modify core safety/readiness code by themselves:

```text
no trade yet
no valid signal
candidate below Kraken minimum notional
market quality blocked entry
volume too low
spread too wide
insufficient candle history
risk rejected a candidate
broker private-read contention recovered on retry
installer replay emitted a temporary fail-closed reset
diagnostic authority status metadata changed while authority_ready stayed true
```

Change code only when evidence shows a real defect such as:

```text
writer/core/readiness truth regresses persistently
authoritative broker sync cannot recover
execution proof cannot be rebuilt from valid authenticated history
EXECUTION_ALLOWED remains false despite all required genuine proofs
metadata-only authority refresh repeatedly revokes a positive activation commit
an EXECUTE decision never reaches the broker adapter despite passing all gates
broker acknowledgment/fill state is mishandled
position reconciliation loses a real filled position
protective exit logic rejects a valid canonical contract
XETHZUSD bypasses ETH-USD canonicalization
a legitimate protective exit cannot reach the broker
```

Preserving a proven working runtime is safer than continuously modifying it without evidence.

---

## Official NIJA Links

- **Website:** https://nijaaitrading.com
- **Mobile documentation:** `mobile/README.md`
- **Owner:** NIJA AI Trading LLC

## Disclaimer

NIJA AI Trading is not financial advice. Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.