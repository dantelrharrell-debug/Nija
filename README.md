# NIJA AI Trading LLC — Current Success State & Recovery Anchor

**Status date:** September 6, 2026 (UTC)

**Preferred current recovery checkpoint:** `3b48c533d191d8ce81d2166b14d3ef0946600c92`

**Kraken ECEL exit-symbol repair parent:** `09f13a0f2b4f189e7fb76de0cdb0035552f9b8ed`

**Verified production writer generation:** `5460`

**Verified production instance:** `srv-d98dsr5aeets73fpbaqg-xdvzm`

**Immutable August 22 explicit-gate checkpoint:** `740c98dc94374bb1ed770ff96a5eafabfd32681b`

**Immutable recovery branch:** `recovery/100-prod-readiness-20260822`

This README is the durable production and recovery anchor for **Nija_Trading_Bot**. Its purpose is to make it possible to return to the September 6 verified success state without forcing trades, weakening safety controls, fabricating readiness, or reintroducing the heartbeat duplicate-order problem.

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

**This is the preferred current recovery point.**

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
```

Change code only when evidence shows a real defect such as:

```text
writer/core/readiness truth regresses persistently
authoritative broker sync cannot recover
execution proof cannot be rebuilt from valid authenticated history
EXECUTION_ALLOWED remains false despite all required genuine proofs
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
