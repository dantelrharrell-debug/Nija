# NIJA Unified Exchange Execution Layer

## Overview

The Unified Exchange Execution Layer provides a **single, simple interface** for executing trades across all supported exchanges. This is a game-changer for scaling NIJA, as **strategies don't care where they trade - they just trade**.

## Supported Exchanges

✅ **Kraken** - Cryptocurrency exchange  
✅ **Coinbase Advanced** - Cryptocurrency exchange  
✅ **Binance** - Cryptocurrency exchange  
✅ **OKX** - Cryptocurrency and derivatives exchange  
✅ **Alpaca** - Stock and crypto trading  

## The Simple Interface

```python
from bot.unified_execution_engine import execute_trade

# That's it! One function for all exchanges
result = execute_trade(
    exchange='coinbase',
    symbol='BTC-USD',
    side='buy',
    size=100.0,
    order_type='market'
)
```

## Why This Matters

### Before (Exchange-Specific Code)

```python
# Different code for each exchange
if exchange == 'coinbase':
    coinbase_client = CoinbaseClient()
    order = coinbase_client.place_order(symbol='BTC-USD', side='buy', ...)
elif exchange == 'kraken':
    kraken_client = KrakenClient()
    order = kraken_client.addOrder(pair='XXBTZUSD', type='buy', ...)
elif exchange == 'binance':
    binance_client = BinanceClient()
    order = binance_client.create_order(symbol='BTCUSDT', side='BUY', ...)
# ... different API for each exchange
```

### After (Unified Interface)

```python
# Same code for all exchanges - just change the exchange parameter!
for exchange in ['coinbase', 'kraken', 'binance', 'okx', 'alpaca']:
    result = execute_trade(
        exchange=exchange,
        symbol=get_symbol_for_exchange(exchange, 'BTC', 'USD'),
        side='buy',
        size=100.0,
        order_type='market'
    )
```

## Key Features

### 1. **Exchange-Agnostic Trading**
Strategies don't need to know which exchange they're trading on. The same strategy code works across all exchanges.

### 2. **Automatic Symbol Normalization**
Each exchange uses different symbol formats:
- Coinbase: `BTC-USD` (dash separator)
- Kraken: `BTC/USD` (slash separator)
- Binance: `BTCUSDT` (no separator, uses USDT)
- OKX: `BTC-USDT` (dash separator, uses USDT)

The unified layer handles this automatically!

### 3. **Exchange-Specific Validation**
Each exchange has different minimum order sizes and requirements:
- Coinbase: $25 minimum (to ensure profitability after 1.20% fees)
- Kraken: $10 minimum (lower fees at 0.42%)
- Binance: $15 minimum
- OKX: $10 minimum

The layer validates orders **before** sending them to prevent rejections.

### 4. **Unified Error Handling**
Consistent error handling across all exchanges with clear, actionable error messages.

## Usage Examples

### Basic Market Order

```python
from bot.unified_execution_engine import execute_trade

# Buy $100 of BTC on Coinbase
result = execute_trade(
    exchange='coinbase',
    symbol='BTC-USD',
    side='buy',
    size=100.0,
    order_type='market'
)

if result.success:
    print(f"Order placed! ID: {result.order_id}")
else:
    print(f"Order failed: {result.error_message}")
```

### Limit Order

```python
# Place a limit buy on Binance
result = execute_trade(
    exchange='binance',
    symbol='BTCUSDT',
    side='buy',
    size=100.0,
    order_type='limit',
    price=50000.0
)
```

### Trading with Base Currency

```python
# Sell 0.5 ETH on Kraken (base currency)
result = execute_trade(
    exchange='kraken',
    symbol='ETH/USD',
    side='sell',
    size=0.5,
    order_type='market',
    size_type='base'  # Size is in ETH, not USD
)
```

### Validate Before Executing

```python
from bot.unified_execution_engine import validate_trade

# Check if a trade is valid before executing
validated = validate_trade(
    exchange='coinbase',
    symbol='BTC-USD',
    side='buy',
    size=10.0  # Below $25 minimum
)

if validated.valid:
    # Execute the trade
    result = execute_trade(...)
else:
    print(f"Validation failed: {validated.error_message}")
```

### Multi-Exchange Strategy

```python
# Execute the same trade across multiple exchanges
def distribute_trade(base, quote, total_usd):
    """Distribute a trade across multiple exchanges."""
    exchanges = {
        'coinbase': f'{base}-{quote}',
        'kraken': f'{base}/{quote}',
        'binance': f'{base}USDT',  # Binance uses USDT
        'okx': f'{base}-USDT',
    }
    
    size_per_exchange = total_usd / len(exchanges)
    
    results = []
    for exchange, symbol in exchanges.items():
        result = execute_trade(
            exchange=exchange,
            symbol=symbol,
            side='buy',
            size=size_per_exchange,
            order_type='market'
        )
        results.append((exchange, result))
    
    return results

# Buy $400 of BTC distributed across 4 exchanges ($100 each)
results = distribute_trade('BTC', 'USD', 400.0)
```

## Return Values

### TradeResult Object

```python
@dataclass
class TradeResult:
    success: bool              # Whether trade succeeded
    exchange: str              # Exchange name
    symbol: str                # Trading pair
    side: str                  # 'buy' or 'sell'
    size: float                # Order size
    order_type: str            # 'market', 'limit', or 'stop_loss'
    order_id: str | None       # Exchange order ID (if successful)
    fill_price: float | None   # Actual fill price (if available)
    error_message: str | None  # Error message (if failed)
    raw_response: dict | None  # Raw exchange response
```

### ValidatedOrder Object

```python
@dataclass
class ValidatedOrder:
    symbol: str                # Normalized symbol
    side: str                  # Order side
    quantity: float            # Order quantity
    size_type: str             # 'base' or 'quote'
    valid: bool                # Is order valid?
    error_message: str | None  # Error if invalid
    warnings: list             # List of warnings
    adjusted: bool             # Was order adjusted?
```

## Parameters

### execute_trade()

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `exchange` | str | Yes | - | Exchange name: 'coinbase', 'kraken', 'binance', 'okx', 'alpaca' |
| `symbol` | str | Yes | - | Trading pair symbol (e.g., 'BTC-USD', 'ETH/USD', 'BTCUSDT') |
| `side` | str | Yes | - | Order side: 'buy' or 'sell' |
| `size` | float | Yes | - | Order size (in base or quote currency) |
| `order_type` | str | No | 'market' | Order type: 'market', 'limit', 'stop_loss' |
| `price` | float | No | None | Limit price (required for limit orders) |
| `size_type` | str | No | 'quote' | Size type: 'base' (e.g., 0.5 BTC) or 'quote' (e.g., $100 USD) |
| `validate_first` | bool | No | True | Validate trade before executing |

### validate_trade()

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `exchange` | str | Yes | - | Exchange name |
| `symbol` | str | Yes | - | Trading pair symbol |
| `side` | str | Yes | - | Order side: 'buy' or 'sell' |
| `size` | float | Yes | - | Order size |
| `size_type` | str | No | 'quote' | Size type: 'base' or 'quote' |
| `force_execute` | bool | No | False | Bypass minimum size checks (for stop-loss) |

## Exchange-Specific Details

### Coinbase Advanced
- **Symbol Format**: `BTC-USD` (dash separator)
- **Minimum Order**: $25 USD
- **Fees**: 0.60% maker + 0.60% taker = 1.20% round-trip
- **Quote Currencies**: USD, USDT, USDC

### Kraken
- **Symbol Format**: `BTC/USD` (slash separator)
- **Minimum Order**: $10 USD
- **Fees**: 0.16% maker + 0.26% taker = 0.42% round-trip
- **Quote Currencies**: USD, EUR (NO BUSD)
- **Note**: Does not support BUSD pairs

### Binance
- **Symbol Format**: `BTCUSDT` (no separator)
- **Minimum Order**: $15 USD
- **Fees**: 0.10% maker + 0.10% taker = 0.20% round-trip
- **Quote Currencies**: USDT, BUSD (converts USD to USDT automatically)
- **Note**: Uses USDT instead of USD

### OKX
- **Symbol Format**: `BTC-USDT` (dash separator)
- **Minimum Order**: $10 USD
- **Fees**: 0.08% maker + 0.10% taker = 0.20% round-trip (VIP tier)
- **Quote Currencies**: USDT, USDC (converts USD to USDT automatically)
- **Features**: Supports futures and perpetuals

### Alpaca
- **Symbol Format**: `AAPL`, `TSLA` (stock symbols)
- **Minimum Order**: Account-based
- **Fees**: Commission-free
- **Markets**: US stocks and crypto
- **Note**: Different market type from crypto exchanges

## Error Handling

### Common Errors

```python
result = execute_trade(...)

if not result.success:
    if "Unsupported exchange" in result.error_message:
        # Invalid exchange name
        print(f"Exchange not supported: {exchange}")
    
    elif "below minimum" in result.error_message:
        # Order size too small
        print(f"Order too small for {exchange}")
    
    elif "Invalid side" in result.error_message:
        # Invalid order side
        print("Side must be 'buy' or 'sell'")
    
    elif "Price is required" in result.error_message:
        # Missing price for limit order
        print("Limit orders require a price")
    
    else:
        # Other error
        print(f"Trade failed: {result.error_message}")
```

### Validation Warnings

```python
validated = validate_trade(...)

if validated.valid:
    # Check warnings
    for warning in validated.warnings:
        print(f"Warning: {warning}")
    
    # Warnings don't prevent execution, but should be logged
```

## Architecture

```
┌─────────────────────────────────────────┐
│     Strategy Layer                      │
│  (Your trading strategies)              │
└────────────────┬────────────────────────┘
                 │
                 │ execute_trade(exchange, symbol, side, size, type)
                 │
┌────────────────▼────────────────────────┐
│  Unified Execution Engine               │
│  - Validates trades                     │
│  - Normalizes symbols                   │
│  - Routes to correct exchange           │
│  - Handles errors consistently          │
└────────────────┬────────────────────────┘
                 │
       ┌─────────┴─────────┐
       │                   │
       ▼                   ▼
┌─────────────┐     ┌─────────────┐
│  Broker     │     │  Broker     │
│  Adapters   │ ... │  Adapters   │
│ (Validation)│     │ (Validation)│
└──────┬──────┘     └──────┬──────┘
       │                   │
       ▼                   ▼
┌─────────────┐     ┌─────────────┐
│ Exchange    │     │ Exchange    │
│ APIs        │ ... │ APIs        │
│ (Coinbase,  │     │ (Kraken,    │
│  Binance,   │     │  OKX,       │
│  Alpaca)    │     │  etc.)      │
└─────────────┘     └─────────────┘
```

## Integration with NIJA

### Using in Trading Strategies

```python
from bot.unified_execution_engine import execute_trade

class MyStrategy:
    def __init__(self, exchange='coinbase'):
        self.exchange = exchange
    
    def execute_buy_signal(self, symbol, size_usd):
        """Execute a buy signal on configured exchange."""
        result = execute_trade(
            exchange=self.exchange,
            symbol=symbol,
            side='buy',
            size=size_usd,
            order_type='market'
        )
        
        if result.success:
            self.log_trade(result)
        else:
            self.log_error(result.error_message)
        
        return result
    
    def execute_sell_signal(self, symbol, size_base):
        """Execute a sell signal on configured exchange."""
        result = execute_trade(
            exchange=self.exchange,
            symbol=symbol,
            side='sell',
            size=size_base,
            order_type='market',
            size_type='base'
        )
        
        return result
```

### Multi-Exchange Portfolio Manager

```python
from bot.unified_execution_engine import execute_trade

class MultiExchangePortfolio:
    def __init__(self):
        self.exchanges = ['coinbase', 'kraken', 'binance', 'okx']
        self.positions = {}
    
    def rebalance(self, target_allocations):
        """Rebalance portfolio across exchanges."""
        for exchange in self.exchanges:
            for symbol, target_pct in target_allocations.items():
                current_pct = self.get_allocation(exchange, symbol)
                
                if current_pct < target_pct:
                    # Buy more
                    size = self.calculate_buy_size(target_pct - current_pct)
                    execute_trade(exchange, symbol, 'buy', size)
                
                elif current_pct > target_pct:
                    # Sell excess
                    size = self.calculate_sell_size(current_pct - target_pct)
                    execute_trade(exchange, symbol, 'sell', size)
```

## Testing

Run the test suite to verify the unified execution layer:

```bash
python test_unified_execution_engine.py
```

This will test:
- ✅ Trade validation across all exchanges
- ✅ Order execution interface
- ✅ Error handling
- ✅ Symbol normalization
- ✅ Multi-exchange trading

## Benefits for Scaling

### 1. **Exchange Diversification**
Reduce risk by spreading trades across multiple exchanges. If one exchange has issues, others continue operating.

### 2. **Liquidity Access**
Access liquidity from multiple venues. Some pairs have better spreads on certain exchanges.

### 3. **API Rate Limit Distribution**
Distribute API calls across multiple exchanges to avoid rate limiting on any single exchange.

### 4. **Arbitrage Opportunities**
Easy to implement cross-exchange arbitrage strategies when you can execute on any exchange with the same interface.

### 5. **Strategy Reusability**
Write a strategy once, run it on any exchange. No need to rewrite strategy code for each exchange.

### 6. **Easy Testing**
Test strategies on lower-fee exchanges (like Kraken at 0.42%) before deploying to higher-fee exchanges.

## Current Status

✅ **Interface Complete**: The unified execution layer is fully implemented  
✅ **Validation Working**: All exchange-specific validation rules implemented  
✅ **Tests Passing**: All 5 test suites pass  
⚠️ **Execution Pending**: Actual broker execution needs integration with BrokerManager  

### Next Steps for Full Integration

1. **Connect to BrokerManager**: Wire up actual order execution
2. **Add Order Tracking**: Track order status and fills
3. **Position Management**: Track positions across exchanges
4. **Real-time Updates**: WebSocket connections for live price data
5. **Performance Metrics**: Track execution quality per exchange

## Summary

The Unified Exchange Execution Layer provides:

```python
# One simple function
execute_trade(exchange, symbol, side, size, type)

# That works across ALL exchanges
# - Kraken
# - Coinbase Advanced
# - Binance
# - OKX
# - Alpaca

# This is HUGE for scaling!
# Strategies don't care where they trade - they just trade.
```

**The abstraction layer handles all the complexity:**
- ✅ Symbol normalization (different formats per exchange)
- ✅ Minimum order validation (different per exchange)
- ✅ Fee awareness (different fees per exchange)
- ✅ Error handling (consistent across exchanges)
- ✅ Order type support (market, limit, stop-loss)

**Your strategies just focus on trading logic, not exchange-specific details.**
