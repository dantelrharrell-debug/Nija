# 🔍 VERIFY YOUR API CONNECTION & ACCOUNT

## The Problem

Your Render logs show:
```
No funds detected in any account
```

This means the API isn't finding money in **either** Consumer wallet **or** Advanced Trade.

## Most Likely Causes

1. **API keys are for a different Coinbase account** than where your funds are
2. **Transfer to Advanced Trade hasn't completed yet**
3. **API connection needs to be refreshed**

## ✅ SOLUTION: Restart Render & Check Logs

### Step 1: Restart Render Service

1. Go to: https://dashboard.render.com
2. Find your **NIJA** service
3. Click **"Manual Deploy"** dropdown
4. Click **"Clear build cache & deploy"**
5. Wait for deployment to complete (~2-3 minutes)

### Step 2: Watch the Startup Logs

As the bot starts, look for these key sections:

#### Section 1: Portfolio Detection
```
🎯 PORTFOLIO ROUTING: DEFAULT ADVANCED TRADE
📊 ACCOUNT BALANCES (for information only):
   USD: $XX.XX | Default | ✅ TRADEABLE
   USDC: $XX.XX | Default | ✅ TRADEABLE
```

#### Section 2: Balance Summary (appears every 15 seconds)
```
💰 BALANCE SUMMARY:
   Consumer USD:  $XX.XX ❌ [NOT TRADABLE]
   Consumer USDC: $XX.XX ❌ [NOT TRADABLE]
   Advanced Trade USD:  $XX.XX ✅ [TRADABLE]
   Advanced Trade USDC: $XX.XX ✅ [TRADABLE]
   ▶ TRADING BALANCE: $XX.XX
```

### Step 3: Interpret Results

#### ✅ Good - Bot Will Trade:
```
Advanced Trade USD: $50.00 ✅
▶ TRADING BALANCE: $50.00
```
→ Bot should start trading within 15-30 seconds!

#### ❌ Bad - Funds in Wrong Place:
```
Consumer USD: $50.00 ❌ [NOT TRADABLE]
Advanced Trade USD: $0.00 ✅
▶ TRADING BALANCE: $0.00
```
→ Need to transfer to Advanced Trade

#### 🚨 Critical - No Funds Found:
```
▶ TRADING BALANCE: $0.00
No funds detected in any account
```
→ API keys might be for wrong account!

## If Still Showing $0.00 After Restart

### Check 1: Verify API Key Account

Your API keys might be for a different Coinbase account than where your money is.

1. Go to: https://www.coinbase.com/settings/api
2. Look at which account the API key belongs to
3. Check if that's the same account with your funds

### Check 2: Verify Funds Location on Coinbase

**Consumer Wallet:**
- Go to: https://www.coinbase.com
- Click "Assets"
- If you see USD/USDC here → Transfer to Advanced Trade

**Advanced Trade:**
- Go to: https://www.coinbase.com/advanced-trade
- Look at bottom-left "Portfolio value"
- Click "Holdings" tab
- Do you see your USD/USDC here?

### Check 3: Verify Transfer Completed

After transferring to Advanced Trade:
1. Wait 2-3 minutes
2. Refresh https://www.coinbase.com/advanced-trade
3. Verify funds appear in "Holdings"
4. Then restart Render

## Emergency: Create New API Keys

If API keys are for wrong account:

1. Go to the Coinbase account **with your funds**
2. Go to: https://www.coinbase.com/settings/api
3. Create **new** API key with these permissions:
   - ✅ View
   - ✅ Trade
   - ✅ Transfer (optional)
4. Copy the API Key and Secret (PEM format)
5. Update Render environment variables:
   - `COINBASE_API_KEY` = your new key
   - `COINBASE_API_SECRET` = your new secret (PEM format)
6. Restart Render

## Quick Reference

| Symptom | Meaning | Solution |
|---------|---------|----------|
| `Advanced Trade: $XX.XX ✅` | Working! | Bot should trade |
| `Consumer USD: $XX.XX ❌` | Wrong wallet | Transfer to Advanced |
| `No funds detected` | API issue | Wrong API keys or no funds |
| `v3 API check failed` | Connection issue | Restart Render |

## Need More Help?

Run the verification script after restart:
```bash
# In Render logs, look for the detailed output during startup
# OR set credentials locally and run:
python3 VERIFY_API_CONNECTION.py
```

The startup sequence will show you **exactly** what the bot sees.
