# Quick Start: Global Kraken Nonce Manager

## What This Is

A **ONE global nonce source** for all Kraken accounts (MASTER + USERS) that eliminates nonce collisions and enables reliable copy trading.

## Key Features

✅ **Zero Nonce Collisions** - Single source of truth  
✅ **Nanosecond Precision** - 19-digit timestamps  
✅ **Thread-Safe** - RLock protection  
✅ **Scales to 100+ Users** - Tested with 100 concurrent threads  
✅ **No File Persistence** - Nanoseconds always increase  
✅ **Drop-In Replacement** - Automatic fallback to old implementation  

## How It Works

```
ALL Kraken API Calls
        ↓
get_global_kraken_nonce()
        ↓
GlobalKrakenNonceManager (singleton)
        ↓
time.time_ns() → 19-digit nanosecond nonce
        ↓
NO collisions possible!
```

## Usage

### For Development

```python
from bot.global_kraken_nonce import get_global_kraken_nonce

# Get a nonce - thread-safe and monotonic
nonce = get_global_kraken_nonce()
# Returns: 1768712093048832619 (19 digits)

# That's it! No configuration needed.
```

### For Production

**No action required** - just deploy the code!

1. Deploy this PR
2. Bot automatically uses global nonce manager
3. Old per-user nonce files are ignored (but not deleted)
4. All Kraken accounts (master + users) share one nonce source

## Testing

### Run Unit Tests

```bash
python3 test_global_kraken_nonce.py
# Expected: 7/7 tests pass
```

### Run Integration Test

```bash
python3 test_kraken_integration_global_nonce.py
# Expected: 6 accounts, 300 API calls, 0 collisions
```

### Verify Imports

```bash
python3 -c "from bot.global_kraken_nonce import get_global_kraken_nonce; print('✅ OK')"
```

## What to Expect After Deployment

### In Logs

Before:
```
❌ Error fetching Kraken balance (MASTER): EAPI:Invalid nonce
❌ Error fetching Kraken balance (USER:daivon): EAPI:Invalid nonce
```

After:
```
✅ GLOBAL Kraken Nonce Manager installed for MASTER (nanosecond precision)
✅ GLOBAL Kraken Nonce Manager installed for USER:daivon_frazier (nanosecond precision)
✅ Connected to Kraken Pro API (MASTER)
✅ Connected to Kraken Pro API (USER:daivon_frazier)
```

### Expected Behavior

✅ **MASTER connects successfully**  
✅ **All USERS connect successfully**  
✅ **Copy trading works**  
✅ **No nonce errors**  
✅ **Scales to 10-100 users**  

## Troubleshooting

### If nonce errors still occur

1. Check that `get_global_kraken_nonce` is available:
   ```python
   from bot.global_kraken_nonce import get_global_kraken_nonce
   print(f"Nonce: {get_global_kraken_nonce()}")
   ```

2. Check logs for which nonce manager is being used:
   - Look for "GLOBAL Kraken Nonce Manager" (good)
   - If you see "fallback" or "OPTION A" (using old implementation)

3. Verify Python version:
   ```bash
   python3 --version  # Should be 3.7+ (for time.time_ns)
   ```

### Fallback Behavior

If global nonce manager is unavailable, the system automatically falls back to:
1. Per-user `KrakenNonce` (milliseconds) - DEPRECATED but functional
2. Basic time-based nonce (milliseconds) - Last resort

This ensures the bot keeps working even with import issues.

## Statistics

Get nonce manager statistics:

```python
from bot.global_kraken_nonce import get_global_nonce_stats

stats = get_global_nonce_stats()
print(f"Total nonces issued: {stats['total_nonces_issued']}")
print(f"Uptime: {stats['uptime_seconds']:.2f}s")
print(f"Rate: {stats['nonces_per_second']:.0f} nonces/second")
```

## Architecture Benefits

### Before (Multiple Sources)
```
KrakenBroker (MASTER)
  ├─ KrakenNonce instance
  ├─ Nonce file: data/kraken_nonce_master.txt
  └─ Milliseconds (13 digits)

KrakenBroker (USER1)
  ├─ KrakenNonce instance
  ├─ Nonce file: data/kraken_nonce_user1.txt
  └─ Milliseconds (13 digits)

❌ Potential collisions at startup
❌ File race conditions
❌ Limited precision
```

### After (Global Manager)
```
GlobalKrakenNonceManager (Singleton)
  ├─ ONE instance process-wide
  ├─ Nanoseconds (19 digits)
  ├─ Thread-safe RLock
  └─ No file persistence
       ↓
  ALL users share this
       ↓
  ✅ Zero collisions
  ✅ Simple & reliable
  ✅ Scales to 100+ users
```

## File Reference

- **Implementation**: `bot/global_kraken_nonce.py`
- **Tests**: `test_global_kraken_nonce.py`
- **Integration Test**: `test_kraken_integration_global_nonce.py`
- **Documentation**: `GLOBAL_KRAKEN_NONCE_MANAGER_JAN_18_2026.md`

## Support

If you encounter issues:

1. Run the test suite to verify functionality
2. Check Python version (3.7+ required for `time.time_ns()`)
3. Check logs for which nonce manager is active
4. Verify imports work: `python3 -c "from bot.global_kraken_nonce import *"`

## Summary

This is a **drop-in fix** that:
- Requires no configuration
- Has comprehensive test coverage
- Maintains backward compatibility
- Solves nonce collisions permanently

Just **deploy and it works**! 🚀

---

**Status**: ✅ Production Ready  
**Date**: January 18, 2026  
**Testing**: Complete (7 unit tests + integration test)  
**Breaking Changes**: None
