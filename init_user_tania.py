#!/usr/bin/env python3
"""
Initialize NIJA with User #2: Tania Gilbert

This script sets up User #2 in the NIJA system with proper encryption,
permissions, and persistent storage.

Run this to add Tania Gilbert's account to the system.
"""

import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import get_api_key_manager, get_user_manager
from execution import UserPermissions, get_permission_validator
from config import get_config_manager

# User database file
USER_DB_FILE = os.path.join(os.path.dirname(__file__), 'users_db.json')


def save_user_database():
    """Save user data to persistent storage."""
    user_mgr = get_user_manager()
    api_mgr = get_api_key_manager()
    validator = get_permission_validator()
    config_mgr = get_config_manager()
    
    data = {
        'users': user_mgr.users,
        'user_keys': api_mgr.user_keys,
        'user_permissions': {
            uid: perms.to_dict() 
            for uid, perms in validator.user_permissions.items()
        },
        'user_configs': {
            uid: config.to_dict() 
            for uid, config in config_mgr.configs.items()
        }
    }
    
    with open(USER_DB_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✅ User database saved to {USER_DB_FILE}")


def load_user_database():
    """Load user data from persistent storage."""
    if not os.path.exists(USER_DB_FILE):
        print(f"ℹ️  No existing user database found at {USER_DB_FILE}")
        return False
    
    with open(USER_DB_FILE, 'r') as f:
        data = json.load(f)
    
    user_mgr = get_user_manager()
    api_mgr = get_api_key_manager()
    validator = get_permission_validator()
    config_mgr = get_config_manager()
    
    # Load users
    user_mgr.users = data.get('users', {})
    
    # Load API keys
    api_mgr.user_keys = data.get('user_keys', {})
    
    # Load permissions
    for uid, perms_dict in data.get('user_permissions', {}).items():
        perms = UserPermissions(
            user_id=perms_dict['user_id'],
            allowed_pairs=perms_dict['allowed_pairs'],
            max_position_size_usd=perms_dict['max_position_size_usd'],
            max_daily_loss_usd=perms_dict['max_daily_loss_usd'],
            max_positions=perms_dict['max_positions'],
            trade_only=perms_dict['trade_only'],
            enabled=perms_dict['enabled']
        )
        validator.user_permissions[uid] = perms
    
    # Load configs
    from config import UserConfig
    for uid, config_dict in data.get('user_configs', {}).items():
        config = UserConfig.from_dict(config_dict)
        config_mgr.configs[uid] = config
    
    print(f"✅ User database loaded from {USER_DB_FILE}")
    print(f"   Loaded {len(user_mgr.users)} users")
    return True


def initialize_tania_gilbert():
    """Initialize system with Tania Gilbert as User #2."""
    
    # Try to load existing database
    if load_user_database():
        user_mgr = get_user_manager()
        existing_user = user_mgr.get_user('tania_gilbert')
        if existing_user:
            print(f"\n✅ User 'tania_gilbert' already exists!")
            print(f"   Email: {existing_user['email']}")
            print(f"   Tier: {existing_user['subscription_tier']}")
            print(f"   Enabled: {existing_user['enabled']}")
            return True
    else:
        # No database exists, create fresh
        load_user_database()
    
    print("\n" + "="*80)
    print("INITIALIZING NIJA WITH USER #2: Tania Gilbert")
    print("="*80)
    
    # User information
    user_id = "tania_gilbert"
    email = "Tanialgilbert@gmail.com"
    name = "Tania Gilbert"
    
    # API credentials (Kraken)
    kraken_api_key = "XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/"
    kraken_api_secret = "iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw=="
    
    # Create user account
    print("\n[1/4] Creating user account...")
    user_mgr = get_user_manager()
    user = user_mgr.create_user(
        user_id=user_id,
        email=email,
        subscription_tier="pro"
    )
    print(f"✅ User created: {user_id}")
    
    # Store encrypted API credentials
    print("\n[2/4] Storing encrypted API credentials...")
    api_mgr = get_api_key_manager()
    api_mgr.store_user_api_key(
        user_id=user_id,
        broker="kraken",
        api_key=kraken_api_key,
        api_secret=kraken_api_secret,
        additional_params={
            'name': name,
            'email': email
        }
    )
    print(f"✅ API credentials encrypted and stored for Kraken")
    
    # Configure permissions
    print("\n[3/4] Configuring permissions...")
    permissions = UserPermissions(
        user_id=user_id,
        allowed_pairs=[
            "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
            "MATIC-USD", "DOT-USD", "LINK-USD", "ADA-USD"
        ],
        max_position_size_usd=300.0,
        max_daily_loss_usd=150.0,
        max_positions=7,
        trade_only=True,
        enabled=True
    )
    validator = get_permission_validator()
    validator.register_user(permissions)
    print(f"✅ Permissions configured")
    
    # Configure settings
    print("\n[4/4] Configuring user settings...")
    config_mgr = get_config_manager()
    config_mgr.update_user_config(user_id, {
        'max_position_size': 300.0,
        'max_concurrent_positions': 7,
        'risk_level': 'moderate',
        'enable_trailing_stops': True,
        'enable_auto_compound': True
    })
    print(f"✅ Settings configured")
    
    # Save to persistent storage
    print("\n[5/4] Saving to persistent storage...")
    save_user_database()
    
    print("\n" + "="*80)
    print("✅ INITIALIZATION COMPLETE")
    print("="*80)
    print(f"\nUser: {name} ({user_id})")
    print(f"Email: {email}")
    print(f"Status: Active and ready to trade")
    print(f"\nManagement Commands:")
    print(f"  python manage_user_tania.py status   # Check status")
    print(f"  python manage_user_tania.py enable   # Enable trading")
    print(f"  python manage_user_tania.py disable  # Disable trading")
    print(f"  python manage_user_tania.py info     # Detailed info")
    print("="*80 + "\n")
    
    return True


if __name__ == "__main__":
    try:
        initialize_tania_gilbert()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
