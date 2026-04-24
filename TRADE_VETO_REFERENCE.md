# Trade Veto Function Reference

This document points to the exact location where trades are vetoed (blocked from execution) in the NIJA trading bot.

## 📍 Primary Trade Veto Location

**File:** `bot/trading_strategy.py`

**Method:** `run_cycle()`

**Line Range:** Approximately lines 3485-3700

### Exact Function Flow

1. **Entry Point:** `run_cycle()` method is called every trading cycle
2. **Condition Checks:** Lines 3485-3690 - Multiple conditions are evaluated
3. **Skip Reasons Tracking:** Line 3485 - `skip_reasons = []` list is initialized
4. **Veto Logging:** Lines 3695-3703 - Explicit veto reasons are logged

### Key Veto Conditions (in order of evaluation)

```python
# Line 3485: Initialize skip reasons tracker
skip_reasons = []

# Line 3488-3490: Check if entries are globally blocked
if entries_blocked:
    skip_reasons.append("STOP_ALL_ENTRIES.conf is active")

# Line 3494-3497: Check position cap
if len(current_positions) >= MAX_POSITIONS_ALLOWED:
    skip_reasons.append(f"Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")

# Line 3501-3504: Check minimum balance
if account_balance < MIN_BALANCE_TO_TRADE_USD:
    skip_reasons.append(f"Insufficient balance (${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD:.2f})")

# Line 3540-3543: Check broker eligibility
if not entry_broker:
    skip_reasons.append("No eligible broker for entry (all in EXIT_ONLY or below minimum balance)")

# Line 3695-3703: Log veto reasons if conditions failed
if not can_enter:
    logger.warning("🔴 RESULT: CONDITIONS FAILED - SKIPPING MARKET SCAN")
    logger.warning("=" * 70)
    logger.warning("🚫 TRADE VETO - Signal Blocked from Execution")
    logger.warning("=" * 70)
    for idx, reason in enumerate(skip_reasons, 1):
        logger.warning(f"   Veto Reason {idx}: {reason}")
    logger.warning("=" * 70)
```

## 🔍 How to Read Veto Logs

When a trade is vetoed, you'll see this in the logs:

```
======================================================================
🚫 TRADE VETO - Signal Blocked from Execution
======================================================================
   Veto Reason 1: Position cap reached (7/7)
   Veto Reason 2: Insufficient balance ($15.00 < $25.00)
======================================================================
```

This tells you **exactly why** the bot decided not to execute a trade.

## 📊 Common Veto Reasons and Solutions

### 1. "Position cap reached (X/Y)"
**What it means:** Maximum number of open positions already held  
**Solution:** Wait for existing positions to close or increase MAX_CONCURRENT_POSITIONS

### 2. "Insufficient balance ($X < $Y)"
**What it means:** Account balance below minimum trading threshold  
**Solution:** Fund account to meet minimum balance requirement

### 3. "No eligible broker for entry (all in EXIT_ONLY or below minimum balance)"
**What it means:** All connected brokers are either in exit-only mode or have insufficient funds  
**Solution:** Check broker balances and ensure at least one broker can accept new positions

### 4. "STOP_ALL_ENTRIES.conf is active"
**What it means:** Global entry blocking file exists (emergency stop)  
**Solution:** Remove the STOP_ALL_ENTRIES.conf file to resume trading

### 5. "LIVE_CAPITAL_VERIFIED=false"
**What it means:** Safety switch preventing live trading  
**Solution:** Set LIVE_CAPITAL_VERIFIED=true in environment when ready for live trading

## 🛠️ Debugging Trade Vetoes

If trades aren't executing, check logs for:

1. **Look for veto messages:**
   ```bash
   grep "TRADE VETO" nija.log
   ```

2. **Check current conditions:**
   ```bash
   grep "CONDITION FAILED" nija.log
   ```

3. **Verify broker status:**
   ```bash
   grep "PLATFORM ACCOUNT" nija.log
   ```

4. **Check balance:**
   ```bash
   grep "LIVE MULTI-BROKER CAPITAL" nija.log
   ```

## 🔗 Related Files

- **Main Strategy:** `bot/trading_strategy.py` (lines 3485-3700)
- **Broker Manager:** `bot/broker_manager.py` (broker eligibility checks)
- **Tier Config:** `bot/tier_config.py` (minimum balance enforcement)
- **Position Cap Enforcer:** `bot/position_cap_enforcer.py` (position limits)

## 📝 Code Snippet for Custom Veto Logging

If you want to add custom veto reasons in other parts of the code:

```python
# Example: Add custom veto reason
skip_reasons.append("Custom reason: market volatility too high")

# The existing logging will automatically include this reason
# in the veto message when can_enter = False
```

## 🎯 Quick Reference: Where to Look

| What You Want | File | Method/Line |
|--------------|------|-------------|
| **Trade veto decision** | `bot/trading_strategy.py` | `run_cycle()` lines 3485-3700 |
| **Veto logging** | `bot/trading_strategy.py` | `run_cycle()` lines 3695-3703 |
| **Status banner** | `bot/trading_strategy.py` | `_display_user_status_banner()` line ~1309 |
| **Heartbeat trade** | `bot/trading_strategy.py` | `_execute_heartbeat_trade()` line ~1368 |
| **Broker eligibility** | `bot/trading_strategy.py` | `_select_entry_broker()` (called in run_cycle) |
| **Position cap check** | `bot/position_cap_enforcer.py` | Various methods |

## 🚀 Next Steps

After understanding where trades are vetoed:

1. Monitor logs with explicit veto reasons
2. Adjust configuration to reduce unwanted vetoes
3. Fund accounts appropriately to meet minimum balances
4. Use heartbeat trade to verify execution pipeline works

---

**Pro Tip:** Set `HEARTBEAT_TRADE=true` to execute a test trade and verify the entire execution pipeline (credentials → order placement → execution → position close) works end-to-end. This proves no vetoes are blocking execution.
