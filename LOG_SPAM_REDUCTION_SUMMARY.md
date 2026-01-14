# Kraken Permission Error Log Spam Fix - Summary

## Issue
When multiple users had Kraken API permission errors, the bot logged the full detailed fix instructions (12+ lines) for EVERY user with a permission error, creating severe log spam and making logs difficult to read.

Example of the spam (from problem statement):
```
2026-01-14 20:45:54 | ERROR |    ⚠️  API KEY PERMISSION ERROR
2026-01-14 20:45:54 | ERROR |    Your Kraken API key does not have the required permissions.
2026-01-14 20:45:54 | WARNING | 
2026-01-14 20:45:54 | WARNING |    To fix this issue:
2026-01-14 20:45:54 | WARNING |    1. Go to https://www.kraken.com/u/security/api
2026-01-14 20:45:54 | WARNING |    2. Find your API key and edit its permissions
2026-01-14 20:45:54 | WARNING |    3. Enable these permissions:
2026-01-14 20:45:54 | WARNING |       ✅ Query Funds (required to check balance)
2026-01-14 20:45:54 | WARNING |       ✅ Query Open Orders & Trades (required for position tracking)
2026-01-14 20:45:54 | WARNING |       ✅ Query Closed Orders & Trades (required for trade history)
2026-01-14 20:45:54 | WARNING |       ✅ Create & Modify Orders (required to place trades)
2026-01-14 20:45:54 | WARNING |       ✅ Cancel/Close Orders (required for stop losses)
2026-01-14 20:45:54 | WARNING |    4. Save changes and restart the bot
2026-01-14 20:45:54 | WARNING | 
2026-01-14 20:45:54 | WARNING |    For security, do NOT enable 'Withdraw Funds' permission
2026-01-14 20:45:54 | WARNING |    See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions
[... repeated for every user ...]
```

## Root Cause
The deduplication logic tracked which accounts had logged permission errors using a per-account set (`_permission_errors_logged`). This prevented logging the same error multiple times for the SAME account, but allowed logging full instructions for EACH DIFFERENT account with permission errors.

## Solution
Changed the deduplication strategy from per-account to global:

### Before:
- Used `_permission_errors_logged` set to track which accounts already logged errors
- Each unique account could log full detailed instructions once
- With N users having errors, full instructions appeared N times

### After:
- Use `_permission_error_details_logged` boolean flag (global, not per-account)
- First account with permission error logs full detailed instructions
- Subsequent accounts log brief reference: "⚠️ Permission error (see above for fix instructions)"
- With N users having errors, full instructions appear only ONCE

## Changes Made

### 1. `bot/broker_manager.py` (KrakenBroker class)
- Line 3370-3382: Changed class variable from set to boolean flag
  - `_permission_errors_logged = set()` → `_permission_error_details_logged = False`
  - Updated documentation to reflect global behavior
- Line 3728-3769: Updated permission error handling logic (main path)
  - Check and set boolean flag instead of checking set membership
  - Log brief reference message for subsequent errors
- Line 3864-3905: Updated permission error handling logic (exception path)
  - Same changes as main path for consistency
- Line 3765, 3901: Fixed documentation reference format
  - `KRAKEN_PERMISSION_ERROR_FIX` → `KRAKEN_PERMISSION_ERROR_FIX.md`

### 2. `bot/broker_integration.py` (KrakenBrokerAdapter class)
- Line 12: Added `import threading` for lock support
- Line 390-395: Added class-level flag and lock
  - `_permission_error_details_logged = False`
  - `_permission_errors_lock = threading.Lock()`
- Line 429-472: Updated permission error handling logic
  - Check and set boolean flag with thread-safe lock
  - Log brief reference message for subsequent errors

## Testing
Created two test scripts to verify the fix:

1. **test_permission_error_deduplication.py**
   - Basic structural test
   - Verifies flag is boolean and persists across instances
   - Verifies lock exists
   - ✅ PASSED

2. **test_permission_error_integration.py**
   - Integration test (requires krakenex library)
   - Simulates multiple users with permission errors
   - Verifies first user gets full instructions, subsequent users get brief message
   - Cannot run in current environment (krakenex not installed), but structure is sound

## Security Review
✅ CodeQL security scan completed - **0 alerts found**
✅ No security vulnerabilities introduced by changes

## Code Review
Addressed feedback:
- ✅ Fixed inconsistent documentation reference format (.md extension)
- ✅ Verified lock naming is correct (protects multiple permission error mechanisms)
- ✅ Confirmed separate flags in KrakenBroker vs KrakenBrokerAdapter is appropriate
  (different implementations, not used together in production)

## Impact

### Before Fix (with 3 users having permission errors):
```
[User 1 error header]
[12 lines of detailed instructions]
[User 2 error header]
[12 lines of detailed instructions]  ← SPAM
[User 3 error header]
[12 lines of detailed instructions]  ← SPAM
Total: ~36+ lines of repeated content
```

### After Fix (with 3 users having permission errors):
```
[User 1 error header]
[12 lines of detailed instructions]
[User 2 error header]
⚠️  Permission error (see above for fix instructions)
[User 3 error header]
⚠️  Permission error (see above for fix instructions)
Total: ~16 lines (55% reduction!)
```

## Benefits
1. **Dramatically reduces log spam** - ~55% reduction in log output for permission errors
2. **Maintains helpful instructions** - First user still gets full detailed help
3. **Improves log readability** - Easier to scan logs and find other issues
4. **Thread-safe implementation** - Uses locks to prevent race conditions
5. **Backward compatible** - No API changes, only internal logging behavior
6. **Consistent behavior** - Applied to both Kraken broker implementations

## Files Changed
- `bot/broker_manager.py` - Main Kraken broker implementation
- `bot/broker_integration.py` - Alternative Kraken broker adapter
- `test_permission_error_deduplication.py` - Test for flag structure (new)
- `test_permission_error_integration.py` - Integration test (new)

## Deployment Notes
- No configuration changes required
- No database migrations needed
- No API changes
- Safe to deploy immediately
- Will take effect on next bot restart
