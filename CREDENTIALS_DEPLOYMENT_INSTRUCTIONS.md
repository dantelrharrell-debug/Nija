# 🔐 Kraken Master Credentials - DEPLOYMENT INSTRUCTIONS

**Date:** January 17, 2026  
**Status:** ✅ Credentials received and validated (format correct)  

---

## ✅ Credentials Received

The following Kraken master API credentials have been provided:

```
KRAKEN_MASTER_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_MASTER_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
```

**Validation Results:**
- ✅ API Key: 56 characters (correct format)
- ✅ API Secret: 88 characters (correct format - base64 encoded)
- ✅ No whitespace issues
- ✅ Properly formatted

**Note:** Network connection test could not be completed in sandbox environment, but format validation passed. The credentials will be tested when deployed to your live environment.

---

## 🚀 DEPLOYMENT INSTRUCTIONS

### ⚠️ IMPORTANT: Choose Your Deployment Method

The credentials are currently stored in the local `.env` file for this repository. However, **`.env` files are NOT committed to git** (for security reasons).

You need to add these credentials to your **actual deployment environment**.

---

## Option 1: Railway Deployment (Recommended)

**If you're using Railway for hosting:**

### Step-by-Step:

1. **Go to Railway Dashboard**
   - Visit: https://railway.app/
   - Log in to your account
   - Select your NIJA project

2. **Open Your Service**
   - Click on your NIJA service (the bot)

3. **Go to Variables Tab**
   - Click on the **"Variables"** tab

4. **Add First Variable**
   - Click **"New Variable"**
   - Name: `KRAKEN_MASTER_API_KEY`
   - Value: `8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7`
   - Click **"Add"**

5. **Add Second Variable**
   - Click **"New Variable"** again
   - Name: `KRAKEN_MASTER_API_SECRET`
   - Value: `e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==`
   - Click **"Add"**

6. **Save and Wait**
   - Railway will automatically restart your service
   - Wait 2-3 minutes for deployment

7. **Verify in Logs**
   - Click on **"Deployments"** tab
   - Click on the latest deployment
   - Check logs for:
     ```
     ✅ Kraken MASTER connected
     💰 Kraken Balance (MASTER): USD $XXX.XX
     ✅ Started independent trading thread for kraken (MASTER)
     ```

**Status:** ☐ Railway configured

---

## Option 2: Render Deployment

**If you're using Render for hosting:**

### Step-by-Step:

1. **Go to Render Dashboard**
   - Visit: https://dashboard.render.com/
   - Log in to your account
   - Select your NIJA web service

2. **Navigate to Environment Tab**
   - Click **"Environment"** in the left sidebar
   - Scroll to "Environment Variables" section

3. **Add First Variable**
   - Click **"Add Environment Variable"**
   - Key: `KRAKEN_MASTER_API_KEY`
   - Value: `8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7`

4. **Add Second Variable**
   - Click **"Add Environment Variable"** again
   - Key: `KRAKEN_MASTER_API_SECRET`
   - Value: `e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==`

5. **Save Changes**
   - Click **"Save Changes"**

6. **Manual Deploy**
   - Click **"Manual Deploy"** button
   - Select **"Deploy latest commit"**
   - Wait 3-5 minutes for deployment

7. **Verify in Logs**
   - Click on **"Logs"** tab
   - Check for:
     ```
     ✅ Kraken MASTER connected
     💰 Kraken Balance (MASTER): USD $XXX.XX
     ✅ Started independent trading thread for kraken (MASTER)
     ```

**Status:** ☐ Render configured

---

## Option 3: Local Development/Server

**If you're running the bot locally or on your own server:**

### Method A: Using .env File (Already Done!)

The credentials are already in your local `.env` file. Just make sure:

1. **Verify .env File Exists**
   ```bash
   cat .env
   ```
   
   Should show:
   ```
   KRAKEN_MASTER_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
   KRAKEN_MASTER_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
   ```

2. **Ensure .env is in .gitignore** (Already done)
   ```bash
   grep ".env" .gitignore
   ```
   
   Should show `.env` in the output

3. **Restart the Bot**
   ```bash
   ./start.sh
   ```

4. **Check Logs**
   ```bash
   tail -f nija.log | grep -i kraken
   ```
   
   Look for:
   ```
   ✅ Kraken MASTER connected
   💰 Kraken Balance (MASTER): USD $XXX.XX
   ```

**Status:** ☐ Local configured

### Method B: Export Environment Variables

Alternatively, export them in your shell:

```bash
export KRAKEN_MASTER_API_KEY="8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7"
export KRAKEN_MASTER_API_SECRET="e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA=="

./start.sh
```

**Note:** This method requires re-exporting every time you open a new terminal.

---

## 🔍 Verification After Deployment

### Quick Check

Run the validation script:
```bash
python3 validate_kraken_master_setup.py
```

**Expected Output:**
```
✅ ALL CHECKS PASSED!
🎉 Kraken master account is properly configured and ready to trade!
```

### Check Trading Status

```bash
python3 check_trading_status.py
```

**Expected Output:**
```
Master Exchanges Connected: 2
  - coinbase: $X.XX
  - kraken: $XXX.XX
```

### Monitor Logs

**Railway/Render:** Check deployment logs in dashboard

**Local:** 
```bash
tail -f nija.log | grep -i kraken
```

**Look for success messages:**
```
✅ Kraken MASTER connected
💰 Kraken Balance (MASTER): USD $XXX.XX
✅ FUNDED - Ready to trade
✅ Started independent trading thread for kraken (MASTER)
```

---

## 📊 What Happens Next

After deploying these credentials:

1. **Bot Starts**
   - Detects Kraken master credentials
   - Initializes Kraken broker connection

2. **Connection Established**
   - Connects to Kraken API
   - Verifies API key permissions
   - Retrieves account balance

3. **Trading Begins**
   - Starts independent trading thread for Kraken
   - Scans markets alongside Coinbase
   - Executes trades on both exchanges

4. **You'll See**
   - Positions opening on Kraken
   - Independent trading on 2 exchanges
   - Better diversification and opportunities

---

## ⚠️ Security Reminders

### ✅ DO

- ✅ Keep these credentials secure
- ✅ Use Railway/Render secret management
- ✅ Never commit `.env` file to git (already in .gitignore)
- ✅ Monitor API key usage on Kraken dashboard
- ✅ Keep 2FA enabled on your Kraken account

### ❌ DON'T

- ❌ Share these credentials publicly
- ❌ Commit them to GitHub
- ❌ Post them in Discord/Slack
- ❌ Email them unencrypted
- ❌ Store them in plain text files on shared systems

### 🔄 If Credentials Compromised

If you ever suspect these credentials are compromised:

1. **Immediately revoke the API key** on Kraken
2. **Generate new API key** with same permissions
3. **Update environment variables** in deployment
4. **Restart deployment**

---

## 📋 Next Steps

**Choose your deployment method above and follow the instructions.**

After deployment:
1. ☐ Credentials added to deployment platform
2. ☐ Deployment restarted
3. ☐ Logs checked for success messages
4. ☐ Validation script confirms connection
5. ☐ Trading status shows Kraken active
6. ☐ Monitor first trades on Kraken

**Time to completion:** ~5 minutes (depending on deployment platform)

---

## 🆘 If Something Goes Wrong

**Error: "Permission denied"**
- The API key on Kraken needs these permissions enabled:
  - Query Funds, Query Orders, Create/Modify Orders, Cancel Orders
- Log in to Kraken → Security → API → Verify permissions

**Error: "Invalid nonce"**
- Wait 1-2 minutes and restart
- This usually resolves itself
- If persistent, may need to regenerate API key

**Error: "Invalid signature"**
- Verify credentials were copied exactly (no extra spaces)
- If issue persists, regenerate API key on Kraken

**Still having issues?**
- Read: [KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md](KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md)
- Run: `python3 diagnose_master_kraken_issue.py`
- Check troubleshooting section in complete guide

---

## ✅ Status Checklist

- [x] Credentials received
- [x] Format validated (56 + 88 characters)
- [x] Local .env file created
- [ ] **Deployed to production** (choose method above)
- [ ] Connection verified
- [ ] Trading confirmed active

---

**Last Updated:** January 17, 2026  
**Credentials Locked:** ✅ Ready for deployment
