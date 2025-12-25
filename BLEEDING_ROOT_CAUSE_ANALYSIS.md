# 🚨 BLEEDING ROOT CAUSE ANALYSIS & FIX

## Current Situation
- **Starting Balance**: ~$5.05 USD
- **Current Balance**: $0.15 USD  
- **Loss**: $4.90 (97% loss)
- **Status**: Bot trying to trade with $0.01-$0.06 positions (blocked)
- **Why Blocked**: Capital guard requires minimum $5.00

---

## Root Causes of Bleeding

### 1. ❌ POSITION SIZING IS BACKWARDS
**File**: `bot/adaptive_growth_manager.py`, Line 152-160

```python
def get_position_size_pct(self) -> float:
    config = self.GROWTH_STAGES[self.current_stage]
    
    # ❌ BUG: Using min_position_pct on ultra-aggressive
    position_pct = config['min_position_pct']  # Returns 0.05 (5%)
```

**Problem**: 
- Ultra-aggressive stage has `min_position_pct: 0.05` (5%)
- On a **$5 account**, 5% = **$0.25 per trade**
- Coinbase fees = 2-4% = **$0.01 per trade**
- **Profit needed to break even: >4%**
- **Margin of error = 0%**

### 2. ❌ NO HARD POSITION MINIMUM
- Code calculates **percentage-based** position sizes
- No **dollar minimum** ($2-5 USD)
- Results in unprofitable micro-positions

### 3. ❌ MISSING STOP-LOSS ENFORCEMENT
- Positions can bleed indefinitely
- No forced exit when loss exceeds threshold
- Default stop loss might be too wide

### 4. ❌ NO CIRCUIT BREAKER
- Bot keeps trading below profit threshold
- Should stop at $5-10 and wait for deposit
- Instead: trades $0.25 positions into fees

### 5. ❌ RESERVE LOGIC INEFFECTIVE
```python
# From trading_strategy.py line 660
if live_balance < 100:
    MINIMUM_RESERVE = max(0.0, live_balance - coinbase_minimum)
```
- When balance = $5.05: reserve = $5.05 - $5.00 = **$0.05**
- Leaves only $0.00 for trading
- But code doesn't enforce this properly

---

## Why Rules Weren't Followed

### Issue 1: Min vs Max Confusion
The `min_position_pct` is meant as a **minimum** for the account to be viable, not a **minimum per trade**. On ultra-aggressive:
- `min_position_pct: 0.05` = "smallest position is 5%"
- On $5 account = $0.25 positions ✗ Not viable
- Should be: `max_position_pct: 0.05` = "never exceed 5%"

### Issue 2: No Fee Awareness Below $50
- Current logic: "smaller accounts = higher %"
- Reality: "smaller accounts = SMALLER $, fees kill profit"
- Needed: "Never trade positions smaller than fees ($2-5)"

### Issue 3: Stop Loss Not Working
If bot is bleeding at $0.15, stop losses should have prevented it
- Possible: stop losses too wide (1.5%)
- Possible: stop losses not being enforced  
- Possible: no trailing stop on small accounts

---

## Critical Fixes Required (Priority Order)

### FIX #1: Position Sizing Logic (CRITICAL)
**File**: `bot/adaptive_growth_manager.py`

Change:
```python
def get_position_size_pct(self) -> float:
    config = self.GROWTH_STAGES[self.current_stage]
    position_pct = config['min_position_pct']  # ❌ WRONG
```

To:
```python
def get_position_size_pct(self) -> float:
    config = self.GROWTH_STAGES[self.current_stage]
    position_pct = config['max_position_pct']  # ✅ CORRECT
```

**Reason**: We want SMALLER positions on small accounts, not larger ones.
- Ultra-aggressive: max_position_pct = 0.15 (15%)
- On $5 account = $0.75 (still need to fix with absolute minimum)

### FIX #2: Absolute Position Minimum (CRITICAL)
**File**: `bot/adaptive_growth_manager.py`

Add method:
```python
def get_min_position_usd(self) -> float:
    """
    Hard minimum position size in USD to avoid fee drag
    Never trade positions smaller than typical Coinbase fees
    """
    # Coinbase fee: 0.5-0.6% → need 1% minimum margin
    # Position < $2 loses money to fees
    MIN_VIABLE_POSITION = 2.00
    
    return MIN_VIABLE_POSITION
```

**Update trading_strategy.py** (line 655):
```python
calculated_size = live_balance * position_size_pct
# Apply hard caps to position size
coinbase_minimum = 5.00
min_position_usd = self.growth_manager.get_min_position_usd()  # NEW
max_position_hard_cap = self.growth_manager.get_max_position_usd()
effective_cap = min(max_position_hard_cap, self.max_position_cap_usd)

# ENFORCE: min_position_usd <= position_size <= effective_cap
position_size_usd = max(min_position_usd, calculated_size)  # NEW MIN
position_size_usd = min(position_size_usd, effective_cap, tradable_balance)

# If position too small, skip trade entirely
if position_size_usd < min_position_usd:
    logger.warning(f"Position ${position_size_usd:.2f} below minimum ${min_position_usd:.2f} - skipping")
    return False
```

### FIX #3: Stop Trading Below Threshold (CRITICAL)
**File**: `bot/trading_strategy.py` (around line 620)

Add before trade execution:
```python
# CIRCUIT BREAKER: Stop all trading if balance drops below trading minimum
MINIMUM_TRADING_BALANCE = float(os.getenv("MINIMUM_TRADING_BALANCE", "25.0"))

if live_balance < MINIMUM_TRADING_BALANCE:
    logger.error("=" * 80)
    logger.error(f"⛔ TRADING HALTED: Balance (${live_balance:.2f}) below minimum (${MINIMUM_TRADING_BALANCE:.2f})")
    logger.error(f"   Positions would be too small to profit after fees")
    logger.error(f"   Bot will pause and wait for deposit")
    logger.error("=" * 80)
    return False
```

### FIX #4: Improve Reserve Management (IMPORTANT)
**File**: `bot/trading_strategy.py` (line 660)

Current code leaves 0% tradable:
```python
if live_balance < 100:
    MINIMUM_RESERVE = max(0.0, live_balance - coinbase_minimum)
```

Better approach:
```python
if live_balance < 100:
    # Keep at least 50% as reserve on small accounts
    # Only trade with 50%, keep 50% for volatility buffer
    MINIMUM_RESERVE = live_balance * 0.5
elif live_balance < 500:
    MINIMUM_RESERVE = live_balance * 0.3  # 30% reserve
elif live_balance < 2000:
    MINIMUM_RESERVE = live_balance * 0.2  # 20% reserve
else:
    MINIMUM_RESERVE = live_balance * 0.1  # 10% reserve
```

---

## Secondary Issues

### Stop Loss Verification
Check if stop losses are actually executing:
```python
# In trading_strategy.py, search for close_full_position()
# Ensure stop loss price is correctly calculated:
stop_loss_price = entry_price * (1 - stop_loss_pct)  # For long positions
```

### Trailing Stop Verification
Confirm trailing stops are updated each candle:
```python
# Should be in position monitoring loop
# current_price > trailing_stop_price → auto-exit
```

### Order Rejection Handling
Confirm failed orders don't silently continue:
```python
# Place market order with retry
if result.get('status') != 'filled':
    logger.error(f"Order FAILED - {result.get('error')}")
    return False  # Don't continue
```

---

## Implementation Plan

### Phase 1: Immediate Fixes (Deploy Today)
1. ✅ Change `min_position_pct` → `max_position_pct` in `get_position_size_pct()`
2. ✅ Add `get_min_position_usd()` returning $2.00 minimum
3. ✅ Update trading_strategy.py to enforce minimum position size
4. ✅ Add circuit breaker at $25 minimum balance

### Phase 2: Robustness (Deploy Next)
5. ⬜ Improve reserve management for small accounts
6. ⬜ Verify stop loss enforcement
7. ⬜ Add better logging for position skips
8. ⬜ Test with small deposits ($10-20)

### Phase 3: Long-term Prevention
9. ⬜ Implement max daily loss limit
10. ⬜ Add win/loss ratio checks before trading
11. ⬜ Implement position size scaling based on streak
12. ⬜ Daily P&L report with recommendations

---

## Testing Plan

### Test 1: Position Sizing with Small Account
```python
# Simulate $10 account
manager = AdaptiveGrowthManager()
pct = manager.get_position_size_pct()  # Should return 0.15 now (max, not min)
min_pos = manager.get_min_position_usd()  # Should return 2.00

# On $10: position = $10 * 0.15 = $1.50
# But minimum = $2.00 → use $2.00 ✅
```

### Test 2: Circuit Breaker
```python
# Simulate balance dropping to $15
# Try to open new trade
# Should be blocked: balance < $25 minimum
```

### Test 3: No Fee Losses
```python
# Trade $2.00 position
# Fee: 0.6% = $0.012
# Need +1.2% gain to break even
# On RSI signal, very achievable ✅
```

---

## Files to Modify

1. **bot/adaptive_growth_manager.py**
   - Line 152: Change `min_position_pct` to `max_position_pct`
   - Add `get_min_position_usd()` method

2. **bot/trading_strategy.py**
   - Line 655: Add minimum position enforcement
   - Line 620: Add circuit breaker at $25
   - Line 660-680: Improve reserve logic

3. **bot/nija_apex_strategy_v71.py** (if handling position sizing)
   - Verify no override of position sizing

---

## Recovery Plan (Once Fixes Deployed)

1. **Deposit $25-50** to Coinbase Advanced Trade
2. **Restart bot** with new code
3. **Monitor closely** first 10 trades
4. **Check logs** for:
   - ✅ Positions opening > $2.00
   - ✅ Trailing stops working
   - ✅ Stop losses executing
   - ✅ Win rate > 50%

5. **Once stable** (24+ hours, 10+ trades):
   - Scale to 8 concurrent positions
   - Increase position size to 10-15% per trade
   - Monitor daily P&L

---

## Prevention Checklist

- [ ] Position size NEVER below $2.00 USD
- [ ] Position size NEVER above 15% of account  
- [ ] Circuit breaker prevents trading below $25
- [ ] Stop loss ALWAYS calculated before trade
- [ ] Trailing stop ALWAYS updated each candle
- [ ] Reserve maintained (30-50% on small accounts)
- [ ] Failed orders logged and skipped
- [ ] Daily P&L checked (email alert if < -5%)
- [ ] Weekly strategy review (win rate, avg profit)
