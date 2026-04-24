# CHANGELOG

## [7.2.0] - 2026-02-03

### Breaking Changes

**⚠️ Independent Trading Mode Only**

Starting with v7.2.0, NIJA operates exclusively in Independent Trading mode:

- Each configured account trades independently based on its own market analysis
- Accounts make autonomous trading decisions every ~2.5 minutes
- Position sizing is scaled to individual account balances
- Different accounts may take different positions based on timing and market conditions
- Multi-account synchronization features have been removed

### What This Means for Users

**Before v7.2.0:**
- Optional master/follower account modes
- Accounts could mirror trades from a master account
- Synchronized position management across accounts

**After v7.2.0:**
- All accounts operate independently
- Each account evaluates markets and executes trades autonomously
- Better suited for distributed capital across multiple brokers
- Each account's performance depends on its own execution timing

### Migration Guide

If you were using synchronized/follower modes:
1. Each account will now trade independently
2. Review risk settings for each account individually
3. Monitor each account's performance separately
4. Consider consolidating to fewer accounts if independent trading is not desired

### New Features

- **Profitability-Focused Strategy**: v7.2 strategy upgrade with stricter entry filters (3/5+ signal quality)
- **Conservative Position Sizing**: 2-5% per position (enables 20-50 concurrent positions)
- **Stepped Profit-Taking**: Progressive exits at 0.5%, 1%, 2%, 3% profit levels
- **Wider Stops**: Dynamic ATR-based stops (1.5x ATR) to reduce stop-hunts
- **Adaptive RSI**: Optional regime-based RSI thresholds for better entry timing

### Improvements

- Enhanced capital efficiency through faster profit-taking
- Reduced stop-hunt losses with wider ATR-based stops
- Better risk management with conservative position sizing
- More trading opportunities through freed capital

### Technical Details

See `bot/nija_apex_strategy_v72_upgrade.py` for detailed implementation.

---

## [7.1.0] - Previous Release

For changes prior to v7.2.0, refer to git history and documentation files.
# Changelog

All notable changes to the NIJA Autonomous Trading Platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [7.2.0] - 2026-02-03

### Removed

- **BREAKING CHANGE**: Removed deprecated copy-trading system. NIJA now supports independent trading only.
  - All accounts now trade independently based on their own risk profiles and capital tiers
  - Legacy copy-trading functionality has been fully removed from the codebase
  - Users should configure each account with appropriate risk parameters for independent operation
  - See `PLATFORM_ONLY_GUIDE.md` and `MULTI_EXCHANGE_TRADING_GUIDE.md` for independent trading setup

### Changed

- Updated all documentation to reflect independent trading model
- Simplified broker management by removing copy-trading complexity

## [7.1.0] - Previous Release

- APEX V7.1 trading strategy
- Dual RSI indicators (RSI_9 + RSI_14)
- Dynamic position management
- Automatic profit compounding
- Intelligent trailing systems
- TradingView webhook integration
- Multi-exchange support (Coinbase, Kraken)
