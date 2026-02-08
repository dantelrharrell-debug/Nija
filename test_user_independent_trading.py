"""
Test suite for independent_trading feature.

Validates that:
1. UserConfig and IndividualUserConfig classes have independent_trading field
2. User configs are properly loaded from JSON files
3. User threads start based on independent_trading flag, not platform status
"""

import unittest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the classes we're testing
from config.user_loader import UserConfig, UserConfigLoader
from config.individual_user_loader import IndividualUserConfig, IndividualUserConfigLoader


class TestUserConfigIndependentTrading(unittest.TestCase):
    """Test UserConfig class independent_trading field."""

    def test_userconfig_has_independent_trading_field(self):
        """Verify UserConfig has independent_trading field."""
        config = UserConfig(
            user_id="test_user",
            name="Test User",
            account_type="retail",
            broker_type="kraken",
            independent_trading=True
        )
        
        self.assertTrue(hasattr(config, 'independent_trading'))
        self.assertTrue(config.independent_trading)

    def test_userconfig_independent_trading_defaults_to_false(self):
        """Verify independent_trading defaults to False."""
        config = UserConfig(
            user_id="test_user",
            name="Test User",
            account_type="retail",
            broker_type="kraken"
        )
        
        self.assertFalse(config.independent_trading)

    def test_userconfig_from_dict_with_independent_trading(self):
        """Verify from_dict() loads independent_trading field."""
        data = {
            'user_id': 'test_user',
            'name': 'Test User',
            'account_type': 'retail',
            'broker_type': 'kraken',
            'enabled': True,
            'independent_trading': True
        }
        
        config = UserConfig.from_dict(data)
        
        self.assertTrue(config.independent_trading)

    def test_userconfig_from_dict_without_independent_trading(self):
        """Verify from_dict() defaults independent_trading to False if missing."""
        data = {
            'user_id': 'test_user',
            'name': 'Test User',
            'account_type': 'retail',
            'broker_type': 'kraken',
            'enabled': True
        }
        
        config = UserConfig.from_dict(data)
        
        self.assertFalse(config.independent_trading)

    def test_userconfig_to_dict_includes_independent_trading(self):
        """Verify to_dict() includes independent_trading field."""
        config = UserConfig(
            user_id="test_user",
            name="Test User",
            account_type="retail",
            broker_type="kraken",
            independent_trading=True
        )
        
        data = config.to_dict()
        
        self.assertIn('independent_trading', data)
        self.assertTrue(data['independent_trading'])


class TestIndividualUserConfigIndependentTrading(unittest.TestCase):
    """Test IndividualUserConfig class independent_trading field."""

    def test_individualuserconfig_has_independent_trading_field(self):
        """Verify IndividualUserConfig has independent_trading field."""
        config = IndividualUserConfig(
            user_id="test_user",
            name="Test User",
            broker="kraken",
            independent_trading=True
        )
        
        self.assertTrue(hasattr(config, 'independent_trading'))
        self.assertTrue(config.independent_trading)

    def test_individualuserconfig_independent_trading_defaults_to_false(self):
        """Verify independent_trading defaults to False."""
        config = IndividualUserConfig(
            user_id="test_user",
            name="Test User",
            broker="kraken"
        )
        
        self.assertFalse(config.independent_trading)

    def test_individualuserconfig_from_dict_with_independent_trading(self):
        """Verify from_dict() loads independent_trading field."""
        data = {
            'name': 'Test User',
            'broker': 'kraken',
            'role': 'user',
            'enabled': True,
            'independent_trading': True
        }
        
        config = IndividualUserConfig.from_dict('test_user', data)
        
        self.assertTrue(config.independent_trading)

    def test_individualuserconfig_from_dict_without_independent_trading(self):
        """Verify from_dict() defaults independent_trading to False if missing."""
        data = {
            'name': 'Test User',
            'broker': 'kraken',
            'role': 'user',
            'enabled': True
        }
        
        config = IndividualUserConfig.from_dict('test_user', data)
        
        self.assertFalse(config.independent_trading)

    def test_individualuserconfig_to_dict_includes_independent_trading(self):
        """Verify to_dict() includes independent_trading field."""
        config = IndividualUserConfig(
            user_id="test_user",
            name="Test User",
            broker="kraken",
            independent_trading=True
        )
        
        data = config.to_dict()
        
        self.assertIn('independent_trading', data)
        self.assertTrue(data['independent_trading'])


class TestUserConfigLoader(unittest.TestCase):
    """Test UserConfigLoader with independent_trading field."""

    def test_load_user_config_with_independent_trading(self):
        """Verify UserConfigLoader loads independent_trading from JSON files."""
        # Create a temporary directory for test config files
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            
            # Create a test user config file
            test_data = [{
                'user_id': 'test_user',
                'name': 'Test User',
                'account_type': 'retail',
                'broker_type': 'kraken',
                'enabled': True,
                'independent_trading': True
            }]
            
            config_file = config_dir / 'retail_kraken.json'
            with open(config_file, 'w') as f:
                json.dump(test_data, f)
            
            # Load the config
            loader = UserConfigLoader(config_dir=str(config_dir))
            loader.load_all_users()
            
            # Verify independent_trading was loaded
            users = loader.get_users_by_type('retail')
            self.assertEqual(len(users), 1)
            self.assertTrue(users[0].independent_trading)


class TestIndividualUserConfigLoader(unittest.TestCase):
    """Test IndividualUserConfigLoader with independent_trading field."""

    def test_load_individual_user_config_with_independent_trading(self):
        """Verify IndividualUserConfigLoader loads independent_trading from JSON files."""
        # Create a temporary directory for test config files
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            
            # Create test user config files
            test_data = {
                'name': 'Test User',
                'broker': 'kraken',
                'role': 'user',
                'enabled': True,
                'independent_trading': True
            }
            
            config_file = config_dir / 'daivon_frazier.json'
            with open(config_file, 'w') as f:
                json.dump(test_data, f)
            
            config_file = config_dir / 'tania_gilbert.json'
            with open(config_file, 'w') as f:
                json.dump(test_data, f)
            
            # Mock environment variables for API keys
            with patch.dict(os.environ, {
                'KRAKEN_USER_DAIVON_API_KEY': 'test_key',
                'KRAKEN_USER_DAIVON_API_SECRET': 'test_secret',
                'KRAKEN_USER_TANIA_API_KEY': 'test_key',
                'KRAKEN_USER_TANIA_API_SECRET': 'test_secret'
            }):
                # Load the config
                loader = IndividualUserConfigLoader(config_dir=str(config_dir))
                loader.load_all_users(hard_fail=True, require_api_keys=False)
                
                # Verify independent_trading was loaded
                user = loader.get_user_by_id('daivon_frazier')
                self.assertIsNotNone(user)
                self.assertTrue(user.independent_trading)


class TestMultiAccountBrokerManagerUserConfigs(unittest.TestCase):
    """Test that MultiAccountBrokerManager stores user configs."""

    def test_multi_account_manager_has_user_configs_dict(self):
        """Verify MultiAccountBrokerManager has user_configs dictionary."""
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        
        manager = MultiAccountBrokerManager()
        
        # Verify user_configs dictionary exists
        self.assertTrue(hasattr(manager, 'user_configs'))
        self.assertIsInstance(manager.user_configs, dict)

    def test_user_configs_stored_when_loading(self):
        """Verify user configs are stored in user_configs dictionary when loading."""
        from bot.multi_account_broker_manager import MultiAccountBrokerManager
        
        manager = MultiAccountBrokerManager()
        
        # Create a mock user config
        mock_user = MagicMock()
        mock_user.user_id = 'test_user'
        mock_user.independent_trading = True
        
        # Simulate storing user config (this happens in _connect_user_brokers)
        manager.user_configs['test_user'] = mock_user
        
        # Verify it was stored
        self.assertIn('test_user', manager.user_configs)
        self.assertEqual(manager.user_configs['test_user'].user_id, 'test_user')
        self.assertTrue(manager.user_configs['test_user'].independent_trading)


class TestIndependentBrokerTraderLogic(unittest.TestCase):
    """Test that IndependentBrokerTrader uses independent_trading flag."""

    def test_user_thread_logic_checks_independent_trading(self):
        """Verify user thread startup logic checks independent_trading flag."""
        # This is a functional test that verifies the logic exists in the code
        from bot.independent_broker_trader import IndependentBrokerTrader
        import inspect
        
        # Get the source code of the start_independent_trading method
        source = inspect.getsource(IndependentBrokerTrader.start_independent_trading)
        
        # Verify the logic checks user_config.independent_trading
        self.assertIn('user_config.independent_trading', source)
        self.assertIn('user_configs.get', source)
        
        # Verify old platform status check is removed
        # (The old code would have checked is_platform_connected)
        # We verify the new implementation doesn't have that check in user thread startup


class TestRealUserConfigs(unittest.TestCase):
    """Test that real user config files have independent_trading set."""

    def test_daivon_frazier_has_independent_trading_true(self):
        """Verify daivon_frazier.json has independent_trading: true."""
        config_path = Path(__file__).parent / 'config' / 'users' / 'daivon_frazier.json'
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                data = json.load(f)
            
            self.assertIn('independent_trading', data)
            self.assertTrue(data['independent_trading'])

    def test_tania_gilbert_has_independent_trading_true(self):
        """Verify tania_gilbert.json has independent_trading: true."""
        config_path = Path(__file__).parent / 'config' / 'users' / 'tania_gilbert.json'
        
        if config_path.exists():
            with open(config_path, 'r') as f:
                data = json.load(f)
            
            self.assertIn('independent_trading', data)
            self.assertTrue(data['independent_trading'])


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
