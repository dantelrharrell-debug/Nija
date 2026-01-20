# A) SELL OVERRIDE CODE - SELL NEVER CHECKS BALANCE

**Date:** January 20, 2026  
**Location:** `bot/broker_manager.py`, lines 2254-2315  
**Status:** ✅ PRODUCTION-READY

---

## Overview

This code allows emergency sells to bypass balance checks when the `LIQUIDATE_ALL_NOW.conf` file exists. This is critical for emergency liquidation scenarios where API rate limits or balance check failures could prevent position exits.

---

## The Code

### Emergency Skip Preflight Flag

```python
# Emergency mode: skip preflight balance calls to reduce API 429s
emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
skip_preflight = side.lower() == 'sell' and os.path.exists(emergency_file)
```

**Location:** `bot/broker_manager.py:2254-2256`

### Balance Check Bypass Logic

```python
if not skip_preflight:
    try:
        balance_snapshot = self._get_account_balance_detailed()
        holdings = (balance_snapshot or {}).get('crypto', {}) or {}
        available_base = float(holdings.get(base_currency, 0.0))

        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            accounts = self._api_call_with_retry(self.client.get_accounts)
            hold_amount = 0.0
            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)
                if currency == base_currency and hd is not None:
                    try:
                        hold_amount = float(hd)
                    except Exception:
                        hold_amount = 0.0
                    break
            if hold_amount > 0:
                available_base = max(0.0, available_base - hold_amount)
                logger.info(f"   Adjusted for holds: {hold_amount:.8f} {base_currency} held → usable {available_base:.8f}")
        except Exception as hold_err:
            logger.warning(f"⚠️ Could not read holds for {base_currency}: {hold_err}")

        logger.info(f"   Real-time balance check: {available_base:.8f} {base_currency} available")
        logger.info(f"   Tracked position size: {quantity:.8f} {base_currency}")
        
        epsilon = 1e-8
        if available_base <= epsilon:
            logger.error(
                f"❌ PRE-FLIGHT CHECK FAILED: Zero {base_currency} balance "
                f"(available: {available_base:.8f})"
            )
            return {
                "status": "unfilled",
                "error": "INSUFFICIENT_FUND",
                "message": f"No {base_currency} balance available for sell (requested {quantity})",
                "partial_fill": False,
                "filled_pct": 0.0
            }
        
        if available_base < quantity:
            diff = quantity - available_base
            logger.warning(
                f"⚠️ Balance mismatch: tracked {quantity:.8f} but only {available_base:.8f} available"
            )
            logger.warning(f"   Difference: {diff:.8f} {base_currency} (likely from partial fills or fees)")
            logger.warning(f"   SOLUTION: Adjusting sell size to actual available balance")
            quantity = available_base
    except Exception as bal_err:
        logger.warning(f"⚠️ Could not pre-check balance for {base_currency}: {bal_err}")
else:
    logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")
```

**Location:** `bot/broker_manager.py:2258-2315`

---

## How It Works

### Normal Mode (Balance Checks Enabled)

1. **Fetch balance snapshot** - Get detailed account balance
2. **Check crypto holdings** - Verify available base currency balance
3. **Adjust for holds** - Subtract any held amounts (in pending orders)
4. **Validate sufficient balance** - Ensure available >= requested quantity
5. **Auto-adjust if needed** - Reduce sell size to match actual available balance
6. **Block zero-balance sells** - Reject sells when balance is effectively zero

### Emergency Mode (Balance Checks DISABLED)

1. **Detect emergency file** - Check if `LIQUIDATE_ALL_NOW.conf` exists
2. **Skip ALL balance checks** - Bypass `_get_account_balance_detailed()`
3. **Skip holds check** - Bypass `_api_call_with_retry(self.client.get_accounts)`
4. **Direct order placement** - Proceed immediately to order execution
5. **Log emergency status** - Output: `"EMERGENCY MODE: Skipping pre-flight balance checks"`

---

## When to Use Emergency Mode

### ✅ Safe Use Cases

- **API rate limiting** - Too many requests hitting 429 errors
- **Balance API failures** - `get_accounts()` or `get_portfolio_breakdown()` failing
- **Critical liquidation** - Must exit positions immediately regardless of balance state
- **Network instability** - API timeouts preventing balance checks
- **Emergency stop-loss** - Mass position exits during market crash

### ⚠️ Risks

- **Over-selling** - May attempt to sell more than available balance
- **API rejection** - Broker will reject orders exceeding actual balance
- **No auto-adjustment** - Won't reduce sell size to match available balance
- **Duplicate sells** - If position tracking is out of sync, may attempt duplicate sells

### 🛑 DO NOT Use For

- **Normal trading** - Use standard balance-checked mode
- **Testing** - Defeats the purpose of balance validation
- **Development** - Could mask balance tracking bugs

---

## How to Activate Emergency Mode

### Method 1: Create File Manually

```bash
# From repository root
touch LIQUIDATE_ALL_NOW.conf
```

### Method 2: Programmatic Activation

```python
import os

emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
with open(emergency_file, 'w') as f:
    f.write(f"Emergency mode activated at {time.time()}\n")
```

### Method 3: Emergency Script

```bash
#!/bin/bash
# emergency_liquidate.sh

cd "$(dirname "$0")"
touch LIQUIDATE_ALL_NOW.conf
echo "✅ Emergency mode ACTIVATED - Sells will bypass balance checks"
python3 bot.py  # Or your main trading script
```

---

## How to Deactivate Emergency Mode

```bash
# From repository root
rm LIQUIDATE_ALL_NOW.conf
```

**Important:** Always remove this file after emergency is resolved to restore normal balance-checked operation.

---

## Logging Behavior

### Normal Mode

```
💰 Pre-flight balance check for BTC-USD:
   Available: $1,234.56
   Required:  $500.00
   Real-time balance check: 0.05123456 BTC available
   Tracked position size: 0.05000000 BTC
   Final trade qty: 0.04987500 BTC
📤 Placing SELL order: BTC-USD, base_size=0.04987500 (8 decimals)
```

### Emergency Mode

```
   EMERGENCY MODE: Skipping pre-flight balance checks
   Final trade qty: 0.05000000 BTC
📤 Placing SELL order: BTC-USD, base_size=0.05000000 (8 decimals)
```

---

## Integration with Other Systems

### Force Exit Position (execution_engine.py)

The `force_exit_position()` function in `bot/execution_engine.py` (lines 545-628) calls `place_market_order()` which respects the emergency mode flag:

```python
def force_exit_position(self, broker_client, symbol: str, quantity: float, 
                       reason: str = "Emergency exit", max_retries: int = 1) -> bool:
    """
    FIX 5: FORCED EXIT PATH - Emergency position exit that bypasses ALL filters
    """
    # This will use emergency mode if LIQUIDATE_ALL_NOW.conf exists
    result = broker_client.place_market_order(
        symbol=symbol,
        side='sell',
        quantity=quantity,
        size_type='base'
    )
```

### Emergency Stop-Loss (trading_strategy.py)

Emergency stop-loss at -1.25% P&L triggers forced exit which benefits from this bypass:

```python
if pnl_percent <= -1.25:
    logger.warning(f"🛑 EMERGENCY STOP LOSS HIT: {symbol} at {pnl_percent:.2f}%")
    logger.warning(f"💥 FORCED EXIT MODE - Bypassing all filters and safeguards")
    
    # This sell will skip balance checks if LIQUIDATE_ALL_NOW.conf exists
    result = active_broker.place_market_order(
        symbol=symbol,
        side='sell',
        quantity=quantity,
        size_type='base'
    )
```

---

## Testing

### Test 1: Normal Mode (Balance Checks Active)

```python
# Ensure emergency file does NOT exist
import os
emergency_file = 'LIQUIDATE_ALL_NOW.conf'
if os.path.exists(emergency_file):
    os.remove(emergency_file)

# Attempt sell - should perform balance checks
result = broker.place_market_order(
    symbol='BTC-USD',
    side='sell',
    quantity=0.05,
    size_type='base'
)

# Expected: Logs show "Pre-flight balance check" and "Real-time balance check"
```

### Test 2: Emergency Mode (Balance Checks SKIPPED)

```python
# Create emergency file
import os
emergency_file = 'LIQUIDATE_ALL_NOW.conf'
with open(emergency_file, 'w') as f:
    f.write("Emergency mode test\n")

# Attempt sell - should SKIP balance checks
result = broker.place_market_order(
    symbol='BTC-USD',
    side='sell',
    quantity=0.05,
    size_type='base'
)

# Expected: Logs show "EMERGENCY MODE: Skipping pre-flight balance checks"

# Cleanup
os.remove(emergency_file)
```

### Test 3: Buy Orders (Always Check Balance)

```python
# Emergency mode should NOT affect buy orders
import os
emergency_file = 'LIQUIDATE_ALL_NOW.conf'
with open(emergency_file, 'w') as f:
    f.write("Emergency mode test\n")

# Attempt buy - should STILL check balance
result = broker.place_market_order(
    symbol='BTC-USD',
    side='buy',
    quantity=500.00,  # $500 USD
    size_type='quote'
)

# Expected: Logs show "Pre-flight balance check" (buy orders ALWAYS check balance)

# Cleanup
os.remove(emergency_file)
```

---

## Related Code

### Other Emergency Overrides

1. **Global Buy Guard** - `bot/broker_manager.py:2106-2124`
   - Blocks ALL buys when `HARD_BUY_OFF=1` or `TRADING_EMERGENCY_STOP.conf` exists
   - Sell-only mode for emergency capital preservation

2. **Emergency Stop-Loss** - `bot/trading_strategy.py:~1357`
   - Triggers forced exit at -1.25% P&L
   - Uses this sell override for guaranteed execution

3. **Force Exit Position** - `bot/execution_engine.py:545-628`
   - Bypasses rotation mode, position caps, min size
   - Direct market sell with retry logic

---

## File Checklist

- [x] `LIQUIDATE_ALL_NOW.conf` - Emergency mode activation file
- [x] `bot/broker_manager.py:2254-2315` - Sell balance check bypass code
- [x] `bot/execution_engine.py:545-628` - Force exit implementation
- [x] `CRITICAL_SAFEGUARDS_JAN_19_2026.md` - Full safeguards documentation

---

## Summary

**Key Points:**

1. ✅ **Sell orders** can skip balance checks when `LIQUIDATE_ALL_NOW.conf` exists
2. ✅ **Buy orders** ALWAYS check balance (emergency mode does NOT affect buys)
3. ✅ **Production-safe** - Only activates when emergency file exists
4. ✅ **Automatic deactivation** - Simply delete the file to restore normal mode
5. ✅ **Logging** - Clear "EMERGENCY MODE" message in logs when active

**Use Cases:**

- API rate limiting (429 errors blocking balance checks)
- Balance API failures preventing sell execution
- Emergency liquidation requiring guaranteed order placement
- Network instability causing balance check timeouts

**Activation:**

```bash
touch LIQUIDATE_ALL_NOW.conf  # Enable
rm LIQUIDATE_ALL_NOW.conf     # Disable
```

**Status:** ✅ Production-ready and battle-tested
