# NIJA Capital Tier Scaling System - Implementation Guide

## Overview

The NIJA Capital Tier Scaling System solves the core problem of running a trading bot across a wide range of account sizes ($50 → $250k+). This implementation addresses three critical issues:

1. **Over-diversification at small account sizes** (50-60 positions on $50 accounts)
2. **No exposure compression** (small accounts need FEWER, LARGER positions)
3. **No deterministic entry rejection logging** (Unknown reason rejections)

## Architecture

The system consists of four integrated components:

### 1. Capital Tier Hierarchy (`capital_tier_hierarchy.py`)

**Purpose:** Define strict position limits and sizing rules per capital tier.

**Tiers:**

| Tier | Balance Range | Max Positions | Strategy | Position Size |
|------|--------------|---------------|----------|---------------|
| STARTER | $50-99 | 2 | CONCENTRATED | 60-80% |
| SAVER | $100-249 | 3 | CONCENTRATED | 40-50% |
| INVESTOR | $250-999 | 5 | MODERATE | 20-33% |
| INCOME | $1k-4,999 | 7 | MODERATE | 14-20% |
| LIVABLE | $5k-24,999 | 10 | DIVERSIFIED | 10-16% |
| BALLER | $25k+ | 15 | DIVERSIFIED | 6-12% |

**Key Features:**
- Hard caps on position count (not advisory)
- Progressive position limits as capital grows
- Minimum position sizes ensure fee viability
- Dynamic optimal position calculation

**Usage:**
```python
from capital_tier_hierarchy import get_capital_tier_hierarchy

hierarchy = get_capital_tier_hierarchy()

# Get max positions for balance
max_positions = hierarchy.get_max_positions(150.0)  # Returns 3 for SAVER

# Get optimal positions (may be less than max)
optimal = hierarchy.get_optimal_position_count(150.0)  # Returns 1-3

# Calculate target position size
size = hierarchy.calculate_target_position_size(150.0, current_positions=0)

# Validate position
is_valid, code, message = hierarchy.validate_new_position(
    balance=150.0,
    current_position_count=0,
    proposed_size_usd=50.0
)
```

### 2. Exposure Compression Engine (`exposure_compression_engine.py`)

**Purpose:** Allocate capital intelligently based on signal quality and tier.

**Compression Strategy:**
- Small accounts: 80% in top signal (concentration)
- Medium accounts: 20-30% in top 3-5 signals (moderate)
- Large accounts: 10-13% in top 10-15 signals (diversification)

**Concentration Scores:**
- STARTER: 0.68 (ultra-concentrated)
- SAVER: 0.38 (high concentration)
- INVESTOR: 0.25 (moderate)
- INCOME: 0.15 (balanced)
- LIVABLE: 0.10 (diversified)
- BALLER: 0.06 (full diversification)

**Key Features:**
- Ranks signals by quality score
- Applies tier-specific allocation curves
- Validates allocations meet minimum sizes
- Supports rebalancing when needed

**Usage:**
```python
from exposure_compression_engine import get_exposure_compression_engine

engine = get_exposure_compression_engine()

# Create signals with quality scores
signals = [
    {'symbol': 'BTC-USD', 'signal_type': 'LONG', 'quality_score': 85.0},
    {'symbol': 'ETH-USD', 'signal_type': 'LONG', 'quality_score': 78.0},
    # ...
]

# Allocate capital
allocations = engine.allocate_capital(
    balance=150.0,
    tier_name='SAVER',
    signals=signals,
    max_positions=3
)

# Each allocation has: symbol, allocated_usd, allocated_pct, rank
for alloc in allocations:
    print(f"{alloc.symbol}: ${alloc.allocated_usd:.2f} ({alloc.allocated_pct*100:.1f}%)")
```

### 3. Deterministic Entry Validator (`deterministic_entry_validator.py`)

**Purpose:** Validate entries with explicit rejection codes (no more "unknown reason").

**Rejection Codes:**
- `TIER_MAX_POSITIONS` - At tier position limit
- `TIER_POSITION_SIZE_TOO_SMALL` - Below tier minimum
- `TIER_POSITION_SIZE_TOO_LARGE` - Exceeds tier maximum
- `INSUFFICIENT_CAPITAL` - Not enough available capital
- `BALANCE_TOO_LOW` - Account below trading minimum
- `EXCHANGE_MINIMUM_NOT_MET` - Below exchange minimum
- `SIGNAL_QUALITY_LOW` - Signal quality too low
- `SIGNAL_CONFIDENCE_LOW` - Confidence too low
- `COOLDOWN_ACTIVE` - Trading paused
- `MAX_DAILY_TRADES` - Daily limit reached
- `DRAWDOWN_HALT` - Drawdown protection active
- `MARKET_CLOSED` - Market not open
- `SYMBOL_RESTRICTED` - Symbol restricted
- `SYMBOL_BLACKLISTED` - Symbol blacklisted
- `DUPLICATE_POSITION` - Position already exists
- `VALIDATION_PASSED` - Entry approved

**8-Gate Validation:**
1. Account State (balance, tier)
2. Capital Availability (sufficient funds)
3. Position Limits (tier max positions)
4. Position Size (tier and exchange minimums)
5. Signal Quality (quality and confidence thresholds)
6. Trading State (cooldowns, limits, drawdowns)
7. Market/Symbol (restrictions, blacklists)
8. Position Conflicts (duplicates, opposing)

**Usage:**
```python
from deterministic_entry_validator import (
    get_entry_validator,
    ValidationContext
)

validator = get_entry_validator()

# Create validation context
context = ValidationContext(
    balance=150.0,
    tier_name='SAVER',
    current_position_count=1,
    open_positions=['ETH-USD'],
    available_capital=120.0,
    symbol='BTC-USD',
    signal_type='LONG',
    signal_quality=75.0,
    signal_confidence=0.70,
    proposed_size_usd=50.0,
    exchange_name='coinbase'
)

# Validate
result = validator.validate_entry(context)

if result.passed:
    print(f"✅ Entry approved: {result.rejection_message}")
else:
    print(f"❌ {result.rejection_code.value}: {result.rejection_message}")
```

### 4. Tier-Aware Position Manager (`tier_aware_position_manager.py`)

**Purpose:** Integration layer that coordinates all components.

**Key Features:**
- Unified interface for tier-based position management
- Coordinates tier hierarchy, compression, and validation
- Maintains backward compatibility
- Provides convenience functions

**Usage:**
```python
from tier_aware_position_manager import get_tier_aware_position_manager

manager = get_tier_aware_position_manager()

# Update balance (tracks tier changes)
manager.update_balance(150.0)

# Get tier info
info = manager.get_tier_info(150.0)
print(f"Tier: {info['tier']}, Max Positions: {info['max_positions']}")

# Calculate position size
size = manager.calculate_tier_aware_position_size(
    balance=150.0,
    current_position_count=1
)

# Validate new position
result = manager.validate_new_position(
    balance=150.0,
    current_position_count=1,
    proposed_size=50.0,
    symbol='BTC-USD',
    signal_quality=75.0
)

# Log tier summary
manager.log_tier_summary(150.0, current_positions=1)
```

## Integration with Existing Code

### Step 1: Update Risk Manager

Modify `risk_manager.py` to use tier hierarchy:

```python
from tier_aware_position_manager import get_tier_aware_position_manager

# In AdaptiveRiskManager.__init__:
self.tier_manager = get_tier_aware_position_manager()

# In calculate_position_size:
# Get tier-aware position count limit
max_positions = self.tier_manager.get_max_positions(account_balance)

# Check if at max positions
if current_positions >= max_positions:
    logger.warning(f"At maximum positions ({current_positions}/{max_positions})")
    return (0.0, {'tier_max_reached': True})

# Calculate tier-aware size
tier_size = self.tier_manager.calculate_tier_aware_position_size(
    account_balance,
    current_positions
)
```

### Step 2: Update Entry Logic

Modify entry validation in strategy files:

```python
from tier_aware_position_manager import should_allow_new_position

# Before opening position:
allowed, rejection_code, rejection_message = should_allow_new_position(
    balance=account_balance,
    current_positions=len(open_positions),
    proposed_size=position_size,
    symbol=symbol,
    signal_quality=entry_score
)

if not allowed:
    logger.warning(f"Entry rejected: {rejection_code} - {rejection_message}")
    return False  # Skip entry
```

### Step 3: Add Tier Logging at Startup

```python
from tier_aware_position_manager import get_tier_aware_position_manager

# In bot startup:
manager = get_tier_aware_position_manager()
manager.update_balance(current_balance)
manager.log_tier_summary(current_balance, len(open_positions))
```

## Testing

Run the comprehensive test suite:

```bash
cd bot
python test_capital_scaling.py
```

Expected output:
```
✅ TEST 1 PASSED: Tier progression working correctly
✅ TEST 2 PASSED: Exposure compression working correctly
✅ TEST 3 PASSED: Entry validation working correctly
✅ TEST 4 PASSED: Integrated scaling working correctly
✅ TEST 5 PASSED: Rejection logging is clear and deterministic

🎉 ALL TESTS PASSED - CAPITAL SCALING SYSTEM OPERATIONAL
```

## Behavior Changes

### Before Implementation

**Problem:**
- $50 account with 50-60 positions = $1 per position
- Below exchange minimums
- Unprofitable after fees
- "Unknown reason" rejections
- No capital hierarchy

**Example:**
```
Balance: $60
Positions: 58
Average Position: $1.03
Result: Most positions rejected, unclear why
```

### After Implementation

**Solution:**
- $50 account with MAX 2 positions = $25-40 per position
- Above exchange minimums
- Profitable after fees
- Explicit rejection codes
- Clear tier-based limits

**Example:**
```
Balance: $60
Tier: STARTER
Max Positions: 2
Position 1: BTC-USD $48.00 (80%)
Position 2: ETH-USD $12.00 (20%)
Result: Both positions valid and profitable
```

## Scaling Examples

### $50 Account (STARTER)
- Max Positions: 2
- Strategy: CONCENTRATED
- Position 1: $40 (80%)
- Position 2: $10 (20%)
- Focus: Best 1-2 signals only

### $500 Account (INVESTOR)
- Max Positions: 5
- Strategy: MODERATE
- Position 1: $150 (30%)
- Position 2: $150 (30%)
- Position 3: $100 (20%)
- Position 4: $75 (15%)
- Position 5: $25 (5%)
- Focus: Top 5 signals, concentrated in top 2

### $50,000 Account (BALLER)
- Max Positions: 15
- Strategy: DIVERSIFIED
- Position 1-2: $5,000 each (10%)
- Position 3-4: $4,500 each (9%)
- Position 5-7: $4,000 each (8%)
- Position 8-10: $3,500 each (7%)
- Position 11-15: $2,000-3,000 each (4-6%)
- Focus: Diversified across top 15 signals

## Performance Impact

### Entry Rejection Clarity
- Before: "Unknown reason" → Cannot debug
- After: "TIER_MAX_POSITIONS: Tier STARTER allows maximum 2 positions (current: 2)" → Clear and actionable

### Position Count Control
- Before: No limit → 50-60 positions on small accounts
- After: Tier-based limits → 2-15 positions based on capital

### Capital Efficiency
- Before: $50 split 50 ways → Unusable
- After: $50 split 2 ways → Profitable

### Fee Impact
- Before: $1 positions with $0.15 fees = 15% fee drag
- After: $25 positions with $0.15 fees = 0.6% fee drag

## Monitoring & Metrics

### Tier Metrics
```python
# Get validation statistics
stats = manager.get_entry_rejection_stats()
print(f"Total validations: {stats['total']}")
print(f"Pass rate: {stats['pass_rate']:.1f}%")
print(f"Rejections by code: {stats['rejection_by_code']}")
```

### Expected Metrics
- Pass rate: 50-70% (expected - quality filter working)
- Top rejection: TIER_MAX_POSITIONS (expected - position limits working)
- Zero "unknown reason" rejections (required)

## Rollback Plan

If issues arise, disable tier-aware features:

```python
# In tier_aware_position_manager.py, set to False:
TIER_HIERARCHY_AVAILABLE = False
EXPOSURE_COMPRESSION_AVAILABLE = False
ENTRY_VALIDATOR_AVAILABLE = False

# System will use fallback logic
```

## Future Enhancements

1. **Dynamic Tier Adjustment**: Adjust tier thresholds based on market conditions
2. **User-Configurable Limits**: Allow users to set custom tier limits
3. **Tier-Specific Strategies**: Different trading strategies per tier
4. **Performance Tracking**: Track performance metrics per tier
5. **Graduation System**: Automatic tier upgrades with confirmation

## Support & Troubleshooting

### Common Issues

**Issue:** Positions rejected with TIER_MAX_POSITIONS
- **Cause:** At maximum positions for tier
- **Solution:** Wait for position to close or increase capital

**Issue:** Positions rejected with TIER_POSITION_SIZE_TOO_SMALL
- **Cause:** Calculated size below tier minimum
- **Solution:** Increase balance or wait for better signal

**Issue:** High rejection rate
- **Cause:** Expected behavior - system is filtering aggressively
- **Solution:** This is correct - small accounts should be selective

### Debug Logging

Enable debug logging:
```python
import logging
logging.getLogger('nija.capital_tier_hierarchy').setLevel(logging.DEBUG)
logging.getLogger('nija.exposure_compression').setLevel(logging.DEBUG)
logging.getLogger('nija.entry_validator').setLevel(logging.DEBUG)
```

## Conclusion

The NIJA Capital Tier Scaling System provides:

✅ **Clear Capital Hierarchy** - Defined tiers from $50 to $250k+
✅ **Exposure Compression** - Concentrated → Diversified as capital grows  
✅ **Deterministic Validation** - Explicit rejection codes (no more "unknown")
✅ **Position Limits** - Hard caps prevent over-diversification
✅ **Profitability Focus** - Minimum sizes ensure fee viability

The system is production-ready and fully tested across all tiers.
