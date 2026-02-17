# NIJA Safe Trading Recovery Guide

## Overview

This guide explains how to safely restore trading operations after an emergency stop or system restart without risking capital.

## 🚨 When to Use This Guide

Use this guide if:
- Trading state is stuck in `EMERGENCY_STOP`
- Kill switch was activated and then deactivated
- Bot won't start trading after restart
- State machine and kill switch are out of sync
- You want to verify trading state before deployment

## 🛡️ Safety Guarantees

The recovery process ensures:
- ✅ **NO automatic live trading** - Always starts in safe mode
- ✅ **NO capital at risk** - Defaults to DRY_RUN (simulation)
- ✅ **User confirmation required** - Manual approval for all state changes
- ✅ **Complete audit trail** - All state changes are logged
- ✅ **Validation checks** - Detects and prevents inconsistent states

## 🔧 Recovery Tool: `safe_restore_trading.py`

### Quick Start

```bash
# 1. Check current status (always run this first)
python safe_restore_trading.py status

# 2. Restore to safe DRY_RUN mode (recommended)
python safe_restore_trading.py restore

# 3. Reset to OFF state only (if needed)
python safe_restore_trading.py reset
```

### Command Details

#### 1. Check Status (`status`)

**Purpose**: Diagnose current trading state and detect any inconsistencies.

```bash
python safe_restore_trading.py status
```

**What it shows**:
- Current trading state machine status
- Kill switch activation status
- Whether trading is allowed
- Any detected state inconsistencies
- Recent kill switch history
- Recommended next steps

**Example Output**:
```
📊 CURRENT STATUS
--------------------------------------------------------------------------------
Trading State Machine: EMERGENCY_STOP
Kill Switch Active:    ✅ NO
Kill File Exists:      False
Can Trade:             ❌ NO
--------------------------------------------------------------------------------

⚠️  STATE INCONSISTENCY DETECTED:
   • State machine is in EMERGENCY_STOP
   • But kill switch is DEACTIVATED
   • Trading is blocked unnecessarily

💡 Solution: Run 'python safe_restore_trading.py restore'
```

#### 2. Restore to DRY_RUN (`restore`)

**Purpose**: Safely restore trading to simulation mode (no capital risk).

```bash
python safe_restore_trading.py restore
```

**What it does**:
1. Validates current state
2. Checks kill switch is deactivated
3. Shows restoration plan
4. Asks for user confirmation
5. Transitions through valid states:
   - `EMERGENCY_STOP` → `OFF` → `DRY_RUN`
   - Or direct transition from other states
6. Enables safe simulation trading

**Safety Features**:
- NO real orders will be placed
- NO real money at risk
- All trading is simulated in-memory
- You can test bot behavior safely

**After Restoration**:
- Bot is in DRY_RUN mode (paper trading)
- Monitor and verify bot behavior
- When ready, manually transition to LIVE mode via UI/API

#### 3. Reset to OFF (`reset`)

**Purpose**: Disable all trading operations completely.

```bash
python safe_restore_trading.py reset
```

**What it does**:
1. Validates current state
2. Checks kill switch is deactivated
3. Asks for user confirmation
4. Transitions to OFF state
5. Disables all trading

**When to use**:
- Need to fully disable trading
- Performing maintenance
- Investigating issues
- Want explicit OFF state before manual re-activation

## 📋 Common Scenarios

### Scenario 1: Emergency Stop Stuck

**Problem**: Kill switch was activated, then deactivated, but trading won't resume.

**Symptoms**:
- State machine shows `EMERGENCY_STOP`
- Kill switch shows inactive
- Can't place trades

**Solution**:
```bash
# 1. Check status
python safe_restore_trading.py status

# 2. Restore to safe mode
python safe_restore_trading.py restore

# 3. Verify restoration
python safe_restore_trading.py status
```

**Result**: Bot is now in DRY_RUN mode, ready for safe testing.

---

### Scenario 2: After System Restart

**Problem**: Bot was restarted and trading needs to be safely enabled.

**Symptoms**:
- State machine shows `OFF` or `EMERGENCY_STOP`
- No trading activity
- Need to verify system before live trading

**Solution**:
```bash
# 1. Always check status first
python safe_restore_trading.py status

# 2. If state is inconsistent or you want safe mode
python safe_restore_trading.py restore

# 3. Test in DRY_RUN mode
# Monitor logs, verify strategies, check positions

# 4. When ready for live (via UI/API, not this tool)
# Manually transition to LIVE mode with proper risk acknowledgment
```

**Important**: This tool never enables LIVE trading automatically.

---

### Scenario 3: Kill Switch Still Active

**Problem**: Kill switch is active and needs to be deactivated first.

**Symptoms**:
- `safe_restore_trading.py status` shows kill switch active
- Emergency stop file exists
- Cannot restore trading

**Solution**:
```bash
# 1. Investigate WHY kill switch was activated
# Review logs and .nija_kill_switch_state.json

# 2. Resolve the underlying issue
# Fix the problem that triggered the kill switch

# 3. Deactivate kill switch
python emergency_kill_switch.py deactivate "Issue resolved: [describe fix]"

# 4. Restore trading safely
python safe_restore_trading.py restore
```

---

### Scenario 4: Want to Verify Before Live Trading

**Problem**: Need to ensure everything is working before risking capital.

**Symptoms**:
- Fresh deployment
- Recent code changes
- Want to be cautious

**Solution**:
```bash
# 1. Check current state
python safe_restore_trading.py status

# 2. Restore to DRY_RUN if not already
python safe_restore_trading.py restore

# 3. Run bot in DRY_RUN mode for testing period
# Recommended: At least 1 hour of monitoring

# 4. Verify:
# - Strategies execute correctly
# - No errors in logs
# - Risk management working
# - Position management correct
# - API connections stable

# 5. Only then manually enable LIVE trading
# Via UI/API with proper risk acknowledgment
```

## 🔄 State Machine Flow

The safe recovery process follows these state transitions:

```
EMERGENCY_STOP → OFF → DRY_RUN → [Manual] → LIVE_PENDING_CONFIRMATION → [Confirm] → LIVE_ACTIVE
                   ↑                           ↑
                   |                           |
                   +---- This tool ----+       +---- Manual only ----+
```

**Key Points**:
- This tool only handles: `EMERGENCY_STOP` → `OFF` → `DRY_RUN`
- Transition to LIVE mode requires manual action via UI/API
- This prevents accidental live trading activation

## 🔐 Security & Safety

### What This Tool CAN Do:
- ✅ Check trading status
- ✅ Transition to OFF state
- ✅ Transition to DRY_RUN (simulation) mode
- ✅ Detect state inconsistencies
- ✅ Provide recovery guidance

### What This Tool CANNOT Do:
- ❌ Activate live trading
- ❌ Override kill switch
- ❌ Bypass safety checks
- ❌ Make trades
- ❌ Modify risk settings

### Built-in Safety Mechanisms:
1. **Kill Switch Check**: Verifies kill switch is deactivated before restoration
2. **User Confirmation**: Requires explicit 'yes' confirmation
3. **Audit Trail**: Logs all state changes to `.nija_trading_state.json`
4. **State Validation**: Detects and prevents inconsistent states
5. **Default Safe Mode**: Always defaults to DRY_RUN, never LIVE

## 📊 State Files

### `.nija_trading_state.json`
Contains trading state machine status:
```json
{
  "current_state": "DRY_RUN",
  "history": [
    {
      "from": "OFF",
      "to": "DRY_RUN",
      "reason": "Safe recovery: Enabling simulation mode",
      "timestamp": "2026-02-17T22:01:15.133111"
    }
  ],
  "last_updated": "2026-02-17T22:01:15.133120"
}
```

### `.nija_kill_switch_state.json`
Contains kill switch activation history:
```json
{
  "is_active": false,
  "history": [
    {
      "reason": "Manual deactivation",
      "timestamp": "2026-02-17T21:00:00.000000"
    }
  ],
  "last_updated": "2026-02-17T21:00:00.000000"
}
```

## 🆘 Troubleshooting

### Error: "Kill switch is active"

**Cause**: Kill switch must be deactivated before restoration.

**Solution**:
```bash
# Check why kill switch was activated
cat .nija_kill_switch_state.json

# Deactivate after resolving issue
python emergency_kill_switch.py deactivate "Reason for resume"

# Then restore
python safe_restore_trading.py restore
```

### Error: "State transition failed"

**Cause**: Invalid state transition or file permissions.

**Solution**:
```bash
# Check file permissions
ls -la .nija_trading_state.json

# Verify file is writable
chmod 644 .nija_trading_state.json

# Try again
python safe_restore_trading.py restore
```

### Warning: "State inconsistency detected"

**Cause**: Kill switch and state machine are out of sync (typically after kill switch deactivation).

**Solution**: This is the exact problem this tool solves!
```bash
python safe_restore_trading.py restore
```

## 🔗 Related Tools

- `emergency_kill_switch.py` - Activate/deactivate kill switch
- `nija_control_center.py` - Monitor trading operations
- State machine managed by `bot/trading_state_machine.py`
- Kill switch managed by `bot/kill_switch.py`

## 📚 Additional Resources

- [Kill Switch Documentation](EMERGENCY_KILL_SWITCH_QUICK_REF.md)
- [Dry Run Mode Guide](DRY_RUN_MODE_GUIDE.md)
- [State Machine Documentation](STATE_MACHINE_IMPLEMENTATION.md)
- [Control Center Guide](CONTROL_CENTER.md)

## ✅ Best Practices

1. **Always check status first**: Run `status` before any recovery action
2. **Test in DRY_RUN**: Always verify bot behavior in simulation mode
3. **Monitor carefully**: Watch logs during and after recovery
4. **Document decisions**: Note why you're activating/deactivating
5. **Gradual deployment**: DRY_RUN → Test → Verify → Manual LIVE enable
6. **Never rush**: Take time to understand why emergency stop was triggered

## 🎯 Summary

**Safe Recovery Workflow**:
```bash
# 1. Diagnose
python safe_restore_trading.py status

# 2. Recover (safe mode)
python safe_restore_trading.py restore

# 3. Test & Verify
# Monitor DRY_RUN mode operation

# 4. Enable LIVE (manual only)
# Via UI/API with risk acknowledgment
```

**Remember**: This tool ensures you can NEVER accidentally risk capital during recovery!
