#!/usr/bin/env python3
"""
Quick Kraken Connection Restoration Helper

This script helps you restore Kraken connection by:
1. Checking current status
2. Identifying missing credentials
3. Providing step-by-step instructions to fix
4. Optionally creating a .env file with your credentials
"""

import os
import sys

def print_header(title):
    """Print formatted header"""
    print()
    print("=" * 80)
    print(title.center(80))
    print("=" * 80)
    print()

def print_section(title):
    """Print formatted section"""
    print()
    print(title)
    print("-" * 80)

def check_env_var(var_name):
    """Check if environment variable is set"""
    value = os.getenv(var_name, '').strip()
    return bool(value)

def main():
    """Main restoration helper function"""
    
    print_header("KRAKEN CONNECTION RESTORATION HELPER")
    
    print("This script will help you restore your Kraken connection.")
    print("It appears the connection was previously working but is now disconnected.")
    print()
    print("Let's diagnose the issue and get you reconnected!")
    
    # Check current status
    print_section("STEP 1: Checking Current Status")
    
    variables = {
        "KRAKEN_MASTER_API_KEY": "Master account API Key",
        "KRAKEN_MASTER_API_SECRET": "Master account Secret",
        "KRAKEN_USER_DAIVON_API_KEY": "Daivon Frazier API Key",
        "KRAKEN_USER_DAIVON_API_SECRET": "Daivon Frazier Secret",
        "KRAKEN_USER_TANIA_API_KEY": "Tania Gilbert API Key",
        "KRAKEN_USER_TANIA_API_SECRET": "Tania Gilbert Secret"
    }
    
    missing = []
    present = []
    
    for var_name, description in variables.items():
        is_set = check_env_var(var_name)
        status = "✅ SET" if is_set else "❌ MISSING"
        print(f"  {description:35s} [{var_name}] {status}")
        
        if is_set:
            present.append(var_name)
        else:
            missing.append(var_name)
    
    # Summary
    print_section("DIAGNOSIS")
    
    total = len(variables)
    present_count = len(present)
    missing_count = len(missing)
    
    print(f"  Total credentials needed: {total}")
    print(f"  Currently configured: {present_count}")
    print(f"  Missing: {missing_count}")
    print()
    
    if missing_count == 0:
        print("  ✅ ALL CREDENTIALS ARE CONFIGURED!")
        print()
        print("  If Kraken is still not connecting, the issue might be:")
        print("    • Incorrect API keys (typo or wrong keys)")
        print("    • API keys revoked or expired on Kraken website")
        print("    • Insufficient API key permissions on Kraken")
        print("    • Bot needs to be restarted to pick up credentials")
        print()
        print("  Run this to verify connection:")
        print("    python3 check_kraken_status.py")
        return 0
    
    print(f"  ❌ PROBLEM IDENTIFIED: {missing_count} credentials are missing")
    print()
    print("  This is why Kraken is not connected.")
    print()
    
    # Identify deployment type
    print_section("STEP 2: Where is Your Bot Running?")
    
    print("  Where is your NIJA bot deployed?")
    print()
    print("  1. Railway (https://railway.app/)")
    print("  2. Render (https://render.com/)")
    print("  3. Local computer / Docker")
    print("  4. Other / I don't know")
    print()
    
    try:
        choice = input("  Enter number (1-4): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nExiting...")
        return 1
    
    print()
    
    # Provide specific instructions based on deployment
    print_section("STEP 3: How to Fix")
    
    if choice == "1":
        # Railway
        print("  📋 RAILWAY FIX INSTRUCTIONS:")
        print()
        print("  1. Open your Railway dashboard: https://railway.app/")
        print("  2. Find your NIJA project")
        print("  3. Click on your service")
        print("  4. Click the 'Variables' tab")
        print("  5. For each missing credential, click '+ New Variable'")
        print()
        print("  Add these variables:")
        print()
        for var_name in missing:
            print(f"     Variable Name: {var_name}")
            print(f"     Variable Value: <paste your {var_name.replace('_', ' ').lower()}>")
            print()
        print("  6. After adding all variables, Railway will auto-redeploy")
        print("  7. Wait 2-3 minutes for deployment to complete")
        print("  8. Check logs for: '✅ Kraken Pro CONNECTED'")
        print()
        
    elif choice == "2":
        # Render
        print("  📋 RENDER FIX INSTRUCTIONS:")
        print()
        print("  1. Open your Render dashboard: https://render.com/")
        print("  2. Find your NIJA service")
        print("  3. Click on your service")
        print("  4. Click the 'Environment' tab")
        print("  5. Click 'Add Environment Variable'")
        print()
        print("  Add these variables:")
        print()
        for var_name in missing:
            print(f"     Key: {var_name}")
            print(f"     Value: <paste your {var_name.replace('_', ' ').lower()}>")
            print()
        print("  6. Click 'Save Changes'")
        print("  7. Render will auto-redeploy (takes 3-5 minutes)")
        print("  8. Check logs for: '✅ Kraken Pro CONNECTED'")
        print()
        
    elif choice == "3":
        # Local
        print("  📋 LOCAL FIX INSTRUCTIONS:")
        print()
        print("  Option 1: Create .env file manually")
        print("  -" * 40)
        print("  1. Copy the example file:")
        print("     cp .env.example .env")
        print()
        print("  2. Edit the .env file:")
        print("     nano .env  # or use your preferred editor")
        print()
        print("  3. Add these lines:")
        print()
        print("     # Master Account")
        print("     KRAKEN_MASTER_API_KEY=your-master-api-key")
        print("     KRAKEN_MASTER_API_SECRET=your-master-secret")
        print()
        print("     # User #1 (Daivon Frazier)")
        print("     KRAKEN_USER_DAIVON_API_KEY=daivon-api-key")
        print("     KRAKEN_USER_DAIVON_API_SECRET=daivon-secret")
        print()
        print("     # User #2 (Tania Gilbert)")
        print("     KRAKEN_USER_TANIA_API_KEY=tania-api-key")
        print("     KRAKEN_USER_TANIA_API_SECRET=tania-secret")
        print()
        print("  4. Save and close the editor")
        print("  5. Restart the bot: ./start.sh")
        print()
        print("  Option 2: Use this helper to create .env")
        print("  -" * 40)
        
        create_env = input("  Would you like me to help create the .env file? (y/n): ").strip().lower()
        
        if create_env == 'y':
            print()
            print("  Great! I'll help you create the .env file.")
            print("  I'll ask for each credential. Paste your API keys when prompted.")
            print()
            
            credentials = {}
            for var_name in missing:
                while True:
                    value = input(f"  Enter {var_name}: ").strip()
                    if value:
                        credentials[var_name] = value
                        break
                    else:
                        print("    ⚠️  Value cannot be empty. Please try again.")
            
            # Create .env file
            env_path = ".env"
            if os.path.exists(env_path):
                backup = input(f"\n  .env file already exists. Create backup? (y/n): ").strip().lower()
                if backup == 'y':
                    import shutil
                    shutil.copy(env_path, f"{env_path}.backup")
                    print(f"  ✅ Backup created: {env_path}.backup")
            
            # Read existing .env if it exists
            existing_lines = []
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    existing_lines = f.readlines()
            
            # Update or append credentials
            with open(env_path, 'w') as f:
                # Write existing lines, updating any matching variables
                written_vars = set()
                for line in existing_lines:
                    var_name = line.split('=')[0].strip() if '=' in line else None
                    if var_name in credentials:
                        f.write(f"{var_name}={credentials[var_name]}\n")
                        written_vars.add(var_name)
                    else:
                        f.write(line)
                
                # Append any credentials that weren't in existing file
                for var_name, value in credentials.items():
                    if var_name not in written_vars:
                        f.write(f"{var_name}={value}\n")
            
            print()
            print(f"  ✅ .env file created/updated successfully!")
            print()
            print("  Next steps:")
            print("    1. Restart the bot: ./start.sh")
            print("    2. Check status: python3 check_kraken_status.py")
            print()
        else:
            print()
            print("  Okay, follow the manual instructions above to create .env file.")
            print()
    
    else:
        # Other/Unknown
        print("  📋 GENERAL FIX INSTRUCTIONS:")
        print()
        print("  You need to set these environment variables wherever your bot runs:")
        print()
        for var_name in missing:
            print(f"     {var_name}=<your-credential-value>")
        print()
        print("  How to set environment variables depends on your deployment platform.")
        print("  Check your platform's documentation for adding environment variables.")
        print()
    
    # Where to get credentials
    print_section("STEP 4: Where to Get Kraken API Credentials")
    
    print("  If you don't have the API keys anymore, regenerate them:")
    print()
    print("  1. Go to Kraken: https://www.kraken.com/u/security/api")
    print("  2. Log in to EACH account (Master, Daivon, Tania)")
    print("  3. Generate new API key with these permissions:")
    print("     ✅ Query Funds")
    print("     ✅ Query Open Orders & Trades")
    print("     ✅ Query Closed Orders & Trades")
    print("     ✅ Create & Modify Orders")
    print("     ✅ Cancel/Close Orders")
    print("     ❌ Withdraw Funds (do NOT enable)")
    print("  4. Save BOTH the API Key and Private Key immediately")
    print("     ⚠️  WARNING: You can only view Private Key ONCE!")
    print()
    
    # Final verification
    print_section("STEP 5: Verify the Fix")
    
    print("  After adding credentials and redeploying:")
    print()
    print("  1. Run status check:")
    print("     python3 check_kraken_status.py")
    print()
    print("  2. Expected output:")
    print("     ✅ Master account: CONNECTED to Kraken")
    print("     ✅ User #1 (Daivon Frazier): CONNECTED to Kraken")
    print("     ✅ User #2 (Tania Gilbert): CONNECTED to Kraken")
    print("     Configured Accounts: 3/3")
    print()
    print("  3. Check bot logs for:")
    print("     ✅ Kraken Pro CONNECTED (MASTER)")
    print("     ✅ Kraken Pro CONNECTED (USER:daivon_frazier)")
    print("     ✅ Kraken Pro CONNECTED (USER:tania_gilbert)")
    print()
    
    print_header("RESTORATION COMPLETE")
    
    print("Follow the instructions above to restore your Kraken connection.")
    print()
    print("For more help, see:")
    print("  • KRAKEN_CONNECTION_LOST_DIAGNOSIS.md")
    print("  • KRAKEN_SETUP_GUIDE.md")
    print("  • KRAKEN_RAILWAY_RENDER_SETUP.md")
    print()
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
