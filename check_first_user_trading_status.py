#!/usr/bin/env python3
"""
Check First User Trading Status and Account Balance

This script answers two key questions:
1. Is NIJA trading for the 1st user (Daivon Frazier)?
2. How much money does NIJA have to trade with in the user's account?

Usage:
    python check_first_user_trading_status.py
"""

import sys
import os
from datetime import datetime

# Load environment variables FIRST before importing anything else
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If dotenv not available, try to read .env manually
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value.strip('"').strip("'")

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_user_system():
    """Check if user management system is initialized."""
    try:
        from auth import get_user_manager, get_api_key_manager
        from execution import get_permission_validator
        from controls import get_hard_controls
        
        # Try to load user database
        try:
            from init_user_system import load_user_database
            load_user_database()
        except:
            pass
        
        return True
    except Exception as e:
        print(f"⚠️  User management system not available: {e}")
        return False


def check_first_user_status():
    """Check if the first user (Daivon Frazier) is set up and trading."""
    
    print("\n" + "=" * 80)
    print("NIJA FIRST USER TRADING STATUS CHECK")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 80)
    
    # Check if user management system exists
    has_user_system = check_user_system()
    
    if has_user_system:
        print("\n📋 USER MANAGEMENT SYSTEM: ✅ Available")
        
        try:
            from auth import get_user_manager
            from execution import get_permission_validator
            from controls import get_hard_controls
            
            user_mgr = get_user_manager()
            validator = get_permission_validator()
            controls = get_hard_controls()
            
            # Check for Daivon Frazier
            user_id = "daivon_frazier"
            user = user_mgr.get_user(user_id)
            
            if user:
                print(f"\n👤 FIRST USER: Daivon Frazier (ID: {user_id})")
                print(f"   Email: {user.get('email', 'N/A')}")
                print(f"   Tier: {user.get('subscription_tier', 'N/A')}")
                print(f"   Created: {user.get('created_at', 'N/A')}")
                
                # Check if user is enabled
                is_enabled = user.get('enabled', False)
                print(f"\n   Account Status: {'✅ ENABLED' if is_enabled else '🔴 DISABLED'}")
                
                # Check trading permissions
                can_trade, error = controls.can_trade(user_id)
                if can_trade:
                    print(f"   Trading Status: ✅ ACTIVE - User can trade")
                else:
                    print(f"   Trading Status: 🔴 BLOCKED - {error}")
                
                # Get permissions
                perms = validator.get_user_permissions(user_id)
                if perms:
                    print(f"\n   Trading Limits:")
                    print(f"   • Max position size: ${perms.max_position_size_usd:.2f}")
                    print(f"   • Max daily loss: ${perms.max_daily_loss_usd:.2f}")
                    print(f"   • Max concurrent positions: {perms.max_positions}")
                    print(f"   • Allowed pairs: {len(perms.allowed_pairs or [])} pairs")
                
            else:
                print(f"\n❌ FIRST USER NOT FOUND")
                print(f"   User ID '{user_id}' does not exist in the system")
                print(f"   The user may need to be set up first")
                
        except Exception as e:
            print(f"\n❌ Error checking user status: {e}")
            import traceback
            traceback.print_exc()
    
    else:
        print("\n📋 USER MANAGEMENT SYSTEM: ❌ Not Available")
        print("   Note: The layered user management system may not be initialized")
    
    # Check Coinbase account balance (this works regardless of user system)
    print("\n" + "-" * 80)
    print("COINBASE ACCOUNT BALANCE")
    print("-" * 80)
    
    try:
        from broker_manager import CoinbaseBroker
        
        broker = CoinbaseBroker()
        
        if broker.connect():
            print("\n✅ Connected to Coinbase")
            
            # Get account balance
            balance_data = broker.get_account_balance()
            
            # Extract key balance information
            trading_balance = balance_data.get('trading_balance', 0)
            usd_balance = balance_data.get('usd', 0)
            usdc_balance = balance_data.get('usdc', 0)
            consumer_usd = balance_data.get('consumer_usd', 0)
            consumer_usdc = balance_data.get('consumer_usdc', 0)
            crypto = balance_data.get('crypto', {})
            
            print(f"\n💰 AVAILABLE FOR TRADING:")
            print(f"   ${trading_balance:,.2f} USD")
            print()
            print(f"   Breakdown:")
            print(f"   • Advanced Trade USD:  ${usd_balance:,.2f}")
            print(f"   • Advanced Trade USDC: ${usdc_balance:,.2f}")
            
            if crypto:
                print(f"\n   Crypto Holdings:")
                total_crypto_value = 0
                for currency, amount in crypto.items():
                    print(f"   • {currency}: {amount:.8f}")
            
            # Show consumer wallet if it has funds
            consumer_total = consumer_usd + consumer_usdc
            if consumer_total > 0:
                print(f"\n💡 Consumer Wallet (Not available for trading):")
                print(f"   • Consumer USD:  ${consumer_usd:,.2f}")
                print(f"   • Consumer USDC: ${consumer_usdc:,.2f}")
                print(f"   • Total: ${consumer_total:,.2f}")
                print()
                print(f"   ⚠️  These funds need to be transferred to Advanced Trade")
                print(f"      to be available for bot trading")
            
            # Trading readiness assessment
            print("\n" + "-" * 80)
            print("TRADING READINESS ASSESSMENT")
            print("-" * 80)
            
            if trading_balance >= 100:
                print(f"\n✅ EXCELLENT: Bot has ${trading_balance:,.2f} to trade with")
                print(f"   This is sufficient for multiple positions")
                print(f"   Bot can execute its strategy effectively")
            elif trading_balance >= 50:
                print(f"\n✅ GOOD: Bot has ${trading_balance:,.2f} to trade with")
                print(f"   This is sufficient for small positions")
                print(f"   Consider adding more for better diversification")
            elif trading_balance >= 10:
                print(f"\n⚠️  LIMITED: Bot has ${trading_balance:,.2f} to trade with")
                print(f"   This limits position sizes significantly")
                print(f"   Recommended: Add at least $50 more")
            elif trading_balance > 0:
                print(f"\n⚠️  VERY LIMITED: Bot has only ${trading_balance:,.2f}")
                print(f"   This is too low for effective trading")
                print(f"   Recommended: Add at least $100")
            else:
                print(f"\n❌ NO FUNDS: Bot has $0.00 to trade with")
                print(f"   Bot cannot execute any trades")
                
                if consumer_total > 0:
                    print(f"\n   💡 SOLUTION: Transfer ${consumer_total:,.2f} from Consumer wallet")
                    print(f"      1. Go to: https://www.coinbase.com/advanced-portfolio")
                    print(f"      2. Click 'Deposit' → 'From Coinbase'")
                    print(f"      3. Transfer funds (instant, no fees)")
                else:
                    print(f"\n   💡 SOLUTION: Deposit funds to Coinbase")
                    print(f"      Recommended: $100-200 USD or USDC")
                    print(f"      To: Advanced Trade portfolio")
            
        else:
            print("\n❌ Could not connect to Coinbase")
            print("   Check API credentials in environment variables")
            print("   Required: COINBASE_API_KEY, COINBASE_API_SECRET")
            
    except Exception as e:
        print(f"\n❌ Error checking Coinbase balance: {e}")
        import traceback
        traceback.print_exc()
    
    # Final summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    print("\nQUESTION 1: Is NIJA trading for the 1st user?")
    if has_user_system:
        try:
            from auth import get_user_manager
            from controls import get_hard_controls
            user_mgr = get_user_manager()
            controls = get_hard_controls()
            user = user_mgr.get_user("daivon_frazier")
            if user:
                can_trade, _ = controls.can_trade("daivon_frazier")
                if user.get('enabled', False) and can_trade:
                    print("   ✅ YES - User account is enabled and can trade")
                else:
                    print("   🔴 NO - User account is disabled or blocked from trading")
            else:
                print("   ❌ NO - User account not found in system")
                print()
                print("   📝 NEXT STEPS:")
                print("   1. Run: python init_user_system.py")
                print("   2. Run: python setup_user_daivon.py")
                print("   3. Run: python manage_user_daivon.py enable")
        except:
            print("   ❓ UNKNOWN - Could not verify user status")
    else:
        print("   ⚠️  User management system not initialized")
        print("   Bot can still trade using direct Coinbase credentials")
        print()
        print("   📝 TO ENABLE USER SYSTEM:")
        print("   1. Run: python init_user_system.py")
        print("   2. Run: python setup_user_daivon.py")
    
    print("\nQUESTION 2: How much does NIJA have to trade with?")
    try:
        from broker_manager import CoinbaseBroker
        broker = CoinbaseBroker()
        if broker.connect():
            balance_data = broker.get_account_balance()
            trading_balance = balance_data.get('trading_balance', 0)
            print(f"   💰 ${trading_balance:,.2f} USD available for trading")
        else:
            print("   ❌ Could not retrieve balance (connection failed)")
            print()
            print("   📝 TO CHECK BALANCE:")
            print("   Run this script in production environment (Railway/Render)")
            print("   Or run: python check_actual_coinbase_balance.py")
    except:
        print("   ❌ Could not retrieve balance (error occurred)")
        print()
        print("   📝 TO CHECK BALANCE:")
        print("   Run this script in production environment with internet access")
        print("   Or run: python check_actual_coinbase_balance.py")
    
    print("\n" + "-" * 80)
    print("📄 For detailed analysis, see: FIRST_USER_STATUS_REPORT.md")
    print("-" * 80)
    
    print("\n" + "=" * 80)
    print("END OF REPORT")
    print("=" * 80 + "\n")


def main():
    """Main execution."""
    try:
        check_first_user_status()
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
