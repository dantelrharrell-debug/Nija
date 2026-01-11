# Quick Start: Get User #1 Trading Now

**TL;DR**: User #1 needs Kraken SDK installed. Run `pip install -r requirements.txt` in production.

---

## The Fix (60 seconds)

### Option 1: Railway/Render (Recommended)
1. Go to deployment dashboard
2. Trigger a fresh deployment (redeploy)
3. Dependencies will auto-install from requirements.txt
4. Check logs for: `✅ USER #1 (Daivon Frazier): TRADING`

### Option 2: Manual Server
```bash
# SSH into your server
cd /path/to/Nija
pip install -r requirements.txt
./start.sh
```

### Option 3: Local Development
```bash
pip install krakenex==2.2.2 pykrakenapi==0.3.2
python3 test_user1_connection.py  # Verify
./start.sh
```

---

## What Was Wrong

**Missing Python packages** in the environment:
- `krakenex==2.2.2` (Kraken API client)
- `pykrakenapi==0.3.2` (Kraken API wrapper)

These are in `requirements.txt` but weren't installed.

---

## How to Verify It's Fixed

### Check 1: Startup Logs
Look for these messages in bot logs:
```
📊 Attempting to connect User #1 (Daivon Frazier) - Kraken...
   ✅ User #1 Kraken connected
   💰 User #1 Kraken balance: $XXX.XX
✅ USER #1 (Daivon Frazier): TRADING (Broker: Kraken)
✅ Started independent trading thread for daivon_frazier_kraken (USER)
```

### Check 2: Trading Cycles
After 5-30 minutes, look for:
```
🔄 daivon_frazier_kraken - Cycle #1
   daivon_frazier_kraken: Running trading cycle...
   ✅ daivon_frazier_kraken cycle completed successfully
```

### Check 3: Run Test Script
```bash
python3 test_user1_connection.py
```

Should show:
```
✅ Kraken SDK: PASS
✅ User #1 Credentials: PASS
✅ Direct Broker Connection: PASS
```

---

## Environment Variables Required

Make sure these are set in your deployment platform:

```bash
KRAKEN_USER_DAIVON_API_KEY=<your-key>
KRAKEN_USER_DAIVON_API_SECRET=<your-secret>
```

*(Already in .env file for local dev)*

---

## Files Added

1. **test_user1_connection.py** - Test User #1 configuration
2. **FIX_USER1_TRADING_ISSUE_JAN_11_2026.md** - Full documentation
3. **QUICK_FIX_USER1_TRADING.md** - This file (quick reference)

---

## Account Separation

User #1 uses **different API keys** from master account:
- Master: `KRAKEN_MASTER_API_KEY`
- User #1: `KRAKEN_USER_DAIVON_API_KEY`

**Different keys = Different Kraken accounts = 100% isolated**

---

## Troubleshooting

### "User #1 NOT TRADING"
```bash
# Install dependencies
pip install -r requirements.txt

# Check credentials
echo $KRAKEN_USER_DAIVON_API_KEY  # Should show key

# Restart bot
./start.sh
```

### "Kraken SDK not installed"
```bash
pip install krakenex==2.2.2 pykrakenapi==0.3.2
```

### "Credentials not configured"
Check deployment platform environment variables:
- Railway: Dashboard → Variables
- Render: Dashboard → Environment
- Local: Check .env file exists

---

**Issue**: User #1 not trading  
**Cause**: Missing Kraken SDK packages  
**Fix**: Install requirements.txt  
**Time**: 60 seconds  
**Risk**: None (no code changes)
