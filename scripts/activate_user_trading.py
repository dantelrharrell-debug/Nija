#!/usr/bin/env python3
"""
NIJA User Trading Activation Helper
====================================

This script helps verify and activate independent trading threads for user accounts.
It checks:
1. User configuration files exist and are enabled
2. Environment variables for API credentials are set
3. Users will be able to trade independently

For NIJA to actively manage and sell positions for user accounts, this script
ensures all prerequisites are met.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


class UserTradingActivator:
    """Helper class to verify and activate user trading."""
    
    # Expected user accounts from the problem statement
    EXPECTED_USERS = [
        {
            'user_id': 'daivon_frazier',
            'name': 'Daivon Frazier',
            'env_prefix': 'DAIVON'
        },
        {
            'user_id': 'tania_gilbert',
            'name': 'Tania Gilbert',
            'env_prefix': 'TANIA'
        }
    ]
    
    def __init__(self):
        """Initialize the activator."""
        self.repo_root = Path(__file__).parent.parent
        self.config_dir = self.repo_root / 'config' / 'users'
        self.issues: List[str] = []
        self.warnings: List[str] = []
        
    def check_user_config_file(self, user_id: str) -> Tuple[bool, Dict]:
        """
        Check if user configuration file exists and is valid.
        
        Args:
            user_id: User identifier (e.g., 'daivon_frazier')
            
        Returns:
            Tuple of (is_valid, config_dict)
        """
        config_file = self.config_dir / f"{user_id}.json"
        
        if not config_file.exists():
            self.issues.append(f"❌ Configuration file missing: {config_file}")
            return False, {}
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            
            # Check if enabled
            if not config.get('enabled', False):
                self.warnings.append(f"⚠️  {user_id}: enabled=false (trading will NOT start)")
                return False, config
            
            # Check broker type
            broker = config.get('broker', 'unknown')
            if broker not in ['kraken', 'alpaca', 'coinbase']:
                self.issues.append(f"❌ {user_id}: Invalid broker type '{broker}'")
                return False, config
            
            return True, config
            
        except json.JSONDecodeError as e:
            self.issues.append(f"❌ {user_id}: Invalid JSON in config file: {e}")
            return False, {}
        except Exception as e:
            self.issues.append(f"❌ {user_id}: Error reading config: {e}")
            return False, {}
    
    def check_credentials(self, user_id: str, env_prefix: str, broker: str) -> bool:
        """
        Check if API credentials are configured in environment variables.
        
        Args:
            user_id: User identifier
            env_prefix: Environment variable prefix (e.g., 'DAIVON')
            broker: Broker type (e.g., 'kraken')
            
        Returns:
            True if credentials are set, False otherwise
        """
        broker_upper = broker.upper()
        
        # Build environment variable names
        # Format: {BROKER}_USER_{PREFIX}_API_KEY
        # Example: KRAKEN_USER_DAIVON_API_KEY
        key_var = f"{broker_upper}_USER_{env_prefix}_API_KEY"
        secret_var = f"{broker_upper}_USER_{env_prefix}_API_SECRET"
        
        key_value = os.getenv(key_var)
        secret_value = os.getenv(secret_var)
        
        if not key_value or not secret_value:
            self.issues.append(
                f"❌ {user_id}: Missing API credentials\n"
                f"   Required environment variables:\n"
                f"   - {key_var}\n"
                f"   - {secret_var}"
            )
            return False
        
        # Check if values look like placeholders
        placeholders = ['YOUR_API_KEY', 'YOUR_SECRET', 'PLACEHOLDER', '']
        if key_value in placeholders or secret_value in placeholders:
            self.issues.append(
                f"❌ {user_id}: Placeholder values detected\n"
                f"   {key_var} and {secret_var} must be set to real credentials"
            )
            return False
        
        return True
    
    def check_platform_broker(self, broker: str) -> bool:
        """
        Check if platform broker is configured for the same broker type.
        User brokers should only trade if platform broker is configured.
        
        Args:
            broker: Broker type (e.g., 'kraken')
            
        Returns:
            True if platform broker is configured
        """
        broker_upper = broker.upper()
        
        # Check platform credentials
        key_var = f"{broker_upper}_PLATFORM_API_KEY"
        secret_var = f"{broker_upper}_PLATFORM_API_SECRET"
        
        key_value = os.getenv(key_var)
        secret_value = os.getenv(secret_var)
        
        if not key_value or not secret_value:
            self.warnings.append(
                f"⚠️  Platform {broker_upper} not configured\n"
                f"   User accounts will trade independently (not recommended)\n"
                f"   For optimal operation, configure:\n"
                f"   - {key_var}\n"
                f"   - {secret_var}"
            )
            return False
        
        return True
    
    def check_pro_mode(self) -> bool:
        """
        Check if PRO_MODE is enabled for advanced scaling.
        
        Returns:
            True if PRO_MODE is enabled
        """
        pro_mode = os.getenv('PRO_MODE', 'false').lower()
        return pro_mode in ['true', '1', 'yes', 'on']
    
    def run_activation_check(self) -> bool:
        """
        Run complete activation check for all expected users.
        
        Returns:
            True if all checks pass, False if issues found
        """
        logger.info("=" * 70)
        logger.info("🔍 NIJA USER TRADING ACTIVATION CHECK")
        logger.info("=" * 70)
        logger.info("")
        
        all_valid = True
        valid_users = []
        
        for user_info in self.EXPECTED_USERS:
            user_id = user_info['user_id']
            name = user_info['name']
            env_prefix = user_info['env_prefix']
            
            logger.info(f"Checking: {name} ({user_id})")
            logger.info("-" * 70)
            
            # Check configuration file
            config_valid, config = self.check_user_config_file(user_id)
            if not config_valid:
                logger.info(f"   ❌ Configuration: INVALID")
                all_valid = False
                logger.info("")
                continue
            
            broker = config.get('broker', 'unknown')
            logger.info(f"   ✅ Configuration: VALID")
            logger.info(f"      Broker: {broker}")
            logger.info(f"      Enabled: {config.get('enabled', False)}")
            
            # Check credentials
            creds_valid = self.check_credentials(user_id, env_prefix, broker)
            if creds_valid:
                logger.info(f"   ✅ API Credentials: SET")
                valid_users.append(name)
            else:
                logger.info(f"   ❌ API Credentials: MISSING")
                all_valid = False
            
            # Check platform broker (warning only, not fatal)
            platform_ok = self.check_platform_broker(broker)
            if platform_ok:
                logger.info(f"   ✅ Platform {broker.upper()}: CONFIGURED")
            else:
                logger.info(f"   ⚠️  Platform {broker.upper()}: NOT CONFIGURED (see warnings)")
            
            logger.info("")
        
        # Check PRO_MODE
        pro_mode_enabled = self.check_pro_mode()
        logger.info("=" * 70)
        logger.info("ADVANCED FEATURES")
        logger.info("=" * 70)
        if pro_mode_enabled:
            logger.info("✅ PRO_MODE: ENABLED (advanced position scaling)")
        else:
            logger.info("⚪ PRO_MODE: DISABLED (set PRO_MODE=true to enable)")
        logger.info("")
        
        # Show summary
        logger.info("=" * 70)
        logger.info("SUMMARY")
        logger.info("=" * 70)
        
        if all_valid:
            logger.info("✅ ALL CHECKS PASSED")
            logger.info("")
            logger.info("User accounts ready for independent trading:")
            for name in valid_users:
                logger.info(f"   • {name}")
            logger.info("")
            logger.info("NIJA will automatically:")
            logger.info("   ✅ Start independent trading thread for each user")
            logger.info("   ✅ Scan markets for opportunities")
            logger.info("   ✅ Execute trades based on signals")
            logger.info("   ✅ Manage stop-loss and take-profit")
            logger.info("   ✅ Close profitable positions")
            logger.info("")
            logger.info("🚀 Start NIJA with: ./start.sh or python bot.py")
        else:
            logger.info("❌ ACTIVATION INCOMPLETE")
            logger.info("")
            logger.info("Issues found:")
            for issue in self.issues:
                logger.info(f"   {issue}")
        
        if self.warnings:
            logger.info("")
            logger.info("Warnings:")
            for warning in self.warnings:
                logger.info(f"   {warning}")
        
        logger.info("=" * 70)
        logger.info("")
        
        if all_valid:
            logger.info("✅ Ready to start NIJA with user trading enabled!")
        else:
            logger.info("⚠️  Fix the issues above and run this script again.")
            logger.info("")
            logger.info("Quick setup guide:")
            logger.info("1. Set environment variables in .env file:")
            logger.info("   - Copy .env.example to .env")
            logger.info("   - Fill in API keys for each user")
            logger.info("2. Ensure user configs have enabled=true")
            logger.info("3. Run this script again to verify")
            logger.info("4. Start NIJA: ./start.sh")
        
        logger.info("")
        
        return all_valid


def main():
    """Main entry point."""
    activator = UserTradingActivator()
    success = activator.run_activation_check()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
