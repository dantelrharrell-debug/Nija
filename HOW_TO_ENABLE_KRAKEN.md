# How to Enable Kraken Trading - Quick Guide

**Problem**: Kraken is not connecting even though you believe environment variables are set.

**Solution**: Follow these steps to verify and fix the issue.

## Step 1: Verify Credentials Are Actually Set

### Railway
1. Go to https://railway.app
2. Click on your NIJA project
3. Click on your service
4. Click **"Variables"** tab
5. **Look for these variables** - are they ALL present?
   - `KRAKEN_MASTER_API_KEY`
   - `KRAKEN_MASTER_API_SECRET`
   - `KRAKEN_USER_DAIVON_API_KEY` (optional)
   - `KRAKEN_USER_DAIVON_API_SECRET` (optional)
   - `KRAKEN_USER_TANIA_API_KEY` (optional)
   - `KRAKEN_USER_TANIA_API_SECRET` (optional)

### Render
1. Go to https://dashboard.render.com
2. Click on your NIJA service
3. Click **"Environment"** tab
4. **Look for these variables** - are they ALL present?
   - Same list as above

## Step 2: Check for Common Issues

### Issue #1: Variables Not Set
**Symptom**: The variables don't exist in the dashboard

**Fix**:
1. Get API credentials from https://www.kraken.com/u/security/api
2. Create API key with these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
3. Add variables to Railway/Render (see Step 3)

### Issue #2: Whitespace in Values
**Symptom**: Variables exist but have leading/trailing spaces or newlines

**Fix**:
1. Click "Edit" on each variable
2. Remove any spaces before or after the value
3. Make sure there are no newlines/line breaks
4. Save each variable
5. Restart deployment

### Issue #3: Invalid/Expired Credentials
**Symptom**: Variables exist and look correct, but connection still fails

**Fix**:
1. Go to https://www.kraken.com/u/security/api
2. Delete the old API key
3. Create a new API key with correct permissions (see Issue #1)
4. Update the variables in Railway/Render
5. Restart deployment

## Step 3: Add Variables (if missing)

### Railway
1. Click **"+ New Variable"**
2. Enter **Variable Name**: `KRAKEN_MASTER_API_KEY`
3. Enter **Value**: `your-api-key-here` (no quotes, no spaces)
4. Click **"Add"**
5. Repeat for `KRAKEN_MASTER_API_SECRET`
6. Railway will auto-restart

### Render
1. Click **"Add Environment Variable"**
2. Enter **Key**: `KRAKEN_MASTER_API_KEY`
3. Enter **Value**: `your-api-key-here` (no quotes, no spaces)
4. Click **"Save Changes"**
5. Repeat for `KRAKEN_MASTER_API_SECRET`
6. Click **"Manual Deploy"** → **"Deploy latest commit"**

## Step 4: Verify It Worked

After restarting, check the deployment logs:

### ✅ Success - Look for:
```
✅ Kraken Master credentials detected
✅ Kraken MASTER connected
Active Master Exchanges:
   ✅ COINBASE
   ✅ ALPACA
   ✅ KRAKEN
```

### ❌ Still Not Working - Look for:
```
⚠️ Kraken Master credentials NOT SET
```
OR
```
⚠️ Kraken Master credentials ARE SET but CONTAIN ONLY WHITESPACE
```

## Diagnostic Tools

Run these commands to diagnose issues:

```bash
# Test live connection (run in Railway/Render environment)
python3 test_kraken_connection_live.py

# Diagnose what's wrong
python3 diagnose_kraken_connection.py

# Check status
python3 check_kraken_status.py
```

## Common Mistakes

1. ❌ **Setting variables in `.env` file** 
   - `.env` only works locally, NOT in Railway/Render
   - ✅ Must set in platform dashboard

2. ❌ **Forgetting to restart after adding variables**
   - Variables only load on deployment start
   - ✅ Always restart after changing variables

3. ❌ **Copying credentials with extra whitespace**
   - Often happens when copy/pasting
   - ✅ Trim whitespace before pasting

4. ❌ **Using API key without required permissions**
   - Trading requires specific permissions
   - ✅ Enable all trading permissions (see Step 2, Issue #1)

5. ❌ **Setting only one of the two variables**
   - Both KEY and SECRET are required
   - ✅ Set both variables

## Still Not Working?

1. Check deployment logs for specific error messages
2. Run `python3 test_kraken_connection_live.py` in the deployment
3. See detailed guides:
   - `KRAKEN_RAILWAY_RENDER_SETUP.md` - Platform-specific setup
   - `KRAKEN_NOT_CONNECTING_DIAGNOSIS.md` - Troubleshooting
   - `ANSWER_WHY_KRAKEN_NOT_CONNECTING.md` - Common issues

## For User Accounts (Daivon, Tania)

Same process, but use these variable names:

**For Daivon:**
- `KRAKEN_USER_DAIVON_API_KEY`
- `KRAKEN_USER_DAIVON_API_SECRET`

**For Tania:**
- `KRAKEN_USER_TANIA_API_KEY`
- `KRAKEN_USER_TANIA_API_SECRET`

Each user needs their own Kraken API credentials.

---

**Last Updated**: January 13, 2026
**Quick Test**: `python3 test_kraken_connection_live.py`
