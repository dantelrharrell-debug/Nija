# ⚠️ KRAKEN NOT TRADING? READ THIS FIRST

## Quick Diagnosis

If you see these messages in your logs:
```
❌ USER: Daivon Frazier: NOT TRADING (Broker: KRAKEN, Connection failed)
❌ USER: Tania Gilbert: NOT TRADING (Broker: KRAKEN, Connection failed)
⚠️  SINGLE EXCHANGE TRADING - CONSIDER ENABLING KRAKEN
```

**This is NOT a bug.** It means your Kraken API credentials are not configured.

## Quick Fix (10 minutes)

### For Master Account Only

1. **Get API credentials** from https://www.kraken.com/u/security/api
   - Enable permissions: Query Funds, Query Orders, Create Orders, Cancel Orders
   - ❌ DO NOT enable: Withdraw, Funding

2. **Add to Railway/Render:**
   ```
   KRAKEN_MASTER_API_KEY = [your-api-key]
   KRAKEN_MASTER_API_SECRET = [your-secret]
   ```

3. **Disable users** (if you don't have their credentials):
   - Edit `config/users/retail_kraken.json`
   - Set `"enabled": false` for each user

4. **Redeploy** and check logs

### For User Accounts

**IMPORTANT:** Each user needs THEIR OWN Kraken account. You cannot use one account for everyone.

- Daivon needs his own Kraken account → `KRAKEN_USER_DAIVON_API_KEY/SECRET`
- Tania needs her own Kraken account → `KRAKEN_USER_TANIA_API_KEY/SECRET`

See [KRAKEN_QUICK_START.md](KRAKEN_QUICK_START.md) for complete instructions.

## Verify Configuration

```bash
python3 verify_kraken_users.py  # Shows which credentials are missing
python3 test_kraken_users.py    # Tests actual connections
```

## Documentation

- **Setup Guide:** [KRAKEN_QUICK_START.md](KRAKEN_QUICK_START.md)
- **Quick Start:** [QUICKFIX_KRAKEN_USERS.md](QUICKFIX_KRAKEN_USERS.md)
- **Environment Variables:** [.env.example](.env.example)

---

**Bottom Line:** Kraken needs API credentials just like Coinbase does. Add them to Railway/Render environment variables.
