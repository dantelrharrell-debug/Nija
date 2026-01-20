# 🚨 URGENT: SELL LOSING POSITIONS NOW

**Problem**: Coinbase positions held for 26 days, losing money  
**Solution**: Run one of the emergency scripts below

---

## Step 0: Check Current Positions (Optional)

First, see what you actually have:
```bash
python3 check_coinbase_positions.py
```

This will show:
- Current positions in Coinbase
- Their P&L status (winning/losing)
- Recommended action

---

## Quick Start (Recommended)

### Option 1: Sell ONLY Losing Positions (Recommended)
```bash
python3 sell_losing_positions_now.py
```

**What it does:**
- ✅ Sells positions with P&L < 0% (losing money)
- ✅ KEEPS positions with P&L >= 0% (profitable or breakeven)
- ✅ No confirmation required - runs immediately
- ✅ Safe and targeted

**Use this if:** You want to cut losses but keep winners

---

### Option 2: Sell ALL Positions (Nuclear Option)
```bash
python3 emergency_sell_all_positions.py
```

**What it does:**
- ⚠️  Sells ALL positions (winning and losing)
- ⚠️  Requires typing 'YES' to confirm
- ⚠️  Complete liquidation

**Use this if:** You want to close everything and start fresh

---

## What Happens After

Both scripts will:
1. Connect to Coinbase
2. Fetch current positions
3. Force-sell selected positions (market orders)
4. Report results
5. Clean up stale tracking files (full liquidation only)

**Expected time**: 30-60 seconds

---

## Troubleshooting

### Script says "No positions found"
- ✅ Good! Positions already sold or account already clear
- Action: Nothing needed

### Script says "Failed to connect"
- ❌ Problem with Coinbase API credentials
- Action: Check `.env` file has valid credentials

### Some positions failed to sell
- ⚠️  Possible issues: position already sold, minimum size not met, rate limiting
- Action: Check Coinbase UI manually: https://www.coinbase.com/advanced-trade/spot

---

## After Running Script

1. **Verify positions sold** in Coinbase UI
2. **Check USD balance** (should reflect sales)
3. **Restart bot** if needed: `bash start.sh`
4. **Monitor new trades** to ensure exit logic works

---

## For More Details

See: `EMERGENCY_LIQUIDATION_JAN_20_2026.md`

---

**Created**: January 20, 2026  
**Branch**: copilot/sell-held-stocks-now
