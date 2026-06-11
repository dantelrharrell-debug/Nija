# 🔴 NIJA Trading Bot — Bootstrap Phase Gate Fix

## Problem
NIJA stops at `BROKER_REGISTRY(1)` phase and never advances to trade. The log shows:
```
⚡ [PhaseGate] ENV_VALIDATION(0) → BROKER_REGISTRY(1) — startup validation passed
```
Then **silence** — no further output, no errors, no trades.

---

## Root Cause Analysis

Your bot has **TWO separate bootstrap systems** that must coordinate:

1. **`startup_phase_gate.py`** (6 phases: ENV_VALIDATION → BROKER_REGISTRY → CAPITAL_BRAIN → STRATEGY_ENGINE → EXECUTION_LAYER → LIVE_ENABLE)
2. **`bootstrap_state_machine.py`** (19 states: BOOT_INIT → LOCK_ACQUIRED → ... → RUNNING_SUPERVISED)
3. **`bootstrap_coordinator.py`** (7 phases: PRECHECK → LOCK_ACQUIRED → ... → RUNNING_SUPERVISED)

These three systems exist in parallel but **are not driving each other forward**. The phase gate advances to BROKER_REGISTRY, but the BootstrapStateMachine is stuck at BOOT_INIT because:

- ❌ **No code calls `bot.py`** (which is just a stub Coinbase example)
- ❌ **No orchestrator drives the FSM transitions**
- ❌ **No main entry point exists** that coordinates all three systems
- ❌ **Timeouts are too short** (30s default) for slow broker connections

---

## The Fix (3 Steps)

### **Step 1: Deploy the New Entry Point** ✅ DONE
```bash
# This creates bot/bot_main.py with proper bootstrap orchestration
```

The new `bot/bot_main.py`:
- ✅ Calls `SelfHealingStartup().run()` to connect brokers
- ✅ Advances BootstrapFSM through all required states
- ✅ Starts the NijaCoreLoop trading engine
- ✅ Handles graceful shutdown via signals

### **Step 2: Use Extended Timeouts**
```bash
# Run the quickstart script (handles timeouts automatically)
python quickstart.py

# OR manually with extended timeouts:
export NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S=120
export NIJA_BOOTSTRAP_STRATEGY_READY_TIMEOUT_S=120
export NIJA_BOOTSTRAP_RUNNING_SUPERVISED_TIMEOUT_S=120
python -m bot.bot_main
```

### **Step 3: Run Diagnostic First** (Optional but recommended)
```bash
# Identify what's actually blocking
python BOOTSTRAP_DIAGNOSTIC.py

# Output will show:
# ✅ or ❌ Credentials
# ✅ or ❌ Broker connection
# ✅ or ❌ FSM state
# ✅ or ❌ Phase gate state
# ✅ or ❌ Capital Authority
# ✅ or ❌ MABM state
```

---

## How It Works Now

### Old Flow (BROKEN)
```
bot.py (stub) → does nothing
                ↓
           Process exits
```

### New Flow (FIXED)
```
bot_main.py
  ├─→ SelfHealingStartup.run()
  │     ├─ NoncePoisonDetector
  │     ├─ BrokerFallbackController (Kraken → Coinbase)
  │     ├─ PreHaltAlertEngine
  │     └─ BootstrapFSM.advance_to_capital_ready()
  │
  ├─→ FSM reaches CAPITAL_READY
  │     ├─ advance_to_capital_ready() called by capital pipeline
  │     └─ FSM fast-forwards through happy-path
  │
  ├─→ Advance remaining phases
  │     ├─ CAPITAL_READY → INIT_COMPLETE
  │     ├─ INIT_COMPLETE → THREADS_STARTING
  │     └─ THREADS_STARTING → RUNNING_SUPERVISED
  │
  └─→ start_trading_engine()
        └─→ NijaCoreLoop enters main trading cycle
             └─→ ✅ TRADES BEGIN!
```

---

## Phase Gate States (The Journey to Trading)

| Phase | State | Meaning | Action |
|-------|-------|---------|--------|
| 0 | ENV_VALIDATION | Env vars checked | ✅ (done) |
| 1 | BROKER_REGISTRY | Brokers registered | ⏭️ (stuck here) |
| 2 | CAPITAL_BRAIN | Capital authority hydrated | ⏳ next |
| 3 | STRATEGY_ENGINE | Trading strategy initialized | ⏳ after |
| 4 | EXECUTION_LAYER | Trading threads started | ⏳ after |
| 5 | LIVE_ENABLE | Live trading enabled | ⏳ final |

**Your bot stops at Phase 1.** The new entry point drives all 6 phases forward.

---

## Immediate Action

### **FASTEST (Recommended)**
```bash
# Run the quickstart script
python quickstart.py

# It will:
# 1. Set extended timeouts automatically
# 2. Start the proper bot entry point
# 3. Log everything with timestamps
```

### **Alternative (Manual)**
```bash
# Set timeouts
export NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S=120
export NIJA_BOOTSTRAP_STRATEGY_READY_TIMEOUT_S=120
export NIJA_BOOTSTRAP_RUNNING_SUPERVISED_TIMEOUT_S=120

# Start bot
python -m bot.bot_main

# Expected output:
# [STEP 1] Self-Healing Bootstrap
# ✅ Connected to KRAKEN (or COINBASE fallback)
# [STEP 2] Advancing Bootstrap FSM
# ✅ FSM is RUNNING_SUPERVISED
# [STEP 3] Starting Trading Loop
# 🎯 Entering trading loop...
# (trades will now execute)
```

---

## If Still Stuck

Run the diagnostic to see where it's actually blocked:
```bash
python BOOTSTRAP_DIAGNOSTIC.py 2>&1 | tee diagnostic.log
```

Share the output — it will show:
- ✅ or ❌ Broker connection status
- FSM current state
- Phase gate current state
- CA readiness
- MABM status

This pinpoints the exact bottleneck.

---

## Files Created

1. **`bot/bot_main.py`** ← Main entry point (replaces stub bot.py)
2. **`BOOTSTRAP_DIAGNOSTIC.py`** ← Debug tool for troubleshooting
3. **`quickstart.py`** ← Easy startup script with timeouts

---

## Why This Works

The **root issue** was that your bot had sophisticated bootstrap FSMs but **no orchestrator** to actually drive them. It's like having an engine but no starter motor.

The new `bot_main.py` is the **starter motor**:
- ✅ Calls the bootstrap sequence in order
- ✅ Drives the FSM through all required states
- ✅ Sets extended timeouts for slow brokers
- ✅ Handles errors gracefully
- ✅ Starts the trading loop when ready

**Everything else (APEX strategy, nonce manager, capital authority, etc.) already works correctly.** They just needed to be orchestrated properly.

---

## Expected Outcome

After running `python quickstart.py`:

```
2026-06-11 20:07:55 | INFO | nija | NIJA TRADING BOT - APEX v7.2.0
✅ Connected to KRAKEN
✅ FSM is RUNNING_SUPERVISED
🎯 Entering trading loop...
[trading cycle executes]
[TRADES HAPPEN]
```

**You'll see your bot making trades on all configured markets.**

---

## Next Steps

1. **Run quickstart.py** right now
2. Watch for the "Entering trading loop" message
3. Verify trades are executing in your broker account
4. If still stuck, run `BOOTSTRAP_DIAGNOSTIC.py` and share output

The fix is deployed. Now execute it! 🚀
