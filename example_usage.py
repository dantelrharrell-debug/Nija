"""
NIJA Layered Architecture - Example Usage

This file demonstrates how to use the new layered architecture for multi-user trading.

Run this file to see the layered architecture in action:
    python example_usage.py
"""

import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def example_1_user_registration():
    """Example 1: Register a new user with API keys and permissions."""
    print("\n" + "="*80)
    print("EXAMPLE 1: User Registration")
    print("="*80)
    
    from auth import get_api_key_manager, get_user_manager
    from execution import UserPermissions, get_permission_validator
    from config import get_config_manager
    
    # Step 1: Create user account
    user_mgr = get_user_manager()
    user = user_mgr.create_user(
        user_id="alice",
        email="alice@example.com",
        subscription_tier="pro"
    )
    print(f"✅ Created user: {user}")
    
    # Step 2: Store encrypted API keys
    api_mgr = get_api_key_manager()
    api_mgr.store_user_api_key(
        user_id="alice",
        broker="coinbase",
        api_key="alice_coinbase_api_key",
        api_secret="alice_coinbase_secret",
        additional_params={'org_id': 'org-123'}
    )
    print(f"✅ Stored encrypted API keys for alice on coinbase")
    
    # Step 3: Set user permissions
    permissions = UserPermissions(
        user_id="alice",
        allowed_pairs=["BTC-USD", "ETH-USD", "SOL-USD"],
        max_position_size_usd=200.0,
        max_daily_loss_usd=100.0,
        max_positions=5,
        trade_only=True
    )
    
    validator = get_permission_validator()
    validator.register_user(permissions)
    print(f"✅ Registered permissions: {permissions.to_dict()}")
    
    # Step 4: Configure user settings
    config_mgr = get_config_manager()
    config_mgr.update_user_config("alice", {
        'max_position_size': 200.0,
        'max_concurrent_positions': 5,
        'risk_level': 'high',
        'enable_trailing_stops': True
    })
    print(f"✅ Updated user configuration")


def example_2_trade_validation():
    """Example 2: Validate trades with hard controls and permissions."""
    print("\n" + "="*80)
    print("EXAMPLE 2: Trade Validation")
    print("="*80)
    
    from execution import get_permission_validator
    from controls import get_hard_controls
    from config import get_config_manager
    
    validator = get_permission_validator()
    controls = get_hard_controls()
    config_mgr = get_config_manager()
    
    # Test 1: Valid trade
    print("\n--- Test 1: Valid trade ---")
    valid, error = validator.validate_trade(
        user_id="alice",
        pair="BTC-USD",
        position_size_usd=100.0
    )
    print(f"Result: valid={valid}, error={error}")
    
    # Test 2: Pair not allowed
    print("\n--- Test 2: Pair not allowed ---")
    valid, error = validator.validate_trade(
        user_id="alice",
        pair="DOGE-USD",  # Not in allowed_pairs
        position_size_usd=100.0
    )
    print(f"Result: valid={valid}, error={error}")
    
    # Test 3: Position too large
    print("\n--- Test 3: Position too large ---")
    valid, error = validator.validate_trade(
        user_id="alice",
        pair="BTC-USD",
        position_size_usd=500.0  # Exceeds max_position_size_usd
    )
    print(f"Result: valid={valid}, error={error}")
    
    # Test 4: Hard control validation
    print("\n--- Test 4: Hard control validation (2-10% rule) ---")
    account_balance = 1000.0
    
    # Position too small (< 2%)
    valid, error = controls.validate_position_size(
        user_id="alice",
        position_size_usd=10.0,  # 1% of balance
        account_balance=account_balance
    )
    print(f"$10 position (1%): valid={valid}, error={error}")
    
    # Position valid (5%)
    valid, error = controls.validate_position_size(
        user_id="alice",
        position_size_usd=50.0,  # 5% of balance
        account_balance=account_balance
    )
    print(f"$50 position (5%): valid={valid}, error={error}")
    
    # Position too large (> 10%)
    valid, error = controls.validate_position_size(
        user_id="alice",
        position_size_usd=150.0,  # 15% of balance
        account_balance=account_balance
    )
    print(f"$150 position (15%): valid={valid}, error={error}")


def example_3_broker_adapter():
    """Example 3: Use secure broker adapter."""
    print("\n" + "="*80)
    print("EXAMPLE 3: Secure Broker Adapter")
    print("="*80)
    
    from execution.broker_adapter import SecureBrokerAdapter
    
    # Create secure adapter for user
    adapter = SecureBrokerAdapter(
        user_id="alice",
        broker_name="coinbase"
    )
    print(f"✅ Created secure broker adapter for alice")
    
    # Place order (automatically validated)
    print("\n--- Placing order ---")
    result = adapter.place_order(
        pair="BTC-USD",
        side="buy",
        size_usd=100.0
    )
    print(f"Order result: {result}")
    
    # Try invalid order (should be rejected)
    print("\n--- Trying invalid order (pair not allowed) ---")
    result = adapter.place_order(
        pair="DOGE-USD",  # Not in allowed_pairs
        side="buy",
        size_usd=50.0
    )
    print(f"Order result: {result}")


def example_4_kill_switches():
    """Example 4: Demonstrate kill switch functionality."""
    print("\n" + "="*80)
    print("EXAMPLE 4: Kill Switches")
    print("="*80)
    
    from controls import get_hard_controls
    
    controls = get_hard_controls()
    
    # Check if user can trade
    print("\n--- Initial state ---")
    can_trade, error = controls.can_trade("alice")
    print(f"Can alice trade? {can_trade} (error: {error})")
    
    # Trigger user kill switch
    print("\n--- Trigger user kill switch ---")
    controls.trigger_user_kill_switch("alice", "Testing kill switch")
    can_trade, error = controls.can_trade("alice")
    print(f"Can alice trade? {can_trade} (error: {error})")
    
    # Reset kill switch
    print("\n--- Reset kill switch ---")
    controls.reset_user_kill_switch("alice")
    can_trade, error = controls.can_trade("alice")
    print(f"Can alice trade? {can_trade} (error: {error})")
    
    # Test global kill switch
    print("\n--- Trigger GLOBAL kill switch ---")
    controls.trigger_global_kill_switch("Market emergency simulation")
    can_trade, error = controls.can_trade("alice")
    print(f"Can alice trade? {can_trade} (error: {error})")
    
    # Reset global kill switch
    print("\n--- Reset global kill switch ---")
    controls.reset_global_kill_switch()
    can_trade, error = controls.can_trade("alice")
    print(f"Can alice trade? {can_trade} (error: {error})")


def example_5_daily_limits():
    """Example 5: Track daily losses and trade limits."""
    print("\n" + "="*80)
    print("EXAMPLE 5: Daily Limits")
    print("="*80)
    
    from controls import get_hard_controls
    
    controls = get_hard_controls()
    
    # Record some losses
    print("\n--- Recording losses ---")
    controls.record_trade_loss("alice", 10.0)
    print(f"Recorded $10 loss")
    
    controls.record_trade_loss("alice", 15.0)
    print(f"Recorded $15 loss")
    
    controls.record_trade_loss("alice", 20.0)
    print(f"Recorded $20 loss (total: $45)")
    
    # Check daily loss limit (assuming $100 max)
    print("\n--- Check daily loss limit ---")
    can_trade, error = controls.check_daily_loss_limit("alice", max_daily_loss_usd=100.0)
    print(f"Can trade? {can_trade} (error: {error})")
    
    # Exceed limit
    print("\n--- Exceed daily loss limit ---")
    controls.record_trade_loss("alice", 60.0)
    print(f"Recorded $60 loss (total: $105)")
    
    can_trade, error = controls.check_daily_loss_limit("alice", max_daily_loss_usd=100.0)
    print(f"Can trade? {can_trade} (error: {error})")


def example_6_api_errors():
    """Example 6: Auto-disable after API errors."""
    print("\n" + "="*80)
    print("EXAMPLE 6: Auto-Disable on API Errors")
    print("="*80)
    
    from controls import get_hard_controls
    
    controls = get_hard_controls()
    
    print(f"Error threshold: {controls.ERROR_THRESHOLD} errors")
    
    # Simulate API errors
    print("\n--- Recording API errors ---")
    for i in range(controls.ERROR_THRESHOLD + 1):
        should_disable = controls.record_api_error("bob")
        print(f"Error {i+1}: should_disable={should_disable}")
        
        if should_disable:
            can_trade, error = controls.can_trade("bob")
            print(f"User auto-disabled! Can trade? {can_trade} (error: {error})")


def example_7_multi_user():
    """Example 7: Multiple users with different permissions."""
    print("\n" + "="*80)
    print("EXAMPLE 7: Multiple Users")
    print("="*80)
    
    from auth import get_user_manager
    from execution import UserPermissions, get_permission_validator
    
    user_mgr = get_user_manager()
    validator = get_permission_validator()
    
    # Create multiple users
    users = [
        {
            'user_id': 'conservative_carl',
            'email': 'carl@example.com',
            'tier': 'basic',
            'permissions': UserPermissions(
                user_id='conservative_carl',
                allowed_pairs=['BTC-USD'],
                max_position_size_usd=50.0,
                max_positions=2,
                trade_only=True
            )
        },
        {
            'user_id': 'aggressive_anna',
            'email': 'anna@example.com',
            'tier': 'pro',
            'permissions': UserPermissions(
                user_id='aggressive_anna',
                allowed_pairs=['BTC-USD', 'ETH-USD', 'SOL-USD', 'AVAX-USD'],
                max_position_size_usd=500.0,
                max_positions=10,
                trade_only=True
            )
        },
        {
            'user_id': 'moderate_mike',
            'email': 'mike@example.com',
            'tier': 'pro',
            'permissions': UserPermissions(
                user_id='moderate_mike',
                allowed_pairs=['BTC-USD', 'ETH-USD'],
                max_position_size_usd=200.0,
                max_positions=5,
                trade_only=True
            )
        }
    ]
    
    print("\n--- Creating users ---")
    for user_data in users:
        user = user_mgr.create_user(
            user_id=user_data['user_id'],
            email=user_data['email'],
            subscription_tier=user_data['tier']
        )
        validator.register_user(user_data['permissions'])
        print(f"✅ {user_data['user_id']}: {user_data['tier']} tier, "
              f"max ${user_data['permissions'].max_position_size_usd}, "
              f"{user_data['permissions'].max_positions} positions, "
              f"{len(user_data['permissions'].allowed_pairs or [])} pairs")
    
    # Compare permissions
    print("\n--- Permission comparison ---")
    test_pair = "BTC-USD"
    test_size = 100.0
    
    for user_data in users:
        user_id = user_data['user_id']
        valid, error = validator.validate_trade(user_id, test_pair, test_size)
        status = "✅ ALLOWED" if valid else f"❌ DENIED ({error})"
        print(f"{user_id}: {test_pair} ${test_size} -> {status}")


def main():
    """Run all examples."""
    print("\n" + "="*80)
    print("NIJA LAYERED ARCHITECTURE - EXAMPLE USAGE")
    print("="*80)
    print("\nThis demonstrates the new multi-user architecture with:")
    print("  • Encrypted API key storage")
    print("  • User-specific permissions")
    print("  • Hard safety controls")
    print("  • Kill switches")
    print("  • Daily limits")
    
    try:
        example_1_user_registration()
        example_2_trade_validation()
        example_3_broker_adapter()
        example_4_kill_switches()
        example_5_daily_limits()
        example_6_api_errors()
        example_7_multi_user()
        
        print("\n" + "="*80)
        print("✅ ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
