# Quick Fix: "Unseen" Kraken Variables Issue

## Problem
Kraken credentials are set in Railway/Render but NIJA reports "NOT SET"

## Root Cause
Environment variables contain **only whitespace** or **invisible characters** (newlines, tabs, spaces)

## Quick Diagnosis

Run this:
```bash
python3 diagnose_kraken_connection.py
```

Look for:
```
⚠️  KRAKEN_MASTER_API_KEY: SET BUT INVALID (contains only whitespace/invisible characters)
```

## Quick Fix (3 Steps)

### 1. Get Fresh Credentials
- Go to: https://www.kraken.com/u/security/api
- Create NEW API key
- Copy to **plain text editor** (Notepad, not Word)

### 2. Clean the Values
- Remove ALL spaces before/after the key
- Ensure key is on ONE line (no line breaks)
- No quotes, just the raw string

### 3. Set in Platform

**Railway:**
1. Dashboard → Service → **Variables**
2. **Delete** old `KRAKEN_MASTER_API_KEY` and `KRAKEN_MASTER_API_SECRET`
3. Add new variables with cleaned values
4. Wait for auto-redeploy

**Render:**
1. Dashboard → Service → **Environment**
2. **Delete** old variables
3. Add new variables with cleaned values
4. Click **Manual Deploy** → **Deploy latest commit**

## Verification

After redeploy, check logs for:
```
✅ KRAKEN (Master): Configured (Key: 16 chars, Secret: 88 chars)
✅ Kraken MASTER connected
```

## Still Not Working?

See full guide: **KRAKEN_CREDENTIAL_TROUBLESHOOTING.md**

---

**Pro Tip**: After pasting a value in Railway/Render, select all the text in that field (Ctrl+A), copy it (Ctrl+C), delete it (Delete key), then paste it back (Ctrl+V). This removes invisible characters from copy-paste.
