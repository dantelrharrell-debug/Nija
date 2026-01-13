# Kraken Permission Error Fix

## Problem Fixed
This PR fixes an issue where Kraken API connection attempts with permission errors would:
1. Detect the permission error correctly
2. Log the error with helpful instructions
3. Return `False` from the `connect()` method
4. **BUT** could be retried by external code, leading to:
   - "Invalid nonce" errors on subsequent attempts
   - Wasted API quota
   - Confusing error logs
   - Delayed bot startup

## Root Cause
Permission errors were detected and logged correctly, but there was no mechanism to prevent future `connect()` calls for the same account. If the multi-account manager or other code attempted to reconnect (whether due to bugs, multiple instances, or other retry logic), the permission error would trigger again, potentially causing nonce issues.

## Solution
Added a class-level tracking mechanism that permanently marks accounts as failed when they encounter permission errors:

1. **New tracking set**: `KrakenBroker._permission_failed_accounts` - stores account identifiers that have had permission errors
2. **Early exit check**: At the start of `connect()`, check if this account is in the tracking set and exit immediately with a warning
3. **Permission error detection**: When a permission error is detected (in either the normal path or exception path), add the account to the tracking set
4. **Thread-safe**: Uses the existing `_permission_errors_lock` to ensure thread safety

## What This Fixes
- ✅ Permission errors no longer trigger retries
- ✅ No more "Invalid nonce" errors after permission errors
- ✅ Faster bot startup (no wasted retry attempts)
- ✅ Clearer logs (only one permission error message per account)
- ✅ Less API quota consumption

## What Still Works
- ✅ Retryable errors (network, rate limit, timeout) still retry correctly
- ✅ Permission error help messages still display with fix instructions
- ✅ Different accounts can fail independently
- ✅ Restarting the bot clears the tracking (allows retry after fixing permissions)

## How to Verify the Fix

### Before the Fix
With invalid Kraken API credentials, the bot would:
```
❌ Kraken connection test failed (USER:tania_gilbert): EGeneral:Permission denied
   ⚠️  API KEY PERMISSION ERROR
   (... help message ...)
⚠️  Failed to connect user broker: tania_gilbert -> kraken
📊 Connecting Tania Gilbert (tania_gilbert) to Kraken...  # <- RETRY HAPPENING
⚠️  Kraken connection attempt 1/5 failed (retryable, USER:tania_gilbert): EAPI:Invalid nonce  # <- NONCE ERROR
🔄 Retrying Kraken connection (USER:tania_gilbert) in 5.0s (attempt 2/5)...
```

### After the Fix
With invalid Kraken API credentials, the bot will:
```
❌ Kraken connection test failed (USER:tania_gilbert): EGeneral:Permission denied
   ⚠️  API KEY PERMISSION ERROR
   (... help message ...)
⚠️  Failed to connect user broker: tania_gilbert -> kraken
📊 Connecting Tania Gilbert (tania_gilbert) to Kraken...  # <- SECOND ATTEMPT (if triggered)
⚠️  Skipping Kraken connection for USER:tania_gilbert - previous permission error  # <- BLOCKED!
   Fix API key permissions at https://www.kraken.com/u/security/api and restart bot
⚠️  Failed to connect user broker: tania_gilbert -> kraken
# No more retries, no Invalid nonce errors
```

## Testing
To test this fix:

1. **Test permission error blocking**:
   - Set invalid Kraken credentials (or credentials with insufficient permissions)
   - Start the bot
   - Verify you see the permission error message
   - Verify you see the "Skipping... previous permission error" message if reconnection is attempted
   - Verify no "Invalid nonce" errors appear

2. **Test normal retry behavior still works**:
   - Temporarily disable your internet connection
   - Start the bot
   - Verify connection failures are retried with exponential backoff
   - Re-enable internet
   - Verify the bot eventually connects successfully

3. **Test fix allows retry after permissions are fixed**:
   - Fix the API key permissions on Kraken website
   - Restart the bot
   - Verify the bot connects successfully (the tracking is cleared on restart)

## Files Changed
- `bot/broker_manager.py`:
  - Added `_permission_failed_accounts` class variable
  - Added early exit check in `connect()` method
  - Updated permission error detection to track failed accounts
  - Added permission error detection in exception handler path

## Related Documentation
- See main error logs in problem statement for before/after comparison
- Kraken API permissions guide: `KRAKEN_PERMISSION_ERROR_FIX.md`
- Multi-user setup: `MULTI_USER_SETUP_GUIDE.md`
