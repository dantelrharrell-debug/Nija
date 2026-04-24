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

### 🟢 OKX (`okx_config.py`) - ULTRA-LOW FEES

**Characteristics:**
- **Fees**: 0.20% round-trip (LOWEST)
- **Assets**: Crypto + Futures + Perpetuals + Options
- **Strategy**: BIDIRECTIONAL (high frequency)

**Configuration:**
```python
from bot.broker_configs import OKX_CONFIG

# Fee structure
OKX_CONFIG.round_trip_cost  # 0.0020 (0.20% - LOWEST!)

# Profit targets (ultra-tight)
OKX_CONFIG.profit_targets  # [(0.8%, "EXCELLENT"), (0.6%, "VERY GOOD"), (0.4%, "GOOD")]

# Stop loss
OKX_CONFIG.stop_loss  # -0.5% (tightest)

# Position management
OKX_CONFIG.max_hold_hours  # 36 hours
OKX_CONFIG.min_position_usd  # $5 minimum
OKX_CONFIG.max_positions  # 15 (highest)
OKX_CONFIG.max_trades_per_day  # 80 (highest volume)

# Strategy
OKX_CONFIG.bidirectional  # True (both directions profitable)
OKX_CONFIG.enable_perpetuals  # True (OKX specialty)
```

**Why OKX for Scaling?**
- Ultra-low fees (0.20%) enable highest frequency trading
- Tightest profit targets (0.4%+)
- Supports perpetuals for 24/7 trading
- Most aggressive position sizing
- Ideal for scaling operations

---

### 🟡 Binance (`binance_config.py`) - BEST LIQUIDITY

**Characteristics:**
- **Fees**: 0.28% round-trip (very low)
- **Assets**: Crypto (1000+ pairs) + Futures
- **Strategy**: BIDIRECTIONAL (high volume)

**Configuration:**
```python
from bot.broker_configs import BINANCE_CONFIG

# Fee structure
BINANCE_CONFIG.round_trip_cost  # 0.0028 (0.28% - very competitive)

# Profit targets (tight)
BINANCE_CONFIG.profit_targets  # [(0.9%, "EXCELLENT"), (0.6%, "GOOD"), (0.5%, "ACCEPTABLE")]

# Stop loss
BINANCE_CONFIG.stop_loss  # -0.6%

# Position management
BINANCE_CONFIG.max_hold_hours  # 30 hours
BINANCE_CONFIG.min_position_usd  # $5 minimum
BINANCE_CONFIG.max_positions  # 12
BINANCE_CONFIG.max_trades_per_day  # 70

# Strategy
BINANCE_CONFIG.bidirectional  # True (both directions profitable)
BINANCE_CONFIG.enable_futures  # True
```

**Why Binance for Scaling?**
- Best liquidity in crypto markets
- Low fees (0.28%) enable high frequency
- 1000+ trading pairs
- Deep order books reduce slippage
- BNB discount reduces fees further

---

### 🔷 Alpaca (`alpaca_config.py`) - ZERO COMMISSIONS

**Characteristics:**
- **Fees**: 0.20% (spread only, ZERO commissions)
- **Assets**: US Stocks + ETFs + Options
- **Strategy**: AGGRESSIVE (zero fees)

**Configuration:**
```python
from bot.broker_configs import ALPACA_CONFIG

# Fee structure
ALPACA_CONFIG.round_trip_cost  # 0.0020 (0.20% spread only)

# Profit targets (very tight)
ALPACA_CONFIG.profit_targets  # [(0.6%, "EXCELLENT"), (0.4%, "GOOD"), (0.3%, "ACCEPTABLE")]

# Stop loss
ALPACA_CONFIG.stop_loss  # -0.4%

# Position management
ALPACA_CONFIG.max_hold_hours  # 6.5 hours (market hours only)
ALPACA_CONFIG.min_position_usd  # $1 minimum (fractional shares)
ALPACA_CONFIG.max_positions  # 10
ALPACA_CONFIG.max_trades_per_day  # 50

# PDT enforcement
ALPACA_CONFIG.pdt_threshold  # $25,000
ALPACA_CONFIG.enforce_pdt  # True
```

**Why Alpaca for Scaling?**
- Zero commissions (only spread costs)
- Fractional shares ($1 minimum)
- Stock market diversification
- PDT-aware position sizing
- Paper trading for testing

---

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
COINBASE_CONFIG.min_position_usd  # $25 minimum (unified across all systems)

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

| Feature | OKX | Binance | Alpaca | Kraken | Coinbase |
|---------|-----|---------|--------|--------|----------|
| **Round-trip fees** | 0.20% | 0.28% | 0.20% | 0.36% | 1.40% |
| **Min profit target** | 0.4% | 0.5% | 0.3% | 0.5% | 1.5% |
| **Stop loss** | -0.5% | -0.6% | -0.4% | -0.7% | -1.0% |
| **Max hold time** | 36h | 30h | 6.5h | 24h | 8h |
| **Min position** | $5 | $5 | $1 | $5 | $10 |
| **Max trades/day** | 80 | 70 | 50 | 60 | 30 |
| **Max positions** | 15 | 12 | 10 | 12 | 8 |
| **Short selling** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Futures** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Perpetuals** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Stocks** | ❌ | ❌ | ✅ | ❌ | ❌ |
| **Strategy** | Bidirectional | Bidirectional | Aggressive | Bidirectional | Buy-only |
| **Best For** | Scaling | Liquidity | Stocks | Reliability | Selective |

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

- **Machine learning** - Optimize targets per broker
- **Dynamic fee updates** - Adjust to tier changes
- **Real-time market conditions** - Adjust strategies based on volatility

---

## Files

- `__init__.py` - Module initialization and exports
- `coinbase_config.py` - Coinbase-specific configuration
- `kraken_config.py` - Kraken-specific configuration
- `binance_config.py` - Binance-specific configuration (NEW)
- `okx_config.py` - OKX-specific configuration (NEW)
- `alpaca_config.py` - Alpaca-specific configuration (NEW)
- `default_config.py` - Default conservative configuration
- `strategy_selector.py` - Broker strategy routing logic
- `README.md` - This file

---

**Last Updated**: January 22, 2026
**Version**: 2.0
**Status**: ✅ Production Ready with Multi-Broker Scaling Support
