#!/usr/bin/env python3
"""
Setup script for user: Tania Gilbert

User Information:
- Name: Tania Gilbert
- Email: Tanialgilbert@gmail.com
- User ID: tania_gilbert
- Broker: Alpaca (https://api.alpaca.markets)
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth import get_api_key_manager, get_user_manager
from execution import UserPermissions, get_permission_validator
from config import get_config_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def setup_user():
    """Set up Tania Gilbert's account."""
    user_id = "tania_gilbert"
    email = "Tanialgilbert@gmail.com"
    name = "Tania Gilbert"
    
    # API credentials for Alpaca
    # Note: These should be set as environment variables
    # ALPACA_USER_TANIA_API_KEY and ALPACA_USER_TANIA_API_SECRET
    api_key = os.getenv("ALPACA_USER_TANIA_API_KEY", "")
    api_secret = os.getenv("ALPACA_USER_TANIA_API_SECRET", "")
    
    if not api_key or not api_secret:
        logging.warning("⚠️  API credentials not found in environment variables")
        logging.warning("   Please set ALPACA_USER_TANIA_API_KEY and ALPACA_USER_TANIA_API_SECRET")
        logging.warning("   Continuing with user setup, but broker connection will fail until credentials are set")
    
    logging.info("=" * 70)
    logging.info(f"Setting up user: {name}")
    logging.info("=" * 70)
    
    # 1. Create user
    logging.info("Step 1: Creating user account...")
    user_mgr = get_user_manager()
    try:
        user = user_mgr.create_user(
            user_id=user_id,
            email=email,
            subscription_tier="pro"
        )
        logging.info(f"✅ User account created: {user_id}")
    except ValueError as e:
        if "already exists" in str(e):
            logging.info(f"ℹ️  User {user_id} already exists, updating...")
            user = user_mgr.get_user(user_id)
        else:
            raise
    
    # 2. Store encrypted credentials (if available)
    logging.info("Step 2: Storing encrypted API credentials...")
    api_mgr = get_api_key_manager()
    if api_key and api_secret:
        api_mgr.store_user_api_key(
            user_id=user_id,
            broker="alpaca",
            api_key=api_key,
            api_secret=api_secret,
            additional_params={
                'name': name,
                'email': email,
                'endpoint': 'https://api.alpaca.markets'
            }
        )
        logging.info("✅ API credentials encrypted and stored")
    else:
        logging.warning("⚠️  API credentials not stored (not found in environment)")
    
    # 3. Configure permissions
    logging.info("Step 3: Configuring user permissions...")
    permissions = UserPermissions(
        user_id=user_id,
        allowed_pairs=[
            # Popular stocks
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META",
            # Crypto (if available on Alpaca)
            "BTC/USD", "ETH/USD", "SOL/USD"
        ],
        max_position_size_usd=200.0,    # Conservative limit for stocks
        max_daily_loss_usd=100.0,       # Daily loss limit
        max_positions=5,                # Concurrent positions
        trade_only=True,                # Cannot modify strategy
        enabled=True                    # Trading enabled
    )
    validator = get_permission_validator()
    validator.register_user(permissions)
    logging.info("✅ User permissions configured")
    
    # 4. Configure user settings
    logging.info("Step 4: Configuring user settings...")
    config_mgr = get_config_manager()
    config_mgr.update_user_config(user_id, {
        'max_position_size': 200.0,
        'max_concurrent_positions': 5,
        'risk_level': 'moderate',        # low, moderate, high
        'enable_trailing_stops': True,
        'enable_auto_compound': True,
        'notification_email': email,
        'broker': 'alpaca',
        'trading_mode': 'paper'          # paper or live
    })
    logging.info("✅ User settings configured")
    
    # Summary
    logging.info("")
    logging.info("=" * 70)
    logging.info(f"✅ User {name} setup complete!")
    logging.info("=" * 70)
    logging.info(f"User ID: {user_id}")
    logging.info(f"Email: {email}")
    logging.info(f"Broker: Alpaca (https://api.alpaca.markets)")
    logging.info(f"Subscription: Pro")
    logging.info(f"Max Position: $200")
    logging.info(f"Daily Loss Limit: $100")
    logging.info(f"Max Positions: 5")
    logging.info("=" * 70)
    logging.info("")
    logging.info("Next steps:")
    logging.info("1. Set environment variables:")
    logging.info("   ALPACA_USER_TANIA_API_KEY=AKG546YWGRDFHUHOOOXZXUCDV5")
    logging.info("   ALPACA_USER_TANIA_API_SECRET=<your-secret>")
    logging.info("   ALPACA_USER_TANIA_PAPER=true")
    logging.info("")
    logging.info("2. Test the connection:")
    logging.info("   from bot.multi_account_broker_manager import multi_account_broker_manager")
    logging.info("   from bot.broker_manager import BrokerType")
    logging.info(f"   broker = multi_account_broker_manager.add_user_broker('{user_id}', BrokerType.ALPACA)")
    logging.info("")
    logging.info("3. Enable user trading:")
    logging.info("   from auth import get_user_manager")
    logging.info(f"   user_mgr = get_user_manager()")
    logging.info(f"   user_mgr.enable_user('{user_id}')")
    logging.info("")

if __name__ == "__main__":
    setup_user()
