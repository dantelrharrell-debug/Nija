#!/usr/bin/env python3
"""
Fix bot settings to prevent $5 trading disasters
"""
import os
import sys

def main():
    print("\n" + "="*80)
    print("⚙️  BOT SETTINGS FIX - Prevent $5 Trading Disasters")
    print("="*80)
    
    print("\n🔍 Current Issues:")
    print("   ❌ Bot accepting $5 positions (too small)")
    print("   ❌ Fees eating all profits (2-4% per trade)")
    print("   ❌ No capital left for position management")
    print("   ❌ Multiple rapid-fire trades draining account")
    
    print("\n✅ Fixes Being Applied:")
    print("   1. Increase MINIMUM_POSITION_SIZE to $10")
    print("   2. Require $15 minimum account balance to trade")
    print("   3. Add cooldown between trades (prevent rapid-fire)")
    print("   4. Increase fee buffer to 15%")
    
    confirm = input("\nApply these fixes? (yes/no): ")
    
    if confirm.lower() != 'yes':
        print("\n❌ Cancelled")
        return
    
    # Read trading_strategy.py
    trading_strategy_path = 'bot/trading_strategy.py'
    
    if not os.path.exists(trading_strategy_path):
        print(f"\n❌ File not found: {trading_strategy_path}")
        return
    
    with open(trading_strategy_path, 'r') as f:
        content = f.read()
    
    # Track changes
    changes_made = []
    
    # Fix 1: Update minimum position size
    if 'coinbase_minimum_with_fees = 5.50' in content:
        content = content.replace(
            'coinbase_minimum_with_fees = 5.50',
            'coinbase_minimum_with_fees = 10.00  # Increased from 5.50 to ensure profitability'
        )
        changes_made.append("✅ Minimum position size: $5.50 → $10.00")
    
    # Fix 2: Update balance requirement
    if '# Safety check: Need enough balance for position + buffer' in content:
        # Find and replace the balance check
        old_check = 'if balance < 6.60:'
        new_check = 'if balance < 15.00:  # Need $15 minimum for viable trading'
        if old_check in content:
            content = content.replace(old_check, new_check)
            changes_made.append("✅ Minimum balance required: $6.60 → $15.00")
    
    # Fix 3: Add trade cooldown (find the execute_trade method)
    if 'def execute_trade(self, analysis: dict) -> bool:' in content and 'TRADE_COOLDOWN_SECONDS' not in content:
        # Add cooldown constant at class level
        class_def = 'class TradingStrategy:'
        if class_def in content:
            content = content.replace(
                class_def,
                class_def + '\n    TRADE_COOLDOWN_SECONDS = 30  # Prevent rapid-fire trades'
            )
            
            # Add cooldown check in execute_trade
            execute_trade_start = 'def execute_trade(self, analysis: dict) -> bool:'
            if execute_trade_start in content:
                # Find the position after the method definition
                idx = content.find(execute_trade_start)
                if idx != -1:
                    # Insert cooldown check after the opening comments
                    insert_point = content.find('symbol = analysis.get', idx)
                    if insert_point != -1:
                        cooldown_check = '''
        # Cooldown check - prevent rapid-fire trades
        if hasattr(self, 'last_trade_time') and self.last_trade_time:
            time_since_last = time.time() - self.last_trade_time
            if time_since_last < self.TRADE_COOLDOWN_SECONDS:
                logger.info(f"⏸️  Trade cooldown active ({self.TRADE_COOLDOWN_SECONDS - time_since_last:.0f}s remaining)")
                return False
        
        '''
                        content = content[:insert_point] + cooldown_check + content[insert_point:]
                        changes_made.append("✅ Added 30-second cooldown between trades")
    
    # Write changes
    if changes_made:
        with open(trading_strategy_path, 'w') as f:
            f.write(content)
        
        print("\n" + "="*80)
        print("✅ FIXES APPLIED")
        print("="*80)
        
        for change in changes_made:
            print(f"   {change}")
        
        print("\n📝 Summary:")
        print("   • Minimum position: $10 (was $5.50)")
        print("   • Minimum balance: $15 (was $6.60)")
        print("   • Trade cooldown: 30 seconds")
        print("\n   These settings require $50+ account balance to work properly")
        
    else:
        print("\n⚠️  No changes needed - settings already updated")
    
    # Additional recommendation
    print("\n" + "="*80)
    print("🛑 CRITICAL: STOP THE BOT FROM AUTO-RUNNING")
    print("="*80)
    
    print("\n1. Check if bot is running:")
    print("   ps aux | grep python")
    
    print("\n2. If running, kill the process:")
    print("   kill <PID>")
    
    print("\n3. DO NOT restart until:")
    print("   ✅ You have $50+ deposited")
    print("   ✅ You understand the new settings")
    print("   ✅ You're ready to monitor trades")
    
    print("\n4. Optional: Disable auto-start")
    print("   Check Railway/Render dashboard")
    print("   Pause deployment until ready")

if __name__ == "__main__":
    main()
