# NIJA Exit Logic Code Path Map

## Executive Summary

**CRITICAL BUG FOUND**: Profit targets are in percentage format (4.0 = 4%) but are compared to fractional PnL values (0.04 = 4%), causing profit-taking to NEVER trigger.

## Exit Code Flow (Every 2.5 min cycle)

### Entry Point
- **File**: `bot/trading_strategy.py`
- **Method**: `run_cycle(broker, user_mode)`
- **Line**: ~2380

### Flow Steps

#### 1. Mode Determination (Lines 2395-2420)
```python
# CRITICAL SAFETY CHECK
if self.safety.is_trading_allowed():
    if not trading_allowed and not user_mode:
        user_mode = True  # Force management-only mode
        
# Managing-only mode determined by:
managing_only = user_mode OR entries_blocked OR (positions >= MAX_POSITIONS)
```

**Triggers for Managing-Only Mode:**
- ✅ `STOP_ALL_ENTRIES.conf` exists
- ✅ Position cap reached (8+ positions)
- ✅ Safety check fails
- ✅ `user_mode=True` parameter

#### 2. Position Fetch (Lines 2520-2600)
```python
current_positions = []
# Fetch from ALL connected brokers
for broker in multi_account_manager.platform_brokers:
    positions = broker.get_positions()
    current_positions.extend(positions)
```

#### 3. Managing-Only Detection & Logging (Lines 2602-2630)
```python
if managing_only and len(current_positions) > 0:
    logger.info("💰 PROFIT REALIZATION ACTIVE (Management Mode)")
    # Lists all active exit logic:
    # - Take-profit targets
    # - Trailing stops  
    # - Stop-loss protection
    # - Time-based exits
```

#### 4. Legacy Position Drain Mode (Lines 2794-2810)
```python
positions_over_cap = len(current_positions) - MAX_POSITIONS_ALLOWED
if positions_over_cap > 0:
    logger.info("🔥 LEGACY POSITION DRAIN MODE ACTIVE")
    # Drains 1-3 positions per cycle
    # Ranks by PnL, age, size
    # Blocks new entries until under cap
```

#### 5. Position Analysis Loop (Lines 2806-3700)

For each open position:

##### 5a. Skip Unsellable Positions (Lines 2814-2825)
```python
if symbol in self.unsellable_positions:
    if time_since_marked < 24h:
        continue  # Skip for 24h
    else:
        retry  # Attempt to sell again
```

##### 5b. Fetch Current Price (Lines 2830-2840)
```python
current_price = position_broker.get_current_price(symbol)
position_value = current_price * quantity
```

##### 5c. Small Position Auto-Exit (Lines 2850-2865)
```python
if position_value < MIN_POSITION_VALUE:
    # Auto-exit positions under $1
    positions_to_exit.append({...})
    continue
```

##### 5d. PnL Calculation (Lines 2870-2920)
```python
if position_tracker:
    pnl_data = position_tracker.calculate_pnl(symbol, current_price)
    pnl_percent = pnl_data['pnl_percent']  # FRACTIONAL format (0.02 = 2%)
    pnl_dollars = pnl_data['pnl_dollars']
    entry_price = pnl_data['entry_price']
    
    # Validation
    assert abs(pnl_percent) < 1.0  # Must be fractional
```

##### 5e. Profit Target Checking (Lines 3193-3238) **🚨 CRITICAL BUG HERE**

```python
# Get broker-specific profit targets
if broker_type == BrokerType.KRAKEN:
    profit_targets = PROFIT_TARGETS_KRAKEN  # [(4.0, "..."), (3.0, "...")]
    min_threshold = 0.005  # Fractional (0.5%)
elif broker_type == BrokerType.COINBASE:
    profit_targets = PROFIT_TARGETS_COINBASE  # [(5.0, "..."), (3.5, "...")]
    min_threshold = MIN_PROFIT_THRESHOLD  # 0.020 (2.0%)

# 🚨 BUG: target_pct is in percentage format (4.0 = 4%)
#         but pnl_percent is in fractional format (0.04 = 4%)
for target_pct, reason in profit_targets:
    if pnl_percent >= target_pct:  # ❌ NEVER TRUE: 0.04 >= 4.0 is False!
        if pnl_percent >= min_threshold:
            if managing_only:
                logger.info("💰 PROFIT REALIZATION (MANAGEMENT MODE)")
            positions_to_exit.append({...})
            break
```

**Current Bug Impact:**
- Profit targets NEVER fire
- Positions held indefinitely
- No profit realization happening

**Fix Required:**
```python
# Convert target_pct from percentage to fractional
for target_pct, reason in profit_targets:
    target_fractional = target_pct / 100.0  # 4.0 -> 0.04
    if pnl_percent >= target_fractional:
        ...
```

##### 5f. Stop-Loss Checking (Lines 3239-3285)
```python
# Catastrophic stop (-5%)
if pnl_percent <= STOP_LOSS_EMERGENCY:  # -0.05
    if managing_only:
        logger.warning("💰 LOSS PROTECTION (MANAGEMENT MODE)")
    positions_to_exit.append({...})

# Standard stop (-1.5%)  
elif pnl_percent <= STOP_LOSS_THRESHOLD:  # -0.015
    if managing_only:
        logger.warning("💰 LOSS PROTECTION (MANAGEMENT MODE)")
    positions_to_exit.append({...})
```

##### 5g. Time-Based Exits (Lines 3290-3450)
```python
# Position age check
if entry_time_available:
    if position_age_hours >= MAX_POSITION_HOLD_HOURS:  # 24h
        positions_to_exit.append({...})
    elif position_age_hours >= MAX_POSITION_HOLD_EMERGENCY:  # 48h
        positions_to_exit.append({...})
```

##### 5h. Forced Drain for Over-Cap (Lines 3640-3710)
```python
if len(current_positions) > MAX_POSITIONS_ALLOWED:
    # Force-sell weakest positions (sorted by size)
    remaining_positions = [p for p not in positions_to_exit]
    remaining_sorted = sorted(remaining_positions, key=position_value)
    
    positions_needed = (current - MAX) - len(positions_to_exit)
    for pos in remaining_sorted[:positions_needed]:
        positions_to_exit.append({...})
```

#### 6. Concurrent Exit Execution (Lines 3714-3850)
```python
if positions_to_exit:
    logger.info(f"🔴 CONCURRENT EXIT: Selling {len(positions_to_exit)} positions NOW")
    
    for pos_data in positions_to_exit:
        symbol = pos_data['symbol']
        quantity = pos_data['quantity']
        reason = pos_data['reason']
        exit_broker = pos_data['broker']
        
        # Execute sell order
        result = exit_broker.place_market_order(
            symbol=symbol,
            side='sell',
            quantity=quantity,
            force_liquidate=True  # For Coinbase protective exits
        )
        
        # Track results
        if success:
            successful_sells.append(symbol)
        else:
            failed_sells.append(symbol)
    
    # Summary logging
    logger.info(f"✅ Successfully sold: {len(successful_sells)}")
    logger.info(f"❌ Failed to sell: {len(failed_sells)}")
```

## Exit Conditions Summary

### Always Active (Even When Entries Blocked)

1. **Take-Profit Targets** (CURRENTLY BROKEN - see bug above)
   - Kraken: 4.0%, 3.0%, 2.0%, 1.5%, 1.0%
   - Coinbase: 5.0%, 3.5%, 2.5%, 2.0%, 1.6%

2. **Stop-Loss Protection** (WORKING)
   - Catastrophic: -5.0%
   - Standard: -1.5%
   - Micro: -0.05%

3. **Time-Based Exits** (WORKING)
   - Standard: 24 hours
   - Emergency: 48 hours

4. **Small Position Cleanup** (WORKING)
   - Auto-exit positions < $1.00

5. **Legacy Drain Mode** (WORKING)
   - Triggers when positions > MAX_POSITIONS
   - Sells 1-3 weakest positions per cycle
   - Ranks by size (smallest first)

### Proof of Independence

The exit logic runs **completely independently** of entry logic:

```python
# Exit logic happens BEFORE entry logic check
# Lines 2806-3850: Exit analysis and execution
# Lines 3866-4600: Entry logic (skipped if managing_only)

if not user_mode and not entries_blocked and len(positions) < MAX_POSITIONS:
    # Entry logic only runs here
    # Exit logic already completed above
```

## Safest Default Profit Rules

Based on fee structures and risk management:

### Recommended PROFIT_TARGETS (Fixed - Fractional Format)

```python
# Kraken (0.36% fees = 0.0036 fractional)
PROFIT_TARGETS_KRAKEN_SAFE = [
    (0.030, "Profit target +3.0% (Net +2.64% after fees) - SAFE TARGET"),
    (0.020, "Profit target +2.0% (Net +1.64% after fees) - GOOD"),  
    (0.015, "Profit target +1.5% (Net +1.14% after fees) - ACCEPTABLE"),
    (0.010, "Profit target +1.0% (Net +0.64% after fees) - MINIMUM"),
]

# Coinbase (1.4% fees = 0.014 fractional)
PROFIT_TARGETS_COINBASE_SAFE = [
    (0.040, "Profit target +4.0% (Net +2.6% after fees) - SAFE TARGET"),
    (0.030, "Profit target +3.0% (Net +1.6% after fees) - GOOD"),
    (0.025, "Profit target +2.5% (Net +1.1% after fees) - ACCEPTABLE"),
    (0.020, "Profit target +2.0% (Net +0.6% after fees) - MINIMUM"),
]
```

### Philosophy

1. **Net Profit First**: All targets ensure NET profitability after fees
2. **Let Winners Run**: Higher targets (3-4%) capture trend moves
3. **Lock Gains Early**: Lower targets (1.5-2%) prevent reversals
4. **Fee-Aware**: Different targets per broker based on fee structure
5. **Risk/Reward**: Minimum 2:1 ratio (2% profit vs 1% stop)

### Stop-Loss Tiers (Current - Already Correct)

```python
# Primary (Kraken)
STOP_LOSS_PRIMARY_KRAKEN = -0.008  # -0.8%

# Primary (Coinbase)  
STOP_LOSS_PRIMARY_COINBASE = -0.010  # -1.0%

# Emergency
STOP_LOSS_THRESHOLD = -0.015  # -1.5%

# Catastrophic
STOP_LOSS_EMERGENCY = -0.05  # -5.0%
```

## Critical Fixes Required

1. **Fix PROFIT_TARGETS format bug** (URGENT)
   - Convert percentage values to fractional
   - OR divide by 100 when comparing

2. **Add explicit managing_only logging** (DONE)
   - Shows profit realization is active
   - Proves exits work without entries

3. **Enhance drain mode logging** (DONE)
   - Shows how many positions to drain
   - Explains strategy clearly

## Testing Checklist

- [ ] Verify profit targets fire correctly after fix
- [ ] Test managing_only mode with positions
- [ ] Test drain mode with >8 positions
- [ ] Verify logging shows "PROFIT REALIZATION ACTIVE"
- [ ] Test stop-loss triggers in managing mode
- [ ] Verify time-based exits work
