# Kraken Environment Variables - Quick Reference

**Purpose**: This document lists the EXACT environment variable names needed for Kraken trading on Railway and Render.

---

## Required Environment Variables (6 Total)

### Master Account (NIJA System)
```
KRAKEN_MASTER_API_KEY
KRAKEN_MASTER_API_SECRET
```

### User #1 (Daivon Frazier)
```
KRAKEN_USER_DAIVON_API_KEY
KRAKEN_USER_DAIVON_API_SECRET
```

### User #2 (Tania Gilbert)
```
KRAKEN_USER_TANIA_API_KEY
KRAKEN_USER_TANIA_API_SECRET
```

---

## Copy-Paste Template for Railway

Add these in Railway Dashboard → Variables:

```
Variable Name: KRAKEN_MASTER_API_KEY
Value: [paste master API key from Kraken]

Variable Name: KRAKEN_MASTER_API_SECRET
Value: [paste master private key from Kraken]

Variable Name: KRAKEN_USER_DAIVON_API_KEY
Value: [paste Daivon's API key from Kraken]

Variable Name: KRAKEN_USER_DAIVON_API_SECRET
Value: [paste Daivon's private key from Kraken]

Variable Name: KRAKEN_USER_TANIA_API_KEY
Value: [paste Tania's API key from Kraken]

Variable Name: KRAKEN_USER_TANIA_API_SECRET
Value: [paste Tania's private key from Kraken]
```

---

## Copy-Paste Template for Render

Add these in Render Dashboard → Environment:

```
Key: KRAKEN_MASTER_API_KEY
Value: [paste master API key from Kraken]

Key: KRAKEN_MASTER_API_SECRET
Value: [paste master private key from Kraken]

Key: KRAKEN_USER_DAIVON_API_KEY
Value: [paste Daivon's API key from Kraken]

Key: KRAKEN_USER_DAIVON_API_SECRET
Value: [paste Daivon's private key from Kraken]

Key: KRAKEN_USER_TANIA_API_KEY
Value: [paste Tania's API key from Kraken]

Key: KRAKEN_USER_TANIA_API_SECRET
Value: [paste Tania's private key from Kraken]
```

---

## Copy-Paste Template for .env File (Local Testing)

Add these to `.env` file:

```bash
# Kraken Master Account
KRAKEN_MASTER_API_KEY=your-master-api-key-here
KRAKEN_MASTER_API_SECRET=your-master-private-key-here

# Kraken User #1 (Daivon Frazier)
KRAKEN_USER_DAIVON_API_KEY=daivon-api-key-here
KRAKEN_USER_DAIVON_API_SECRET=daivon-private-key-here

# Kraken User #2 (Tania Gilbert)
KRAKEN_USER_TANIA_API_KEY=tania-api-key-here
KRAKEN_USER_TANIA_API_SECRET=tania-private-key-here
```

**⚠️ IMPORTANT**: Never commit `.env` file to git!

---

## Variable Name Rules

### ✅ Correct Format (Case-Sensitive)
- `KRAKEN_MASTER_API_KEY` ✅
- `KRAKEN_MASTER_API_SECRET` ✅
- `KRAKEN_USER_DAIVON_API_KEY` ✅
- `KRAKEN_USER_DAIVON_API_SECRET` ✅
- `KRAKEN_USER_TANIA_API_KEY` ✅
- `KRAKEN_USER_TANIA_API_SECRET` ✅

### ❌ Wrong Format (Will NOT Work)
- `kraken_master_api_key` ❌ (lowercase)
- `Kraken_Master_Api_Key` ❌ (wrong case)
- `KRAKEN_MASTER_API_KEY ` ❌ (trailing space)
- ` KRAKEN_MASTER_API_KEY` ❌ (leading space)
- `KRAKEN_MASTER_KEY` ❌ (missing _API)
- `MASTER_KRAKEN_API_KEY` ❌ (wrong order)

---

## How to Get API Keys from Kraken

1. **Log in**: https://www.kraken.com/u/security/api
2. **Click**: "Generate New Key"
3. **Name**: "NIJA Trading Bot - [Account Name]"
4. **Permissions** (select all):
   - ✅ Query Funds
   - ✅ Query Open Orders & Trades
   - ✅ Query Closed Orders & Trades
   - ✅ Create & Modify Orders
   - ✅ Cancel/Close Orders
5. **Generate**: Click "Generate Key"
6. **SAVE BOTH**:
   - API Key (starts with "AA" or similar)
   - Private Key (long string, won't see again!)
7. **Store Securely**: Save in password manager

---

## Verification After Adding

### Check Local Status
```bash
python3 check_kraken_status.py
```

Expected output:
```
✅ Master account: CONNECTED to Kraken
✅ User #1 (Daivon Frazier): CONNECTED to Kraken
✅ User #2 (Tania Gilbert): CONNECTED to Kraken
```

### Check Deployment Status
```bash
python3 kraken_deployment_verify.py
```

Expected output:
```
✅ ALL ACCOUNTS CONFIGURED
```

### Check Deployment Logs

Look for these messages in Railway/Render logs:

```
✅ Connected to Kraken Pro API (MASTER)
💰 Master balance: $X,XXX.XX
✅ User #1 Kraken connected
💰 User #1 Kraken balance: $X,XXX.XX
✅ User #2 Kraken connected
💰 User #2 Kraken balance: $X,XXX.XX
```

---

## Troubleshooting

### Variables not recognized
- Check spelling (case-sensitive)
- Remove extra spaces
- Redeploy after adding variables

### Still says "not configured"
- Verify exact variable names match
- Check for typos in values
- Ensure no quotes around values (Railway/Render)

### "Invalid nonce" errors
- Already fixed in code
- If still occurs, check that each account has separate API keys

### "Permission denied" errors
- Verify API key has all required permissions
- Regenerate key with correct permissions if needed

---

## Security Checklist

Before adding keys to Railway/Render:

- [ ] Each account has separate API keys (don't reuse)
- [ ] 2FA enabled on all Kraken accounts
- [ ] API keys stored in password manager
- [ ] Minimum permissions granted (only what's needed)
- [ ] IP whitelisting considered (optional but recommended)
- [ ] `.env` file in `.gitignore` (if using locally)
- [ ] Never commit keys to git/GitHub

---

## Quick Links

- **Get Kraken API Keys**: https://www.kraken.com/u/security/api
- **Railway Dashboard**: https://railway.app
- **Render Dashboard**: https://render.com
- **Full Setup Guide**: [DEPLOYMENT_KRAKEN_STATUS.md](DEPLOYMENT_KRAKEN_STATUS.md)
- **Connection Status**: [KRAKEN_CONNECTION_STATUS.md](KRAKEN_CONNECTION_STATUS.md)

---

**Last Updated**: January 12, 2026  
**Total Variables Needed**: 6 (2 per account × 3 accounts)  
**Platforms**: Railway, Render, Local (.env)
