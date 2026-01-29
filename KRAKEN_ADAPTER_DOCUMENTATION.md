# Kraken Adapter Module Documentation

## Overview

The Kraken Adapter Module provides broker-specific symbol normalization, position reconciliation, and dust threshold management for Kraken cryptocurrency trading.

## Features

### 1. Symbol Normalization

The module provides centralized symbol normalization for Kraken and Coinbase exchanges.

#### Kraken Format
- Input: `ETH-USD`, `BTC-USD`, `SOL-USD` (with dash or slash)
- Output: `ETHUSD`, `BTCUSD`, `SOLUSD` (no separator)

#### Coinbase Format
- Input: `ETHUSD`, `BTCUSD`, `SOL/USD` (no separator or slash)
- Output: `ETH-USD`, `BTC-USD`, `SOL-USD` (dash separator)

#### Usage

```python
from bot.kraken_adapter import normalize_symbol

# Normalize for Kraken
kraken_symbol = normalize_symbol("ETH-USD", "kraken")  # Returns "ETHUSD"

# Normalize for Coinbase
coinbase_symbol = normalize_symbol("ETHUSD", "coinbase")  # Returns "ETH-USD"
```

### 2. Dust Threshold Management

Positions below $1.00 USD value are considered "dust" and should not be tracked to prevent:
- Phantom positions
- Position cap pollution
- Endless cleanup attempts

#### Constants

```python
DUST_THRESHOLD_USD = 1.00  # Minimum USD value to track
```

#### Usage

```python
from bot.kraken_adapter import is_dust_position, should_track_position

# Check if position is dust
if is_dust_position(0.75):  # Returns True (dust)
    print("Skip tracking this position")

# Check if position should be tracked
if should_track_position(5.00):  # Returns True (track)
    print("Track this position")
```

### 3. Position Reconciliation

After failed exit attempts, the reconciler refreshes positions from the exchange to prevent phantom positions.

#### Usage

```python
from bot.kraken_adapter import get_kraken_reconciler, reconcile_kraken_position_after_failed_exit

# Method 1: Using convenience function
success = reconcile_kraken_position_after_failed_exit(
    symbol="ETH-USD",
    attempted_size=0.1,
    broker_adapter=kraken_broker
)

# Method 2: Using reconciler instance
reconciler = get_kraken_reconciler(broker_adapter=kraken_broker)
success = reconciler.reconcile_after_failed_exit("ETH-USD", 0.1)
```

#### Reconciliation Process

1. **Refresh positions from exchange** - Fetch current state from Kraken API
2. **Purge stale internal positions** - Remove positions that don't exist on exchange
3. **Filter dust positions** - Remove positions below $1.00 USD value
4. **Update internal state** - Sync with actual exchange state

## Symbol Map

The module includes a comprehensive symbol map for 40+ common trading pairs:

```python
KRAKEN_SYMBOL_MAP = {
    # Major pairs
    "ETH-USD": "ETHUSD",
    "BTC-USD": "BTCUSD",
    "SOL-USD": "SOLUSD",
    "XRP-USD": "XRPUSD",
    "ADA-USD": "ADAUSD",
    # ... and 35+ more pairs
}
```

## Integration Points

### Broker Adapters

The `broker_adapters.py` module's `KrakenAdapter` uses centralized normalization:

```python
# In broker_adapters.py
from bot.kraken_adapter import normalize_kraken_symbol

def normalize_symbol(self, symbol: str) -> str:
    return normalize_kraken_symbol(symbol)
```

### Broker Integration

The `broker_integration.py` module's `KrakenBrokerAdapter` integrates reconciliation:

```python
# In broker_integration.py
from bot.kraken_adapter import (
    normalize_kraken_symbol, is_dust_position,
    reconcile_kraken_position_after_failed_exit
)

# In KrakenBrokerAdapter class:
def _convert_to_kraken_symbol(self, symbol: str) -> str:
    return normalize_kraken_symbol(symbol)

def reconcile_position_after_failed_exit(self, symbol: str, attempted_size: float):
    return reconcile_kraken_position_after_failed_exit(symbol, attempted_size, self)
```

### Copy Trading

The `copy_trade_engine.py` module uses symbol normalization and dust filtering:

```python
# In copy_trade_engine.py
from bot.kraken_adapter import normalize_symbol, is_dust_position

# Normalize symbol for Kraken
if signal.broker.lower() == 'kraken':
    normalized_symbol = normalize_symbol(signal.symbol, 'kraken')

# Check for dust positions
if signal.size_type == 'quote' and is_dust_position(user_size_rounded):
    # Skip copy trade (dust position)
    pass
```

## Error Handling

### Failed Exit Reconciliation

When a SELL order fails, automatic reconciliation is triggered:

```python
# In broker_integration.py
except Exception as e:
    if side.lower() == 'sell':
        try:
            self.reconcile_position_after_failed_exit(symbol, size)
        except Exception as reconcile_err:
            logger.error(f"Position reconciliation error: {reconcile_err}")
```

This ensures:
- Phantom positions are detected and removed
- Internal state matches exchange reality
- Position cap counts are accurate

## Testing

The module includes comprehensive tests in `test_kraken_adapter.py`:

### Test Coverage

1. **Symbol Normalization** (10 test cases)
   - Kraken format (dash and slash separators)
   - Coinbase format (no separator and slash)
   - All tests pass ✅

2. **Dust Detection** (7 test cases)
   - Values below $1.00 (should be dust)
   - Values at $1.00 and above (should track)
   - All tests pass ✅

3. **Position Filtering** (1 test case)
   - Filter 5 positions (2 dust, 3 valid)
   - Correctly removes 2 dust positions
   - Test passes ✅

4. **Symbol Map** (6 test cases)
   - Verify required pairs exist
   - All tests pass ✅

### Running Tests

```bash
cd /home/runner/work/Nija/Nija
python test_kraken_adapter.py
```

Expected output:
```
======================================================================
TEST SUMMARY
======================================================================
✅ ALL TESTS PASSED
```

## Requirements Implemented

Per the problem statement, this module implements:

✅ **1. Kraken symbol normalization** (MANDATORY)
- KRAKEN_SYMBOL_MAP with 40+ pairs
- normalize_symbol(symbol, broker) function
- Integration with broker adapters and broker integration

✅ **2. Forced position reconciliation on failed exits** (STRONGLY RECOMMENDED)
- refresh_positions_from_exchange()
- purge_stale_internal_positions()
- Automatic reconciliation on failed SELL orders

✅ **3. Dust threshold guard** (MANDATORY)
- if usd_value < 1.00: do_not_track_position()
- Prevents phantom positions
- Prevents position cap pollution
- Prevents endless cleanup attempts

## Best Practices

### When to Use Symbol Normalization

Always normalize symbols before:
- Calling Kraken API endpoints
- Storing symbols in databases
- Comparing symbols from different sources
- Copying trades between exchanges

### When to Check for Dust

Always check for dust when:
- Getting positions from exchange
- Copying trades to user accounts
- Calculating position cap
- Deciding whether to track a position

### When to Trigger Reconciliation

Always reconcile after:
- Failed SELL orders (market or limit)
- Failed exit attempts
- Position cap violations
- Suspected phantom positions

## Troubleshooting

### Symbol Not Found Error

If you get "Symbol not found" errors:
1. Check if symbol is in KRAKEN_SYMBOL_MAP
2. Add new pairs to the map if needed
3. Ensure symbol is in correct format before normalization

### Phantom Positions

If you see phantom positions (positions that don't exist):
1. Trigger manual reconciliation
2. Check dust threshold (positions < $1.00 are filtered)
3. Verify exchange API is returning correct data

### Position Cap Issues

If position cap is incorrect:
1. Check for dust positions (should be filtered)
2. Trigger reconciliation to sync with exchange
3. Verify all positions have USD values calculated

## Configuration

No configuration is required. The module uses:
- Fixed dust threshold: $1.00 USD
- Static symbol map: KRAKEN_SYMBOL_MAP
- Automatic reconciliation on failed exits

## Security

✅ Security scan completed: No vulnerabilities found

The module:
- Does not store API keys or secrets
- Does not expose sensitive data
- Uses safe string operations
- Validates all inputs

## Support

For issues or questions:
1. Check this documentation
2. Run test suite to verify functionality
3. Check logs for reconciliation events
4. Review problem statement requirements
