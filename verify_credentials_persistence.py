#!/usr/bin/env python3
"""
Credential Persistence Verification Tool
=========================================

This script verifies that credentials are:
1. Set in environment variables
2. Accessible to the bot
3. Non-empty and valid
4. Persisted in deployment platform (not just session)

Use this to diagnose recurring credential loss issues.

Usage:
    python3 verify_credentials_persistence.py
    
    # With verbose output
    python3 verify_credentials_persistence.py --verbose
    
    # Check specific user
    python3 verify_credentials_persistence.py --user daivon_frazier
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ANSI colors for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def check_env_var(var_name: str, required: bool = False) -> Tuple[bool, str, Optional[str]]:
    """
    Check if environment variable is set and valid.
    
    Returns:
        (is_valid, status_message, value_preview)
    """
    value = os.getenv(var_name, "")
    
    if not value:
        if required:
            return False, f"{RED}❌ NOT SET (REQUIRED){RESET}", None
        else:
            return False, f"{YELLOW}⚪ NOT SET (Optional){RESET}", None
    
    # Check for whitespace-only values
    if not value.strip():
        return False, f"{RED}❌ SET but EMPTY/WHITESPACE{RESET}", None
    
    # Value is valid
    preview = value[:8] + "..." if len(value) > 8 else value
    return True, f"{GREEN}✅ SET{RESET}", preview


def check_master_credentials() -> Dict[str, bool]:
    """Check master account credentials."""
    results = {}
    
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}🔒 MASTER ACCOUNT CREDENTIALS{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    
    # Coinbase Master
    print(f"\n📊 Coinbase Master:")
    cb_key_valid, cb_key_status, cb_key_preview = check_env_var("COINBASE_API_KEY")
    cb_secret_valid, cb_secret_status, cb_secret_preview = check_env_var("COINBASE_API_SECRET")
    
    print(f"   COINBASE_API_KEY:    {cb_key_status} ({cb_key_preview if cb_key_preview else 'N/A'})")
    print(f"   COINBASE_API_SECRET: {cb_secret_status}")
    
    results['coinbase_master'] = cb_key_valid and cb_secret_valid
    
    # Kraken Master
    print(f"\n📊 Kraken Master:")
    kr_key_valid, kr_key_status, kr_key_preview = check_env_var("KRAKEN_MASTER_API_KEY")
    kr_secret_valid, kr_secret_status, kr_secret_preview = check_env_var("KRAKEN_MASTER_API_SECRET")
    
    print(f"   KRAKEN_MASTER_API_KEY:    {kr_key_status} ({kr_key_preview if kr_key_preview else 'N/A'})")
    print(f"   KRAKEN_MASTER_API_SECRET: {kr_secret_status}")
    
    results['kraken_master'] = kr_key_valid and kr_secret_valid
    
    # Alpaca Master
    print(f"\n📊 Alpaca Master:")
    al_key_valid, al_key_status, al_key_preview = check_env_var("ALPACA_API_KEY")
    al_secret_valid, al_secret_status, al_secret_preview = check_env_var("ALPACA_API_SECRET")
    
    print(f"   ALPACA_API_KEY:    {al_key_status} ({al_key_preview if al_key_preview else 'N/A'})")
    print(f"   ALPACA_API_SECRET: {al_secret_status}")
    
    results['alpaca_master'] = al_key_valid and al_secret_valid
    
    return results


def check_user_credentials() -> Dict[str, Dict[str, bool]]:
    """Check user account credentials."""
    results = {}
    
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}👤 USER ACCOUNT CREDENTIALS{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    
    # Load user configurations
    try:
        from config.user_loader import get_user_config_loader
        user_loader = get_user_config_loader()
        enabled_users = user_loader.get_all_enabled_users()
        
        if not enabled_users:
            print(f"\n{YELLOW}⚪ No enabled users found in configuration files{RESET}")
            return results
        
        print(f"\n✅ Found {len(enabled_users)} enabled user(s) in config files")
        
        for user in enabled_users:
            user_id = user.user_id
            broker_type = user.broker_type.upper()
            
            print(f"\n👤 {user.name} ({user_id}) - {broker_type}:")
            
            # Construct environment variable names based on broker type
            if broker_type == "KRAKEN":
                # Convert user_id to env var format: daivon_frazier -> DAIVON
                first_name = user_id.split('_')[0].upper()
                key_var = f"KRAKEN_USER_{first_name}_API_KEY"
                secret_var = f"KRAKEN_USER_{first_name}_API_SECRET"
                
            elif broker_type == "ALPACA":
                first_name = user_id.split('_')[0].upper()
                key_var = f"ALPACA_USER_{first_name}_API_KEY"
                secret_var = f"ALPACA_USER_{first_name}_API_SECRET"
                paper_var = f"ALPACA_USER_{first_name}_PAPER"
                
                # Check paper trading setting
                paper_valid, paper_status, paper_preview = check_env_var(paper_var)
                print(f"   {paper_var}: {paper_status} ({paper_preview if paper_preview else 'N/A'})")
                
            else:
                print(f"   {YELLOW}⚠️  Unsupported broker type: {broker_type}{RESET}")
                continue
            
            # Check credentials
            key_valid, key_status, key_preview = check_env_var(key_var)
            secret_valid, secret_status, secret_preview = check_env_var(secret_var)
            
            print(f"   {key_var}: {key_status} ({key_preview if key_preview else 'N/A'})")
            print(f"   {secret_var}: {secret_status}")
            
            # Store results
            user_key = f"{user_id}_{broker_type.lower()}"
            results[user_key] = {
                'configured': key_valid and secret_valid,
                'user_name': user.name,
                'broker': broker_type
            }
            
    except ImportError as e:
        print(f"\n{RED}❌ Could not load user configurations: {e}{RESET}")
        print(f"{YELLOW}   Make sure you're running from the repository root{RESET}")
    except Exception as e:
        print(f"\n{RED}❌ Error checking user credentials: {e}{RESET}")
        import traceback
        traceback.print_exc()
    
    return results


def check_credential_persistence() -> bool:
    """
    Check if credentials are persisted properly.
    
    This detects if credentials are:
    - Set in deployment platform (Railway/Render)
    - Only in local .env file
    - Only in current shell session
    """
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}🔄 CREDENTIAL PERSISTENCE CHECK{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    
    # Check if .env file exists
    env_file_exists = os.path.exists(".env")
    print(f"\n📄 .env file: {GREEN + '✅ EXISTS' + RESET if env_file_exists else YELLOW + '⚪ NOT FOUND' + RESET}")
    
    # Check if we're in a deployment environment
    deployment_platform = None
    if os.getenv("RAILWAY_ENVIRONMENT"):
        deployment_platform = "Railway"
    elif os.getenv("RENDER"):
        deployment_platform = "Render"
    elif os.getenv("HEROKU"):
        deployment_platform = "Heroku"
    
    if deployment_platform:
        print(f"🚀 Deployment Platform: {GREEN}{deployment_platform}{RESET}")
        print(f"\n{YELLOW}ℹ️  NOTE: In {deployment_platform}, credentials must be set in platform dashboard{RESET}")
        print(f"{YELLOW}   .env files are NOT used in production deployments{RESET}")
        return True
    else:
        print(f"💻 Environment: {YELLOW}Local Development{RESET}")
        if env_file_exists:
            print(f"{GREEN}✅ Using .env file for credentials{RESET}")
            return True
        else:
            print(f"{RED}❌ WARNING: No .env file found{RESET}")
            print(f"{YELLOW}   Credentials may be set in shell session (will be lost on restart){RESET}")
            return False


def generate_credential_setup_commands(missing_creds: List[str]) -> str:
    """Generate commands to set missing credentials."""
    if not missing_creds:
        return ""
    
    commands = []
    commands.append(f"\n{BLUE}{'=' * 70}{RESET}")
    commands.append(f"{BLUE}🔧 TO FIX MISSING CREDENTIALS:{RESET}")
    commands.append(f"{BLUE}{'=' * 70}{RESET}")
    commands.append("")
    
    # Check deployment platform
    if os.getenv("RAILWAY_ENVIRONMENT"):
        commands.append(f"{YELLOW}📋 For Railway:{RESET}")
        commands.append("1. Go to Railway dashboard: https://railway.app/")
        commands.append("2. Select your NIJA service")
        commands.append("3. Click 'Variables' tab")
        commands.append("4. Add the following variables:")
        for cred in missing_creds:
            commands.append(f"   - {cred}=<your-{cred.lower().replace('_', '-')}>")
        commands.append("5. Click 'Save' - Railway will auto-redeploy")
        
    elif os.getenv("RENDER"):
        commands.append(f"{YELLOW}📋 For Render:{RESET}")
        commands.append("1. Go to Render dashboard: https://render.com/")
        commands.append("2. Select your NIJA service")
        commands.append("3. Click 'Environment' tab")
        commands.append("4. Add the following variables:")
        for cred in missing_creds:
            commands.append(f"   - {cred}=<your-{cred.lower().replace('_', '-')}>")
        commands.append("5. Click 'Save Changes'")
        commands.append("6. Click 'Manual Deploy' → 'Deploy latest commit'")
        
    else:
        commands.append(f"{YELLOW}📋 For Local Development:{RESET}")
        commands.append("1. Create/edit .env file:")
        commands.append("   cp .env.example .env")
        commands.append("")
        commands.append("2. Add the following to .env:")
        for cred in missing_creds:
            commands.append(f"   {cred}=<your-{cred.lower().replace('_', '-')}>")
        commands.append("")
        commands.append("3. Restart the bot:")
        commands.append("   ./start.sh")
    
    return "\n".join(commands)


def main():
    """Main execution."""
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}🔍 NIJA CREDENTIAL PERSISTENCE VERIFICATION{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    
    # Check credential persistence
    is_persisted = check_credential_persistence()
    
    # Check master credentials
    master_results = check_master_credentials()
    
    # Check user credentials
    user_results = check_user_credentials()
    
    # Summary
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}📊 SUMMARY{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}")
    
    # Count configured accounts
    master_count = sum(1 for v in master_results.values() if v)
    user_count = sum(1 for v in user_results.values() if v.get('configured', False))
    
    print(f"\n✅ Master Accounts Configured: {master_count}/{len(master_results)}")
    for broker, configured in master_results.items():
        status = f"{GREEN}✅{RESET}" if configured else f"{RED}❌{RESET}"
        print(f"   {status} {broker.replace('_', ' ').title()}")
    
    print(f"\n✅ User Accounts Configured: {user_count}/{len(user_results)}")
    for user_key, user_data in user_results.items():
        status = f"{GREEN}✅{RESET}" if user_data['configured'] else f"{RED}❌{RESET}"
        print(f"   {status} {user_data['user_name']} ({user_data['broker']})")
    
    # Persistence warning
    if not is_persisted:
        print(f"\n{RED}⚠️  WARNING: Credentials may not be persisted!{RESET}")
        print(f"{YELLOW}   Credentials set in shell session will be lost on restart{RESET}")
        print(f"{YELLOW}   Use .env file (local) or deployment platform (production){RESET}")
    
    # Generate fix commands for missing credentials
    missing_creds = []
    
    # Check master credentials
    if not master_results.get('coinbase_master'):
        missing_creds.extend(['COINBASE_API_KEY', 'COINBASE_API_SECRET'])
    if not master_results.get('kraken_master'):
        missing_creds.extend(['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET'])
    if not master_results.get('alpaca_master'):
        missing_creds.extend(['ALPACA_API_KEY', 'ALPACA_API_SECRET'])
    
    # Check user credentials
    for user_key, user_data in user_results.items():
        if not user_data['configured']:
            user_id, broker = user_key.rsplit('_', 1)
            first_name = user_id.split('_')[0].upper()
            if broker == 'kraken':
                missing_creds.extend([
                    f'KRAKEN_USER_{first_name}_API_KEY',
                    f'KRAKEN_USER_{first_name}_API_SECRET'
                ])
            elif broker == 'alpaca':
                missing_creds.extend([
                    f'ALPACA_USER_{first_name}_API_KEY',
                    f'ALPACA_USER_{first_name}_API_SECRET'
                ])
    
    if missing_creds:
        print(generate_credential_setup_commands(missing_creds))
    
    # Final status
    print(f"\n{BLUE}{'=' * 70}{RESET}")
    if master_count > 0 or user_count > 0:
        if missing_creds:
            print(f"{YELLOW}⚠️  PARTIAL SUCCESS: Some credentials configured, some missing{RESET}")
            return 1
        else:
            print(f"{GREEN}✅ SUCCESS: All configured accounts have valid credentials{RESET}")
            return 0
    else:
        print(f"{RED}❌ FAILURE: No credentials configured{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
