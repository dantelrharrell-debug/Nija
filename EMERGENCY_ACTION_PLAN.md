# 🚨 EMERGENCY ACTION PLAN - Stop NIJA Bleeding

**Date:** December 25, 2025  
**Status:** CRITICAL - Bot losing money  
**Current Positions:** 16 (8 over limit)

---

## IMMEDIATE ACTIONS (Do Now)

### ✅ Step 1: Entries Already Blocked
- File exists: `STOP_ALL_ENTRIES.conf`
- Bot will NOT open new positions
- Bot can still EXIT positions

### 🔥 Step 2: Reduce Positions to 8 (URGENT)

Run the position cap enforcer:

```bash
python3 emergency_fix.py
```

This will:
- Sell smallest 8 positions (lowest capital impact)
- Reduce position count from 16 → 8
- Keep STOP_ALL_ENTRIES.conf in place

**Expected result:** Position count = 8 within 5-10 minutes

---

## ROOT CAUSE & FIXES

### 🔴 Problem 1: Entry Filters TOO LOOSE

**Current Issue:**
- Bot only requires 3 out of 5 market filters to pass (60% confidence)
- Bot only requires 4 out of 5 entry signals (80% confidence)
- ADX minimum = 20 (too low, allows weak trends)
- Volume threshold = 30% (too low, allows low-liquidity trades)
- Pullback tolerance = 0.5% (too wide)
- RSI range = 30-70 (too wide, catches false signals)

**Result:** Bot buys ANYTHING that shows a hint of movement

**Fix Required:**
```python
# File: bot/nija_apex_strategy_v71.py

# Line 60: Increase ADX minimum
self.min_adx = self.config.get('min_adx', 25)  # Was: 20

# Line 61: Increase volume requirement
self.volume_threshold = self.config.get('volume_threshold', 0.5)  # Was: 0.3

# Lines 140-142: Require ALL market filters
if uptrend_score >= 5:  # Was: >= 3 (now require ALL 5 filters)
    return True, 'uptrend', ...

# Line 182: Tighten pullback tolerance
near_ema21 = abs(current_price - ema21) / ema21 < 0.003  # Was: 0.005

# Line 184: Tighten RSI range
conditions['rsi_pullback'] = 35 < rsi < 65 and rsi > rsi_prev  # Was: 30 < rsi < 70

# Line 222: Require ALL entry conditions
signal = score >= 5  # Was: >= 4 (now require ALL 5 conditions)
```

### 🔴 Problem 2: Exit Logic INSUFFICIENT

**Current Issue:**
- Only exits if market filter fails OR down 5%
- NO profit-taking levels
- NO time-based exits
- NO RSI overbought exits
- Stop loss at -5% is too wide

**Result:** Bot holds losing positions too long, doesn't lock in profits

**Fix Required:**
```python
# File: bot/trading_strategy.py

# Add after line 280 (in position management section):

# NEW: Profit-taking exits
entry_price = position.get('entry_price', current_price)
pnl_pct = ((current_price - entry_price) / entry_price) * 100

if pnl_pct >= 10.0:
    logger.info(f"   💰 TAKE PROFIT +10%: Selling {symbol}")
    positions_to_exit.append({'symbol': symbol, 'quantity': quantity, 
                             'reason': f'Take profit +10% (${pnl_pct:.2f}%)'})
elif pnl_pct >= 5.0:
    logger.info(f"   💰 TAKE PROFIT +5%: Selling {symbol}")
    positions_to_exit.append({'symbol': symbol, 'quantity': quantity,
                             'reason': f'Take profit +5% (${pnl_pct:.2f}%)'})
elif pnl_pct >= 3.0:
    logger.info(f"   💰 TAKE PROFIT +3%: Selling {symbol}")
    positions_to_exit.append({'symbol': symbol, 'quantity': quantity,
                             'reason': f'Take profit +3% (${pnl_pct:.2f}%)'})

# NEW: Time-based exit (24 hours)
from datetime import datetime, timedelta
position_age = datetime.now() - position.get('entry_time', datetime.now())
if position_age > timedelta(hours=24) and pnl_pct < 0:
    logger.info(f"   ⏰ TIME EXIT: {symbol} held 24h with loss")
    positions_to_exit.append({'symbol': symbol, 'quantity': quantity,
                             'reason': '24h hold time limit (losing position)'})

# NEW: RSI overbought exit
rsi = indicators.get('rsi', pd.Series()).iloc[-1]
if rsi > 70 and pnl_pct > 0:
    logger.info(f"   📈 RSI OVERBOUGHT: {symbol} (RSI={rsi:.1f})")
    positions_to_exit.append({'symbol': symbol, 'quantity': quantity,
                             'reason': f'RSI overbought ({rsi:.1f})'})

# MODIFY: Tighten stop loss to -3%
stop_loss_pct = 0.03  # Was: 0.05 (change line 301)
```

---

## IMPLEMENTATION STEPS

### Phase 1: Emergency Stop (Now)
```bash
# 1. Verify STOP_ALL_ENTRIES.conf exists
ls -la STOP_ALL_ENTRIES.conf

# 2. Run position cap enforcer
python3 emergency_fix.py

# 3. Verify position count reduced
python3 check_current_positions.py
```

### Phase 2: Apply Code Fixes (Today)
```bash
# 1. Review analysis
cat CRITICAL_ISSUES_ANALYSIS.md

# 2. Apply fixes to nija_apex_strategy_v71.py
#    (see code changes above)

# 3. Apply fixes to trading_strategy.py
#    (see code changes above)

# 4. Test syntax
python3 -m py_compile bot/nija_apex_strategy_v71.py
python3 -m py_compile bot/trading_strategy.py

# 5. Commit changes
git add bot/nija_apex_strategy_v71.py bot/trading_strategy.py
git commit -m "Fix: Tighten entry filters and add profit-taking exits"
git push origin main
```

### Phase 3: Controlled Restart (Tomorrow)
```bash
# 1. Monitor current positions exiting
#    Wait until <= 4 positions remain

# 2. Deploy updated code to Railway/Render
#    (automatic on git push)

# 3. Monitor logs for 6 hours with STOP_ALL_ENTRIES.conf

# 4. If stable, remove stop file
rm STOP_ALL_ENTRIES.conf

# 5. Bot will resume with strict filters
#    Should only take 1-2 high-quality trades per day
```

---

## SUCCESS CRITERIA

### Immediate (6 hours):
- ✅ Position count ≤ 8
- ✅ No new entries (STOP_ALL_ENTRIES.conf)
- ✅ Existing positions exiting properly

### Short-term (24 hours):
- ✅ At least 2-4 positions closed
- ✅ Remaining positions managed with tight stops
- ✅ No further bleeding

### Medium-term (3 days):
- ✅ Code fixes deployed and tested
- ✅ STOP_ALL_ENTRIES.conf removed
- ✅ Bot taking only 1-2 high-quality trades/day
- ✅ Win rate > 55%
- ✅ No position holds > 24 hours without profit

---

## MONITORING

Watch these metrics:
1. **Position count** - Must stay ≤ 8
2. **Entry quality** - Should see FAR fewer entries (maybe 1-2/day)
3. **Win rate** - Target >55% (currently much lower)
4. **Average hold time** - Target <12 hours
5. **Profit factor** - Total wins / Total losses > 1.5

---

## FILES CREATED

1. `CRITICAL_ISSUES_ANALYSIS.md` - Detailed problem analysis
2. `emergency_fix.py` - Position cap enforcement script
3. `apply_comprehensive_fixes.py` - Fix validation script
4. `EMERGENCY_ACTION_PLAN.md` - This file

---

## CONTACT / ESCALATION

If issues persist after implementing fixes:
1. Check Railway/Render deployment logs
2. Verify environment variables (API keys)
3. Test Coinbase API connectivity
4. Review `nija.log` for errors

**Remember:** Quality over quantity. Better to take 1 winning trade than 10 losing trades.

