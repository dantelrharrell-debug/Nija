# Migration Guide: Transitioning to Elite-Tier Nonce Manager

## Overview

This guide helps developers migrate from legacy nonce management systems to the new Elite-Tier Centralized Kraken Nonce Manager.

## Background

Previously, NIJA used multiple nonce generation systems:

1. **GlobalKrakenNonceManager** (bot/global_kraken_nonce.py) - Current system
2. **UserNonceManager** (bot/user_nonce_manager.py) - Per-user file-based ❌ DEPRECATED
3. **KrakenNonce** (bot/kraken_nonce.py) - Per-user class ❌ DEPRECATED  
4. **get_kraken_nonce()** (bot/broker_manager.py) - Legacy function ⚠️ FALLBACK ONLY

This fragmentation caused:
- Potential nonce collisions during startup
- Inconsistent nonce precision (ms vs ns)
- Harder to debug and maintain
- No centralized burst protection

## Current State (After Elite-Tier Implementation)

✅ **Primary System:** GlobalKrakenNonceManager
- Nanosecond precision (19 digits)
- Thread-safe atomic operations
- Startup burst protection
- File persistence
- Comprehensive metrics

✅ **Already Updated:**
- `bot/broker_integration.py` - Uses global nonce manager ✅
- `bot/broker_manager.py` - Prefers global nonce manager, fallback to legacy ⚠️
- `bot/kraken_copy_trading.py` - Uses global nonce manager ✅

⚠️ **Needs Migration:**
- `bot/dashboard_server.py` - Uses UserNonceManager
- `bot/user_dashboard_api.py` - Uses UserNonceManager
- Any custom code using KrakenNonce directly

## Migration Steps

### Step 1: Identify Legacy Usage

Search your codebase for legacy imports:

```bash
# Find UserNonceManager usage
grep -r "from.*user_nonce_manager" . --include="*.py"

# Find KrakenNonce usage  
grep -r "from.*kraken_nonce import KrakenNonce" . --include="*.py"

# Find legacy get_kraken_nonce calls
grep -r "get_kraken_nonce(" . --include="*.py"
```

### Step 2: Update Imports

**Before (UserNonceManager):**
```python
from bot.user_nonce_manager import get_user_nonce_manager

manager = get_user_nonce_manager()
nonce = manager.get_nonce(user_id)
```

**After (GlobalKrakenNonceManager):**
```python
from bot.global_kraken_nonce import get_global_nonce_manager

# Note: No user_id needed - single global nonce for all users
manager = get_global_nonce_manager()
nonce = manager.get_nonce()
```

---

**Before (KrakenNonce):**
```python
from bot.kraken_nonce import KrakenNonce

nonce_gen = KrakenNonce()
nonce = nonce_gen.next()
```

**After (GlobalKrakenNonceManager):**
```python
from bot.global_kraken_nonce import get_global_nonce_manager

nonce = get_global_nonce_manager().get_nonce()
```

---

**Before (Legacy get_kraken_nonce):**
```python
from bot.broker_manager import get_kraken_nonce

nonce = get_kraken_nonce(account_identifier)
```

**After (GlobalKrakenNonceManager):**
```python
from bot.global_kraken_nonce import get_global_kraken_nonce

# Note: No account_identifier needed - single global nonce
nonce = get_global_kraken_nonce()
```

### Step 3: Add API Lock (If Making Kraken API Calls)

All Kraken API calls MUST use the global lock to prevent parallel execution:

```python
from bot.global_kraken_nonce import (
    get_global_nonce_manager,
    get_kraken_api_lock
)

# Get the global API lock
lock = get_kraken_api_lock()

# Always wrap Kraken API calls with the lock
with lock:
    nonce = get_global_nonce_manager().get_nonce()
    
    # Make your Kraken API call
    result = kraken_api.query_private('AddOrder', {
        'nonce': nonce,
        # ... other parameters
    })
```

### Step 4: Remove Per-User Logic

The Elite-Tier system uses ONE global nonce for ALL users. Remove any per-user nonce tracking:

**Before:**
```python
# DON'T DO THIS - per-user tracking is unnecessary
user_nonces = {}
for user_id in users:
    user_nonces[user_id] = get_user_nonce(user_id)
```

**After:**
```python
# ONE global nonce for all operations
nonce = get_global_nonce_manager().get_nonce()

# Use the same nonce for all users if needed in parallel
# (Though parallel calls are prevented by the global lock)
```

### Step 5: Update Tests

**Before:**
```python
def test_user_nonce():
    manager = UserNonceManager()
    nonce1 = manager.get_nonce("user1")
    nonce2 = manager.get_nonce("user2")
    # Test per-user isolation
```

**After:**
```python
def test_global_nonce():
    manager = get_global_nonce_manager()
    nonce1 = manager.get_nonce()
    nonce2 = manager.get_nonce()
    # Test global monotonic increase
    assert nonce2 > nonce1
```

## Specific File Migrations

### bot/dashboard_server.py

**Current Code:**
```python
try:
    from user_nonce_manager import get_user_nonce_manager
    ...
except ImportError:
    get_user_nonce_manager = None
```

**Recommended Change:**
```python
try:
    from bot.global_kraken_nonce import get_global_nonce_manager
    ...
except ImportError:
    get_global_nonce_manager = None

# If you need user-specific functionality, use other means
# The nonce is now global and shared
```

### bot/user_dashboard_api.py

**Current Code:**
```python
from bot.user_nonce_manager import get_user_nonce_manager

manager = get_user_nonce_manager()
stats = manager.get_stats(user_id)
```

**Recommended Change:**
```python
from bot.global_kraken_nonce import (
    get_global_nonce_manager,
    get_global_nonce_stats
)

# Get global stats (not per-user)
stats = get_global_nonce_stats()

# If you need user-specific stats, track them separately
# The nonce manager itself is now global
```

## Breaking Changes

### 1. No More Per-User Nonces

**Impact:** All users share one global nonce sequence

**Reason:** Kraken requires monotonically increasing nonces PER API KEY, not per user. Since we use one API key for all users in most deployments, a single global nonce is correct.

**Action Required:** Remove any code that tracks nonces per user.

### 2. Precision Change

**Impact:** Nonces are now 19 digits (nanoseconds) instead of 13 digits (milliseconds)

**Reason:** Nanosecond precision provides better uniqueness and prevents collisions in high-frequency scenarios.

**Action Required:** Update any code that parses or validates nonce length.

**Example:**
```python
# Before: 13 digits (milliseconds)
nonce = 1768712093048  # ms since epoch

# After: 19 digits (nanoseconds)  
nonce = 1768712093048832619  # ns since epoch
```

### 3. Automatic Burst Protection

**Impact:** Nonce generation may be throttled during startup

**Reason:** Prevents rapid bursts that trigger Kraken rate limiting.

**Action Required:** If you need maximum speed in specific scenarios, disable burst protection:
```python
nonce = manager.get_nonce(apply_rate_limiting=False)
```

## Backward Compatibility

The elite-tier system maintains backward compatibility:

✅ **Legacy Functions Still Work:**
```python
# These all use GlobalKrakenNonceManager internally
from bot.global_kraken_nonce import (
    get_kraken_nonce,           # Legacy function
    get_global_kraken_nonce     # Recommended alias
)

nonce = get_kraken_nonce()        # Works
nonce = get_global_kraken_nonce()  # Same result
```

✅ **Automatic Fallback:**
```python
# broker_manager.py has automatic fallback
# If GlobalKrakenNonceManager is unavailable, falls back to KrakenNonce
```

## Deprecation Timeline

| Component | Status | Action |
|-----------|--------|--------|
| GlobalKrakenNonceManager | ✅ **Active** | Use this |
| UserNonceManager | ⚠️ **Deprecated** | Migrate away |
| KrakenNonce | ⚠️ **Deprecated** | Migrate away |
| get_kraken_nonce() (broker_manager) | ⚠️ **Fallback Only** | Use global manager instead |

**Recommended Timeline:**
- **Week 1-2:** Update dashboard_server.py and user_dashboard_api.py
- **Week 3-4:** Audit all custom code for legacy usage
- **Week 5:** Remove deprecation warnings
- **Week 6+:** Consider removing legacy code (after full migration)

## Testing Your Migration

After migrating, run these tests:

### 1. Unit Tests
```bash
python3 test_elite_nonce_manager.py
```

### 2. Integration Tests
```python
# Test your migrated code
from bot.global_kraken_nonce import (
    get_global_nonce_manager,
    get_kraken_api_lock
)

# Verify nonce generation
manager = get_global_nonce_manager()
nonce1 = manager.get_nonce()
nonce2 = manager.get_nonce()
assert nonce2 > nonce1, "Nonces should be monotonically increasing"

# Verify API lock
lock = get_kraken_api_lock()
assert lock is not None, "API lock should be available"
```

### 3. Performance Tests
```python
import time
from bot.global_kraken_nonce import get_global_nonce_manager

manager = get_global_nonce_manager()

# Test throughput
start = time.time()
for _ in range(1000):
    manager.get_nonce(apply_rate_limiting=False)
elapsed = time.time() - start

print(f"Generated 1000 nonces in {elapsed:.2f}s")
print(f"Rate: {1000/elapsed:.0f} nonces/sec")

# Should be > 10,000 nonces/sec
assert 1000/elapsed > 10000, "Performance regression detected"
```

## Common Issues and Solutions

### Issue: "Module 'user_nonce_manager' not found"

**Cause:** Code still imports deprecated module

**Solution:** Update imports to use `global_kraken_nonce`

```python
# Change from:
from bot.user_nonce_manager import get_user_nonce_manager

# To:
from bot.global_kraken_nonce import get_global_nonce_manager
```

### Issue: "TypeError: get_nonce() got unexpected keyword argument 'user_id'"

**Cause:** Passing user_id to global manager

**Solution:** Remove user_id parameter

```python
# Change from:
nonce = manager.get_nonce(user_id="user123")

# To:
nonce = manager.get_nonce()  # No user_id needed
```

### Issue: Nonces seem "too large" (19 digits)

**Cause:** Migration from milliseconds to nanoseconds

**Solution:** This is expected. Kraken accepts both. If you need to convert:

```python
# Nanoseconds to milliseconds (if needed for display)
nonce_ns = 1768712093048832619
nonce_ms = nonce_ns // 1_000_000
print(f"Nonce (ms): {nonce_ms}")  # 1768712093048
```

### Issue: "Nonce window exceeded" errors

**Cause:** Old persisted nonce is ahead of current time

**Solution:** Jump nonce forward

```python
from bot.global_kraken_nonce import get_global_nonce_manager

manager = get_global_nonce_manager()
manager.jump_forward(60_000_000_000)  # Jump 60 seconds
```

## Benefits After Migration

✅ **Reduced Complexity**
- One nonce system instead of three
- Easier to debug and maintain
- Single source of truth

✅ **Better Performance**
- Startup burst protection prevents throttling
- No file I/O on every call (batched every 10th)
- Optimized thread locking

✅ **Higher Reliability**
- Zero nonce collisions (tested with 1000 concurrent threads)
- Guaranteed monotonic increase
- Crash recovery via persistence

✅ **Elite Features**
- Comprehensive metrics and monitoring
- Configurable rate limiting
- Institutional-grade reliability

## Support

If you encounter issues during migration:

1. **Review the documentation:** `ELITE_NONCE_MANAGER.md`
2. **Run the test suite:** `python3 test_elite_nonce_manager.py`
3. **Check your logs:** Look for nonce-related warnings
4. **Verify imports:** Ensure you're using `bot.global_kraken_nonce`

## Summary

The migration to Elite-Tier Nonce Manager is straightforward:

1. ✅ Replace `UserNonceManager` with `GlobalKrakenNonceManager`
2. ✅ Replace `KrakenNonce` with `GlobalKrakenNonceManager`
3. ✅ Always use `get_kraken_api_lock()` for API calls
4. ✅ Remove per-user nonce tracking logic
5. ✅ Test thoroughly with the provided test suite

The result: A more reliable, performant, and maintainable system ready for elite quantitative trading operations.

---

*Author: NIJA Trading Systems*  
*Version: 1.0*  
*Date: January 29, 2026*
