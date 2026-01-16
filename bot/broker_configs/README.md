# Broker-Specific Trading Configurations

## Overview

Each brokerage has different fee structures, supported assets, and optimal trading strategies. This module provides **dedicated buy and sell logic for each brokerage** to maximize profitability.

## Why Broker-Specific Logic?

**Problem**: Using the same strategy across all brokers is suboptimal because:
- Coinbase has 4x higher fees than Kraken (1.4% vs 0.36%)
- Kraken supports futures/options, Coinbase doesn't
- Short selling is profitable on Kraken but not on Coinbase (due to fees)
- Different minimum position sizes are viable on each exchange

**Solution**: Separate configurations optimized for each broker's characteristics.

## Broker Configurations

### 🔵 Coinbase (`coinbase_config.py`)

**Characteristics:**
- **Fees**: 1.4% round-trip (high)
- **Assets**: Crypto only
- **Strategy**: BUY-FOCUSED

**Configuration:**
```python
from bot.broker_configs import COINBASE_CONFIG

# Fee structure
COINBASE_CONFIG.round_trip_cost  # 0.014 (1.4%)

# Profit targets (must exceed fees)
COINBASE_CONFIG.profit_targets  # [(1.5%, "GOOD"), (1.2%, "ACCEPTABLE"), (1.0%, "EMERGENCY")]

# Stop loss
COINBASE_CONFIG.stop_loss  # -1.0% (aggressive)

# Position management
COINBASE_CONFIG.max_hold_hours  # 8 hours (short due to high fees)
COINBASE_CONFIG.min_position_usd  # $10 minimum

# Strategy
COINBASE_CONFIG.buy_preferred  # True
COINBASE_CONFIG.sell_preferred  # False (unprofitable with high fees)
COINBASE_CONFIG.bidirectional  # False
```

**Why Buy-Focused?**
- High fees make frequent buying/selling unprofitable
- Better to buy on dips, sell for quick profit
- Short selling not viable (1.4% fees eat profits)

---

### 🟣 Kraken (`kraken_config.py`)

**Characteristics:**
- **Fees**: 0.36% round-trip (4x cheaper than Coinbase!)
- **Assets**: Crypto + Futures + Options + Stocks
- **Strategy**: BIDIRECTIONAL

**Configuration:**
```python
from bot.broker_configs import KRAKEN_CONFIG

# Fee structure
KRAKEN_CONFIG.round_trip_cost  # 0.0036 (0.36% - 4x cheaper!)

# Profit targets (lower targets viable)
KRAKEN_CONFIG.profit_targets  # [(1.0%, "EXCELLENT"), (0.7%, "GOOD"), (0.5%, "ACCEPTABLE")]

# Stop loss
KRAKEN_CONFIG.stop_loss  # -0.7% (tighter due to low fees)

# Position management
KRAKEN_CONFIG.max_hold_hours  # 24 hours (3x longer than Coinbase)
KRAKEN_CONFIG.min_position_usd  # $5 minimum (2x smaller)

# Strategy
KRAKEN_CONFIG.buy_preferred  # True
KRAKEN_CONFIG.sell_preferred  # True (PROFITABLE with low fees!)
KRAKEN_CONFIG.bidirectional  # True

# Derivatives
KRAKEN_CONFIG.supports_futures  # True
KRAKEN_CONFIG.supports_options  # True
```

**Why Bidirectional?**
- Low fees (0.36%) make both buying AND selling profitable
- Can short sell profitably
- Futures and options provide additional strategies
- Can use smaller positions ($5 vs $10)
- Can hold longer (24h vs 8h)

---

### ⚪ Default (`default_config.py`)

**Characteristics:**
- Conservative configuration for unknown brokers
- Assumes moderate fees (1.2%)
- Buy-focused strategy

---

## Usage

### Automatic Strategy Selection

```python
from bot.broker_configs import STRATEGY_SELECTOR

# Select strategy for specific broker
config = STRATEGY_SELECTOR.select_strategy("kraken")

# Use broker-specific logic
if config.should_buy(rsi=35, price=100, ema9=98, ema21=96):
    position_size = config.calculate_position_size(account_balance=1000)
    # Execute buy order
```

### Manual Configuration

```python
from bot.broker_configs import COINBASE_CONFIG, KRAKEN_CONFIG

# Get Coinbase profit targets
coinbase_targets = COINBASE_CONFIG.profit_targets
# [(0.015, "1.5%"), (0.012, "1.2%"), (0.010, "1.0%")]

# Get Kraken profit targets
kraken_targets = KRAKEN_CONFIG.profit_targets
# [(0.010, "1.0%"), (0.007, "0.7%"), (0.005, "0.5%")]

# Kraken can profit with 0.5% move, Coinbase needs 1.0% minimum
```

### Compare Strategies

```python
from bot.broker_configs.strategy_selector import STRATEGY_SELECTOR

# Print detailed comparison
STRATEGY_SELECTOR.print_strategy_comparison()
```

---

## Key Differences Summary

| Feature | Coinbase | Kraken | Difference |
|---------|----------|--------|------------|
| **Round-trip fees** | 1.4% | 0.36% | **4x cheaper** |
| **Min profit target** | 1.5% | 0.5% | **3x lower** |
| **Stop loss** | -1.0% | -0.7% | Tighter |
| **Max hold time** | 8 hours | 24 hours | **3x longer** |
| **Min position** | $10 | $5 | **2x smaller** |
| **Max trades/day** | 30 | 60 | **2x more** |
| **Short selling** | ❌ Unprofitable | ✅ **PROFITABLE** | Huge advantage |
| **Futures/Options** | ❌ Not supported | ✅ **Supported** | More strategies |
| **Strategy** | Buy-only | Bidirectional | More opportunities |

---

## Integration with Trading Strategy

The trading strategy should query the appropriate configuration based on the broker being used:

```python
# In trading_strategy.py
from bot.broker_configs import STRATEGY_SELECTOR

def run_cycle(self, broker):
    broker_type = broker.broker_type.value  # 'coinbase' or 'kraken'
    config = STRATEGY_SELECTOR.select_strategy(broker_type)
    
    # Use broker-specific profit targets
    profit_targets = config.profit_targets
    
    # Use broker-specific stop loss
    stop_loss = config.stop_loss
    
    # Check if should enter long
    if config.should_buy(rsi, price, ema9, ema21):
        position_size = config.calculate_position_size(balance, signal_strength)
        # Execute trade
    
    # Check if should enter short (only on Kraken!)
    if config.bidirectional and config.should_short(rsi, price, ema9, ema21):
        # Short selling only on low-fee exchanges
        pass
```

---

## Benefits

### ✅ Coinbase Configuration Benefits
- Optimized for high-fee environment
- Focus on quality over quantity
- Buy-focused to avoid unprofitable selling
- Minimum $10 positions to overcome fees
- Quick 8-hour exits to avoid fee accumulation

### ✅ Kraken Configuration Benefits
- Optimized for low-fee environment
- Can profit from 0.5% moves (vs 1.5% on Coinbase)
- **Short selling profitable** (not viable on Coinbase)
- Smaller $5 positions viable
- Can hold 24 hours for bigger moves
- 60 trades/day possible (vs 30 on Coinbase)
- Futures and options support

### ✅ Overall System Benefits
- **Maximum profitability per broker**
- No wasted opportunities
- Fee-aware position sizing
- Appropriate strategies per fee structure
- Can run different strategies simultaneously

---

## Future Enhancements

- **Alpaca configuration** - Stock-specific strategies
- **Binance configuration** - International crypto exchange
- **OKX configuration** - Derivatives-focused
- **Dynamic fee updates** - Adjust to tier changes
- **Machine learning** - Optimize targets per broker

---

## Files

- `__init__.py` - Module initialization and exports
- `coinbase_config.py` - Coinbase-specific configuration
- `kraken_config.py` - Kraken-specific configuration
- `default_config.py` - Default conservative configuration
- `strategy_selector.py` - Broker strategy routing logic
- `README.md` - This file

---

**Last Updated**: January 16, 2026  
**Version**: 1.0  
**Status**: ✅ Production Ready
