# Merge Conflict Prevention Guide

## Issue Resolved

**Date:** January 29, 2026  
**Problem:** Copilot sessions were experiencing merge conflicts due to runtime state files being tracked in git.

## Root Cause

Runtime state files in the `data/` directory were being committed to the repository. These files change during bot execution and should not be version controlled, as they cause merge conflicts when:
- Multiple developers work on the same branch
- The bot runs on different branches simultaneously
- Automated processes push changes while manual work is in progress

## Files Removed from Git Tracking

The following runtime state files have been removed from git tracking (but remain on disk for bot functionality):

### Trading State Files
- `data/daily_profit_history.json` - Daily profit tracking
- `data/daily_profit_state.json` - Daily profit state
- `data/progressive_targets.json` - Progressive targets state
- `data/trade_history.json` - Trade history
- `data/open_positions.json` - Open positions state
- `data/trade_ledger.db` - SQLite trade ledger database

### Exchange Integration Files
- `data/kraken_global_nonce.txt` - Kraken API nonce state

### Capital Management Files
- `data/capital_allocation.json` - Capital allocation state

### Data Export Files
- `data/*.csv` - CSV export files (e.g., `nija_trades_*.csv`)

### Demo and Learning Data
- `data/demo_live_tracking/*` - Demo trading tracking data
- `data/learning/*` - ML learning data

## .gitignore Updates

The `.gitignore` file has been updated with comprehensive patterns to prevent these files from being committed in the future:

```gitignore
# Trading state files (runtime state, should not be committed)
# Daily profit tracking
data/daily_profit_history.json
data/daily_profit_state.json
# Progressive targets
data/progressive_targets.json
data/progressive_targets_*.json
# Trade history and positions
data/trade_history.json
data/trade_history_*.json
data/open_positions.json
data/open_positions.json.*
# Trade exports and database
data/nija_trades_*.csv
data/trade_ledger.db
data/trade_ledger.db-journal

# Kraken nonce files (already covered by existing patterns)
# data/kraken_nonce*.txt covers data/kraken_global_nonce.txt

# Demo and learning data (runtime state, should not be committed)
data/demo_live_tracking/
data/learning/
```

**Note:** The Kraken global nonce file is already covered by the existing pattern `data/kraken_nonce*.txt` in lines 50-52 of `.gitignore`.

## Prevention Strategy

To prevent future merge conflicts:

1. **Never commit runtime state files** - These files change during execution and should not be version controlled
2. **Use .gitignore** - Add patterns for any new runtime state files to `.gitignore`
3. **Verify before committing** - Run `git status` to ensure no unwanted files are staged
4. **Remove accidentally committed files** - Use `git rm --cached <file>` to remove from tracking while keeping on disk

## Verification

To verify a file is properly ignored:
```bash
git check-ignore -v <filename>
```

To verify no runtime state files are tracked:
```bash
git ls-files | grep -E "data/.*\.(json|db|csv)$"
```

## Impact

These changes prevent merge conflicts by ensuring runtime state files are local to each environment and not shared through version control. The bot will continue to function normally as these files remain on disk - they're just no longer tracked by git.

## Related Files

- `.gitignore` - Updated with comprehensive runtime state patterns
- `data/` directory - Contains runtime state files (not tracked)

## Notes for Developers

If you add new runtime state files to the bot:
1. Add corresponding patterns to `.gitignore`
2. If the file is already tracked, remove it with `git rm --cached <file>`
3. Document the file type in this guide
4. Ensure the file is created by the bot at runtime if it doesn't exist

## Testing

After this fix:
- ✅ Working tree is clean
- ✅ All runtime state files remain on disk
- ✅ Runtime state files are properly ignored by git
- ✅ Repository integrity verified with `git fsck`
- ✅ No merge conflicts from runtime state files
