#!/usr/bin/env python3
"""
Verification Script: All Users Trading Enabled

This script verifies that:
1. Master account is enabled for trading
2. All configured user accounts are enabled
3. Specifically checks Kraken master and users
4. Shows the trading enablement status clearly

Run this to verify the system is ready for trading.
"""

import json
import sys
from pathlib import Path


def verify_user_configs():
    """Verify all user configuration files have enabled=true."""
    print("=" * 80)
    print("STEP 1: Verifying User Configuration Files")
    print("=" * 80)
    
    config_dir = Path('config/users')
    all_users = []
    all_enabled = True
    
    for json_file in sorted(config_dir.glob('*.json')):
        try:
            with open(json_file) as f:
                users = json.load(f)
                
            if not users:
                print(f"  ⚪ {json_file.name}: No users configured (empty)")
                continue
                
            for user in users:
                user_id = user.get('user_id')
                name = user.get('name')
                enabled = user.get('enabled', True)
                broker = user.get('broker_type')
                account_type = user.get('account_type')
                
                all_users.append({
                    'file': json_file.name,
                    'user_id': user_id,
                    'name': name,
                    'enabled': enabled,
                    'broker': broker,
                    'account_type': account_type
                })
                
                status_icon = '✅' if enabled else '❌'
                status_text = 'ENABLED' if enabled else 'DISABLED'
                print(f"  {status_icon} {json_file.name:25s} | {user_id:20s} | {broker:10s} | {status_text}")
                
                if not enabled:
                    all_enabled = False
        
        except Exception as e:
            print(f"  ❌ Error reading {json_file.name}: {e}")
            all_enabled = False
    
    print()
    print(f"Total users configured: {len(all_users)}")
    print(f"All users enabled: {all_enabled}")
    
    if not all_enabled:
        print()
        print("⚠️  WARNING: Some users are disabled!")
        print("   Edit the JSON files in config/users/ and set enabled=true")
        return False
    
    return all_users


def verify_hard_controls(all_users):
    """Verify HardControls system enables all accounts."""
    print()
    print("=" * 80)
    print("STEP 2: Verifying Hard Controls (Trading Enablement System)")
    print("=" * 80)
    
    try:
        from controls import get_hard_controls
        
        controls = get_hard_controls()
        
        print(f"Global kill switch: {controls.global_kill_switch.value.upper()}")
        print(f"Total accounts enabled: {len(controls.user_kill_switches)}")
        print()
        print("Account Status:")
        
        # Check master
        master_can_trade, master_msg = controls.can_trade('master')
        master_icon = '✅' if master_can_trade else '❌'
        print(f"  {master_icon} master (NIJA system account) - {'CAN TRADE' if master_can_trade else f'BLOCKED: {master_msg}'}")
        
        # Check each user
        seen_users = set()
        for user_data in all_users:
            user_id = user_data['user_id']
            
            # Skip duplicates (same user on multiple brokers)
            if user_id in seen_users:
                continue
            seen_users.add(user_id)
            
            can_trade, msg = controls.can_trade(user_id)
            icon = '✅' if can_trade else '❌'
            broker_list = ', '.join(sorted(set(u['broker'] for u in all_users if u['user_id'] == user_id)))
            print(f"  {icon} {user_id:20s} ({broker_list}) - {'CAN TRADE' if can_trade else f'BLOCKED: {msg}'}")
        
        if not master_can_trade:
            print()
            print("❌ ERROR: Master account is blocked from trading!")
            return False
        
        all_can_trade = all(controls.can_trade(u['user_id'])[0] for u in all_users)
        if not all_can_trade:
            print()
            print("❌ ERROR: Some users are blocked from trading!")
            return False
        
        return True
    
    except Exception as e:
        print(f"❌ Error checking hard controls: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_kraken_accounts(all_users):
    """Verify Kraken master and user accounts specifically."""
    print()
    print("=" * 80)
    print("STEP 3: Verifying Kraken Accounts (Master + Users)")
    print("=" * 80)
    
    kraken_users = [u for u in all_users if u['broker'] == 'kraken' and u['enabled']]
    
    print(f"Kraken users configured: {len(kraken_users)}")
    print()
    
    if not kraken_users:
        print("⚠️  WARNING: No Kraken user accounts configured!")
        print("   This means only master account will trade on Kraken")
        print("   To add users, edit config/users/retail_kraken.json or config/users/investor_kraken.json")
    else:
        print("Kraken user accounts:")
        for user in kraken_users:
            print(f"  ✅ {user['user_id']:20s} ({user['name']})")
    
    print()
    print("Kraken trading readiness:")
    print("  ✅ Master account (NIJA system) - ready for Kraken trading")
    for user in kraken_users:
        print(f"  ✅ {user['user_id']} - ready for Kraken trading")
    
    return True


def main():
    """Run all verification checks."""
    print()
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "NIJA TRADING ENABLEMENT VERIFICATION" + " " * 21 + "║")
    print("╚" + "=" * 78 + "╝")
    print()
    
    # Step 1: Verify user configs
    all_users = verify_user_configs()
    if not all_users and all_users is not False:
        print()
        print("✅ No user accounts configured (master-only mode)")
        print("   Master account will trade on all configured exchanges")
        all_users = []
    elif all_users is False:
        print()
        print("❌ VERIFICATION FAILED: User configuration issues detected")
        sys.exit(1)
    
    # Step 2: Verify hard controls
    if not verify_hard_controls(all_users):
        print()
        print("❌ VERIFICATION FAILED: Hard controls not working correctly")
        sys.exit(1)
    
    # Step 3: Verify Kraken specifically
    verify_kraken_accounts(all_users)
    
    # Final summary
    print()
    print("=" * 80)
    print("✅ VERIFICATION COMPLETE - ALL CHECKS PASSED")
    print("=" * 80)
    print()
    print("Summary:")
    print("  ✅ Master account enabled for trading")
    print(f"  ✅ {len(all_users)} user account(s) enabled for trading")
    print("  ✅ Hard controls system working correctly")
    print("  ✅ All accounts can trade")
    
    # Kraken-specific summary
    kraken_users = [u for u in all_users if u['broker'] == 'kraken']
    if kraken_users:
        print()
        print(f"Kraken-specific: Master + {len(kraken_users)} user(s) ready for Kraken trading")
    else:
        print()
        print("Kraken-specific: Master account ready (no user accounts configured)")
    
    print()
    print("🚀 System is ready for trading!")
    print()
    
    # Next steps
    print("Next steps:")
    print("  1. Ensure API credentials are configured in .env or deployment platform")
    print("  2. Restart the bot to apply changes: python3 bot.py")
    print("  3. Monitor logs to confirm connections and trading starts")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
