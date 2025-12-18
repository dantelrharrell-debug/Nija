u# 🚀 RENDER.COM DEPLOYMENT SETUP

**Quick Deploy - Copy & Paste Ready**

---

## STEP 1: Go to Render

Open: **https://render.com**
- Click **"Get Started"** or **"Sign In"**
- Use **GitHub** to sign in
- Authorize Render to access your repositories

---

## STEP 2: Create New Web Service

1. Click **"New +"** (top right)
2. Select **"Web Service"**
3. Find repository: **`dantelrharrell-debug/Nija`**
4. Click **"Connect"**

---

## STEP 3: Configure Service

**Name**: `nija-trading-bot` (or whatever you want)

**Region**: Choose closest to you (e.g., Oregon USA)

**Branch**: `main`

**Runtime**: **Docker** ⚠️ IMPORTANT

**Docker Command**: Leave BLANK (uses Dockerfile CMD)

**Instance Type**: 
- **Free** (0 cost, good for testing)
- **Starter** ($7/month, better performance)

---

## STEP 4: Add Environment Variables

Click **"Advanced"** → Scroll to **"Environment Variables"**

Add these **4 variables** (click "Add Environment Variable" for each):

### Variable 1: COINBASE_API_KEY
```
organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/4cfe95c4-23c3-4480-a13c-1259f7320c36
```

### Variable 2: COINBASE_API_SECRET
⚠️ **CRITICAL**: Must be ONE continuous line with `\n` as literal text (not actual newlines)

```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIN8qIYi2YYF+EVw3SjBFI4vGG5s5+GK67PMtJsihiqMboAoGCCqGSM49\nAwEHoUQDQgAEyX6F9fdJ6FN8iigO3bOpAgs5rURgmpbPQulXOJhVUIQrBVvdHPz3\nKBxA/l4CdmnIbdsK4d+kTK8bNygn794vPA==\n-----END EC PRIVATE KEY-----\n
```

### Variable 3: LIVE_TRADING
```
1
```

### Variable 4: ALLOW_CONSUMER_USD
```
true
```

---

## STEP 5: Deploy

1. Scroll to bottom
2. Click **"Create Web Service"**
3. Render will:
   - Clone from GitHub
   - Build Docker image (FRESH, no cache)
   - Deploy container
   - Show live logs

---

## STEP 6: Verify Success

Watch the **"Logs"** tab for these **SUCCESS INDICATORS**:

```
✅ Branch: main
✅ Commit: <actual commit SHA>
✅ Account balance: $55.81
✅ Position size: $5.00 or higher
✅ ✅ Coinbase Advanced Trade connected
✅ Trades execute successfully
```

**FAILURE indicators** (old cached code):
```
❌ Branch: unknown
❌ Commit: unknown
❌ Position size: $1.12
❌ Unknown error from broker
```

---

## IF YOU SEE $1.12 POSITION SIZES

This means the $5 fix didn't deploy. Try:

1. **Manual Deploy**:
   - Click "Manual Deploy" → "Clear build cache & deploy"
   
2. **Check GitHub**:
   - Verify latest commit has the $5 fix
   - Check bot/trading_strategy.py line 500

3. **Verify Variables**:
   - Go to "Environment" tab
   - Ensure all 4 variables are set
   - Check API_SECRET is ONE line with `\n` escapes

---

## RENDER ADVANTAGES

✅ **Fresh builds** - No Docker cache persistence  
✅ **Free tier** - 750 hours/month  
✅ **Auto-deploy** - Updates when you push to GitHub  
✅ **Easy rollback** - One-click to previous version  
✅ **Better logs** - More detailed than Railway  

---

## COST

- **Free Tier**: $0/month, 750 hours
- **Starter**: $7/month, always on
- **Pro**: $15/month, more resources

Free tier is fine for testing. Upgrade to Starter for 24/7 live trading.

---

## AFTER DEPLOYMENT

Your bot URL will be: `https://nija-trading-bot.onrender.com` (or similar)

Check logs regularly:
- Click your service
- "Logs" tab
- Watch for trade executions

---

## TROUBLESHOOTING

**Service won't start?**
- Check environment variables (all 4 required)
- Verify API_SECRET format (one line)
- Check logs for error messages

**Still seeing $1.12?**
- Trigger manual deploy with cache clear
- Verify GitHub has latest code
- Contact me if issue persists

**Trades failing?**
- Check LIVE_TRADING=1 is set
- Verify ALLOW_CONSUMER_USD=true
- Check Coinbase credentials are valid

---

**Ready to deploy? Follow steps 1-6 above!** 🚀
