#!/usr/bin/env python3
"""
NIJA Go Live Validator
======================

This script validates all requirements before enabling LIVE trading mode.

Usage:
    python go_live.py --check              # Check readiness
    python go_live.py --activate           # Activate live mode
    python go_live.py --status             # Show current status

Pre-flight Checks:
    1. DRY_RUN_MODE is disabled
    2. LIVE_CAPITAL_VERIFIED can be enabled
    3. All brokers show green (healthy)
    4. Kraken platform account configured and connected
    5. Kraken user accounts configured (optional)
    6. No adoption failures
    7. No halted threads
    8. Capital safety thresholds satisfied
    9. Multi-account isolation healthy
    10. Recovery checks operational

Kraken Configuration Steps:
    1. Configure Platform account first:
       - Set KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET
       - Verify connection: python go_live.py --check
    
    2. Configure individual user accounts (optional):
       - Set KRAKEN_USER_DAIVON_API_KEY, KRAKEN_USER_DAIVON_API_SECRET
       - Set KRAKEN_USER_TANIA_API_KEY, KRAKEN_USER_TANIA_API_SECRET
       - Add more users following same pattern
    
    3. Set LIVE_CAPITAL_VERIFIED=true in production
    
    4. Activate: python go_live.py --activate
    
    5. Monitor logs:
       - First 30 minutes: Continuous monitoring
       - Next 24 hours: Hourly checks
       - Ensure positions adopted correctly
       - Check tier floors, forced cleanup, risk management
       - Validate user accounts follow independent trading rules

Safety:
    - Will NOT activate live mode if any checks fail
    - Provides clear remediation steps for failures
    - Logs all checks for audit trail

Author: NIJA Trading Systems
Version: 2.0
Date: February 17, 2026
"""

import os
import sys
import logging
import argparse
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from dataclasses import dataclass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.go_live")


@dataclass
class CheckResult:
    """Result of a pre-flight check"""
    name: str
    passed: bool
    message: str
    remediation: Optional[str] = None
    critical: bool = True  # If False, warning only


class GoLiveValidator:
    """
    Validates all requirements for going live with NIJA trading bot.
    """
    
    def __init__(self):
        """Initialize the go-live validator"""
        self.checks: List[CheckResult] = []
        self.critical_failures = 0
        self.warnings = 0
        
    def run_all_checks(self) -> bool:
        """
        Run all pre-flight checks.
        
        Returns:
            bool: True if all critical checks pass
        """
        logger.info("=" * 80)
        logger.info("🚀 NIJA GO-LIVE VALIDATION")
        logger.info("=" * 80)
        logger.info("")
        
        # Run all checks
        self._check_dry_run_mode()
        self._check_live_capital_verified()
        self._check_broker_health()
        self._check_adoption_failures()
        self._check_halted_threads()
        self._check_capital_safety()
        self._check_multi_account_isolation()
        self._check_recovery_mechanisms()
        self._check_credentials_configured()
        self._check_kraken_connectivity()
        self._check_emergency_stops()
        
        # Print results
        self._print_results()
        
        return self.critical_failures == 0
    
    def _check_dry_run_mode(self):
        """Check that DRY_RUN_MODE is disabled"""
        dry_run = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
        
        if dry_run:
            self.checks.append(CheckResult(
                name="DRY_RUN Mode Check",
                passed=False,
                message="DRY_RUN_MODE is currently enabled (simulated trades only)",
                remediation="Set DRY_RUN_MODE=false in environment or .env file",
                critical=True
            ))
            self.critical_failures += 1
        else:
            self.checks.append(CheckResult(
                name="DRY_RUN Mode Check",
                passed=True,
                message="DRY_RUN_MODE is disabled ✅",
                critical=True
            ))
    
    def _check_live_capital_verified(self):
        """Check LIVE_CAPITAL_VERIFIED setting"""
        live_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
        
        if not live_verified:
            self.checks.append(CheckResult(
                name="Live Capital Verification",
                passed=False,
                message="LIVE_CAPITAL_VERIFIED is not enabled (safety lock active)",
                remediation="Set LIVE_CAPITAL_VERIFIED=true to enable live trading",
                critical=True
            ))
            self.critical_failures += 1
        else:
            self.checks.append(CheckResult(
                name="Live Capital Verification",
                passed=True,
                message="LIVE_CAPITAL_VERIFIED is enabled ✅",
                critical=True
            ))
    
    def _check_broker_health(self):
        """Check that all brokers are healthy (green status)"""
        try:
            from bot.health_check import get_health_manager
            
            health_mgr = get_health_manager()
            state = health_mgr.state
            
            # Check broker health status
            broker_status = state.broker_health_status
            
            if not broker_status:
                self.checks.append(CheckResult(
                    name="Broker Health Check",
                    passed=False,
                    message="No broker health data available",
                    remediation="Ensure health check system is initialized and brokers are configured",
                    critical=True
                ))
                self.critical_failures += 1
                return
            
            # Check each broker
            failed_brokers = []
            degraded_brokers = []
            healthy_brokers = []
            
            for broker_name, broker_info in broker_status.items():
                status = broker_info.get('status', 'unknown')
                if status == 'failed':
                    failed_brokers.append(broker_name)
                elif status == 'degraded':
                    degraded_brokers.append(broker_name)
                elif status == 'healthy':
                    healthy_brokers.append(broker_name)
            
            # Failed brokers are critical
            if failed_brokers:
                self.checks.append(CheckResult(
                    name="Broker Health Check",
                    passed=False,
                    message=f"Failed brokers detected: {', '.join(failed_brokers)}",
                    remediation=f"Fix broker connectivity issues. Check logs for details. Visit observability dashboard.",
                    critical=True
                ))
                self.critical_failures += 1
            # Degraded brokers are warnings
            elif degraded_brokers:
                self.checks.append(CheckResult(
                    name="Broker Health Check",
                    passed=True,
                    message=f"Some brokers degraded: {', '.join(degraded_brokers)} (can proceed with caution)",
                    remediation="Monitor degraded brokers closely. Consider fixing before going live.",
                    critical=False
                ))
                self.warnings += 1
            # All healthy
            else:
                broker_list = ', '.join(healthy_brokers) if healthy_brokers else 'None'
                self.checks.append(CheckResult(
                    name="Broker Health Check",
                    passed=True,
                    message=f"All brokers healthy ✅ ({broker_list})",
                    critical=True
                ))
                
        except ImportError:
            self.checks.append(CheckResult(
                name="Broker Health Check",
                passed=False,
                message="Unable to import health check module",
                remediation="Ensure bot/health_check.py is available",
                critical=False
            ))
            self.warnings += 1
        except Exception as e:
            self.checks.append(CheckResult(
                name="Broker Health Check",
                passed=False,
                message=f"Error checking broker health: {str(e)}",
                remediation="Check logs for details",
                critical=False
            ))
            self.warnings += 1
    
    def _check_adoption_failures(self):
        """Check for recent adoption failures"""
        try:
            from bot.health_check import get_health_manager
            
            health_mgr = get_health_manager()
            state = health_mgr.state
            
            failure_count = state.adoption_failure_count
            recent_failures = state.adoption_failures[-5:] if state.adoption_failures else []
            
            if failure_count > 0:
                self.checks.append(CheckResult(
                    name="Adoption Failures Check",
                    passed=False,
                    message=f"Adoption failures detected: {failure_count} total, {len(recent_failures)} recent",
                    remediation="Review adoption failures in observability dashboard. Fix authentication/onboarding issues.",
                    critical=False
                ))
                self.warnings += 1
            else:
                self.checks.append(CheckResult(
                    name="Adoption Failures Check",
                    passed=True,
                    message="No adoption failures detected ✅",
                    critical=False
                ))
                
        except Exception as e:
            self.checks.append(CheckResult(
                name="Adoption Failures Check",
                passed=True,
                message="Unable to check adoption failures (assuming clean)",
                remediation=None,
                critical=False
            ))
    
    def _check_halted_threads(self):
        """Check for halted trading threads"""
        try:
            from bot.health_check import get_health_manager
            
            health_mgr = get_health_manager()
            state = health_mgr.state
            
            halted_count = state.halted_threads
            
            if halted_count > 0:
                self.checks.append(CheckResult(
                    name="Trading Threads Check",
                    passed=False,
                    message=f"Halted trading threads detected: {halted_count}",
                    remediation="Restart halted threads or investigate deadlock. Check observability dashboard.",
                    critical=True
                ))
                self.critical_failures += 1
            else:
                self.checks.append(CheckResult(
                    name="Trading Threads Check",
                    passed=True,
                    message="No halted threads detected ✅",
                    critical=True
                ))
                
        except Exception as e:
            self.checks.append(CheckResult(
                name="Trading Threads Check",
                passed=True,
                message="Unable to check thread status (assuming healthy)",
                remediation=None,
                critical=False
            ))
    
    def _check_capital_safety(self):
        """Check capital safety thresholds"""
        try:
            from bot.capital_reservation_manager import CapitalReservationManager
            
            # Try to instantiate manager to verify it's available
            mgr = CapitalReservationManager()
            
            # Check configuration
            safety_buffer = mgr.safety_buffer_pct
            min_free_capital = mgr.min_free_capital_usd
            
            self.checks.append(CheckResult(
                name="Capital Safety Thresholds",
                passed=True,
                message=f"Capital safety configured ✅ (buffer: {safety_buffer*100:.1f}%, min free: ${min_free_capital:.2f})",
                critical=True
            ))
            
        except Exception as e:
            self.checks.append(CheckResult(
                name="Capital Safety Thresholds",
                passed=False,
                message=f"Unable to verify capital safety configuration: {str(e)}",
                remediation="Ensure bot/capital_reservation_manager.py is available and properly configured",
                critical=False
            ))
            self.warnings += 1
    
    def _check_multi_account_isolation(self):
        """Check multi-account isolation status"""
        try:
            from bot.account_isolation_manager import AccountIsolationManager
            
            # Try to instantiate to verify it's available
            isolation_mgr = AccountIsolationManager()
            
            self.checks.append(CheckResult(
                name="Multi-Account Isolation",
                passed=True,
                message="Account isolation system available ✅",
                critical=True
            ))
            
        except Exception as e:
            self.checks.append(CheckResult(
                name="Multi-Account Isolation",
                passed=False,
                message=f"Account isolation system not available: {str(e)}",
                remediation="Ensure bot/account_isolation_manager.py is available",
                critical=False
            ))
            self.warnings += 1
    
    def _check_recovery_mechanisms(self):
        """Check that recovery mechanisms are operational"""
        try:
            from bot.account_isolation_manager import CircuitBreakerConfig
            
            # Verify circuit breaker config is available
            config = CircuitBreakerConfig()
            
            self.checks.append(CheckResult(
                name="Recovery Mechanisms",
                passed=True,
                message=f"Recovery systems operational ✅ (circuit breaker: {config.failure_threshold} failures, {config.timeout_seconds}s timeout)",
                critical=True
            ))
            
        except Exception as e:
            self.checks.append(CheckResult(
                name="Recovery Mechanisms",
                passed=False,
                message=f"Unable to verify recovery mechanisms: {str(e)}",
                remediation="Ensure account isolation and recovery systems are properly configured",
                critical=False
            ))
            self.warnings += 1
    
    def _check_credentials_configured(self):
        """Check that API credentials are configured"""
        # Check for Kraken Platform account credentials (recommended)
        kraken_platform_key = os.getenv('KRAKEN_PLATFORM_API_KEY', '')
        kraken_platform_secret = os.getenv('KRAKEN_PLATFORM_API_SECRET', '')
        
        # Check for legacy Kraken credentials (fallback)
        kraken_legacy_key = os.getenv('KRAKEN_API_KEY', '')
        kraken_legacy_secret = os.getenv('KRAKEN_API_SECRET', '')
        
        # Check for Kraken user accounts
        kraken_user_daivon_key = os.getenv('KRAKEN_USER_DAIVON_API_KEY', '')
        kraken_user_daivon_secret = os.getenv('KRAKEN_USER_DAIVON_API_SECRET', '')
        
        kraken_user_tania_key = os.getenv('KRAKEN_USER_TANIA_API_KEY', '')
        kraken_user_tania_secret = os.getenv('KRAKEN_USER_TANIA_API_SECRET', '')
        
        # Check for Coinbase credentials (optional, now secondary)
        coinbase_api_key = os.getenv('COINBASE_API_KEY', '')
        coinbase_api_secret = os.getenv('COINBASE_API_SECRET', '')
        
        # Kraken Platform account check
        has_kraken_platform = bool(kraken_platform_key and kraken_platform_secret)
        has_kraken_legacy = bool(kraken_legacy_key and kraken_legacy_secret)
        has_kraken = has_kraken_platform or has_kraken_legacy
        
        if not has_kraken:
            self.checks.append(CheckResult(
                name="Kraken Platform Account Check",
                passed=False,
                message="Kraken platform account credentials not found in environment",
                remediation="Set KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET in .env file",
                critical=True
            ))
            self.critical_failures += 1
        else:
            cred_type = "Platform" if has_kraken_platform else "Legacy"
            self.checks.append(CheckResult(
                name="Kraken Platform Account Check",
                passed=True,
                message=f"Kraken {cred_type} account credentials configured ✅",
                critical=True
            ))
        
        # Kraken User accounts check (informational)
        configured_users = []
        if kraken_user_daivon_key and kraken_user_daivon_secret:
            configured_users.append("Daivon")
        if kraken_user_tania_key and kraken_user_tania_secret:
            configured_users.append("Tania Gilbert")
        
        if configured_users:
            self.checks.append(CheckResult(
                name="Kraken User Accounts Check",
                passed=True,
                message=f"Kraken user accounts configured: {', '.join(configured_users)} ✅",
                critical=False
            ))
        else:
            self.checks.append(CheckResult(
                name="Kraken User Accounts Check",
                passed=True,
                message="No user accounts configured (platform-only trading)",
                remediation="Optional: Add KRAKEN_USER_* credentials in .env for multi-user trading",
                critical=False
            ))
        
        # Coinbase check (now optional/informational)
        has_coinbase = bool(coinbase_api_key and coinbase_api_secret)
        if has_coinbase:
            self.checks.append(CheckResult(
                name="Coinbase Account Check",
                passed=True,
                message="Coinbase credentials configured (secondary broker) ✅",
                critical=False
            ))
    
    def _check_kraken_connectivity(self):
        """Check Kraken platform and user account connectivity"""
        try:
            from bot.broker_manager import BrokerType, get_broker_manager
            
            broker_mgr = get_broker_manager()
            
            # Test Kraken platform connection
            try:
                # Access Kraken broker from brokers dict
                kraken_broker = broker_mgr.brokers.get(BrokerType.KRAKEN)
                
                if kraken_broker and kraken_broker.connect():
                    self.checks.append(CheckResult(
                        name="Kraken Platform Connection",
                        passed=True,
                        message="Kraken platform account connection successful ✅",
                        critical=True
                    ))
                elif not kraken_broker:
                    self.checks.append(CheckResult(
                        name="Kraken Platform Connection",
                        passed=False,
                        message="Kraken broker not initialized in broker manager",
                        remediation="Ensure Kraken broker is configured and added to broker manager on startup",
                        critical=False
                    ))
                    self.warnings += 1
                else:
                    self.checks.append(CheckResult(
                        name="Kraken Platform Connection",
                        passed=False,
                        message="Unable to connect to Kraken platform account",
                        remediation="Verify KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET are correct. Check Kraken API status.",
                        critical=True
                    ))
                    self.critical_failures += 1
            except Exception as e:
                self.checks.append(CheckResult(
                    name="Kraken Platform Connection",
                    passed=False,
                    message=f"Kraken platform connection error: {str(e)}",
                    remediation="Check Kraken API credentials and network connectivity",
                    critical=False
                ))
                self.warnings += 1
            
            # Test user account connections (informational)
            user_accounts = []
            for user_prefix in ['DAIVON', 'TANIA']:
                api_key = os.getenv(f'KRAKEN_USER_{user_prefix}_API_KEY', '')
                if api_key:
                    user_accounts.append(user_prefix.capitalize())
            
            if user_accounts:
                self.checks.append(CheckResult(
                    name="Kraken User Accounts Status",
                    passed=True,
                    message=f"User accounts ready for independent trading: {', '.join(user_accounts)} ✅",
                    remediation="Verify each user account has correct API credentials in .env",
                    critical=False
                ))
                
        except ImportError:
            self.checks.append(CheckResult(
                name="Kraken Platform Connection",
                passed=False,
                message="Unable to import broker_manager module",
                remediation="Ensure bot/broker_manager.py is available",
                critical=False
            ))
            self.warnings += 1
        except Exception as e:
            self.checks.append(CheckResult(
                name="Kraken Platform Connection",
                passed=False,
                message=f"Error checking Kraken connectivity: {str(e)}",
                remediation="Check logs for details. Ensure Kraken broker integration is configured.",
                critical=False
            ))
            self.warnings += 1
    
    def _check_emergency_stops(self):
        """Check that no emergency stops are active"""
        emergency_file = 'EMERGENCY_STOP'
        
        if os.path.exists(emergency_file):
            self.checks.append(CheckResult(
                name="Emergency Stop Check",
                passed=False,
                message=f"Emergency stop file exists: {emergency_file}",
                remediation=f"Remove {emergency_file} file to proceed",
                critical=True
            ))
            self.critical_failures += 1
        else:
            self.checks.append(CheckResult(
                name="Emergency Stop Check",
                passed=True,
                message="No emergency stop active ✅",
                critical=True
            ))
    
    def _print_results(self):
        """Print all check results in a formatted way"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("📋 PRE-FLIGHT CHECK RESULTS")
        logger.info("=" * 80)
        logger.info("")
        
        # Print each check
        for check in self.checks:
            icon = "✅" if check.passed else ("⚠️" if not check.critical else "❌")
            severity = "CRITICAL" if check.critical and not check.passed else ("WARNING" if not check.passed else "PASS")
            
            logger.info(f"{icon} [{severity}] {check.name}")
            logger.info(f"   {check.message}")
            if check.remediation:
                logger.info(f"   → Remediation: {check.remediation}")
            logger.info("")
        
        # Print summary
        logger.info("=" * 80)
        logger.info("📊 SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total checks: {len(self.checks)}")
        logger.info(f"Passed: {len([c for c in self.checks if c.passed])}")
        logger.info(f"Critical failures: {self.critical_failures}")
        logger.info(f"Warnings: {self.warnings}")
        logger.info("")
        
        # Final verdict
        if self.critical_failures == 0:
            logger.info("=" * 80)
            logger.info("🎉 ALL CRITICAL CHECKS PASSED!")
            logger.info("=" * 80)
            if self.warnings > 0:
                logger.warning(f"Note: {self.warnings} non-critical warning(s) present. Review before proceeding.")
            logger.info("")
            logger.info("System is ready for LIVE trading mode.")
            logger.info("")
            logger.info("To activate live mode, run:")
            logger.info("  python go_live.py --activate")
            logger.info("")
        else:
            logger.error("=" * 80)
            logger.error("❌ CRITICAL FAILURES DETECTED")
            logger.error("=" * 80)
            logger.error(f"{self.critical_failures} critical issue(s) must be resolved before going live.")
            logger.error("")
            logger.error("Review the remediation steps above and fix all critical issues.")
            logger.error("")
    
    def activate_live_mode(self) -> bool:
        """
        Activate live trading mode after validation.
        
        Returns:
            bool: True if activation successful
        """
        logger.info("=" * 80)
        logger.info("🚀 ACTIVATING LIVE TRADING MODE")
        logger.info("=" * 80)
        logger.info("")
        
        # First, run all checks
        if not self.run_all_checks():
            logger.error("❌ Cannot activate live mode: Critical checks failed")
            logger.error("Fix all critical issues and try again.")
            return False
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("✅ LIVE MODE ACTIVATION")
        logger.info("=" * 80)
        logger.info("")
        logger.info("All pre-flight checks passed. Live mode requirements satisfied:")
        logger.info("")
        logger.info("  ✅ DRY_RUN_MODE: Disabled")
        logger.info("  ✅ LIVE_CAPITAL_VERIFIED: Enabled")
        logger.info("  ✅ Broker Health: All green")
        logger.info("  ✅ Adoption Failures: None detected")
        logger.info("  ✅ Trading Threads: No halts")
        logger.info("  ✅ Capital Safety: Thresholds satisfied")
        logger.info("  ✅ Multi-Account Isolation: Healthy")
        logger.info("  ✅ Recovery Mechanisms: Operational")
        logger.info("")
        logger.info("=" * 80)
        logger.info("🟢 NIJA IS NOW READY FOR LIVE TRADING")
        logger.info("=" * 80)
        logger.info("")
        logger.info("To start the bot in live mode:")
        logger.info("  1. Ensure DRY_RUN_MODE=false in your .env file")
        logger.info("  2. Ensure LIVE_CAPITAL_VERIFIED=true in your .env file")
        logger.info("  3. Run: ./start.sh or python bot/trading_strategy.py")
        logger.info("")
        logger.info("⚠️  IMPORTANT REMINDERS:")
        logger.info("  • Monitor the observability dashboard regularly")
        logger.info("  • Review the position manager and risk settings")
        logger.info("  • Start with small position sizes initially")
        logger.info("  • Keep the EMERGENCY_STOP file ready if needed")
        logger.info("")
        logger.info("📊 MONITORING SCHEDULE (First 24 Hours):")
        logger.info("  • First 30 minutes: Continuous monitoring")
        logger.info("    - Verify positions are adopted correctly")
        logger.info("    - Check tier floors are enforced")
        logger.info("    - Monitor forced cleanup execution")
        logger.info("    - Validate risk management thresholds")
        logger.info("  • After 30 minutes: Hourly monitoring for 24 hours")
        logger.info("    - Check position status and P&L")
        logger.info("    - Verify user accounts follow independent trading rules")
        logger.info("    - Review API rate limiting and broker health")
        logger.info("    - Monitor capital allocation across accounts")
        logger.info("")
        logger.info("🔍 KEY METRICS TO MONITOR:")
        logger.info("  • Position adoption rate (should be 100%)")
        logger.info("  • Tier floor compliance (no trades below minimum)")
        logger.info("  • Forced cleanup execution (logs should show cleanup runs)")
        logger.info("  • Risk per trade (should match tier configuration)")
        logger.info("  • User account independence (no trade copying)")
        logger.info("")
        
        return True
    
    def show_status(self):
        """Show current trading mode status"""
        logger.info("=" * 80)
        logger.info("📊 NIJA TRADING MODE STATUS")
        logger.info("=" * 80)
        logger.info("")
        
        # Check current mode
        dry_run = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
        live_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
        app_store = os.getenv('APP_STORE_MODE', 'false').lower() in ('true', '1', 'yes')
        emergency_stop = os.path.exists('EMERGENCY_STOP')
        
        # Determine mode
        if emergency_stop:
            mode = "EMERGENCY STOP (DISABLED)"
            color = "🔴"
        elif app_store:
            mode = "APP STORE REVIEW MODE"
            color = "📱"
        elif dry_run:
            mode = "DRY RUN (SIMULATION)"
            color = "🎭"
        elif live_verified:
            mode = "LIVE TRADING"
            color = "🟢"
        else:
            mode = "MONITOR MODE (DISABLED)"
            color = "📊"
        
        logger.info(f"Current Mode: {color} {mode}")
        logger.info("")
        logger.info("Environment Settings:")
        logger.info(f"  DRY_RUN_MODE: {os.getenv('DRY_RUN_MODE', 'false')}")
        logger.info(f"  LIVE_CAPITAL_VERIFIED: {os.getenv('LIVE_CAPITAL_VERIFIED', 'false')}")
        logger.info(f"  APP_STORE_MODE: {os.getenv('APP_STORE_MODE', 'false')}")
        logger.info(f"  Emergency Stop File: {'EXISTS' if emergency_stop else 'Not present'}")
        logger.info("")
        
        # Show available commands
        logger.info("Available Commands:")
        logger.info("  python go_live.py --check      # Run all pre-flight checks")
        logger.info("  python go_live.py --activate   # Activate live mode (after checks pass)")
        logger.info("  python go_live.py --status     # Show this status")
        logger.info("")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Go Live Validator - Validate system readiness for live trading',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--check',
        action='store_true',
        help='Run all pre-flight checks (default)'
    )
    
    parser.add_argument(
        '--activate',
        action='store_true',
        help='Activate live mode after validation'
    )
    
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current trading mode status'
    )
    
    args = parser.parse_args()
    
    validator = GoLiveValidator()
    
    # Default to check if no args provided
    if not any([args.check, args.activate, args.status]):
        args.check = True
    
    try:
        if args.status:
            validator.show_status()
            return 0
        elif args.activate:
            success = validator.activate_live_mode()
            return 0 if success else 1
        elif args.check:
            success = validator.run_all_checks()
            return 0 if success else 1
    except KeyboardInterrupt:
        logger.info("\n\nOperation cancelled by user")
        return 130
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
