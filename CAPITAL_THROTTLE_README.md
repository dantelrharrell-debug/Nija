# Automated Capital Throttle - README

## What Is This?

The Automated Capital Throttle is NIJA's disciplined capital scaling system. It ensures the bot grows capital safely by:

1. **Progressive Gates** - Unlock higher position sizes as you prove profitability
2. **Risk Modeling** - Continuous monitoring of account destruction probability
3. **Stress Testing** - Simulate 25% drawdown before major scaling
4. **Automatic Throttling** - Reduce position sizes when performance drops

## Quick Start

```python
from bot.automated_capital_throttle import AutomatedCapitalThrottle

# Initialize at bot startup
throttle = AutomatedCapitalThrottle(initial_capital=10000.0)

# In your trading loop
throttle.update_capital(current_balance)
max_position_pct = throttle.get_max_position_size()  # Respects throttling
throttle.record_trade(is_winner=True, profit_loss=150.0)
```

## How It Works

### 4 Capital Tiers

Your capital unlocks progressively higher position sizes:

```
$0-10k    → 2% max position | Must maintain 50% WR, 1.2 PF
$10k-25k  → 3% max position | Must maintain 52% WR, 1.3 PF
$25k-50k  → 4% max position | Must maintain 53% WR, 1.4 PF + stress test
$50k+     → 5% max position | Must maintain 55% WR, 1.5 PF + stress test
```

**Can't skip tiers** - Must meet requirements to advance.

### Automatic Throttling

Position sizes automatically reduce to 25% when:
- Win rate drops below tier requirement
- Profit factor drops below tier requirement
- Drawdown exceeds tier maximum
- Risk-of-ruin probability exceeds 5%

### 25% Drawdown Stress Test

At $50k threshold, must pass stress test:
- Simulates 25% account drawdown
- Tests if strategy can recover 50% in 30 days
- Runs 1,000 Monte Carlo scenarios
- **Capital scaling locks until test passes**

### Parallel Risk-of-Ruin Modeling

Every 10 trades, system runs:
- 5,000 Monte Carlo simulations
- Calculates probability of account destruction
- Analyzes bull, bear, and high volatility scenarios
- Auto-throttles if risk too high

## Example Scenario

```
Starting capital: $10,000
Current tier: 1 ($0-10k)
Max position: 2%

Trade 50: Balance $15,000
✨ Tier upgraded to 2 ($10k-25k)
Max position: 3%

Trade 100: Balance $30,000
✨ Tier upgraded to 3 ($25k-50k)
Max position: 4%

Trade 150: Balance $52,000
⚠️ Approaching tier 4 ($50k+)
🔥 Running 25% drawdown stress test...

Stress test: ✅ PASSED (73% recovery probability)
✨ Tier upgraded to 4 ($50k+)
Max position: 5%
```

## Integration

### With risk_manager.py

```python
from bot.risk_manager import AdaptiveRiskManager
from bot.automated_capital_throttle import AutomatedCapitalThrottle

risk_mgr = AdaptiveRiskManager()
throttle = AutomatedCapitalThrottle(initial_capital=balance)

# Use the more conservative limit
throttle_limit = throttle.get_max_position_size()
risk_mgr_limit = risk_mgr.calculate_position_size(...)
final_position_pct = min(throttle_limit, risk_mgr_limit)
```

### With capital_scaling_engine.py

```python
from bot.capital_scaling_engine import CapitalScalingEngine
from bot.automated_capital_throttle import AutomatedCapitalThrottle

scaler = CapitalScalingEngine(base_capital=balance)
throttle = AutomatedCapitalThrottle(initial_capital=balance)

# Check throttle before scaling
if not throttle.state.is_throttled:
    scaled_capital = scaler.get_scaled_capital()
else:
    logger.warning(f"Throttled: {throttle.state.throttle_reason}")
```

## Status Monitoring

```python
status = throttle.get_status_report()

print(f"""
Capital: ${status['capital']['current']:,.2f}
Peak: ${status['capital']['peak']:,.2f}
Drawdown: {status['capital']['drawdown_pct']:.2f}%

Win Rate: {status['performance']['win_rate']:.2%}
Profit Factor: {status['performance']['profit_factor']:.2f}

Throttled: {status['throttle']['is_throttled']}
Max Position: {status['throttle']['max_position_size']*100:.2f}%

Ruin Risk: {status['risk']['ruin_probability']:.4%}
Stress Test: {'✅' if status['stress_test']['passed'] else '❌'}
""")
```

## Files

- **Core**: `bot/automated_capital_throttle.py`
- **Risk Engine**: `bot/risk_of_ruin_engine.py`
- **Tests**: `test_automated_capital_throttle.py`
- **Full Docs**: `AUTOMATED_CAPITAL_THROTTLE.md`
- **Quick Ref**: `CAPITAL_THROTTLE_QUICK_REF.md`
- **Summary**: `CAPITAL_THROTTLE_IMPLEMENTATION_SUMMARY.md`
- **Example**: `example_capital_throttle_integration.py`

## Benefits

✅ **Prevents Overtrading** - Locks position sizes to safe levels  
✅ **Enforces Discipline** - Can't bypass requirements  
✅ **Catches Deterioration** - Auto-throttles on poor performance  
✅ **Simulates Adversity** - Stress tests before major scaling  
✅ **Quantifies Risk** - Continuous ruin probability monitoring  
✅ **Preserves Capital** - Reduces risk during drawdowns  

## Common Questions

**Q: Can I override the throttle?**  
A: No. The throttle enforces discipline. If throttled, improve performance to required levels.

**Q: What if stress test keeps failing?**  
A: Improve win rate to 55%+, profit factor to 1.5+, and build 50+ trade history.

**Q: Does this replace risk_manager.py?**  
A: No. Use both. Throttle provides capital-level limits, risk_manager provides trade-level sizing.

**Q: Will this slow down my bot?**  
A: No. Position checks take <1ms. Risk analysis runs in background every 10 trades.

**Q: What if I restart the bot?**  
A: State persists to `data/capital_throttle_state.json`. All history preserved.

## Support

- 📖 Full documentation: `AUTOMATED_CAPITAL_THROTTLE.md`
- 📋 Quick reference: `CAPITAL_THROTTLE_QUICK_REF.md`
- 💻 Integration example: `example_capital_throttle_integration.py`
- 🧪 Test suite: `test_automated_capital_throttle.py`

## Status

✅ **Production Ready**  
✅ **Fully Tested**  
✅ **Comprehensively Documented**  
✅ **Ready for Integration**

---

**That sequence keeps NIJA disciplined.** ✨
