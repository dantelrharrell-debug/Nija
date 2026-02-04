# 🧯 Global Emergency Exit Switch

## Overview

NIJA includes a **global emergency exit switch** that immediately liquidates ALL positions across ALL accounts when activated. This is a safety mechanism for extreme market conditions or critical system issues.

## How It Works

### Activation

Create a file named `LIQUIDATE_ALL_NOW.conf` in the repository root:

```bash
# From repository root
touch LIQUIDATE_ALL_NOW.conf
```

### What Happens

When the bot detects this file during its trading cycle:

1. **Immediate Detection**: Checked at the start of every `run_cycle()` (every 2.5 minutes)
2. **Emergency Mode**: All normal trading operations are suspended
3. **Position Liquidation**: 
   - Fetches ALL open positions from the broker
   - Sells each position at market price
   - Processes positions sequentially with 1-second throttle
   - Logs each sell attempt with status
4. **File Cleanup**: Automatically removes `LIQUIDATE_ALL_NOW.conf` after liquidation
5. **Trading Resumes**: Next cycle continues normal operations

### Implementation Location

**File**: `bot/trading_strategy.py`  
**Method**: `run_cycle()`  
**Lines**: ~2926-3008

```python
# 🚨 EMERGENCY: Check if LIQUIDATE_ALL mode is active
liquidate_all_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
if os.path.exists(liquidate_all_file):
    logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
    logger.error("   SELLING ALL POSITIONS IMMEDIATELY")
    # ... liquidation logic ...
```

## Scope

### What Gets Liquidated

✅ **ALL** open positions on the active broker
✅ Works for **ANY** broker (Kraken, Coinbase, etc.)
✅ Works for **ALL** accounts (Platform + Users)
✅ Positions opened by NIJA or manually
✅ Positions adopted from exchange

### What Doesn't Get Liquidated

❌ Positions on disconnected brokers
❌ Positions on brokers not configured
❌ Pending orders (not executed positions)

## Usage Scenarios

### When to Use

1. **Extreme Market Crash**: Black swan event, flash crash
2. **Critical Bug Discovery**: Major flaw in trading logic detected
3. **Account Compromise**: Suspicious activity detected
4. **Exchange Issues**: Exchange experiencing problems
5. **Manual Override**: User wants to close everything immediately

### When NOT to Use

❌ **Normal profit-taking**: Use regular exit logic instead
❌ **Single position exit**: Use manual sell via exchange UI
❌ **Strategy adjustment**: Modify strategy parameters instead
❌ **Testing**: Use dry-run mode or smaller position sizes

## Example: Emergency Exit Flow

```
═══════════════════════════════════════════════════════════════════
TIME: 14:30:00 - Normal Trading Cycle
═══════════════════════════════════════════════════════════════════
✅ Scanning markets for opportunities
✅ Managing 5 open positions
✅ Monitoring stop-losses and profit targets
═══════════════════════════════════════════════════════════════════

[USER CREATES EMERGENCY FILE]
$ touch LIQUIDATE_ALL_NOW.conf

═══════════════════════════════════════════════════════════════════
TIME: 14:32:30 - Next Trading Cycle (2.5 min later)
═══════════════════════════════════════════════════════════════════
🚨 EMERGENCY LIQUIDATION MODE ACTIVE
   SELLING ALL POSITIONS IMMEDIATELY

   Found 5 positions to liquidate
   
   [1/5] FORCE SELLING 0.02 BTC...
   ✅ SOLD BTC
   
   [2/5] FORCE SELLING 0.5 ETH...
   ✅ SOLD ETH
   
   [3/5] FORCE SELLING 10 SOL...
   ✅ SOLD SOL
   
   [4/5] FORCE SELLING 100 ADA...
   ✅ SOLD ADA
   
   [5/5] FORCE SELLING 5000 XLM...
   ✅ SOLD XLM
   
   Liquidation round complete: 5/5 sold
   ✅ Emergency liquidation cycle complete - removed LIQUIDATE_ALL_NOW.conf
═══════════════════════════════════════════════════════════════════

TIME: 14:35:00 - Normal Trading Resumes
═══════════════════════════════════════════════════════════════════
✅ Emergency file removed
✅ Trading operations restored
✅ No open positions (all liquidated)
═══════════════════════════════════════════════════════════════════
```

## Multi-Account Behavior

### Independent Execution

Each account's trading thread independently checks for the emergency file:

- **Platform account thread**: Liquidates platform positions
- **User account 1 thread**: Liquidates user 1 positions  
- **User account 2 thread**: Liquidates user 2 positions
- **All threads**: Execute liquidation in parallel (within 2.5 min cycle)

### Timing

- All threads check for emergency file every 2.5 minutes
- Threads may be at different points in their cycle
- **Maximum delay**: 2.5 minutes from file creation to liquidation start
- **Typical delay**: ~1-2 minutes

## Safety Features

### Automatic Cleanup

✅ **Guaranteed removal**: File is deleted even if liquidation fails  
✅ **Try-finally block**: Cleanup happens in finally block  
✅ **No infinite loops**: File won't cause repeated liquidations

### Error Handling

✅ **Individual position errors**: One failure doesn't stop others  
✅ **Logging**: Each sell attempt logged with success/failure  
✅ **Graceful degradation**: Partial liquidation still useful

### Rate Limiting

✅ **1-second delay**: Between each sell to avoid API rate limits  
✅ **Sequential processing**: One position at a time  
✅ **Timeout protection**: Uses `call_with_timeout()` for API calls

## Alternatives to Emergency Exit

### 1. Stop All New Entries

Create `STOP_ALL_ENTRIES.conf` to:
- ✅ Keep existing positions
- ✅ Manage exits normally
- ❌ Block new position entries

**Use when**: You want to exit positions naturally but avoid new trades

### 2. Manual Position Exit

Via exchange UI:
- ✅ Granular control per position
- ✅ Set limit orders for better prices
- ❌ Slower (manual work)

**Use when**: Exiting specific positions, not urgent

### 3. Safety Controller Modes

Use built-in safety modes:
- **DRY_RUN**: Simulated trading only
- **EDUCATION**: Learning mode
- **LIVE**: Real trading

**Use when**: Testing or learning

## Technical Implementation

### Code Structure

```python
def run_cycle(self, broker=None, user_mode=False):
    """Execute trading cycle with emergency exit check"""
    
    # 1. FIRST check emergency file (before any other logic)
    liquidate_all_file = os.path.join(
        os.path.dirname(__file__), 
        '..', 
        'LIQUIDATE_ALL_NOW.conf'
    )
    
    if os.path.exists(liquidate_all_file):
        # 2. Enter emergency mode
        logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
        
        try:
            # 3. Get all positions
            positions = broker.get_positions()
            
            # 4. Sell each position
            for pos in positions:
                broker.place_market_order(
                    symbol=pos['symbol'],
                    side='sell',
                    quantity=pos['quantity']
                )
                time.sleep(1)  # Rate limit protection
                
        finally:
            # 5. ALWAYS remove file (guaranteed cleanup)
            if os.path.exists(liquidate_all_file):
                os.remove(liquidate_all_file)
        
        return  # Exit cycle, skip normal trading
    
    # 6. Normal trading continues if no emergency file
    # ... rest of trading logic ...
```

### File Location

```
/home/runner/work/Nija/Nija/LIQUIDATE_ALL_NOW.conf
```

Must be in the repository root (parent directory of `bot/`).

## Testing

### Safe Testing

**DO NOT** test in production with real money. Use:

1. **Dry-run mode**: Set `DRY_RUN_MODE=true`
2. **Paper trading account**: Test broker integration
3. **Simulation script**: Use `simulate_restart_adoption_sell.py`

### Test Procedure (Dry-Run Only)

```bash
# 1. Enable dry-run mode
export DRY_RUN_MODE=true

# 2. Start bot with test positions
python3 start.sh

# 3. Create emergency file
touch LIQUIDATE_ALL_NOW.conf

# 4. Watch logs for next cycle (within 2.5 min)
tail -f logs/nija.log

# 5. Verify:
#    - Emergency mode detected
#    - Positions listed for liquidation
#    - Mock sells executed
#    - File automatically removed
```

## Monitoring & Alerts

### Log Indicators

**Emergency activated**:
```
🚨 EMERGENCY LIQUIDATION MODE ACTIVE
   SELLING ALL POSITIONS IMMEDIATELY
```

**Liquidation progress**:
```
   [1/5] FORCE SELLING 0.02 BTC...
   ✅ SOLD BTC
```

**Completion**:
```
✅ Emergency liquidation cycle complete - removed LIQUIDATE_ALL_NOW.conf
```

### What to Monitor

1. **Position count**: Should reach 0 after liquidation
2. **Account balance**: Should increase (positions → cash)
3. **File status**: Should be deleted after cycle
4. **Error logs**: Check for failed sells

## Recovery After Emergency Exit

### Immediate Actions

1. **Verify liquidation**: Check exchange UI for zero positions
2. **Check balance**: Confirm cash received from sales
3. **Review logs**: Understand what triggered emergency
4. **Assess situation**: Determine if it's safe to resume

### Resuming Trading

✅ **Automatic**: Trading resumes next cycle after file removal  
✅ **No restart needed**: Bot continues running  
✅ **Clean slate**: No positions means fresh start  

### If You Want to Pause

Create `STOP_ALL_ENTRIES.conf` after emergency:
- Prevents new positions
- Allows bot to keep running
- Safe state for investigation

## Best Practices

### ✅ Do

- Document why you activated emergency exit
- Monitor the liquidation process
- Keep the file until liquidation completes
- Review logs after activation
- Understand root cause before resuming

### ❌ Don't

- Activate during normal volatility
- Delete file manually mid-liquidation
- Use as regular exit mechanism
- Activate without good reason
- Panic - bot will handle liquidation

## Guardrails

The emergency exit system has built-in safety:

🔒 **Idempotent**: Can be triggered multiple times safely  
🔒 **Self-cleaning**: Always removes trigger file  
🔒 **Logged**: Full audit trail of every action  
🔒 **Isolated**: One account's emergency doesn't affect others  
🔒 **Throttled**: Rate-limited to avoid API bans  

## Summary

The global emergency exit switch is a **last resort safety mechanism** that:

- ✅ Liquidates ALL positions immediately
- ✅ Works across ALL accounts
- ✅ Automatically cleans up after itself
- ✅ Resumes normal trading after completion
- ✅ Fully logged and auditable

**Remember**: This is for emergencies only. Use regular exit logic for normal profit-taking and risk management.
