# How to Restart Your NIJA Deployment to Load New Environment Variables

**Last Updated**: January 12, 2026  
**Purpose**: Force reload of environment variables after adding/updating API credentials

---

## The Problem

If you've added Kraken, OKX, Binance, or Alpaca API credentials to Railway or Render, but the bot still says they're "not configured", it's because **the deployment is running a cached instance that hasn't loaded the new environment variables**.

### Why This Happens

- Railway and Render cache running instances for performance
- Environment variables are loaded **only at startup**
- Adding new env vars doesn't automatically restart the service
- The bot needs a **full restart** to pick up new credentials

---

## Solution: Force a Deployment Restart

Choose your deployment platform below and follow the instructions:

---

## 🚂 Railway

### Method 1: Restart via Dashboard (Recommended)

1. **Open Railway Dashboard**
   - Go to https://railway.app
   - Sign in with your account
   - Select your NIJA bot project

2. **Navigate to Your Service**
   - Click on the NIJA service (it should show as running)
   
3. **Restart the Deployment**
   - Click the **"..."** menu (three dots) in the top right
   - Select **"Restart Deployment"**
   - OR: Go to **"Deployments"** tab → Click **"Redeploy"** on latest deployment

4. **Verify Environment Variables Were Loaded**
   - Click on **"Deployments"** tab
   - Click on the **latest deployment** (should show as "deploying")
   - Click **"View Logs"**
   - Look for startup log section: `🔍 EXCHANGE CREDENTIAL STATUS:`
   - Verify that your exchanges show as **✅ Configured**

### Method 2: Trigger Redeploy via Git Push

```bash
# Make a trivial commit to force redeploy
git commit --allow-empty -m "Trigger redeploy to load env vars"
git push origin main
```

Railway will automatically detect the push and redeploy.

### Method 3: Using Railway CLI

```bash
# Install Railway CLI if not already installed
npm install -g @railway/cli

# Login
railway login

# Link to your project (first time only)
railway link

# Restart the service
railway service restart
```

---

## 🎨 Render

### Method 1: Auto-Redeploy (Usually Automatic)

**Good news**: Render typically auto-redeploys when you save environment variables!

1. **Check if auto-redeploy happened**
   - Go to https://dashboard.render.com
   - Select your NIJA service
   - Look at **"Events"** tab
   - If you see recent "Deploy" event after adding env vars → ✅ Already redeployed

2. **If no auto-redeploy, proceed to Method 2**

### Method 2: Manual Deploy (Recommended)

1. **Open Render Dashboard**
   - Go to https://dashboard.render.com
   - Sign in with your account
   - Select your NIJA bot service

2. **Trigger Manual Deploy**
   - Click **"Manual Deploy"** button (top right)
   - Select **"Deploy latest commit"**
   - Click **"Deploy"**

3. **Monitor the Deployment**
   - Click on the new deployment in the list
   - Watch the build and deploy logs
   - Look for: `🔍 EXCHANGE CREDENTIAL STATUS:`
   - Verify your exchanges show as **✅ Configured**

### Method 3: Clear Build Cache + Redeploy

If environment variables still aren't loading:

1. **Go to your service settings**
   - Dashboard → Your Service → **"Settings"**

2. **Scroll to "Build & Deploy"**
   - Find **"Build Command"** section

3. **Clear build cache**
   - Click **"Clear Build Cache"**
   - Wait for confirmation

4. **Trigger manual deploy**
   - Go back to main service page
   - Click **"Manual Deploy"** → **"Clear build cache & deploy"**

---

## 🔍 Verify the Restart Worked

After restarting your deployment, verify that environment variables loaded correctly:

### Check 1: Review Startup Logs

Look for this section in your deployment logs:

```
🔍 EXCHANGE CREDENTIAL STATUS:
   ────────────────────────────────────────────────────────────
   📊 COINBASE (Master):
      ✅ Configured (Key: XX chars, Secret: XX chars)
   📊 KRAKEN (Master):
      ✅ Configured (Key: XX chars, Secret: XX chars)
   👤 KRAKEN (User #1: Daivon):
      ✅ Configured (Key: XX chars, Secret: XX chars)
   👤 KRAKEN (User #2: Tania):
      ✅ Configured (Key: XX chars, Secret: XX chars)
```

**✅ Success**: Exchanges show as "✅ Configured"  
**❌ Problem**: Exchanges show as "❌ Not configured" → See troubleshooting below

### Check 2: Look for Connection Messages

A few lines later, you should see:

```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Connected to Kraken Pro API (MASTER)
   💰 Kraken balance: $X,XXX.XX

📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $X,XXX.XX
```

**✅ Success**: Shows "✅ Connected" and displays balance  
**❌ Problem**: Shows "⚠️ credentials not configured" → See troubleshooting below

---

## 🔧 Troubleshooting

### Problem: Env vars still show as "❌ Not configured" after restart

**Possible causes**:

1. **Environment variables have typos in names**
   - Double-check variable names are EXACT (case-sensitive)
   - Example: `KRAKEN_MASTER_API_KEY` (not `kraken_master_api_key`)

2. **Environment variables contain leading/trailing spaces**
   - Railway/Render: Edit each variable and remove any spaces before/after the value
   - Values should start immediately after the `=` sign (no spaces)

3. **Environment variables are empty strings**
   - Make sure you pasted the actual API key/secret values
   - They should not be empty or contain placeholder text

4. **Wrong deployment environment**
   - If you have multiple Render services or Railway projects, make sure you added env vars to the correct one

### Solution: Run Diagnostic Script

The NIJA bot includes a diagnostic script that shows exactly which variables are set:

1. **Download the diagnostic script** from your repository
2. **Set your environment variables locally** (for testing)
3. **Run the script**:
   ```bash
   python3 diagnose_env_vars.py
   ```

4. **Review the output** to see which variables are properly set

The script will show:
- ✅ Which variables are configured correctly
- ❌ Which variables are missing
- ⚠️ Which variables have whitespace issues

### Problem: "Invalid API key" or "Authentication failed" errors

**This is different from "not configured"** - it means:
- ✅ Environment variables ARE loaded
- ❌ But the API credentials are invalid

**Solutions**:
1. **Verify API key/secret are correct** - Copy them again from exchange website
2. **Check API key permissions** - Make sure trading permissions are enabled
3. **Check API key is not expired** - Some exchanges expire keys after time
4. **Try regenerating the API key** - Delete old key, create new one

### Problem: Bot crashes on startup

**Check logs for error messages**:
- Look for Python traceback
- Common issues:
  - Missing required dependencies
  - Invalid JSON in JWT credentials (Coinbase)
  - Network connection issues

---

## 📋 Complete Restart Checklist

Use this checklist when adding new exchange credentials:

- [ ] **Step 1**: Get API credentials from exchange website
- [ ] **Step 2**: Add environment variables to Railway/Render
  - [ ] Verify variable names are spelled correctly (case-sensitive)
  - [ ] Verify values have no leading/trailing spaces
  - [ ] Verify values are not empty
- [ ] **Step 3**: Restart deployment (see methods above)
- [ ] **Step 4**: Wait for deployment to complete (2-5 minutes)
- [ ] **Step 5**: Check startup logs for credential status
  - [ ] Look for `🔍 EXCHANGE CREDENTIAL STATUS:` section
  - [ ] Verify exchanges show as `✅ Configured`
- [ ] **Step 6**: Check connection messages
  - [ ] Look for `✅ Connected to [Exchange]` messages
  - [ ] Look for balance displays
- [ ] **Step 7**: Verify no error messages in logs
- [ ] **Step 8**: Bot should show as "Running" in platform dashboard

---

## 🎯 Quick Reference

| Platform | Fastest Restart Method |
|----------|----------------------|
| **Railway** | Dashboard → "..." menu → "Restart Deployment" |
| **Render** | Dashboard → "Manual Deploy" → "Deploy latest commit" |
| **Local/Docker** | `docker-compose down && docker-compose up -d` |
| **VPS/PM2** | `pm2 restart nija-bot` |

---

## 📚 Additional Resources

- **Environment Variables Reference**: `KRAKEN_ENV_VARS_REFERENCE.md`
- **Kraken Setup Guide**: `KRAKEN_SETUP_GUIDE.md`
- **Multi-User Setup**: `MULTI_USER_SETUP_GUIDE.md`
- **Diagnostic Tool**: `diagnose_env_vars.py`
- **Connection Status Checker**: `check_kraken_status.py`

---

## 💡 Pro Tips

1. **Test locally first**: Before deploying to production, test your API credentials locally to ensure they work

2. **Use .env file for local testing**:
   ```bash
   # Create .env file (don't commit to git!)
   cp .env.example .env
   # Edit .env with your credentials
   # Test: ./start.sh
   ```

3. **Monitor logs during restart**: Watch the logs in real-time as the bot starts up to catch any issues immediately

4. **Enable notifications**: Set up Render/Railway notifications to alert you when deployments fail

5. **Keep credentials secure**: 
   - Never commit `.env` file to git
   - Use secret management features in Railway/Render
   - Rotate API keys periodically

---

**Questions or issues?** Check the troubleshooting section above or review the detailed setup guides in the repository.
