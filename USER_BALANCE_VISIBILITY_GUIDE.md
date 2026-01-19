# User Balance Visibility & Observe Mode - Implementation Guide

## Overview

This document describes the implementation of user balance visibility and observe mode features in NIJA. These changes enable monitoring of user accounts without automatically executing trades.

## Problem Solved

Previously, NIJA was running in "MASTER-ONLY SIGNAL MODE" where:
- ❌ User balances were not visible unless actively trading
- ❌ CopyTradeEngine only activated for funded users
- ❌ No way to see users or track what they would receive

Now:
- ✅ All user balances are visible at startup
- ✅ CopyTradeEngine runs in OBSERVE MODE by default
- ✅ Users appear in logs even with small balances ($1+)
- ✅ Trades are tracked but NOT executed until enabled

## Features Implemented

### 1. User Balance Audit

**Location:** `bot/multi_account_broker_manager.py`

A new method `audit_user_accounts()` displays all user account balances regardless of trading status.

**When it runs:**
- At bot startup (after user connections, before trading begins)
- Shows ALL users with credentials configured
- Reports balances even if trading is disabled

**Output example:**
```
======================================================================
👥 USER ACCOUNT BALANCES AUDIT
======================================================================

👤 User: daivon_frazier
   KRAKEN: $125.50
   💰 User Total: $125.50

👤 User: tania_gilbert
   KRAKEN: $500.00
   ALPACA: $1,000.00
   💰 User Total: $1,500.00

======================================================================
📊 AUDIT SUMMARY
   Total Users: 2
   Total User Balance: $1,625.50
======================================================================
```

### 2. Copy Engine Observe Mode

**Location:** `bot/copy_trade_engine.py`

The CopyTradeEngine now supports an `observe_only` mode that tracks signals without executing trades.

**Parameters:**
- `observe_only=True` → Observe mode (NO trades executed)
- `observe_only=False` → Normal mode (trades executed)

**What Observe Mode Does:**

✅ **Does:**
- Tracks all master trade signals
- Logs what WOULD be copied to users
- Shows position sizing calculations
- Displays user balances
- Counts total signals observed

❌ **Does NOT:**
- Execute any trades on user accounts
- Place orders
- Modify positions
- Risk user capital

**Output example (Observe Mode):**
```
======================================================================
🔔 RECEIVED MASTER TRADE SIGNAL
======================================================================
   Symbol: BTC-USD
   Side: BUY
   Size: 0.001 (base_currency)
   Broker: coinbase
======================================================================
👁️  OBSERVE MODE - Signal Logged (NO TRADE EXECUTED)
======================================================================
   Total Signals Observed: 5
   ⚠️  Trading is DISABLED in observe mode
======================================================================
```

### 3. Startup Integration

**Location:** `bot.py`

The bot startup sequence now includes:

1. **Initialize trading strategy** (connects to exchanges)
2. **Audit user balances** ← NEW
3. **Start copy engine in observe mode** ← NEW
4. **Begin master trading**

**Code:**
```python
# AUDIT USER BALANCES - Show all user balances regardless of trading status
if hasattr(strategy, 'multi_account_manager') and strategy.multi_account_manager:
    strategy.multi_account_manager.audit_user_accounts()

# Start copy trade engine in OBSERVE MODE
from bot.copy_trade_engine import start_copy_engine
start_copy_engine(observe_only=True)  # CRITICAL: observe_only=True prevents auto-trading
```

## Configuration

### User Configuration Files

Users are configured in JSON files under `config/users/`:

- `retail_kraken.json` - Retail users on Kraken
- `retail_alpaca.json` - Retail users on Alpaca
- `investor_kraken.json` - Investors on Kraken
- etc.

**Example (`retail_kraken.json`):**
```json
[
  {
    "user_id": "daivon_frazier",
    "name": "Daivon Frazier",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  },
  {
    "user_id": "tania_gilbert",
    "name": "Tania Gilbert",
    "account_type": "retail",
    "broker_type": "kraken",
    "enabled": true,
    "description": "Retail user - Kraken crypto account"
  }
]
```

### Environment Variables

Users need API credentials configured as environment variables:

**Kraken Users:**
```bash
KRAKEN_USER_DAIVON_API_KEY=<api-key>
KRAKEN_USER_DAIVON_API_SECRET=<api-secret>
KRAKEN_USER_TANIA_API_KEY=<api-key>
KRAKEN_USER_TANIA_API_SECRET=<api-secret>
```

**Alpaca Users:**
```bash
ALPACA_USER_TANIA_API_KEY=<api-key>
ALPACA_USER_TANIA_API_SECRET=<api-secret>
ALPACA_USER_TANIA_PAPER=true
```

## Usage

### Viewing User Balances

User balances appear automatically at startup in the logs:

```bash
# In Railway/Render logs, you'll see:
======================================================================
👥 USER ACCOUNT BALANCES AUDIT
======================================================================
   ... user balances here ...
======================================================================
```

### Monitoring Observe Mode

When a master trade executes, observe mode logs what would happen:

```bash
# You'll see signals logged but NOT executed:
======================================================================
🔔 RECEIVED MASTER TRADE SIGNAL
======================================================================
   Symbol: ETH-USD
   Side: SELL
   ...
======================================================================
👁️  OBSERVE MODE - Signal Logged (NO TRADE EXECUTED)
======================================================================
```

### Enabling Live Trading

**⚠️ IMPORTANT:** Once you're ready to enable actual copy trading, change ONE line in `bot.py`:

**Current (Observe Mode - Safe):**
```python
start_copy_engine(observe_only=True)  # No trades executed
```

**Change to (Live Trading - User trades execute):**
```python
start_copy_engine(observe_only=False)  # Trades will execute!
```

**Before enabling:**
1. ✅ Verify position sizing is correct
2. ✅ Confirm risk caps are appropriate
3. ✅ Test stop-loss enforcement
4. ✅ Ensure user balances are accurate
5. ✅ Start with small test amounts

## Testing

Run the integration test to verify everything works:

```bash
python3 test_balance_visibility_integration.py
```

**Expected output:**
```
🎉 ALL VALIDATIONS PASSED!

Summary of changes:
  ✅ User balance audit function implemented
  ✅ Copy engine observe mode implemented
  ✅ Users marked as enabled in config files
  ✅ Global functions support observe_only parameter
```

## Architecture

### Component Interaction

```
┌─────────────────────────────────────────────────────────────┐
│                         bot.py                              │
│                                                             │
│  1. Initialize TradingStrategy                              │
│  2. Call audit_user_accounts() ← NEW                        │
│  3. Start copy engine (observe_only=True) ← NEW             │
│  4. Begin master trading                                    │
└─────────────────────────────────────────────────────────────┘
                            │
                            ├─────────────────────────────────┐
                            ▼                                 ▼
    ┌────────────────────────────────┐    ┌──────────────────────────────┐
    │  MultiAccountBrokerManager     │    │    CopyTradeEngine           │
    │                                │    │                              │
    │  • audit_user_accounts()       │    │  • observe_only flag         │
    │  • Lists all users             │    │  • Tracks signals            │
    │  • Shows balances              │    │  • NO trades if observe=True │
    │  • Regardless of trading       │    │  • Executes if observe=False │
    └────────────────────────────────┘    └──────────────────────────────┘
                            │                                 │
                            ▼                                 ▼
                    User Configurations              Trade Signals
                    (config/users/*.json)            (from master)
```

### Data Flow

**Observe Mode (Current State):**
```
Master Trade → Signal Emitter → Copy Engine → LOG ONLY (no execution)
                                             ↓
                                  Track: signals_observed++
```

**Normal Mode (After enabling):**
```
Master Trade → Signal Emitter → Copy Engine → Calculate Position Size
                                             ↓
                                    Execute on User Accounts
                                             ↓
                                  Track: trades_copied++
```

## API Reference

### audit_user_accounts()

```python
def audit_user_accounts(self):
    """
    Audit and log all user account balances.
    
    This function displays user balances regardless of trading status.
    It does NOT place trades - only reports current balances for visibility.
    
    Called at startup to ensure all users are visible even if not actively trading.
    """
```

**Returns:** None (logs to console)

### CopyTradeEngine.__init__()

```python
def __init__(self, multi_account_manager=None, observe_only=False):
    """
    Initialize the copy trade engine.
    
    Args:
        multi_account_manager: MultiAccountBrokerManager instance (uses global if None)
        observe_only: If True, track signals but don't execute trades (observe mode)
    """
```

### start_copy_engine()

```python
def start_copy_engine(observe_only: bool = False):
    """
    Start the global copy trade engine.
    
    Args:
        observe_only: If True, engine runs in observe mode (no trades executed)
    """
```

## Safety Features

### Built-in Safeguards

1. **Observe Mode by Default:** `observe_only=True` prevents accidental trading
2. **Explicit Enablement Required:** Must manually change to `observe_only=False`
3. **User Visibility:** All users shown at startup for transparency
4. **Clear Logging:** Observe mode clearly indicates NO TRADES EXECUTED
5. **Backward Compatible:** Functions default to safe settings

### Risk Management (When Trading Enabled)

When `observe_only=False`, these safety features still apply:

- ✅ Position sizing based on account equity
- ✅ Risk caps enforced
- ✅ Stop-loss enforcement active
- ✅ Master account must be connected
- ✅ User credentials must be valid

## Troubleshooting

### Users Not Appearing in Audit

**Check:**
1. Config files exist in `config/users/`
2. Users have `"enabled": true` in config
3. API credentials are set in environment variables
4. Broker connection succeeded

### Observe Mode Not Showing Signals

**Check:**
1. Master account is connected and trading
2. Copy engine started successfully
3. Check logs for `CopyTradeEngine` messages

### Ready to Enable Trading But Cautious

**Recommended approach:**
1. Start with ONE user
2. Use smallest allowed position size
3. Monitor closely for first few trades
4. Gradually increase as confidence grows

## FAQ

**Q: Will users see their balances even if not trading?**
A: Yes! The audit runs at startup and shows ALL users with credentials.

**Q: Does observe mode use real API credentials?**
A: Yes, it connects to exchanges to fetch real balances, but doesn't place orders.

**Q: How do I know if observe mode is active?**
A: Check logs for "OBSERVE MODE" messages and verify `observe_only=True` in bot.py.

**Q: Can I test with $1?**
A: Yes! Even small balances ($1+) will appear in the audit.

**Q: When should I enable live trading?**
A: After verifying:
- Balances are correct
- Position sizes make sense
- Risk caps are appropriate
- You understand the trading strategy

**Q: Can I disable a user without removing credentials?**
A: Yes! Set `"enabled": false` in the user's config file.

## Next Steps

1. **Deploy to production** - Push changes to Railway/Render
2. **Monitor startup logs** - Verify user balances appear
3. **Watch observe mode** - See what signals would copy
4. **Validate calculations** - Ensure position sizing is correct
5. **Enable trading** - When ready, set `observe_only=False`

## Support

For issues or questions:
- Check logs for error messages
- Run `test_balance_visibility_integration.py`
- Review user config files
- Verify API credentials are set correctly
