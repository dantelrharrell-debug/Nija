#!/usr/bin/env python3
"""
Check all users in the NIJA system and provide status overview.

This script checks the status of all registered users and provides
a summary of their trading activity and account status.

Usage:
    python check_all_users.py
    python check_all_users.py --detailed
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import get_user_manager, get_api_key_manager
from execution import get_permission_validator
from controls import get_hard_controls


def load_users():
    """Load user database."""
    try:
        from init_user_system import load_user_database
        load_user_database()
        return True
    except Exception as e:
        print(f"⚠️  Warning: Could not load user database: {e}")
        return False


def check_all_users(detailed=False):
    """Check status of all users."""
    
    # Load user database
    if not load_users():
        print("❌ Failed to load user database")
        print("   Run 'python init_user_system.py' first to initialize users.")
        return
    
    user_mgr = get_user_manager()
    api_mgr = get_api_key_manager()
    validator = get_permission_validator()
    controls = get_hard_controls()
    
    users = user_mgr.users
    
    if not users:
        print("\n📋 No users found in the system.")
        print("   Add users with 'python init_user_system.py' or setup scripts.")
        return
    
    print("\n" + "="*80)
    print(f"NIJA USER STATUS CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("="*80)
    
    # Summary
    total_users = len(users)
    active_users = sum(1 for u in users.values() if u.get('enabled', False))
    inactive_users = total_users - active_users
    
    print(f"\n📊 SYSTEM SUMMARY")
    print(f"   Total Users: {total_users}")
    print(f"   Active: {active_users}")
    print(f"   Inactive: {inactive_users}")
    
    # Individual user status
    print(f"\n👥 USER STATUS")
    print("-" * 80)
    
    for user_id, user_data in users.items():
        enabled = user_data.get('enabled', False)
        email = user_data.get('email', 'N/A')
        tier = user_data.get('subscription_tier', 'N/A')
        
        # Check if can trade
        can_trade, error = controls.can_trade(user_id)
        
        # Get brokers
        brokers = api_mgr.list_user_brokers(user_id)
        
        # Get permissions
        perms = validator.get_user_permissions(user_id)
        
        # Status icon
        if enabled and can_trade:
            status_icon = "🟢"
            status_text = "ACTIVE"
        elif not enabled:
            status_icon = "🔴"
            status_text = "DISABLED"
        else:
            status_icon = "🟡"
            status_text = f"BLOCKED ({error})"
        
        print(f"\n{status_icon} {user_id}")
        print(f"   Email: {email}")
        print(f"   Tier: {tier}")
        print(f"   Status: {status_text}")
        print(f"   Brokers: {', '.join(brokers) if brokers else 'None'}")
        
        if perms and detailed:
            print(f"   Max Position: ${perms.max_position_size_usd}")
            print(f"   Max Daily Loss: ${perms.max_daily_loss_usd}")
            print(f"   Max Positions: {perms.max_positions}")
            if perms.allowed_pairs:
                print(f"   Allowed Pairs: {len(perms.allowed_pairs)} pairs")
    
    print("\n" + "-" * 80)
    
    # Tiers breakdown
    tier_counts = {}
    for user_data in users.values():
        tier = user_data.get('subscription_tier', 'unknown')
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    
    print(f"\n📈 BY SUBSCRIPTION TIER")
    for tier, count in sorted(tier_counts.items()):
        print(f"   {tier.capitalize()}: {count}")
    
    # Broker breakdown
    broker_counts = {}
    for user_id in users.keys():
        brokers = api_mgr.list_user_brokers(user_id)
        for broker in brokers:
            broker_counts[broker] = broker_counts.get(broker, 0) + 1
    
    print(f"\n🔗 BY BROKER")
    for broker, count in sorted(broker_counts.items()):
        print(f"   {broker.capitalize()}: {count}")
    
    print("\n" + "="*80)
    print("✅ Check complete")
    print("="*80 + "\n")


def main():
    """Main execution."""
    detailed = '--detailed' in sys.argv or '-d' in sys.argv
    
    try:
        check_all_users(detailed=detailed)
    except Exception as e:
        print(f"\n❌ Error checking users: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
