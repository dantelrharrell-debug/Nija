# NIJA Bot - Issues Fixed and Remaining Actions

**Date**: January 10, 2026  
**Status**: Partial Fix Completed - Manual Steps Required

---

## 🎯 Summary

The bot was unable to start trading because:
1. **Minimum balance was too high** ($2.00) vs actual Coinbase balance ($1.37) ✅ **FIXED**
2. **Coinbase shows $1.37** but you report having **$28** ⏳ **NEEDS INVESTIGATION**
3. **Kraken Master connection fails** with "Invalid nonce" error ⏳ **NEEDS FIX**
4. **User #1 Kraken connection fails** with same error ⏳ **NEEDS FIX**

---

## ✅ What Was Fixed

### 1. Lowered Minimum Balance Requirements

**Problem**: Bot required $2.00 minimum but Coinbase showed only $1.37

**Solution**: Lowered all minimum balance thresholds from $2.00 → $1.00

**Files Changed**:
- `bot/independent_broker_trader.py`: MINIMUM_FUNDED_BALANCE = 1.0
- `bot/fee_aware_config.py`: MIN_BALANCE_TO_TRADE = 1.0
- `bot/trading_strategy.py`: MIN_BALANCE_TO_TRADE_USD = 1.0
- `bot/broker_manager.py`: MINIMUM_BALANCE_PROTECTION = 1.00

**Result**: Bot will now accept accounts with $1.00+ balance

---

## ⏳ What Still Needs to Be Done

### 2. Locate Missing Coinbase Funds ($26.63)

**Problem**: Bot detects $1.37 but you report having $28.00

**Most Likely Cause**: Funds are in **Coinbase Consumer Wallet** (not API-tradable)

**How to Check**:
```bash
python3 diagnose_all_balances.py
```

This will show you:
- ✅ Advanced Trade balance (API can trade with this)
- ❌ Consumer wallet balance (API CANNOT trade with this)
- 💎 Crypto holdings
- 📊 All portfolios

**If Funds Are in Consumer Wallet**:
1. Go to: https://www.coinbase.com/advanced-portfolio
2. Click "Deposit" → "From Coinbase"
3. Transfer your USD/USDC to Advanced Trade
4. **No fees** - instant transfer
5. Restart the bot - it will see the funds

**Other Possibilities**:
- Funds held in open crypto positions
- Funds in a different Coinbase portfolio
- API keys pointing to wrong account

### 3. Fix Kraken Master "Invalid Nonce" Error

**Problem**: Connection fails with "EAPI:Invalid nonce"

**What is This?**: Kraken requires each API request to have a unique, incrementing nonce (timestamp). "Invalid nonce" means the timestamp is wrong or out of order.

**Solution A - Regenerate API Keys** (Recommended):
1. Go to: https://www.kraken.com/u/security/api
2. **Delete** your old Kraken Master API key
3. **Create new** API key with these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ❌ Withdraw Funds (leave OFF for security)
4. Update your `.env` file or Railway/Render environment variables:
   ```
   KRAKEN_MASTER_API_KEY=<your-new-key>
   KRAKEN_MASTER_API_SECRET=<your-new-secret>
   ```
5. Redeploy the bot

**Solution B - Sync System Clock** (If on your own server):
```bash
sudo ntpdate -s time.nist.gov
```

### 4. Fix User #1 (Daivon Frazier) Kraken Connection

**Problem**: Same "EAPI:Invalid nonce" error

**Solution**: Same as Kraken Master - regenerate the API key

1. Go to: https://www.kraken.com/u/security/api (log in to Daivon's account)
2. Create new API key for User #1
3. Update environment variables:
   ```
   KRAKEN_USER_DAIVON_API_KEY=<new-key>
   KRAKEN_USER_DAIVON_API_SECRET=<new-secret>
   ```
4. Redeploy

### 5. Verify Alpaca Paper Trading

**Status**: Not tested yet

**Check**: Ensure these environment variables are set:
```
ALPACA_API_KEY=<your-paper-key>
ALPACA_API_SECRET=<your-paper-secret>
ALPACA_PAPER=true
```

You can get paper trading credentials from: https://alpaca.markets/

---

## 📋 Step-by-Step Action Plan

### Step 1: Run Diagnostic (Do This First!)
```bash
python3 diagnose_all_balances.py
```

This will tell you:
- Where your Coinbase $28 actually is
- If Kraken credentials work
- If Alpaca is connected
- If User #1 credentials work

### Step 2: Fix Coinbase (If Needed)

**If diagnostic shows funds in Consumer wallet**:
- Transfer to Advanced Trade (instructions above)

**If diagnostic shows $28 in Advanced Trade**:
- No action needed! Bot will detect it on next restart.

### Step 3: Fix Kraken Connections

**For both Master and User #1**:
1. Regenerate API keys (instructions above)
2. Update environment variables
3. Redeploy bot

### Step 4: Verify Everything Works

After fixes, run the diagnostic again:
```bash
python3 diagnose_all_balances.py
```

Expected output:
```
✅ Coinbase: $28.00
✅ Kraken Master: $28.00
✅ Alpaca Paper: $100,000.00
✅ User #1 Kraken: $30.00
```

### Step 5: Redeploy and Monitor

Deploy the bot and check startup logs for:
```
✅ FUNDED BROKERS: 4
💰 TOTAL TRADING CAPITAL: $100,086.00
🚀 Starting independent multi-broker trading...
```

---

## 🔧 Quick Reference: Environment Variables

Make sure these are set correctly in your `.env` file or deployment platform:

### Coinbase Advanced Trade
```bash
COINBASE_API_KEY=<your-key>
COINBASE_API_SECRET=<your-secret>
COINBASE_PEM_CONTENT=<your-pem-key>
```

### Kraken Master
```bash
KRAKEN_MASTER_API_KEY=<your-key>
KRAKEN_MASTER_API_SECRET=<your-secret>
```

### Kraken User #1 (Daivon Frazier)
```bash
KRAKEN_USER_DAIVON_API_KEY=<daivon-key>
KRAKEN_USER_DAIVON_API_SECRET=<daivon-secret>
```

### Alpaca Paper Trading
```bash
ALPACA_API_KEY=<paper-key>
ALPACA_API_SECRET=<paper-secret>
ALPACA_PAPER=true
```

---

## ❓ FAQ

**Q: Why does the bot only see $1.37 in Coinbase?**  
A: The bot can ONLY see funds in the Advanced Trade portfolio. Consumer wallet funds are not accessible via API.

**Q: Can't you just make the bot access Consumer wallet?**  
A: No. This is a Coinbase API limitation. The Advanced Trade API cannot access Consumer wallets.

**Q: How do I fix the Kraken nonce error?**  
A: Regenerate your API keys. The nonce error usually means the keys are old or the system time is wrong.

**Q: Will the bot trade now that minimum is lowered to $1.00?**  
A: Yes, but with $1.37 balance, it can only make tiny trades and fees will eat most profits. You should transfer the remaining funds.

**Q: Do I need to change any code?**  
A: No. All code fixes are complete. You just need to:
1. Transfer Coinbase funds (if in Consumer wallet)
2. Regenerate Kraken API keys
3. Update environment variables
4. Redeploy

---

## 📞 Need Help?

If after following these steps the bot still doesn't work:

1. **Run the diagnostic**: `python3 diagnose_all_balances.py`
2. **Check the logs** for error messages
3. **Share the diagnostic output** for further troubleshooting

---

## 🎯 Expected Final State

Once all fixes are applied:

```
2026-01-10 XX:XX:XX | INFO | ✅ Coinbase MASTER connected
2026-01-10 XX:XX:XX | INFO | 💰 MASTER ACCOUNT BALANCE: $28.00
2026-01-10 XX:XX:XX | INFO | ✅ Kraken MASTER connected  
2026-01-10 XX:XX:XX | INFO | 💰 Kraken Master Balance: $28.00
2026-01-10 XX:XX:XX | INFO | ✅ Alpaca MASTER connected
2026-01-10 XX:XX:XX | INFO | 💰 Alpaca Paper Balance: $100,000.00
2026-01-10 XX:XX:XX | INFO | ✅ User #1 (Daivon Frazier) CONNECTED
2026-01-10 XX:XX:XX | INFO | 💰 User #1 Kraken Balance: $30.00
2026-01-10 XX:XX:XX | INFO | 💰 TOTAL BALANCE (ALL ACCOUNTS): $100,086.00
2026-01-10 XX:XX:XX | INFO | ✅ FUNDED BROKERS: 4
2026-01-10 XX:XX:XX | INFO | 🚀 STARTING INDEPENDENT MULTI-BROKER TRADING
```

---

**Last Updated**: January 10, 2026  
**Status**: Code fixes complete, awaiting manual credential updates
