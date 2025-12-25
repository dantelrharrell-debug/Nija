# CRITICAL TRADING FIXES - December 21, 2025

## ISSUE SUMMARY
Bot is buying but NOT selling for profit. Two critical bugs identified:

### BUG #1: MockBroker Sell Orders Failing ✅ FIXED
**Problem**: When bot tries to sell positions (take profit or stop loss), it crashes with:
```
MockBroker.place_market_order() got an unexpected keyword argument 'size_type'
```

**Root Cause**: trading_strategy.py passes `size_type='base'` parameter when selling, but MockBroker.place_market_order() didn't accept this parameter.

**Fix Applied**: Updated /workspaces/Nija/bot/mock_broker.py lines 28-47:
- Added `size_type` parameter to method signature
- Implemented proper logic to handle 'base' (crypto amount) vs 'quote' (USD amount)
- Added balance tracking for sells (adds USD back to mock balance)

**Status**: ✅ **FIXED** - MockBroker can now execute sell orders without crashing

---

### BUG #2: Bot Running in Paper Mode Instead of Live ⚠️ IN PROGRESS
**Problem**: Despite credentials being in .env and PAPER_MODE=false in start.sh, bot keeps either:
1. Running in PAPER_MODE with MockBroker ($10k simulated balance), OR
2. Failing to connect to Coinbase API and crashing

**Evidence from nija.log**:
- **06:04** - PAPER_MODE enabled (MockBroker used, trades simulated)
- **13:03** - PAPER_MODE enabled (MockBroker used, ETH sold at loss successfully)  
- **13:10 onwards** - Multiple connection failures: "❌ BROKER CONNECTION FAILED"

**Root Cause**: Credentials exist in .env but connection is failing. Possible reasons:
1. API key/secret format issues
2. Permissions on the API key
3. Network/firewall issues
4. Key expiration

**Credentials in .env**:
```
COINBASE_API_KEY=organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/05067708-2a5d-43a5-a4c6-732176c05e7c
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----
```

**Status**: ⚠️ **NEEDS VERIFICATION** - Connection test required

---

## IMMEDIATE ACTION PLAN

### Step 1: Test API Connection
Run the diagnostic script to verify credentials work:
```bash
cd /workspaces/Nija
source .venv/bin/activate
python -u VERIFY_API_CONNECTION.py
```

**Expected Output if Working**:
```
✅ Coinbase Advanced Trade connected
Account Balance: $XXX.XX
Consumer USD: $XXX.XX
Advanced Trade USD: $XXX.XX
```

**If it fails**, check:
- API key permissions in Coinbase dashboard
- Key expiration date
- Whether key has "Trade" permission enabled

### Step 2: Fix Credentials if Needed
If connection test fails, regenerate API credentials:
1. Go to https://www.coinbase.com/settings/api
2. Delete old API key
3. Create new API key with permissions:
   - ✅ View
   - ✅ Trade
   - ✅ Transfer
4. Update .env with new credentials

### Step 3: Restart Bot with Fixes
Once connection test passes, use the emergency restart script:
```bash
./FIX_AND_START_NOW.sh
```

This script will:
1. Kill any running bot processes
2. Load credentials from .env
3. Test connection FIRST
4. Only start bot if connection succeeds
5. Force PAPER_MODE=false (live trading)

### Step 4: Monitor for Profitable Sells
Once running, watch logs for:
```bash
tail -f nija.log | grep -E "✅|🔴|PROFIT|LOSS|SELL"
```

**Look for**:
- "✅ Position closed with PROFIT" (successful take-profit)
- "🔴 Exit recorded" (position closed, check P&L)
- "Take profit hit" (TP level reached)

---

## EXPECTED BEHAVIOR (AFTER FIX)

### Normal Trading Cycle:
1. Bot scans markets every 15 seconds
2. Finds BUY signal (RSI pullback + MACD + volume)
3. Opens position at $X with:
   - Stop Loss: -2% ($X * 0.98)
   - Take Profit: +5% ($X * 1.05)
   - Trailing Stop: Locks in profit as price rises

4. **PROFIT TAKING** (now fixed):
   - Price rises to +5% → Take Profit triggered
   - Bot executes SELL order
   - Records profit in trade_journal.jsonl
   - Logs "✅ Position closed with PROFIT: $+Y.YY"

5. **LOSS CUTTING** (now fixed):
   - Price drops to -2% → Stop Loss triggered
   - Bot executes SELL order
   - Records loss in analytics
   - Resets consecutive trade counter

### What Was Broken Before:
- MockBroker crashed on SELL due to missing `size_type` parameter
- Positions would hit TP/SL but sell order would fail
- Bot would try to close position but encounter error
- Position remained open, accumulating losses

### What's Fixed Now:
- ✅ MockBroker accepts `size_type='base'` for crypto sells
- ✅ Sells execute successfully in paper mode
- ⚠️ Live mode still needs connection fix

---

## VERIFICATION CHECKLIST

After restart, verify:

- [ ] Bot starts without "PAPER_MODE enabled" message
- [ ] Logs show "✅ Coinbase Advanced Trade connected"
- [ ] Real balance displayed (not $10,000.00 mock balance)
- [ ] BUY orders execute with real USD deduction
- [ ] SELL orders execute when TP/SL hit
- [ ] Profits are credited to real USD balance
- [ ] No crashes on position exits

---

## FILES MODIFIED

1. **/workspaces/Nija/bot/mock_broker.py**
   - Lines 28-47: Added `size_type` parameter handling
   - Implements proper balance tracking for sells

2. **/workspaces/Nija/FIX_AND_START_NOW.sh**
   - New emergency restart script
   - Tests connection before starting bot

---

## NEXT STEPS IF STILL NOT WORKING

If bot still won't sell for profit after these fixes:

1. Check [trading_strategy.py](cci:7://file:///workspaces/Nija/bot/trading_strategy.py:0:0-0:0) line 917-1000 for take-profit logic
2. Verify exit conditions in manage_open_positions()
3. Check if broker.place_market_order() is being called for sells
4. Review retry_handler for sell order processing
5. Inspect trade_journal.jsonl for exit records

---

## CONTACT POINTS

- Logs: `/workspaces/Nija/nija.log`
- Positions: `/workspaces/Nija/data/open_positions.json`
- Trades: `/workspaces/Nija/trade_journal.jsonl`
- Connection Test: `VERIFY_API_CONNECTION.py`

---

**Last Updated**: 2025-12-21 13:22:00
**Status**: MockBroker sell bug FIXED ✅ | Live connection PENDING ⚠️
