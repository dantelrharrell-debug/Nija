"""
NIJA Startup Validation - Critical Pre-Flight Checks
Addresses subtle risks: branch/commit unknown, disabled exchanges, testing vs. live mode

This module provides validation for:
1. Git metadata (branch/commit must be known)
2. Exchange configuration (clear warnings for disabled exchanges)
3. Trading mode intentionality (testing vs. live must be explicit)
"""

import os
import logging
from typing import Dict, List, Tuple
from enum import Enum

logger = logging.getLogger("nija")


class StartupRisk(Enum):
    """Categories of startup risks"""
    GIT_METADATA_UNKNOWN = "git_metadata_unknown"
    DISABLED_EXCHANGE_WARNING = "disabled_exchange_warning"
    MODE_AMBIGUOUS = "mode_ambiguous"
    NO_EXCHANGES_ENABLED = "no_exchanges_enabled"


class StartupValidationResult:
    """Result of startup validation checks"""
    
    def __init__(self):
        self.risks: List[Tuple[StartupRisk, str]] = []
        self.warnings: List[str] = []
        self.info: List[str] = []
        self.critical_failure: bool = False
        self.failure_reason: str = ""
    
    def add_risk(self, risk_type: StartupRisk, message: str):
        """Add a risk item"""
        self.risks.append((risk_type, message))
        
    def add_warning(self, message: str):
        """Add a warning"""
        self.warnings.append(message)
        
    def add_info(self, message: str):
        """Add informational message"""
        self.info.append(message)
        
    def mark_critical_failure(self, reason: str):
        """Mark as critical failure (bot should not start)"""
        self.critical_failure = True
        self.failure_reason = reason
        
    def has_risks(self) -> bool:
        """Check if any risks were detected"""
        return len(self.risks) > 0
    
    def get_summary(self) -> Dict:
        """Get summary of validation results"""
        return {
            'risks': [{'type': r[0].value, 'message': r[1]} for r in self.risks],
            'warnings': self.warnings,
            'info': self.info,
            'critical_failure': self.critical_failure,
            'failure_reason': self.failure_reason,
        }


def _is_git_metadata_unknown(value: str) -> bool:
    """
    Helper function to check if git metadata value is unknown.
    
    Args:
        value: Git metadata value (branch or commit)
        
    Returns:
        True if value is unknown or missing, False otherwise
    """
    return not value or value == "unknown"


def validate_git_metadata(git_branch: str, git_commit: str) -> StartupValidationResult:
    """
    Validate that git branch and commit are known.
    
    Risk: Running with unknown branch/commit makes it impossible to verify
    which code version is executing, especially dangerous in production.
    
    Args:
        git_branch: Git branch name from environment or git command
        git_commit: Git commit hash from environment or git command
        
    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()
    
    # Check if branch is unknown
    if _is_git_metadata_unknown(git_branch):
        result.add_risk(
            StartupRisk.GIT_METADATA_UNKNOWN,
            "Git branch is UNKNOWN - cannot verify code version"
        )
        result.add_warning(
            "RISK: Running code with unknown branch. "
            "Set GIT_BRANCH environment variable or ensure .git directory exists."
        )
    else:
        result.add_info(f"Git branch verified: {git_branch}")
    
    # Check if commit is unknown
    if _is_git_metadata_unknown(git_commit):
        result.add_risk(
            StartupRisk.GIT_METADATA_UNKNOWN,
            "Git commit is UNKNOWN - cannot verify code version"
        )
        result.add_warning(
            "RISK: Running code with unknown commit hash. "
            "Set GIT_COMMIT environment variable or ensure .git directory exists."
        )
    else:
        result.add_info(f"Git commit verified: {git_commit}")
    
    # If both are unknown, this is a critical configuration issue
    if _is_git_metadata_unknown(git_branch) and _is_git_metadata_unknown(git_commit):
        result.add_warning(
            "CRITICAL: Both branch and commit are unknown. "
            "This bot instance cannot be traced to any specific code version."
        )
    
    return result


def validate_exchange_configuration() -> StartupValidationResult:
    """
    Validate exchange configuration and warn about disabled exchanges.
    
    Risk: Exchanges may be disabled in code without clear runtime warnings,
    leaving operators unaware that certain brokers are not available.
    
    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()
    
    # Track which exchanges are configured and which are disabled in code
    exchanges_configured = []
    exchanges_disabled_in_code = []
    
    # Coinbase - KNOWN TO BE DISABLED IN CODE (broker_manager.py)
    if os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"):
        exchanges_configured.append("Coinbase")
        # Coinbase is hardcoded as disabled in bot/broker_manager.py
        exchanges_disabled_in_code.append("Coinbase")
        result.add_risk(
            StartupRisk.DISABLED_EXCHANGE_WARNING,
            "Coinbase credentials configured BUT exchange is DISABLED in code"
        )
        result.add_warning(
            "⚠️  COINBASE IS DISABLED: Credentials are set but Coinbase integration "
            "is hardcoded as disabled in bot/broker_manager.py. Trading will NOT occur on Coinbase."
        )
    
    # Kraken Platform (Primary Broker)
    if os.getenv("KRAKEN_PLATFORM_API_KEY") and os.getenv("KRAKEN_PLATFORM_API_SECRET"):
        exchanges_configured.append("Kraken (Platform)")
        result.add_info("✅ Kraken Platform credentials configured and enabled")
    
    # OKX
    if os.getenv("OKX_API_KEY") and os.getenv("OKX_API_SECRET") and os.getenv("OKX_PASSPHRASE"):
        exchanges_configured.append("OKX")
        result.add_info("✅ OKX credentials configured")
    
    # Binance
    if os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET"):
        exchanges_configured.append("Binance")
        result.add_info("✅ Binance credentials configured")
    
    # Alpaca Platform
    if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET"):
        exchanges_configured.append("Alpaca (Platform)")
        result.add_info("✅ Alpaca Platform credentials configured")
    
    # Critical: No exchanges enabled
    enabled_exchanges = [e for e in exchanges_configured if e not in exchanges_disabled_in_code]
    if len(enabled_exchanges) == 0:
        result.mark_critical_failure(
            "No exchanges are enabled. At least one exchange must be configured and enabled."
        )
        result.add_risk(
            StartupRisk.NO_EXCHANGES_ENABLED,
            "CRITICAL: No enabled exchanges detected - trading cannot occur"
        )
    
    # Summary
    result.add_info(f"Total exchanges configured: {len(exchanges_configured)}")
    result.add_info(f"Total exchanges enabled: {len(enabled_exchanges)}")
    result.add_info(f"Disabled in code: {', '.join(exchanges_disabled_in_code) if exchanges_disabled_in_code else 'none'}")
    
    return result


def validate_trading_mode() -> StartupValidationResult:
    """
    Validate that trading mode (testing vs. live) is intentionally set.
    
    Risk: Multiple mode flags exist (PAPER_MODE, LIVE_CAPITAL_VERIFIED, DRY_RUN_MODE, etc.)
    making it unclear whether the bot is in testing or live mode. Accidental
    live trading can occur if flags are misconfigured.
    
    Returns:
        StartupValidationResult with validation findings
    """
    result = StartupValidationResult()
    
    # Check DRY_RUN_MODE flag (takes priority - safest mode)
    dry_run_str = os.getenv("DRY_RUN_MODE", "false").lower()
    dry_run_mode = dry_run_str in ("true", "1", "yes")
    
    # Check PAPER_MODE flag (default to false for consistency)
    paper_mode_str = os.getenv("PAPER_MODE", "false").lower()
    paper_mode = paper_mode_str in ("true", "1", "yes")
    
    # Check LIVE_CAPITAL_VERIFIED flag (default to false for consistency)
    live_verified_str = os.getenv("LIVE_CAPITAL_VERIFIED", "false").lower()
    live_verified = live_verified_str in ("true", "1", "yes")
    
    # Check if mode flags are contradictory
    if dry_run_mode and live_verified:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: Both DRY_RUN_MODE=true and LIVE_CAPITAL_VERIFIED=true are set"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: DRY_RUN_MODE and LIVE_CAPITAL_VERIFIED both enabled. "
            "DRY_RUN_MODE takes priority (simulation mode)."
        )
    
    if paper_mode and live_verified:
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "CONTRADICTORY: Both PAPER_MODE=true and LIVE_CAPITAL_VERIFIED=true are set"
        )
        result.add_warning(
            "⚠️  MODE CONFLICT: PAPER_MODE and LIVE_CAPITAL_VERIFIED both enabled. "
            "This is contradictory. Bot behavior may be unpredictable."
        )
    
    # Determine actual mode (priority: DRY_RUN > LIVE > PAPER)
    if dry_run_mode:
        result.add_info("🟡 DRY RUN MODE: DRY_RUN_MODE=true (SAFEST - Full simulation)")
        result.add_info(
            "✅ SIMULATION ONLY: All exchanges in dry-run mode. "
            "No real orders will be placed. No real money at risk."
        )
    elif live_verified:
        result.add_info("🔴 LIVE TRADING MODE: LIVE_CAPITAL_VERIFIED=true")
        result.add_warning(
            "⚠️  LIVE TRADING ENABLED: Real money at risk. "
            "Ensure this is intentional. Set LIVE_CAPITAL_VERIFIED=false to disable live trading."
        )
    elif paper_mode:
        result.add_info("📝 PAPER TRADING MODE: PAPER_MODE=true")
    else:
        # Neither flag is explicitly set - ambiguous
        result.add_risk(
            StartupRisk.MODE_AMBIGUOUS,
            "Trading mode is AMBIGUOUS - no mode flags explicitly set"
        )
        result.add_warning(
            "⚠️  MODE UNCLEAR: Trading mode not explicitly configured. "
            "Set DRY_RUN_MODE=true for full simulation, PAPER_MODE=true for testing, "
            "or LIVE_CAPITAL_VERIFIED=true for live trading."
        )
    
    # Additional mode flags for context
    app_store_mode = os.getenv("APP_STORE_MODE", "false").lower() in ("true", "1", "yes")
    if app_store_mode:
        result.add_info("📱 APP_STORE_MODE enabled (demo mode for App Store reviewers)")
    
    return result


def run_all_validations(git_branch: str, git_commit: str) -> StartupValidationResult:
    """
    Run all startup validations and combine results.
    
    Args:
        git_branch: Git branch name
        git_commit: Git commit hash
        
    Returns:
        Combined StartupValidationResult
    """
    combined = StartupValidationResult()
    
    # 1. Validate git metadata
    git_result = validate_git_metadata(git_branch, git_commit)
    combined.risks.extend(git_result.risks)
    combined.warnings.extend(git_result.warnings)
    combined.info.extend(git_result.info)
    if git_result.critical_failure:
        combined.mark_critical_failure(git_result.failure_reason)
    
    # 2. Validate exchange configuration
    exchange_result = validate_exchange_configuration()
    combined.risks.extend(exchange_result.risks)
    combined.warnings.extend(exchange_result.warnings)
    combined.info.extend(exchange_result.info)
    if exchange_result.critical_failure:
        combined.mark_critical_failure(exchange_result.failure_reason)
    
    # 3. Validate trading mode
    mode_result = validate_trading_mode()
    combined.risks.extend(mode_result.risks)
    combined.warnings.extend(mode_result.warnings)
    combined.info.extend(mode_result.info)
    if mode_result.critical_failure:
        combined.mark_critical_failure(mode_result.failure_reason)
    
    return combined


def display_validation_results(result: StartupValidationResult):
    """
    Display validation results with visual formatting.
    
    Args:
        result: StartupValidationResult to display
    """
    logger.info("=" * 80)
    logger.info("🔍 STARTUP VALIDATION REPORT")
    logger.info("=" * 80)
    
    # Display risks
    if result.has_risks():
        logger.warning("")
        logger.warning("⚠️  RISKS DETECTED:")
        logger.warning("─" * 80)
        for risk_type, message in result.risks:
            logger.warning(f"   [{risk_type.value.upper()}] {message}")
        logger.warning("─" * 80)
    else:
        logger.info("✅ No risks detected")
    
    # Display warnings
    if result.warnings:
        logger.warning("")
        logger.warning("⚠️  WARNINGS:")
        logger.warning("─" * 80)
        for warning in result.warnings:
            logger.warning(f"   {warning}")
        logger.warning("─" * 80)
    
    # Display info
    if result.info:
        logger.info("")
        logger.info("ℹ️  CONFIGURATION INFO:")
        logger.info("─" * 80)
        for info in result.info:
            logger.info(f"   {info}")
        logger.info("─" * 80)
    
    # Critical failure
    if result.critical_failure:
        logger.error("")
        logger.error("=" * 80)
        logger.error("❌ CRITICAL FAILURE - BOT CANNOT START")
        logger.error("=" * 80)
        logger.error(f"   Reason: {result.failure_reason}")
        logger.error("=" * 80)
    
    logger.info("=" * 80)
    
    # Summary
    risk_count = len(result.risks)
    warning_count = len(result.warnings)
    
    if result.critical_failure:
        logger.error(f"RESULT: FAILED (Critical failure)")
    elif risk_count > 0:
        logger.warning(f"RESULT: PASSED WITH RISKS ({risk_count} risks, {warning_count} warnings)")
    elif warning_count > 0:
        logger.warning(f"RESULT: PASSED WITH WARNINGS ({warning_count} warnings)")
    else:
        logger.info("RESULT: PASSED (No risks or warnings)")
    
    logger.info("=" * 80)
    logger.info("")
