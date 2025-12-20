# POSITION CLOSING FIX - CRITICAL BUG RESOLVED

## Problem Identified
The bot was **buying crypto but never selling it**, causing capital to get locked up in open positions.

## Root Causes

### 1. **Incorrect Quantity Calculation When Closing**
- **Old code**: Recalculated quantity as `position['size_usd'] / current_price`
- **Problem**: This doesn't account for fees paid during entry
- **Example**:
  - Spend $20 to buy BTC
  - After 3% fee, only receive $19.40 worth of BTC (0.00022 BTC)
  - When selling, bot tried to sell $20 / current_price = wrong amount
  - Coinbase rejected the order (insufficient balance)

### 2. **Missing Size Type Parameter**
- **Old code**: Always used `quote_size` (USD amount) for both buy and sell
- **Problem**: When selling crypto, should use `base_size` (actual crypto amount)
- **Result**: Orders failed because we need to specify exact crypto quantity to sell

### 3. **Not Storing Actual Crypto Received**
- **Old code**: Only stored the USD amount spent (`size_usd`)
- **Problem**: Didn't track the actual crypto received after fees
- **Result**: No way to know exact amount to sell later

## Fixes Applied

### Fix #1: Store Actual Crypto Quantity
**File**: `bot/trading_strategy.py` (lines 669-688)

```python
# NOW STORES:
self.open_positions[symbol] = {
    'side': signal,
    'entry_price': entry_price,
    'size_usd': position_size_usd,
    'crypto_quantity': float(crypto_quantity),  # ← NEW: Actual crypto received
    'timestamp': datetime.now(),
    'stop_loss': stop_loss,
    'take_profit': take_profit,
    ...
}
```

### Fix #2: Use Stored Quantity When Closing
**File**: `bot/trading_strategy.py` (lines 825-835)

```python
# OLD (WRONG):
quantity = position['size_usd'] / current_price

# NEW (CORRECT):
quantity = position.get('crypto_quantity', position['size_usd'] / entry_price)
```

### Fix #3: Use base_size for SELL Orders
**File**: `bot/trading_strategy.py` (line 842)

```python
# NEW: Specify size_type parameter
result = self.broker.place_market_order(
    symbol, 
    exit_signal.lower(), 
    quantity,
    size_type='base' if exit_signal == 'SELL' else 'quote'  # ← KEY FIX
)
```

### Fix #4: Update Broker to Support size_type
**File**: `bot/broker_manager.py` (lines 583-670)

```python
def place_market_order(self, symbol: str, side: str, quantity: float, size_type: str = 'quote'):
    """
    Args:
        size_type: 'quote' for USD amount (default) or 'base' for crypto amount
    """
    ...
    if side.lower() == 'sell':
        if size_type == 'base':
            # Use base_size (crypto amount)
            order = self.client.market_order_sell(
                client_order_id,
                product_id=symbol,
                base_size=str(base_size_rounded)
            )
```

### Fix #5: Extract Filled Size from Response
**File**: `bot/broker_manager.py` (lines 716-725)

```python
# Extract actual crypto received from Coinbase response
filled_size = success_response.get('filled_size')
return {
    "status": "filled", 
    "filled_size": float(filled_size) if filled_size else None
}
```

## Expected Behavior After Fix

### Opening Positions
1. Bot buys $20 worth of BTC
2. Coinbase fills order, returns `filled_size = 0.00022 BTC`
3. Bot stores: `crypto_quantity: 0.00022`

### Closing Positions
1. Bot detects take profit hit
2. Retrieves stored quantity: `0.00022 BTC`
3. Places SELL order with `base_size = 0.00022`
4. Coinbase sells exact amount, returns USD proceeds
5. Position closed, capital freed for next trade

## Testing the Fix

### Manual Liquidation (Free Up Capital Now)
```bash
python3 liquidate_all_crypto.py
```
This will:
- Sell all ATOM, BTC, ETH holdings
- Convert to USD
- Make capital available for bot trading

### Verify Bot Now Closes Positions
After liquidation + deposit to reach $50+:
1. Bot will buy crypto when signals appear
2. Bot will now **automatically sell** when:
   - Stop loss hit (-2%)
   - Take profit hit (+6%)
   - Trailing stop triggered
   - Opposite signal detected

### Check Open Positions
```bash
cat /usr/src/app/data/open_positions.json
```

Should be empty after positions close.

## Impact
- **Before**: Capital locked in crypto → balance drops → bot can't trade
- **After**: Positions close automatically → capital recycled → continuous trading

## Files Changed
1. `/workspaces/Nija/bot/trading_strategy.py` (3 edits)
2. `/workspaces/Nija/bot/broker_manager.py` (3 edits)
3. `/workspaces/Nija/liquidate_all_crypto.py` (new script)

## Next Steps
1. Run liquidation script to free current locked capital
2. Deposit funds to reach $50+ trading balance
3. Restart bot - positions will now close properly
4. Monitor logs to confirm sells execute when profit targets hit
