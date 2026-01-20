#!/usr/bin/env python3
"""
Enable PRO MODE Trading for NIJA
=================================

This script configures NIJA to enable:
1. PRO MODE for capital efficiency
2. Master trading on Coinbase and Kraken
3. User copy trading on Kraken

Usage:
    python enable_pro_mode_trading.py
"""

import os
import sys
from pathlib import Path

def create_env_config():
    """Create or update .env file with PRO MODE configuration."""
    
    env_path = Path(__file__).parent / ".env"
    env_example_path = Path(__file__).parent / ".env.example"
    
    print("=" * 70)
    print("🚀 ENABLING PRO MODE TRADING")
    print("=" * 70)
    print()
    
    # Read existing .env or copy from example
    if env_path.exists():
        print("✅ Found existing .env file")
        with open(env_path, 'r') as f:
            env_content = f.read()
    elif env_example_path.exists():
        print("📋 Creating .env from .env.example")
        with open(env_example_path, 'r') as f:
            env_content = f.read()
    else:
        print("❌ No .env or .env.example found")
        return False
    
    # Check for PRO_MODE configuration
    pro_mode_configs = []
    
    # 1. Enable PRO MODE
    if 'PRO_MODE=true' in env_content:
        print("✅ PRO_MODE already enabled")
    elif 'PRO_MODE=' in env_content:
        print("🔧 Updating PRO_MODE to true")
        env_content = env_content.replace('PRO_MODE=false', 'PRO_MODE=true')
        pro_mode_configs.append("PRO_MODE=true")
    else:
        print("➕ Adding PRO_MODE=true")
        # Add PRO_MODE configuration
        env_content += "\n# PRO MODE - Enabled for capital efficiency\nPRO_MODE=true\n"
        pro_mode_configs.append("PRO_MODE=true")
    
    # 2. Set minimum reserve percentage
    if 'PRO_MODE_MIN_RESERVE_PCT=' in env_content:
        print("✅ PRO_MODE_MIN_RESERVE_PCT already configured")
    else:
        print("➕ Adding PRO_MODE_MIN_RESERVE_PCT=0.15 (15% reserve)")
        env_content += "PRO_MODE_MIN_RESERVE_PCT=0.15\n"
        pro_mode_configs.append("PRO_MODE_MIN_RESERVE_PCT=0.15")
    
    # 3. Ensure live trading is enabled
    if 'LIVE_TRADING=1' in env_content or 'LIVE_TRADING=true' in env_content:
        print("✅ LIVE_TRADING already enabled")
    elif 'LIVE_TRADING=' in env_content:
        print("🔧 Updating LIVE_TRADING to 1")
        env_content = env_content.replace('LIVE_TRADING=0', 'LIVE_TRADING=1')
        env_content = env_content.replace('LIVE_TRADING=false', 'LIVE_TRADING=1')
    else:
        print("➕ Adding LIVE_TRADING=1")
        env_content += "\nLIVE_TRADING=1\n"
    
    # Write updated .env file
    try:
        with open(env_path, 'w') as f:
            f.write(env_content)
        print()
        print("=" * 70)
        print("✅ .env FILE UPDATED SUCCESSFULLY")
        print("=" * 70)
        return True
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ ERROR UPDATING .env FILE: {e}")
        print("=" * 70)
        return False


def check_credentials():
    """Check that necessary credentials are configured."""
    
    print()
    print("=" * 70)
    print("🔍 CHECKING EXCHANGE CREDENTIALS")
    print("=" * 70)
    print()
    
    issues = []
    
    # Check Coinbase (for master trading)
    coinbase_key = os.getenv("COINBASE_API_KEY", "")
    coinbase_secret = os.getenv("COINBASE_API_SECRET", "")
    
    if coinbase_key and coinbase_secret:
        print("✅ Coinbase Master credentials configured")
    else:
        print("⚠️  Coinbase Master credentials NOT configured")
        issues.append("Coinbase")
    
    # Check Kraken Master (for master trading and copy trading)
    kraken_master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
    kraken_master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
    
    # Fallback to legacy credentials
    if not kraken_master_key:
        kraken_master_key = os.getenv("KRAKEN_API_KEY", "")
    if not kraken_master_secret:
        kraken_master_secret = os.getenv("KRAKEN_API_SECRET", "")
    
    if kraken_master_key and kraken_master_secret:
        print("✅ Kraken Master credentials configured")
    else:
        print("⚠️  Kraken Master credentials NOT configured")
        issues.append("Kraken Master")
    
    # Check for Kraken user credentials
    kraken_users_found = False
    for key in os.environ:
        if key.startswith("KRAKEN_USER_") and key.endswith("_API_KEY"):
            user_name = key.replace("KRAKEN_USER_", "").replace("_API_KEY", "")
            secret_key = f"KRAKEN_USER_{user_name}_API_SECRET"
            if os.getenv(secret_key):
                print(f"✅ Kraken User credentials configured: {user_name}")
                kraken_users_found = True
    
    if not kraken_users_found:
        print("⚠️  No Kraken User credentials configured")
        print("   💡 Add KRAKEN_USER_<NAME>_API_KEY and KRAKEN_USER_<NAME>_API_SECRET")
        issues.append("Kraken Users")
    
    print()
    if issues:
        print("=" * 70)
        print("⚠️  CREDENTIALS STATUS: INCOMPLETE")
        print("=" * 70)
        print()
        print("Missing credentials for:")
        for issue in issues:
            print(f"   • {issue}")
        print()
        print("📋 ACTION REQUIRED:")
        print()
        if "Coinbase" in issues:
            print("   1. Get Coinbase credentials from: https://portal.cdp.coinbase.com/")
            print("      Set: COINBASE_API_KEY and COINBASE_API_SECRET")
            print()
        if "Kraken Master" in issues:
            print("   2. Get Kraken Master credentials from: https://www.kraken.com/u/security/api")
            print("      Set: KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
            print()
        if "Kraken Users" in issues:
            print("   3. For each user, set:")
            print("      KRAKEN_USER_<NAME>_API_KEY=xxx")
            print("      KRAKEN_USER_<NAME>_API_SECRET=xxx")
            print()
        print("   4. Restart the bot after adding credentials")
        print("=" * 70)
        return False
    else:
        print("=" * 70)
        print("✅ ALL REQUIRED CREDENTIALS CONFIGURED")
        print("=" * 70)
        return True


def display_pro_mode_status():
    """Display PRO MODE status and next steps."""
    
    print()
    print("=" * 70)
    print("📊 PRO MODE CONFIGURATION SUMMARY")
    print("=" * 70)
    print()
    
    pro_mode = os.getenv("PRO_MODE", "false")
    min_reserve = os.getenv("PRO_MODE_MIN_RESERVE_PCT", "0.15")
    live_trading = os.getenv("LIVE_TRADING", "0")
    
    print(f"PRO_MODE: {pro_mode}")
    print(f"PRO_MODE_MIN_RESERVE_PCT: {min_reserve} ({float(min_reserve)*100:.0f}% free reserve)")
    print(f"LIVE_TRADING: {live_trading}")
    print()
    
    print("=" * 70)
    print("🎯 EXPECTED TRADING BEHAVIOR")
    print("=" * 70)
    print()
    print("MASTER ACCOUNTS (Nija System):")
    print("   ✅ Coinbase: Will trade independently")
    print("   ✅ Kraken: Will trade and emit copy signals")
    print()
    print("USER ACCOUNTS:")
    print("   ✅ Kraken Users: Will copy master trades only")
    print("   ⚪ No independent trading loops for Kraken users")
    print()
    
    if pro_mode.lower() in ('true', '1', 'yes'):
        print("PRO MODE FEATURES ACTIVE:")
        print("   ✅ Position values count as available capital")
        print("   ✅ Can rotate positions for better opportunities")
        print("   ✅ Maintains minimum free balance reserve")
        print("   ✅ Maximum capital efficiency")
    else:
        print("⚠️  PRO MODE NOT ENABLED")
        print("   Set PRO_MODE=true to enable")
    
    print()
    print("=" * 70)
    print("🚀 NEXT STEPS")
    print("=" * 70)
    print()
    print("1. ✅ Configuration complete (if credentials are set)")
    print("2. 🔄 Restart the bot:")
    print("      python bot.py")
    print("      # or")
    print("      ./start.sh")
    print()
    print("3. 📋 Verify in logs:")
    print("      Look for: '🔄 PRO MODE ACTIVATED'")
    print("      Look for: 'COPY TRADING ACTIVE'")
    print()
    print("4. 📊 Monitor trading:")
    print("      • Master trades on Coinbase + Kraken")
    print("      • Users copy Kraken master trades")
    print("      • Position rotation in PRO MODE")
    print()
    print("=" * 70)


def main():
    """Main entry point."""
    
    print()
    print("=" * 70)
    print("NIJA PRO MODE TRADING ENABLER")
    print("=" * 70)
    print()
    print("This script will:")
    print("   1. Enable PRO MODE for capital efficiency")
    print("   2. Configure for master trading (Coinbase + Kraken)")
    print("   3. Configure for user copy trading (Kraken)")
    print()
    print("=" * 70)
    print()
    
    # Step 1: Update .env configuration
    if not create_env_config():
        print()
        print("❌ Failed to update .env configuration")
        sys.exit(1)
    
    # Reload environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
        print()
        print("✅ Environment variables reloaded")
    except ImportError:
        print()
        print("ℹ️  dotenv not available (environment variables loaded from system)")
    
    # Step 2: Check credentials
    creds_ok = check_credentials()
    
    # Step 3: Display status and next steps
    display_pro_mode_status()
    
    if creds_ok:
        print()
        print("✅ SETUP COMPLETE - READY TO TRADE")
        print()
        sys.exit(0)
    else:
        print()
        print("⚠️  SETUP INCOMPLETE - ADD CREDENTIALS")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
