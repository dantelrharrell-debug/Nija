# Quick Reference: Unified Execution Layer

## One-Line Summary
Single interface to trade on any exchange: `execute_trade(exchange, symbol, side, size, type)`

## Quick Start

```python
from bot.unified_execution_engine import execute_trade

# Buy $100 of BTC on Coinbase
result = execute_trade('coinbase', 'BTC-USD', 'buy', 100.0, 'market')

# Sell 0.5 ETH on Kraken  
result = execute_trade('kraken', 'ETH/USD', 'sell', 0.5, 'market', size_type='base')

# Limit buy on Binance
result = execute_trade('binance', 'BTCUSDT', 'buy', 50000.0, 'limit', price=50000.0)
```

## Supported Exchanges
- `'coinbase'` - Coinbase Advanced Trade
- `'kraken'` - Kraken Pro
- `'binance'` - Binance
- `'okx'` - OKX
- `'alpaca'` - Alpaca Markets

## Common Parameters

| Parameter | Required | Options | Default | Description |
|-----------|----------|---------|---------|-------------|
| `exchange` | Yes | coinbase, kraken, binance, okx, alpaca | - | Which exchange to use |
| `symbol` | Yes | BTC-USD, ETH/USD, BTCUSDT, etc. | - | Trading pair |
| `side` | Yes | buy, sell | - | Order direction |
| `size` | Yes | any float | - | Order size |
| `order_type` | No | market, limit, stop_loss | market | Order type |
| `price` | No | any float | None | Required for limit orders |
| `size_type` | No | quote, base | quote | Size in USD or base currency |

## Return Value

```python
result.success        # bool: Did it work?
result.order_id       # str: Exchange order ID
result.exchange       # str: Which exchange
result.error_message  # str: Error if failed
```

## Validate First (Optional)

```python
from bot.unified_execution_engine import validate_trade

validated = validate_trade('coinbase', 'BTC-USD', 'buy', 100.0)
if validated.valid:
    result = execute_trade('coinbase', 'BTC-USD', 'buy', 100.0)
```

## Exchange Minimums

| Exchange | Minimum Order | Fees (Round-trip) |
|----------|--------------|-------------------|
| Coinbase | $25 USD | 1.20% |
| Kraken | $10 USD | 0.42% |
| Binance | $15 USD | 0.20% |
| OKX | $10 USD | 0.20% |
| Alpaca | Account-based | 0% (commission-free) |

## Symbol Formats

| Exchange | Format | Example |
|----------|--------|---------|
| Coinbase | BASE-QUOTE | BTC-USD |
| Kraken | BASE/QUOTE | BTC/USD |
| Binance | BASEQUOTE | BTCUSDT |
| OKX | BASE-QUOTE | BTC-USDT |

**Note**: The engine handles normalization automatically!

## Error Handling

```python
result = execute_trade(...)
if not result.success:
    print(f"Error: {result.error_message}")
```

## Multi-Exchange Example

```python
# Same trade on all exchanges
for exchange in ['coinbase', 'kraken', 'binance', 'okx']:
    result = execute_trade(exchange, 'BTC-USD', 'buy', 100.0)
    print(f"{exchange}: {result.success}")
```

## Documentation

- **Full Guide**: `UNIFIED_EXECUTION_LAYER.md`
- **Integration**: `INTEGRATION_GUIDE_UNIFIED_EXECUTION.md`
- **Summary**: `IMPLEMENTATION_SUMMARY_UNIFIED_EXECUTION.md`

## Tests

```bash
python test_unified_execution_engine.py
```

## Key Benefit

**Strategies don't care where they trade - they just trade!** ✨
