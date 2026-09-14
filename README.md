# NIJA AI Trading LLC — Trading Platform Architecture & Recovery Guide

**Project:** `Nija_Trading_Bot`  
**Status date:** September 14, 2026 (UTC)  
**Current main merge:** `c44d74b42f35999e4113a6b75129d5607ef1b679`  
**Broker-cell implementation head:** `472eeaa2c9d6f518bad029fbd550fa6a84505eb2`  
**Merged PR:** `#2784 — Broker-cell isolation: independent strategy/risk/user runtimes`

NIJA is an automated multi-broker trading platform designed around **broker isolation, fail-closed safety, independent risk control, and authoritative broker state**.

The current architecture separates Kraken, Coinbase, OKX, and Alpaca into independent broker cells so that a failure, halt, degraded API, bad state, strategy problem, or reconciliation problem in one brokerage does not automatically shut down or contaminate the others.

NIJA does **not** guarantee trades, fills, profits, income, or returns. A healthy system may correctly place no trade when strategy, market-quality, capital, broker-minimum, position, execution, or risk gates reject all candidates.

---

## 1. Current Architecture — Broker Cells

The platform is organized as a control plane plus isolated broker cells:

```text
NIJA CONTROL PLANE
│
├── NIJA_KRAKEN_CELL
├── NIJA_COINBASE_CELL
├── NIJA_OKX_CELL
└── NIJA_ALPACA_CELL
```

Each broker cell owns its own mutable trading state and is responsible for its own:

- broker/API adapter,
- account and user membership,
- credentials and access scope,
- strategy configuration,
- risk configuration,
- APEX runtime,
- NijaCoreLoop runtime,
- positions,
- orders and fills,
- realized/unrealized P&L,
- exposure and capital accounting,
- broker-local health state,
- circuit-breaker state,
- broker-local halt/recovery state,
- rate-limit handling,
- reconciliation state,
- runtime telemetry.

The design rule is:

> **Share visibility. Do not share mutable trading state.**

A consolidated NIJA dashboard may aggregate read-only summaries across brokers, but it must not become the shared source of truth for broker execution state.

---

## 2. Isolation Contract

A brokerage must not be able to accidentally execute, halt, mutate, or account for another brokerage's trading state.

Canonical routing hierarchy:

```text
broker_id
  -> account_id
    -> user_id
      -> strategy_id
        -> position/order
```

Every execution path should remain attributable to immutable routing identity such as:

```text
broker_id
account_id
user_id
strategy_id
client_order_id
```

Examples of prohibited cross-cell behavior:

```text
Kraken order -> Coinbase queue
Coinbase balance -> Kraken position sizing
OKX failure -> global broker shutdown
Alpaca circuit breaker -> Kraken execution disable
one broker's P&L -> another broker's capital authority
one broker's position cache -> another broker's reconciliation state
```

Unknown or unregistered brokers fail closed.

---

## 3. Broker-Local Failure Containment

The broker-cell design intentionally minimizes blast radius.

If Kraken loses authoritative position visibility, the expected behavior is:

```text
KRAKEN_CELL -> SAFE / HALTED FOR NEW ENTRIES
COINBASE_CELL -> unaffected
OKX_CELL -> unaffected
ALPACA_CELL -> unaffected
```

Protective exits remain eligible where the runtime has authoritative state and the required safety gates permit them.

A broker-local incident must not automatically become a platform-wide trading stop unless the failure is genuinely platform-wide, for example:

- shared credential compromise,
- confirmed systemic order-generation defect,
- corrupted shared market data affecting every broker,
- invalid global risk authority,
- compromised writer/fencing authority,
- other platform-wide integrity failures.

---

## 4. Hierarchical Kill Switches

NIJA should use the lowest appropriate shutdown scope:

```text
GLOBAL_TRADING_ENABLED
BROKER_TRADING_ENABLED
ACCOUNT_TRADING_ENABLED
USER_TRADING_ENABLED
STRATEGY_TRADING_ENABLED
```

Examples:

```text
single strategy defect -> halt strategy
single user/account risk breach -> halt account/user
Kraken API outage -> halt Kraken cell
platform-wide authority compromise -> global halt
```

Do not escalate a broker-local problem into a global shutdown without evidence that the problem crosses broker boundaries.

---

## 5. Broker-Cell Runtime State

Each broker cell should independently progress through a state machine equivalent to:

```text
STARTING
  -> SYNCING
    -> READY
      -> DEGRADED
        -> SAFE / HALTED
          -> RECOVERING
            -> READY
```

A cell must not report `READY` merely because the process is alive.

Before new entries are permitted, the cell should prove the broker-specific prerequisites required by its execution path, including authoritative state such as:

- broker connection/authentication,
- current balances/capital,
- open orders,
- open positions,
- reconciliation freshness,
- risk readiness,
- strategy readiness,
- execution readiness,
- writer/authority requirements where applicable.

---

## 6. Kraken Safety Requirement

Kraken remains especially sensitive because prior incidents showed that the canonical protection path could fail to surface an actual Kraken margin ETH position even while other readiness signals appeared healthy.

Therefore:

```text
Kraken authoritative position visibility unproven
    -> KRAKEN_CELL remains SAFE/HALTED for new Kraken entries
    -> other broker cells remain independently eligible
```

Do not promote Kraken to `READY` until the required Kraken position/open-order/balance reconciliation path has produced authoritative current evidence.

Kraken margin capabilities may also differ from spot/account-segmentation capabilities, so application-level runtime isolation remains mandatory even when broker-native account separation exists.

---

## 7. Capital, Risk, Strategy, and User Separation

Each broker/account/user runtime maintains its own strategy and mutable risk state.

Do not use a process-global singleton for broker-specific values such as:

```text
current strategy
current broker balance
current broker risk mode
current position cache
current order queue
current circuit breaker
current runtime health
```

Global policy may define maximum ceilings or platform-wide constraints, but evaluation and enforcement must remain broker/account-local before execution.

Capital from one brokerage must not be silently redistributed into another brokerage's sizing calculation.

User capital must not be mixed with platform capital.

---

## 8. Queue and Execution Isolation

The intended logical queue model is broker-scoped:

```text
orders.kraken
orders.coinbase
orders.okx
orders.alpaca
```

Each broker should have its own worker/execution context and dead-letter handling.

Retries must remain idempotent. Broker/client order identifiers must be preserved so a retry cannot silently create an unintended duplicate order.

A broker executor should hold only the credentials required for that brokerage and should use the minimum permissions necessary for execution.

Trading services should not have withdrawal privileges unless a separately reviewed requirement explicitly needs them.

---

## 9. Current Merge and Validation State

Broker-cell isolation was merged through PR `#2784`.

```text
implementation_head=472eeaa2c9d6f518bad029fbd550fa6a84505eb2
main_merge=c44d74b42f35999e4113a6b75129d5607ef1b679
```

The merged architecture includes:

- context-local strategy selection instead of process-global strategy state,
- first-class Kraken, Coinbase, OKX, and Alpaca broker cells,
- broker-local health and circuit state,
- broker-local risk/strategy metadata,
- broker-local user membership,
- persistent per-account APEX + NijaCoreLoop runtimes,
- per-account strategy-cycle routing,
- non-cascading broker halts,
- protective exit eligibility while a cell is locally halted,
- fail-closed unknown broker handling,
- broker-specific startup evaluation,
- regression tests for cross-broker failure containment,
- preservation of writer authority, Redis fencing, risk engines, broker managers, execution logic, position sizing, and Kraken nonce protections.

The final tested implementation head passed the repository's major validation workflows before merge, including:

```text
CI
NIJA Deployment Safety
CI imports smoke test
CI preflight/lint
Canonical startup launcher
Runtime repair regression tests
Build image
CodeQL Security Scanning
Security Scanning
Zero-Trust CI Isolation
Continuous Threat Modeling
Artifact Scanning
Branch policy
```

Deployment Safety also passed the writer/Kraken convergence, heartbeat, prebot authority, Render handoff/liveness, source-runtime guard, and related startup safety checks.

A neutral GitHub Advanced Security/Trivy configuration notice may appear when a code-scanning configuration from `canary-deployment.yml` is not represented in a PR check. Treat that as configuration telemetry, not proof of successful or failed trading runtime behavior.

---

## 10. Recovery Anchors

The broker-cell merge is the current `main` architecture, but historical recovery checkpoints remain important for incident response.

### September 6 verified production recovery anchor

```text
commit=3b48c533d191d8ce81d2166b14d3ef0946600c92
runtime_generation=5460
```

This historical checkpoint proved a complete production success chain including:

```text
writer acquired
core registered
capital ready
authoritative position sync
execution proof recovered from authenticated history
EXECUTION_ALLOWED: TRUE
LIVE_ACTIVE
execution authority ready
exit supervision active
live market scan reached
```

### September 10 Coinbase/Kraken recovery repair

```text
commit=f6efa3a4c439020869ee6b1c1164bd1cd219dda4
```

This repaired the funded-account recovery snapshot path by restoring the missing `importlib` dependency used to reach `broker_account_isolation_v64_patch`.

### August 22 immutable explicit-gate baseline

```text
commit=740c98dc94374bb1ed770ff96a5eafabfd32681b
branch=recovery/100-prod-readiness-20260822
```

These are historical rollback/evidence anchors. Do not automatically roll back merely because a newer deployment behaves differently. First determine whether the cause is broker latency, stale state, deployment handoff, account configuration, market conditions, or a genuine code regression.

---

## 11. Writer and Execution Authority Safety

Single-writer fencing remains authoritative.

Never recover faster by:

- deleting or force-clearing a valid writer lease,
- fabricating writer/core readiness,
- bypassing fencing tokens,
- manually forcing `LIVE_ACTIVE`,
- marking position sync ready without authoritative broker evidence,
- treating an ACK as a fill,
- inventing execution proof,
- weakening nonce protections,
- disabling broker minimum-order enforcement,
- bypassing risk/capital gates.

The real trading core must be registered before writer state can legitimately become active.

Brief Redis/heartbeat interruptions may use the existing bounded recovery behavior, but a genuine ownership loss must demote execution and fail closed.

---

## 12. Verification Trades and Heartbeat Safety

The preferred normal production configuration remains:

```text
HEARTBEAT_TRADE=false
NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS=false
```

Do not create a live capital-bearing order merely to prove that the runtime is alive when authenticated broker history can establish execution proof.

Historical restart-proof behavior has successfully recovered real fill evidence from authenticated broker history without submitting a new heartbeat order.

---

## 13. Protective Exit Contract

Protective exits are safety-critical and must remain reachable when valid broker state exists.

Do not create duplicate exit workers that could double-sell.

Kraken native symbols must continue to normalize into NIJA canonical symbols before execution/risk contract evaluation. Historical example:

```text
XETHZUSD -> ETH-USD
```

Do not create duplicate ECEL contracts simply to accommodate broker-native aliases when canonical normalization already exists.

Trusted cost basis must come from broker-backed/history-backed evidence when an exit decision depends on entry basis.

---

## 14. Production Verification Checklist

Before declaring a broker cell healthy for new entries, verify the applicable broker-specific evidence:

- [ ] Correct production commit is deployed.
- [ ] Broker credentials authenticate successfully.
- [ ] Broker cell identity is correct.
- [ ] Broker/account/user membership is correct.
- [ ] Current broker-backed capital is hydrated.
- [ ] Authoritative positions are reconciled.
- [ ] Authoritative open orders are reconciled.
- [ ] Position/order state is current, not stale.
- [ ] Risk state is broker/account-local.
- [ ] Strategy state is broker/account-local.
- [ ] Circuit breaker is broker-local.
- [ ] Writer/authority requirements are satisfied.
- [ ] Execution readiness is true through the normal canonical path.
- [ ] Protective exits remain available where appropriate.
- [ ] No cross-broker capital, queue, strategy, or position state is observed.
- [ ] A failure injected into one broker cell does not halt unrelated cells.

For the overall platform, verify that dashboard totals are aggregation-only and are not being used as mutable source-of-truth execution state.

---

## 15. Observability

Each broker cell should expose enough telemetry to diagnose it independently, including:

```text
broker_id
account_id
cell_state
starting_capital
current_equity
realized_pnl
unrealized_pnl
fees
open_positions
open_orders
risk_exposure
api_health
error_rate
rate_limit_state
last_authoritative_reconciliation
circuit_breaker_state
halt_reason
```

A platform dashboard may sum or compare broker summaries, but broker-local logs and state remain authoritative for broker-local decisions.

---

## 16. When No Trade Is Correct

Trading readiness does not require an order every cycle.

These are not failures by themselves:

```text
no valid signal
candidate below broker minimum
insufficient capital for strategy
risk rejected candidate
spread too wide
volume too low
market quality rejected entry
insufficient candle history
position already at exposure limit
broker cell intentionally halted
```

Do not weaken market-quality, risk, spread, volume, signal, capital, or broker-minimum thresholds just to make the system trade.

---

## 17. Deployment Practice

Broker cells should be deployed and validated incrementally rather than changing every broker simultaneously.

Preferred release pattern:

```text
1. run focused tests
2. verify paper/test paths where available
3. deploy one broker-cell change
4. verify authoritative broker state and runtime telemetry
5. verify no cross-broker effect
6. proceed to the next broker
```

A failure in a newly deployed broker cell should be contained to that cell whenever platform-wide safety has not been compromised.

---

## 18. Core Safety Contracts

Never weaken these contracts to recover faster or increase trade frequency:

- single-writer fencing,
- current writer generation/token,
- nonce protection,
- real broker authentication,
- broker-backed capital authority,
- authoritative position/order reconciliation,
- freshness requirements,
- real execution proof,
- ACK-vs-fill distinction,
- risk governor enforcement,
- broker minimum-order rules,
- kill switches,
- core-thread readiness,
- canonical execution-state transitions,
- broker-backed fill/order state,
- user/platform capital separation,
- broker-cell isolation,
- protective exit eligibility,
- fail-closed unknown broker handling.

---

## Official NIJA Links

- **Website:** https://nijaaitrading.com
- **Mobile documentation:** `mobile/README.md`
- **Owner:** NIJA AI Trading LLC

## Disclaimer

NIJA AI Trading is not financial advice. Trading involves risk and may result in financial loss. Users are responsible for their trading decisions. NIJA does not guarantee profits, returns, income, trade frequency, order fills, or trading success.
