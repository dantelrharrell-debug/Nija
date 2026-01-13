# Kraken Master Account - Legacy Credentials Solution

## Your Current Setup

You have Kraken credentials set in Railway as:
- `KRAKEN_API_KEY` ✅
- `KRAKEN_API_SECRET` ✅

But NIJA is looking for:
- `KRAKEN_MASTER_API_KEY` ❌
- `KRAKEN_MASTER_API_SECRET` ❌

## The Good News

**NIJA now supports legacy credentials!** You don't need to rename your variables.

## What Changed

The bot now automatically falls back to `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` if the master-specific credentials aren't set. This provides backward compatibility for existing deployments.

## Two Options to Fix

### Option 1: Do Nothing (Recommended)

Just **redeploy** your Railway service with the latest code. The bot will automatically use your existing `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` for the master account.

**Steps:**
1. Wait for this PR to be merged to main
2. Railway will auto-redeploy with the new code
3. Check logs - you should see:
   ```
   ✅ Using legacy KRAKEN_API_KEY for master account
   ✅ Using legacy KRAKEN_API_SECRET for master account
   ✅ Kraken MASTER connected
   ```

### Option 2: Rename to New Format (Future-proof)

If you want to use the newer naming convention:

**Railway:**
1. Go to Dashboard → Service → **Variables**
2. Click **"+ New Variable"**
3. Add `KRAKEN_MASTER_API_KEY` = (copy value from `KRAKEN_API_KEY`)
4. Add `KRAKEN_MASTER_API_SECRET` = (copy value from `KRAKEN_API_SECRET`)
5. *(Optional)* Delete old `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`
6. Wait for auto-redeploy

**Why rename?**
- More explicit about which account uses which credentials
- Consistent with user account naming (e.g., `KRAKEN_USER_DAIVON_API_KEY`)
- Future-proof if you ever need to separate master from other trading accounts

## Your User Accounts

Your user account credentials are already correctly named:
- ✅ `KRAKEN_USER_DAIVON_API_KEY` / `KRAKEN_USER_DAIVON_API_SECRET`
- ✅ `KRAKEN_USER_TANIA_API_KEY` / `KRAKEN_USER_TANIA_API_SECRET`

These will work without any changes.

## Expected Behavior After Fix

**With Legacy Credentials (Option 1):**
```
📊 Attempting to connect Kraken Pro (MASTER)...
   Using legacy KRAKEN_API_KEY for master account
   Using legacy KRAKEN_API_SECRET for master account
   ✅ Kraken MASTER connected

📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ Kraken USER:daivon_frazier connected

📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ Kraken USER:tania_gilbert connected
```

**With Renamed Credentials (Option 2):**
```
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected

📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ Kraken USER:daivon_frazier connected

📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ Kraken USER:tania_gilbert connected
```

## Summary

**You don't need to do anything!** Once this code is deployed, your existing `KRAKEN_API_KEY` and `KRAKEN_API_SECRET` will work automatically for the master account. All three Kraken accounts (master, Daivon, Tania) will connect successfully.

---

**Last Updated**: January 13, 2026  
**Related**: This is the fix for the issue you reported in comment #3741325753
