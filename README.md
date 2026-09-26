# NIJA AI Trading LLC — Trading Platform Architecture & Recovery Guide

**Project:** `Nija_Trading_Bot`  
**Status date:** September 26, 2026 (UTC)  
**Latest runtime merge:** `e60ce1be56cd4080b47cbf7637e55d816aa66c28`  
**Latest merged runtime PR:** `#2893 — Fix heartbeat canonical selection deadlock`  
**Broker-cell implementation head:** `472eeaa2c9d6f518bad029fbd550fa6a84505eb2`  
**Broker-cell architecture merge:** `#2784 — Broker-cell isolation: independent strategy/risk/user runtimes`

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

The current `main` head is the September 26 UTC merge of PR `#2893`. Since the previous README refresh, NIJA merged runtime-liveness recovery, paid-user live-trading entitlement/credential gating, durable encrypted Redis-backed paid-user state, and a heartbeat canonical-selection deadlock repair.

```text
latest_runtime_merge=e60ce1be56cd4080b47cbf7637e55d816aa66c28
latest_runtime_pr=#2893
runtime_liveness_position_sync=#2890
paid_user_live_trading_bridge=#2891
paid_user_redis_state=#2892
heartbeat_canonical_selection=#2893
startup_fail_closed_nonfatal=#2874
break_retest_fvg_gate=#2875
liquidity_fvg_retrace_strategy=#2876
liquidity_reversal_sequence=#2877
universal_exit_contract_repair=#2878
protection_readiness_strict=#2873
protection_status_surface=#2872
broker_cell_implementation_head=472eeaa2c9d6f518bad029fbd550fa6a84505eb2
broker_cell_architecture_merge=c44d74b42f35999e4113a6b75129d5607ef1b679
```

### September 26 current deployment and blocker status

Treat **merged**, **deployed**, **runtime-ready**, and **protected-live-ready** as separate states.

PR `#2890` repaired capital-worker buildup and added a capital-independent pulse for Kraken authoritative position recovery. It preserves fail-closed behavior: no stale snapshot is promoted, no worker is force-killed, and no execution/protection proof is fabricated.

PR `#2891` wired paid customers into the canonical multi-account runtime only when authoritative billing, consent, risk acknowledgement, mode, supported broker credentials, and encrypted-vault checks pass. Entitlement is rechecked on every customer entry cycle; cancellation, expiry, payment failure, consent revocation, education mode, or access-check failure blocks new entries while preserving exit/protection access for existing positions.

PR `#2892` moved paid-user entitlement and encrypted broker state toward durable Redis-backed authority so paid-user runtime access is not dependent on ephemeral process memory.

PR `#2893` repaired a heartbeat selection deadlock. Before that repair, the PR records production as healthy on the canonical non-execution prerequisites while `execution_ready` remained unresolved because the heartbeat could not select a venue to produce the needed proof. The repair permits only the dedicated heartbeat thread to use the existing selection fallback when broker, balance, writer, capital, risk, strategy, nonce, bootstrap, and platform position-sync readiness are already true. It does **not** mark execution ready or bypass downstream gates.

#### Current blockers / verification still required

- **CI validation is not currently green for the September 26 head.** Push workflows for CI, preflight/lint, imports, image build, CodeQL, security scanning, threat modeling, zero-trust isolation, and artifact scanning all reported failure on `e60ce1be56cd4080b47cbf7637e55d816aa66c28`. The associated jobs exposed no executed step list and no retrievable job logs, so this evidence must be treated as a **validation/infrastructure blocker**, not as proof that application tests passed or as proof of a specific code regression.
- **Production deployment of the September 26 head still requires direct runtime confirmation.** A merge to `main` is not sufficient evidence that the production service is running that commit.
- **`execution_ready` requires post-repair runtime proof.** PR `#2893` repairs the selection deadlock but does not itself prove that the production heartbeat subsequently produced authoritative execution readiness.
- **Protected real-money entry remains fail-closed until broker capability and protection evidence are authoritative.** The selected router must report protected-entry capability, authoritative protection coverage must be ready, and a broker-confirmed live entry must show active SL and TP legs on readback.
- **Paid-user live activation requires deployment and runtime verification.** Redis-backed entitlement, encrypted broker credentials, subscription state, consent, and continuous revocation behavior are merged control paths; they still need to be observed working in the deployed production runtime.
- **Broker/account authority remains broker-local.** Any stale positions, stale open orders, missing credentials, disconnected broker, stale capital, writer/nonce failure, risk denial, kill switch, minimum-order failure, or reconciliation failure must continue to block only the affected scope unless evidence shows a platform-wide integrity failure.

Do not describe NIJA as fully production-complete, fully protected for real-money entry, or ready for store submission solely because the September 26 repairs are merged.

### App Store / Google Play submission roadmap — gated

Store submission remains a **roadmap milestone**, not a current release state. Do not move NIJA into public App Store or Google Play submission until all four readiness groups below are demonstrably complete with current evidence.

#### 1. Mobile build gate

- [ ] One mobile architecture is locked for release: complete the planned Expo React Native conversion or formally retain and harden Capacitor.
- [ ] One permanent bundle/package identifier is selected and used consistently for iOS and Android.
- [ ] Production authentication and authorization are implemented for every mobile API route.
- [ ] Secure local session/token storage is implemented and verified on both platforms.
- [ ] Home, Signals, Trades, Risk, and Profile flows are implemented with explicit offline, degraded, error, Simulation, Live Pending, Live, and Emergency Paused states.
- [ ] Consent, disclosures, broker connection, account deletion, emergency pause, push notifications, biometrics, deep links, accessibility, icons, splash screens, and approved black-and-gold branding are complete.
- [ ] Signed iOS and Android release candidates pass physical-device QA, TestFlight, and Google Play internal testing.

#### 2. Security gate

- [ ] Required CI, CodeQL, security scanning, artifact scanning, threat-modeling, zero-trust, build, import, and preflight checks are genuinely green for the release commit.
- [ ] No broker secrets, Redis/database credentials, signing material, writer-authority values, or administrative tokens are embedded in the mobile client.
- [ ] Mobile authentication, authorization, rate limiting, durable encrypted device-token storage, token rotation/revocation, audit logging, and abuse controls are verified.
- [ ] Threat modeling and penetration/security testing are complete with release-blocking findings resolved.
- [ ] Privacy, retention, account-deletion, disclosures, and store data-use declarations match actual production behavior.

#### 3. Brokerage / trading gate

- [ ] Each supported production broker has authoritative connectivity, capital, position, open-order, risk, writer, nonce, and reconciliation evidence for the intended user flow.
- [ ] Paid-user entitlement and credential hydration are verified in production, including cancellation/payment-failure/expiry/consent revocation.
- [ ] Live-entry eligibility remains server-authoritative and cannot be enabled by a mobile-only toggle.
- [ ] Protected strategies remain fail-closed unless the selected broker explicitly supports the required protected-entry contract.
- [ ] A broker-confirmed protected live entry proves active stop-loss and take-profit protection on readback where that live feature is enabled.
- [ ] Existing-position protection and exit-only management remain available when new-entry entitlement is revoked.

#### 4. Operational gate

- [ ] The exact release commit is confirmed deployed in production.
- [ ] Production health, logs, runtime authority, broker cells, reconciliation, and incident telemetry are reviewed after deployment.
- [ ] Monitoring, support, incident response, rollback, credential-rotation, and emergency-pause procedures are documented and exercised.
- [ ] Legal/compliance review is complete for privacy policy, terms, risk disclosures, account deletion, pricing/subscription behavior, and store metadata.
- [ ] Release ownership, signing keys/certificates, store accounts, reviewer access, support contacts, and rollback ownership are defined.
- [ ] Final release signoff is based on current production and device evidence, not historical checklists or completion claims.

**Submission rule:** App Store and Google Play submission stays **NO-GO / roadmap-only** until the mobile build, security, brokerage, and operational gates above are all complete and evidenced on the intended release commit.

### September 22 authoritative protection-readiness status

`BREAK_RETEST` remains deliberately **fail-closed for real broker entry** until all applicable execution and protection gates are satisfied.

PR `#2872` added the native read-only v281 `coverage_status()` surface. It returns the current authoritative all-account SL/TP coverage evaluation without submitting orders, performing broker I/O, mutating protection trackers, or fabricating protection/fill evidence.

PR `#2873` then tightened v347 so protection readiness is accepted only when:

```text
coverage_status() returns a dict
AND
coverage_status()["ready"] is exactly True
```

The following conditions now remain fail-closed:

```text
status helper missing
status helper unavailable
payload malformed
ready missing
ready=false
ready="false"
ready=1
coverage evaluation deferred/error
```

This distinction is important: a merged safety patch proves the **control path**, not that the live brokerage state is currently ready.

For real-money `BREAK_RETEST` activation eligibility, require:

```text
EXECUTION_ALLOWED: TRUE
AND
authoritative v281 coverage_status()["ready"] is True
AND
v347 protection readiness is True
AND
selected broker router reports protected-entry capability
AND
risk/capital/writer/nonce/circuit-breaker gates pass
AND
current broker positions and open orders are authoritative
```

For end-to-end protected-trading proof, additionally verify a real broker-confirmed entry where the requested protections are actually attached and read back:

```text
live entry broker-confirmed
AND
stop-loss broker-confirmed active
AND
take-profit broker-confirmed active
AND
protective exit/reconciliation supervision verified
```

An `EXECUTION_ALLOWED: TRUE` signal by itself is therefore **not** sufficient to declare protected live trading complete.

Current routing contracts still include:

- the single-venue `ExecutionRouter.supports_v2_protected_entry(...)` failing closed where no verified protected-entry contract exists;
- the multi-broker router requiring an explicit broker protected-entry capability and protected submission method;
- rejection or reconciliation when SL/TP protection cannot be verified after submission;
- paper, backtest, and simulated `BREAK_RETEST` operation remaining separate from the real-money protected-entry gate.

### Recent Kraken execution-path repairs

The latest merge chain also includes several Kraken-specific safety and routing repairs:

- PR `#2868` preserves local pre-dispatch volume-rejection provenance so a locally rejected `VOLUME_TOO_SMALL` path is not falsely counted as an exchange rejection;
- PR `#2869` canonicalizes Kraken market aliases such as `XBT -> BTC` and `XDG -> DOGE` during product discovery, allowing NIJA's canonical heartbeat universe to match Kraken markets correctly;
- PR `#2870` makes heartbeat sizing honor Kraken's canonical safe quote floor while preserving the configured risk cap. If the risk budget cannot satisfy the safe minimum, the heartbeat defers before broker dispatch instead of weakening the exchange minimum or risk limit;
- PR `#2872` exposes authoritative read-only all-account protection coverage status;
- PR `#2873` requires that authoritative status to be strictly ready before v347 can report protection readiness.

These repairs do **not** clear a genuine emergency-stop latch, force a trade, lower broker minimums, increase the heartbeat risk fraction, fabricate execution proof, or bypass writer/nonce/risk/protection gates.

Do not report NIJA as fully protected for real-money entry solely because these changes are merged. Runtime completion still requires current authoritative broker evidence through the canonical gates.

### September 22–23 strategy, startup, and universal-exit updates

PR `#2874` changed startup behavior so a legitimate not-yet-ready v324 profitability/protection chain remains **fail-closed but nonfatal** while broker registration, authoritative position sync, and protection coverage converge. A missing installer remains fatal. This prevents a restart loop without fabricating readiness or bypassing v347.

PR `#2875` added directional Fair Value Gap confirmation to `BREAK_RETEST` signal qualification. The detector defaults to requiring FVG confirmation through:

```text
NIJA_BREAK_RETEST_REQUIRE_FVG=true
```

The retest candle is excluded from FVG discovery, and missing required FVG evidence fails the signal closed. The rollback switch `NIJA_BREAK_RETEST_REQUIRE_FVG=false` exists for controlled testing, but disabling the signal qualifier does not bypass execution, protection, risk, capital, writer, nonce, or circuit-breaker gates.

PR `#2876` added the separate opt-in strategy:

```text
LIQUIDITY_FVG_RETRACE
FEATURE_LIQUIDITY_FVG_RETRACE_ENABLED
```

Its intended sequence combines completed Daily structure/FVG context with a 1H liquidity sweep, displacement, newly formed directional FVG, and retracement/rejection at the FVG edge. Both SL and TP are mandatory. The strategy is treated as a protected-entry strategy throughout the request, broadcaster, pipeline, and multi-broker routing contracts.

For live protected LIMIT entries, `LIQUIDITY_FVG_RETRACE` must remain fail-closed until the selected broker adapter explicitly proves protected-limit capability. The execution path must not silently downgrade the planned LIMIT entry to MARKET.

PR `#2877` hardened liquidity reversal qualification to require the ordered sequence:

```text
liquidity sweep
-> close back inside prior range
-> directional displacement within 1–3 candles
-> fresh directional three-candle FVG
-> first retrace into that FVG
```

Full-body structural breaks are not treated as wick sweeps. RSI, volume, CRT-style candle-range confirmation, macro liquidity, and prior-day liquidity remain secondary confluence rather than substitutes for the primary sequence.

PR `#2878` repaired a production universal-exit failure where circular startup could leave `bot.execution_pipeline` bound to a reduced fallback `PipelineRequest` that did not accept fields such as `limit_price`. The canonical submitter now detects stale dataclass-like request contracts and rebinds to `bot.pipeline_request_contract.PipelineRequest` once available. If the canonical contract is still unavailable, the path fails closed rather than constructing a known-incompatible exit request.

PR `#2878` also normalizes base-sized crypto exit units to canonical `base_asset`. The repair does not weaken writer, nonce, kill-switch, risk, capital, broker-minimum, routing, acknowledgement, or fill-confirmation gates.

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

Universal exit requests must use the canonical `bot.pipeline_request_contract.PipelineRequest` contract. A stale fallback dataclass from circular startup must be rebound when the canonical contract becomes available; if it cannot be resolved, the exit submission path must fail closed rather than issue a malformed request. Base-sized crypto exits use the canonical `base_asset` unit type.

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
- [ ] Startup may remain alive while v324/v347 readiness is false, but execution remains fail-closed until authoritative readiness converges.
- [ ] v281 `coverage_status()` returns a dict whose `ready` field is exactly boolean `True`.
- [ ] v347 remains fail-closed for missing, malformed, unavailable, or non-boolean/unready coverage status.
- [ ] Kraken heartbeat sizing satisfies both the risk cap and canonical safe quote floor, or defers before dispatch.
- [ ] Kraken canonical market discovery maps broker aliases such as `XBT` to `BTC`.
- [ ] Local pre-dispatch minimum failures are not misclassified as exchange rejections.
- [ ] If `BREAK_RETEST` is enabled, required directional FVG confirmation is present unless the explicit controlled-test rollback switch is intentionally used.
- [ ] `LIQUIDITY_FVG_RETRACE` remains opt-in and preserves its planned LIMIT price plus mandatory SL/TP through the canonical request pipeline.
- [ ] A live protected LIMIT entry is not downgraded to MARKET and remains blocked until the broker proves protected-limit capability.
- [ ] Universal exits resolve the canonical `PipelineRequest` contract and use canonical `base_asset` units for base-sized crypto exits.
- [ ] If `BREAK_RETEST` real-money entry is enabled, the selected broker reports protected-entry capability.
- [ ] A live protected entry has broker readback confirming both active stop-loss and take-profit legs.
- [ ] Protected-entry uncertainty/reconciliation paths fail closed rather than claiming success.
- [ ] Protective exits remain available and have been verified where appropriate.
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
- authoritative v281 protection coverage with strict boolean readiness,
- fail-closed v347 handling for unavailable, malformed, or unready protection status,
- fail-closed/nonfatal startup convergence without fabricated readiness,
- directional FVG qualification for `BREAK_RETEST` when required,
- protected LIMIT semantics for `LIQUIDITY_FVG_RETRACE` with no silent LIMIT-to-MARKET downgrade,
- canonical `PipelineRequest` resolution for universal exits,
- explicit protected-entry capability before real `BREAK_RETEST` dispatch,
- broker-verified stop-loss and take-profit protection for protected entries,
- fail-closed protected-entry reconciliation when protection cannot be verified,
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
