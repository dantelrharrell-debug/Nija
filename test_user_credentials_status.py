"""
Test script to verify user credential status display logic.
"""
import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('nija.test')

# Add bot directory to path
sys.path.insert(0, '/home/runner/work/Nija/Nija/bot')
sys.path.insert(0, '/home/runner/work/Nija/Nija')

def test_user_status_display():
    """Test the user account status display logic."""
    from bot.broker_manager import BrokerType, AccountType
    from bot.multi_account_broker_manager import MultiAccountBrokerManager
    from config.user_loader import get_user_config_loader
    
    # Initialize manager
    manager = MultiAccountBrokerManager()
    
    # Load users from config
    user_loader = get_user_config_loader()
    enabled_users = user_loader.get_all_enabled_users()
    
    logger.info("=" * 70)
    logger.info("Testing User Account Status Display")
    logger.info("=" * 70)
    
    # Try to connect each user
    for user in enabled_users:
        broker_type = BrokerType[user.broker_type.upper()]
        logger.info(f"\nTesting {user.name} ({user.user_id}) -> {broker_type.value.upper()}")
        
        # Attempt to add user broker
        broker = manager.add_user_broker(user.user_id, broker_type)
        
        # Check connection status
        user_broker = manager.get_user_broker(user.user_id, broker_type)
        has_creds = manager.user_has_credentials(user.user_id, broker_type)
        
        logger.info(f"  Broker object: {broker is not None}")
        if broker:
            logger.info(f"  Broker connected: {broker.connected}")
            logger.info(f"  Credentials configured: {broker.credentials_configured}")
        logger.info(f"  user_has_credentials(): {has_creds}")
        
        # Display status as it would appear in logs
        if user_broker and user_broker.connected:
            logger.info(f"  STATUS: ✅ USER: {user.name}: TRADING (Broker: {user.broker_type.upper()})")
        else:
            if has_creds:
                logger.info(f"  STATUS: ❌ USER: {user.name}: NOT TRADING (Broker: {user.broker_type.upper()}, Connection failed)")
            else:
                logger.info(f"  STATUS: ⚪ USER: {user.name}: NOT CONFIGURED (Broker: {user.broker_type.upper()}, Credentials not set)")
    
    logger.info("\n" + "=" * 70)
    logger.info("Test complete")
    logger.info("=" * 70)

if __name__ == "__main__":
    test_user_status_display()
