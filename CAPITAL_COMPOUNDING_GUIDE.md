# NIJA Capital Scaling & Compounding Engine - User Guide

## Overview

The **Capital Scaling & Compounding Engine** is a comprehensive capital management system that automatically grows your trading capital through intelligent profit reinvestment, drawdown protection, and milestone-based scaling.

## Features

### 💰 Profit Compounding Engine
Automatically reinvests profits to achieve exponential growth:
- **Profit Separation**: Tracks base capital vs. reinvested profits separately
- **Flexible Strategies**: Conservative (50% reinvest), Moderate (75%), Aggressive (90%), Full (100%)
- **CAGR Tracking**: Real-time Compound Annual Growth Rate calculations
- **Growth Projections**: Estimates future capital based on performance

### 🛡️ Drawdown Protection System
Preserves capital during losing streaks:
- **Circuit Breakers**: Automatically reduces position sizes during drawdowns
- **Protection Levels**: Normal → Caution (5%) → Warning (10%) → Danger (15%) → Halt (20%)
- **Recovery Protocol**: Gradually increases position sizes as performance improves
- **Capital Floor**: Protects minimum capital (default: 80% of base)

### 🎯 Capital Milestone Manager
Tracks progress and celebrates achievements:
- **Predefined Milestones**: $100, $250, $500, $1K, $5K, $25K, $50K, $100K
- **Profit Locking**: Automatically locks in gains at each milestone (default: 10%)
- **Position Scaling**: Increases position sizes after milestone achievements
- **Progress Tracking**: Shows percentage to next goal with visual progress bars

## Quick Start

### Basic Usage

```python
from bot.capital_scaling_engine import get_capital_engine

# Create engine with $1000 starting capital
engine = get_capital_engine(
    base_capital=1000.0,
    strategy="moderate",  # conservative/moderate/aggressive/full_compound
    enable_protection=True,
    enable_milestones=True
)

# Record a trade
profit = 50.0  # Gross profit
fees = 2.0     # Trading fees
is_win = True  # Profitable trade
new_capital = 1048.0  # Capital after trade

engine.record_trade(profit, fees, is_win, new_capital)

# Get optimal position size
available_balance = 1048.0
position_size = engine.get_optimal_position_size(available_balance)

# Check if trading is allowed
can_trade, reason = engine.can_trade()

# Get status
status = engine.get_capital_status()
print(f"Capital: ${status['current_capital']:.2f}")
print(f"ROI: {status['roi_pct']:.2f}%")
```

## Compounding Strategies

### Conservative (50% Reinvest, 50% Preserve)
**Best for:**
- Risk-averse traders
- Preserving gains
- Building capital slowly and safely

**Characteristics:**
- Slowest growth
- Highest profit preservation
- Minimal drawdown impact
- Recommended for accounts under $1,000

### Moderate (75% Reinvest, 25% Preserve)
**Best for:**
- Most traders (DEFAULT)
- Balanced growth and safety
- Medium-term goals

**Characteristics:**
- Good growth rate
- Reasonable profit preservation
- Moderate drawdown recovery
- Recommended for accounts $1,000-$10,000

### Aggressive (90% Reinvest, 10% Preserve)
**Best for:**
- Experienced traders
- Fast capital growth
- Higher risk tolerance

**Characteristics:**
- Fast growth
- Minimal profit preservation
- Quick recovery from drawdowns
- Recommended for accounts $10,000+

### Full Compound (100% Reinvest)
**Best for:**
- Professional traders
- Maximum growth focus
- Very high risk tolerance

**Characteristics:**
- Fastest possible growth
- No profit preservation
- Maximum drawdown exposure
- Only for experienced traders with backup capital

## Drawdown Protection Levels

| Level | Drawdown | Position Size | Trading Status |
|-------|----------|---------------|----------------|
| **NORMAL** | 0-5% | 100% | ✅ Full trading |
| **CAUTION** | 5-10% | 75% | ⚠️ Reduced positions |
| **WARNING** | 10-15% | 50% | ⚠️ Significantly reduced |
| **DANGER** | 15-20% | 25% | ⚠️ Minimal trading only |
| **HALT** | >20% | 0% | 🛑 Trading stopped |

### Recovery Protocol

Once in a protection level, the system requires:
- **3 consecutive wins** to step down one level
- **Recovery of 50%** of the drawdown amount

Example: If you're at WARNING level (10% drawdown), you need:
1. Three consecutive winning trades
2. Recover at least 5% (half of the 10% drawdown)
3. Then you can step down to CAUTION level

## Milestones

### Standard Milestone Ladder

| Milestone | Amount | Tier | Description |
|-----------|--------|------|-------------|
| Starter Achievement | $100 | SAVER | Minimum viable trading capital |
| Saver Threshold | $250 | INVESTOR | Multi-position rotation possible |
| Investor Entry | $500 | INVESTOR | Comfortable trading range |
| First $1K | $1,000 | INCOME | NIJA trades as designed |
| Income Tier | $2,500 | INCOME | Consistent income possible |
| Livable Entry | $5,000 | LIVABLE | Pro-style scaling enabled |
| $10K Milestone | $10,000 | LIVABLE | Semi-professional level |
| Baller Status | $25,000 | BALLER | Institutional behavior |
| $50K Club | $50,000 | BALLER | Professional trader |
| Six Figures | $100,000 | BALLER | Elite status |

### Milestone Benefits

When you achieve a milestone:
1. **Profit Locking**: 10% of total profits are locked and preserved
2. **Celebration**: System logs achievement with details
3. **Position Scaling**: Position sizes increase by 20% (if enabled)
4. **Progress Update**: Next milestone target is displayed

## Position Sizing

The engine calculates optimal position sizes considering:

1. **Base Position %**: Configured percentage (default: 5%)
2. **Compound Multiplier**: Increases with profits (max 2x)
3. **Drawdown Adjustment**: Reduces during losses (0-100%)
4. **Milestone Bonus**: Increases after achievements (+20% each)

### Formula

```
Optimal Position = Base Position × Compound Multiplier × Drawdown Multiplier × Milestone Multiplier
```

### Examples

**Scenario 1: Normal trading, no growth**
- Available: $1,000
- Base %: 5%
- Multipliers: 1.0 × 1.0 × 1.0 = 1.0
- Position: $50

**Scenario 2: After doubling capital**
- Available: $2,000
- Base %: 5%
- Compound: 2.0x (doubled capital)
- Position: $100 × 2.0 = $200

**Scenario 3: During 10% drawdown**
- Available: $900
- Base %: 5%
- Drawdown: 0.5x (WARNING level)
- Position: $45 × 0.5 = $22.50

**Scenario 4: After 3 milestones**
- Available: $5,000
- Base %: 5%
- Milestone: 1.6x (1 + 3×0.20)
- Position: $250 × 1.6 = $400

## Reporting

### Quick Summary

```python
print(engine.get_quick_summary())
# Output: 💰 $1159.00 (+15.9% ROI) | ✅ TRADING | 🛡️ NORMAL | 🎯 Next: First $1K (45%)
```

### Comprehensive Report

```python
print(engine.get_comprehensive_report())
```

Generates a multi-section report with:
- Overall capital status
- Compounding metrics (CAGR, growth rate, projections)
- Drawdown protection status
- Milestone progress and achievements
- Position sizing examples

### Capital Status Dictionary

```python
status = engine.get_capital_status()
```

Returns dictionary with:
- `base_capital`: Starting capital
- `current_capital`: Current total
- `total_profit`: All-time profit
- `roi_pct`: Return on investment %
- `compound_multiplier`: Growth multiplier
- `tradeable_capital`: Capital available for trading
- `preserved_profit`: Locked profits
- `drawdown_pct`: Current drawdown % (if protection enabled)
- `protection_level`: Current protection level
- `next_milestone`: Next milestone name (if milestones enabled)
- `milestone_progress_pct`: Progress % to next milestone
- `cagr`: Compound annual growth rate
- `daily_growth_rate`: Average daily growth %

## Integration with Trading Bot

### In TradingStrategy Class

```python
from bot.capital_scaling_engine import get_capital_engine

class TradingStrategy:
    def __init__(self, base_capital):
        # Initialize capital engine
        self.capital_engine = get_capital_engine(
            base_capital=base_capital,
            strategy="moderate",
            enable_protection=True,
            enable_milestones=True
        )
    
    def calculate_position_size(self, available_balance):
        # Check if trading is allowed
        can_trade, reason = self.capital_engine.can_trade()
        if not can_trade:
            logger.warning(f"Trading blocked: {reason}")
            return 0.0
        
        # Get optimal position size
        return self.capital_engine.get_optimal_position_size(available_balance)
    
    def on_trade_close(self, profit, fees, is_win, new_balance):
        # Record trade in capital engine
        self.capital_engine.record_trade(profit, fees, is_win, new_balance)
        
        # Log status
        logger.info(self.capital_engine.get_quick_summary())
    
    def get_capital_report(self):
        return self.capital_engine.get_comprehensive_report()
```

## Configuration

### Environment Variables

```bash
# Compounding strategy
CAPITAL_COMPOUNDING_STRATEGY=moderate  # conservative/moderate/aggressive/full_compound

# Drawdown protection
ENABLE_DRAWDOWN_PROTECTION=true
DRAWDOWN_HALT_THRESHOLD=20.0  # Stop trading at 20% drawdown

# Milestones
ENABLE_MILESTONES=true
LOCK_PROFIT_AT_MILESTONES=true
CELEBRATE_MILESTONES=true

# Position sizing
BASE_POSITION_PCT=0.05  # 5% base position size
ENABLE_DYNAMIC_POSITION_SIZING=true
```

### Custom Configuration

```python
from bot.capital_scaling_engine import CapitalScalingEngine, CapitalEngineConfig

config = CapitalEngineConfig(
    compounding_strategy="aggressive",
    reinvest_percentage=0.90,
    preserve_percentage=0.10,
    enable_drawdown_protection=True,
    halt_threshold_pct=25.0,  # More aggressive halt threshold
    warning_threshold_pct=15.0,
    enable_milestones=True,
    lock_profit_at_milestones=True,
    base_position_pct=0.08  # 8% base positions
)

engine = CapitalScalingEngine(
    base_capital=5000.0,
    current_capital=5000.0,
    config=config
)
```

## Best Practices

### Starting Out
1. **Use Conservative/Moderate**: Start with safer compounding strategies
2. **Enable All Features**: Use protection, compounding, and milestones
3. **Small Positions**: Keep base position size 5% or less
4. **Monitor Closely**: Watch the first few trades carefully

### Growing Capital
1. **Stay Disciplined**: Don't disable protection during drawdowns
2. **Trust the System**: Let compounding work over time
3. **Celebrate Milestones**: Lock in profits at achievements
4. **Scale Gradually**: Don't jump to aggressive too quickly

### Managing Drawdowns
1. **Don't Override Protection**: System knows when to reduce risk
2. **Win Streak Recovery**: Focus on getting 3 wins to step down
3. **Add Capital Carefully**: Adding funds resets drawdown tracking
4. **Learn from Losses**: Review what caused the drawdown

### Advanced Usage
1. **Custom Milestones**: Define your own goals beyond standard ladder
2. **Multiple Strategies**: Use different configs for different accounts
3. **Performance Analysis**: Track CAGR and growth rates over time
4. **Backtest Integration**: Test compounding with historical data

## Troubleshooting

### "Trading halted due to drawdown"
**Cause**: Drawdown exceeded 20% threshold
**Solution**: 
- Win 3 consecutive trades to begin recovery
- Add capital to reduce drawdown percentage
- Review and improve trading strategy

### "Position size too small"
**Cause**: Drawdown protection or small capital
**Solution**:
- Trade higher-value assets
- Increase base position percentage
- Grow capital before trading

### "No milestone progress"
**Cause**: Capital hasn't reached next milestone yet
**Solution**:
- Keep trading profitably
- Check milestone report for progress %
- Consider smaller custom milestones

### "CAGR shows extreme values"
**Cause**: Not enough trading days for reliable calculation
**Solution**:
- Wait for at least 7 days of trading
- CAGR stabilizes after 30+ days
- Use daily growth rate for short-term tracking

## Performance Metrics

### Key Metrics Tracked

1. **ROI (Return on Investment)**
   - Formula: `(Current - Base) / Base × 100`
   - Measures total percentage gain

2. **CAGR (Compound Annual Growth Rate)**
   - Formula: `((Current / Base) ^ (365 / Days)) - 1`
   - Annualized growth rate
   - Most meaningful after 30+ days

3. **Daily Growth Rate**
   - Formula: `Total Growth / Days × 100`
   - Average daily percentage gain

4. **Compound Multiplier**
   - Formula: `Current Capital / Base Capital`
   - How many times capital has grown

5. **Capital Velocity**
   - Formula: `Net Profit / Days Active`
   - Average dollar profit per day

## Examples

### Example 1: Conservative Growth ($500 → $1000)

```python
engine = get_capital_engine(500.0, strategy="conservative")

# Simulate 50 trades over 2 months
for i in range(50):
    profit = 15.0
    fees = 1.0
    engine.record_trade(profit, fees, True, engine.current_capital + 14)

# Results:
# - 50% preserved ($250)
# - 50% reinvested ($250)
# - Total: $1000
# - Locked at $100 milestone
```

### Example 2: Aggressive Growth with Drawdown ($1000 → $1500 → $1200)

```python
engine = get_capital_engine(1000.0, strategy="aggressive")

# Growth phase (10 wins)
for i in range(10):
    engine.record_trade(50.0, 2.0, True, capital)
# Capital reaches $1500

# Drawdown phase (5 losses)
for i in range(5):
    engine.record_trade(-40.0, 2.0, False, capital)
# Capital drops to $1290

# Protection activated: WARNING level (14% drawdown)
# Position sizes automatically reduced to 50%
```

## See Also

- **CAPITAL_CAPACITY_GUIDE.md** - Capital deployment and position sizing
- **RISK_PROFILES_GUIDE.md** - Risk management guidelines
- **TIER_AND_RISK_CONFIG_GUIDE.md** - Tier-based configurations
- **TRADE_SIZE_TUNING_GUIDE.md** - Advanced position sizing

## Support

For issues or questions:
1. Check logs in `data/compounding_state.json`
2. Review `data/drawdown_protection.json` for protection status
3. Check `data/milestones.json` for achievement history
4. Consult NIJA documentation repository

---

**Version**: 1.0  
**Last Updated**: January 28, 2026  
**Author**: NIJA Trading Systems
