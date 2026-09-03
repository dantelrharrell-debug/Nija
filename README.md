# NIJA AI Trading LLC — Current Success State & Recovery Anchor

**Status date:** September 3, 2026 (UTC)

**Current repository recovery checkpoint:** `760a43710d39156d78771e8833dd7e0633f2e0ce`

**Current deployed production-readiness runtime:** `6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e`

**Immutable explicit-gate recovery checkpoint:** `740c98dc94374bb1ed770ff96a5eafabfd32681b`

**Immutable recovery branch:** `recovery/100-prod-readiness-20260822`

This README is the durable production and recovery anchor for NIJA. It records the latest successful repository checkpoint, the latest verified production runtime, and the immutable explicit-gate checkpoint so production can be restored without weakening safety controls.

> The current v188 deployment (`6d3c8e37...`) reproduced the operational production-readiness state: writer/core healthy, Kraken/Coinbase/OKX connected, authoritative reconciliation `CLEAN_START`, position sync 3/3, fresh complete capital 3/3, kill switch inactive, `LIVE_ACTIVE`, strict live dispatch ready, and the strategy trade cycle invoked through the normal runtime path. The latest log slice does **not** contain the literal `EXECUTION_ALLOWED: TRUE` line and does **not** contain a new broker order ID/fill. The immutable August 22 checkpoint remains the canonical explicit-gate proof because it includes `EXECUTION_ALLOWED: TRUE`.

NIJA does not guarantee trades, fills, profits, income, or returns. Never manufacture readiness with forced activation, synthetic capital, fabricated prices, credential bypasses, nonce bypasses, writer-lock deletion, freshness extension, emergency-stop bypasses, weakened risk gates, or fake order/fill state.

---

## 1. Current Repository Success Checkpoint — v348

The current codebase is green at the following immutable checkpoint:

```text
commit=760a43710d39156d78771e8833dd7e0633f2e0ce
short_commit=760a437
date=2026-09-02
change=test v348 stale platform dispatch and safety invariants
```

This checkpoint contains the v348 regression coverage for stale platform position dispatch. The tests confirm that stale candidates are deduplicated, the existing worker is reused asynchronously, and recovery does not grant position or execution readiness, promote stale data, or force trades.

This is the **current code/repository recovery point**, not a claim that v348 has been deployed or that a new order/fill occurred. To return to this exact code state after investigating a later failure, preserve the commit above and restore it through the normal Git/GitHub deployment process. Re-run the repository's applicable tests and re-establish all production gates from current broker evidence; never restore readiness from this README alone.

The last verified deployed operational runtime remains v188 (`6d3c8e37...`), and the immutable `EXECUTION_ALLOWED: TRUE` proof remains the August 22 checkpoint below.

---

## 2. Latest Verified Production Runtime — v188

Current deployed SHA:

```text
deployment_sha=6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e
runtime_generation=4648
writer_token_prefix=3335
```

The runtime release manifest reports the v188 deployment SHA while retaining the established runtime release identity:

```text
NIJA_RUNTIME_RELEASE_MANIFEST
release=20260818-runtime-convergence-v146
deployment_sha=6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e
ready=true
```

### Broker connectivity

The current runtime proved all configured platform brokers connected:

```text
kraken_connected=True
coinbase_connected=True
okx_connected=True
all_configured_connected=True
platform_accounts_connected=3
platform_accounts_registered=3
registry_all_connected=True
```

Kraken user supervision also reported:

```text
kraken_users_registered=2
kraken_users_connected=2
kraken_users_disconnected=0
kraken_users_all_connected=True
user_accounts_registered=2
user_accounts_connected=2
user_accounts_trading_eligible=2
```

### Writer/core authority

```text
WRITER_LOCK_RENEWED
generation=4648
token_prefix=3335
core_thread_alive=True
core_thread_registered=True
core_thread_reason=ok
WRITER_STATE_TRANSITION ... state=ACTIVE reason=heartbeat_renewed
```

### Reconciliation and position sync

The runtime reached authoritative clean reconciliation:

```text
STARTUP_RECONCILIATION_V146_READY
status=CLEAN_START
brokers=['platform:coinbase', 'platform:kraken', 'platform:okx']
authoritative_snapshots=true
```

Position sync then proved all three platform brokers current:

```text
POSITION_SYNC_V96_READINESS
ready=true
pending=[]
status={'platform:kraken': True, 'platform:coinbase': True, 'platform:okx': True}
canonical_readiness=true
```

The authoritative position-fetch proof remained genuine:

```text
RUNTIME_POSITION_FETCH_PROOF_V182
ready=true
exact_v98_owner_required=true
adopted_and_fetch_proof_required=true
copied_marker_false_positive_blocked=true
synthetic_success=false
```

### Capital proof

Current complete capital snapshot:

```text
real_capital=341.53984970237343
usable_capital=334.70905270832594
risk_capital=334.70905270832594
broker_count=3
expected_brokers=3
capital_completeness=1.0
is_fresh=True
capital_lifecycle_state=ACTIVE_CAPITAL
```

Broker-backed balances in that snapshot:

```text
kraken=246.4199
coinbase=95.11593557479999
okx=0.004014127573456987
```

The observed dollar values are live historical snapshots, not fixed recovery targets. Recovery must always use current broker-backed balances.

The runtime also reported:

```text
AGGREGATED STATE:
aggregation_ready=True
capital_authority_ready=True
all_brokers_ready=True
valid_brokers=3
platform_brokers=['kraken', 'coinbase', 'okx']
bootstrap_state=READY
runtime_state=RUN_READY
```

### Live runtime / trade-cycle proof

The state machine repeatedly reported:

```text
trading_state=LIVE_ACTIVE
kill_switch=False
```

Strict live dispatch was available with fresh complete capital:

```text
TRADING_STATE_DISPATCH_LATCH_REPAIR_APPLIED
detail=strict_live_dispatch_ready
state=LIVE_ACTIVE
hydrated=True
complete=True
registered_brokers=3
expected_brokers=3
valid_brokers=3
fresh=True
```

The core then entered the live trade cycle:

```text
TRADE LOOP HEARTBEAT: active=True
LIVE LOOP TICK — scanning markets
RUNNING TRADE CYCLE
[CYCLE_INVOKE] strategy.run_cycle() CALLED
```

This is stronger than a startup-only readiness snapshot: the live core reached the strategy execution cycle through the normal runtime path.

### What this latest slice does not prove

The current v188 log slice does not include:

```text
EXECUTION_ALLOWED: TRUE
new broker order ID / acknowledgment
new confirmed entry fill
new confirmed exit fill
```

Therefore:

- v188 is the **current verified operational production-readiness runtime**.
- the August 22 immutable checkpoint remains the **canonical explicit `EXECUTION_ALLOWED: TRUE` recovery proof**.
- a real order/fill remains separate behavioral proof and must never be fabricated or forced merely to satisfy documentation.

### Position-specific safety condition observed

A Kraken user position was synchronized for `CELO-USD` with an unresolved trusted entry/cost basis:

```text
POSITION_COST_BASIS_RECONCILIATION_REQUIRED
symbol=CELO-USD
cost_basis_verified=False
auto_exit_blocked=true
```

This is **not a global runtime blocker**. It is correct fail-safe behavior for that position. NIJA must not auto-exit that position using an unverified cost basis. Resolve it only from trusted broker/reconciliation evidence; never invent an entry price.

---

## 3. August 22, 2026 — Immutable 100/100 Explicit-Gate Baseline

The immutable successful production lineage is anchored to:

```text
deployment_sha=740c98dc94374bb1ed770ff96a5eafabfd32681b
runtime_generation=4629
```

The runtime proved the complete live gate:

```text
Reconciliation: COMPLETE
Nonce Sync: VALID
Lease Owner: CONFIRMED
Writer Heartbeat: HEALTHY
Strategy Ready: TRUE
Circuit Breaker: CLOSED
EXECUTION_ALLOWED: TRUE
```

Writer/core proof:

```text
WRITER_LOCK_RENEWED
WRITER_STATE_TRANSITION ... state=ACTIVE
core_thread_alive=True
core_thread_registered=True
core_thread_reason=ok
```

Position/reconciliation proof:

```text
RUNTIME_POSITION_FETCH_PROOF_V182 ... ready=true ... synthetic_success=false
STARTUP_RECONCILIATION_V146_READY ... status=CLEAN_START ... authoritative_snapshots=true
POSITION_SYNC_V96_READINESS ... ready=true pending=[]
status={'platform:kraken': True, 'platform:coinbase': True, 'platform:okx': True}
```

Broker connectivity proof:

```text
kraken_connected=True
coinbase_connected=True
okx_connected=True
all_configured_connected=True
platform_accounts_connected=3
platform_accounts_registered=3
kraken_users_registered=2
kraken_users_connected=2
user_accounts_trading_eligible=2
```

Capital proof in the successful window:

```text
CAPITAL_REFRESH_COMPLETED ... success=true ready=true total_capital=342.57
RUNTIME_CAPITAL_PUBLICATION_IDENTITY_V178 ... reason_not_repairable:accepted
```

The observed `$342.57` is a historical live snapshot, not a fixed target. Recovery must use current broker-backed balances, not reproduce that number.

The final execution router also reported:

```text
FINAL_EXECUTION_STATE_ROUTER_RECONVERGED
state={'execution': True, 'startup': True, 'okx': True}
```

---

## 4. Current Recovery Hierarchy

Use this order when recovering production:

1. **Preferred current runtime reference:** `6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e` (v188).
2. Verify that the failure is an actual persistent code/runtime defect rather than startup convergence, broker latency, account-side behavior, market quality, or a temporary external failure.
3. If v188 cannot be restored safely or its lineage is suspect, compare against the immutable explicit-gate baseline:

```text
740c98dc94374bb1ed770ff96a5eafabfd32681b
recovery/100-prod-readiness-20260822
```

Do not force-move or rewrite the immutable recovery branch merely because a newer deployment is healthy. Create a new recovery anchor only after intentionally validating and preserving a later full explicit-gate proof.

---

## 5. Exact Recovery Target

If production regresses, the target is not merely `LIVE_ACTIVE`. Restore the full evidence chain below:

1. Expected deployment/recovery lineage loaded.
2. Single writer owns the current generation.
3. Writer heartbeat healthy.
4. Real core thread alive and registered.
5. Kraken, Coinbase, and OKX connected.
6. Position fetch/adoption proof genuine (`synthetic_success=false`).
7. Reconciliation reaches `CLEAN_START` with authoritative snapshots.
8. Position sync is 3/3 with `pending=[]`.
9. Capital refresh succeeds with all expected brokers represented.
10. Capital publication is current/accepted.
11. v183 Kraken balance liveness is ready.
12. v184 authenticated aggregate valuation confidence is ready.
13. Nonce sync is valid.
14. Lease owner confirmed.
15. Strategy ready.
16. Circuit breaker closed.
17. Kill switch naturally inactive.
18. Final execution router is enabled.
19. `EXECUTION_ALLOWED: TRUE` appears through the normal canonical path for the strongest explicit-gate proof.
20. No active fail-closed execution blocker remains.
21. Live core can enter `strategy.run_cycle()` without bypassing any safety gate.

Do not skip failed steps by forcing later states.

---

## 6. Recovery Rollback Procedure

### A. Preserve evidence first

Before changing code or redeploying, save the failing production logs and identify the **first false proof**. Do not patch based only on the last downstream error.

### B. Compare against the current runtime and immutable checkpoint

Current deployed reference:

```text
6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e
```

Immutable explicit-gate checkpoint:

```text
740c98dc94374bb1ed770ff96a5eafabfd32681b
```

Immutable branch:

```text
recovery/100-prod-readiness-20260822
```

### C. Roll back code only when evidence supports it

If a later deployment introduced a regression, restore from a proven-good checkpoint using normal Git/GitHub rollback or redeploy procedures. Never bypass runtime safety gates merely to make the rollback appear healthy.

### D. Re-validate production after rollback

A rollback is not complete until runtime again proves:

```text
writer ACTIVE
core_thread_alive=True
core_thread_registered=True
3/3 broker connectivity
3/3 position sync
CLEAN_START authoritative reconciliation
capital refresh success=true ready=true
nonce VALID
strategy TRUE
circuit breaker CLOSED
kill switch naturally inactive
strict live dispatch ready
EXECUTION_ALLOWED: TRUE (strongest explicit-gate proof)
```

---

## 7. Critical Recovery Lineage — v169 through v188

The current production hardening lineage includes:

```text
v169 execution-capital integrity
v170 capital publication monotonicity
v171 market-data concurrency
v172 post-core activation budget
v173 Kraken capital tail liveness
v174 Kraken capital observation admission
v175 authority-position convergence
v176 capital pipeline completion/reactivation
v177 market-data source convergence
v178 capital publication identity recovery
v179 bootstrap capital publication/hydration convergence
v180 direct-refresh capital downgrade guard/bootstrap completeness
v181 canonical generation-context recovery
v182 authoritative position-fetch proof reassertion
v183 Kraken capital balance liveness/cache-only valuation
v184 authenticated Kraken aggregate-equity valuation confidence
v185 kill-switch provenance reassertion
v186 post-reassert guarded kill-switch recovery recheck
v187 canonical capital generation / effective Kraken valuation coverage
v188 production readiness convergence stabilization
```

v188 preserves the normal safety path. It does not force live state, fabricate capital or prices, manufacture position success, weaken completeness/freshness, disable the kill switch, or bypass writer/nonce/risk/execution-authority gates.

Important merged checkpoints leading to the immutable August 22 baseline:

```text
PR #2626 -> 9dcf412e0cdf39394e77a25cc5d06c2d6b5173aa
PR #2627 -> 11db94d8a849d5fd6955876f3513f55715ba87d6
PR #2628 -> 9d497b22bc7966d70f573d273eca8c3aa96519a3
PR #2629 -> 7a23a0fa395ad2f650ba3bf0f1b8c66c45c7d7e3
PR #2630 -> 68b99033c0cd4746441dd6ef7c1daff297009093
PR #2631 -> 1bd329e3efe72b22dc7aec6359d3f398810ceeb8
PR #2632 -> 3ddccccf98267c3325feb2db4a142a535fb23a2d
PR #2633 -> 20a40012bb60a12fe948714cf0d1591316ec658b
PR #2634 -> cc579542218dfacce64738ba1ca78e134f7f6da5
PR #2635 -> 3c6f6fd84f5b6054dc80a30f0b3246c5a253d7c2
PR #2636 -> 740c98dc94374bb1ed770ff96a5eafabfd32681b
```

Do not assume a future failure requires a new numbered patch. First determine whether the problem is broker-side, account-side, transient, deployment-related, stale state, or an actual code defect.

---

## 8. Kraken-Specific Recovery Contract

Kraken was the final repeated capital-readiness problem before the immutable 100/100 checkpoint.

### v183 contract

During capital refresh, per-asset USD pricing is cache-only so public price lookups cannot consume the private-balance budget. Authenticated Kraken `TradeBalance` equivalent equity remains authoritative for total-equity floor logic.

Do not undo this by reintroducing serial public price fetches into the protected capital-refresh path.

### v184 contract

Fresh authenticated Kraken `TradeBalance.result.eb` may provide effective aggregate valuation coverage when it is:

- authenticated,
- positive,
- from the same balance epoch,
- fresh,
- error-free,
- and the broker is available/healthy.

Raw asset-pricing coverage remains diagnostic and must not be falsified.

Never fabricate asset prices, extend freshness TTL, mutate capital to pass confidence, or weaken broker-completeness requirements.

### v187/v188 contract

Current canonical generation context and effective Kraken valuation coverage must stay tied to accepted canonical snapshots and authenticated v184 proof. Retired-generation fences remain authoritative. v188 stabilizes convergence around those contracts; it does not redefine the underlying truth conditions.

---

## 9. Position & Held-Trade Recovery Contract

A healthy runtime must prove real position adoption/fetch, not copied or synthetic readiness.

Expected proof:

```text
RUNTIME_POSITION_FETCH_PROOF_V182
ready=true
exact_v98_owner_required=true
adopted_and_fetch_proof_required=true
synthetic_success=false
```

Healthy reconciliation must return:

```text
STARTUP_RECONCILIATION_V146_READY
status=CLEAN_START
authoritative_snapshots=true
```

The automatic exit stack must remain intact for existing positions. Entry fail-closed conditions must not disable legitimate protective exits.

When a real position has unverified cost basis/entry metadata, NIJA must preserve the raw position while blocking unsafe automatic exit logic for that position until trusted reconciliation resolves the basis.

Do not create duplicate exit workers that could double-sell a position.

---

## 10. Exit-Protection Stack That Must Be Preserved

Current production code contains the following protections:

- hard/standard stop loss,
- forced/emergency stop loss,
- take-profit levels,
- trailing/profit-lock exit,
- trailing stop loss,
- trailing take profit,
- break-even stop,
- universal broker exit supervision,
- Kraken profit-realization protection.

The canonical automatic SL/TP monitor is engine-aware and scans open positions. Recovery must preserve position metadata such as symbol, side, quantity, entry price, market price access, and stored protection levels.

Never mark a position closed or fabricate an exit fill without broker/exchange evidence.

---

## 11. Safety-Critical Contracts — Never Weaken These to Recover Faster

- Single-writer fencing remains authoritative.
- Writer generation/token must be current.
- Nonce protection remains fail-closed.
- Real broker credentials/authentication are required.
- Capital must come from current broker-backed observations.
- Complete broker aggregation rules remain truthful.
- Freshness TTLs must not be extended to hide failures.
- Stale or partial snapshots must not be promoted to current.
- Position readiness must come from authoritative broker snapshots.
- Risk governor remains in the execution path.
- Kill switch and genuine emergency stops remain authoritative.
- Core-thread readiness must describe the actual live thread.
- `EXECUTION_ALLOWED` must come only through the canonical state machine/gates.
- Order submission/fill state must come from broker/exchange evidence.
- User capital must never be mixed into platform capital.
- Do not lower market-quality, risk, spread, volume, or signal thresholds merely to force a trade.
- Absence of trades by itself is not a bug.

---

## 12. Known Non-Blocking / Transient Signals

Healthy runtime may still show installer/reset/replay messages such as:

```text
RUNTIME_RELEASE_DECLARATION_DOWNGRADE_BLOCKED
RUNTIME_RELEASE_IDENTITY_OVERRIDE_BLOCKED
RUNTIME_RELEASE_REPAIR_AUDIT_REQUIRED
POSITION_SYNC_V96_READINESS source=install_fail_closed ready=false status={}
STARTUP_RECONCILIATION_V146_PENDING source=install_fail_closed
```

These are not automatically production failures. Judge the final/current runtime truth after convergence.

In the v188 production slice, install-time fail-closed position/reconciliation resets were followed by:

```text
STARTUP_RECONCILIATION_V146_READY ... status=CLEAN_START
POSITION_SYNC_V96_READINESS ... ready=true ... 3/3
LIVE_ACTIVE
strict_live_dispatch_ready
strategy.run_cycle() CALLED
```

Likewise, market-data quality blocks, insufficient candle history, low volume, spread filters, and no valid strategy signal can correctly prevent new entries while the runtime remains production ready.

---

## 13. Definition of Production Readiness

### Current v188 operational production proof

- [x] Current deployment identity known (`6d3c8e37...`).
- [x] Writer lease acquired and renewed.
- [x] Writer heartbeat healthy.
- [x] Real core thread alive and registered.
- [x] Kraken connected.
- [x] Coinbase connected.
- [x] OKX connected.
- [x] Authoritative position adoption/fetch proof.
- [x] `CLEAN_START` reconciliation.
- [x] Position sync 3/3.
- [x] Broker-backed capital complete 3/3.
- [x] Capital publication accepted/current and fresh.
- [x] v183 ready.
- [x] v184 ready.
- [x] v185/v186 kill-switch provenance protections preserved.
- [x] v187 generation/valuation coverage ready.
- [x] Kill switch inactive naturally.
- [x] Runtime state `LIVE_ACTIVE`.
- [x] Strict live dispatch ready.
- [x] Live trade loop active.
- [x] `strategy.run_cycle()` invoked.
- [ ] Literal `EXECUTION_ALLOWED: TRUE` line present in this specific v188 log slice.
- [ ] New broker order acknowledgment/fill proven in this specific v188 log slice.

### Immutable August 22 explicit-gate proof

The immutable checkpoint additionally proved:

- [x] Nonce valid.
- [x] Lease owner confirmed.
- [x] Strategy ready.
- [x] Circuit breaker closed.
- [x] `EXECUTION_ALLOWED: TRUE`.

Therefore:

- **v188 is the current verified operational production-readiness runtime.**
- **`740c98dc...` remains the immutable 100/100 explicit-gate recovery baseline.**

### Separate end-to-end behavioral proof

The following are stronger behavioral confirmations but are not required to establish that the runtime is ready and operating:

- [ ] A new legitimate live order receives a broker/exchange acknowledgment/order ID.
- [ ] The new entry reaches a confirmed fill.
- [ ] Position reconciliation confirms that fill.
- [ ] A valid exit condition triggers.
- [ ] The exit order is acknowledged.
- [ ] The exit reaches confirmed fill/closed state.
- [ ] Final broker position/PnL reconciliation confirms closure.

Do not force a trade merely to satisfy this checklist.

---

## 14. When Everything Is Working

If production matches the v188 current runtime or the immutable August 22 recovery target, **stop patching unless a concrete defect appears**.

Do not treat the following as reasons to modify core safety/readiness code by themselves:

```text
no trade yet
no valid signal
market quality blocked entry
volume too low
spread too wide
insufficient candle history
risk rejected a candidate
installer replay emitted a temporary fail-closed reset
```

Change code only when evidence shows a real defect, such as:

```text
writer/core/readiness truth regresses
one broker repeatedly fails authoritative synchronization
capital publication repeatedly loses a healthy broker
current authenticated capital cannot be admitted correctly
EXECUTION_ALLOWED becomes false despite all required proofs being current
an EXECUTE decision never reaches the broker adapter
broker acknowledgment/fill state is mishandled
position reconciliation loses a real filled position
protective exit logic fails to submit a valid exit
```

Preserving a proven working runtime is safer than continuously modifying it without evidence.

---

## 15. Historical Recovery Anchors

Prior August 13 recovery checkpoint:

```text
666ef8893dd491bcd2e52acb6cae8291e61d780e
runtime_generation=3774
```

Immutable August 22 explicit-gate checkpoint:

```text
740c98dc94374bb1ed770ff96a5eafabfd32681b
runtime_generation=4629
```

Current v188 deployed runtime:

```text
6d3c8e37b02e6b4a3679c34fc0450d4c53ed064e
runtime_generation=4648
```

The August 13 checkpoint remains historical context. The August 22 checkpoint remains the immutable explicit-gate recovery anchor. v188 is the newest verified deployed operational production state.

---

## Official NIJA Links

- **Website:** https://nijaaitrading.com
- **Mobile documentation:** `mobile/README.md`
- **Owner:** NIJA AI Trading LLC

## Disclaimer

NIJA AI Trading is not financial advice. Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.
