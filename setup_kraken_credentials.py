#!/usr/bin/env python3
"""
Kraken Credentials Setup Script
Interactive tool to help users configure Kraken API credentials

This script:
1. Checks current credential status
2. Guides user through obtaining API keys from Kraken
3. Helps configure environment variables
4. Validates credentials (optional)
5. Updates .env file or provides deployment platform instructions
"""

import os
import sys
from pathlib import Path


def check_current_status():
    """Check which credentials are currently configured."""
    print("="*80)
    print("CHECKING CURRENT KRAKEN CREDENTIAL STATUS")
    print("="*80)
    
    credentials = {
        "Master Account": {
            "KRAKEN_MASTER_API_KEY": os.getenv("KRAKEN_MASTER_API_KEY", ""),
            "KRAKEN_MASTER_API_SECRET": os.getenv("KRAKEN_MASTER_API_SECRET", ""),
        },
        "Daivon Frazier": {
            "KRAKEN_USER_DAIVON_API_KEY": os.getenv("KRAKEN_USER_DAIVON_API_KEY", ""),
            "KRAKEN_USER_DAIVON_API_SECRET": os.getenv("KRAKEN_USER_DAIVON_API_SECRET", ""),
        },
        "Tania Gilbert": {
            "KRAKEN_USER_TANIA_API_KEY": os.getenv("KRAKEN_USER_TANIA_API_KEY", ""),
            "KRAKEN_USER_TANIA_API_SECRET": os.getenv("KRAKEN_USER_TANIA_API_SECRET", ""),
        },
    }
    
    configured_count = 0
    total_accounts = len(credentials)
    
    for account_name, creds in credentials.items():
        api_key = creds.get("KRAKEN_MASTER_API_KEY") or creds.get("KRAKEN_USER_DAIVON_API_KEY") or creds.get("KRAKEN_USER_TANIA_API_KEY", "")
        api_secret = list(creds.values())[1]  # Get the second credential (secret)
        
        key_name = list(creds.keys())[0]
        secret_name = list(creds.keys())[1]
        
        key_set = bool(list(creds.values())[0])
        secret_set = bool(list(creds.values())[1])
        
        print(f"\n{account_name}:")
        print(f"  {key_name}: {'✅ SET' if key_set else '❌ NOT SET'}")
        print(f"  {secret_name}: {'✅ SET' if secret_set else '❌ NOT SET'}")
        
        if key_set and secret_set:
            print(f"  Status: ✅ CONFIGURED")
            configured_count += 1
        else:
            print(f"  Status: ❌ NOT CONFIGURED")
    
    print(f"\n{'='*80}")
    print(f"Summary: {configured_count}/{total_accounts} accounts configured")
    print(f"{'='*80}\n")
    
    return configured_count, total_accounts


def print_instructions():
    """Print detailed setup instructions."""
    print("\n" + "="*80)
    print("HOW TO GET KRAKEN API CREDENTIALS")
    print("="*80)
    print("""
For EACH Kraken account you want to enable, follow these steps:

1. Log in to Kraken
   → https://www.kraken.com/u/security/api

2. Click "Generate New Key"

3. Configure API Key Settings:
   Key Description: "NIJA Trading Bot" (or any name you prefer)
   
4. Select these permissions (REQUIRED):
   ✅ Query Funds
   ✅ Query Open Orders & Trades
   ✅ Query Closed Orders & Trades
   ✅ Create & Modify Orders
   ✅ Cancel/Close Orders
   
   ❌ Do NOT enable "Withdraw Funds" (for security)

5. Click "Generate Key"

6. IMMEDIATELY SAVE BOTH VALUES:
   - API Key: A long string starting with letters/numbers
   - Private Key: Another long string (shown ONLY ONCE!)
   
   ⚠️  WARNING: Private Key is shown ONLY ONCE during creation!
   ⚠️  Save it to a password manager or secure note immediately!

7. Repeat for all accounts you want to enable:
   - Master Account (NIJA system's Kraken account)
   - Daivon Frazier's Kraken account
   - Tania Gilbert's Kraken account

8. Come back here when you have the credentials ready.
""")
    print("="*80)


def get_deployment_choice():
    """Ask user about their deployment method."""
    print("\n" + "="*80)
    print("DEPLOYMENT METHOD")
    print("="*80)
    print("""
Where are you running NIJA?

1. Local development (on my computer)
2. Railway (railway.app)
3. Render (render.com)
4. Other cloud platform
5. Just show me what to do (I'll configure manually)
""")
    
    while True:
        choice = input("Enter choice (1-5): ").strip()
        if choice in ['1', '2', '3', '4', '5']:
            return choice
        print("Invalid choice. Please enter 1, 2, 3, 4, or 5.")


def setup_local_env():
    """Guide user through setting up .env file."""
    print("\n" + "="*80)
    print("LOCAL .env FILE SETUP")
    print("="*80)
    
    env_path = Path(".env")
    env_example_path = Path(".env.example")
    
    # Check if .env exists
    if env_path.exists():
        print(f"\n✅ Found existing .env file at: {env_path.absolute()}")
        overwrite = input("Do you want to add/update Kraken credentials? (y/n): ").strip().lower()
        if overwrite != 'y':
            print("Cancelled.")
            return
    else:
        print(f"\n.env file not found. Creating new one...")
        if env_example_path.exists():
            print(f"Copying from .env.example...")
            # Copy .env.example to .env
            with open(env_example_path, 'r') as f:
                example_content = f.read()
            with open(env_path, 'w') as f:
                f.write(example_content)
            print(f"✅ Created .env from .env.example")
        else:
            # Create minimal .env
            with open(env_path, 'w') as f:
                f.write("# NIJA Trading Bot Environment Variables\n\n")
            print(f"✅ Created new .env file")
    
    print("\n" + "-"*80)
    print("ENTER KRAKEN CREDENTIALS")
    print("-"*80)
    print("Leave blank to skip an account\n")
    
    # Collect credentials
    credentials = {}
    
    # Master account
    print("Master Account (NIJA System):")
    master_key = input("  KRAKEN_MASTER_API_KEY: ").strip()
    master_secret = input("  KRAKEN_MASTER_API_SECRET: ").strip()
    if master_key and master_secret:
        credentials["KRAKEN_MASTER_API_KEY"] = master_key
        credentials["KRAKEN_MASTER_API_SECRET"] = master_secret
        print("  ✅ Master account credentials collected")
    else:
        print("  ⏭️  Skipped Master account")
    
    print()
    
    # Daivon Frazier
    print("User #1: Daivon Frazier:")
    daivon_key = input("  KRAKEN_USER_DAIVON_API_KEY: ").strip()
    daivon_secret = input("  KRAKEN_USER_DAIVON_API_SECRET: ").strip()
    if daivon_key and daivon_secret:
        credentials["KRAKEN_USER_DAIVON_API_KEY"] = daivon_key
        credentials["KRAKEN_USER_DAIVON_API_SECRET"] = daivon_secret
        print("  ✅ Daivon Frazier credentials collected")
    else:
        print("  ⏭️  Skipped Daivon Frazier")
    
    print()
    
    # Tania Gilbert
    print("User #2: Tania Gilbert:")
    tania_key = input("  KRAKEN_USER_TANIA_API_KEY: ").strip()
    tania_secret = input("  KRAKEN_USER_TANIA_API_SECRET: ").strip()
    if tania_key and tania_secret:
        credentials["KRAKEN_USER_TANIA_API_KEY"] = tania_key
        credentials["KRAKEN_USER_TANIA_API_SECRET"] = tania_secret
        print("  ✅ Tania Gilbert credentials collected")
    else:
        print("  ⏭️  Skipped Tania Gilbert")
    
    if not credentials:
        print("\n❌ No credentials provided. Nothing to save.")
        return
    
    # Update .env file
    print(f"\n{'='*80}")
    print("UPDATING .env FILE")
    print("="*80)
    
    # Read current .env
    with open(env_path, 'r') as f:
        lines = f.readlines()
    
    # Update or append credentials
    for key, value in credentials.items():
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                print(f"✅ Updated {key}")
                break
        
        if not found:
            # Find the Kraken section or append at end
            kraken_section_index = -1
            for i, line in enumerate(lines):
                if "KRAKEN" in line and "#" in line:
                    kraken_section_index = i
                    break
            
            if kraken_section_index >= 0:
                # Insert after Kraken section header
                insert_index = kraken_section_index + 1
                while insert_index < len(lines) and (lines[insert_index].strip().startswith("#") or not lines[insert_index].strip()):
                    insert_index += 1
                lines.insert(insert_index, f"{key}={value}\n")
            else:
                # Append at end
                if lines and not lines[-1].endswith('\n'):
                    lines.append('\n')
                lines.append(f"{key}={value}\n")
            
            print(f"✅ Added {key}")
    
    # Write back to .env
    with open(env_path, 'w') as f:
        f.writelines(lines)
    
    print(f"\n✅ Credentials saved to {env_path.absolute()}")
    print(f"\n⚠️  SECURITY REMINDER:")
    print(f"   - .env file contains sensitive credentials")
    print(f"   - NEVER commit .env to Git")
    print(f"   - .env is already in .gitignore (safe)")
    
    print(f"\n{'='*80}")
    print("NEXT STEPS")
    print("="*80)
    print("1. Verify credentials: python3 check_kraken_status.py")
    print("2. Test connection: python3 test_kraken_connection_live.py")
    print("3. Start the bot: ./start.sh")
    print("="*80)


def show_railway_instructions():
    """Show instructions for Railway deployment."""
    print("\n" + "="*80)
    print("RAILWAY DEPLOYMENT SETUP")
    print("="*80)
    print("""
Follow these steps to add Kraken credentials to Railway:

1. Go to Railway Dashboard:
   → https://railway.app/

2. Select your NIJA project/service

3. Click the "Variables" tab

4. For EACH credential you want to add, click "+ New Variable":

   Master Account:
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_MASTER_API_KEY                     │
   │ Value: (paste your master API key here)             │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_MASTER_API_SECRET                  │
   │ Value: (paste your master API secret here)          │
   └─────────────────────────────────────────────────────┘

   User #1 (Daivon Frazier):
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_USER_DAIVON_API_KEY                │
   │ Value: (paste Daivon's API key here)                │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_USER_DAIVON_API_SECRET             │
   │ Value: (paste Daivon's API secret here)             │
   └─────────────────────────────────────────────────────┘

   User #2 (Tania Gilbert):
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_USER_TANIA_API_KEY                 │
   │ Value: (paste Tania's API key here)                 │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Variable: KRAKEN_USER_TANIA_API_SECRET              │
   │ Value: (paste Tania's API secret here)              │
   └─────────────────────────────────────────────────────┘

5. Railway will automatically redeploy with the new variables

6. Check deployment logs to confirm Kraken connection:
   Look for: "✅ Kraken connected (MASTER)"
             "✅ Kraken connected (USER:daivon_frazier)"
             "✅ Kraken connected (USER:tania_gilbert)"

7. Verify: The bot will start trading on Kraken automatically
""")
    print("="*80)


def show_render_instructions():
    """Show instructions for Render deployment."""
    print("\n" + "="*80)
    print("RENDER DEPLOYMENT SETUP")
    print("="*80)
    print("""
Follow these steps to add Kraken credentials to Render:

1. Go to Render Dashboard:
   → https://render.com/

2. Select your NIJA service

3. Click the "Environment" tab

4. For EACH credential, click "Add Environment Variable":

   Master Account:
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_MASTER_API_KEY                          │
   │ Value: (paste your master API key here)             │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_MASTER_API_SECRET                       │
   │ Value: (paste your master API secret here)          │
   └─────────────────────────────────────────────────────┘

   User #1 (Daivon Frazier):
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_USER_DAIVON_API_KEY                     │
   │ Value: (paste Daivon's API key here)                │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_USER_DAIVON_API_SECRET                  │
   │ Value: (paste Daivon's API secret here)             │
   └─────────────────────────────────────────────────────┘

   User #2 (Tania Gilbert):
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_USER_TANIA_API_KEY                      │
   │ Value: (paste Tania's API key here)                 │
   └─────────────────────────────────────────────────────┘
   
   ┌─────────────────────────────────────────────────────┐
   │ Key: KRAKEN_USER_TANIA_API_SECRET                   │
   │ Value: (paste Tania's API secret here)              │
   └─────────────────────────────────────────────────────┘

5. Click "Save Changes"

6. Render will automatically redeploy with the new environment variables

7. Check deployment logs to confirm Kraken connection:
   Look for: "✅ Kraken connected (MASTER)"
             "✅ Kraken connected (USER:daivon_frazier)"
             "✅ Kraken connected (USER:tania_gilbert)"
""")
    print("="*80)


def show_manual_instructions():
    """Show manual setup instructions."""
    print("\n" + "="*80)
    print("MANUAL SETUP INSTRUCTIONS")
    print("="*80)
    print("""
You need to set these environment variables on your deployment platform:

┌─────────────────────────────────────────────────────────────────────┐
│ MASTER ACCOUNT (NIJA System)                                       │
├─────────────────────────────────────────────────────────────────────┤
│ KRAKEN_MASTER_API_KEY=<your-master-api-key>                        │
│ KRAKEN_MASTER_API_SECRET=<your-master-api-secret>                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ USER #1: Daivon Frazier                                            │
├─────────────────────────────────────────────────────────────────────┤
│ KRAKEN_USER_DAIVON_API_KEY=<daivon-api-key>                        │
│ KRAKEN_USER_DAIVON_API_SECRET=<daivon-api-secret>                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ USER #2: Tania Gilbert                                             │
├─────────────────────────────────────────────────────────────────────┤
│ KRAKEN_USER_TANIA_API_KEY=<tania-api-key>                          │
│ KRAKEN_USER_TANIA_API_SECRET=<tania-api-secret>                    │
└─────────────────────────────────────────────────────────────────────┘

How to set environment variables depends on your platform:
- Local: Add to .env file in repository root
- Railway: Dashboard → Variables → Add Variable
- Render: Dashboard → Environment → Add Environment Variable
- Heroku: Dashboard → Settings → Config Vars → Reveal Config Vars
- Docker: Use -e flag or --env-file option: docker run -e KEY=value or docker run --env-file .env
- Kubernetes: ConfigMap or Secret
- Systemd: Environment file in service unit

After setting variables, restart your service/container.
""")
    print("="*80)


def main():
    """Main setup flow."""
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*78 + "║")
    print("║" + "NIJA KRAKEN CREDENTIALS SETUP WIZARD".center(78) + "║")
    print("║" + " "*78 + "║")
    print("╚" + "="*78 + "╝")
    
    # Check current status
    configured, total = check_current_status()
    
    if configured == total:
        print("✅ All accounts are already configured!")
        reconfigure = input("\nDo you want to reconfigure anyway? (y/n): ").strip().lower()
        if reconfigure != 'y':
            print("Exiting.")
            return
    
    # Show instructions
    show_instructions = input("\nDo you need instructions on how to get Kraken API keys? (y/n): ").strip().lower()
    if show_instructions == 'y':
        print_instructions()
        input("\nPress Enter when you have your credentials ready...")
    
    # Get deployment choice
    choice = get_deployment_choice()
    
    if choice == '1':
        setup_local_env()
    elif choice == '2':
        show_railway_instructions()
    elif choice == '3':
        show_render_instructions()
    elif choice == '4' or choice == '5':
        show_manual_instructions()
    
    print("\n" + "="*80)
    print("SETUP COMPLETE")
    print("="*80)
    print("""
Next steps:
1. Verify credentials: python3 check_kraken_status.py
2. Test connection: python3 test_kraken_connection_live.py
3. Start trading: ./start.sh (local) or wait for auto-deploy (cloud)

Documentation:
- CURRENT_KRAKEN_STATUS.md - Current status and troubleshooting
- KRAKEN_SETUP_GUIDE.md - Detailed setup guide
- KRAKEN_CREDENTIAL_TROUBLESHOOTING.md - Common issues

Questions? Check the documentation or file an issue on GitHub.
""")
    print("="*80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
