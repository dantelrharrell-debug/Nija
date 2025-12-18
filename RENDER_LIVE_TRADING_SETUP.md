# Enable LIVE TRADING on Render - Step-by-Step

## ⚠️ Current Status: PAPER MODE (Simulated Trades)

Your bot is running in **PAPER MODE** because Coinbase credentials are missing from Render.

---

## 🚀 Enable Live Trading (5 Minutes)

### Step 1: Access Render Dashboard

1. Go to https://render.com
2. Sign in with your GitHub account
3. Click on your **Nija** service

### Step 2: Add Environment Variables

1. Click **"Environment"** in the left sidebar
2. Click **"Add Environment Variable"** for each of these 4 variables:

---

#### Variable 1: COINBASE_API_KEY

**Key:**
```
COINBASE_API_KEY
```

**Value:**
```
organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/4cfe95c4-23c3-4480-a13c-1259f7320c36
```

---

#### Variable 2: COINBASE_API_SECRET

**Key:**
```
COINBASE_API_SECRET
```

**Value:** (⚠️ CRITICAL: Must be ONE line with `\n` as literal text - do NOT add actual line breaks)
```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIN8qIYi2YYF+EVw3SjBFI4vGG5s5+GK67PMtJsihiqMboAoGCCqGSM49\nAwEHoUQDQgAEyX6F9fdJ6FN8iigO3bOpAgs5rURgmpbPQulXOJhVUIQrBVvdHPz3\nKBxA/l4CdmnIbdsK4d+kTK8bNygn794vPA==\n-----END EC PRIVATE KEY-----\n
```

**Common mistake:** Adding actual line breaks. The `\n` must be the literal characters backslash-n, not a newline.

---

#### Variable 3: LIVE_TRADING

**Key:**
```
LIVE_TRADING
```

**Value:**
```
1
```

---

#### Variable 4: ALLOW_CONSUMER_USD

**Key:**
```
ALLOW_CONSUMER_USD
```

**Value:**
```
true
```

---

### Step 3: Save and Redeploy

1. Click **"Save Changes"** at the bottom
2. Render will automatically redeploy
3. OR click **"Manual Deploy"** → **"Deploy latest commit"**

### Step 4: Verify Live Trading is Active

Watch the deployment logs for these **SUCCESS INDICATORS**:

```
✅ Coinbase Advanced Trade connected
💰 TOTAL BALANCE:
   USD:  $57.00
   USDC: $0.00
   TRADING BALANCE: $57.00
```

**You should NOT see:**
```
⚠️ COINBASE CREDENTIALS MISSING — PAPER_MODE ENABLED
```

---

## ✅ Success Checklist

- [ ] All 4 environment variables added to Render
- [ ] Service redeployed successfully
- [ ] Logs show "Coinbase Advanced Trade connected"
- [ ] Logs show your real balance ($57.00)
- [ ] No "PAPER_MODE ENABLED" warning

---

## 🎯 After Live Trading Enabled

Your bot will:
- Use your real $57.00 balance
- Place real orders on Coinbase
- Execute up to 8 concurrent positions
- Risk 2% per trade ($1.14 stop loss)
- Target 6% profit ($3.42 per trade)

**Minimum order:** $5.00 (Coinbase requirement)

---

## 🔒 Security Note

**NEVER commit these credentials to GitHub!**

Environment variables in Render are:
- ✅ Encrypted at rest
- ✅ Only accessible to your service
- ✅ Not visible in logs
- ✅ Not stored in GitHub

---

## 🆘 Troubleshooting

### Still seeing PAPER_MODE warning?

1. **Check variable names** - Must be exact (case-sensitive)
2. **Check COINBASE_API_SECRET** - Must be ONE line with `\n` as text
3. **Redeploy manually** - Click "Manual Deploy"
4. **Wait 2-3 minutes** - Build takes time

### Logs show "401 Unauthorized"?

- API key or secret is incorrect
- Copy-paste credentials again carefully
- Ensure no extra spaces in values

### Balance shows $0.00?

- Funds are in Consumer wallet, not Advanced Trade
- Transfer funds to Advanced Trade portfolio:
  https://www.coinbase.com/advanced-portfolio

---

## 📊 Monitor Your Bot

**Check logs every hour:**
```
✅ Trade executed: BTC-USD BUY
   Entry: $42,500.00
   Stop Loss: $41,650.00 (-2.0%)
   Take Profit: $45,050.00 (+6.0%)
```

**Check Coinbase Advanced Trade:**
- View open positions
- Track profit/loss
- Monitor executed orders

---

## 🎯 Goal: $5,000 in 15 Days

**Current:** $57.00  
**Target:** $5,000  
**Required:** ~34.94% daily returns  
**Strategy:** APEX V7.1 with dual RSI  

Let the bot run 24/7 - it scans markets every 2.5 minutes!

---

**Questions?** Check the logs and verify environment variables first.
