# D) LIVE EXECUTION PATH AUDIT - WHERE SELL IS BLOCKED

**Date:** January 20, 2026  
**Purpose:** Identify ALL points where SELL orders can be blocked  
**Status:** ✅ COMPLETE AUDIT

---

## Executive Summary

This document maps the complete execution path for SELL orders in the NIJA trading bot, identifying **every single point** where a sell can be blocked, filtered, or rejected. Understanding this path is critical for diagnosing why positions aren't exiting.

**Key Finding:** There are **8 distinct blocking points** where SELL orders can fail.

---

## High-Level Execution Flow

```
User/Strategy Decision to SELL
        ↓
1. Trading Strategy Layer
        ↓
2. Execution Engine Layer
        ↓
3. Broker Manager Layer (CoinbaseBroker/KrakenBroker)
        ↓
4. Broker API Layer (Coinbase/Kraken)
        ↓
SELL ORDER EXECUTED or REJECTED
```

---

## Detailed Execution Path Audit

### LAYER 1: Trading Strategy (`bot/trading_strategy.py`)

#### Checkpoint 1.1: Emergency Stop-Loss (-1.25%)

**Location:** `bot/trading_strategy.py:~1357`

**Blocking Logic:**
```python
if pnl_percent <= -1.25:
    logger.warning(f"🛑 EMERGENCY STOP LOSS HIT: {symbol} at {pnl_percent:.2f}%")
    # FORCED EXIT - bypasses all filters
    result = active_broker.place_market_order(
        symbol=symbol,
        side='sell',
        quantity=quantity,
        size_type='base'
    )
```

**Can Block Sell?** NO - This TRIGGERS forced sell  
**Bypass:** N/A - This is the emergency trigger

---

#### Checkpoint 1.2: Immediate Loss Prevention Filter

**Location:** `bot/trading_strategy.py:~1100`

**Blocking Logic:**
```python
# Check for immediate loss on entry
immediate_pnl = ((current_price - entry_price) / entry_price) * 100

if immediate_pnl < -0.50:
    logger.warning(f"⚠️ Rejecting entry with immediate loss: {symbol}")
    continue  # Skip this entry
```

**Can Block Sell?** NO - Only affects BUY decisions  
**Bypass:** N/A - Entry filter only

---

#### Checkpoint 1.3: Broker Symbol Filter (Kraken)

**Location:** `bot/trading_strategy.py:~2000`

**Blocking Logic:**
```python
if broker_name == 'kraken':
    # Kraken only supports */USD and */USDT pairs
    markets_to_scan = [
        sym for sym in markets_to_scan 
        if sym.endswith('/USD') or sym.endswith('/USDT')
    ]
```

**Can Block Sell?** NO - Filters before analysis, doesn't block existing positions  
**Impact:** Prevents buying unsupported symbols (won't have positions to sell)

---

### LAYER 2: Execution Engine (`bot/execution_engine.py`)

#### Checkpoint 2.1: Force Exit Function

**Location:** `bot/execution_engine.py:545-628`

**Blocking Logic:**
```python
def force_exit_position(self, broker_client, symbol: str, quantity: float, 
                       reason: str = "Emergency exit", max_retries: int = 1) -> bool:
    """
    FIX 5: FORCED EXIT PATH - Emergency position exit that bypasses ALL filters
    """
    # BYPASSES:
    # - Rotation mode restrictions
    # - Position caps
    # - Minimum trade size requirements
    # - Fee optimizer delays
    
    result = broker_client.place_market_order(...)
```

**Can Block Sell?** NO - This ENABLES sells, bypasses filters  
**Purpose:** Ensures emergency exits succeed

---

### LAYER 3: Broker Manager (`bot/broker_manager.py`)

This is where **MOST blocking occurs**.

#### Checkpoint 3.1: Global BUY Guard

**Location:** `bot/broker_manager.py:2118-2136`

**Blocking Logic:**
```python
# Global BUY guard: block all buys when emergency stop is active
lock_path = os.path.join(os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
hard_buy_off = (os.getenv('HARD_BUY_OFF', '0') in ('1', 'true', 'True'))

if side.lower() == 'buy' and (hard_buy_off or os.path.exists(lock_path)):
    logger.error("🛑 BUY BLOCKED at broker layer: SELL-ONLY mode")
    return {
        "status": "unfilled",
        "error": "BUY_BLOCKED",
        "message": "Global buy guard active (sell-only mode)"
    }
```

**Can Block Sell?** NO - Only blocks BUY orders  
**Purpose:** Sell-only mode for capital preservation

---

#### Checkpoint 3.2: Symbol Validation

**Location:** `bot/broker_manager.py:2081-2116`

**Blocking Logic:**
```python
# Validate symbol parameter
if not symbol:
    logger.error("❌ INVALID SYMBOL: Symbol parameter is None or empty")
    return {"status": "error", "error": "INVALID_SYMBOL"}

if not isinstance(symbol, str):
    logger.error(f"❌ INVALID SYMBOL: Symbol must be string, got {type(symbol)}")
    return {"status": "error", "error": "INVALID_SYMBOL"}

if '-' not in symbol or len(symbol) < 5:
    logger.error(f"❌ INVALID SYMBOL: Invalid format '{symbol}'")
    return {"status": "error", "error": "INVALID_SYMBOL"}
```

**Can Block Sell?** YES ⚠️  
**Condition:** If symbol is None, not a string, or invalid format  
**Fix:** Ensure symbol is valid before calling place_market_order

**Bypass:**
```python
# Always validate symbol before calling
if not symbol or not isinstance(symbol, str):
    logger.error("Invalid symbol, cannot sell")
    return
```

---

#### Checkpoint 3.3: Quantity Validation

**Location:** `bot/broker_manager.py:2138-2139`

**Blocking Logic:**
```python
if quantity <= 0:
    raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")
```

**Can Block Sell?** YES ⚠️  
**Condition:** If quantity is 0 or negative  
**Common Cause:** Position tracking out of sync

**Bypass:**
```python
# Always validate quantity before selling
if quantity <= 0:
    logger.error(f"Cannot sell zero or negative quantity: {quantity}")
    return
```

---

#### Checkpoint 3.4: Emergency Balance Check Skip (SELL OVERRIDE)

**Location:** `bot/broker_manager.py:2266-2354`

**Critical Code:**
```python
# Emergency mode: skip preflight balance calls to reduce API 429s
emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
skip_preflight = side.lower() == 'sell' and os.path.exists(emergency_file)

if not skip_preflight:
    # NORMAL MODE: Check balance
    balance_snapshot = self._get_account_balance_detailed()
    available_base = float(holdings.get(base_currency, 0.0))
    
    # FIX 2: Changed from ERROR to WARNING
    if available_base <= epsilon:
        logger.warning("⚠️ PRE-FLIGHT WARNING: Zero balance shown")
        logger.warning("   Attempting sell anyway - position may exist on exchange")
        # DON'T RETURN - continue with sell attempt
    
    if available_base < quantity:
        logger.warning("⚠️ Balance mismatch: adjusting sell size")
        quantity = available_base
else:
    logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")
```

**Can Block Sell?** NO (FIXED) ⭐  
**Previous Behavior:** Would return error if balance showed zero  
**Current Behavior:** Issues warning but continues with sell  
**Emergency Bypass:** Create `LIQUIDATE_ALL_NOW.conf` to skip ALL balance checks

**Key Changes:**
- Changed from `logger.error()` → `logger.warning()`
- Changed from `return error` → `continue with sell`
- Allows sells even if cached balance shows zero

---

#### Checkpoint 3.5: Precision/Rounding Validation

**Location:** `bot/broker_manager.py:2427-2467`

**Blocking Logic:**
```python
# Round quantity to exchange's precision requirements
num_increments = math.floor(trade_qty / base_increment)
base_size_rounded = num_increments * base_increment
base_size_rounded = round(base_size_rounded, precision)

# If rounded to zero, try full balance
if base_size_rounded <= 0 or base_size_rounded < base_increment:
    logger.warning(f"   ⚠️ Rounded size too small, attempting FULL balance")
    num_increments = math.floor(requested_qty / base_increment)
    base_size_rounded = num_increments * base_increment

# FINAL CHECK: If still too small, ERROR
if base_size_rounded <= 0 or base_size_rounded < base_increment:
    logger.error(f"   ❌ Position too small to sell with current precision rules")
    return {
        "status": "unfilled",
        "error": "INVALID_SIZE",
        "message": f"Position too small: {symbol} rounded to {base_size_rounded}"
    }
```

**Can Block Sell?** YES ⚠️  
**Condition:** Position size rounds to zero after precision adjustment  
**Common Cause:** Dust positions (< minimum increment)  
**Example:** 0.0000001 BTC with 0.00000001 increment = rounds to 0

**Bypass:**
```python
# For dust positions, manual intervention required
# These are too small for API to accept
# Coinbase/Kraken have minimum order sizes
```

**Solutions:**
1. Accumulate dust positions before selling
2. Manual sell via exchange UI
3. Accept loss and ignore dust

---

#### Checkpoint 3.6: Kraken Symbol Allowlist

**Location:** `bot/broker_integration.py:636-662` (KrakenBroker adapter)

**Blocking Logic:**
```python
# ✅ FIX 3: HARD SYMBOL ALLOWLIST FOR KRAKEN
if not (symbol.endswith('/USD') or symbol.endswith('/USDT') or 
        symbol.endswith('-USD') or symbol.endswith('-USDT')):
    logger.info(f"⏭️ Kraken skip unsupported symbol {symbol}")
    return {
        'status': 'error',
        'error': 'UNSUPPORTED_SYMBOL',
        'message': 'Kraken only supports */USD and */USDT pairs'
    }
```

**Can Block Sell?** YES ⚠️  
**Condition:** Symbol doesn't end with /USD or /USDT on Kraken  
**Example:** ETH-BUSD, BTC-EUR would be rejected

**Bypass:**
```python
# No bypass - Kraken truly doesn't support these pairs
# If you have a position in unsupported pair, use Kraken UI to exit
```

---

### LAYER 4: Broker API (`Coinbase/Kraken`)

#### Checkpoint 4.1: API Rate Limiting

**Location:** External (Coinbase/Kraken servers)

**Blocking Logic:**
- Coinbase: 10 requests/second (private endpoints)
- Kraken: 1 request/second (private endpoints)
- Returns 429 "Too Many Requests"

**Can Block Sell?** YES ⚠️  
**Condition:** Too many API calls in short time  
**Impact:** Sell order rejected with 429 error

**Bypass:**
```python
# Retry logic with backoff (already implemented)
def _with_backoff(fn, *args, **kwargs):
    delays = [1, 2, 4]
    for i, d in enumerate(delays):
        try:
            return fn(*args, **kwargs)
        except Exception as err:
            if 'Too Many Requests' in str(err) or '429' in str(err):
                logger.warning(f"⚠️ Rate limited, retrying in {d}s")
                time.sleep(d)
                continue
            raise
    return fn(*args, **kwargs)
```

**Additional Fix:** Emergency mode (`LIQUIDATE_ALL_NOW.conf`) reduces API calls

---

#### Checkpoint 4.2: Insufficient Balance (Exchange)

**Location:** External (Coinbase/Kraken servers)

**Blocking Logic:**
- Exchange checks actual balance in your account
- If balance < sell quantity, rejects order
- Returns error: "INSUFFICIENT_FUND" or similar

**Can Block Sell?** YES ⚠️  
**Condition:** Position doesn't exist on exchange (only in bot tracker)  
**Common Causes:**
- Position manually closed via exchange UI
- Position partially filled and tracker out of sync
- Wrong symbol (typo in position tracker)

**Detection:**
```python
# Zombie position detection in trading_strategy.py
broker_positions = active_broker.get_positions()
broker_symbols = {p.get('symbol') for p in broker_positions}

for symbol in tracked_positions:
    if symbol not in broker_symbols:
        logger.warning(f"🧟 ZOMBIE POSITION DETECTED: {symbol}")
        position_tracker.remove_position(symbol)
```

**Fix:** Automatic cleanup of zombie positions

---

#### Checkpoint 4.3: Order Size Too Small (Exchange)

**Location:** External (Coinbase/Kraken servers)

**Blocking Logic:**
- Coinbase minimum: ~$1-5 depending on asset
- Kraken minimum: ~0.0001-0.001 depending on asset
- Returns error: "ORDER_MIN_SIZE" or "INVALID_SIZE"

**Can Block Sell?** YES ⚠️  
**Condition:** Position value below exchange minimum  
**Example:** $0.50 worth of BTC (Coinbase minimum is $1)

**Detection:**
```python
# Check position USD value before selling
position_usd_value = quantity * current_price
if position_usd_value < 10.0:
    logger.info(f"Small position (${position_usd_value:.2f})")
```

**Fix:** Already implemented - uses minimal safety margin for small positions

---

#### Checkpoint 4.4: Symbol Not Found (Exchange)

**Location:** External (Coinbase/Kraken servers)

**Blocking Logic:**
- Exchange doesn't recognize the symbol
- Returns error: "UNKNOWN_PRODUCT_ID" or "INVALID_SYMBOL"

**Can Block Sell?** YES ⚠️  
**Condition:** Symbol format doesn't match exchange requirements  
**Examples:**
- Coinbase wants: `BTC-USD`
- Kraken wants: `XBT/USD` or `XXBTZUSD`
- Bot sends: `BTC/USD` (wrong format)

**Fix:** Symbol normalization in broker adapters

---

## Summary of Blocking Points

### Where SELL Can Be Blocked

| # | Layer | Location | Can Block? | Severity | Bypass Available? |
|---|-------|----------|------------|----------|-------------------|
| 1 | Broker Manager | Symbol Validation | YES | HIGH | No (validate symbols) |
| 2 | Broker Manager | Quantity Validation | YES | HIGH | No (fix tracker) |
| 3 | Broker Manager | Balance Check (OLD) | NO* | LOW | Yes (FIXED in code) |
| 4 | Broker Manager | Precision Rounding | YES | MEDIUM | Partial (dust issue) |
| 5 | Broker Manager | Kraken Symbol Filter | YES | MEDIUM | No (use supported symbols) |
| 6 | Exchange API | Rate Limiting | YES | MEDIUM | Yes (retry logic) |
| 7 | Exchange API | Insufficient Balance | YES | HIGH | Auto-cleanup (zombie detection) |
| 8 | Exchange API | Minimum Order Size | YES | MEDIUM | Accumulate or ignore dust |

\* Fixed in current code - now issues warning instead of blocking

---

## Critical Fixes Already Implemented

### ✅ Fix 1: Balance Check No Longer Blocks Sells

**Before:**
```python
if available_base <= epsilon:
    return {"status": "unfilled", "error": "INSUFFICIENT_FUND"}
```

**After:**
```python
if available_base <= epsilon:
    logger.warning("⚠️ PRE-FLIGHT WARNING: Zero balance shown")
    logger.warning("   Attempting sell anyway - position may exist on exchange")
    # DON'T RETURN - continue with sell
```

---

### ✅ Fix 2: Emergency Balance Skip

**Activation:**
```bash
touch LIQUIDATE_ALL_NOW.conf
```

**Effect:**
```python
if skip_preflight:
    logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")
    # All balance checks bypassed
    # Proceed directly to order placement
```

---

### ✅ Fix 3: Zombie Position Cleanup

**Detection:**
```python
broker_positions = active_broker.get_positions()
for symbol in tracked_positions:
    if symbol not in broker_positions:
        logger.warning(f"🧟 ZOMBIE POSITION DETECTED: {symbol}")
        position_tracker.remove_position(symbol)
```

---

### ✅ Fix 4: Forced Exit Path

**Usage:**
```python
# Emergency stop-loss triggers forced exit
if pnl_percent <= -1.25:
    result = force_exit_position(
        broker_client=active_broker,
        symbol=symbol,
        quantity=quantity,
        reason="Emergency stop-loss"
    )
```

**Bypasses:**
- Rotation mode
- Position caps
- Min size requirements
- All filters

---

## How to Diagnose Blocked Sells

### Step 1: Check Logs

```bash
# Search for sell-related errors
grep -i "sell" logs/trading.log | grep -E "error|blocked|failed"

# Common patterns:
grep "INVALID_SYMBOL" logs/trading.log
grep "INVALID_QUANTITY" logs/trading.log
grep "INSUFFICIENT_FUND" logs/trading.log
grep "INVALID_SIZE" logs/trading.log
grep "Too Many Requests" logs/trading.log
```

### Step 2: Verify Symbol Format

```python
# Check position tracker
from bot.position_tracker import position_tracker
positions = position_tracker.get_open_positions()

for symbol, data in positions.items():
    print(f"Symbol: {symbol}")
    print(f"  Valid format: {'-' in symbol and len(symbol) >= 5}")
    print(f"  Quantity: {data.get('quantity')}")
```

### Step 3: Check Live Balance

```bash
# Get actual balance from exchange
python3 display_broker_status.py

# Compare with tracked positions
python3 check_coinbase_positions.py
```

### Step 4: Test Precision

```python
# Check if position rounds to zero
symbol = "BTC-USD"
quantity = 0.00000001  # Very small

# Get increment
meta = broker._get_product_metadata(symbol)
base_increment = meta.get('base_increment', 0.00000001)

# Calculate rounded
import math
num_increments = math.floor(quantity / base_increment)
rounded = num_increments * base_increment

print(f"Original: {quantity}")
print(f"Increment: {base_increment}")
print(f"Rounded: {rounded}")
print(f"Will Block: {rounded <= 0}")
```

### Step 5: Enable Emergency Mode (Testing)

```bash
# Activate emergency sell override
touch LIQUIDATE_ALL_NOW.conf

# Watch logs
tail -f logs/trading.log | grep "EMERGENCY MODE"

# Try sell
# ...

# Deactivate
rm LIQUIDATE_ALL_NOW.conf
```

---

## Quick Reference: Unblock Checklist

When a sell is blocked, check in this order:

1. **Symbol Valid?**
   - [ ] Symbol is a string
   - [ ] Format: BASE-QUOTE (e.g., "BTC-USD")
   - [ ] Supported by broker (Kraken: only /USD or /USDT)

2. **Quantity Valid?**
   - [ ] Quantity > 0
   - [ ] Quantity matches position tracker
   - [ ] Position exists on exchange (not zombie)

3. **Balance Sufficient?**
   - [ ] Check actual exchange balance
   - [ ] Compare with bot tracker
   - [ ] Enable emergency mode if needed: `touch LIQUIDATE_ALL_NOW.conf`

4. **Size Acceptable?**
   - [ ] Not too small (< exchange minimum)
   - [ ] Not dust (rounds to zero)
   - [ ] Meets precision requirements

5. **API Working?**
   - [ ] No 429 rate limit errors
   - [ ] Broker connection healthy
   - [ ] No network issues

6. **Emergency Features?**
   - [ ] Force exit available for critical positions
   - [ ] Emergency mode can bypass balance checks
   - [ ] Emergency stop-loss triggers at -1.25%

---

## Exact Sell Execution Path

```
SELL DECISION
     ↓
[1] Symbol Validation ❌ Can block (invalid format)
     ↓ PASS
[2] Quantity Validation ❌ Can block (quantity <= 0)
     ↓ PASS
[3] BUY Guard Check ✅ SELL passes (only blocks buys)
     ↓ PASS
[4] Emergency Mode Check ⚡ Skip to [8] if emergency file exists
     ↓ NORMAL MODE
[5] Balance Pre-Flight ⚠️ WARNING ONLY (doesn't block anymore)
     ↓ CONTINUE
[6] Precision Rounding ❌ Can block (rounds to zero)
     ↓ PASS
[7] Kraken Symbol Filter ❌ Can block (unsupported symbol)
     ↓ PASS
[8] Order Placement → API
     ↓
[9] API Rate Limit ❌ Can block (429 error)
     ↓ RETRY
[10] Exchange Validation ❌ Can block (insufficient balance, min size)
     ↓ PASS
✅ SELL EXECUTED
```

---

## Where Sells Are Currently Blocked

Based on recent logs and issues:

### CONFIRMED BLOCKING POINTS (Active)

1. ✅ **Precision Rounding** - Dust positions round to zero
2. ✅ **Kraken Symbol Filter** - Non-USD/USDT symbols rejected
3. ✅ **API Rate Limiting** - 429 errors during high volume
4. ✅ **Insufficient Balance** - Zombie positions (tracker vs reality)

### FIXED BLOCKING POINTS (No Longer Block)

1. ✅ **Balance Check** - Now warning only, doesn't block
2. ✅ **Emergency Balance Check** - Can be bypassed completely

### NEVER BLOCKED SELLS

1. ✅ **BUY Guard** - Only blocks buys
2. ✅ **Emergency Stop-Loss** - TRIGGERS sells
3. ✅ **Force Exit** - ENABLES sells

---

## Recommended Actions

### For Immediate Relief

```bash
# 1. Enable emergency sell mode (bypasses balance checks)
touch LIQUIDATE_ALL_NOW.conf

# 2. Check for zombie positions
python3 verify_zombie_positions.py

# 3. Monitor sell execution
tail -f logs/trading.log | grep "SELL"
```

### For Long-Term Stability

1. Keep emergency mode files ready but inactive
2. Monitor for dust positions and clean up periodically
3. Ensure position tracker stays in sync with exchange
4. Use forced exit for emergency situations
5. Monitor API rate limits and adjust scan frequency

---

**Status:** ✅ AUDIT COMPLETE  
**Last Updated:** January 20, 2026  
**Next Action:** Use this audit to diagnose specific sell failures
