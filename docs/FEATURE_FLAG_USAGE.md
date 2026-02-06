# Feature Flag Usage Guide

## Overview

NIJA uses a centralized feature flag system that allows safe progressive rollout and easy toggling of features. This guide explains how to use and add feature flags.

## Using the PROFIT_CONFIRMATION Feature Flag

### Option A: Import from config/feature_flags.py (Recommended)

This is the recommended approach as specified in the problem statement. It defines flags globally and explicitly in a centralized location.

```python
from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE

# Use in your code
if PROFIT_CONFIRMATION_AVAILABLE:
    # Use profit confirmation logging
    profit_logger = ProfitConfirmationLogger()
    profit_logger.log_profit_confirmation(...)
else:
    # Skip profit confirmation (lightweight mode)
    pass
```

**Benefits:**
- ✅ Explicit - Clear global definition
- ✅ Testable - Easy to mock and test
- ✅ Toggleable - Can be changed via environment variable

### Option B: Use bot/feature_flags.py Infrastructure

For runtime-controlled flags that integrate with the full feature flag system:

```python
from bot.feature_flags import FeatureFlag, is_feature_enabled

# Check if feature is enabled
if is_feature_enabled(FeatureFlag.PROFIT_CONFIRMATION):
    # Feature is enabled
    profit_logger = ProfitConfirmationLogger()
    profit_logger.log_profit_confirmation(...)
```

**Benefits:**
- ✅ Runtime control via environment variables
- ✅ Centralized management with logging
- ✅ Integration with feature flag dashboard

## Environment Variable Control

You can control the PROFIT_CONFIRMATION feature flag via environment variable:

```bash
# Enable profit confirmation (default)
FEATURE_PROFIT_CONFIRMATION=true

# Disable profit confirmation
FEATURE_PROFIT_CONFIRMATION=false
```

Add this to your `.env` file or set it in your deployment environment.

## Default Behavior

- **Default State:** Enabled (True)
- **Rationale:** Profit confirmation is a core feature for production trading and should be enabled by default

## Adding New Feature Flags

### 1. Define in config/feature_flags.py

```python
# Add to config/feature_flags.py
NEW_FEATURE_AVAILABLE = True  # or False for default off
```

### 2. Add to bot/feature_flags.py Enum

```python
# Add to FeatureFlag enum in bot/feature_flags.py
class FeatureFlag(Enum):
    # ... existing flags ...
    NEW_FEATURE = "new_feature"
```

### 3. Set Default Value

```python
# Add to defaults dict in _load_flags method
defaults = {
    # ... existing defaults ...
    FeatureFlag.NEW_FEATURE: False,  # Default state
}
```

### 4. Document in .env.example

```bash
# Add to FEATURE FLAGS section in .env.example
# NEW_FEATURE - Description of what it does
# Default: false
# FEATURE_NEW_FEATURE=false
```

### 5. Use in Code

```python
from config.feature_flags import NEW_FEATURE_AVAILABLE
# or
from bot.feature_flags import FeatureFlag, is_feature_enabled

if NEW_FEATURE_AVAILABLE:  # Option A
    # Use feature
    pass

if is_feature_enabled(FeatureFlag.NEW_FEATURE):  # Option B
    # Use feature
    pass
```

## Testing Feature Flags

Feature flags should be tested to ensure they work correctly:

```python
import unittest
from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
from bot.feature_flags import FeatureFlag, is_feature_enabled

class TestMyFeatureFlag(unittest.TestCase):
    def test_flag_is_defined(self):
        # Test the global constant exists
        self.assertIsInstance(PROFIT_CONFIRMATION_AVAILABLE, bool)
    
    def test_flag_can_be_toggled(self):
        # Test environment variable control
        import os
        os.environ['FEATURE_PROFIT_CONFIRMATION'] = 'false'
        # ... test with flag disabled
        
        os.environ['FEATURE_PROFIT_CONFIRMATION'] = 'true'
        # ... test with flag enabled
```

See `bot/tests/test_profit_confirmation_feature_flag.py` for complete examples.

## Best Practices

### 1. Safe Defaults

- **New features:** Default to OFF (False)
- **Production features:** Default to ON (True) if critical
- **Safety features:** LOCKED ON (cannot be disabled)

### 2. Feature Flag Lifecycle

1. **Development:** Feature flag OFF by default
2. **Testing:** Enable via environment variable for specific environments
3. **Gradual Rollout:** Enable for subset of users/accounts
4. **Full Release:** Update default to ON
5. **Cleanup:** After proven stable, consider removing flag and making it permanent

### 3. Documentation

Always document:
- What the feature does
- Why it's behind a flag
- Default state and rationale
- How to enable/disable it

### 4. Never Remove Safety Features

Some features should NEVER be disabled:
- `PROFITABILITY_ASSERTION` - Always ON (LOCKED)
- `STOP_LOSS_VALIDATION` - Always ON (LOCKED)

These are implemented in the `is_enabled` method to always return True regardless of configuration.

## Troubleshooting

### Flag Not Taking Effect

1. Check environment variable is set correctly:
   ```bash
   echo $FEATURE_PROFIT_CONFIRMATION
   ```

2. Verify syntax (case-sensitive):
   ```bash
   FEATURE_PROFIT_CONFIRMATION=true  # Correct
   FEATURE_PROFIT_CONFIRMATION=True  # Will work (case-insensitive)
   FEATURE_PROFIT_CONFIRMATION=1     # Will work
   ```

3. Restart application after changing environment variables

4. Check logs for feature flag initialization:
   ```
   🚩 Feature Flags Loaded:
     profit_confirmation: ✅ ENABLED
   ```

### Flag Not Found

If you get "KeyError" or "AttributeError":

1. Ensure flag is added to BOTH locations:
   - `config/feature_flags.py` (global constant)
   - `bot/feature_flags.py` (enum and defaults)

2. Check spelling matches exactly

3. Ensure you've imported from the correct module

## Examples

### Example 1: Using PROFIT_CONFIRMATION

```python
from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
from bot.profit_confirmation_logger import ProfitConfirmationLogger

class TradingBot:
    def __init__(self):
        self.profit_logger = None
        if PROFIT_CONFIRMATION_AVAILABLE:
            self.profit_logger = ProfitConfirmationLogger()
    
    def close_position(self, symbol, profit_pct, profit_usd):
        # Always log trade closure
        logger.info(f"Closed {symbol} with {profit_pct:.2f}% profit")
        
        # Optionally track profit confirmation
        if self.profit_logger:
            self.profit_logger.log_profit_confirmation(
                symbol=symbol,
                net_profit_pct=profit_pct,
                net_profit_usd=profit_usd,
                # ... other params
            )
```

### Example 2: Runtime Toggle

```python
from bot.feature_flags import FeatureFlag, get_feature_flags

# Get feature flag manager
flags = get_feature_flags()

# Check current state
if flags.is_enabled(FeatureFlag.PROFIT_CONFIRMATION):
    print("Profit confirmation is enabled")

# Emergency disable (runtime control)
if emergency_condition:
    flags.disable(FeatureFlag.PROFIT_CONFIRMATION)
```

### Example 3: Testing with Flags

```python
import unittest
import os

class TestProfitConfirmation(unittest.TestCase):
    def test_with_flag_enabled(self):
        os.environ['FEATURE_PROFIT_CONFIRMATION'] = 'true'
        # Test code that uses profit confirmation
        
    def test_with_flag_disabled(self):
        os.environ['FEATURE_PROFIT_CONFIRMATION'] = 'false'
        # Test code works without profit confirmation
```

## Summary

The NIJA feature flag system provides:

1. **Explicit Definition:** Flags defined in `config/feature_flags.py`
2. **Testable:** Easy to write unit tests
3. **Toggleable:** Control via environment variables
4. **Safe:** Defaults protect production systems
5. **Flexible:** Choose between global constants or runtime control

For the PROFIT_CONFIRMATION feature specifically, use:

```python
from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
```

This follows **Option A (Recommended)** from the implementation guidelines, providing explicit, testable, and toggleable feature flag control.
