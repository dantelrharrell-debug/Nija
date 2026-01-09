# Is NIJA Trading on Kraken?

## ❌ NO

**NIJA is NOT trading on Kraken.**

---

## What's Actually Happening?

✅ **NIJA IS trading on Coinbase Advanced Trade**

All buy and sell orders are executed on Coinbase, not Kraken.

---

## Why Not Kraken?

Kraken credentials are not configured:
- Missing: `KRAKEN_API_KEY`
- Missing: `KRAKEN_API_SECRET`

---

## Want to Enable Kraken?

### Quick Setup (3 steps):

1. **Set credentials:**
   ```bash
   export KRAKEN_API_KEY="your_key"
   export KRAKEN_API_SECRET="your_secret"
   ```

2. **Install SDK:**
   ```bash
   pip install krakenex pykrakenapi
   ```

3. **Restart bot:**
   ```bash
   ./start.sh
   ```

---

## Verify Status

```bash
python3 check_broker_status.py
python3 check_kraken_connection_status.py
```

---

## Full Details

See: **[ANSWER_IS_NIJA_TRADING_ON_KRAKEN_NOW.md](./ANSWER_IS_NIJA_TRADING_ON_KRAKEN_NOW.md)**

---

**Bottom Line:** Currently trading on Coinbase only. Kraken support exists in code but needs credentials to activate.

*Status: 2026-01-09 07:03 UTC*
