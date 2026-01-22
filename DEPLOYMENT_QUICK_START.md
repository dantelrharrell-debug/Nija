# Quick Deployment Guide

## What Changed

This PR implements two critical changes to the NIJA trading bot:

1. **Master account is now ALWAYS BALLER tier** (regardless of balance)
2. **Maximum trade size reduced to 15%** (down from 20%)

## Deployment Steps

### Step 1: Update Your `.env` File

Add or update this line in your `.env` file:

```bash
MASTER_ACCOUNT_TIER=BALLER
```

This ensures the master account uses BALLER tier parameters.

### Step 2: Restart the Bot

After updating `.env`, restart the NIJA bot to apply changes.

### Step 3: Verify Configuration

The bot will log the tier assignment on startup. Look for:

```
🎯 Master account: Using BALLER tier (balance: $62.49)
   Note: Master account always uses BALLER tier regardless of balance
```

## What to Expect

### For Master Account with $62.49 Balance

**Before:**
- Tier: STARTER (auto-detected from balance)
- Max risk: 10-15% per tier
- Max trade size: $12.50 (20% of balance)
- Max positions: 1

**After:**
- Tier: BALLER (forced)
- Max risk: 1-2% per tier guidelines
- Max trade size: $9.37 (15% of balance - global cap)
- Max positions: 8

**Key Benefits:**
- ✅ Better risk management (1-2% vs 10-15%)
- ✅ More position capacity (8 vs 1)
- ✅ Safer max trade size (15% vs 20%)
- ✅ Professional-grade controls

## Important Notes

### About the 15% Cap

Even though BALLER tier normally allows $100-$1,000 trades, the **15% global cap still applies**:

- Balance: $62.49
- 15% cap: $9.37
- BALLER tier minimum: $100

**Result:** Trades will be limited to $9.37 (the 15% cap), not the tier minimum.

This is by design for safety - the 15% cap protects all accounts from oversized positions.

### About Trade Execution

With a $62.49 balance:
- Maximum possible trade: $9.37 (15%)
- This is BELOW the BALLER tier minimum ($100)
- Trades will execute at the 15% cap amount
- You get BALLER tier risk parameters (1-2%)
- You get the safety of the 15% cap

## Testing

Run the test suite to verify everything works:

```bash
python3 test_tier_and_risk_changes.py
```

Expected output:
```
✅ Tier Override & Master BALLER: PASS
✅ Risk Manager Max Position: PASS
✅ Trade Size Calculations: PASS
✅ Master Account BALLER Benefits: PASS

Total: 4/4 tests passed
```

## Troubleshooting

### Issue: Trades not executing

**Check:**
1. Verify `MASTER_ACCOUNT_TIER=BALLER` is in `.env`
2. Restart the bot
3. Check logs for tier assignment

### Issue: Tier shows as STARTER instead of BALLER

**Solution:**
1. Add `MASTER_ACCOUNT_TIER=BALLER` to `.env`
2. Restart the bot
3. Verify with logs

### Issue: Trade size larger than 15%

**This should not happen** - if you see this, it's a bug. The 15% cap should enforce globally.

## Rollback Plan

If you need to rollback to previous behavior:

1. Remove `MASTER_ACCOUNT_TIER=BALLER` from `.env`
2. Restart the bot
3. Master will use auto-detected tier (STARTER for $62.49)

**Note:** The 15% max trade size will remain (it's a permanent safety improvement).

## Questions?

See `TIER_AND_RISK_CONFIG_GUIDE.md` for complete documentation on:
- All tier levels and parameters
- Configuration options
- Examples for different account sizes
- Troubleshooting

## Summary

✅ Master account: BALLER tier (forced)
✅ Max trade size: 15% (global cap)
✅ Better risk management for master
✅ All tests passing
✅ Security scan clean
✅ Ready to deploy
