#!/usr/bin/env python3
"""
Execute Solutions B and C - Setup Kraken Trading

This script guides you through implementing both:
- Solution B: Configure Kraken credentials  
- Solution C: Initialize multi-user system with User #1

Usage:
    python3 execute_solutions_b_and_c.py
"""

import os
import sys
import subprocess

def print_header(title):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print formatted section"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def check_dependencies():
    """Check if required dependencies are installed"""
    print_section("Checking Dependencies")
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        print("  ✅ Kraken SDK installed (krakenex + pykrakenapi)")
        return True
    except ImportError:
        print("  ❌ Kraken SDK NOT installed")
        print("\n  Install with:")
        print("     pip install krakenex pykrakenapi")
        print("  Or:")
        print("     pip install -r requirements.txt")
        return False

def check_user_database():
    """Check if user database exists"""
    print_section("Checking User Database")
    
    db_file = os.path.join(os.path.dirname(__file__), 'users_db.json')
    
    if os.path.exists(db_file):
        print(f"  ✅ User database found: {db_file}")
        return True
    else:
        print(f"  ℹ️  User database not found: {db_file}")
        print("     Will need to initialize")
        return False

def solution_b_instructions():
    """Print instructions for Solution B"""
    print_header("SOLUTION B: Configure Kraken Credentials")
    
    print("\n📋 What Solution B Does:")
    print("  - Sets up Kraken API credentials in environment")
    print("  - Enables bot to trade on Kraken")
    print("  - Lower fees (~0.16% vs 0.5-1.5%)")
    
    print("\n⚠️  IMPORTANT: Solution B requires Railway dashboard access")
    print("   This script CANNOT set environment variables automatically.")
    print("   You must do this manually on Railway.")
    
    print_section("Step-by-Step Instructions for Solution B")
    
    print("\n1️⃣  Get your Kraken API credentials:")
    print("   - Go to: https://www.kraken.com")
    print("   - Navigate to: Settings → API")
    print("   - Create new API key with these permissions:")
    print("     ✅ Query Funds")
    print("     ✅ Query Open Orders & Trades")
    print("     ✅ Query Closed Orders & Trades")
    print("     ✅ Create & Modify Orders")
    print("     ✅ Cancel/Close Orders")
    print("   - Save API Key and Private Key securely")
    
    print("\n2️⃣  Add credentials to Railway:")
    print("   - Go to: https://railway.app")
    print("   - Select your NIJA project")
    print("   - Navigate to: Variables tab")
    print("   - Click: New Variable")
    print("   - Add these TWO variables:")
    print()
    print("     Variable 1:")
    print("       Name:  KRAKEN_API_KEY")
    print("       Value: [your_kraken_api_key_here]")
    print()
    print("     Variable 2:")
    print("       Name:  KRAKEN_API_SECRET")
    print("       Value: [your_kraken_private_key_here]")
    
    print("\n3️⃣  Verify Kraken account balance:")
    print("   - Ensure you have $100+ USD or USDT on Kraken")
    print("   - Minimum: $25 (limited trading)")
    print("   - Recommended: $100+ (optimal)")
    
    print("\n4️⃣  Deploy:")
    print("   - Railway will automatically redeploy when you save variables")
    print("   - Or click 'Deploy' manually")
    
    print("\n5️⃣  Verify in logs:")
    print("   - Check Railway logs for:")
    print("     '📊 Attempting to connect Kraken Pro...'")
    print("     '   ✅ Kraken connected'")
    print("     'kraken: Running trading cycle...'")
    
    print("\n📖 Full documentation:")
    print("   See: IMPLEMENT_SOLUTION_B_KRAKEN.md")

def solution_c_execute():
    """Execute Solution C steps"""
    print_header("SOLUTION C: Initialize Multi-User System")
    
    print("\n📋 What Solution C Does:")
    print("  - Sets up user database with encrypted credentials")
    print("  - Configures User #1 (Daivon Frazier) with Kraken account")
    print("  - Enables user-specific trading with isolated balances")
    
    print_section("Checking Prerequisites")
    
    # Check if Kraken SDK is available
    try:
        import krakenex
        print("  ✅ Kraken SDK available")
    except ImportError:
        print("  ⚠️  Kraken SDK not installed")
        print("     Solution C can proceed but won't be able to verify balance")
    
    # Check if auth module exists
    auth_path = os.path.join(os.path.dirname(__file__), 'auth')
    if os.path.exists(auth_path):
        print(f"  ✅ Auth module found: {auth_path}")
    else:
        print(f"  ❌ Auth module NOT found: {auth_path}")
        print("     Cannot proceed with Solution C")
        print("     This feature may not be available in this environment")
        return False
    
    print_section("Solution C: Step 1 - Check User #1's Kraken Balance")
    
    print("\n  Run this command to check balance:")
    print("    python3 check_user1_kraken_balance.py")
    
    response = input("\n  Have you verified User #1's Kraken account has $100+ balance? (y/n): ")
    if response.lower() != 'y':
        print("\n  ⚠️  Please ensure User #1's Kraken account is funded before proceeding.")
        print("     Go to: https://www.kraken.com")
        print("     Log in as: Frazierdaivon@gmail.com")
        print("     Deposit $100+ USD or USDT")
        return False
    
    print_section("Solution C: Step 2 - Initialize User System")
    
    print("\n  This will create the user database and authentication system.")
    response = input("  Proceed with initialization? (y/n): ")
    
    if response.lower() == 'y':
        print("\n  Running: python3 init_user_system.py")
        try:
            result = subprocess.run(
                ['python3', 'init_user_system.py'],
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
                timeout=60
            )
            print(result.stdout)
            if result.stderr:
                print("  Errors:", result.stderr)
            
            if result.returncode == 0:
                print("\n  ✅ User system initialized successfully")
            else:
                print(f"\n  ❌ Initialization failed (exit code: {result.returncode})")
                return False
        except Exception as e:
            print(f"\n  ❌ Error running init_user_system.py: {e}")
            return False
    else:
        print("\n  ⏭️  Skipped initialization")
    
    print_section("Solution C: Step 3 - Setup User #1 (Daivon Frazier)")
    
    print("\n  This will configure User #1 with Kraken credentials and permissions.")
    response = input("  Proceed with user setup? (y/n): ")
    
    if response.lower() == 'y':
        print("\n  Running: python3 setup_user_daivon.py")
        try:
            result = subprocess.run(
                ['python3', 'setup_user_daivon.py'],
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
                timeout=60
            )
            print(result.stdout)
            if result.stderr:
                print("  Errors:", result.stderr)
            
            if result.returncode == 0:
                print("\n  ✅ User #1 setup completed successfully")
            else:
                print(f"\n  ❌ User setup failed (exit code: {result.returncode})")
                return False
        except Exception as e:
            print(f"\n  ❌ Error running setup_user_daivon.py: {e}")
            return False
    else:
        print("\n  ⏭️  Skipped user setup")
        return False
    
    print_section("Solution C: Step 4 - Enable Trading for User #1")
    
    print("\n  This will enable User #1 to start trading.")
    response = input("  Proceed with enabling User #1? (y/n): ")
    
    if response.lower() == 'y':
        print("\n  Running: python3 manage_user_daivon.py enable")
        try:
            result = subprocess.run(
                ['python3', 'manage_user_daivon.py', 'enable'],
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
                timeout=60
            )
            print(result.stdout)
            if result.stderr:
                print("  Errors:", result.stderr)
            
            if result.returncode == 0:
                print("\n  ✅ User #1 enabled successfully")
            else:
                print(f"\n  ❌ Enable failed (exit code: {result.returncode})")
                return False
        except Exception as e:
            print(f"\n  ❌ Error running manage_user_daivon.py: {e}")
            return False
    else:
        print("\n  ⏭️  Skipped enabling user")
        return False
    
    print_section("Solution C: Step 5 - Verify User Status")
    
    print("\n  Checking User #1 status...")
    try:
        result = subprocess.run(
            ['python3', 'manage_user_daivon.py', 'status'],
            cwd=os.path.dirname(__file__),
            capture_output=True,
            text=True,
            timeout=60
        )
        print(result.stdout)
        if result.stderr:
            print("  Errors:", result.stderr)
    except Exception as e:
        print(f"  ⚠️  Could not check status: {e}")
    
    print("\n  📖 Full documentation:")
    print("     See: IMPLEMENT_SOLUTION_C_MULTIUSER.md")
    
    return True

def main():
    """Main execution function"""
    print_header("Execute Solutions B and C - Setup Kraken Trading")
    print("  This script will guide you through implementing both solutions.")
    print("  Date: January 9, 2026")
    
    # Check dependencies
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\n⚠️  Please install dependencies before proceeding.")
        sys.exit(1)
    
    # Check user database
    check_user_database()
    
    # Ask which solutions to implement
    print_header("Choose Solutions to Implement")
    
    print("\n  Available solutions:")
    print("    B - Configure Kraken credentials (Railway dashboard)")
    print("    C - Initialize multi-user system (automated scripts)")
    print("    BOTH - Do both B and C")
    
    choice = input("\n  Which solution(s) would you like to implement? (B/C/BOTH): ").upper()
    
    if choice in ['B', 'BOTH']:
        solution_b_instructions()
        
        if choice == 'B':
            print("\n" + "=" * 80)
            print("  ✅ Solution B instructions provided")
            print("  ⚠️  You must manually configure Railway dashboard")
            print("=" * 80)
            return
    
    if choice in ['C', 'BOTH']:
        print("\n")
        success = solution_c_execute()
        
        if success:
            print_header("✅ SOLUTION C COMPLETE")
            print("\n  User #1 (Daivon Frazier) is now configured and enabled!")
            print("\n  Next steps:")
            print("    1. Restart bot: railway restart")
            print("    2. Check logs: railway logs --tail 200 --follow")
            print("    3. Look for: 'kraken (daivon_frazier): Running trading cycle...'")
        else:
            print_header("⚠️  SOLUTION C INCOMPLETE")
            print("\n  Some steps were skipped or failed.")
            print("  Review the output above and try again.")
    
    if choice == 'BOTH':
        print_header("✅ SOLUTIONS B AND C COMPLETE")
        print("\n  Summary:")
        print("    ✅ Solution B: Instructions provided (manual Railway setup)")
        print("    ✅ Solution C: Multi-user system initialized")
        print("\n  Final steps:")
        print("    1. Configure Kraken credentials on Railway (Solution B)")
        print("    2. Restart bot: railway restart")
        print("    3. Verify both Kraken and User #1 in logs")
    
    print("\n" + "=" * 80)
    print("  For detailed documentation, see:")
    print("    - IMPLEMENT_SOLUTION_B_KRAKEN.md")
    print("    - IMPLEMENT_SOLUTION_C_MULTIUSER.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
