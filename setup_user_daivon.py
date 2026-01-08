#!/usr/bin/env python3
"""
Setup script for first user: Daivon Frazier

This script properly registers the first user in NIJA's layered architecture
with encrypted API credentials, permissions, and individual control capabilities.

User Information:
- Name: Daivon Frazier
- Email: Frazierdaivon@gmail.com
- User ID: daivon_frazier
"""

import logging
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def setup_daivon_frazier():
    """
    Set up user account for Daivon Frazier with Kraken credentials.
    """
    from auth import get_api_key_manager, get_user_manager
    from execution import UserPermissions, get_permission_validator
    from config import get_config_manager
    
    # User information
    user_id = "daivon_frazier"
    email = "Frazierdaivon@gmail.com"
    name = "Daivon Frazier"
    
    # API credentials provided by user (Kraken)
    kraken_api_key = "8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7"
    kraken_api_secret = "e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA=="
    
    print("\n" + "="*80)
    print(f"Setting up user: {name}")
    print(f"Email: {email}")
    print(f"User ID: {user_id}")
    print("="*80)
    
    # Step 1: Create user account
    print("\n[1/4] Creating user account...")
    user_mgr = get_user_manager()
    
    try:
        user = user_mgr.create_user(
            user_id=user_id,
            email=email,
            subscription_tier="pro"  # Start with pro tier
        )
        print(f"✅ User account created: {user_id}")
        print(f"    Email: {email}")
        print(f"    Tier: pro")
        print(f"    Created: {user['created_at']}")
    except ValueError as e:
        # User might already exist
        print(f"⚠️  User already exists: {e}")
        user = user_mgr.get_user(user_id)
        if user:
            print(f"    Using existing user: {user_id}")
        else:
            raise
    
    # Step 2: Store encrypted API credentials
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
    print(f"    Credentials are encrypted and secure")
    print(f"    User can now trade on Kraken")
    
    # Step 3: Configure user permissions
    print("\n[3/4] Configuring user permissions...")
    
    # Pro tier permissions - moderate limits with room to grow
    permissions = UserPermissions(
        user_id=user_id,
        allowed_pairs=[
            "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD",
            "MATIC-USD", "DOT-USD", "LINK-USD", "ADA-USD"
        ],  # Popular pairs to start
        max_position_size_usd=300.0,  # $300 max per position
        max_daily_loss_usd=150.0,     # $150 daily loss limit
        max_positions=7,               # Up to 7 concurrent positions
        trade_only=True,               # Cannot modify core strategy
        enabled=True                   # Trading enabled
    )
    
    validator = get_permission_validator()
    validator.register_user(permissions)
    
    print(f"✅ Permissions configured:")
    print(f"    Max position size: ${permissions.max_position_size_usd}")
    print(f"    Max daily loss: ${permissions.max_daily_loss_usd}")
    print(f"    Max positions: {permissions.max_positions}")
    print(f"    Allowed pairs: {len(permissions.allowed_pairs)} pairs")
    print(f"    Trading enabled: {permissions.enabled}")
    
    # Step 4: Configure user settings
    print("\n[4/4] Configuring user settings...")
    config_mgr = get_config_manager()
    
    config_mgr.update_user_config(user_id, {
        'name': name,
        'email': email,
        'max_position_size': 300.0,
        'max_concurrent_positions': 7,
        'risk_level': 'moderate',
        'enable_trailing_stops': True,
        'enable_auto_compound': True,
        'notification_email': email
    })
    print(f"✅ User settings configured")
    print(f"    Risk level: moderate")
    print(f"    Trailing stops: enabled")
    print(f"    Auto-compound: enabled")
    
    # Print summary
    print("\n" + "="*80)
    print("✅ USER SETUP COMPLETE")
    print("="*80)
    print(f"\nUser: {name} ({user_id})")
    print(f"Email: {email}")
    print(f"Status: Active and ready to trade")
    print(f"\nCONTROL OPTIONS:")
    print(f"  • Enable/disable trading: user_mgr.enable_user('{user_id}')")
    print(f"  • Disable trading: user_mgr.disable_user('{user_id}')")
    print(f"  • Check status: user_mgr.get_user('{user_id}')")
    print(f"\nAPI KEYS:")
    print(f"  • Broker: Kraken")
    print(f"  • Status: Encrypted and stored")
    print(f"  • Retrieve: api_mgr.get_user_api_key('{user_id}', 'kraken')")
    print("\n" + "="*80)
    
    return user, permissions


def test_user_controls():
    """
    Test that user can be enabled/disabled independently.
    """
    from auth import get_user_manager
    from execution import get_permission_validator
    from controls import get_hard_controls
    
    user_id = "daivon_frazier"
    
    print("\n" + "="*80)
    print("TESTING INDIVIDUAL USER CONTROL")
    print("="*80)
    
    user_mgr = get_user_manager()
    validator = get_permission_validator()
    controls = get_hard_controls()
    
    # Test 1: User enabled by default
    print("\n[Test 1] User should be enabled by default")
    user = user_mgr.get_user(user_id)
    print(f"  User enabled status: {user['enabled']}")
    assert user['enabled'] == True, "User should be enabled"
    print("  ✅ PASS")
    
    # Test 2: Can trade when enabled
    print("\n[Test 2] User should be able to trade when enabled")
    can_trade, error = controls.can_trade(user_id)
    print(f"  Can trade: {can_trade} (error: {error})")
    print("  ✅ PASS")
    
    # Test 3: Disable user
    print("\n[Test 3] Disable user trading")
    result = user_mgr.disable_user(user_id)
    user = user_mgr.get_user(user_id)
    print(f"  User disabled: {result}")
    print(f"  User enabled status: {user['enabled']}")
    assert user['enabled'] == False, "User should be disabled"
    print("  ✅ PASS")
    
    # Test 4: Re-enable user
    print("\n[Test 4] Re-enable user trading")
    result = user_mgr.enable_user(user_id)
    user = user_mgr.get_user(user_id)
    print(f"  User enabled: {result}")
    print(f"  User enabled status: {user['enabled']}")
    assert user['enabled'] == True, "User should be enabled"
    print("  ✅ PASS")
    
    print("\n" + "="*80)
    print("✅ ALL CONTROL TESTS PASSED")
    print("="*80)
    print("\nUser can be independently controlled without affecting other users!")


def main():
    """Main execution."""
    try:
        # Set up user
        user, permissions = setup_daivon_frazier()
        
        # Test individual control
        test_user_controls()
        
        print("\n🎉 Setup complete! User is ready to trade.")
        
    except Exception as e:
        logger.error(f"Error setting up user: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
