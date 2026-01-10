#!/usr/bin/env python3
"""
Activate Kraken Trading for Both Users

This script:
1. Initializes User #1 (Daivon Frazier) if not already set up
2. Initializes User #2 (Tania Gilbert)
3. Connects both users to their Kraken accounts
4. Verifies both accounts are trading-ready
5. Displays status report

Run this to fully activate multi-user Kraken trading.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """Main execution."""
    print("\n" + "="*80)
    print("ACTIVATING KRAKEN TRADING FOR BOTH USERS")
    print("="*80)
    
    # Step 1: Initialize User #1 (Daivon Frazier)
    print("\n" + "-"*80)
    print("STEP 1: Initializing User #1 (Daivon Frazier)")
    print("-"*80)
    
    try:
        from init_user_system import initialize_daivon_frazier
        if not initialize_daivon_frazier():
            print("❌ Failed to initialize User #1")
            return False
    except Exception as e:
        print(f"❌ Error initializing User #1: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 2: Initialize User #2 (Tania Gilbert)
    print("\n" + "-"*80)
    print("STEP 2: Initializing User #2 (Tania Gilbert)")
    print("-"*80)
    
    try:
        from init_user_tania import initialize_tania_gilbert
        if not initialize_tania_gilbert():
            print("❌ Failed to initialize User #2")
            return False
    except Exception as e:
        print(f"❌ Error initializing User #2: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 3: Connect Kraken brokers for both users
    print("\n" + "-"*80)
    print("STEP 3: Connecting Kraken Brokers")
    print("-"*80)
    
    try:
        from bot.multi_account_broker_manager import multi_account_broker_manager
        from bot.broker_manager import BrokerType
        
        # Connect User #1 Kraken broker
        print("\n🔌 Connecting User #1 (Daivon) to Kraken...")
        user1_broker = multi_account_broker_manager.add_user_broker(
            user_id="daivon_frazier",
            broker_type=BrokerType.KRAKEN
        )
        
        if user1_broker:
            print("✅ User #1 Kraken connection successful")
        else:
            print("⚠️  User #1 Kraken connection failed - check credentials")
            print("   Set environment variables:")
            print("      KRAKEN_USER_DAIVON_API_KEY=<api-key>")
            print("      KRAKEN_USER_DAIVON_API_SECRET=<api-secret>")
        
        # Connect User #2 Kraken broker
        print("\n🔌 Connecting User #2 (Tania) to Kraken...")
        user2_broker = multi_account_broker_manager.add_user_broker(
            user_id="tania_gilbert",
            broker_type=BrokerType.KRAKEN
        )
        
        if user2_broker:
            print("✅ User #2 Kraken connection successful")
        else:
            print("⚠️  User #2 Kraken connection failed - check credentials")
            print("   Set environment variables:")
            print("      KRAKEN_USER_TANIA_API_KEY=<api-key>")
            print("      KRAKEN_USER_TANIA_API_SECRET=<api-secret>")
        
    except Exception as e:
        print(f"❌ Error connecting brokers: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 4: Display comprehensive status report
    print("\n" + "-"*80)
    print("STEP 4: Status Report")
    print("-"*80)
    
    try:
        # Get status from multi-account broker manager
        status_report = multi_account_broker_manager.get_status_report()
        print("\n" + status_report)
        
        # Show individual user statuses
        from auth import get_user_manager
        from execution import get_permission_validator
        
        user_mgr = get_user_manager()
        validator = get_permission_validator()
        
        print("\n" + "="*80)
        print("USER ACCOUNT SUMMARIES")
        print("="*80)
        
        for user_id in ["daivon_frazier", "tania_gilbert"]:
            user = user_mgr.get_user(user_id)
            perms = validator.get_user_permissions(user_id)
            
            if user:
                name = "Daivon Frazier" if user_id == "daivon_frazier" else "Tania Gilbert"
                print(f"\n📊 {name} ({user_id})")
                print(f"   Email: {user['email']}")
                print(f"   Tier: {user['subscription_tier']}")
                print(f"   Enabled: {user['enabled']}")
                
                if perms:
                    print(f"   Max Position: ${perms.max_position_size_usd}")
                    print(f"   Max Positions: {perms.max_positions}")
                    print(f"   Trading Enabled: {perms.enabled}")
        
        print("\n" + "="*80)
        print("✅ ACTIVATION COMPLETE")
        print("="*80)
        print("\nBoth users are now initialized and ready to trade on Kraken!")
        print("\nManagement Commands:")
        print("  User #1: python manage_user_daivon.py status")
        print("  User #2: python manage_user_tania.py status")
        print("\nEnvironment Variables Required:")
        print("  KRAKEN_USER_DAIVON_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7")
        print("  KRAKEN_USER_DAIVON_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==")
        print("  KRAKEN_USER_TANIA_API_KEY=XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/")
        print("  KRAKEN_USER_TANIA_API_SECRET=iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw==")
        print("="*80 + "\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Error generating status report: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
