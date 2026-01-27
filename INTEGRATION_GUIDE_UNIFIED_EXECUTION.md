# Quick Start: Unified Execution Layer Integration

## For Existing NIJA Code

If you're working with existing NIJA trading strategies and want to use the new unified execution layer, here's how to integrate it:

### Step 1: Import the Unified Engine

```python
# Add to your strategy file
from bot.unified_execution_engine import execute_trade, validate_trade
```

### Step 2: Replace Exchange-Specific Code

**Before (Old Way):**
```python
# Old: Exchange-specific code
if self.broker == 'coinbase':
    from bot.broker_manager import BrokerManager
    broker = BrokerManager()
    # Coinbase-specific order placement
    result = broker.place_coinbase_order(...)
elif self.broker == 'kraken':
    # Different API for Kraken
    result = broker.place_kraken_order(...)
```

**After (New Way):**
```python
# New: Unified interface for all exchanges
result = execute_trade(
    exchange=self.broker,  # 'coinbase', 'kraken', etc.
    symbol=symbol,
    side='buy',
    size=position_size_usd,
    order_type='market'
)
```

### Step 3: Handle Results

```python
if result.success:
    logger.info(f"✅ Order placed: {result.order_id}")
    # Track the position
    self.positions[symbol] = {
        'order_id': result.order_id,
        'size': result.size,
        'fill_price': result.fill_price
    }
else:
    logger.error(f"❌ Order failed: {result.error_message}")
```

## Integration Examples

### Example 1: Update Existing Strategy

```python
class ApexStrategy:
    """APEX v7.1 strategy with unified execution."""
    
    def __init__(self, exchange='coinbase'):
        self.exchange = exchange
        self.positions = {}
    
    def execute_entry(self, symbol, entry_size_usd):
        """Execute entry with unified interface."""
        # Validate first
        validated = validate_trade(
            exchange=self.exchange,
            symbol=symbol,
            side='buy',
            size=entry_size_usd
        )
        
        if not validated.valid:
            logger.warning(f"⚠️ Entry validation failed: {validated.error_message}")
            return None
        
        # Execute trade
        result = execute_trade(
            exchange=self.exchange,
            symbol=symbol,
            side='buy',
            size=entry_size_usd,
            order_type='market'
        )
        
        if result.success:
            # Track position
            self.positions[symbol] = {
                'order_id': result.order_id,
                'entry_size': result.size,
                'exchange': self.exchange
            }
        
        return result
    
    def execute_exit(self, symbol, exit_size_base):
        """Execute exit with unified interface."""
        result = execute_trade(
            exchange=self.exchange,
            symbol=symbol,
            side='sell',
            size=exit_size_base,
            order_type='market',
            size_type='base'  # Selling base currency (e.g., 0.5 BTC)
        )
        
        if result.success and symbol in self.positions:
            del self.positions[symbol]
        
        return result
```

### Example 2: Multi-Exchange Portfolio

```python
class MultiExchangePortfolio:
    """Manage positions across multiple exchanges."""
    
    def __init__(self, exchanges=['coinbase', 'kraken', 'binance']):
        self.exchanges = exchanges
        self.positions = {ex: {} for ex in exchanges}
    
    def distribute_buy(self, symbol, total_usd):
        """Distribute a buy order across all exchanges."""
        size_per_exchange = total_usd / len(self.exchanges)
        
        results = []
        for exchange in self.exchanges:
            # Get exchange-specific symbol format
            exchange_symbol = self.normalize_symbol(symbol, exchange)
            
            # Execute on this exchange
            result = execute_trade(
                exchange=exchange,
                symbol=exchange_symbol,
                side='buy',
                size=size_per_exchange,
                order_type='market'
            )
            
            if result.success:
                self.positions[exchange][symbol] = result
            
            results.append((exchange, result))
        
        return results
    
    def normalize_symbol(self, symbol, exchange):
        """Convert symbol to exchange-specific format."""
        # The unified engine handles this automatically,
        # but you can pre-normalize if needed
        symbol_map = {
            'coinbase': symbol.replace('/', '-'),
            'kraken': symbol.replace('-', '/'),
            'binance': symbol.replace('-', '').replace('/', ''),
            'okx': symbol.replace('/', '-')
        }
        return symbol_map.get(exchange, symbol)
```

### Example 3: Strategy Router

```python
class StrategyRouter:
    """Route trades to the best exchange based on conditions."""
    
    def __init__(self):
        self.exchange_fees = {
            'coinbase': 0.012,  # 1.20%
            'kraken': 0.0042,   # 0.42%
            'binance': 0.002,   # 0.20%
            'okx': 0.002        # 0.20%
        }
    
    def execute_with_best_fees(self, symbol, side, size):
        """Execute on the exchange with the lowest fees."""
        # Choose exchange with lowest fees
        best_exchange = min(self.exchange_fees.items(), key=lambda x: x[1])[0]
        
        logger.info(f"📊 Routing to {best_exchange} (lowest fees: {self.exchange_fees[best_exchange]*100}%)")
        
        result = execute_trade(
            exchange=best_exchange,
            symbol=symbol,
            side=side,
            size=size,
            order_type='market'
        )
        
        return result
    
    def execute_with_fallback(self, symbol, side, size):
        """Try exchanges in order until one succeeds."""
        exchanges = ['kraken', 'binance', 'coinbase', 'okx']
        
        for exchange in exchanges:
            logger.info(f"🎯 Attempting on {exchange}...")
            
            result = execute_trade(
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type='market'
            )
            
            if result.success:
                logger.info(f"✅ Success on {exchange}")
                return result
            else:
                logger.warning(f"⚠️ Failed on {exchange}: {result.error_message}")
        
        logger.error("❌ All exchanges failed")
        return None
```

## Migration Checklist

- [ ] Import unified execution functions
- [ ] Replace exchange-specific broker calls with `execute_trade()`
- [ ] Update symbol normalization (or let the engine handle it)
- [ ] Update error handling to use `TradeResult` object
- [ ] Test with small amounts first
- [ ] Update logging to use new result format
- [ ] Remove old exchange-specific code

## Benefits of Migration

✅ **Simpler Code**: One function instead of many  
✅ **More Exchanges**: Easy to add new exchanges  
✅ **Better Validation**: Automatic pre-flight checks  
✅ **Consistent Errors**: Same error handling everywhere  
✅ **Symbol Normalization**: Automatic format conversion  
✅ **Multi-Exchange**: Easy to distribute trades  

## Need Help?

- Check `UNIFIED_EXECUTION_LAYER.md` for full documentation
- Run `python test_unified_execution_engine.py` for examples
- See `examples/unified_execution_example.py` for usage patterns

## Next Steps

After migration:
1. Test thoroughly on each exchange
2. Monitor execution quality
3. Compare fees and slippage across exchanges
4. Optimize exchange selection based on conditions
5. Implement advanced multi-exchange strategies
