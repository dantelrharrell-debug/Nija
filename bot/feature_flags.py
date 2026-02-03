# bot/feature_flags.py

import os
from enum import Enum
from typing import Dict, Optional
import logging

logger = logging.getLogger("nija.feature_flags")


class FeatureFlag(Enum):
    """Available feature flags"""
    ENTRY_QUALITY_AUDIT = "entry_quality_audit"
    VOLATILITY_ADAPTIVE_SIZING = "volatility_adaptive_sizing"
    DYNAMIC_STOP_EXPANSION = "dynamic_stop_expansion"
    LIVE_DASHBOARD = "live_dashboard"
    
    # Safety killswitches (always ON)
    PROFITABILITY_ASSERTION = "profitability_assertion"
    STOP_LOSS_VALIDATION = "stop_loss_validation"


class FeatureFlagManager:
    """
    Manages feature flags for safe progressive rollout.
    
    Feature flags can be controlled via:
    1. Environment variables (highest priority)
    2. Configuration file
    3. Default values (most conservative)
    """
    
    def __init__(self):
        """Initialize feature flag manager"""
        self.flags: Dict[FeatureFlag, bool] = {}
        self._load_flags()
        
    def _load_flags(self):
        """Load feature flags from environment and config"""
        
        # Default values (all new features OFF by default)
        defaults = {
            FeatureFlag.ENTRY_QUALITY_AUDIT: False,
            FeatureFlag.VOLATILITY_ADAPTIVE_SIZING: False,
            FeatureFlag.DYNAMIC_STOP_EXPANSION: False,
            FeatureFlag.LIVE_DASHBOARD: False,
            
            # Safety features ALWAYS ON (cannot be disabled)
            FeatureFlag.PROFITABILITY_ASSERTION: True,
            FeatureFlag.STOP_LOSS_VALIDATION: True,
        }
        
        # Load from environment variables
        for flag in FeatureFlag:
            env_var = f"FEATURE_{flag.value.upper()}"
            env_value = os.getenv(env_var)
            
            if env_value is not None:
                self.flags[flag] = env_value.lower() in ('true', '1', 'yes', 'on')
            else:
                self.flags[flag] = defaults[flag]
        
        # Log flag states
        logger.info("🚩 Feature Flags Loaded:")
        for flag, enabled in self.flags.items():
            status = "✅ ENABLED" if enabled else "❌ DISABLED"
            if flag in [FeatureFlag.PROFITABILITY_ASSERTION, FeatureFlag.STOP_LOSS_VALIDATION]:
                status += " (LOCKED)"
            logger.info(f"  {flag.value}: {status}")
    
    def is_enabled(self, flag: FeatureFlag) -> bool:
        """
        Check if a feature flag is enabled.
        
        Args:
            flag: Feature flag to check
            
        Returns:
            True if feature is enabled
        """
        # Safety features cannot be disabled
        if flag in [FeatureFlag.PROFITABILITY_ASSERTION, FeatureFlag.STOP_LOSS_VALIDATION]:
            return True
        
        return self.flags.get(flag, False)
    
    def enable(self, flag: FeatureFlag) -> None:
        """Enable a feature flag (runtime control)"""
        if flag in [FeatureFlag.PROFITABILITY_ASSERTION, FeatureFlag.STOP_LOSS_VALIDATION]:
            logger.warning(f"Cannot disable safety feature: {flag.value}")
            return
        
        self.flags[flag] = True
        logger.info(f"✅ Feature enabled: {flag.value}")
    
    def disable(self, flag: FeatureFlag) -> None:
        """Disable a feature flag (emergency killswitch)"""
        if flag in [FeatureFlag.PROFITABILITY_ASSERTION, FeatureFlag.STOP_LOSS_VALIDATION]:
            logger.warning(f"Cannot disable safety feature: {flag.value}")
            return
        
        self.flags[flag] = False
        logger.warning(f"❌ Feature disabled: {flag.value}")
    
    def get_all_flags(self) -> Dict[str, bool]:
        """Get all flag states"""
        return {flag.value: enabled for flag, enabled in self.flags.items()}


# Singleton instance
_feature_flag_manager: Optional[FeatureFlagManager] = None

def get_feature_flags() -> FeatureFlagManager:
    """Get singleton feature flag manager"""
    global _feature_flag_manager
    if _feature_flag_manager is None:
        _feature_flag_manager = FeatureFlagManager()
    return _feature_flag_manager


def is_feature_enabled(flag: FeatureFlag) -> bool:
    """Convenience function to check feature flag"""
    return get_feature_flags().is_enabled(flag)
