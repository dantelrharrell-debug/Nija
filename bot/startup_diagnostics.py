"""
NIJA Startup Diagnostics

Provides startup verification and diagnostics:
1. Feature flag banner showing which features are enabled
2. Trading capability verification checklist
3. Startup retry logic helpers

Author: NIJA Trading Systems
Date: February 7, 2026
"""

import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger("nija")


def display_feature_flag_banner():
    """
    Display a banner showing which features are enabled/disabled at startup.
    
    This provides immediate visibility into the bot's configuration.
    """
    logger.info("=" * 70)
    logger.info("🏁 FEATURE FLAGS STATUS")
    logger.info("=" * 70)
    
    # Import and check all feature flags
    flags = {}
    
    # Profit Confirmation Feature
    try:
        from config.feature_flags import PROFIT_CONFIRMATION_AVAILABLE
        flags['Profit Confirmation Logging'] = PROFIT_CONFIRMATION_AVAILABLE
    except ImportError:
        flags['Profit Confirmation Logging'] = False
    
    # Execution Intelligence
    try:
        from bot.execution_engine import EXECUTION_INTELLIGENCE_AVAILABLE
        flags['Execution Intelligence'] = EXECUTION_INTELLIGENCE_AVAILABLE
    except (ImportError, AttributeError):
        flags['Execution Intelligence'] = False
    
    # Hard Controls / Live Capital Verified
    try:
        from bot.execution_engine import HARD_CONTROLS_AVAILABLE
        flags['Hard Controls (LIVE_CAPITAL_VERIFIED)'] = HARD_CONTROLS_AVAILABLE
    except (ImportError, AttributeError):
        flags['Hard Controls (LIVE_CAPITAL_VERIFIED)'] = False
    
    # Trade Ledger
    try:
        from bot.execution_engine import TRADE_LEDGER_ENABLED
        flags['Trade Ledger Database'] = TRADE_LEDGER_ENABLED
    except (ImportError, AttributeError):
        flags['Trade Ledger Database'] = False
    
    # Fee-Aware Mode
    try:
        from bot.execution_engine import FEE_AWARE_MODE
        flags['Fee-Aware Profit Calculations'] = FEE_AWARE_MODE
    except (ImportError, AttributeError):
        flags['Fee-Aware Profit Calculations'] = False
    
    # Display results
    for feature_name, is_enabled in flags.items():
        status_icon = "✅" if is_enabled else "⚪"
        status_text = "ENABLED" if is_enabled else "DISABLED"
        logger.info(f"   {status_icon} {feature_name}: {status_text}")
    
    enabled_count = sum(1 for v in flags.values() if v)
    total_count = len(flags)
    logger.info("=" * 70)
    logger.info(f"📊 {enabled_count}/{total_count} features enabled")
    logger.info("=" * 70)


def verify_trading_capability() -> Tuple[bool, List[str]]:
    """
    Verify that the bot has the basic capability to execute trades.
    
    This is a pre-flight check to ensure critical components are available.
    
    Returns:
        Tuple of (all_passed, issues_found)
        - all_passed: True if all critical checks passed
        - issues_found: List of issue descriptions if any failed
    """
    logger.info("=" * 70)
    logger.info("🔍 TRADING CAPABILITY VERIFICATION")
    logger.info("=" * 70)
    
    checks = []
    issues = []
    
    # Check 1: ExecutionEngine can be imported
    try:
        from bot.execution_engine import ExecutionEngine
        checks.append(("ExecutionEngine Module", True, None))
    except Exception as e:
        checks.append(("ExecutionEngine Module", False, str(e)))
        issues.append(f"ExecutionEngine import failed: {e}")
    
    # Check 2: Broker integration available
    try:
        from bot.broker_manager import BrokerManager
        checks.append(("BrokerManager Module", True, None))
    except Exception as e:
        checks.append(("BrokerManager Module", False, str(e)))
        issues.append(f"BrokerManager import failed: {e}")
    
    # Check 3: Trading strategy can be imported
    try:
        from bot.nija_apex_strategy_v72_upgrade import NijaApexStrategyV72
        checks.append(("Trading Strategy (APEX v7.2)", True, None))
    except Exception as e:
        checks.append(("Trading Strategy (APEX v7.2)", False, str(e)))
        issues.append(f"Trading strategy import failed: {e}")
    
    # Check 4: Risk manager available
    try:
        from bot.user_risk_manager import UserRiskManager
        checks.append(("Risk Manager", True, None))
    except Exception as e:
        checks.append(("Risk Manager", False, str(e)))
        issues.append(f"Risk manager import failed: {e}")
    
    # Check 5: Position manager available
    try:
        from bot.position_manager import PositionManager
        checks.append(("Position Manager", True, None))
    except Exception as e:
        checks.append(("Position Manager", False, str(e)))
        issues.append(f"Position manager import failed: {e}")
    
    # Display results
    for check_name, passed, error in checks:
        if passed:
            logger.info(f"   ✅ {check_name}: OK")
        else:
            logger.warning(f"   ❌ {check_name}: FAILED")
            if error:
                logger.warning(f"      Error: {error}")
    
    all_passed = len(issues) == 0
    
    logger.info("=" * 70)
    if all_passed:
        logger.info("✅ All trading capability checks passed")
        logger.info("   Bot is ready to execute trades")
    else:
        logger.warning(f"⚠️  {len(issues)} critical check(s) failed")
        logger.warning("   Bot may not be able to execute trades properly")
    logger.info("=" * 70)
    
    return all_passed, issues


class StartupRetryManager:
    """
    Manages startup retry logic with exponential backoff.
    
    Prevents permanent failure from transient errors during bot initialization.
    """
    
    def __init__(self, max_retries: int = 3, initial_delay: int = 5):
        """
        Initialize retry manager.
        
        Args:
            max_retries: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay in seconds between retries (default: 5)
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.current_attempt = 0
    
    def should_retry(self, error: Exception) -> bool:
        """
        Determine if we should retry after this error.
        
        Args:
            error: The exception that occurred
            
        Returns:
            True if we should retry, False if we should give up
        """
        # Don't retry certain fatal errors
        fatal_error_types = (KeyboardInterrupt, SystemExit)
        if isinstance(error, fatal_error_types):
            return False
        
        # Check if we have retries left
        return self.current_attempt < self.max_retries
    
    def get_retry_delay(self) -> int:
        """
        Calculate delay before next retry using exponential backoff.
        
        Returns:
            Delay in seconds
        """
        # Exponential backoff: 5s, 10s, 20s
        return self.initial_delay * (2 ** self.current_attempt)
    
    def record_attempt(self):
        """Record that we've made another attempt."""
        self.current_attempt += 1
    
    def log_retry_attempt(self, error: Exception, delay: int):
        """
        Log information about the retry attempt.
        
        Args:
            error: The error that triggered the retry
            delay: Delay before retry in seconds
        """
        logger.warning("=" * 70)
        logger.warning(f"⚠️  STARTUP FAILED - Attempt {self.current_attempt}/{self.max_retries}")
        logger.warning("=" * 70)
        logger.warning(f"Error: {type(error).__name__}: {str(error)}")
        logger.warning(f"Retrying in {delay} seconds...")
        logger.warning("=" * 70)
    
    def log_final_failure(self, error: Exception):
        """
        Log final failure after all retries exhausted.
        
        Args:
            error: The final error
        """
        logger.error("=" * 70)
        logger.error(f"❌ STARTUP FAILED PERMANENTLY")
        logger.error("=" * 70)
        logger.error(f"All {self.max_retries} retry attempts exhausted")
        logger.error(f"Final error: {type(error).__name__}: {str(error)}")
        logger.error("Bot initialization cannot continue")
        logger.error("=" * 70)
