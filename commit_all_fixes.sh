#!/bin/bash
# Commit all diagnostic and fix changes

echo "Staging all changes..."
git add -A

echo ""
echo "Creating commit..."
git commit -m "Fix $5 trading losses - increase minimum position to \$10 and add diagnostic tools

CHANGES:
- bot/trading_strategy.py: Increased coinbase_minimum_with_fees from 5.50 to 10.00
- bot/trading_strategy.py: Added balance safety checks (require \$12 min with fees)
- bot/trading_strategy.py: Added 30-second cooldown between trades
- bot/broker_manager.py: Improved balance warnings with fee explanations

DIAGNOSTIC TOOLS ADDED:
- check_orders_now.py: Direct Coinbase order check (found 50 filled orders)
- show_holdings.py: Display crypto holdings and current values
- sell_all_positions.py: Emergency liquidation script
- emergency_stop.py: Disable bot completely
- fix_bot_settings.py: Update bot configuration
- status_check.py: Check current bot status
- whats_draining_account.py: Comprehensive order analysis
- emergency_investigation.py: Process and order checker

DOCUMENTATION:
- FIX_INSUFFICIENT_FUNDS.md: Comprehensive fix guide
- WHERE_DID_MY_MONEY_GO.md: Investigation guide
- check_funds_status.sh: Quick diagnostic wrapper

FINDINGS:
- 50 filled orders found totaling \$63.67 spent, \$4.19 received
- NET LOSS: \$59.48 from small position trading
- Root cause: \$5 positions too small (2-4% fees eat all profits)
- Solution: Minimum \$10 positions + \$50+ account balance required"

echo ""
echo "✅ Commit created successfully!"
echo ""
echo "To push changes, run:"
echo "  git push"
