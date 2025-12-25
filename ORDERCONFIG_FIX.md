# Fix Summary: OrderConfiguration AttributeError

## Problem
The NIJA bot was experiencing repeated failures with the error:
```
AttributeError: 'OrderConfiguration' object has no attribute 'get'
```

This occurred when trying to place buy/sell orders through the Coinbase API.

## Root Cause
The Coinbase Advanced Trade Python SDK (`coinbase-advanced-py`) returns complex response objects (like `OrderConfiguration`) instead of plain dictionaries. 

The bot's code was attempting to convert these objects using `order.__dict__`, which:
1. Returns the object's internal dictionary
2. Contains nested objects (e.g., `OrderConfiguration` instances)
3. These nested objects don't have a `.get()` method
4. Calling `.get()` on them caused AttributeError

Example of the problematic code:
```python
# BROKEN: Creates a dict with nested objects that aren't dicts
order_dict = order if isinstance(order, dict) else (
    order.__dict__ if hasattr(order, '__dict__') else {}
)

# FAILS: Tries to call .get() on OrderConfiguration object
success = order_dict.get('success', True)  # ❌ AttributeError
```

## Solution
Added a helper function `_serialize_object_to_dict()` that:
1. Uses `json.dumps()` with `default=str` to recursively serialize all nested objects
2. Falls back to recursive attribute extraction if JSON fails
3. Returns a true dictionary that supports `.get()` method

Example of the fix:
```python
# FIXED: Safely serialize all nested objects to primitive types
order_dict = _serialize_object_to_dict(order)

# NOW WORKS: order_dict is a true dict
success = order_dict.get('success', True)  # ✅ Works!
```

## Files Modified

### 1. **bot/broker_manager.py** (Primary fix)
- Added `_serialize_object_to_dict()` helper function at module level
- Updated `place_market_order()` method (line ~919) to use the helper
- Now all Coinbase API responses are properly serialized

### 2. **liquidate_all_crypto.py**
- Applied inline serialization logic for order response handling

### 3. **find_and_sell_crypto.py**
- Applied inline serialization logic for order response handling

### 4. **direct_sell.py**
- Applied inline serialization logic for order response handling

### 5. **sell_now_auto.py**
- Applied inline serialization logic for order response handling

## Testing
Created `test_serialization.py` to verify the serialization function works correctly with mock Coinbase objects.

## Impact
- ✅ Orders will now place successfully
- ✅ Error responses will be properly parsed
- ✅ No more AttributeError on nested Coinbase objects
- ✅ Cleaner, more maintainable code

## What's NOT Fixed
This fix addresses the technical issue with order placement. However:
- The bot still cannot trade with only $5.90 (insufficient capital)
- User needs to deposit funds to Advanced Trade portfolio
- Minimum viable capital is $15-20 for fee-aware profitability
