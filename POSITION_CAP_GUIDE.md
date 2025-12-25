# Position Cap & Manual Sell Protection Guide

## Current Status (2025-12-23)

**SELL-ONLY MODE ACTIVE** 🔒

The bot is currently configured to:
- ✅ Manage and close existing positions (stop loss, take profit, trailing stops)
- ❌ NOT open new positions (BUY blocked)
- 🎯 Target: Reduce from 14 positions to max 7
- 🛡️ Buffer: 1 position below hard limit of 8

## Configuration

### Position Limits
```bash
MAX_CONCURRENT_POSITIONS=7        # Hard cap with 1-position buffer
REENTRY_COOLDOWN_MINUTES=120      # 2-hour block after manual sells
MIN_CASH_TO_BUY=5.0               # Minimum USD to open positions
MINIMUM_TRADING_BALANCE=25.0      # Circuit breaker threshold
```

### Files
- **Emergency Stop**: `TRADING_EMERGENCY_STOP.conf` (ACTIVE)
- **Environment Config**: `.env.position_cap`

## How It Works

### Startup Behavior
1. Bot loads saved positions (may be > cap)
2. Syncs actual Coinbase holdings
3. **Immediately trims to cap** via `close_excess_positions()`
   - Closes weakest performers first (lowest P&L)
   - Removes stale tracked positions (zero holdings)
   - Continues until count ≤ `MAX_CONCURRENT_POSITIONS`

### During Operation
1. **Position Monitoring** (every 2.5 minutes)
   - Checks stop loss, take profit, trailing stops
   - Exits positions per strategy rules
   
2. **Manual Sell Detection**
   - Compares holdings snapshot each cycle
   - Detects when you manually liquidate a symbol
   - Blocks re-entry for `REENTRY_COOLDOWN_MINUTES`

3. **Buy Guards** (when emergency stop removed)
   - Requires USD ≥ `MIN_CASH_TO_BUY`
   - Requires total account ≥ `MINIMUM_TRADING_BALANCE`
   - Blocks if at cap: `actual_positions >= MAX_CONCURRENT_POSITIONS`
   - Blocks if at cap-1 (safety buffer)
   - Blocks symbols in manual-sell cooldown

## Resuming Normal Trading

### 1. Wait for positions to reduce
Monitor logs until you see:
```
✅ Excess position closed: <symbol> | P&L: ...
Liquidation cycle complete: N/N positions closed
```

### 2. Verify count is under cap
Check that open positions ≤ 7

### 3. Remove emergency stop
```bash
rm TRADING_EMERGENCY_STOP.conf
```

### 4. Optionally adjust cap
Edit `.env.position_cap` and redeploy, or set Railway env vars:
```bash
MAX_CONCURRENT_POSITIONS=8        # Back to full limit
REENTRY_COOLDOWN_MINUTES=60       # Reduce cooldown if desired
```

## Logs to Watch For

### Good Signs ✅
```
🔴 CLOSING EXCESS: <symbol> (P&L: ...)
✅ Excess position closed: <symbol> | P&L: ...
🧹 Removing stale tracked position with zero holdings: <symbol>
🔄 Liquidation cycle complete: N/N positions closed
```

### Protection Active 🛡️
```
🔒 EMERGENCY STOP ACTIVE - SELL-ONLY MODE ENABLED
🛡️ Manual sell detected for <symbol>. Blocking re-entry for 120 minutes.
🛑 BUY BLOCKED: N actual crypto positions on Coinbase, max is 7.
⏸️ BUY blocked for <symbol>: manual sell cooldown active (X min remaining).
```

### Issues ❌
```
❌ Failed to close excess position: <symbol>
⚠️ Could not resolve quantity for <symbol> from holdings
```

## Emergency Controls

### Force exit ALL positions
```bash
touch FORCE_EXIT_ALL.conf
```
Bot will close all positions on next cycle and remove the flag.

### Pause all trading (current state)
```bash
touch TRADING_EMERGENCY_STOP.conf
```

### Resume trading
```bash
rm TRADING_EMERGENCY_STOP.conf
```

## FAQ

**Q: Why cap at 7 instead of 8?**  
A: Keeps 1-position buffer to prevent hitting the hard limit during race conditions or API delays.

**Q: Why 2-hour cooldown after manual sells?**  
A: Prevents the bot from immediately re-buying what you just liquidated. Gives you time to adjust strategy or move funds.

**Q: Can I manually trade while the bot is running?**  
A: Yes, but be aware the bot will detect manual sells and apply cooldowns. Avoid manual buys that would push you over the cap.

**Q: What if I need to buy manually during emergency stop?**  
A: Manual buys still work. The bot only blocks its own automated BUY orders. Just stay under the cap.

## Support

If the bot re-buys after a manual sell:
1. Check that `REENTRY_COOLDOWN_MINUTES` is set
2. Look for "Manual sell detected" in logs
3. Verify the symbol is in cooldown: "BUY blocked ... manual sell cooldown active"
4. If still happening, increase cooldown or report the symbol + timestamp

If trimming isn't working:
1. Check logs for "CLOSING EXCESS" messages
2. Verify actual crypto holdings on Coinbase
3. Look for API errors in sell attempts
4. Check that bot has correct API permissions (VIEW + TRADE)
