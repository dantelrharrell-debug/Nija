# Quick Monitoring Guide - Emergency Filter Relaxation V4

## 🎯 What to Watch

### In the Next 6 Hours (CRITICAL)

#### Success Indicators ✅
Look for these in the logs:
```
💡 Signals found: 1-8          (was: 0)
🔇 Smart filter: 5-15          (was: 18-24)  
🚫 No entry signal: 2-8        (was: 6-12)
📊 Market filter: 0-5          (normal)
```

#### Warning Signs ⚠️
```
💡 Signals found: 0            → Still blocked, check config
💡 Signals found: >15          → Too aggressive, watch quality
🔇 Smart filter: >20           → Volume filter still too strict
```

### First Trades (Within 24 Hours)

#### What to Check
1. **Entry Score**: Should be 50-70/100 average (was 75+)
2. **Win Rate**: Track after first 5 trades (expect 40-60%)
3. **Execution**: Check for slippage on low-volume markets
4. **P&L**: Small losses OK initially, watch for large losses

#### Red Flags 🚩
- Entry scores consistently < 40/100 → Quality too low
- Slippage > 1% on entries → Volume too low
- Large immediate losses > 2% → Stop loss not working
- Failed orders → Exchange rejecting trades

---

## 📊 Key Metrics to Track

### Signal Generation Rate
| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| Signals per cycle | 1-8 | 0 or >15 | Still 0 after 6hrs |
| Smart filter % | 20-40% | >60% | >80% |
| Markets passing | 15-20 | <10 | <5 |

### Trade Quality (After 20+ Trades)
| Metric | Good | Acceptable | Poor |
|--------|------|------------|------|
| Win Rate | >55% | 45-55% | <40% |
| Avg Win | >+1.5% | +1.0-1.5% | <+1.0% |
| Avg Loss | <-1.5% | -1.5 to -2% | >-2% |

---

## 🚨 When to Rollback

### Immediate Rollback (Stop Trading)
- Win rate < 35% after 30 trades
- Average loss > -3% per trade
- Critical errors or system failures
- Exchange blocking trades

### Partial Rollback (Tighten Filters)
- Win rate 35-40% after 30 trades
- Entry scores consistently < 40/100
- Excessive slippage (>1% average)

### Rollback Commands
```python
# In bot/nija_apex_strategy_v71.py, revert to Third Relaxation:
self.min_adx = 8                      # was 6
self.volume_threshold = 0.1           # was 0.05
self.volume_min_threshold = 0.005     # was 0.001
self.min_trend_confirmation = 2       # was 1
self.candle_exclusion_seconds = 1     # was 0

# In bot/nija_apex_strategy_v71.py:
MIN_CONFIDENCE = 0.75                 # was 0.50

# In bot/enhanced_entry_scoring.py:
self.min_score_threshold = 75         # was 50
```

---

## 📈 Fine-Tuning Based on Results

### If: Too Many Low-Quality Signals
**Action**: Increase MIN_CONFIDENCE to 0.60 (from 0.50)
```python
MIN_CONFIDENCE = 0.60  # Increase quality slightly
```

### If: Still No Signals After 12 Hours
**Action**: Further reduce volume_min_threshold
```python
self.volume_min_threshold = 0.0005  # Allow ANY volume
```

### If: High Slippage on Entries
**Action**: Increase volume_min_threshold slightly
```python
self.volume_min_threshold = 0.002  # Require more volume
```

### If: Too Many False Breakouts
**Action**: Increase min_adx slightly
```python
self.min_adx = 7  # Require slightly stronger trends
```

---

## 📝 Log Commands for Monitoring

### Check Recent Signal Generation
```bash
tail -100 /path/to/logs | grep "Signals found"
tail -100 /path/to/logs | grep "Smart filter"
tail -100 /path/to/logs | grep "No entry signal"
```

### Check Recent Trades
```bash
tail -100 /path/to/logs | grep "TRADE EXECUTED"
tail -100 /path/to/logs | grep "Entry score"
tail -100 /path/to/logs | grep "Confidence"
```

### Check Win/Loss
```bash
tail -500 /path/to/logs | grep "PROFIT\|LOSS"
```

---

## ⏱️ Timeline Expectations

### Hour 1-2
- First signals should appear
- May see 1-3 trades executed
- Entry scores: 50-65/100 typical

### Hour 2-6
- 3-8 signals per cycle
- 5-15 trades executed total
- Can start calculating initial win rate

### Hour 6-24
- Pattern should stabilize
- 20+ trades for meaningful statistics
- Can assess if filters need adjustment

### Day 2-7
- Collect 50+ trades
- Fine-tune based on data
- Optimize for best balance of quantity/quality

---

## 🎯 Success Criteria

### Short-Term (24 hours)
✅ Signals generating (>0 per cycle)  
✅ Trades executing (>10 in 24hrs)  
✅ No critical errors  
✅ Balance stable or growing

### Medium-Term (1 week)
✅ Win rate >40%  
✅ Net P&L positive or break-even  
✅ Filter settings stabilized  
✅ No further relaxations needed

### Long-Term (1 month)
✅ Win rate >50%  
✅ Consistent profitability  
✅ Balance growing  
✅ System operating smoothly

---

## 🔧 Contact/Escalation

If any CRITICAL issues:
1. Stop the bot immediately
2. Review logs for errors
3. Check for system/exchange issues
4. Consider rollback to Third Relaxation
5. Document issue for analysis

---

**Last Updated**: January 29, 2026  
**Status**: DEPLOYED - Active Monitoring Phase  
**Next Review**: After 6 hours or 10+ trades
