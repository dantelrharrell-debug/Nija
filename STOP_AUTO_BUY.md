# How to Stop NIJA from Auto-Buying Back Your Sales

## The Problem
When you manually sell crypto, NIJA's autonomous scanner detects the same coin as a trading opportunity and immediately buys it back. This happens because:

1. **NIJA is always running** (deployed on Railway)
2. **Scans 50 markets every 15 seconds** (ultra-aggressive mode)
3. **Auto-buys** when RSI signals match its strategy
4. **Your manual sales** don't affect its trading logic

## Solution: Stop the Bot

### Method 1: Pause Railway Deployment (FASTEST)
1. Go to https://railway.app/dashboard
2. Find your NIJA trading bot project
3. Click on the project
4. Click **"Settings"** tab
5. Scroll down and click **"Pause Deployment"**
6. Wait 1-2 minutes for the bot to fully stop

### Method 2: Delete the Railway Service (PERMANENT)
1. Go to https://railway.app/dashboard
2. Find your NIJA project
3. Click **Settings**
4. Scroll to bottom
5. Click **"Delete Service"**
6. Confirm deletion

### Method 3: Add Environment Variable (TEMPORARY DISABLE)
1. Go to Railway project settings
2. Click **"Variables"** tab
3. Add new variable:
   - **Name:** `TRADING_ENABLED`
   - **Value:** `false`
4. Redeploy the service
5. Bot will run but not execute trades

## Verify It's Stopped

After stopping the bot:
1. Wait 2-3 minutes
2. Sell a small amount of crypto ($1-5)
3. Watch for 5 minutes
4. If it doesn't get bought back, the bot is stopped ✅

## WARNING: Current Behavior

- **NIJA is set to ULTRA AGGRESSIVE mode**
- **8-40% position sizes**
- **Up to 8 concurrent trades**
- **15-second market scanning**

This means it will aggressively buy any opportunity it finds. If you want to manually manage your portfolio, you MUST stop the bot first.

## Re-enabling Later

When you want to restart automated trading:
- Railway: Click "Resume" or redeploy
- Environment variable: Change `TRADING_ENABLED` to `true`
- Code changes: Remove or modify the trading logic

## Alternative: Modify Trading Logic

If you want the bot to run but NOT trade certain coins:
1. Edit `bot/trading_strategy.py`
2. Add a blacklist of coins to avoid
3. Redeploy to Railway

Let me know if you need help with any of these steps!
