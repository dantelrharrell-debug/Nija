# Where to See Your NIJA Trades in Kraken

## Overview

When NIJA executes trades on Kraken, you can view them in multiple places within the Kraken platform. This guide shows you exactly where to find your trading activity and how to verify NIJA's execution.

---

## 🎯 Quick Access: Where Are My Trades?

### 1. **Trade History** (Filled Orders)
📍 **Location**: Kraken.com → Portfolio → Trade History

**What You'll See:**
- ✅ All filled orders (buy/sell)
- ✅ Execution price
- ✅ Fees paid
- ✅ Timestamp
- ✅ Order ID

**Best For:**
- Verifying NIJA executed your trade
- Checking actual fill prices
- Reviewing trading fees
- Tax reporting

**How to Access:**
1. Login to [Kraken.com](https://www.kraken.com)
2. Click **Portfolio** in top navigation
3. Select **Trade History** tab
4. Filter by:
   - Date range
   - Trading pair (e.g., ETH/USD, BTC/USDT)
   - Order type (market, limit)

---

### 2. **Open Orders** (Active Positions)
📍 **Location**: Kraken.com → Portfolio → Open Orders

**What You'll See:**
- ⏳ Orders placed by NIJA that haven't filled yet
- ⏳ Stop-loss orders
- ⏳ Take-profit orders
- ⏳ Trailing stops

**Best For:**
- Monitoring pending orders
- Checking if stop-losses are set
- Seeing NIJA's active risk management

**How to Access:**
1. Go to **Portfolio** → **Open Orders**
2. You'll see all orders waiting to execute
3. NIJA's stop-loss and take-profit orders appear here

**Important Note:**
> ⚠️ If you see orders here for a long time, they may be waiting for price to reach target levels.

---

### 3. **Balance Ledger** (Account Activity)
📍 **Location**: Kraken.com → Portfolio → Ledger

**What You'll See:**
- 💰 All deposits/withdrawals
- 💰 Trading fee debits
- 💰 Position value changes
- 💰 Realized P&L

**Best For:**
- Tracking account balance changes
- Verifying fee impact
- Understanding cash flow

---

### 4. **Positions** (Current Holdings)
📍 **Location**: Kraken.com → Portfolio → Balances

**What You'll See:**
- 🪙 Current cryptocurrency holdings
- 🪙 USD/USDT cash balance
- 🪙 Total portfolio value
- 🪙 Available vs. locked funds

**Best For:**
- Seeing what NIJA is currently holding
- Checking if positions are still open
- Monitoring portfolio composition

**Understanding the Numbers:**
- **Available**: Cash/crypto you can trade
- **In Orders**: Funds locked in pending orders
- **Total**: Sum of available + in orders

---

## 📊 NIJA-Specific Trading Patterns in Kraken

### What to Expect in Your Kraken Account

1. **Market Orders**
   - NIJA typically uses market orders for instant execution
   - You'll see "Market" in the order type column
   - Fills happen immediately at best available price

2. **Stop-Loss Orders**
   - NIJA places stop-loss orders to protect positions
   - Appear in "Open Orders" until triggered
   - Execute as market orders when price hits stop level

3. **Partial Exits**
   - NIJA uses partial profit-taking (TP1, TP2, TP3)
   - You'll see multiple sell orders for the same pair
   - Each exit reduces position size incrementally

4. **Trading Pairs**
   - **Preferred**: `/USDT` pairs (lower fees on Kraken)
   - **Also Used**: `/USD` pairs
   - NIJA automatically normalizes symbols (e.g., `ETH-USD` → `ETH/USD`)

---

## 🔍 How to Verify NIJA Executed Correctly

### Step-by-Step Verification

1. **Check Trade History**
   - Look for the trading pair NIJA signaled (e.g., `ETH/USD`)
   - Verify timestamp matches NIJA's log
   - Confirm direction (buy/sell)

2. **Compare Execution Price**
   - NIJA logs intended entry price
   - Kraken shows actual fill price
   - Small differences are normal (slippage)

3. **Verify Fees**
   - Kraken shows exact fee in trade details
   - Standard Kraken fees: ~0.16% maker, ~0.26% taker
   - NIJA accounts for fees in P&L calculations

4. **Check Position is Open**
   - Go to **Portfolio** → **Balances**
   - Verify you hold the cryptocurrency NIJA bought
   - Check "Available" amount matches NIJA's position size

---

## 🚨 Troubleshooting: "I Don't See My Trade"

### Possible Reasons

1. **Order is Still Pending**
   - Check **Open Orders** instead of Trade History
   - Limit orders may not have filled yet
   - Cancel and replace if stuck

2. **Wrong Trading Pair Format**
   - NIJA logs: `ETH-USD` or `ETH-USDT`
   - Kraken displays: `ETH/USD` or `ETH/USDT`
   - Same pair, different format

3. **Insufficient Balance**
   - Check NIJA logs for error messages
   - Verify Kraken balance is sufficient
   - Account for locked funds in open orders

4. **API Credentials Issue**
   - NIJA may not be connected to Kraken
   - Check `.env` file has correct `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`
   - Verify API permissions include "Create & Modify Orders" and "Query Funds"

5. **Trade Was Rejected by Filters**
   - NIJA may have blocked the trade due to:
     - Minimum position size not met
     - Daily loss limit reached
     - Pair quality checks failed
   - Check **NIJA Activity Feed** for rejection reasons

---

## 💡 Pro Tips

### Best Practices for Kraken + NIJA

1. **Enable Email Notifications**
   - Kraken can email you for every trade
   - Settings → Notifications → Trade Notifications
   - Get instant confirmation when NIJA executes

2. **Use Kraken Mobile App**
   - Real-time push notifications
   - Faster than refreshing web dashboard
   - Great for monitoring on the go

3. **Set Up API Alerts (Advanced)**
   - Use Kraken's WebSocket API
   - Get real-time order updates
   - Integrate with your own monitoring tools

4. **Check Transaction Costs**
   - Kraken fees are typically lower than Coinbase
   - Volume-based fee tiers (higher volume = lower fees)
   - NIJA routes stablecoin trades to Kraken for this reason

---

## 🆚 Kraken vs. NIJA Activity Feed

### What's the Difference?

| Feature | Kraken Trade History | NIJA Activity Feed |
|---------|---------------------|-------------------|
| **Shows Filled Orders** | ✅ Yes | ✅ Yes |
| **Shows Pending Orders** | ✅ Yes (Open Orders) | ✅ Yes |
| **Shows Rejected Signals** | ❌ No | ✅ Yes |
| **Shows Filter Reasons** | ❌ No | ✅ Yes |
| **Shows Fee Analysis** | ✅ Yes | ✅ Yes |
| **Shows Why No Trade** | ❌ No | ✅ Yes |
| **Real-Time Updates** | ⚡ Fast (1-2 sec) | ⚡ Instant |
| **Trust Level** | 🏦 Exchange Official | 🤖 Bot Reporting |

**Key Insight:**
- **Kraken = Execution Proof** (what actually happened on the exchange)
- **NIJA Activity Feed = Decision Truth** (why NIJA did or didn't trade)

Use **both** together for complete visibility:
1. Check **NIJA Activity Feed** to see what NIJA decided
2. Verify in **Kraken Trade History** that it executed correctly

---

## 🔗 Quick Links

### Kraken Resources
- [Kraken Trade History](https://www.kraken.com/u/trade-history)
- [Kraken Open Orders](https://www.kraken.com/u/open-orders)
- [Kraken Portfolio Balances](https://www.kraken.com/u/portfolio)
- [Kraken API Documentation](https://docs.kraken.com/rest/)

### NIJA Resources
- **NIJA Dashboard**: `http://localhost:5000` (when running locally)
- **NIJA Activity Feed**: See dashboard for real-time decision log
- **Trade Journal**: `/data/trade_journal/trades.csv`
- **Multi-Exchange Guide**: See `MULTI_EXCHANGE_TRADING_GUIDE.md`

---

## ❓ FAQ

**Q: Why do some trades show in NIJA but not in Kraken?**
A: NIJA may have filtered/rejected the trade before placing the order. Check the Activity Feed for the rejection reason.

**Q: Why do fees differ from what NIJA predicted?**
A: Kraken's fee tier depends on your 30-day trading volume. NIJA estimates based on standard fees, but your actual fee may be lower if you're in a higher volume tier.

**Q: Can I manually close positions NIJA opened?**
A: Yes, but this may confuse NIJA's position tracking. Better to use NIJA's emergency stop-loss feature or disable the bot first.

**Q: What if Kraken UI is lagging?**
A: Use NIJA's "Live Position Mirror" in the dashboard - it shows current positions even if Kraken's UI hasn't updated yet.

**Q: How do I know if NIJA is connected to Kraken?**
A: Check the NIJA dashboard health status. It should show "Kraken: Connected ✅". Also check logs for "Kraken balance: USD $X.XX".

---

## 🎓 Next Steps

1. ✅ Bookmark this guide for quick reference
2. ✅ Verify your Kraken API credentials are configured in NIJA
3. ✅ Make a small test trade and verify it appears in both NIJA and Kraken
4. ✅ Set up email notifications in Kraken for instant trade confirmations
5. ✅ Use NIJA Activity Feed + Kraken Trade History together for full visibility

---

**Still have questions?** Check the main [README.md](README.md) or [MULTI_EXCHANGE_TRADING_GUIDE.md](MULTI_EXCHANGE_TRADING_GUIDE.md) for more details.
