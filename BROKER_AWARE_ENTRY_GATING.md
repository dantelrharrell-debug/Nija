# Broker-Aware Entry Gating Implementation

## Problem Statement

NIJA was checking "can I trade?" globally instead of asking "WHERE am I allowed to trade?"

This caused issues where:
- BUY orders were attempted on brokers in EXIT_ONLY mode
- Misleading "ALL CONDITIONS PASSED" messages didn't specify which broker
- Coinbase with balance < $25 would still be selected for trading
- No prioritization of brokers based on fees or eligibility

## Solution Implemented

### 1. Broker Priority System

Added explicit broker priority for entry (BUY) orders:
```python
ENTRY_BROKER_PRIORITY = [
    BrokerType.KRAKEN,      # Priority 1: Lowest fees (0.36%)
    BrokerType.OKX,         # Priority 2: Low fees
    BrokerType.BINANCE,     # Priority 3: Low fees
    BrokerType.COINBASE,    # Priority 4: Highest fees (1.4%)
]
```

### 2. Broker-Specific Balance Requirements

```python
BROKER_MIN_BALANCE = {
    BrokerType.COINBASE: 25.0,  # $25 minimum
    BrokerType.KRAKEN: 25.0,    # $25 minimum
    BrokerType.OKX: 10.0,       # $10 minimum
    BrokerType.BINANCE: 10.0,   # $10 minimum
}
```

### 3. Broker Eligibility Checks

Before attempting any BUY order, the system now checks:

1. **Is the broker connected?**
   - If no → skip this broker

2. **Is the broker in EXIT_ONLY mode?**
   - If yes → skip this broker (can only SELL, not BUY)

3. **Does the account balance meet minimum threshold?**
   - If no → skip this broker

### 4. Broker Selection Flow

```
┌─────────────────────────────────────────┐
│ Start: Need to place BUY order         │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ Check KRAKEN (Priority 1)               │
│ - Connected? Yes                        │
│ - EXIT_ONLY? No                         │
│ - Balance >= $25? Yes                   │
│ ✅ ELIGIBLE → Use KRAKEN                │
└─────────────────────────────────────────┘

         OR if KRAKEN ineligible
                 │
                 v
┌─────────────────────────────────────────┐
│ Check OKX (Priority 2)                  │
│ - Connected? Yes                        │
│ - EXIT_ONLY? No                         │
│ - Balance >= $10? No                    │
│ ❌ INELIGIBLE → Try next                │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ Check BINANCE (Priority 3)              │
│ - Connected? Yes                        │
│ - EXIT_ONLY? Yes (EXIT-ONLY mode)       │
│ ❌ INELIGIBLE → Try next                │
└────────────────┬────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────┐
│ Check COINBASE (Priority 4)             │
│ - Connected? Yes                        │
│ - EXIT_ONLY? No                         │
│ - Balance >= $25? Yes                   │
│ ✅ ELIGIBLE → Use COINBASE              │
└─────────────────────────────────────────┘

         OR if all ineligible
                 │
                 v
┌─────────────────────────────────────────┐
│ NO ELIGIBLE BROKER                      │
│ → Skip market scan                      │
│ → Log reasons for each broker           │
└─────────────────────────────────────────┘
```

### 5. Improved Logging

**Before:**
```
🟢 RESULT: ALL CONDITIONS PASSED - WILL SCAN MARKETS FOR TRADES
```

**After:**
```
🏦 BROKER ELIGIBILITY CHECK:
   ✅ KRAKEN: Eligible
   ❌ OKX: Not configured
   ❌ BINANCE: BINANCE in EXIT-ONLY mode
   ❌ COINBASE: COINBASE balance $20.00 < $25.00 minimum

✅ Selected KRAKEN for entry (priority: 1)
🟢 RESULT: CONDITIONS PASSED FOR KRAKEN
```

Or when no broker is eligible:
```
🏦 BROKER ELIGIBILITY CHECK:
   ❌ KRAKEN: KRAKEN balance $15.00 < $25.00 minimum
   ⚪ OKX: Not configured
   ❌ BINANCE: BINANCE in EXIT-ONLY mode
   ❌ COINBASE: COINBASE in EXIT-ONLY mode

🔴 RESULT: CONDITIONS FAILED - SKIPPING MARKET SCAN
   Reasons: No eligible broker for entry (all in EXIT_ONLY or below minimum balance)
```

## Key Features

### ✅ Prevents BUY on EXIT_ONLY Brokers

If a broker is in EXIT_ONLY mode (balance below minimum, manual shutdown, etc.):
- **SELL orders**: ✅ Allowed (capital preservation)
- **BUY orders**: ❌ Blocked (automatically skipped)

### ✅ Coinbase Auto-Downgrade

If Coinbase balance < $25:
- Automatically falls to lowest priority
- Other brokers with sufficient balance are selected first
- Prevents unprofitable trades due to high fees

### ✅ Multi-Broker Optimization

Prioritizes brokers with:
1. Lower fees (Kraken 0.36% vs Coinbase 1.4%)
2. Sufficient balance for minimum position size
3. Active trading mode (not EXIT_ONLY)

### ✅ Clear Visibility

Logs show exactly:
- Which broker was selected
- Why each broker was eligible/ineligible
- What action the bot will take

## Code Changes

### Files Modified
- `bot/trading_strategy.py` - Main implementation

### New Methods
- `_is_broker_eligible_for_entry(broker)` - Check if broker can accept BUY orders
- `_select_entry_broker(all_brokers)` - Select best broker from priority list

### New Constants
- `ENTRY_BROKER_PRIORITY` - Priority order for broker selection
- `BROKER_MIN_BALANCE` - Minimum balance requirements per broker

### Tests Added
- `bot/tests/test_broker_entry_gating.py` - Comprehensive test suite
  - Broker eligibility checking
  - Priority selection
  - Coinbase auto-downgrade
  - EXIT_ONLY mode handling

## Testing

All tests pass successfully:
```bash
$ python bot/tests/test_broker_entry_gating.py

======================================================================
TEST 1: Broker Eligibility Checking
======================================================================
✓ Test 1a: Eligible broker - True, Reason: Eligible
✓ Test 1b: EXIT_ONLY mode - False, Reason: COINBASE in EXIT-ONLY mode
✓ Test 1c: Insufficient balance - False, Reason: COINBASE balance $10.00 < $25.00 minimum
✓ Test 1d: Not connected - False, Reason: KRAKEN not connected
✅ All eligibility tests passed!

======================================================================
TEST 2: Broker Priority Selection
======================================================================
✓ Test 2a: Multiple eligible brokers - Selected: kraken
✓ Test 2b: KRAKEN EXIT_ONLY - Selected: binance
✓ Test 2c: COINBASE as fallback - Selected: coinbase
✓ Test 2d: No eligible broker - Selected: None
✅ All priority selection tests passed!

======================================================================
TEST 3: Coinbase Auto-Downgrade
======================================================================
✓ Test 3a: Coinbase balance $20 - False, Reason: COINBASE balance $20.00 < $25.00 minimum
✓ Test 3b: Coinbase balance $30 - True, Reason: Eligible
✓ Test 3c: Kraken $50 vs Coinbase $20 - Selected: kraken
✅ All Coinbase auto-downgrade tests passed!

======================================================================
✅ ALL TESTS PASSED!
======================================================================
```

## Security

- CodeQL scan: ✅ No vulnerabilities detected
- Type safety: ✅ Proper type annotations added
- Error handling: ✅ Graceful fallbacks for all edge cases

## Backward Compatibility

- ✅ Single-broker setups continue to work
- ✅ Existing broker selection logic preserved
- ✅ No breaking changes to API or configuration

## Impact

### Before
- Global "can I trade?" check
- BUY orders attempted on EXIT_ONLY brokers
- No broker prioritization
- Unclear logging

### After
- Broker-specific "WHERE can I trade?" check
- BUY orders skip EXIT_ONLY brokers
- Priority-based broker selection
- Clear, actionable logging

## Summary

This implementation fixes the core issue identified in the problem statement by:
1. ✅ Checking broker eligibility BEFORE attempting BUY orders
2. ✅ Selecting brokers based on priority and eligibility
3. ✅ Auto-downgrading underfunded brokers (Coinbase < $25)
4. ✅ Providing clear, broker-specific logging

The bot now asks "WHERE am I allowed to trade?" instead of "can I trade?" globally.
