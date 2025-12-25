# 🚨 Emergency Position Liquidation Guide

## Problem
You have **12 active positions** but your risk limit is **3 max positions** (set in `bot/apex_config.py`). This violates your risk management rules.

## Solution
Run the emergency liquidation script **ON RAILWAY** to close 9 positions and keep only the top 3 performers.

---

## Step 1: Access Railway Shell

1. Go to your Railway dashboard: https://railway.app
2. Click on your **NIJA** project
3. Click on the **Shell** tab (or use Railway CLI)

---

## Step 2: Run Liquidation Script

In the Railway shell, run:

```bash
python3 CLOSE_EXCESS_POSITIONS.py
```

---

## What It Does

### Positions to KEEP (Top 3 Performers):
- ✅ **APT-USD**: +2.80% P&L (best performer)
- ✅ **FET-USD**: +2.15% P&L (second best)
- ✅ **VET-USD**: +1.94% P&L (third best)

### Positions to CLOSE (10 positions):
- 🗑️ **ARB-USD**: +0.86%
- 🗑️ **SOL-USD**: +0.95%
- 🗑️ **UNI-USD**: +1.26%
- 🗑️ **ETH-USD**: +0.51%
- 🗑️ **ICP-USD**: +0.34%
- 🗑️ **HBAR-USD**: +0.23%
- 🗑️ **DOT-USD**: -0.23%
- 🗑️ **BTC-USD**: -0.00%
- 🗑️ **AAVE-USD**: -0.82%
- 🗑️ **LTC-USD**: (dust)
- 🗑️ **RENDER-USD**: (dust)

---

## Expected Output

```
🔥 EMERGENCY: CLOSING EXCESS POSITIONS TO COMPLY WITH 3-POSITION LIMIT
======================================================================
📊 Loaded 12 positions

📌 KEEPING: APT-USD, FET-USD, VET-USD
🗑️  CLOSING: 9 positions
======================================================================

✅ Broker connected

🔄 Closing ARB-USD...
   SELL 31.43693219 units
   ✅ CLOSED @ $0.1873

🔄 Closing SOL-USD...
   SELL 0.04729361 units
   ✅ CLOSED @ $122.70

... (7 more closures)

======================================================================
📊 LIQUIDATION SUMMARY
======================================================================
  Started with: 12 positions
  Successfully closed: 9 positions
  Failed to close: 0 positions
  Remaining: 3 positions
  Target: 3 positions
======================================================================

✅ SUCCESS: Position limit achieved!
✅ Remaining positions: APT-USD, FET-USD, VET-USD
✅ NIJA is now compliant with 3-position limit!
```

---

## After Running

1. **Check Railway logs** - NIJA should show "📊 Managing 3 open position(s)..." in next cycle
2. **Verify compliance** - Max position limit respected
3. **Bot continues** - Will still auto-exit remaining 3 positions when SL/TP hit
4. **Emergency stop** - Still active (no new entries until you delete `TRADING_EMERGENCY_STOP.conf`)

---

## Troubleshooting

### If script fails with "No module named broker_manager"
```bash
cd /usr/src/app && python3 CLOSE_EXCESS_POSITIONS.py
```

### If API errors occur
- Check Railway logs for Coinbase API issues
- Verify API keys are set correctly
- Try again in 30 seconds (rate limiting)

### If some positions fail to close
- Note which ones failed
- Manually close them on Coinbase.com
- Or wait for bot to auto-close them at SL/TP

---

## Manual Alternative

If script doesn't work, manually close positions on Coinbase:

1. Go to https://www.coinbase.com/advanced-trade
2. Click each position you want to close
3. Click "Sell" → "Market Order" → "Sell All"
4. Repeat for 9 positions (keep APT, FET, VET)

---

## After Compliance Achieved

Your bot will then be:
- ✅ **Managing 3 positions** (APT, FET, VET)
- ✅ **Compliant with risk limits** (max_positions: 3)
- ✅ **Auto-exiting at SL/TP** every 2.5 minutes
- ✅ **Emergency stop active** (no new entries)
- ✅ **Account bleeding controlled** (positions can only exit)

---

## Next Steps

Once you're down to 3 positions and bleeding is fully stopped:

1. Monitor the 3 remaining positions
2. Wait for them to hit +5% TP or -3% SL
3. When all 3 close, you'll have ~$70-75 cash (if all hit TP)
4. Delete `TRADING_EMERGENCY_STOP.conf` to allow new entries
5. Bot will resume normal trading with 3-position limit enforced

---

## Questions?

The script is safe - it only sells positions you already own. No new buys, no shorting, just closing long positions via market sells.
