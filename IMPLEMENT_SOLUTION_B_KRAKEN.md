# Implementation Guide: Solution B - Switch to Kraken

**Date:** January 9, 2026  
**Goal:** Configure NIJA to trade on Kraken instead of Coinbase  
**Complexity:** Simple (5-10 minutes)  
**Benefits:** Lower fees (~0.16-0.26% vs 0.5-1.5%), different rate limits

---

## ✅ Prerequisites

Before starting, ensure you have:
- [ ] Kraken account with API access
- [ ] Kraken API Key and API Secret
- [ ] Kraken account funded with $100+ USD or USDT
- [ ] Access to Railway dashboard (or your deployment platform)

---

## 📋 Step-by-Step Implementation

### Step 1: Get Kraken API Credentials

1. **Log into Kraken:**
   - Go to: https://www.kraken.com
   - Sign in with your account

2. **Create API Key:**
   - Navigate to: Settings → API
   - Click "Generate New Key"
   
3. **Set Permissions:**
   Required permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
   
4. **Save Credentials:**
   - **API Key:** Copy and save (looks like: `abcd1234...`)
   - **Private Key:** Copy and save (long encrypted string)
   - ⚠️ Keep these secure - never commit to git or share

### Step 2: Verify Kraken Account Balance

**Check balance:**
```bash
# Run this script to check your Kraken balance
python3 check_kraken_connection_status.py
```

**Required balance:**
- Minimum: $25 USD/USDT (bot can trade but limited)
- Recommended: $100+ USD/USDT (optimal trading)
- Excellent: $500+ USD/USDT (full strategy execution)

**If balance too low:**
1. Go to: https://www.kraken.com
2. Navigate to: Funding → Deposit
3. Deposit USD or USDT
4. Wait for confirmation

### Step 3: Set Environment Variables on Railway

**Access Railway Dashboard:**
1. Go to: https://railway.app
2. Select your NIJA project
3. Click on the service/deployment
4. Navigate to "Variables" tab

**Add Kraken Credentials:**

Click "New Variable" and add these **two** variables:

**Variable 1:**
```
Name:  KRAKEN_API_KEY
Value: your_kraken_api_key_here
```

**Variable 2:**
```
Name:  KRAKEN_API_SECRET  
Value: your_kraken_private_key_here
```

**Important:**
- Replace `your_kraken_api_key_here` with your actual API key
- Replace `your_kraken_private_key_here` with your actual private key
- No quotes needed around the values
- Do NOT add extra spaces

**Verify Variables:**
After adding, you should see:
```
KRAKEN_API_KEY: ••••••••••••••••
KRAKEN_API_SECRET: ••••••••••••••••
```

### Step 4: Remove or Keep Coinbase Credentials (Optional)

**Two options:**

**Option A: Keep Both (Multi-Broker Mode)**
- Leave existing `COINBASE_API_KEY` and `COINBASE_API_SECRET` variables
- Bot will trade on BOTH Coinbase AND Kraken
- Each broker trades independently

**Option B: Kraken Only**
- Remove or rename `COINBASE_API_KEY` to `COINBASE_API_KEY_BACKUP`
- Remove or rename `COINBASE_API_SECRET` to `COINBASE_API_SECRET_BACKUP`
- Bot will trade ONLY on Kraken

**Recommendation:** Keep both for multi-broker trading

### Step 5: Redeploy Bot

**On Railway:**
1. After saving environment variables, Railway will automatically trigger a redeploy
2. If not, click "Deploy" or "Redeploy" button
3. Wait for deployment to complete (usually 1-3 minutes)

**Verify deployment:**
- Check deployment logs
- Look for "✅ Kraken connected"

### Step 6: Verify Kraken Connection

**Check logs for these messages:**

Expected successful connection:
```
🌐 MULTI-BROKER MODE ACTIVATED
📊 Attempting to connect Kraken Pro...
   ✅ Kraken connected
💰 Fetching account balance...
   Kraken balance: $XXX.XX USD
kraken: Running trading cycle...
```

**If you see these, SUCCESS! ✅**

### Step 7: Monitor Trading Activity

**Watch for Kraken trades:**
```bash
# View live logs
railway logs --tail 200 --follow
```

**Look for:**
- `kraken: Running trading cycle...`
- `kraken - Cycle #X`
- `🎯 KRAKEN: BUY order placed...`
- `✅ KRAKEN: Position opened...`

**Check positions:**
```bash
python3 check_current_positions.py
```

Should show positions on Kraken (not just Coinbase)

---

## 🔍 Verification Checklist

After completing all steps, verify:

- [ ] Kraken API credentials set on Railway
- [ ] Deployment completed successfully
- [ ] Logs show "✅ Kraken connected"
- [ ] Logs show "kraken: Running trading cycle..."
- [ ] Kraken balance displayed in logs
- [ ] Trades appearing in Kraken account (if signals found)

---

## 🐛 Troubleshooting

### Issue: "Kraken connection failed"

**Check:**
1. API credentials correct (no typos)
2. API key permissions enabled (see Step 1)
3. API key not expired
4. No firewall blocking Kraken API

**Fix:**
- Regenerate API key on Kraken
- Verify permissions are set correctly
- Update environment variables
- Redeploy

### Issue: "No module named 'krakenex'"

**Cause:** Kraken SDK not installed

**Fix:**
```bash
# Should already be in requirements.txt
pip install krakenex pykrakenapi
```

Then redeploy.

### Issue: "Still trading on Coinbase only"

**Check:**
1. Environment variables saved correctly
2. Deployment picked up new variables
3. Kraken credentials valid

**Fix:**
- Check logs for error messages about Kraken
- Verify API key is correct
- Try redeploying manually

### Issue: "Invalid API credentials"

**Causes:**
- Wrong API key or secret
- Extra spaces in credentials
- API key expired
- API key deleted on Kraken

**Fix:**
- Double-check credentials (copy/paste fresh)
- Regenerate API key on Kraken
- Update Railway variables
- Redeploy

---

## 📊 Expected Results

### Before Solution B:
```
2026-01-09 05:34:11 | INFO |    coinbase: Running trading cycle...
INFO:root:✅ Connected to Coinbase Advanced Trade API
INFO:root:   💰 Total Trading Balance: $10.05
```

### After Solution B:
```
2026-01-09 06:15:22 | INFO |    🌐 MULTI-BROKER MODE ACTIVATED
2026-01-09 06:15:22 | INFO |    📊 Attempting to connect Coinbase Advanced Trade...
2026-01-09 06:15:23 | INFO |       ✅ Coinbase connected
2026-01-09 06:15:24 | INFO |    📊 Attempting to connect Kraken Pro...
2026-01-09 06:15:25 | INFO |       ✅ Kraken connected
2026-01-09 06:15:26 | INFO |    kraken: Running trading cycle...
2026-01-09 06:15:27 | INFO | 💰 Kraken balance: $150.00 USD
2026-01-09 06:15:28 | INFO | 🔄 kraken - Cycle #1
```

---

## 💡 Benefits of Kraken

### Lower Fees
- **Coinbase:** 0.5% - 1.5% per trade
- **Kraken:** 0.16% - 0.26% per trade
- **Savings:** ~70% reduction in trading fees

### Example Cost Comparison
**100 trades at $50 each = $5,000 volume**

| Broker | Fee Rate | Total Fees |
|--------|----------|------------|
| Coinbase | 0.5% | $25.00 |
| Kraken | 0.16% | $8.00 |
| **Savings** | | **$17.00 (68%)** |

Over 1,000 trades, you'd save ~$170!

### Better Rate Limits
- Kraken generally has more lenient rate limits
- Fewer 403 errors
- More reliable market data access

### Different Market Pairs
- Some cryptocurrencies only available on Kraken
- Different liquidity for certain pairs
- More trading opportunities

---

## ⚠️ Important Notes

### Before Switching

1. **Close Coinbase positions:**
   - Bot cannot manage positions across different brokers
   - Existing Coinbase positions won't transfer to Kraken
   - Close all positions before switching if going Kraken-only

2. **Test with small amount first:**
   - Start with minimum balance to test
   - Verify trades execute correctly
   - Scale up after confirming everything works

3. **Monitor first few trades:**
   - Watch logs closely for first hour
   - Verify trades appear in Kraken account
   - Check for any API errors

### Multi-Broker Mode

If keeping both Coinbase and Kraken:
- Each broker trades independently
- Separate balances
- Separate positions
- Failures on one don't affect the other

**Advantages:**
- Diversification
- More trading opportunities
- Redundancy (if one broker has issues)

**Disadvantages:**
- Need to fund both accounts
- Manage positions on two platforms
- More complex monitoring

---

## 📞 Support

### If You Get Stuck

1. **Check the logs:**
   ```bash
   railway logs --tail 200
   ```

2. **Run diagnostic:**
   ```bash
   python3 quick_broker_diagnostic.py
   ```

3. **Test connection:**
   ```bash
   python3 check_kraken_connection_status.py
   ```

4. **Check existing documentation:**
   - [KRAKEN_CONNECTION_STATUS.md](./KRAKEN_CONNECTION_STATUS.md)
   - [MULTI_BROKER_STATUS.md](./MULTI_BROKER_STATUS.md)

---

## ✅ Success Criteria

You'll know Solution B is working when:

1. ✅ Railway shows `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` variables
2. ✅ Deployment completed without errors
3. ✅ Logs show "✅ Kraken connected"
4. ✅ Logs show "kraken: Running trading cycle..."
5. ✅ Kraken balance displayed correctly
6. ✅ Trades appearing in your Kraken account (when signals found)

---

**Implementation Status:** Ready to execute  
**Estimated Time:** 5-10 minutes  
**Difficulty:** Easy  
**Impact:** Lower fees, better trading experience

**Next:** Once Solution B is working, you can optionally implement Solution C (multi-user system) to have user-specific Kraken accounts.
