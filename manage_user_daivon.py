#!/usr/bin/env python3
"""
User Management Interface for Daivon Frazier

This script provides a simple interface to manage Daivon Frazier's trading account.
You can enable/disable trading and check status without affecting other users.

Usage:
    python manage_user_daivon.py status        # Check current status
    python manage_user_daivon.py enable        # Enable trading
    python manage_user_daivon.py disable       # Disable trading
    python manage_user_daivon.py info          # Show detailed info
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import get_user_manager, get_api_key_manager
from execution import get_permission_validator
from controls import get_hard_controls

# Load user database on import
try:
    from init_user_system import load_user_database
    load_user_database()
except Exception as e:
    print(f"⚠️  Warning: Could not load user database: {e}")
    print("   Run 'python init_user_system.py' first to initialize users.")


def print_status(user_id="daivon_frazier"):
    """Print user trading status."""
    user_mgr = get_user_manager()
    controls = get_hard_controls()
    validator = get_permission_validator()
    
    user = user_mgr.get_user(user_id)
    if not user:
        print(f"❌ User {user_id} not found!")
        print("Run setup_user_daivon.py first to create the user.")
        return False
    
    perms = validator.get_user_permissions(user_id)
    can_trade, error = controls.can_trade(user_id)
    
    print("\n" + "="*60)
    print(f"USER: Daivon Frazier ({user_id})")
    print("="*60)
    
    # Trading status
    if user['enabled'] and can_trade:
        print("STATUS: ✅ TRADING ENABLED")
    elif not user['enabled']:
        print("STATUS: 🛑 TRADING DISABLED (User disabled)")
    else:
        print(f"STATUS: 🛑 TRADING DISABLED ({error})")
    
    print(f"\nEmail: {user['email']}")
    print(f"Tier: {user['subscription_tier']}")
    print(f"Created: {user['created_at']}")
    print(f"Enabled: {user['enabled']}")
    
    if perms:
        print(f"\nPERMISSIONS:")
        print(f"  Max position: ${perms.max_position_size_usd}")
        print(f"  Max daily loss: ${perms.max_daily_loss_usd}")
        print(f"  Max positions: {perms.max_positions}")
        print(f"  Allowed pairs: {len(perms.allowed_pairs or [])} pairs")
        print(f"  Trade only: {perms.trade_only}")
        print(f"  Enabled: {perms.enabled}")
    
    print("="*60 + "\n")
    return True


def show_detailed_info(user_id="daivon_frazier"):
    """Show detailed user information."""
    user_mgr = get_user_manager()
    api_mgr = get_api_key_manager()
    validator = get_permission_validator()
    controls = get_hard_controls()
    
    user = user_mgr.get_user(user_id)
    if not user:
        print(f"❌ User {user_id} not found!")
        return False
    
    perms = validator.get_user_permissions(user_id)
    brokers = api_mgr.list_user_brokers(user_id)
    
    print("\n" + "="*60)
    print(f"DETAILED INFO: Daivon Frazier")
    print("="*60)
    
    print(f"\n📋 ACCOUNT INFO:")
    print(f"  User ID: {user_id}")
    print(f"  Email: {user['email']}")
    print(f"  Tier: {user['subscription_tier']}")
    print(f"  Created: {user['created_at']}")
    print(f"  Enabled: {user['enabled']}")
    
    print(f"\n🔐 API CONNECTIONS:")
    if brokers:
        for broker in brokers:
            creds = api_mgr.get_user_api_key(user_id, broker)
            if creds:
                print(f"  ✅ {broker.upper()}: Connected")
                print(f"     API Key: {creds['api_key'][:20]}...")
    else:
        print("  No brokers configured")
    
    print(f"\n⚙️  PERMISSIONS:")
    if perms:
        print(f"  Max position size: ${perms.max_position_size_usd}")
        print(f"  Max daily loss: ${perms.max_daily_loss_usd}")
        print(f"  Max concurrent positions: {perms.max_positions}")
        print(f"  Trading enabled: {perms.enabled}")
        print(f"  Trade only mode: {perms.trade_only}")
        
        if perms.allowed_pairs:
            print(f"\n  Allowed pairs ({len(perms.allowed_pairs)}):")
            for pair in perms.allowed_pairs:
                print(f"    • {pair}")
    
    print(f"\n🛡️  SAFETY CONTROLS:")
    print(f"  Position size limits: {controls.MIN_POSITION_PCT*100:.0f}% - {controls.MAX_POSITION_PCT*100:.0f}% of balance")
    print(f"  Max daily trades: {controls.MAX_DAILY_TRADES}")
    print(f"  Error threshold: {controls.ERROR_THRESHOLD} errors")
    print(f"  Strategy locked: {controls.strategy_locked}")
    
    # Check if user can trade
    can_trade, error = controls.can_trade(user_id)
    print(f"\n✓ Can trade: {can_trade}")
    if error:
        print(f"  Error: {error}")
    
    print("="*60 + "\n")
    return True


def enable_trading(user_id="daivon_frazier"):
    """Enable trading for user."""
    user_mgr = get_user_manager()
    controls = get_hard_controls()
    
    print(f"\n🔓 Enabling trading for {user_id}...")
    
    # Enable user
    success = user_mgr.enable_user(user_id)
    if not success:
        print(f"❌ Failed to enable user {user_id}")
        return False
    
    # Reset kill switch if needed
    controls.reset_user_kill_switch(user_id)
    
    # Verify
    can_trade, error = controls.can_trade(user_id)
    
    if can_trade:
        print(f"✅ Trading enabled for {user_id}")
        print_status(user_id)
    else:
        print(f"⚠️  User enabled but cannot trade: {error}")
        print_status(user_id)
    
    return True


def disable_trading(user_id="daivon_frazier"):
    """Disable trading for user."""
    user_mgr = get_user_manager()
    
    print(f"\n🔒 Disabling trading for {user_id}...")
    
    success = user_mgr.disable_user(user_id)
    if not success:
        print(f"❌ Failed to disable user {user_id}")
        return False
    
    print(f"✅ Trading disabled for {user_id}")
    print_status(user_id)
    return True


def print_usage():
    """Print usage information."""
    print("\nUsage: python manage_user_daivon.py <command>")
    print("\nCommands:")
    print("  status    - Show current trading status")
    print("  enable    - Enable trading for user")
    print("  disable   - Disable trading for user")
    print("  info      - Show detailed user information")
    print("\nExamples:")
    print("  python manage_user_daivon.py status")
    print("  python manage_user_daivon.py enable")
    print("  python manage_user_daivon.py disable")
    print("  python manage_user_daivon.py info")
    print()


def main():
    """Main execution."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    try:
        if command == "status":
            print_status()
        elif command == "enable":
            enable_trading()
        elif command == "disable":
            disable_trading()
        elif command == "info":
            show_detailed_info()
        elif command in ["help", "-h", "--help"]:
            print_usage()
        else:
            print(f"❌ Unknown command: {command}")
            print_usage()
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
