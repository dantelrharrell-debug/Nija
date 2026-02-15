# NIJA Dry-Run Mode Guide

## Overview

Dry-Run Mode (also called Paper Mode) is a **100% safe simulation mode** that allows you to:
- Test the trading bot without risking real money
- Validate all exchange configurations
- Review startup banners and validation summaries
- Verify strategy logic
- Gain confidence before enabling live trading

**CRITICAL SAFETY GUARANTEES:**
- ✅ NO REAL ORDERS will be placed on any exchange
- ✅ NO REAL MONEY at risk
- ✅ ALL TRADING is simulated in-memory
- ✅ ALL EXCHANGES run in simulation mode
- ✅ Separate logging clearly marked as "SIMULATION"

## Quick Start

### Option 1: Using the Dry-Run Script (Recommended)

The easiest way to run dry-run mode:

```bash
# Run continuously until you stop it
./run_dry_run.sh

# Run for a specific duration (e.g., 30 minutes)
./run_dry_run.sh 30
```

### Option 2: Using Environment Variables

Set the `DRY_RUN_MODE` environment variable:

```bash
# Enable dry-run mode
export DRY_RUN_MODE=true

# Ensure live trading is disabled
export LIVE_CAPITAL_VERIFIED=false

# Start the bot
./start.sh
```

### Option 3: Using .env File

Create or edit your `.env` file:

```bash
# Dry-Run Mode Configuration
DRY_RUN_MODE=true
PAPER_MODE=false
LIVE_CAPITAL_VERIFIED=false

# All your exchange credentials
# (These won't be used for real trading in dry-run mode)
KRAKEN_PLATFORM_API_KEY=your_key_here
KRAKEN_PLATFORM_API_SECRET=your_secret_here
# ... other exchange credentials ...
```

Then start the bot:

```bash
./start.sh
```

## What You'll See

### Startup Banner

When the bot starts in dry-run mode, you'll see a clear banner:

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║                      🟡 DRY RUN MODE (PAPER TRADING) 🟡                      ║
║                                                                              ║
║                          ⚠️  SIMULATION ONLY ⚠️                             ║
║                                                                              ║
║  ✅ NO REAL ORDERS will be placed on any exchange                           ║
║  ✅ NO REAL MONEY at risk                                                   ║
║  ✅ ALL TRADING is simulated in-memory                                      ║
║  ✅ ALL EXCHANGES are in simulation mode                                    ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### Feature Flags Display

The feature flags will show dry-run mode status:

```
🏁 FEATURE FLAGS STATUS
======================================================================
   🟡 Dry-Run Mode (Paper Trading): ENABLED (SIMULATION)
   ✅ Profit Confirmation Logging: ENABLED
   ✅ Execution Intelligence: ENABLED
   ...
======================================================================
```

### Validation Summary

Before trading begins, you'll see a comprehensive validation summary:

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                     DRY RUN VALIDATION SUMMARY                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

✅ SIMULATION CONFIGURATION VALIDATED:

   📊 Exchanges Configured: 3
   💰 Initial Balance: 10,000.00 USD
   ⏱️  Duration: Continuous
   🎯 Mode: PAPER TRADING (100% Safe)

✅ SAFETY GUARANTEES CONFIRMED:

   ✓ Zero real orders will be placed
   ✓ Zero real money at risk
   ✓ All exchanges in simulation mode
   ✓ Trade history will be logged for review
   ✓ Performance metrics will be calculated

✅ NEXT STEPS:

   1. Monitor simulation logs for expected behavior
   2. Review performance metrics after run
   3. Verify all exchanges are responding correctly
   4. Check banner displays are clear and visible
   5. Operator sign-off when satisfied with validation
   6. Enable live trading with confidence:
      • export DRY_RUN_MODE=false
      • export LIVE_CAPITAL_VERIFIED=true
```

## Trading Mode Priority

NIJA supports multiple trading mode flags. They are evaluated in this priority order:

1. **DRY_RUN_MODE** (Highest Priority - Safest)
   - Full simulation mode
   - No real orders on any exchange
   - Perfect for testing and validation

2. **LIVE_CAPITAL_VERIFIED**
   - Live trading with real money
   - Only use after successful dry-run validation

3. **PAPER_MODE**
   - Paper trading mode (legacy)
   - Less comprehensive than DRY_RUN_MODE

**Important:** If multiple flags are set, DRY_RUN_MODE takes priority to ensure safety.

## Validation Checklist

Before going live, use dry-run mode to validate:

### 1. Startup Banners
- [ ] Dry-run banner displays clearly at startup
- [ ] Banner shows all safety guarantees
- [ ] Mode is clearly indicated as "SIMULATION"

### 2. Exchange Configuration
- [ ] All configured exchanges show up in the validation summary
- [ ] Exchange count is accurate
- [ ] No connection errors (even though no real orders are placed)

### 3. Feature Flags
- [ ] Dry-run mode shows as enabled in feature flags
- [ ] All expected features are enabled
- [ ] No unexpected features are enabled

### 4. Validation Summary
- [ ] Initial balance is correct
- [ ] Exchange count is accurate
- [ ] Safety guarantees are listed
- [ ] Next steps are clearly shown

### 5. Logging
- [ ] All log messages clearly indicate "SIMULATION"
- [ ] Simulated orders are logged
- [ ] Position updates are tracked
- [ ] No errors in logs

### 6. Operator Confidence
- [ ] You understand all the banners and messages
- [ ] You're confident the bot will behave as expected
- [ ] You're ready to enable live trading

## Going Live After Dry-Run

Once you've validated everything in dry-run mode and are satisfied:

### Step 1: Disable Dry-Run Mode

```bash
export DRY_RUN_MODE=false
```

Or remove/comment it from your `.env` file:

```bash
# DRY_RUN_MODE=true  # Commented out
```

### Step 2: Enable Live Trading

```bash
export LIVE_CAPITAL_VERIFIED=true
```

Or in your `.env` file:

```bash
LIVE_CAPITAL_VERIFIED=true
```

### Step 3: Restart the Bot

```bash
./start.sh
```

### Step 4: Verify Live Mode

You should see:

```
🎯 TRADING MODE VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   DRY_RUN_MODE: false
   PAPER_MODE: false
   LIVE_CAPITAL_VERIFIED: true

   🔴 MODE: LIVE TRADING
   ⚠️  REAL MONEY AT RISK
   ⚠️  This bot will execute real trades with real capital
   ⚠️  Ensure this is INTENTIONAL
```

## Dry-Run Engine Features

The dry-run engine simulates realistic trading:

### Simulated Elements
- ✅ Order placement (market and limit orders)
- ✅ Order fills with realistic slippage (5 bps default)
- ✅ Trading fees (0.06% maker/taker for Coinbase)
- ✅ Position tracking (entries, exits, P&L)
- ✅ Balance updates
- ✅ Trade history

### Realistic Simulation
- Slippage on market orders
- Trading fees deducted from balance
- Delayed fills (configurable)
- Partial fills (if enabled)

### Performance Tracking
- Initial vs. current balance
- Total realized P&L
- Total unrealized P&L
- Total fees paid
- Number of trades
- Return percentage

## Configuration Options

You can customize the dry-run engine:

```python
from bot.dry_run_engine import DryRunEngine

# Create with custom settings
engine = DryRunEngine(
    initial_balance=50000.0,     # Starting balance
    currency="USD",              # Base currency
    slippage_bps=10,             # Slippage in basis points (10 = 0.1%)
    enable_realistic_fills=True  # Enable realistic fill delays
)
```

## Common Questions

### Q: Will my exchange API keys be used?
**A:** No. In dry-run mode, the bot never connects to real exchanges. Your API keys are not used for placing orders.

### Q: Can I test multiple exchanges simultaneously?
**A:** Yes! Configure credentials for all exchanges you want to test. All will run in simulation mode.

### Q: How long should I run dry-run mode?
**A:** At minimum, run it long enough to:
- See the startup banners
- Verify exchange configurations
- Watch a few simulated trades execute
- Review the validation summary

Typically 15-30 minutes is sufficient.

### Q: What if I see errors in dry-run mode?
**A:** Some errors are expected (e.g., no real market data). Focus on:
- Startup banners display correctly
- Validation summary is accurate
- Simulated trades execute without crashes
- Logs are clear and understandable

### Q: Can I switch back to dry-run mode after going live?
**A:** Yes! Simply set `DRY_RUN_MODE=true` again and restart.

### Q: Does dry-run mode use real market data?
**A:** The dry-run engine simulates fills at specified prices. For full backtesting with real historical data, use the backtest scripts instead.

## Troubleshooting

### Issue: Bot still tries to connect to real exchange

**Solution:** Ensure `DRY_RUN_MODE=true` is set BEFORE starting the bot:

```bash
export DRY_RUN_MODE=true
./start.sh
```

### Issue: Don't see dry-run banner

**Solution:** Check that `DRY_RUN_MODE` is set correctly:

```bash
echo $DRY_RUN_MODE  # Should output: true
```

### Issue: Validation summary shows 0 exchanges

**Solution:** Ensure exchange credentials are configured in `.env` file (even though they won't be used for real trading).

## Safety Reminders

- ✅ Always test in dry-run mode first
- ✅ Review all banners and validation summaries
- ✅ Understand what the bot will do before going live
- ✅ Start with small positions when going live
- ✅ Monitor closely when first enabling live trading
- ✅ Keep `DRY_RUN_MODE=true` as your default for testing

## Related Documentation

- `IMPLEMENTATION_SUMMARY_STARTUP_VALIDATION.md` - Startup validation details
- `bot/dry_run_engine.py` - Dry-run engine implementation
- `bot/startup_diagnostics.py` - Startup diagnostics
- `bot/startup_validation.py` - Startup validation

## Support

If you have questions or issues with dry-run mode:

1. Check this guide first
2. Review the startup logs
3. Verify environment variables are set correctly
4. Review the validation summary
5. Check related documentation files

Remember: **Dry-run mode is your safety net**. Use it liberally, test thoroughly, and go live with confidence!
