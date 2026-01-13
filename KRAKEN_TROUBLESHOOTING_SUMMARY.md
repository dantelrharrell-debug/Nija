# Kraken Connection Troubleshooting - Consolidated Guide

**Last Updated**: January 13, 2026  
**Purpose**: Single source of truth for Kraken connection issues

---

## 🎯 Quick Diagnosis

### Run Status Check
```bash
python3 check_kraken_status.py
```

### Interpret Results

| Output | Meaning | Fix |
|--------|---------|-----|
| `❌ NOT SET` | Environment variable not configured | Set the environment variable |
| `✅ SET` but connection fails | Credentials invalid or insufficient permissions | Check API key permissions on Kraken |
| `⚠️ SET but contains only whitespace` | Variable exists but is empty | Remove/fix the variable |
| `❌ Permission error` | API key lacks required permissions | Update permissions on Kraken website |
| `❌ Invalid nonce` | Nonce collision or clock sync issue | Already fixed in code - restart bot |

---

## 🔧 Common Issues & Solutions

### Issue 1: "NOT SET" - Credentials Not Configured

**Symptom**:
```
❌ Master account: NOT connected to Kraken
❌ KRAKEN_MASTER_API_KEY: NOT SET
❌ KRAKEN_MASTER_API_SECRET: NOT SET
```

**Root Cause**: Environment variables not configured

**Solution**:
1. **Quick Fix**: Run `python3 setup_kraken_credentials.py`
2. **Manual Fix**: See [CURRENT_KRAKEN_STATUS.md](CURRENT_KRAKEN_STATUS.md) for detailed instructions
3. **Railway**: Go to Variables tab → Add Variable
4. **Render**: Go to Environment tab → Add Environment Variable

**Time to Fix**: 5-10 minutes (if you have API keys ready)

---

### Issue 2: "Permission Error" - API Key Lacks Permissions

**Symptom**:
```
⚠️ Kraken connection failed: API-EPERMISSION:Permission denied
⚠️ Skipping Kraken connection for MASTER - previous permission error
   Fix API key permissions at https://www.kraken.com/u/security/api
```

**Root Cause**: API key created without required permissions

**Required Permissions**:
- ✅ Query Funds
- ✅ Query Open Orders & Trades
- ✅ Query Closed Orders & Trades
- ✅ Create & Modify Orders
- ✅ Cancel/Close Orders
- ❌ Withdraw Funds (NOT needed - leave unchecked)

**Solution**:
1. Go to https://www.kraken.com/u/security/api
2. Delete old API key (or create new one)
3. Create new API key with all 5 required permissions
4. Update environment variables with new credentials
5. Restart bot

**Time to Fix**: 5 minutes

---

### Issue 3: "Invalid Nonce" Errors

**Symptom**:
```
EAPI:Invalid nonce
```

**Root Cause**: 
- Multiple requests with same nonce
- Clock not synchronized
- Rapid consecutive API calls

**Solution**: 
✅ **ALREADY FIXED IN CODE** - Nonce collision prevention implemented

If you still see this:
1. Restart the bot (clears nonce state)
2. Check system time is synchronized (NTP)
3. Wait 60 seconds between restart attempts

**Time to Fix**: 1 minute (just restart)

---

### Issue 4: Variables Set But Contains Whitespace

**Symptom**:
```
⚠️ Kraken credentials DETECTED but INVALID for MASTER
   KRAKEN_MASTER_API_KEY: SET but contains only whitespace/invisible characters
```

**Root Cause**: 
- Copied credential with leading/trailing spaces
- Line breaks or tabs in the value
- Empty string assigned to variable

**Solution**:
1. Check your deployment platform (Railway/Render)
2. Edit the environment variable
3. Remove any spaces, newlines, or invisible characters
4. Paste the credential again (copy from Kraken directly)
5. Save and redeploy

**Railway**: Variables tab → Click edit → Remove spaces → Save
**Render**: Environment tab → Edit → Trim whitespace → Save Changes

**Time to Fix**: 2 minutes

---

### Issue 5: Rate Limiting / 429 Errors

**Symptom**:
```
429 Too Many Requests
```

**Root Cause**: Making too many API calls too quickly

**Solution**: 
✅ **ALREADY HANDLED IN CODE** - Rate limiting with backoff implemented

If persistent:
1. Wait 60 seconds
2. Restart bot
3. Bot will automatically throttle requests

**Time to Fix**: 1 minute (automatic)

---

### Issue 6: "Forbidden" / 403 Errors

**Symptom**:
```
403 Forbidden - Too many errors
```

**Root Cause**: API key temporarily banned due to repeated errors

**Solution**:
1. Wait 5-10 minutes (ban is temporary)
2. Fix underlying issue (usually permission error)
3. Restart bot after cooldown period

**Time to Fix**: 10 minutes (waiting period)

---

### Issue 7: Mixed Credentials (Master + Legacy)

**Symptom**: Some accounts work, others don't

**Root Cause**: Using `KRAKEN_API_KEY` (legacy) and `KRAKEN_MASTER_API_KEY` (new) simultaneously

**Solution**:
**Recommended**: Use new format for all accounts
```bash
# Use this format (new):
KRAKEN_MASTER_API_KEY=...
KRAKEN_MASTER_API_SECRET=...
KRAKEN_USER_DAIVON_API_KEY=...
KRAKEN_USER_DAIVON_API_SECRET=...
KRAKEN_USER_TANIA_API_KEY=...
KRAKEN_USER_TANIA_API_SECRET=...
```

**Fallback** (legacy, for backward compatibility):
```bash
# Master account can use legacy:
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
```

**Time to Fix**: 5 minutes

---

## 📋 Verification Checklist

After fixing any issue, verify:

### 1. Check Credential Status
```bash
python3 check_kraken_status.py
```
**Expected**: All accounts show `✅ SET` and `✅ CONFIGURED`

### 2. Verify User Configuration
```bash
python3 verify_kraken_users.py
```
**Expected**: All users show `✅ ENABLED` with valid credentials

### 3. Test Live Connection
```bash
python3 test_kraken_connection_live.py
```
**Expected**: Successful connection to Kraken API

### 4. Check Bot Logs
```bash
./start.sh
# Or check Railway/Render logs
```
**Expected**:
```
✅ Kraken connected (MASTER)
✅ Kraken connected (USER:daivon_frazier)
✅ Kraken connected (USER:tania_gilbert)
📊 Trading will occur on exchange(s): COINBASE, KRAKEN
```

---

## 🚀 Quick Reference Commands

| Task | Command |
|------|---------|
| Check status | `python3 check_kraken_status.py` |
| Interactive setup | `python3 setup_kraken_credentials.py` |
| Verify users | `python3 verify_kraken_users.py` |
| Test connection | `python3 test_kraken_connection_live.py` |
| Check infrastructure | `python3 verify_kraken_infrastructure.py` |
| Start bot (local) | `./start.sh` |

---

## 📚 Related Documentation

### Primary References
- **[CURRENT_KRAKEN_STATUS.md](CURRENT_KRAKEN_STATUS.md)** - Current status and setup guide
- **[KRAKEN_SETUP_GUIDE.md](KRAKEN_SETUP_GUIDE.md)** - Step-by-step setup instructions
- **[HOW_TO_ENABLE_KRAKEN.md](HOW_TO_ENABLE_KRAKEN.md)** - Quick start guide

### Deployment Guides
- **[RAILWAY_KRAKEN_SETUP.md](RAILWAY_KRAKEN_SETUP.md)** - Railway deployment
- **[MULTI_USER_SETUP_GUIDE.md](MULTI_USER_SETUP_GUIDE.md)** - User management

### Technical Details
- **[KRAKEN_CREDENTIAL_TROUBLESHOOTING.md](KRAKEN_CREDENTIAL_TROUBLESHOOTING.md)** - Detailed troubleshooting
- **[KRAKEN_NONCE_IMPROVEMENTS.md](KRAKEN_NONCE_IMPROVEMENTS.md)** - Nonce collision fix
- **[KRAKEN_CONNECTION_CONFIRMED.md](KRAKEN_CONNECTION_CONFIRMED.md)** - Infrastructure verification

---

## 🆘 Still Having Issues?

### 1. Check Documentation
Review [CURRENT_KRAKEN_STATUS.md](CURRENT_KRAKEN_STATUS.md) for complete setup instructions

### 2. Run Diagnostics
```bash
python3 diagnose_kraken_connection.py
```

### 3. Check Existing Issues
Many issues are already documented in the guides above

### 4. File New Issue
If problem persists, file a GitHub issue with:
- Output of `python3 check_kraken_status.py`
- Output of `python3 verify_kraken_users.py`
- Bot logs (redact credentials!)
- Deployment platform (Railway/Render/Local)

---

## ✅ Success Criteria

You know Kraken is working when:

1. ✅ `check_kraken_status.py` shows all accounts `CONFIGURED`
2. ✅ `test_kraken_connection_live.py` connects successfully
3. ✅ Bot logs show `✅ Kraken connected` for all accounts
4. ✅ Bot logs show `Trading will occur on ... KRAKEN`
5. ✅ Trades appear in Kraken account

---

**Remember**: The infrastructure is complete. 99% of issues are just missing or incorrect credentials.

**Estimated Time to Fix Most Issues**: 5-10 minutes
