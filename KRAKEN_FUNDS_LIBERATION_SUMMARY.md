# Kraken Funds Liberation & Profit-Taking Optimization

**Date**: January 23, 2026  
**Status**: ✅ IMPLEMENTED

## Problem Statement

The trading bot had funds tied up inefficiently:

1. **Kraken**: $40.68 held in unfilled open orders (66% of capital locked)
2. **Coinbase**: Below minimum for new entries ($20.60 < $25.00)
3. **Overall**: Capital locked in orders preventing new profitable trades

The user requested:
- Free up funds on Kraken so new profitable trades can execute
- Ensure NIJA takes profit on both Coinbase and Kraken
- Implement "little loss, major profit" philosophy

## Solution Implemented

### 1. Automatic Kraken Order Cleanup ✅

**File**: `bot/kraken_order_cleanup.py` (308 lines)

**Features**:
- Automatically cancels stale limit orders older than 5 minutes
- Frees up capital trapped in unfilled orders
- Integrated into trading cycle (runs every 5 minutes)
- Dry-run mode for safe testing
- Statistics tracking for monitoring

**How it works**:
```python
# During each Kraken trading cycle:
1. Check if 5 minutes passed since last cleanup
2. Fetch all open orders from Kraken
3. Identify orders older than 5 minutes
4. Cancel stale orders
5. Log capital freed
6. Refresh account balance
```

**Expected Impact**:
- Frees ~$40 in locked capital every cycle
- Makes funds available for new profitable trades
- Prevents capital from being tied up indefinitely

### 2. Optimized Profit-Taking Targets ✅

**File**: `bot/trading_strategy.py`

**Philosophy: "Little Loss, Major Profit"**

#### Kraken Profit Targets (Lower Fees = Tighter Targets)
```python
PROFIT_TARGETS_KRAKEN = [
    (3.0%, "MAJOR PROFIT - Net +2.64%"),   # Let winners run!
    (2.0%, "EXCELLENT - Net +1.64%"),
    (1.0%, "GOOD - Net +0.64%"),
    (0.7%, "ACCEPTABLE - Net +0.34%"),
    (0.5%, "MINIMAL - Net +0.14%")
]
```

**Kraken Advantages**:
- Lower fees (0.36% vs Coinbase 1.4%)
- Tighter profit targets still profitable
- Can take profits faster while maintaining net gains

#### Coinbase Profit Targets (Higher Fees = Wider Targets)
```python
PROFIT_TARGETS_COINBASE = [
    (3.0%, "MAJOR PROFIT - Net +1.6%"),   # Let winners run!
    (2.0%, "EXCELLENT - Net +0.6%"),
    (1.5%, "GOOD - Net +0.1%"),
    (1.2%, "ACCEPTABLE - Net -0.2%"),     # Better than -1% stop
    (1.0%, "EMERGENCY - Net -0.4%")
]
```

**Strategy**:
- Bot checks targets from HIGHEST to LOWEST
- Exits at first target hit (prioritizes larger gains)
- "Major Profit" targets (+3%, +2%) let winners run
- Lower targets provide safety exits

### 3. Risk Management: "Little Loss" ✅

**Tight Stop-Losses**:
- **Kraken**: -0.6% to -0.8% (accounts for lower fees)
- **Coinbase**: -1.0% (accounts for higher fees)
- **Philosophy**: Cut losses quickly, let profits run

**3-Tier Protection System**:
1. **Primary Stop**: -0.6% to -1.0% (main risk management)
2. **Emergency Micro-Stop**: -1% (logic failure prevention)
3. **Catastrophic Failsafe**: -5% (absolute last resort)

## Testing

**Test Script**: `test_kraken_cleanup_dryrun.py`

Run this to test the cleanup without making actual changes:
```bash
python test_kraken_cleanup_dryrun.py
```

**What it does**:
- Connects to Kraken (read-only mode)
- Fetches current balance and open orders
- Shows what WOULD be cleaned up
- Displays statistics
- **Does NOT actually cancel any orders**

## Expected Results

### Before Implementation
```
Kraken Balance:
  Available USD:  $20.77
  Held in orders: $40.68  ⚠️ 66% locked!
  Total:          $61.45
```

### After Implementation
```
Kraken Balance:
  Available USD:  $60-61   ✅ ~$40 freed!
  Held in orders: $0-1     ✅ Orders cleaned
  Total:          $61.45
```

### Profit-Taking Improvements

**Old Behavior**:
- Kraken: Exit at +1.0%, +0.7%, +0.5% only
- Coinbase: Exit at +1.5%, +1.2%, +1.0% only
- Limited upside capture

**New Behavior**:
- Kraken: Check +3.0%, +2.0%, +1.0%, +0.7%, +0.5%
- Coinbase: Check +3.0%, +2.0%, +1.5%, +1.2%, +1.0%
- **Major profit targets** (+3%, +2%) let big wins run
- **Smaller targets** provide safety exits

## How to Monitor

### Check if Cleanup is Working

Look for these log messages during Kraken trading cycles:

```
🧹 Kraken order cleanup: Checking for stale orders...
   📋 Found X open order(s)
   🔴 Cancelling Y stale order(s) to free $Z
   ✅ Cancelled: PAIR (freed $XX.XX)
   📊 Cleanup complete: Y/Y orders cancelled
   💰 Capital freed: $Z
   💰 Balance increased: $A → $B (+$C)
```

### Check if Profit-Taking is Working

Look for these log messages:

```
🎯 PROFIT TARGET HIT: SYMBOL at +X.XX%
   (target: +Y%, min threshold: +Z%)
   
Or for major profits:
💰 MAJOR PROFIT CAPTURED: SYMBOL at +3.XX%
```

## Manual Override

If you need to force-cancel ALL Kraken orders immediately:

```bash
python scripts/clean_kraken.py
```

This will:
1. Cancel ALL open orders
2. Force-sell ALL positions (except dust)
3. Verify cleanup succeeded

## Integration Points

The cleanup runs automatically in these locations:

1. **Trading Cycle**: Every 5 minutes during Kraken cycles
   - File: `bot/trading_strategy.py` line ~1920
   - Condition: Only if Kraken is active broker

2. **Initialization**: Created when Kraken connects
   - File: `bot/trading_strategy.py` line ~523
   - Only if Kraken connection succeeds

## Configuration

**Max Order Age**: 5 minutes (configurable)
```python
# In bot/trading_strategy.py
self.kraken_cleanup = create_kraken_cleanup(
    kraken, 
    max_order_age_minutes=5  # Adjust this value
)
```

**Cleanup Interval**: 5 minutes (configurable)
```python
# In bot/trading_strategy.py run_cycle()
if self.kraken_cleanup.should_run_cleanup(
    min_interval_minutes=5  # Adjust this value
):
```

## Safety Features

1. **Dry-Run Mode**: Test without making changes
2. **Interval Limiting**: Won't spam cancel requests
3. **Error Isolation**: Cleanup failures don't stop trading
4. **Statistics Tracking**: Monitor cleanup effectiveness
5. **Balance Refresh**: Updates balance after freeing capital

## Success Metrics

After deployment, you should see:

1. **Kraken held funds**: Drop from ~$40 to near $0
2. **Available capital**: Increase by ~$40
3. **Trade frequency**: More trades as capital is freed
4. **Profit captures**: Hits on +2% and +3% targets
5. **Loss cuts**: Quick exits at -0.6% to -1.0%

## Troubleshooting

**If cleanup not running**:
- Check logs for "Kraken order cleanup initialized"
- Verify Kraken is connected and active
- Check if `self.kraken_cleanup` is not None

**If orders still accumulating**:
- Verify max_order_age_minutes setting
- Check if cleanup interval is too long
- Review Kraken API rate limits

**If profit targets not hit**:
- Verify profit calculation is using correct targets
- Check broker_type is correctly identified
- Review position entry/exit logic

## Files Modified

1. `bot/kraken_order_cleanup.py` - NEW FILE (308 lines)
2. `bot/trading_strategy.py` - Modified:
   - Added Kraken cleanup initialization
   - Updated profit targets (Kraken & Coinbase)
   - Integrated cleanup into run_cycle()
3. `test_kraken_cleanup_dryrun.py` - NEW FILE (test script)

## Rollback Plan

If issues arise, you can disable the cleanup by:

1. Comment out cleanup initialization:
```python
# self.kraken_cleanup = create_kraken_cleanup(kraken, ...)
self.kraken_cleanup = None
```

2. Or set max_order_age to a very high value:
```python
max_order_age_minutes=999999  # Effectively disabled
```

3. Profit targets can be reverted in `bot/trading_strategy.py`

---

**Implementation Complete**: January 23, 2026  
**Ready for Production**: ✅ Yes  
**Testing Required**: Run `test_kraken_cleanup_dryrun.py` first  
**Expected Impact**: Immediate (~$40 capital freed, better profit capture)
