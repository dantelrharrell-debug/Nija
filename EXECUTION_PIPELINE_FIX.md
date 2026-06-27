# Execution Pipeline Fix — Zero Trades Blocker Resolution

## Problem

Nija was generating valid entry signals (scores 36–76) with `Trade allowed: True` logged every
cycle, but **zero orders were ever submitted to Kraken or Coinbase** across 3000+ trading cycles.
Orders were being silently dropped inside the execution pipeline before reaching any broker.

## Root Cause Analysis

The execution pipeline has **multiple sequential gates** that must all pass before an order
reaches a broker. With a standard `LIVE_CAPITAL_VERIFIED=true` deployment that lacks Redis
distributed locking infrastructure, **every single order was blocked at one of these gates**
with no actionable log output:

### Gate 1 — ECEL Execution Compiler (hardcoded `_ecel_required = True`)

The ECEL (Execution Compiler and Exchange Layer) is a pre-trade order normaliser that validates
order sizes against exchange step-size rules. It was **hardcoded as mandatory** — if ECEL fails
to load (e.g. schema endpoints unreachable at startup) or fails to compile an order, the order
is silently dropped with only a DEBUG-level log.

### Gate 2 — Fencing Token (`NIJA_WRITER_FENCING_TOKEN`)

When `LIVE_CAPITAL_VERIFIED=true` and no `NIJA_WRITER_FENCING_TOKEN` is set, the pipeline
raises `RuntimeError("LIVE EXECUTION DISABLED: Missing fencing token")`. This token is normally
set by a Redis distributed writer-lock heartbeat — which is not present in single-instance
Railway deployments without Redis.

### Gate 3 — Runtime Authority Convergence (`runtime_authority_snapshot`)

The `runtime_authority_snapshot()` function checks whether the startup coordinator has committed
to `lifecycle_phase=LIVE`. Without Redis and a distributed writer lock, this snapshot always
returns `ready=False` with `lifecycle_phase=BOOT`, blocking all orders.

### Gate 4 — `assert_execution_dispatch_permitted()`

This calls `can_execute()` which checks: lifecycle phase, Redis lease validity, lease generation,
nonce authority, heartbeat freshness, broker health, circuit breaker state, and stability
governor. **All of these fail** without Redis infrastructure, blocking every order.

## Fix

### Changes to `bot/execution_pipeline.py`

1. **`_ecel_required` and `_ecel_fail_closed` are now configurable via env vars** instead of
   being hardcoded to `True`. Set `NIJA_ECEL_REQUIRED=false` to allow orders to bypass ECEL
   when the compiler is unavailable.

2. **`NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true` now bypasses the fencing token gate** in
   addition to the existing `FORCE_TRADE=true` bypass. This is the correct flag for
   single-instance Railway deployments without Redis.

3. **`NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true` now bypasses the runtime authority
   convergence check** — the `runtime_authority_snapshot().ready=False` gate no longer blocks
   orders when this flag is set.

4. **`NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true` now bypasses `assert_execution_dispatch_permitted()`**
   — the full lifecycle/lease/nonce/heartbeat gate stack is skipped for single-instance
   deployments.

5. **Comprehensive INFO/WARNING/ERROR logging added at every gate** so the exact blocking reason
   is always visible in logs. Every order now logs its gate configuration on entry.

## Required Environment Variables

To enable live order execution on a single-instance Railway deployment **without Redis**:

```env
# Core live trading flag (already set)
LIVE_CAPITAL_VERIFIED=true

# CRITICAL: Bypass distributed Redis writer-lock requirement for single-instance deployments.
# Without this, ALL orders are blocked at the fencing token gate, runtime authority gate,
# and execution dispatch gate.
NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true

# Optional: Bypass ECEL if schema endpoints are unreachable at startup.
# ECEL normalises order sizes to exchange step-size rules. Disabling it means
# raw USD notional values are sent directly to the broker — safe for market orders
# on Kraken/Coinbase which accept notional USD sizing.
NIJA_ECEL_REQUIRED=false

# Optional: Allow ECEL compile exceptions to fall through instead of blocking.
NIJA_ECEL_FAIL_CLOSED=false
```

### Minimal fix (recommended for Railway single-instance):

```env
LIVE_CAPITAL_VERIFIED=true
NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true
```

### If ECEL is also blocking (check logs for "ECEL GATE BLOCKING"):

```env
LIVE_CAPITAL_VERIFIED=true
NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true
NIJA_ECEL_REQUIRED=false
NIJA_ECEL_FAIL_CLOSED=false
```

## How to Diagnose

After deploying this fix, every order will log its gate configuration:

```
🔧 [Pipeline.execute] GATE CONFIG | ecel_required=True ecel_loaded=True ecel_fail_closed=True |
   live_capital_verified=true fencing_token=False | force_local_writer_fallback=false |
   router=True multi_router=True | throttler=True pre_trade_risk=True
```

If `fencing_token=False` and `force_local_writer_fallback=false`, set
`NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true`.

If `ecel_loaded=False` and `ecel_required=True`, set `NIJA_ECEL_REQUIRED=false`.

## Gate Flow (after fix)

```
Signal generated → execute_entry() called
  ↓
ExecutionPipeline.execute()
  ↓ [Gate 1] SafetyController: mode=LIVE, allowed=True ✅
  ↓ [Gate 2] CapitalMarginAuthorization: spot order, no ledger required ✅
  ↓ [Gate 3] ECEL compile: normalise size to exchange step-size ✅ (or bypassed)
  ↓ [Gate 4] BrokerCapabilities: symbol supported ✅
  ↓ [Gate 5] TradeThrottler: rate limit check ✅
  ↓ [Gate 6] RiskGovernor: portfolio risk check ✅
  ↓ [Gate 7] SlippageGuard: spread/slippage check ✅
  ↓ [Gate 8] Fencing token: present OR NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true ✅
  ↓ [Gate 9] SEAK halt check ✅
  ↓ [Gate 10] runtime_authority_snapshot: ready OR bypass flag set ✅
  ↓ [Gate 11] assert_execution_dispatch_permitted: passed OR bypass flag set ✅
  ↓
_dispatch() → MultiBrokerExecutionRouter → Kraken/Coinbase API ✅
```
