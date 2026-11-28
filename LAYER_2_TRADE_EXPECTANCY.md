# Layer 2: Trade Expectancy Improvement - Complete Guide

## Overview

Layer 2 transforms NIJA from "not bleeding" (Layer 1) to "actually profitable" by improving the math on every trade and managing exits intelligently.

**Philosophy**: Profitability comes from expectancy, not accuracy.

---

## Components

### 1. Trade Quality Gate

**Location**: `bot/trade_quality_gate.py`

**Purpose**: Kill mathematically stupid trades before execution

**What It Does**:
- Computes reward-to-risk ratio (must be ≥ 1.5)
- Measures momentum strength (volume + range expansion)
- Scores stop placement quality (0-100 based on ATR)

**Integration**: Wraps apex strategy output, filters before execution

**Example**:
```
🚫 Quality Gate REJECTED: Poor R:R 1.2 < 1.5
✅ Quality Gate APPROVED: R:R=2.3
   Momentum: Vol:1.45x Range:1.28x
   Stop: Stop well-placed (1.3x ATR)
```

---

### 2. Profit Protection System

**Location**: `bot/profit_protection_system.py`

**Purpose**: Lock profits and prevent reversals

**Three Protection Layers**:

#### Layer A: Partial Exits
- Exit 40% at +1% profit (~1R typical)
- Exit 30% more at +2% profit (~2R)
- **Why**: Lock gains before reversal, raise win rate

#### Layer B: Break-Even Stop
- Triggers at +0.5% profit
- Moves stop to entry + 0.15% (covers fees)
- **Why**: Convert potential losers to break-even

#### Layer C: Stagnation Exit
- Exits if <0.3% movement in 30 minutes
- **Why**: Cut slow bleeders, free capital

**Example Scenario**:

| Event | Action | Reasoning |
|-------|--------|-----------|
| Entry @ $100 | Full position | - |
| Price → $101 (+1%) | Exit 40% | Lock $0.40/share before reversal |
| Price → $102 (+2%) | Exit 30% more | Lock $0.60/share on remaining |
| Price → $100.50 (+0.5%) | Move stop to $100.15 | Protect break-even + fees |
| No movement for 30min | Exit remaining | Cut stagnant position |

---

## Integration Points

### In Trading Strategy

```python
# Quality Gate (after analyze_market)
if self.quality_gate:
    analysis = self.quality_gate.filter_strategy_signal(analysis, df)

# Profit Protection (in position management)
if self.profit_protection:
    # Check partial exits
    exit_action = self.profit_protection.check_partial_exit(...)

    # Check break-even move
    new_stop = self.profit_protection.check_breakeven_move(...)

    # Check stagnation
    stagnation_reason = self.profit_protection.check_stagnation_exit(...)
```

---

## Configuration

### Trade Quality Gate

```python
quality_gate = TradeQualityGate(
    min_reward_risk=1.5,      # Minimum R:R (1.5 or 2.0)
    require_momentum=True     # Require volume/range expansion
)
```

### Profit Protection

```python
protection = ProfitProtectionSystem(config={
    'exit_schedule': {
        0.01: 0.40,  # Exit 40% at +1%
        0.02: 0.30,  # Exit 30% at +2%
    },
    'breakeven_trigger': 0.005,         # 0.5% profit
    'fee_buffer': 0.0015,               # 0.15% fee coverage
    'stagnation_minutes': 30,           # 30min timeout
    'stagnation_min_movement': 0.003,   # 0.3% minimum
})
```

---

## Why This Improves Profitability

### Problem: Standard Trading Bot Behavior

```
Trade Entry → Goes to +0.5R → Reverses → Exits at -1R → Net Loss
```

**Result**: 50% win rate but still unprofitable due to asymmetric losses

### Solution: Layer 2 Enhancements

**Quality Gate**:
```
Before Entry: R:R check
If 1.2:1 → REJECT (mathematically stupid)
If 2.0:1 → APPROVE (worth the risk)
```

**Profit Protection**:
```
Entry @ $100 → Price $101 → Exit 40%
Locked: $40 profit on 40% of position
Remaining 60% has break-even stop @ $100.15
```

**If reversal happens**:
- Old way: Full position exits at loss
- New way: 40% already profitable, 60% exits at break-even
- **Result**: Net profit instead of loss

---

## Expected Impact

### Metrics Improvement

| Metric | Before | After Layer 2 | Improvement |
|--------|--------|---------------|-------------|
| Win Rate | 45-50% | 55-65% | +10-15% |
| Avg Win | 1.5% | 1.3% | -0.2% (acceptable) |
| Avg Loss | -1.2% | -0.6% | -50% (huge) |
| Expectancy | -0.1% | +0.4% | Profitable! |
| Drawdowns | Frequent | Rare | Smoother curve |

### Psychological Benefits

1. **More Wins**: Partial exits create more "win" events
2. **Less Stress**: Break-even stops remove fear
3. **Better Compounding**: Smaller drawdowns → faster recovery

---

## Real-World Example

**Trade: BTC-USD Long**

```
Entry: $65,000
Stop: $64,350 (1% risk = $650)
Target: $66,300 (2% profit = $1,300)
R:R = 2.0 ✅

Timeline:
T+5min:  $65,325 (+0.5%)  → Break-even stop set @ $65,100
T+15min: $65,650 (+1.0%)  → Exit 40% (lock $260 profit)
T+30min: $66,300 (+2.0%)  → Exit 30% (lock $390 more profit)
T+45min: $65,800 (+1.2%)  → Stagnant, exit remaining 30%

Results:
- 40% exited @ +1%: +$260
- 30% exited @ +2%: +$390
- 30% exited @ +1.2%: +$234
- Total: +$884 profit vs full exit at +1.2% = +$780
- Bonus: Locked profits before potential reversal
```

---

## Testing

### Quality Gate Test

```bash
# Test R:R rejection
Entry: $100, Stop: $99, Target: $100.50
R:R = 0.5 → Should REJECT ❌

Entry: $100, Stop: $99, Target: $101.50
R:R = 1.5 → Should APPROVE ✅
```

### Profit Protection Test

```bash
# Register position
protection.register_position('BTC-USD', 65000, datetime.now(), 100)

# Check at +1%
exit_pct, reason = protection.check_partial_exit('BTC-USD', 65650, 'long')
# Should return: (0.40, "Partial exit 40% at +1.00% profit")

# Check break-even
new_stop, reason = protection.check_breakeven_move('BTC-USD', 65325, 64350, 'long')
# Should return: (65097.5, "Break-even stop @ $65097.50 (entry + fees)")
```

---

## Common Scenarios

### Scenario 1: Quick Winner
```
Entry → +1% in 10min → Exit 40% → Continues to +2% → Exit 30% → Win locked
```

### Scenario 2: Slow Grinder
```
Entry → +0.5% in 15min → Break-even set → Stagnates → Exit @ break-even after 30min
Old: Would hold hoping for move, often reverses to loss
New: Exit at break-even, no loss
```

### Scenario 3: False Breakout
```
Entry → +0.3% in 5min → Reverses → Hits stop
Old: Full loss
New: Same (not every loss is preventable, but we reduce them)
```

### Scenario 4: Big Winner
```
Entry → +1% → Exit 40% → +2% → Exit 30% → +4% → Exit 30% → Huge win captured
Old: Might hold too long and give back
New: Locked 70% of profits early, final 30% rides trend
```

---

## Maintenance

### Adjusting Thresholds

**If win rate too low** (< 50%):
- Lower R:R requirement (1.5 → 1.3)
- Disable momentum requirement temporarily
- Widen partial exit levels

**If missing big moves**:
- Reduce partial exit percentages (40% → 30%)
- Move first exit level higher (1% → 1.5%)
- Extend stagnation timeout (30min → 45min)

**If too many break-evens**:
- Raise break-even trigger (0.5% → 0.7%)
- Increase fee buffer (0.15% → 0.20%)

---

## Integration Checklist

### In `__init__`:
- [ ] Import ProfitProtectionSystem
- [ ] Initialize with config
- [ ] Set up position tracking

### In `run_cycle`:
- [ ] Register new positions on entry
- [ ] Check partial exits in position management
- [ ] Check break-even moves
- [ ] Check stagnation exits
- [ ] Unregister on full exit

### Logging:
- [ ] Log partial exit executions
- [ ] Log break-even stop moves
- [ ] Log stagnation exits
- [ ] Track metrics (total partials, BE saves, stagnation cuts)

---

## Metrics to Track

### Daily Summary:
```
Profit Protection Stats:
- Partial exits taken: 12
- Profits locked early: $234.56
- Break-even stops set: 8
- Losses prevented: $156.78
- Stagnation exits: 3
- Capital freed: $450.00
```

### Per-Trade:
```
BTC-USD Trade Summary:
- Entry: $65,000
- Partial exits: 2 (40% @ +1%, 30% @ +2%)
- Profits locked: $650
- Final exit: +1.5% on remaining 30%
- Total profit: $825
- vs Hold to end: $975 (difference: -$150 but safer)
```

---

## FAQ

**Q: Won't partial exits reduce total profit?**
A: Yes, on big winners. But they increase win rate and prevent giving back profits on reversals. Net result: Better expectancy.

**Q: What if I exit 40% and it goes to +10%?**
A: You still have 60% in the trade. The 40% locked profit before reversal risk. This is risk management, not profit maximization.

**Q: Should I always use these features?**
A: Yes for Layer 2 effectiveness. Disable only if you have evidence of negative impact over 100+ trades.

**Q: Can I customize the exit schedule?**
A: Absolutely. Test with your strategy. Some traders prefer 30/30/40 split, others 50/50.

**Q: What about time-based stops on winners?**
A: Winners are exempt from stagnation exits if they're above profit thresholds.

---

## See Also

- `bot/trade_quality_gate.py` - Implementation
- `bot/profit_protection_system.py` - Implementation  
- `bot/market_readiness_gate.py` - Layer 1 foundation
- `MARKET_READINESS_GATE.md` - Layer 1 documentation
