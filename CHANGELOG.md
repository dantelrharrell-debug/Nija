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
