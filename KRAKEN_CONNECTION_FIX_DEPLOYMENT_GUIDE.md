# Kraken Connection Fix - Deployment Guide

**Date**: January 11, 2026  
**Issue**: Kraken not connecting for Master and Users #1 and #2  
**Status**: Code is correct, needs deployment with environment variables

---

## Problem Analysis

The code in `bot/trading_strategy.py` and `bot/broker_manager.py` is **already configured correctly** to connect Kraken for all three accounts:

1. ✅ Master account
2. ✅ User #1 (Daivon Frazier)
3. ✅ User #2 (Tania Gilbert)

**The issue is**: Environment variables are not set in the deployment platform (Railway/Render).

---

## Required Environment Variables

### Master Account
```bash
KRAKEN_MASTER_API_KEY=<your-master-api-key>
KRAKEN_MASTER_API_SECRET=<your-master-api-secret>
```

### User #1 (Daivon Frazier)
```bash
KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
```

### User #2 (Tania Gilbert)
```bash
KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
```

---

## How the Code Works

### Environment Variable Naming Convention

The code uses this logic to construct environment variable names:

```python
# For user_id = "daivon_frazier"
user_env_name = "DAIVON"  # Extracts first part before underscore
# Looks for: KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET

# For user_id = "tania_gilbert"
user_env_name = "TANIA"  # Extracts first part before underscore
# Looks for: KRAKEN_USER_TANIA_API_KEY and KRAKEN_USER_TANIA_API_SECRET
```

### Connection Flow

1. **Master Account** (`trading_strategy.py` line 224-237):
   ```python
   kraken = KrakenBroker(account_type=AccountType.MASTER)
   if kraken.connect():
       # Registers as MASTER broker
   ```

2. **User #1** (`trading_strategy.py` line 305-323):
   ```python
   user1_id = "daivon_frazier"
   user1_broker_type = BrokerType.KRAKEN
   user1_kraken = self.multi_account_manager.add_user_broker(user1_id, user1_broker_type)
   ```

3. **User #2** (`trading_strategy.py` line 332-352):
   ```python
   user2_id = "tania_gilbert"
   user2_broker_type = BrokerType.KRAKEN
   user2_kraken = self.multi_account_manager.add_user_broker(user2_id, user2_broker_type)
   ```

---

## Deployment Steps

### Option 1: Railway

1. **Navigate to your Railway project**
   - Go to: https://railway.app/
   - Select your NIJA project

2. **Add Environment Variables**
   - Click on "Variables" tab
   - Add each variable one at a time:
     ```
     KRAKEN_MASTER_API_KEY = <value>
     KRAKEN_MASTER_API_SECRET = <value>
     KRAKEN_USER_DAIVON_API_KEY = 8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
     KRAKEN_USER_DAIVON_API_SECRET = e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
     KRAKEN_USER_TANIA_API_KEY = XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
     KRAKEN_USER_TANIA_API_SECRET = iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
     ```

3. **Deploy**
   - Railway will automatically redeploy when you save variables
   - Or manually trigger a redeploy

4. **Verify**
   - Check logs for connection messages
   - Look for: "✅ MASTER ACCOUNT: TRADING"
   - Look for: "✅ USER #1 (Daivon Frazier): TRADING"
   - Look for: "✅ USER #2 (Tania Gilbert): TRADING"

### Option 2: Render

1. **Navigate to your Render service**
   - Go to: https://render.com/
   - Select your NIJA service

2. **Add Environment Variables**
   - Click on "Environment" tab
   - Add each variable:
     ```
     KRAKEN_MASTER_API_KEY = <value>
     KRAKEN_MASTER_API_SECRET = <value>
     KRAKEN_USER_DAIVON_API_KEY = 8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
     KRAKEN_USER_DAIVON_API_SECRET = e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==
     KRAKEN_USER_TANIA_API_KEY = XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
     KRAKEN_USER_TANIA_API_SECRET = iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==
     ```

3. **Save and Deploy**
   - Render auto-deploys when you save environment changes

4. **Verify**
   - Check deployment logs
   - Look for connection confirmation messages

### Option 3: Local Testing (.env file)

1. **Create .env file** in repository root:
   ```bash
   cd /path/to/Nija
   touch .env
   ```

2. **Add variables to .env**:
   ```bash
   # Master Kraken credentials (if you have them)
   KRAKEN_MASTER_API_KEY=<your-master-key>
   KRAKEN_MASTER_API_SECRET=<your-master-secret>

   # User #1 (Daivon Frazier)
   KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7
   KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==

   # User #2 (Tania Gilbert)
   KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/
   KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==

   # Other Coinbase/Alpaca vars as needed...
   ```

3. **Test locally**:
   ```bash
   python diagnose_kraken_multi_accounts.py
   ```

---

## Expected Log Output

After deployment with correct environment variables, you should see:

```
======================================================================
📊 Attempting to connect Kraken Pro (MASTER)...
   ✅ Kraken MASTER connected
   ✅ Kraken registered as MASTER broker in multi-account manager

======================================================================
👤 CONNECTING USER ACCOUNTS
======================================================================
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $XX.XX

📊 Attempting to connect User #2 (Tania Gilbert) - Kraken...
   ✅ User #2 Kraken connected
   💰 User #2 Kraken balance: $XX.XX

======================================================================
📊 ACCOUNT TRADING STATUS SUMMARY
======================================================================
✅ MASTER ACCOUNT: TRADING (Broker: kraken)
✅ USER #1 (Daivon Frazier): TRADING (Broker: Kraken)
✅ USER #2 (Tania Gilbert): TRADING (Broker: Kraken)
```

---

## Troubleshooting

### Issue: "Kraken credentials not configured"

**Cause**: Environment variables not set or misspelled

**Solution**:
1. Double-check variable names (case-sensitive):
   - `KRAKEN_USER_DAIVON_API_KEY` (not `KRAKEN_USER_daivon_API_KEY`)
   - `KRAKEN_USER_TANIA_API_KEY` (not `KRAKEN_USER_tania_API_KEY`)
2. Verify no extra spaces in values
3. Ensure deployment platform saved the variables

### Issue: "Permission denied" error

**Cause**: Kraken API key lacks required permissions

**Solution**:
1. Go to https://www.kraken.com/u/security/api
2. Edit the API key
3. Enable these permissions:
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
4. Do NOT enable: Withdraw Funds (security risk)

### Issue: "Invalid nonce" error

**Cause**: Clock drift or rapid API requests

**Solution**:
- The code already has nonce fix built-in
- If persistent, check server time synchronization
- Error should auto-retry and resolve

### Issue: "Connection timeout"

**Cause**: Network issue or Kraken API down

**Solution**:
- Check https://status.kraken.com/
- Code will retry automatically
- If persistent, contact Kraken support

---

## Verification Checklist

After deployment, verify:

- [ ] Master Kraken connection message in logs
- [ ] User #1 (Daivon) connection message in logs
- [ ] User #2 (Tania) connection message in logs
- [ ] All three show "TRADING" status
- [ ] Balance displayed for each account
- [ ] No "credentials not configured" warnings
- [ ] No permission errors
- [ ] Trading cycles starting

---

## Security Notes

⚠️ **CRITICAL**: Never commit API keys to git

- `.env` file is in `.gitignore` (protected)
- Environment variables on deployment platforms are encrypted
- API keys in this doc should be rotated if leaked
- Use separate API keys for each account
- Enable 2FA on Kraken accounts
- Monitor API key usage regularly

---

## Summary

**The Problem**: Environment variables not set on deployment platform  
**The Solution**: Add 6 environment variables (2 master + 2 user1 + 2 user2)  
**The Result**: All three Kraken accounts will connect and trade  

**No code changes needed** - the implementation is already correct!

---

## Related Files

- `bot/trading_strategy.py` - Lines 224-400 (broker initialization)
- `bot/broker_manager.py` - Lines 3188-3494 (KrakenBroker class)
- `bot/multi_account_broker_manager.py` - Multi-account manager
- `USER_SETUP_COMPLETE_DAIVON.md` - User #1 documentation
- `USER_SETUP_COMPLETE_TANIA.md` - User #2 documentation
- `.env.example` - Environment variable template

---

**Last Updated**: January 11, 2026  
**Status**: Ready for deployment  
**Next Action**: Set environment variables on Railway/Render
