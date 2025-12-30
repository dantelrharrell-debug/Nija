# Active Trading Status per Brokerage

## Quick Answer

**Is NIJA actively trading on each brokerage?**

Run this command to find out:
```bash
python3 check_active_trading_per_broker.py
```

Or use the shortcut:
```bash
./check_active_trading.sh
```

---

## What This Shows

The script checks **each supported brokerage** and reports:

1. ✅ **Connection Status** - Is the broker connected?
2. 💰 **Account Balance** - How much capital is available?
3. 📊 **Open Positions** - Are there active trades right now?
4. 🟢 **Trading Status** - Is the bot actively trading or idle?

---

## Understanding "Active Trading"

A broker is considered **actively trading** if:
- ✅ Successfully connected to the exchange
- ✅ Has open positions (currently holding assets)

A broker is **connected but idle** if:
- ✅ Successfully connected
- ❌ No open positions (may be waiting for signals)

---

## Example Output

### Scenario 1: Actively Trading on Coinbase

```
================================================================================
  ACTIVE TRADING SUMMARY
================================================================================

📊 Overall Status:
   • Total Brokers Checked: 5
   • Connected Brokers: 1
   • Actively Trading: 1
   • Connected but Idle: 0
   • Not Connected: 4

✅ BROKERS ACTIVELY TRADING (1):
   🟦 Coinbase Advanced Trade [PRIMARY]
      💰 Balance: $157.42
      📊 Open Positions: 3

📈 Total Open Positions Across All Brokers: 3
💰 Total Balance Across All Brokers: $157.42

✅ NIJA IS ACTIVELY TRADING

   Primary Broker: Coinbase Advanced Trade
   Active Exchanges: 1
   Combined Open Positions: 3
   Recent Activity (24h): 12 trades
```

### Scenario 2: Multiple Brokers, Some Trading

```
================================================================================
  ACTIVE TRADING SUMMARY
================================================================================

📊 Overall Status:
   • Total Brokers Checked: 5
   • Connected Brokers: 3
   • Actively Trading: 2
   • Connected but Idle: 1
   • Not Connected: 2

✅ BROKERS ACTIVELY TRADING (2):
   🟦 Coinbase Advanced Trade [PRIMARY]
      💰 Balance: $157.42
      📊 Open Positions: 5
   🟪 Kraken Pro
      💰 Balance: $50.00
      📊 Open Positions: 2

⚪ CONNECTED BUT IDLE (1):
   🟨 Binance
      💰 Balance: $100.00
      📊 Open Positions: 0
      ℹ️ Ready to trade but no positions currently open

❌ NOT CONNECTED (2):
   ⬛ OKX
   🟩 Alpaca

📈 Total Open Positions Across All Brokers: 7
💰 Total Balance Across All Brokers: $307.42

✅ NIJA IS ACTIVELY TRADING
   Primary Broker: Coinbase Advanced Trade
   Active Exchanges: 2
   Combined Open Positions: 7
```

### Scenario 3: No Active Trading

```
================================================================================
  ACTIVE TRADING SUMMARY
================================================================================

📊 Overall Status:
   • Total Brokers Checked: 5
   • Connected Brokers: 1
   • Actively Trading: 0
   • Connected but Idle: 1
   • Not Connected: 4

⚪ CONNECTED BUT IDLE (1):
   🟦 Coinbase Advanced Trade
      💰 Balance: $34.54
      📊 Open Positions: 0
      ℹ️ Ready to trade but no positions currently open

⚠️ NO ACTIVE POSITIONS

NIJA is connected but not currently holding any positions.
This could mean:
  • Bot is waiting for entry signals
  • All positions were recently closed
  • Bot just started and hasn't entered any trades yet

ℹ️ Recent activity detected (8 trades in last 24h)
   The bot has been trading recently but all positions are now closed
```

---

## What Each Status Means

### 🟢 Actively Trading
- **Meaning**: Broker is connected AND has open positions
- **What it shows**: The bot is currently executing the trading strategy on this exchange
- **Action needed**: None - normal operation

### ⚪ Connected but Idle
- **Meaning**: Broker is connected BUT has no open positions
- **What it shows**: Bot is monitoring markets but hasn't found entry signals yet
- **Action needed**: None - this is normal; bot waits for the right conditions

### ❌ Not Connected
- **Meaning**: Cannot establish connection to the broker
- **What it shows**: Missing credentials or connection issue
- **Action needed**: Add API credentials to `.env` file or check connection

---

## Detailed Information Shown

For each broker, you'll see:

1. **Connection Status**
   - ✅ Connected / ❌ Not Connected

2. **Balance**
   - Total USD/USDC available for trading
   - Shown as: `💰 Balance: $XXX.XX`

3. **Open Positions** (if actively trading)
   - Number of positions: `📊 Open Positions: X`
   - Position details for each:
     ```
     • BTC-USD: 0.00123456 BTC
     • ETH-USD: 0.05678900 ETH
     ```

4. **Trading Status**
   - `🟢 STATUS: ACTIVELY TRADING` - Has open positions
   - `⚪ STATUS: Connected but no open positions` - Idle

5. **Recent Activity** (last 24 hours)
   - Total trades executed
   - Most active trading pairs
   - Number of buys vs sells

---

## Supported Brokers

The script checks these 5 brokerages:

| Icon | Broker | Type | Primary? |
|------|--------|------|----------|
| 🟦 | Coinbase Advanced Trade | Crypto | Yes |
| 🟪 | Kraken Pro | Crypto | No |
| ⬛ | OKX | Crypto | No |
| 🟨 | Binance | Crypto | No |
| 🟩 | Alpaca | Stocks | No |

---

## Interpreting Results

### All Positions on Primary Broker (Coinbase)
```
✅ BROKERS ACTIVELY TRADING (1):
   🟦 Coinbase Advanced Trade [PRIMARY]
      📊 Open Positions: 8
```
**Meaning**: Normal operation. All trades are on the primary exchange.

### Positions Spread Across Multiple Brokers
```
✅ BROKERS ACTIVELY TRADING (3):
   🟦 Coinbase Advanced Trade [PRIMARY] - 5 positions
   🟪 Kraken Pro - 2 positions
   🟨 Binance - 1 position
```
**Meaning**: Multi-broker mode active. Trades distributed across exchanges.

### No Open Positions but Recent Activity
```
⚠️ NO ACTIVE POSITIONS
ℹ️ Recent activity detected (15 trades in last 24h)
```
**Meaning**: Bot is working correctly. All positions were closed (likely took profits or hit stops).

### No Connections
```
❌ NOT CONNECTED (5):
   🟦 Coinbase Advanced Trade
   🟪 Kraken Pro
   [etc...]
```
**Meaning**: Need to configure broker credentials in `.env` file.

---

## Comparison with Other Status Scripts

### `check_broker_status.py`
- Shows: Which brokers are **connected**
- Purpose: Verify API credentials and connection
- Does NOT show: Whether bot is currently trading

### `check_active_trading_per_broker.py` (THIS SCRIPT)
- Shows: Which brokers are **actively trading**
- Purpose: See real-time trading activity
- Shows: Open positions, recent trades, trading status

### `check_nija_trading_status.py`
- Shows: Overall bot status
- Purpose: General health check
- Does NOT break down by broker

---

## Common Questions

### Q: Why does it show "Connected but Idle"?
**A**: The bot is working correctly but hasn't found good entry signals yet. This is normal - the strategy only enters trades when specific RSI conditions are met.

### Q: I see positions but no recent trades in the journal
**A**: Position may have been opened before the 24-hour window, or the trade journal file doesn't exist yet.

### Q: How often should I run this?
**A**: 
- Before making changes: Verify current state
- After deploying: Confirm trading resumed
- When debugging: Understand what's happening
- Monitoring: Every few hours in production

### Q: What if multiple brokers show positions?
**A**: This is normal in multi-broker mode. The 8-position limit applies across ALL brokers combined.

### Q: Can I see which specific assets are being traded?
**A**: Yes! The script shows up to 5 open positions per broker with symbol and quantity details.

---

## Troubleshooting

### Script shows "No brokers connected"
1. Check `.env` file has broker credentials
2. Verify credentials are valid
3. Check network connectivity
4. See `BROKER_INTEGRATION_GUIDE.md` for setup

### Script shows "Error importing broker classes"
1. Make sure you're in the project root directory
2. Verify `bot/broker_manager.py` exists
3. Check Python dependencies: `pip install -r requirements.txt`

### Positions shown don't match what I expect
1. Run `python3 check_broker_status.py` to verify balances
2. Check the trade journal: `tail -20 trade_journal.jsonl`
3. Review bot logs: `./show_latest_logs.sh`

---

## Related Documentation

- **Broker Setup**: `BROKER_INTEGRATION_GUIDE.md`
- **Multi-Broker Mode**: `MULTI_BROKER_STATUS.md`
- **Connection Status**: `ANSWER_BROKERAGES_CONNECTED.md`
- **Trading Strategy**: `APEX_V71_DOCUMENTATION.md`

---

## Technical Details

### How It Works

1. **Imports broker classes** from `bot/broker_manager.py`
2. **Attempts connection** to each broker (using credentials from `.env`)
3. **Fetches positions** via `broker.get_positions()` for connected brokers
4. **Reads trade journal** (`trade_journal.jsonl`) for recent activity
5. **Analyzes and reports** connection status, positions, and trading activity

### Exit Codes

- `0` - At least one broker is actively trading
- `1` - No active trading detected

Useful for scripts:
```bash
if ./check_active_trading.sh; then
    echo "Bot is actively trading"
else
    echo "No active trading detected"
fi
```

---

**Last Updated**: December 30, 2025
