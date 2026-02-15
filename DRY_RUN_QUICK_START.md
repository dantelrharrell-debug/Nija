# Dry-Run Mode Quick Reference

## Purpose

Run the NIJA trading bot in **100% safe simulation mode** to:
- ✅ Test strategy without risking money
- ✅ Validate exchange configurations  
- ✅ Review startup banners
- ✅ Get operator sign-off before going live

## Quick Start

```bash
# Run dry-run mode
./run_dry_run.sh

# Or run for specific duration (e.g., 30 minutes)
./run_dry_run.sh 30
```

## What Happens

1. **Startup Banner** - Clear visual indication you're in simulation mode
2. **Validation Summary** - Shows configured exchanges and safety guarantees
3. **Simulated Trading** - All orders are simulated in-memory (NO REAL ORDERS)
4. **Performance Tracking** - P&L, trades, and metrics calculated

## Environment Variables

```bash
# Enable dry-run mode
export DRY_RUN_MODE=true

# Ensure live trading is disabled
export LIVE_CAPITAL_VERIFIED=false
```

## Going Live After Validation

Once you've validated everything:

```bash
# Disable dry-run mode
export DRY_RUN_MODE=false

# Enable live trading
export LIVE_CAPITAL_VERIFIED=true

# Restart
./start.sh
```

## Documentation

- **Complete Guide**: `DRY_RUN_MODE_GUIDE.md`
- **Test Suite**: `test_dry_run_mode.py`

## Safety Guarantees

- ✅ NO REAL ORDERS placed on any exchange
- ✅ NO REAL MONEY at risk
- ✅ ALL TRADING simulated in-memory
- ✅ ALL EXCHANGES in simulation mode

**Use dry-run mode first, go live with confidence!**
