# Startup Validation Guide

## Overview

This document describes the startup validation system that addresses three subtle but critical risks in the NIJA trading bot:

1. **Branch/Commit Unknown** - Running code without version traceability
2. **Disabled Exchanges** - Operating with disabled brokers without clear warnings
3. **Testing vs. Live Mode** - Ambiguous configuration of trading mode

## The Problem

### 1. Branch/Commit Unknown Risk

**What it is:**
When the bot starts without knowing which git branch and commit it's running, operators cannot trace issues back to specific code versions.

**Why it's dangerous:**
- Cannot verify which code is running in production
- Difficult to debug issues or roll back changes
- Risk of running wrong/stale builds without realizing it

**Where it occurs:**
- `start.sh` lines 152-164: Falls back to "unknown" if git commands fail
- `bot.py` lines 430-462: Python also falls back to "unknown"

**Example scenario:**
```bash
# Git not installed in container
$ git rev-parse HEAD
bash: git: command not found

# Bot starts with "unknown" branch/commit
Branch: unknown
Commit: unknown

# Operator has no idea which code is running!
```

### 2. Disabled Exchanges Risk

**What it is:**
Exchanges can be disabled in code (hardcoded) even when credentials are configured. Without clear warnings, operators may not realize trading won't occur on those exchanges.

**Why it's dangerous:**
- Credentials configured but trading doesn't occur
- Silent failures if primary exchange is disabled
- No fallback validation when disabled exchange is misconfigured

**Where it occurs:**
- `bot/broker_manager.py` lines 1125-1132: Coinbase hardcoded as disabled
- Only a single warning logged, easy to miss

**Example scenario:**
```python
# Operator configures Coinbase credentials
export COINBASE_API_KEY="..."
export COINBASE_API_SECRET="..."

# But Coinbase is disabled in code
# CoinbaseBroker.connect() returns False immediately
# Trading fails silently, operator doesn't know why
```

### 3. Testing vs. Live Mode Risk

**What it is:**
Multiple mode flags exist (`PAPER_MODE`, `LIVE_CAPITAL_VERIFIED`, etc.) making it unclear whether the bot is in testing or live mode.

**Why it's dangerous:**
- Accidental live trading with real money
- Ambiguous mode when neither flag is set
- Contradictory flags (both PAPER_MODE=true and LIVE_CAPITAL_VERIFIED=true)
- Single typo can enable live trading

**Where it occurs:**
- `bot/safety_controller.py` lines 125-173: Mode detection logic
- Multiple environment variables controlling mode

**Example scenario:**
```bash
# Operator intends to test
# But accidentally types:
export LIVE_CAPITAL_VERIFIED=yes  # TYPO! Meant "no"

# Bot immediately starts live trading!
# Real money at risk from a single character mistake
```

## The Solution

### Startup Validation System

The new `bot/startup_validation.py` module provides comprehensive pre-flight checks that run before any trading begins.

#### Components

1. **Git Metadata Validation**
   - Checks if branch/commit are known
   - Warns if either is "unknown"
   - Logs risk in validation report

2. **Exchange Configuration Validation**
   - Detects disabled exchanges
   - Warns if credentials are configured but exchange is disabled
   - Ensures at least one exchange is enabled
   - Critical failure if no exchanges available

3. **Trading Mode Validation**
   - Checks PAPER_MODE and LIVE_CAPITAL_VERIFIED flags
   - Detects contradictory configurations
   - Warns if mode is ambiguous
   - Makes live trading explicit and visible

#### Integration Points

**1. bot.py Startup (Lines 468-495)**
```python
# Run validation after version logging
from bot.startup_validation import run_all_validations, display_validation_results
validation_result = run_all_validations(git_branch, git_commit)
display_validation_results(validation_result)

# Exit if critical failure
if validation_result.critical_failure:
    logger.error("STARTUP VALIDATION FAILED - EXITING")
    sys.exit(1)
```

**2. start.sh Script (Lines 163-184)**
```bash
# Warn if git metadata is unknown
if [ "${BRANCH_VAL:-unknown}" = "unknown" ] || [ "${COMMIT_VAL:-unknown}" = "unknown" ]; then
    echo "⚠️  RISK: Running with UNKNOWN git metadata"
    echo "⚠️  Cannot verify which code version is running!"
    # ... detailed warning message
fi
```

**3. start.sh Mode Banner (Lines 280-310)**
```bash
# Display trading mode with clear warnings
if [ "${LIVE_CAPITAL_VERIFIED_VAL}" = "true" ]; then
    echo "🔴 MODE: LIVE TRADING"
    echo "⚠️  REAL MONEY AT RISK"
elif [ "${PAPER_MODE_VAL}" = "true" ]; then
    echo "📝 MODE: PAPER TRADING"
else
    echo "⚠️  MODE: UNCLEAR"
fi
```

**4. broker_manager.py Enhanced Warning (Lines 1125-1152)**
```python
# Explicit banner when Coinbase is disabled
logger.warning("=" * 70)
logger.warning("🚫 COINBASE INTEGRATION IS DISABLED (HARDCODED)")
logger.warning("=" * 70)
logger.warning("   Even if credentials are configured, they will be IGNORED")
# ... detailed instructions
```

## Usage

### For Developers

**Ensure git metadata is available:**
```bash
# In CI/CD pipeline, set environment variables
export GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
export GIT_COMMIT=$(git rev-parse --short HEAD)

# Or use the injection script
./inject_git_metadata.sh
```

**Enable/disable exchanges explicitly:**
```bash
# Instead of hardcoding disables, use environment variables
export DISABLED_EXCHANGES="coinbase,okx"  # Future enhancement
```

**Set trading mode explicitly:**
```bash
# For testing
export PAPER_MODE=true

# For live trading (be careful!)
export LIVE_CAPITAL_VERIFIED=true
```

### For Operators

**Check startup logs:**
```
🔍 STARTUP VALIDATION REPORT
================================================================================
⚠️  RISKS DETECTED:
────────────────────────────────────────────────────────────────────────────────
   [GIT_METADATA_UNKNOWN] Git commit is UNKNOWN - cannot verify code version
   [DISABLED_EXCHANGE_WARNING] Coinbase credentials configured BUT exchange is DISABLED in code
────────────────────────────────────────────────────────────────────────────────
```

**Interpret validation results:**
- `PASSED` - No risks detected, safe to proceed
- `PASSED WITH RISKS` - Bot will start but risks exist
- `PASSED WITH WARNINGS` - Non-critical warnings
- `FAILED` - Critical failure, bot will not start

### Example Startup Output

**Good Startup (No Risks):**
```
🔍 STARTUP VALIDATION REPORT
================================================================================
✅ No risks detected
ℹ️  CONFIGURATION INFO:
────────────────────────────────────────────────────────────────────────────────
   Git branch verified: main
   Git commit verified: a1b2c3d
   ✅ Kraken Platform credentials configured and enabled
   📝 PAPER TRADING MODE: PAPER_MODE=true
   Total exchanges configured: 1
   Total exchanges enabled: 1
────────────────────────────────────────────────────────────────────────────────
RESULT: PASSED (No risks or warnings)
================================================================================
```

**Startup with Risks:**
```
🔍 STARTUP VALIDATION REPORT
================================================================================
⚠️  RISKS DETECTED:
────────────────────────────────────────────────────────────────────────────────
   [GIT_METADATA_UNKNOWN] Git branch is UNKNOWN - cannot verify code version
   [DISABLED_EXCHANGE_WARNING] Coinbase credentials configured BUT exchange is DISABLED
   [MODE_AMBIGUOUS] Trading mode is AMBIGUOUS - neither PAPER_MODE nor LIVE_CAPITAL_VERIFIED set
────────────────────────────────────────────────────────────────────────────────
⚠️  WARNINGS:
────────────────────────────────────────────────────────────────────────────────
   RISK: Running code with unknown branch. Set GIT_BRANCH environment variable
   ⚠️  COINBASE IS DISABLED: Credentials are set but integration is hardcoded as disabled
   ⚠️  MODE UNCLEAR: Trading mode not explicitly configured
────────────────────────────────────────────────────────────────────────────────
RESULT: PASSED WITH RISKS (3 risks, 3 warnings)
================================================================================
```

**Critical Failure:**
```
🔍 STARTUP VALIDATION REPORT
================================================================================
⚠️  RISKS DETECTED:
────────────────────────────────────────────────────────────────────────────────
   [NO_EXCHANGES_ENABLED] CRITICAL: No enabled exchanges detected
────────────────────────────────────────────────────────────────────────────────
================================================================================
❌ CRITICAL FAILURE - BOT CANNOT START
================================================================================
   Reason: No exchanges are enabled. At least one exchange must be configured.
================================================================================
RESULT: FAILED (Critical failure)
================================================================================

❌ STARTUP VALIDATION FAILED - EXITING
```

## Testing

To test the validation system:

```bash
# Test unknown git metadata
unset GIT_BRANCH
unset GIT_COMMIT
./start.sh
# Should show warning banner

# Test disabled exchange
export COINBASE_API_KEY="test"
export COINBASE_API_SECRET="test"
./start.sh
# Should show Coinbase disabled warning

# Test ambiguous mode
unset PAPER_MODE
unset LIVE_CAPITAL_VERIFIED
./start.sh
# Should show mode unclear warning

# Test live mode warning
export LIVE_CAPITAL_VERIFIED=true
./start.sh
# Should show RED live trading warning
```

## Benefits

1. **Visibility** - All risks are clearly logged during startup
2. **Traceability** - Git metadata tracking ensures version control
3. **Intentionality** - Trading mode must be explicit, no accidents
4. **Safety** - Critical failures prevent bot from starting unsafely
5. **Debugging** - Clear error messages help operators diagnose issues

## Future Enhancements

1. **Environment variable for disabled exchanges** instead of hardcoded disables
2. **Unified BOT_MODE variable** (paper|monitor|live) instead of multiple flags
3. **Build-time git metadata injection** to make version tracking mandatory
4. **Startup validation API** to query validation status via HTTP
5. **Validation metrics** to track risk occurrences over time

## Related Files

- `bot/startup_validation.py` - Validation logic
- `bot.py` lines 468-495 - Validation integration
- `start.sh` lines 163-184 - Git metadata warning
- `start.sh` lines 280-310 - Mode verification banner
- `bot/broker_manager.py` lines 1125-1152 - Coinbase disable warning
- `bot/safety_controller.py` - Mode detection (unchanged)

## Questions?

For questions or issues with the validation system:
1. Check this guide first
2. Review startup logs for detailed error messages
3. Enable debug logging: `export LOG_LEVEL=DEBUG`
4. See `TROUBLESHOOTING.md` for common issues
