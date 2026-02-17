# Live Balance Audit - Quick Start Guide

## Purpose
Run `live_balance_audit.py` to determine if NIJA is:
- **CONFIG-HARDENED**: Has correct settings but can't execute (credentials missing)
- **EXECUTION-HARDENED**: Can execute trades in production (API connected, balance accessible)

## Quick Run

```bash
python3 live_balance_audit.py
```

## What It Checks

1. ✅ **Environment Variables** - Are Kraken API credentials set?
2. ✅ **API Connection** - Can we connect to Kraken?
3. ✅ **Balance Access** - Can we fetch live account balance?
4. ✅ **API Capabilities** - Can we read market data?

## Possible Verdicts

### 🎯 EXECUTION-HARDENED (Score ≥75%)
- ✅ All components working
- ✅ Real API connection established
- ✅ Live balance accessible
- ✅ Production-ready for trading

**Action:** Start trading with confidence

### ⚠️ PARTIALLY HARDENED (Score 50-74%)
- ⚠️ Some components work, others don't
- ⚠️ Has credentials but incomplete functionality
- ⚠️ Needs debugging before production

**Action:** Fix failing components, re-run audit

### 📝 CONFIG-HARDENED (Score <50%)
- ❌ Missing API credentials
- ❌ Cannot connect to exchange
- ❌ Cannot execute trades
- ❌ "Paper tiger" - looks good but doesn't work

**Action:** Configure credentials, re-run audit

## Current Status

**Last Run:** February 17, 2026, 15:12:57 UTC

```
📝  VERDICT: CONFIG-HARDENED  📝
Overall Score: 0.0%

Missing:
  ❌ KRAKEN_PLATFORM_API_KEY not set
  ❌ KRAKEN_PLATFORM_API_SECRET not set
```

## How to Fix (Achieve Execution-Hardening)

### Step 1: Get Kraken API Credentials
1. Log into Kraken
2. Go to Settings → API
3. Create API key with permissions:
   - Query Funds
   - Query Open Orders & Trades
   - Create & Modify Orders
   - Cancel/Close Orders

### Step 2: Configure Environment

**Local Development:**
```bash
# Create .env file
echo "KRAKEN_PLATFORM_API_KEY=your_key_here" > .env
echo "KRAKEN_PLATFORM_API_SECRET=your_secret_here" >> .env
```

**Railway/Production:**
```bash
railway variables set KRAKEN_PLATFORM_API_KEY="your_key"
railway variables set KRAKEN_PLATFORM_API_SECRET="your_secret"
```

### Step 3: Re-run Audit
```bash
python3 live_balance_audit.py
```

Expected output if successful:
```
✅ Environment Variables: 100% configured
✅ API Connection: Established
✅ Balance Access: $XXX.XX
✅ API Capabilities: 100% functional

🎯  VERDICT: EXECUTION-HARDENED  🎯
Overall Score: 100.0%
```

## Why This Matters

### CONFIG-HARDENED ❌
- Has code, but never tested with real API
- Looks good in demos, fails in production
- 90% of bugs only appear with live trading
- **Cannot make money** (no connection to exchange)

### EXECUTION-HARDENED ✅
- Proven to work with real exchange API
- Survived production conditions
- Can place real orders with real money
- **Can make money** (everything connected)

## FAQ

**Q: Do I need real money in the account?**  
A: No, just valid API credentials. Balance can be $0.00 and still be execution-hardened.

**Q: Can I use testnet/sandbox?**  
A: No, only production API counts. Sandbox is still config-hardening.

**Q: How long to become execution-hardened?**  
A: < 30 minutes with valid API credentials.

**Q: Is my data secure?**  
A: Script only reads balance, doesn't execute trades. API credentials never logged.

## Troubleshooting

### "Cannot import broker_manager"
```bash
# Ensure you're in the repository root
cd /path/to/Nija
python3 live_balance_audit.py
```

### "API Connection Failed"
- ✅ Check API key is correct (no typos)
- ✅ Check API secret is correct
- ✅ Verify API permissions on Kraken
- ✅ Test network connectivity to api.kraken.com

### "Invalid balance returned"
- ✅ Check API key has "Query Funds" permission
- ✅ Verify account exists on Kraken
- ✅ Check account is not restricted

## Files Created

1. **`live_balance_audit.py`** - The audit script (422 lines)
2. **`LIVE_BALANCE_AUDIT_RESULTS.md`** - Full audit results with analysis
3. **`LIVE_BALANCE_AUDIT_QUICKSTART.md`** - This quick start guide

## Next Steps After Execution-Hardened

1. ✅ Fund account with trading capital
2. ✅ Start with minimum trade sizes
3. ✅ Monitor first 24-48 hours closely
4. ✅ Verify profitability metrics
5. ✅ Scale gradually as confidence builds

---

**Remember:** Only execution-hardening matters in trading. Config-hardening is just theory.
