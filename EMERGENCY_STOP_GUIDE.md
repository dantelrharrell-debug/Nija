# Emergency Stop Mechanism

## Overview
Nija has an emergency stop mechanism that can halt trading by creating specific configuration files.

## Emergency Stop Files

### 1. STOP_ALL_ENTRIES.conf
**Location:** `/STOP_ALL_ENTRIES.conf` (repository root)

**Purpose:** Blocks all new position entries while allowing exits

**When Active:**
- ✅ Bot continues running
- ✅ Manages existing positions
- ✅ Can exit/sell positions
- ❌ Cannot open new positions

**Checked By:**
- `bot/trading_strategy.py` (line 216-221)
- `bot/nija_apex_strategy_v71.py` (line 644-651)

**To Activate:**
```bash
cat > STOP_ALL_ENTRIES.conf << EOF
EMERGENCY STOP - All new entries blocked
Time: $(date -u +"%Y-%m-%d %H:%M:%S")
Reason: [Your reason here]
EOF
```

**To Deactivate:**
```bash
rm STOP_ALL_ENTRIES.conf
git rm STOP_ALL_ENTRIES.conf  # If tracked by git
```

### 2. EMERGENCY_STOP
**Location:** `/EMERGENCY_STOP` (repository root)

**Purpose:** Complete bot shutdown

**When Active:**
- ❌ Bot will not start
- ❌ No trading
- ❌ No position management

**Checked By:**
- `bot.py` (lines 18-35) - Checked twice on startup

**To Activate:**
```bash
touch EMERGENCY_STOP
echo "Bot stopped for [reason]" > EMERGENCY_STOP
```

**To Deactivate:**
```bash
rm EMERGENCY_STOP
```

## Usage Examples

### Scenario 1: Need to liquidate positions without new entries
**Problem:** Position cap exceeded, need to close positions

**Solution:**
```bash
# Create stop file
cat > STOP_ALL_ENTRIES.conf << EOF
EMERGENCY STOP - All new entries blocked
Time: $(date -u +"%Y-%m-%d %H:%M:%S")
Reason: Position cap exceeded - liquidating to 8 positions
EOF

# Bot will continue running and exit positions
# Monitor logs to verify liquidation

# Once positions reduced, remove stop
rm STOP_ALL_ENTRIES.conf
```

### Scenario 2: Complete emergency shutdown
**Problem:** Critical issue, need to stop bot completely

**Solution:**
```bash
# Stop bot completely
echo "EMERGENCY STOP: [Critical issue description]" > EMERGENCY_STOP

# Bot will refuse to start
# Fix the issue

# Re-enable when ready
rm EMERGENCY_STOP
```

## Position Cap Enforcement

The bot has a **hard position cap of 8**:
- Automatically enforced by `PositionCapEnforcer`
- New entries blocked when at or above cap
- Excess positions automatically sold (weakest first)

**Related Files:**
- `bot/position_cap_enforcer.py`
- `bot/trading_strategy.py` (lines 206-226)

## Monitoring

**Check if emergency stops are active:**
```bash
ls -la STOP_ALL_ENTRIES.conf EMERGENCY_STOP 2>&1
```

**Check bot logs:**
```bash
tail -f nija.log | grep "BLOCKED\|EMERGENCY\|STOP"
```

**Look for these log messages:**
- `🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active`
- `🛑 BUY BLOCKED: STOP_ALL_ENTRIES.conf active`
- `🛑 ENTRY BLOCKED: Position cap reached`
- `🚨 EMERGENCY STOP ACTIVE`

## Troubleshooting

### Bot not trading?
1. Check for emergency stop files:
   ```bash
   ls -la STOP_ALL_ENTRIES.conf EMERGENCY_STOP
   ```

2. Check position count:
   - If >= 8 positions, new entries blocked until positions closed

3. Check account balance:
   - Minimum $25 required for new entries
   - Check logs for: `💰 Trading balance: $X.XX`

4. Check logs for block messages:
   ```bash
   grep "BLOCKED\|EMERGENCY" nija.log
   ```

### How to resume trading after emergency stop?
1. Remove stop files:
   ```bash
   rm -f STOP_ALL_ENTRIES.conf EMERGENCY_STOP
   git rm -f STOP_ALL_ENTRIES.conf  # If tracked
   ```

2. Verify removal:
   ```bash
   ls -la STOP_ALL_ENTRIES.conf EMERGENCY_STOP
   # Should show: cannot access
   ```

3. Restart bot (if EMERGENCY_STOP was active):
   ```bash
   ./start.sh
   ```

4. Monitor logs:
   ```bash
   tail -f nija.log
   # Should see: ✅ Position cap OK (X/8) - entries enabled
   ```

## Best Practices

1. **Always document the reason** when creating emergency stops
2. **Monitor positions** before removing stops
3. **Check logs** to verify bot behavior after changes
4. **Test in paper mode** when making significant changes
5. **Keep stops in .gitignore** to prevent accidental commits (currently tracked - consider updating)

## Git Tracking Note

Currently, emergency stop files ARE tracked by git. Consider adding to `.gitignore`:
```bash
echo "STOP_ALL_ENTRIES.conf" >> .gitignore
echo "EMERGENCY_STOP" >> .gitignore
```

This prevents accidental deployment of emergency stops to production.
