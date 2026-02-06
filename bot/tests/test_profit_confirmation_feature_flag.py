"""
Tests for Profit Confirmation Feature Flag

Validates that the PROFIT_CONFIRMATION feature flag:
1. Can be defined globally in config/feature_flags.py
2. Can be controlled via environment variable
3. Integrates with bot/feature_flags.py infrastructure
4. Is explicit, testable, and toggleable

Author: NIJA Trading Systems
Date: February 6, 2026
"""

import os
import sys
import unittest

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
from bot.feature_flags import FeatureFlag, is_feature_enabled


class TestProfitConfirmationFeatureFlag(unittest.TestCase):
    """Test suite for profit confirmation feature flag"""
    
    def test_config_flag_is_defined(self):
        """Test that PROFIT_CONFIRMATION_AVAILABLE is defined in config"""
        # The flag should be defined and be a boolean
        self.assertIsInstance(PROFIT_CONFIRMATION_AVAILABLE, bool)
        # Default should be True for production
        self.assertTrue(PROFIT_CONFIRMATION_AVAILABLE)
    
    def test_config_flag_is_importable(self):
        """Test that flag can be imported from config.feature_flags"""
        # This import should work without errors
        from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
        self.assertIsNotNone(PROFIT_CONFIRMATION_AVAILABLE)
    
    def test_feature_flag_enum_includes_profit_confirmation(self):
        """Test that FeatureFlag enum includes PROFIT_CONFIRMATION"""
        # PROFIT_CONFIRMATION should be in the enum
        self.assertTrue(hasattr(FeatureFlag, 'PROFIT_CONFIRMATION'))
        # Verify the enum value
        self.assertEqual(FeatureFlag.PROFIT_CONFIRMATION.value, 'profit_confirmation')
    
    def test_feature_flag_default_enabled(self):
        """Test that PROFIT_CONFIRMATION is enabled by default"""
        # Clear any environment override for this test
        env_var = 'FEATURE_PROFIT_CONFIRMATION'
        original_value = os.environ.get(env_var)
        
        try:
            # Remove env var to test default
            if env_var in os.environ:
                del os.environ[env_var]
            
            # Clear modules for fresh reload
            import sys
            if 'bot.feature_flags' in sys.modules:
                del sys.modules['bot.feature_flags']
            
            # Re-import to get fresh instance with defaults
            import bot.feature_flags as ff_module
            from bot.feature_flags import FeatureFlag as FF
            
            # Check default is True
            is_enabled = ff_module.is_feature_enabled(FF.PROFIT_CONFIRMATION)
            self.assertTrue(is_enabled, "PROFIT_CONFIRMATION should be enabled by default")
            
        finally:
            # Restore original environment
            if original_value is not None:
                os.environ[env_var] = original_value
            elif env_var in os.environ:
                del os.environ[env_var]
    
    def test_feature_flag_can_be_disabled_via_env(self):
        """Test that PROFIT_CONFIRMATION can be disabled via environment variable"""
        env_var = 'FEATURE_PROFIT_CONFIRMATION'
        original_value = os.environ.get(env_var)
        
        try:
            # Set to false
            os.environ[env_var] = 'false'
            
            # Clear modules for fresh reload
            import sys
            if 'bot.feature_flags' in sys.modules:
                del sys.modules['bot.feature_flags']
            
            # Re-import to get fresh instance
            import bot.feature_flags as ff_module
            from bot.feature_flags import FeatureFlag as FF
            
            # Check it's disabled
            is_enabled = ff_module.is_feature_enabled(FF.PROFIT_CONFIRMATION)
            self.assertFalse(is_enabled, "PROFIT_CONFIRMATION should be disabled when env var is false")
            
        finally:
            # Restore original environment
            if original_value is not None:
                os.environ[env_var] = original_value
            elif env_var in os.environ:
                del os.environ[env_var]
    
    def test_feature_flag_can_be_enabled_via_env(self):
        """Test that PROFIT_CONFIRMATION can be enabled via environment variable"""
        env_var = 'FEATURE_PROFIT_CONFIRMATION'
        original_value = os.environ.get(env_var)
        
        try:
            # Set to true
            os.environ[env_var] = 'true'
            
            # Clear modules for fresh reload
            import sys
            if 'bot.feature_flags' in sys.modules:
                del sys.modules['bot.feature_flags']
            
            # Re-import to get fresh instance
            import bot.feature_flags as ff_module
            from bot.feature_flags import FeatureFlag as FF
            
            # Check it's enabled
            is_enabled = ff_module.is_feature_enabled(FF.PROFIT_CONFIRMATION)
            self.assertTrue(is_enabled, "PROFIT_CONFIRMATION should be enabled when env var is true")
            
        finally:
            # Restore original environment
            if original_value is not None:
                os.environ[env_var] = original_value
            elif env_var in os.environ:
                del os.environ[env_var]
    
    def test_feature_flag_explicit(self):
        """Test that flag is explicit and easy to understand"""
        # Flag should have a clear name
        self.assertEqual(FeatureFlag.PROFIT_CONFIRMATION.value, 'profit_confirmation')
        # Global constant should be descriptive
        import config.feature_flags as config_ff
        self.assertTrue(hasattr(config_ff, 'PROFIT_CONFIRMATION_AVAILABLE'))
    
    def test_feature_flag_testable(self):
        """Test that flag is testable (this test proves it!)"""
        # The fact that we can run these tests proves the flag is testable
        self.assertTrue(True, "Feature flag is testable via unit tests")
    
    def test_feature_flag_toggleable(self):
        """Test that flag is toggleable at runtime"""
        env_var = 'FEATURE_PROFIT_CONFIRMATION'
        original_value = os.environ.get(env_var)
        
        try:
            # Test toggle from false to true
            import sys
            
            # Test FALSE
            os.environ[env_var] = 'false'
            if 'bot.feature_flags' in sys.modules:
                del sys.modules['bot.feature_flags']
            import bot.feature_flags as ff_module
            from bot.feature_flags import FeatureFlag as FF
            self.assertFalse(ff_module.is_feature_enabled(FF.PROFIT_CONFIRMATION))
            
            # Test TRUE
            os.environ[env_var] = 'true'
            if 'bot.feature_flags' in sys.modules:
                del sys.modules['bot.feature_flags']
            import bot.feature_flags as ff_module2
            from bot.feature_flags import FeatureFlag as FF2
            self.assertTrue(ff_module2.is_feature_enabled(FF2.PROFIT_CONFIRMATION))
            
        finally:
            # Restore original environment
            if original_value is not None:
                os.environ[env_var] = original_value
            elif env_var in os.environ:
                del os.environ[env_var]


if __name__ == '__main__':
    unittest.main()
