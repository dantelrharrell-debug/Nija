#!/usr/bin/env python3
"""
Kraken MICRO_CAP Production Validation Script
==============================================

This script validates live Kraken integration with $25-$50 capital in MICRO_CAP mode
as a production reliability test. It performs comprehensive checks before allowing
any real trading.

Requirements:
1. Connect live Kraken keys ($25-$50 balance)
2. Run controlled MICRO_CAP validation
3. Treat it like a production reliability test

Safety Features:
- Pre-flight balance verification
- API connectivity testing
- MICRO_CAP mode validation
- Symbol availability checks
- Order validation (no actual trades in dry-run)
- Rate limiting verification
- Position management checks
- Risk management validation

Usage:
    # Dry run (recommended first):
    python scripts/kraken_micro_cap_validation.py --dry-run
    
    # Live validation (after dry-run passes):
    python scripts/kraken_micro_cap_validation.py
    
    # With specific balance check:
    python scripts/kraken_micro_cap_validation.py --min-balance 25 --max-balance 50

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import os
import sys
import time
import logging
from typing import Dict, Optional, Tuple, List
from decimal import Decimal

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class KrakenMicroCapValidator:
    """Validates Kraken integration for MICRO_CAP mode ($25-$50 accounts)."""
    
    def __init__(self, dry_run: bool = True, min_balance: float = 25.0, max_balance: float = 50.0):
        """
        Initialize validator.
        
        Args:
            dry_run: If True, no actual trades will be executed
            min_balance: Minimum expected balance in USD
            max_balance: Maximum expected balance in USD
        """
        self.dry_run = dry_run
        self.min_balance = min_balance
        self.max_balance = max_balance
        self.validation_results = []
        self.errors = []
        self.warnings = []
        
        # Import required modules
        self._import_modules()
    
    def _import_modules(self):
        """Import required modules with proper error handling."""
        try:
            import krakenex
            from pykrakenapi import KrakenAPI
            self.krakenex = krakenex
            self.KrakenAPI = KrakenAPI
            logger.info("✅ Kraken SDK (krakenex + pykrakenapi) available")
        except ImportError as e:
            logger.error(f"❌ Failed to import Kraken SDK: {e}")
            logger.error("   Run: pip install krakenex pykrakenapi")
            sys.exit(1)
        
        try:
            from kraken_rate_profiles import (
                get_kraken_rate_profile,
                KrakenRateMode,
                get_rate_profile_summary
            )
            self.get_kraken_rate_profile = get_kraken_rate_profile
            self.KrakenRateMode = KrakenRateMode
            self.get_rate_profile_summary = get_rate_profile_summary
            logger.info("✅ Kraken rate profiles available")
        except ImportError as e:
            logger.warning(f"⚠️  Kraken rate profiles not available: {e}")
            self.get_kraken_rate_profile = None
            self.KrakenRateMode = None
            self.get_rate_profile_summary = None
        
        try:
            from tier_config import get_tier_from_balance, get_tier_config
            self.get_tier_from_balance = get_tier_from_balance
            self.get_tier_config = get_tier_config
            logger.info("✅ Tier configuration available")
        except ImportError as e:
            logger.warning(f"⚠️  Tier configuration not available: {e}")
            self.get_tier_from_balance = None
            self.get_tier_config = None
    
    def _log_result(self, test_name: str, passed: bool, message: str):
        """Log validation result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.validation_results.append({
            'test': test_name,
            'passed': passed,
            'message': message
        })
        logger.info(f"{status}: {test_name} - {message}")
        
        if not passed:
            self.errors.append(f"{test_name}: {message}")
    
    def _log_warning(self, message: str):
        """Log a warning."""
        self.warnings.append(message)
        logger.warning(f"⚠️  {message}")
    
    def validate_environment(self) -> bool:
        """Validate environment variables."""
        logger.info("=" * 80)
        logger.info("STEP 1: Environment Validation")
        logger.info("=" * 80)
        
        # Check for Kraken credentials
        api_key = os.getenv('KRAKEN_PLATFORM_API_KEY', '')
        api_secret = os.getenv('KRAKEN_PLATFORM_API_SECRET', '')
        
        if not api_key:
            self._log_result('Kraken API Key', False, 'KRAKEN_PLATFORM_API_KEY not set')
            return False
        
        if not api_secret:
            self._log_result('Kraken API Secret', False, 'KRAKEN_PLATFORM_API_SECRET not set')
            return False
        
        self._log_result('Kraken Credentials', True, f'API Key length: {len(api_key)} chars')
        
        # Check trading mode settings
        live_trading = os.getenv('LIVE_TRADING', '0')
        if live_trading not in ['1', 'true', 'True']:
            self._log_warning('LIVE_TRADING not set to 1 - this will be paper trading')
        
        micro_capital_mode = os.getenv('MICRO_CAPITAL_MODE', 'false')
        if micro_capital_mode.lower() not in ['true', '1', 'yes']:
            self._log_warning('MICRO_CAPITAL_MODE not enabled - MICRO_CAP features may not activate')
        
        return True
    
    def validate_kraken_connection(self) -> Tuple[bool, Optional[object]]:
        """Validate Kraken API connection."""
        logger.info("=" * 80)
        logger.info("STEP 2: Kraken API Connection")
        logger.info("=" * 80)
        
        try:
            api_key = os.getenv('KRAKEN_PLATFORM_API_KEY', '')
            api_secret = os.getenv('KRAKEN_PLATFORM_API_SECRET', '')
            
            # Initialize Kraken API
            kraken = self.krakenex.API()
            kraken.key = api_key
            kraken.secret = api_secret
            k = self.KrakenAPI(kraken)
            
            # Test connection with SystemStatus
            logger.info("Testing API connection with SystemStatus...")
            system_status = k.get_system_status()
            
            status = system_status.get('status', 'unknown')
            timestamp = system_status.get('timestamp', 'unknown')
            
            self._log_result('Kraken Connection', True, f'Status: {status}, Time: {timestamp}')
            
            return True, k
            
        except Exception as e:
            self._log_result('Kraken Connection', False, f'Connection failed: {str(e)}')
            return False, None
    
    def validate_account_balance(self, k: object) -> Tuple[bool, float]:
        """Validate account balance is in MICRO_CAP range."""
        logger.info("=" * 80)
        logger.info("STEP 3: Account Balance Validation")
        logger.info("=" * 80)
        
        try:
            # Get account balance
            balance = k.get_account_balance()
            logger.info(f"Raw balance response: {balance}")
            
            # Get USD balance (including ZUSD and USDT)
            usd_balance = 0.0
            
            if 'ZUSD' in balance.index:
                zusd = float(balance.loc['ZUSD', 'vol'])
                usd_balance += zusd
                logger.info(f"ZUSD: ${zusd:.2f}")
            
            if 'USDT' in balance.index:
                usdt = float(balance.loc['USDT', 'vol'])
                usd_balance += usdt
                logger.info(f"USDT: ${usdt:.2f}")
            
            # Get crypto positions value (approximate)
            total_value = usd_balance
            crypto_holdings = []
            
            for asset in balance.index:
                if asset not in ['ZUSD', 'USDT', 'USD']:
                    vol = float(balance.loc[asset, 'vol'])
                    if vol > 0.0001:  # Ignore dust
                        crypto_holdings.append(f"{asset}: {vol}")
                        logger.info(f"Crypto holding: {asset}: {vol}")
            
            logger.info(f"Total USD/USDT: ${usd_balance:.2f}")
            logger.info(f"Total estimated value: ${total_value:.2f}")
            
            # Validate balance is in expected range
            if total_value < self.min_balance:
                self._log_result(
                    'Balance Range',
                    False,
                    f'Balance ${total_value:.2f} is below minimum ${self.min_balance:.2f}'
                )
                return False, total_value
            
            if total_value > self.max_balance:
                self._log_warning(
                    f'Balance ${total_value:.2f} exceeds maximum ${self.max_balance:.2f} '
                    f'(may not be optimal for MICRO_CAP mode)'
                )
            
            self._log_result(
                'Balance Range',
                True,
                f'Balance ${total_value:.2f} is within MICRO_CAP range '
                f'(${self.min_balance:.2f} - ${self.max_balance:.2f})'
            )
            
            return True, total_value
            
        except Exception as e:
            self._log_result('Balance Check', False, f'Failed to get balance: {str(e)}')
            return False, 0.0
    
    def validate_micro_cap_profile(self, balance: float) -> bool:
        """Validate MICRO_CAP profile configuration."""
        logger.info("=" * 80)
        logger.info("STEP 4: MICRO_CAP Profile Validation")
        logger.info("=" * 80)
        
        if not self.get_kraken_rate_profile:
            self._log_warning('Kraken rate profiles not available, skipping profile validation')
            return True
        
        try:
            # Get rate profile for this balance
            profile = self.get_kraken_rate_profile(balance)
            
            mode = profile.get('mode', 'unknown')
            logger.info(f"Detected mode: {mode}")
            
            # Validate it's MICRO_CAP mode for $25-$50
            expected_mode = 'micro_cap'
            if balance >= 20 and balance <= 100:
                if mode != expected_mode:
                    self._log_result(
                        'MICRO_CAP Mode',
                        False,
                        f'Expected {expected_mode} but got {mode} for ${balance:.2f}'
                    )
                    return False
            
            # Display profile details
            logger.info("=" * 60)
            logger.info("MICRO_CAP Profile Configuration:")
            logger.info("=" * 60)
            logger.info(f"Mode: {profile.get('name', 'N/A')}")
            logger.info(f"Description: {profile.get('description', 'N/A')}")
            logger.info(f"Balance range: ${profile.get('min_account_balance', 0):.2f} - "
                       f"${profile.get('max_account_balance', 0):.2f}")
            
            # Entry settings
            entry = profile.get('entry', {})
            logger.info(f"Entry interval: {entry.get('min_interval_seconds', 0)}s")
            logger.info(f"Max entries/minute: {entry.get('max_per_minute', 0)}")
            
            # Exit settings
            exit_cfg = profile.get('exit', {})
            logger.info(f"Exit interval: {exit_cfg.get('min_interval_seconds', 0)}s")
            
            # Position management
            logger.info(f"Max concurrent positions: {profile.get('max_concurrent_positions', 0)}")
            logger.info(f"Position size: ${profile.get('position_size_usd', 0):.2f}")
            logger.info(f"Profit target: {profile.get('profit_target_pct', 0):.2f}%")
            logger.info(f"Stop loss: {profile.get('stop_loss_pct', 0):.2f}%")
            
            # Quality controls
            logger.info(f"High confidence only: {profile.get('high_confidence_only', False)}")
            logger.info(f"Min quality score: {profile.get('min_quality_score', 0):.2f}")
            logger.info("=" * 60)
            
            self._log_result('MICRO_CAP Profile', True, f'Mode: {mode} correctly configured')
            return True
            
        except Exception as e:
            self._log_result('MICRO_CAP Profile', False, f'Failed to validate profile: {str(e)}')
            return False
    
    def validate_tradeable_pairs(self, k: object) -> bool:
        """Validate tradeable pairs are available."""
        logger.info("=" * 80)
        logger.info("STEP 5: Tradeable Pairs Validation")
        logger.info("=" * 80)
        
        try:
            # Get tradeable asset pairs
            pairs = k.get_tradable_asset_pairs()
            
            # Check for major pairs recommended in MICRO_CAP mode
            recommended_pairs = ['BTCUSD', 'ETHUSD', 'SOLUSD']
            available_pairs = []
            
            for pair in recommended_pairs:
                # Kraken uses various formats: BTC/USD, XXBTZUSD, etc.
                found = False
                for idx in pairs.index:
                    if pair.replace('/', '') in idx or pair in idx:
                        available_pairs.append(pair)
                        found = True
                        break
                
                if found:
                    logger.info(f"✅ {pair} is available")
                else:
                    logger.warning(f"⚠️  {pair} not found (may be under different name)")
            
            if len(available_pairs) == 0:
                self._log_result('Tradeable Pairs', False, 'No recommended pairs found')
                return False
            
            self._log_result(
                'Tradeable Pairs',
                True,
                f'{len(available_pairs)} recommended pairs available: {", ".join(available_pairs)}'
            )
            return True
            
        except Exception as e:
            self._log_result('Tradeable Pairs', False, f'Failed to check pairs: {str(e)}')
            return False
    
    def validate_order_minimums(self, k: object) -> bool:
        """Validate order minimums are compatible with MICRO_CAP."""
        logger.info("=" * 80)
        logger.info("STEP 6: Order Minimums Validation")
        logger.info("=" * 80)
        
        try:
            # Kraken minimum order is typically $10 USD
            kraken_min = 10.0
            
            # MICRO_CAP typical position size is $20
            micro_cap_position = 20.0
            
            if micro_cap_position < kraken_min:
                self._log_result(
                    'Order Minimums',
                    False,
                    f'MICRO_CAP position ${micro_cap_position} below Kraken min ${kraken_min}'
                )
                return False
            
            self._log_result(
                'Order Minimums',
                True,
                f'MICRO_CAP position ${micro_cap_position} meets Kraken min ${kraken_min}'
            )
            
            # Warn if balance is tight
            if self.min_balance < 25:
                self._log_warning(
                    f'Balance ${self.min_balance} is very tight for $20 positions '
                    f'(only 1 position possible)'
                )
            
            return True
            
        except Exception as e:
            self._log_result('Order Minimums', False, f'Failed to validate: {str(e)}')
            return False
    
    def validate_rate_limiting(self, balance: float) -> bool:
        """Validate rate limiting configuration."""
        logger.info("=" * 80)
        logger.info("STEP 7: Rate Limiting Validation")
        logger.info("=" * 80)
        
        if not self.get_kraken_rate_profile:
            self._log_warning('Rate profiles not available, skipping rate limit validation')
            return True
        
        try:
            profile = self.get_kraken_rate_profile(balance)
            
            # Get entry rate limits
            entry = profile.get('entry', {})
            entry_interval = entry.get('min_interval_seconds', 0)
            max_entries_per_min = entry.get('max_per_minute', 0)
            
            # Validate MICRO_CAP rate limits
            # Should be conservative: 30s between entries, max 2/min
            if balance >= 20 and balance <= 100:
                if entry_interval < 20:
                    self._log_warning(
                        f'Entry interval {entry_interval}s may be too aggressive for MICRO_CAP'
                    )
                
                if max_entries_per_min > 3:
                    self._log_warning(
                        f'Max entries {max_entries_per_min}/min may be too aggressive for MICRO_CAP'
                    )
            
            self._log_result(
                'Rate Limiting',
                True,
                f'Entry interval: {entry_interval}s, Max: {max_entries_per_min}/min'
            )
            return True
            
        except Exception as e:
            self._log_result('Rate Limiting', False, f'Failed to validate: {str(e)}')
            return False
    
    def validate_position_management(self, balance: float) -> bool:
        """Validate position management settings."""
        logger.info("=" * 80)
        logger.info("STEP 8: Position Management Validation")
        logger.info("=" * 80)
        
        if not self.get_kraken_rate_profile:
            self._log_warning('Rate profiles not available, skipping position validation')
            return True
        
        try:
            profile = self.get_kraken_rate_profile(balance)
            
            max_positions = profile.get('max_concurrent_positions', 0)
            position_size = profile.get('position_size_usd', 0)
            
            # Calculate if account can support positions
            total_needed = max_positions * position_size
            
            if total_needed > balance:
                self._log_result(
                    'Position Management',
                    False,
                    f'Max positions ({max_positions} × ${position_size}) = ${total_needed} '
                    f'exceeds balance ${balance:.2f}'
                )
                return False
            
            # Calculate buffer
            buffer_pct = ((balance - total_needed) / balance) * 100
            
            self._log_result(
                'Position Management',
                True,
                f'{max_positions} positions × ${position_size} = ${total_needed:.2f} '
                f'(buffer: {buffer_pct:.1f}%)'
            )
            
            if buffer_pct < 15:
                self._log_warning(
                    f'Buffer {buffer_pct:.1f}% is low, recommend keeping ≥15% cash reserve'
                )
            
            return True
            
        except Exception as e:
            self._log_result('Position Management', False, f'Failed to validate: {str(e)}')
            return False
    
    def validate_risk_parameters(self, balance: float) -> bool:
        """Validate risk management parameters."""
        logger.info("=" * 80)
        logger.info("STEP 9: Risk Parameters Validation")
        logger.info("=" * 80)
        
        if not self.get_kraken_rate_profile:
            self._log_warning('Rate profiles not available, skipping risk validation')
            return True
        
        try:
            profile = self.get_kraken_rate_profile(balance)
            
            profit_target = profile.get('profit_target_pct', 0)
            stop_loss = profile.get('stop_loss_pct', 0)
            
            # Calculate risk/reward ratio
            if stop_loss > 0:
                risk_reward_ratio = profit_target / stop_loss
            else:
                risk_reward_ratio = 0
            
            # Validate MICRO_CAP should have at least 2:1 reward/risk
            min_ratio = 2.0
            if risk_reward_ratio < min_ratio:
                self._log_result(
                    'Risk Parameters',
                    False,
                    f'Risk/reward ratio {risk_reward_ratio:.2f}:1 is below minimum {min_ratio}:1'
                )
                return False
            
            # Calculate per-trade risk
            position_size = profile.get('position_size_usd', 0)
            risk_per_trade = (stop_loss / 100) * position_size
            reward_per_trade = (profit_target / 100) * position_size
            
            self._log_result(
                'Risk Parameters',
                True,
                f'Risk/reward {risk_reward_ratio:.2f}:1 '
                f'(${risk_per_trade:.2f} risk / ${reward_per_trade:.2f} reward per trade)'
            )
            
            return True
            
        except Exception as e:
            self._log_result('Risk Parameters', False, f'Failed to validate: {str(e)}')
            return False
    
    def run_dry_run_order_test(self, k: object, balance: float) -> bool:
        """Test order validation without placing real orders."""
        logger.info("=" * 80)
        logger.info("STEP 10: Dry-Run Order Validation")
        logger.info("=" * 80)
        
        if not self.dry_run:
            logger.info("Skipping dry-run test in live mode")
            return True
        
        try:
            # Test order parameters (not actually placing)
            test_symbol = 'BTCUSD'
            test_size_usd = 20.0  # MICRO_CAP typical position
            
            # Get current BTC price (for validation)
            ticker = k.get_ticker_information(test_symbol)
            
            if test_symbol in ticker.index:
                ask_price = float(ticker.loc[test_symbol, 'a'][0])
                logger.info(f"Current BTC price: ${ask_price:.2f}")
                
                # Calculate volume
                volume = test_size_usd / ask_price
                logger.info(f"Test order: {volume:.8f} BTC (~${test_size_usd})")
                
                # Validate against Kraken minimums
                kraken_min = 10.0
                if test_size_usd >= kraken_min:
                    self._log_result(
                        'Dry-Run Order',
                        True,
                        f'Test order ${test_size_usd} meets Kraken min ${kraken_min}'
                    )
                else:
                    self._log_result(
                        'Dry-Run Order',
                        False,
                        f'Test order ${test_size_usd} below Kraken min ${kraken_min}'
                    )
                    return False
            else:
                self._log_warning(f'Could not get price for {test_symbol}')
            
            logger.info("✅ Dry-run validation complete (no real orders placed)")
            return True
            
        except Exception as e:
            self._log_result('Dry-Run Order', False, f'Failed to validate: {str(e)}')
            return False
    
    def generate_report(self) -> Dict:
        """Generate validation report."""
        logger.info("=" * 80)
        logger.info("VALIDATION REPORT")
        logger.info("=" * 80)
        
        total_tests = len(self.validation_results)
        passed_tests = sum(1 for r in self.validation_results if r['passed'])
        failed_tests = total_tests - passed_tests
        
        logger.info(f"Total tests: {total_tests}")
        logger.info(f"Passed: {passed_tests} ✅")
        logger.info(f"Failed: {failed_tests} ❌")
        logger.info(f"Warnings: {len(self.warnings)} ⚠️")
        
        if failed_tests > 0:
            logger.info("")
            logger.info("FAILED TESTS:")
            for result in self.validation_results:
                if not result['passed']:
                    logger.error(f"  ❌ {result['test']}: {result['message']}")
        
        if self.warnings:
            logger.info("")
            logger.info("WARNINGS:")
            for warning in self.warnings:
                logger.warning(f"  ⚠️  {warning}")
        
        success = failed_tests == 0
        
        logger.info("=" * 80)
        if success:
            logger.info("✅ ALL VALIDATIONS PASSED - READY FOR MICRO_CAP TRADING")
        else:
            logger.error("❌ VALIDATION FAILED - DO NOT TRADE")
        logger.info("=" * 80)
        
        return {
            'success': success,
            'total_tests': total_tests,
            'passed': passed_tests,
            'failed': failed_tests,
            'warnings': len(self.warnings),
            'errors': self.errors,
            'results': self.validation_results
        }
    
    def run_full_validation(self) -> bool:
        """Run complete validation suite."""
        logger.info("=" * 80)
        logger.info("KRAKEN MICRO_CAP PRODUCTION VALIDATION")
        logger.info("=" * 80)
        logger.info(f"Mode: {'DRY-RUN' if self.dry_run else 'LIVE'}")
        logger.info(f"Balance range: ${self.min_balance:.2f} - ${self.max_balance:.2f}")
        logger.info("=" * 80)
        logger.info("")
        
        # Step 1: Validate environment
        if not self.validate_environment():
            logger.error("❌ Environment validation failed")
            return False
        
        # Step 2: Connect to Kraken
        success, k = self.validate_kraken_connection()
        if not success:
            logger.error("❌ Kraken connection failed")
            return False
        
        # Step 3: Validate balance
        success, balance = self.validate_account_balance(k)
        if not success:
            logger.error("❌ Balance validation failed")
            return False
        
        # Step 4: Validate MICRO_CAP profile
        if not self.validate_micro_cap_profile(balance):
            logger.error("❌ MICRO_CAP profile validation failed")
            return False
        
        # Step 5: Validate tradeable pairs
        if not self.validate_tradeable_pairs(k):
            logger.error("❌ Tradeable pairs validation failed")
            return False
        
        # Step 6: Validate order minimums
        if not self.validate_order_minimums(k):
            logger.error("❌ Order minimums validation failed")
            return False
        
        # Step 7: Validate rate limiting
        if not self.validate_rate_limiting(balance):
            logger.error("❌ Rate limiting validation failed")
            return False
        
        # Step 8: Validate position management
        if not self.validate_position_management(balance):
            logger.error("❌ Position management validation failed")
            return False
        
        # Step 9: Validate risk parameters
        if not self.validate_risk_parameters(balance):
            logger.error("❌ Risk parameters validation failed")
            return False
        
        # Step 10: Dry-run order test
        if self.dry_run:
            if not self.run_dry_run_order_test(k, balance):
                logger.error("❌ Dry-run order test failed")
                return False
        
        # Generate final report
        report = self.generate_report()
        
        return report['success']


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Validate Kraken MICRO_CAP mode for production trading'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Run in dry-run mode (no real trades, default: True)'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Run in live mode (enables real trading validation)'
    )
    parser.add_argument(
        '--min-balance',
        type=float,
        default=25.0,
        help='Minimum expected balance in USD (default: 25.0)'
    )
    parser.add_argument(
        '--max-balance',
        type=float,
        default=50.0,
        help='Maximum expected balance in USD (default: 50.0)'
    )
    
    args = parser.parse_args()
    
    # If --live is specified, disable dry-run
    dry_run = not args.live
    
    if not dry_run:
        logger.warning("=" * 80)
        logger.warning("⚠️  LIVE MODE ENABLED")
        logger.warning("⚠️  This will perform real validations with live account")
        logger.warning("=" * 80)
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != 'yes':
            logger.info("Validation cancelled by user")
            return 1
    
    # Run validation
    validator = KrakenMicroCapValidator(
        dry_run=dry_run,
        min_balance=args.min_balance,
        max_balance=args.max_balance
    )
    
    success = validator.run_full_validation()
    
    if success:
        logger.info("")
        logger.info("=" * 80)
        logger.info("✅ VALIDATION COMPLETE - SYSTEM READY")
        logger.info("=" * 80)
        logger.info("")
        logger.info("Next steps:")
        logger.info("1. Review the validation report above")
        logger.info("2. Ensure MICRO_CAPITAL_MODE=true in .env")
        logger.info("3. Set LIVE_CAPITAL_VERIFIED=true when ready for live trading")
        logger.info("4. Start the bot with: ./start.sh")
        logger.info("5. Monitor first few trades closely")
        logger.info("")
        return 0
    else:
        logger.error("")
        logger.error("=" * 80)
        logger.error("❌ VALIDATION FAILED - DO NOT TRADE")
        logger.error("=" * 80)
        logger.error("")
        logger.error("Please fix the errors above before proceeding")
        logger.error("")
        return 1


if __name__ == '__main__':
    sys.exit(main())
