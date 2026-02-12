# Performance Attribution & Capital Scaling - Usage Guide

## Overview

This guide shows how to use the new performance attribution, capital scaling integration, and comprehensive reporting systems in NIJA.

**KEY PRINCIPLE**: All systems respect frozen risk limits. Position sizes NEVER exceed `max_position_pct` regardless of scaling factors.

## Quick Start

### 1. Performance Attribution

Track which signals, sectors, and assets drive gains/losses:

```python
from bot.performance_attribution import get_performance_attribution

# Initialize attribution system
attribution = get_performance_attribution()

# Record a trade with full attribution
attribution.record_trade(
    trade_id="trade_001",
    symbol="BTC-USD",
    strategy="APEX_V71",
    market_regime="bull_trending",
    entry_price=45000.0,
    exit_price=46000.0,
    position_size=0.1,
    side="long",
    pnl=100.0,
    fees=2.0,
    risk_capital=4500.0,
    # NEW: Attribution dimensions
    signal_type="RSI_oversold",  # Which signal triggered the trade
    sector="Layer1",              # Market sector
    asset_class="crypto"          # Asset class
)

# Get attribution breakdown
strategy_attrs = attribution.get_strategy_attribution()
regime_attrs = attribution.get_regime_attribution()

# Generate attribution report
report = attribution.generate_attribution_report()
print(report)
```

**What it tracks:**
- **By Strategy**: Which strategies perform best
- **By Market Regime**: Performance in different market conditions
- **By Signal Type**: Which signals are most profitable
- **By Sector**: Which sectors generate returns
- **By Time Period**: Daily/weekly/monthly attribution

### 2. Capital Scaling Integration

Dynamically scale allocations while respecting frozen risk limits:

```python
from bot.capital_scaling_integration import (
    get_capital_scaling_integration,
    PositionSizingParams
)

# Initialize integration (one-time setup)
capital_scaling = get_capital_scaling_integration(
    initial_capital=10000.0,
    base_position_pct=0.05,  # 5% base position size
    enable_autonomous_scaling=True,
    enable_attribution=True
)

# Calculate position size with all scaling factors
params = PositionSizingParams(
    available_balance=12000.0,
    current_price=45000.0,
    volatility=0.25,
    expected_return=0.15,
    signal_strength=0.8,  # 0.0 to 1.0
    market_regime="bull_trending",
    strategy_name="APEX_V71",
    max_position_pct=0.10  # 🔒 FROZEN RISK LIMIT - NEVER EXCEEDED
)

result = capital_scaling.calculate_position_size(params)

print(f"Position Size: ${result.position_size_usd:,.2f}")
print(f"Position %: {result.position_pct_of_capital:.2f}%")
print(f"Can Trade: {result.can_trade}")
print(f"Frozen Limit Applied: {result.scaling_factors['frozen_limit_applied']}")

# Record trade after execution
capital_scaling.record_trade(
    trade_id="trade_001",
    symbol="BTC-USD",
    strategy="APEX_V71",
    market_regime="bull_trending",
    entry_price=45000.0,
    exit_price=46000.0,
    position_size=result.position_size_base,
    side="long",
    pnl=100.0,
    fees=2.0,
    risk_capital=result.position_size_usd,
    new_capital=12098.0
)
```

**🔒 Frozen Risk Limit Guarantee:**
```
Position size will NEVER exceed:
  available_balance * max_position_pct
  
Even if scaling factors suggest a larger size!
```

### 3. Comprehensive Reporting

Auto-generate daily/weekly performance and compliance reports:

```python
from bot.comprehensive_reporting import get_comprehensive_reporting

# Initialize reporting system
reporting = get_comprehensive_reporting()

# Generate daily report
daily_report = reporting.generate_daily_report(save_to_file=True)
print(daily_report)

# Generate weekly report
weekly_report = reporting.generate_weekly_report(save_to_file=True)
print(weekly_report)

# Export to JSON for programmatic access
json_file = reporting.export_to_json(report_type="daily")
```

**Daily Report Includes:**
- Executive Summary (capital, returns, trades, win rate)
- Performance Metrics (Sharpe, Sortino, drawdown, profit factor)
- Risk Assessment (drawdown levels, protection status)
- Compliance Status (frozen limits respected ✅)
- Attribution Breakdown (by strategy, regime, signal, sector)
- Capital Scaling Status (compounding, preserved profit)

**Weekly Report Includes:**
- Weekly summary and trends
- Daily attribution breakdown
- Top performing strategies
- Compliance verification

## Integration with Existing Trading Strategy

### Example: Integrate with APEX V7.1

```python
from bot.nija_apex_strategy_v71 import NijaApexStrategyV71
from bot.capital_scaling_integration import (
    get_capital_scaling_integration,
    PositionSizingParams
)

class EnhancedApexStrategy(NijaApexStrategyV71):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize capital scaling integration
        self.capital_scaling = get_capital_scaling_integration(
            initial_capital=self.config.get('initial_capital', 1000.0),
            base_position_pct=self.config.get('min_position_pct', 0.05),
            enable_autonomous_scaling=True,
            enable_attribution=True
        )
    
    def calculate_position_size_enhanced(
        self,
        account_balance: float,
        symbol: str,
        signal_strength: float,
        market_regime: str
    ) -> float:
        """
        Calculate position size using capital scaling integration
        with frozen risk limit enforcement
        """
        # Get current price and volatility
        current_price = self.broker.get_current_price(symbol)
        volatility = self.calculate_volatility(symbol)  # Your method
        
        # Create position sizing params
        params = PositionSizingParams(
            available_balance=account_balance,
            current_price=current_price,
            volatility=volatility,
            expected_return=0.15,  # Expected return estimate
            signal_strength=signal_strength,
            market_regime=market_regime,
            strategy_name="APEX_V71",
            max_position_pct=self.risk_manager.max_position_pct  # 🔒 FROZEN LIMIT
        )
        
        # Calculate optimal position size
        result = self.capital_scaling.calculate_position_size(params)
        
        if not result.can_trade:
            logger.warning(f"Trading halted: {result.reason}")
            return 0.0
        
        logger.info(
            f"Position sized: ${result.position_size_usd:,.2f} "
            f"({result.position_pct_of_capital:.2f}% of capital)"
        )
        
        if result.scaling_factors['frozen_limit_applied']:
            logger.info(
                f"🔒 Frozen risk limit enforced at "
                f"{params.max_position_pct*100:.1f}%"
            )
        
        return result.position_size_base
    
    def record_trade_with_attribution(
        self,
        trade_id: str,
        symbol: str,
        entry_price: float,
        exit_price: float,
        position_size: float,
        side: str,
        pnl: float,
        fees: float,
        market_regime: str,
        signal_type: str,
        sector: str
    ):
        """
        Record trade with full attribution
        """
        new_capital = self.broker.get_account_balance()
        
        # Record in capital scaling system
        self.capital_scaling.record_trade(
            trade_id=trade_id,
            symbol=symbol,
            strategy="APEX_V71",
            market_regime=market_regime,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size=position_size,
            side=side,
            pnl=pnl,
            fees=fees,
            risk_capital=entry_price * position_size,
            new_capital=new_capital
        )
```

## Automated Daily Reporting

Set up automated daily reports:

```python
from bot.comprehensive_reporting import get_comprehensive_reporting
import schedule
import time

# Initialize reporting
reporting = get_comprehensive_reporting()

def generate_daily_reports():
    """Generate and save daily reports"""
    # Generate text report
    daily_report = reporting.generate_daily_report(save_to_file=True)
    
    # Export to JSON
    json_file = reporting.export_to_json(report_type="daily")
    
    # Log completion
    logger.info(f"✅ Daily reports generated and saved")

# Schedule daily reports at 11:59 PM
schedule.every().day.at("23:59").do(generate_daily_reports)

# Run scheduler
while True:
    schedule.run_pending()
    time.sleep(60)
```

## Key Features

### 1. Performance Attribution
✅ Track signals (RSI_oversold, momentum_breakout, etc.)
✅ Track sectors (DeFi, Layer1, Memecoins, etc.)
✅ Track asset classes (crypto, forex, stocks, etc.)
✅ Strategy-level metrics (win rate, Sharpe ratio, capital efficiency)
✅ Market regime attribution
✅ Time-based attribution (daily/weekly/monthly)

### 2. Capital Scaling
✅ Respects FROZEN RISK LIMITS (hard position size caps)
✅ Integrates compounding and drawdown protection
✅ Autonomous volatility and regime adjustments
✅ Full scaling factor breakdown
✅ Real-time capital status monitoring

### 3. Comprehensive Reporting
✅ Auto-generated daily and weekly reports
✅ Performance metrics (Sharpe, Sortino, drawdown)
✅ Risk assessment with warnings
✅ Compliance verification
✅ Attribution breakdown
✅ JSON export for programmatic access

## Compliance Guarantee

**All systems respect frozen risk discipline:**

```python
# Maximum position size is ALWAYS enforced
max_allowed = available_balance * max_position_pct  # 🔒 FROZEN LIMIT

# Even if scaling suggests 15% of capital,
# if max_position_pct is 10%, position will be capped at 10%
```

**Reports verify compliance:**
```
✅ COMPLIANCE STATUS
------------------------------------------------------------------
  ✅ Frozen risk limits respected
  ✅ Position size caps enforced
  ✅ Drawdown protection active
  ✅ Maximum exposure within limits
```

## Directory Structure

```
reports/
├── daily/
│   ├── daily_report_2026-02-12.txt
│   └── daily_report_2026-02-12.json
├── weekly/
│   ├── weekly_report_2026-02-12.txt
│   └── weekly_report_2026-02-12.json
├── monthly/
└── compliance/

data/
└── attribution/
    └── trades.json  # Attribution history
```

## API Reference

See module documentation:
- `bot/performance_attribution.py` - Performance attribution system
- `bot/capital_scaling_integration.py` - Capital scaling integration
- `bot/comprehensive_reporting.py` - Automated reporting system

## Support

For questions or issues with the new systems:
1. Check this usage guide
2. Review module documentation
3. See integration examples above
4. Test with sample data before production use

---

**Remember: These enhancements grow capital and improve transparency WITHOUT breaking your frozen risk discipline! 🔒**
