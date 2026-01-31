# Tier Floor Enforcement Implementation Summary

**Date**: January 30, 2026  
**Issue**: Respect the tier floor of 22% for INVESTOR tier  
**Status**: ✅ COMPLETE

## Problem Statement

LOW_CAPITAL mode and fee-aware adjustments could reduce position sizes below the tier-defined MAX_POSITION_PCT. For the INVESTOR tier ($250-999), the maximum position size should be 22%, and this should act as a FLOOR that adjustments cannot reduce below.

**Core Issue**: 
```python
# INCORRECT BEHAVIOR:
# INVESTOR tier has 22% max, but LOW_CAPITAL or quality multipliers
# could reduce it to 15%, 10%, or lower.

# CORRECT BEHAVIOR:
max_position_pct = max(tier_config.MAX_POSITION_PCT, low_capital_max_position_pct)
# Example: max(22%, 15%) = 22%
```

## Solution Implemented

### 1. Updated Tier Configuration

**File**: `bot/tier_config.py` (line 250)

```python
# BEFORE:
'INVESTOR': MasterFundingRules(
    tier=TradingTier.INVESTOR,
    max_trade_size_pct=20.0,  # Max 20% per trade
    # ...
)

# AFTER:
'INVESTOR': MasterFundingRules(
    tier=TradingTier.INVESTOR,
    max_trade_size_pct=22.0,  # Max 22% per trade (tier floor)
    # ...
)
```

### 2. Added Tier Floor Enforcement Logic

**File**: `bot/risk_manager.py` (lines 622-671)

**Key Changes:**

1. **Get tier floor from MASTER_FUNDING_RULES** (not legacy tier config):
```python
from tier_config import MASTER_FUNDING_RULES, get_master_funding_tier

funding_tier_name = get_master_funding_tier(sizing_base)
funding_rules = MASTER_FUNDING_RULES[funding_tier_name]
tier_max_risk_pct = funding_rules.max_trade_size_pct / 100.0  # 0.22 for INVESTOR
```

2. **Store tier floor separately from ceiling**:
```python
tier_floor_pct = tier_max_risk_pct  # 22% for INVESTOR
tier_max_pct = self.max_position_pct  # Allow configured max (e.g., 30%)
```

3. **Enforce floor AFTER all adjustments**:
```python
# After fee-aware sizing, quality multipliers, etc.
if TIER_AWARE_MODE and 'tier_floor_pct' in breakdown:
    tier_floor = breakdown['tier_floor_pct']
    if final_pct < tier_floor:
        logger.info(f"🛡️ TIER FLOOR ENFORCEMENT: Raising {final_pct*100:.1f}% → {tier_floor*100:.1f}%")
        final_pct = tier_floor
        breakdown['tier_floor_enforced'] = True
```

### 3. Updated Documentation

**File**: `bot/micro_capital_config.py` (line 14)

Clarified that the 25% mentioned in comments is for micro capital mode, not INVESTOR tier.

## Benefits

This implementation ensures:

1. **✅ INVESTOR tier respects 22% minimum**
   - Fee-aware adjustments cannot reduce below 22%
   - Quality multipliers cannot reduce below 22%
   - LOW_CAPITAL mode settings cannot reduce below 22%

2. **✅ Meets exchange minimums**
   - INVESTOR tier balance: $250-999
   - 22% of $250 = $55 position (well above Kraken's $10 minimum)
   - 22% of $999 = $219.78 position (optimal for trading)

3. **✅ Prevents risk explosion**
   - Positions won't be too small to handle fees and slippage
   - Maintains meaningful position sizes for the tier

4. **✅ Consistent across all tiers**
   - STARTER: 30% floor
   - SAVER: 25% floor
   - INVESTOR: 22% floor
   - INCOME: 15% floor
   - LIVABLE: 10% floor
   - BALLER: 5% floor

## Test Results

**Manual Testing**: ✅ All tests passed

1. **INVESTOR tier with tier_lock**:
   - Balance: $250, $500, $999
   - All enforced 22% minimum
   - Tier floor enforcement logged correctly

2. **Automatic tier detection**:
   - STARTER ($60): 30% floor enforced
   - SAVER ($150): 25% floor enforced
   - INVESTOR ($400): 22% floor enforced
   - INCOME ($2000): 15% floor enforced

**Code Review**: ✅ No issues found  
**Security Scan (CodeQL)**: ✅ No vulnerabilities detected

## Files Changed

1. `bot/tier_config.py` - Updated INVESTOR max_trade_size_pct to 22%
2. `bot/risk_manager.py` - Added tier floor enforcement logic
3. `bot/micro_capital_config.py` - Updated documentation comment

## Backwards Compatibility

✅ **Fully backwards compatible**

- Existing configurations continue to work
- Only affects tiers where calculated position would be below tier floor
- Master accounts are exempted from tier floors (as before)
- Tier-locked accounts properly enforce tier floors

## Monitoring and Logging

### Startup Logging (Added Jan 31, 2026)

The system now logs all tier floors at startup for immediate visibility:

```
================================================================================
                    TIER FLOOR CONFIGURATION
================================================================================

📊 Tier Floors (Position Size Minimums):
   These floors ensure position sizes don't fall below tier-appropriate levels,
   even with fee-aware adjustments or quality multipliers.

   MICRO_MASTER $25-$50             40.0% floor
   STARTER      $50-$100            30.0% floor
   SAVER        $100-$250           25.0% floor
   INVESTOR     $250-$1000          22.0% floor ← Tier floor fix (Jan 30, 2026)
   INCOME       $1000-$5000         15.0% floor
   LIVABLE      $5000-$25000        10.0% floor
   BALLER       $25,000+             5.0% floor

ℹ️  Tier floors prevent LOW_CAPITAL mode and quality multipliers from
   reducing position sizes below tier-appropriate minimums.
   This ensures exchange minimums are met and prevents undersized positions.
================================================================================
```

This startup logging:
- Appears when `AdaptiveRiskManager` is initialized
- Shows all tier floors in one place for easy verification
- Highlights the INVESTOR tier 22% fix
- Explains the purpose of tier floors
- Helps operators quickly verify correct configuration

### Runtime Logging

During position sizing, tier floor enforcement is logged:

```
📊 Tier INVESTOR: floor=22.0%, ceiling=30.0%
🛡️ TIER FLOOR ENFORCEMENT: Raising 18.5% → 22.0% (tier minimum)
```

This allows easy debugging and verification that tier floors are being respected.

## Enhanced Visibility Features (Added Jan 31, 2026)

Three additional features were added to improve tier floor visibility and production safety:

### 1. Metrics Emission

**Function**: `emit_tier_floor_metrics()` in `tier_config.py`

Emits 21 tier floor metrics to monitoring systems (Prometheus, StatsD, Datadog, etc.):
- Floor percentages (e.g., `nija_tier_floor_investor_pct: 22.0`)
- Capital minimums (e.g., `nija_tier_floor_investor_capital_min: 250.0`)
- Max positions (e.g., `nija_tier_floor_investor_max_positions: 3.0`)

Called once at startup during Risk Manager initialization.

**Use Case**: Monitor tier configuration in production, alert on unexpected changes.

### 2. Production Assertions

**Function**: `assert_expected_tier_floors()` in `tier_config.py`

Validates tier floors match expected values at startup:
```python
expected_floors = {
    'INVESTOR': 22.0,  # CRITICAL: Recent fix from 20% to 22% (Jan 30, 2026)
    # ... other tiers
}
```

- Only runs when `ENVIRONMENT=production`
- Raises `AssertionError` if validation fails
- Provides clear error messages for debugging

**Use Case**: Fail-fast validation that INVESTOR tier is correctly set to 22% before trading starts.

### 3. Dashboard API

**Endpoint**: `GET /api/command-center/tier-floors`

**Function**: `get_tier_floors_for_api()` in `tier_config.py`

Returns JSON with complete tier floor data:
```json
{
  "success": true,
  "data": {
    "tiers": [
      {
        "name": "INVESTOR",
        "capital_range": "$250-$1000",
        "floor_pct": 22.0,
        "max_positions": 3,
        "notes": "Tier floor fix implemented Jan 30, 2026 (20% → 22%)"
      }
    ],
    "generated_at": "2026-01-31T00:08:53.954145",
    "last_modified": "2026-01-30",
    "version": "1.1"
  }
}
```

**Use Case**: Display tier configuration in dashboard UI, allow operators to verify settings.

## Related Documentation

- [TIER_AND_RISK_CONFIG_GUIDE.md](TIER_AND_RISK_CONFIG_GUIDE.md) - Tier configuration guide
- [MICRO_CAPITAL_AUTO_SCALING_GUIDE.md](MICRO_CAPITAL_AUTO_SCALING_GUIDE.md) - Small capital guidance
- [KRAKEN_RATE_PROFILES.md](KRAKEN_RATE_PROFILES.md) - LOW_CAPITAL mode documentation

---

**Implemented by**: GitHub Copilot  
**Dates**: 
- January 30, 2026: Tier floor enforcement
- January 31, 2026: Startup logging, metrics emission, assertions, dashboard API
**PR**: copilot/respect-tier-floor-22-percent
