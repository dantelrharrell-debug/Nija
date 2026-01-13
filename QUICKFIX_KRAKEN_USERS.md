# 🚀 QUICK START: Fix "NOT TRADING" Status for Kraken Users

## The Problem You're Seeing

```
❌ USER: Daivon Frazier: NOT TRADING (Connection failed or not configured)
❌ USER: Tania Gilbert: NOT TRADING (Connection failed or not configured)
```

## What This Means

✅ **Good News**: Your users are configured correctly in the system
❌ **Missing**: Kraken API credentials in environment variables

## ⚡ 3-Step Fix (10 Minutes)

### Step 1: Get API Credentials (5 min)

1. Go to: https://www.kraken.com/u/security/api
2. Create **3 separate API keys**:
   - One for "Master Account"
   - One for "Daivon Frazier"
   - One for "Tania Gilbert"
3. For each key, enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. **Save each API Key and Private Key** (you won't see them again!)

### Step 2: Add to Railway/Render (2 min)

#### For Railway:
1. Open: https://railway.app/dashboard
2. Select your NIJA project
3. Click "Variables" tab
4. Click "New Variable" and add each of these 6:

```
KRAKEN_MASTER_API_KEY = [paste master API key]
KRAKEN_MASTER_API_SECRET = [paste master private key]
KRAKEN_USER_DAIVON_API_KEY = [paste Daivon's API key]
KRAKEN_USER_DAIVON_API_SECRET = [paste Daivon's private key]
KRAKEN_USER_TANIA_API_KEY = [paste Tania's API key]
KRAKEN_USER_TANIA_API_SECRET = [paste Tania's private key]
```

5. Railway will automatically redeploy (takes ~2 minutes)

#### For Render:
1. Open: https://dashboard.render.com
2. Select your NIJA service
3. Click "Environment" tab
4. Add the same 6 variables as above
5. Click "Manual Deploy" → "Deploy latest commit"

### Step 3: Verify (3 min)

After the redeploy completes, check your bot logs. You should see:

```
✅ MASTER: Kraken connected
✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
```

## 🔍 Diagnostic Tools

### Before Adding Credentials

Check which credentials are missing:

```bash
python3 verify_kraken_users.py
```

Output will show exactly which variables are NOT SET.

### After Adding Credentials

Test that connections work:

```bash
python3 test_kraken_users.py
```

Output will show if each account connected successfully.

## ❌ Common Issues

### "Still showing NOT TRADING"

**Checklist:**
- [ ] Added all 6 environment variables?
- [ ] No typos in variable names? (case-sensitive!)
- [ ] No extra spaces in the values?
- [ ] Waited for redeploy to complete?
- [ ] API keys have correct permissions on Kraken?

**Quick Fix:**
1. Run: `python3 verify_kraken_users.py`
2. Fix any variables showing ❌ NOT SET or ⚠️ SET but EMPTY
3. Delete and re-add the variable in Railway/Render
4. Wait for redeploy

### "Permission denied" error

Your API keys don't have the right permissions.

**Fix:**
1. Go to: https://www.kraken.com/u/security/api
2. Edit each API key
3. Enable all required permissions (see Step 1)
4. Save and restart bot

### "Invalid nonce" error

You're using the same API key in multiple places.

**Fix:**
1. Create separate API keys for each account
2. Delete any duplicate keys on Kraken
3. Wait 5 minutes, then create fresh keys
4. Update environment variables with new keys

## 📖 More Documentation

- **Complete Guide**: [SETUP_KRAKEN_USERS.md](SETUP_KRAKEN_USERS.md)
- **Quick Answer**: [ANSWER_KRAKEN_USER_SETUP.md](ANSWER_KRAKEN_USER_SETUP.md)
- **Full Solution**: [KRAKEN_USER_CONNECTION_SOLUTION.md](KRAKEN_USER_CONNECTION_SOLUTION.md)

## ✅ Success Looks Like

When everything is working:

```bash
$ python3 verify_kraken_users.py
✅ ALL CHECKS PASSED

$ python3 test_kraken_users.py
✅ MASTER account connected successfully
💰 Master balance: $1,234.56
✅ Daivon Frazier connected successfully
💰 Daivon Frazier balance: $567.89
✅ Tania Gilbert connected successfully
💰 Tania Gilbert balance: $890.12
```

And in your bot logs:
```
✅ USER: Daivon Frazier: TRADING (Broker: Kraken)
✅ USER: Tania Gilbert: TRADING (Broker: Kraken)
```

## 🎯 Bottom Line

**Problem**: Missing 6 environment variables
**Solution**: Add them to Railway/Render
**Time**: 10 minutes
**Result**: Users will show TRADING ✅

---

Need help? See the complete guides linked above or run the diagnostic scripts.
