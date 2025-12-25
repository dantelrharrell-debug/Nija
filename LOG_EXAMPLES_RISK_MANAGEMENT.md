# 📊 Expected Log Output When Risk Management Features Are Working

This document shows you **exactly what logs to expect** when NIJA is using stop loss, trailing stop, take profit, and trailing take profit features.

---

## 🔍 Position Entry Log

```
🔄 Executing BUY for BTC-USD
   Price: $42500.00
   Position size: $25.50 (capped at $100 max)
   Reason: Long score: 5/5 - Strong uptrend with RSI confluence

✅ Trade executed: BTC-USD BUY
   Entry: $42500.00
   Stop Loss: $41650.00 (-2%)          ← STOP LOSS CONFIGURED
   Take Profit: $44625.00 (+5%)        ← TAKE PROFIT CONFIGURED
```

---

## 📈 Position Monitoring (Every 15 Seconds)

### Example 1: Price Rising (Trailing Stop Activates)

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $42850.00 | P&L: +0.82% (+$20.95)
   📈 Trailing stop updated: $42220.00 (locks in 0.65% profit)
```

What this means:
- Price moved up $350 ($42500 → $42850)
- Trailing stop moved from $41650 → $42220 (locks in $0.65 profit)
- If price drops below $42220, it will exit with ~+0.65% profit

### Example 2: Price Continues Rising

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $43600.00 | P&L: +2.58% (+$65.70)
   📈 Trailing stop updated: $43020.00 (locks in 1.22% profit)
```

What this means:
- Price moved up $1,100 ($42500 → $43600)
- Trailing stop moved to $43020 (locks in $1.22 profit)
- Only risk $0.36 to make $0.58 more

### Example 3: Stepping Take Profit (Favorable Move)

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $43895.00 | P&L: +3.22% (+$82.06)
   🎯 TP stepped up to $45900.00 after move ≥ 3.0%
   📈 Trailing stop updated: $43245.00 (locks in 1.75% profit)
```

What this means:
- Price moved +3.22% (> 3% trigger)
- **Take profit stepped up from $44625 → $45900** (capturing larger move)
- Trailing stop now at $43245 (locks $0.75 profit)
- Position can now make up to +8% instead of just +5%

---

## 🛑 Position Exit Scenarios

### Scenario A: Take Profit Hit

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $44750.00 | P&L: +5.29% (+$134.88)

🔄 Closing BTC-USD position: Take profit hit @ $44750.00
   Exit price: $44750.00 | P&L: +5.29% (+$134.88)
   
✅ Position closed with PROFIT: +$134.88
```

**When this happens**: Price reaches your take profit target (5% base or 8% if stepped)

---

### Scenario B: Trailing Stop Hit (Protecting Profits)

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $42100.00 | P&L: -0.94% (-$23.94)

🔄 Closing BTC-USD position: Trailing stop hit @ $42220.00
   Exit price: $42100.00 | P&L: +0.65% (+$16.58)
   
✅ Position closed with PROFIT: +$16.58
```

**What happened**:
1. Price went up to $43600 (+2.58%)
2. Trailing stop locked in at $43020
3. Price retraced back down to $42100
4. Hit the trailing stop → **Auto-exited with profit still locked**

This is the **profit protection in action**!

---

### Scenario C: Stop Loss Hit (Cutting Losses)

```
📊 Managing 1 open position(s)...
   BTC-USD: BUY @ $42500.00 | Current: $41580.00 | P&L: -2.16% (-$55.08)

🔄 Closing BTC-USD position: Stop loss hit @ $41650.00
   Exit price: $41580.00 | P&L: -2.00% (-$51.00)
   
❌ Position closed with LOSS: -$51.00
```

**When this happens**: Price drops 2% below entry → **Auto-exit to limit losses**

---

### Scenario D: Multiple Positions Being Managed

```
📊 Managing 3 open position(s)...
   
   BTC-USD: BUY @ $42500.00 | Current: $43200.00 | P&L: +1.65% (+$41.88)
   📈 Trailing stop updated: $42770.00 (locks in 0.64% profit)
   
   ETH-USD: BUY @ $2280.00 | Current: $2412.00 | P&L: +5.78% (+$33.70)
   🎯 TP stepped up to $2462.40 after move ≥ 3.0%
   📈 Trailing stop updated: $2349.60 (locks in 3.05% profit)
   
   SOL-USD: BUY @ $198.50 | Current: $195.20 | P&L: -1.66% (-$8.32)

🔄 Closing ETH-USD position: Take profit hit @ $2400.00
   Exit price: $2412.00 | P&L: +5.78% (+$33.70)

✅ Position closed with PROFIT: +$33.70
```

---

## 🔎 Finding These Logs

### Search for specific feature:

```bash
# See all trailing stop updates
tail -f nija.log | grep "Trailing stop updated"

# See all TP steps
tail -f nija.log | grep "TP stepped"

# See all exits
tail -f nija.log | grep "Closing"

# See stop loss hits
tail -f nija.log | grep "Stop loss hit"

# See take profit hits
tail -f nija.log | grep "Take profit hit"

# See profit/loss summary
tail -f nija.log | grep "Position closed with"
```

### View full position management cycle:

```bash
tail -f nija.log | grep -E "(Managing|Trailing|TP stepped|Closing|Position closed)"
```

---

## ✅ Checklist: Verify All Features Working

After running the bot for a few hours, verify:

- [ ] **Stop Loss**: Saw at least one position exit with -2%?
- [ ] **Trailing Stop**: Saw "Trailing stop updated" messages?
- [ ] **Take Profit**: Saw "Take profit hit" exit message?
- [ ] **Stepped TP**: Saw "TP stepped up" message on profitable trade?
- [ ] **Profit Locking**: Positions closing with profit even after retraces?
- [ ] **Loss Control**: Loss positions limited to ~2% or less?

If you see **ALL** these in your logs, all features are working! ✅

---

## 🚨 If You DON'T See These Logs

### Possible reasons:

1. **Bot just started** - Need time for positions to develop
2. **No positions open** - Need trades first (check if balance sufficient)
3. **Market not moving** - Prices flat, nothing triggers exits
4. **Position sizes too small** - Rounding effects on tiny orders
5. **Position closed too fast** - Quick TP hit before logging shows

### To troubleshoot:

1. Check balance: `grep "Current Balance" nija.log`
2. Check if positions opening: `grep "Trade executed" nija.log`
3. Check for errors: `grep "ERROR" nija.log`
4. Verify config: `grep "self.stop_loss\|self.trailing\|self.take_profit" bot/trading_strategy.py`

---

## 📝 Full Sample Trading Cycle

Here's what a **complete trade from entry to exit** looks like:

```
[2025-12-20 10:15:32] 🔄 Executing BUY for ETH-USD
[2025-12-20 10:15:32]    Price: $2280.00
[2025-12-20 10:15:32]    Position size: $25.00
[2025-12-20 10:15:33] ✅ Trade executed: ETH-USD BUY
[2025-12-20 10:15:33]    Entry: $2280.00
[2025-12-20 10:15:33]    Stop Loss: $2234.40 (-2%)
[2025-12-20 10:15:33]    Take Profit: $2394.00 (+5%)

[2025-12-20 10:30:45] 📊 Managing 2 open position(s)...
[2025-12-20 10:30:45]    ETH-USD: BUY @ $2280.00 | Current: $2315.00 | P&L: +1.54% (+$8.59)
[2025-12-20 10:30:45]    📈 Trailing stop updated: $2288.00 (locks in 0.35% profit)

[2025-12-20 10:45:18] 📊 Managing 2 open position(s)...
[2025-12-20 10:45:18]    ETH-USD: BUY @ $2280.00 | Current: $2350.00 | P&L: +3.07% (+$17.12)
[2025-12-20 10:45:18]    🎯 TP stepped up to $2462.40 after move ≥ 3.0%
[2025-12-20 10:45:18]    📈 Trailing stop updated: $2329.20 (locks in 2.15% profit)

[2025-12-20 11:00:22] 📊 Managing 2 open position(s)...
[2025-12-20 11:00:22]    ETH-USD: BUY @ $2280.00 | Current: $2400.00 | P&L: +5.26% (+$29.36)
[2025-12-20 11:00:22] 🔄 Closing ETH-USD position: Take profit hit @ $2394.00
[2025-12-20 11:00:22]    Exit price: $2400.00 | P&L: +5.26% (+$29.36)
[2025-12-20 11:00:23] ✅ Position closed with PROFIT: +$29.36
```

---

## 💡 Key Takeaway

**You should see this pattern regularly**:

1. Entry log with SL/TP configured
2. Multiple "Trailing stop updated" messages as price rises
3. Optional "TP stepped up" message if move >= 3%
4. Exit message (TP hit, SL hit, or trailing stop hit)
5. "Position closed with PROFIT/LOSS" message

**If you see this pattern, everything is working!** ✅
