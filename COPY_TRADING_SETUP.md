# NIJA Copy Trading Setup Guide

## Overview

NIJA supports full copy trading functionality where user accounts automatically mirror trades from the master account. This guide explains how to activate and configure copy trading for small accounts.

## Quick Start: Activate Full Copy Trading

### Step 1: Enable Copy Trading Mode

Add to your `.env` file:

```bash
# Enable copy trading - users mirror master trades
COPY_TRADING_MODE=MASTER_FOLLOW
```

### Step 2: Enable PRO MODE (For Small Accounts)

PRO MODE enables:
- ✅ Faster entries
- ✅ Smaller profit targets
- ✅ Allows scalps that beat fees slightly
- ⚠️ More aggressive trading (but with safety limits)

Add to your `.env` file:

```bash
# Enable PRO MODE for faster trading
PRO_MODE=true
```

### Step 3: Lower Minimum Balance Requirements

For small accounts under $25, you can lower the minimum balance requirements:

Add to your `.env` file:

```bash
# Lower minimums for small accounts
MINIMUM_TRADING_BALANCE=15.0
MIN_CASH_TO_BUY=5.0
```

**Note:** The risk engine already limits drawdown, so these lower minimums are safe for copy trading.

### Step 4: Disable XRP (Recommended for Small Accounts)

XRP has high spreads and low profit potential, making it unsuitable for small accounts:

```bash
# Disable XRP trading (already disabled by default)
DISABLED_PAIRS=XRP-USD
```

**Note:** XRP is already disabled by default in the code. This setting is optional.

## Complete Configuration Example

Here's a complete `.env` configuration for small account copy trading:

```bash
# ============================================================================
# COPY TRADING CONFIGURATION - SMALL ACCOUNTS
# ============================================================================

# Enable copy trading - mirror master trades
COPY_TRADING_MODE=MASTER_FOLLOW

# Enable PRO MODE - faster entries, smaller targets
PRO_MODE=true

# Lower minimums for accounts $15-$25
MINIMUM_TRADING_BALANCE=15.0
MIN_CASH_TO_BUY=5.0

# Disable XRP (high spreads, low profit)
DISABLED_PAIRS=XRP-USD

# ============================================================================
# RECOMMENDED SETTINGS FOR SMALL ACCOUNTS
# ============================================================================

# Keep position limits conservative
MAX_CONCURRENT_POSITIONS=3

# Use minimum free reserve
PRO_MODE_MIN_RESERVE_PCT=0.15
```

## How Copy Trading Works

### Position Sizing

User positions are automatically scaled based on account balance ratio:

```
User Position Size = Master Position Size × (User Balance / Master Balance)
```

**Example:**
- Master account: $1,000 balance, buys $100 of BTC (10% of balance)
- User account: $50 balance
- User position: $100 × ($50 / $1,000) = $5 of BTC (10% of balance)

### Trade Execution Flow

1. **Master Account** places a trade (BUY or SELL)
   - **BUY orders** = Entry positions
   - **SELL orders** = Profit-taking, stop-loss, or position exits
2. **Trade Signal** is emitted to the copy trading engine
3. **Copy Engine** receives the signal and processes it:
   - Identifies all active user accounts
   - For each user:
     - Calculates scaled position size based on balance ratio
     - Validates minimum size requirements
     - Places the same trade (BUY/SELL) on user's exchange
     - Logs execution results
4. **User Accounts** execute the trade automatically

**✅ PROFIT-TAKING SYNCHRONIZATION**
- When master takes profit (sells), **all users take profit simultaneously**
- When master exits a position (stop-loss), **all users exit simultaneously**
- Users maintain proportional position sizes throughout entry AND exit
- This ensures users **never hold positions after master has exited**

### Safety Features

✅ **Automatic Position Scaling**
- User positions are always proportional to account size
- Never risks more than the master's allocation percentage

✅ **Balance Validation**
- Checks user balance before each trade
- Skips trades if insufficient funds

✅ **Error Isolation**
- Failed trades for one user don't affect others
- Master trading continues regardless of user failures

✅ **Risk Management**
- Same stop-loss and take-profit rules as master
- Respects maximum position limits
- Daily loss limits apply to each account independently

✅ **Synchronized Exits (Profit-Taking & Stop-Loss)**
- Users automatically exit when master exits
- Profit-taking orders are copied identically to entry orders
- Stop-loss exits are replicated to protect all accounts
- No manual intervention needed for exits

## Supported Trading Pairs

By default, copy trading works with:
- ✅ BTC-USD
- ✅ ETH-USD
- ✅ SOL-USD
- ❌ XRP-USD (disabled - not profitable for small accounts)

To trade additional pairs, configure your broker for those markets and ensure they're not in `DISABLED_PAIRS`.

## User Account Configuration

User accounts are configured in JSON files:

```json
{
  "name": "User Name",
  "broker": "kraken",
  "role": "user",
  "enabled": true,
  "copy_from_master": true,
  "risk_multiplier": 1.0
}
```

**Key Fields:**
- `enabled`: Set to `true` to activate the account
- `copy_from_master`: Set to `true` to enable copy trading for this user
- `risk_multiplier`: Scale risk (1.0 = same as master, 0.5 = half risk)

## Monitoring Copy Trading

### Understanding Entry and Exit Signals

**Entry Signals (BUY)**
- Master opens new positions
- Users receive BUY signals
- Example: Master buys $100 BTC → User buys $5 BTC (proportional)

**Exit Signals (SELL)** 
- Master takes profit or hits stop-loss
- Users receive SELL signals
- Example: Master sells 0.001 BTC → User sells 0.00005 BTC (proportional)

**✅ Critical Feature: Both BUY and SELL orders are copied identically**

### Check Copy Engine Status

Look for these log messages on startup:

```
🔄 Starting copy trade engine in MASTER_FOLLOW MODE...
   📋 Mode: MASTER_FOLLOW (mirror master trades)
   📊 Allocation: Proportional (auto-scaled by balance)
   ✅ Copy trade engine started in ACTIVE MODE
   📡 Users will receive and execute copy trades from master accounts
   💰 User position sizes will be scaled based on account balance ratios
```

### Monitor Trade Execution

**When the master ENTERS a trade (BUY):**

```
🔔 RECEIVED MASTER TRADE SIGNAL
   Symbol: BTC-USD
   Side: BUY
   Size: 0.001 (crypto)
   Broker: coinbase

🔄 Copying trade to 2 user account(s)...
   🔄 Copying to user: user_001
      User Balance: $50.00
      Master Balance: $1000.00
      Calculated Size: 0.00005 (crypto)
      Scale Factor: 0.0500 (5.00%)
      📤 Placing BUY order...
      🟢 COPY TRADE SUCCESS
         Order ID: abc123
         Symbol: BTC-USD
         Side: BUY
         Size: 0.00005 (crypto)
```

**When the master EXITS a trade (SELL - Profit-Taking):**

```
🔔 RECEIVED MASTER TRADE SIGNAL
   Symbol: BTC-USD
   Side: SELL
   Size: 0.001 (crypto)
   Broker: coinbase

🔄 Copying trade to 2 user account(s)...
   🔄 Copying to user: user_001
      User Balance: $50.00
      Master Balance: $1000.00
      Calculated Size: 0.00005 (crypto)
      Scale Factor: 0.0500 (5.00%)
      📤 Placing SELL order...
      🟢 COPY TRADE SUCCESS
         Order ID: def456
         Symbol: BTC-USD
         Side: SELL
         Size: 0.00005 (crypto)
         ✅ PROFIT TAKEN IN SYNC WITH MASTER
```

## Troubleshooting

### Copy Trading Not Working

**Check 1:** Verify `COPY_TRADING_MODE` is set
```bash
echo $COPY_TRADING_MODE
# Should output: MASTER_FOLLOW
```

**Check 2:** Check copy engine logs
```bash
grep "copy trade engine" nija.log
```

**Check 3:** Verify user accounts are configured
- Check `config/users/` directory
- Ensure `enabled: true` and `copy_from_master: true`

### Trades Not Executing

**Common Issues:**

1. **Insufficient Balance**
   - User balance is too low for minimum position size
   - Solution: Add more funds or lower `MIN_CASH_TO_BUY`

2. **User Broker Not Connected**
   - User's API credentials are invalid or missing
   - Solution: Check credentials in `.env` file

3. **Symbol Not Supported**
   - User's exchange doesn't support the trading pair
   - Solution: Ensure user's exchange lists the same pairs as master

4. **Risk Limits Exceeded**
   - User has reached maximum positions or daily loss limit
   - Solution: Wait for limits to reset or adjust risk settings

## Advanced Configuration

### Custom Allocation Strategy

By default, copy trading uses **proportional allocation** (scales by balance ratio).

To implement custom allocation strategies, modify `bot/position_sizer.py`:

```python
def calculate_user_position_size(
    master_size: float,
    master_balance: float,
    user_balance: float,
    size_type: str,
    symbol: str
) -> Dict:
    """
    Calculate scaled position size for user account.
    
    Default strategy: Proportional scaling
    Custom strategies can be implemented here.
    """
    # Your custom logic here
    pass
```

### Multiple Master Accounts

To support multiple master accounts (advanced use case):

1. Configure multiple brokers as "master" in user JSON files
2. Use `copy_from_master` field to specify which master to follow
3. Set different `risk_multiplier` values per user

Example:
```json
{
  "name": "Conservative User",
  "copy_from_master": "master_conservative",
  "risk_multiplier": 0.5
}
```

## Best Practices

### For Small Accounts ($15-$50)

✅ **DO:**
- Enable copy trading (`COPY_TRADING_MODE=MASTER_FOLLOW`)
- Enable PRO MODE (`PRO_MODE=true`)
- Lower minimums (`MINIMUM_TRADING_BALANCE=15`, `MIN_CASH_TO_BUY=5`)
- Disable XRP (`DISABLED_PAIRS=XRP-USD`)
- Start with 1-2 concurrent positions
- Monitor daily to learn the system

❌ **DON'T:**
- Increase risk multiplier above 1.0
- Trade more than 3 concurrent positions
- Disable stop-losses or risk limits
- Override master's strategy with manual trades

### For Medium Accounts ($50-$200)

✅ **DO:**
- Use standard minimums (`MINIMUM_TRADING_BALANCE=25`)
- Enable PRO MODE for faster opportunities
- Allow 3-5 concurrent positions
- Consider adding SOL-USD to trading pairs

### For Large Accounts ($200+)

✅ **DO:**
- Use standard or higher minimums
- Consider independent trading instead of copy trading
- Diversify across multiple exchanges
- Scale positions more conservatively (risk_multiplier < 1.0)

## Support

For issues or questions:
1. Check logs in `nija.log`
2. Review this guide
3. Check APEX strategy documentation
4. File an issue on GitHub

## Safety Disclaimer

Copy trading involves risk. Small accounts are more sensitive to:
- Trading fees (can eat into profits)
- Slippage (price moves between master and user execution)
- Exchange rate limits (may delay user trades)

Always:
- Start with small amounts you can afford to lose
- Monitor your account regularly
- Understand the strategy being copied
- Keep risk management enabled
- Never disable stop-losses

**Copy trading is NOT a guaranteed profit system. Past performance does not guarantee future results.**
