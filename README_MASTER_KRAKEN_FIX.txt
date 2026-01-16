# READ ME: Master Kraken Trading Not Working

## Quick Answer

Your master account can't trade on Kraken because **the credentials are not set** in your deployment.

## The Fix (5 minutes)

1. **Run this diagnostic:**
   ```bash
   python3 quick_fix_master_kraken.py
   ```

2. **Follow the instructions** it gives you

3. **Or read the full guide:**
   - See `ENABLE_MASTER_KRAKEN_TRADING.md` in this repository

## What's Wrong

Your setup right now:
- ✅ Coinbase Master: Trading
- ❌ Kraken Master: NOT trading (credentials missing)
- ✅ User tania_gilbert (Kraken): Trading
- ✅ User daivon_frazier (Kraken): Trading

## What You Need

Add these to Railway or Render:
```bash
KRAKEN_MASTER_API_KEY=<your-key-from-kraken>
KRAKEN_MASTER_API_SECRET=<your-secret-from-kraken>
```

## Where to Get Credentials

1. https://www.kraken.com/u/security/api
2. Generate new key
3. Copy API Key and Private Key
4. Add to Railway/Render environment variables
5. Restart

## Important

- ⚠️ Use a DIFFERENT API key than your user accounts
- ⚠️ Enable all required permissions (Query Funds, Orders, etc.)
- ⚠️ No spaces or newlines in the values
- ⚠️ Spelling must be EXACTLY: `KRAKEN_MASTER_API_KEY`

## Resources

| File | Purpose |
|------|---------|
| `quick_fix_master_kraken.py` | Run this first - diagnoses the issue |
| `ENABLE_MASTER_KRAKEN_TRADING.md` | Complete step-by-step guide |
| `setup_kraken_master.py` | Interactive setup wizard |

## No Code Changes Needed

The code is already correct. You just need to add environment variables.

---

**TL;DR:** Run `python3 quick_fix_master_kraken.py` and follow the instructions.
