#!/usr/bin/env python3
"""
Simple script to answer: Is NIJA trading for user #1?

This provides a quick YES/NO answer with next steps.

Usage:
    python is_user1_trading.py
"""

import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USER_DB_FILE = os.path.join(os.path.dirname(__file__), 'users_db.json')


def check_user1_trading():
    """Check if user #1 (Daivon Frazier) is trading."""
    
    print("\n" + "=" * 70)
    print("IS NIJA TRADING FOR USER #1?")
    print(f"Checked: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70 + "\n")
    
    # Check if user database exists
    if not os.path.exists(USER_DB_FILE):
        print("❌ NO - User #1 is NOT trading\n")
        print("Reason: User database not initialized")
        print("User #1 (Daivon Frazier) has not been set up yet.\n")
        print("=" * 70)
        print("NEXT STEPS TO ENABLE USER #1:")
        print("=" * 70)
        print("\n1. Initialize the user system:")
        print("   python init_user_system.py\n")
        print("2. Set up Daivon Frazier:")
        print("   python setup_user_daivon.py\n")
        print("3. Enable trading for the user:")
        print("   python manage_user_daivon.py enable\n")
        print("4. Verify user is trading:")
        print("   python check_first_user_trading_status.py\n")
        print("=" * 70 + "\n")
        return False
    
    # User database exists, check user status
    try:
        from auth import get_user_manager
        from controls import get_hard_controls
        from init_user_system import load_user_database
        
        # Load the database
        load_user_database()
        
        user_mgr = get_user_manager()
        controls = get_hard_controls()
        
        # Check for user #1 (Daivon Frazier)
        user_id = "daivon_frazier"
        user = user_mgr.get_user(user_id)
        
        if not user:
            print("❌ NO - User #1 is NOT trading\n")
            print("Reason: User #1 (Daivon Frazier) not found in database")
            print("\n" + "=" * 70)
            print("NEXT STEPS:")
            print("=" * 70)
            print("\n1. Set up Daivon Frazier:")
            print("   python setup_user_daivon.py\n")
            print("2. Enable trading:")
            print("   python manage_user_daivon.py enable\n")
            print("=" * 70 + "\n")
            return False
        
        # User exists, check if enabled and can trade
        is_enabled = user.get('enabled', False)
        can_trade, error = controls.can_trade(user_id)
        
        if is_enabled and can_trade:
            print("✅ YES - User #1 IS trading\n")
            print(f"User: Daivon Frazier ({user_id})")
            print(f"Email: {user.get('email', 'N/A')}")
            print(f"Tier: {user.get('subscription_tier', 'N/A')}")
            print(f"Status: ENABLED and ACTIVE")
            print("\n" + "=" * 70)
            print("USER #1 IS ACTIVELY TRADING")
            print("=" * 70)
            print("\nTo check detailed status:")
            print("  python check_first_user_trading_status.py")
            print("\nTo manage user:")
            print("  python manage_user_daivon.py status")
            print("=" * 70 + "\n")
            return True
        else:
            print("❌ NO - User #1 is NOT trading\n")
            print(f"User: Daivon Frazier ({user_id})")
            if not is_enabled:
                print("Reason: User account is DISABLED")
            else:
                print(f"Reason: Trading blocked - {error}")
            
            print("\n" + "=" * 70)
            print("NEXT STEPS:")
            print("=" * 70)
            print("\n1. Enable the user:")
            print("   python manage_user_daivon.py enable\n")
            print("2. Check status:")
            print("   python manage_user_daivon.py status\n")
            print("=" * 70 + "\n")
            return False
            
    except Exception as e:
        print(f"⚠️  ERROR - Could not check user status\n")
        print(f"Error: {e}\n")
        print("=" * 70)
        print("TROUBLESHOOTING:")
        print("=" * 70)
        print("\n1. Make sure dependencies are installed:")
        print("   pip install -r requirements.txt\n")
        print("2. Check if user system is initialized:")
        print("   python init_user_system.py\n")
        print("3. Run detailed check:")
        print("   python check_first_user_trading_status.py\n")
        print("=" * 70 + "\n")
        return False


def main():
    """Main execution."""
    try:
        is_trading = check_user1_trading()
        sys.exit(0 if is_trading else 1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
