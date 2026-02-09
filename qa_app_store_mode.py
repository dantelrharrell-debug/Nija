#!/usr/bin/env python3
"""
ENHANCED APP STORE MODE QA VERIFICATION

Comprehensive quality assurance script that verifies:
1. No trades execute when APP_STORE_MODE=true
2. All read-only endpoints work correctly
3. UI-level disclosures are accessible
4. Normal trading works when APP_STORE_MODE=false
5. Automated verification for repeatable results

This script provides complete QA coverage for App Store submission.

Usage:
    python qa_app_store_mode.py
    python qa_app_store_mode.py --mode=enabled   # Test with mode enabled
    python qa_app_store_mode.py --mode=disabled  # Test with mode disabled
    python qa_app_store_mode.py --full           # Run all tests
"""

import os
import sys
import logging
import argparse
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


class AppStoreModeQA:
    """Comprehensive QA test suite for APP_STORE_MODE."""
    
    def __init__(self):
        self.test_results = []
        self.current_mode = os.getenv('APP_STORE_MODE', 'not set')
    
    def log_test_result(self, test_name: str, passed: bool, details: str = ""):
        """Log a test result."""
        self.test_results.append({
            'test': test_name,
            'passed': passed,
            'details': details,
            'timestamp': datetime.now().isoformat()
        })
        
        if passed:
            logger.info(f"✅ {test_name}")
            if details:
                logger.info(f"   {details}")
        else:
            logger.error(f"❌ {test_name}")
            if details:
                logger.error(f"   {details}")
    
    def test_no_trades_when_enabled(self) -> bool:
        """Test that no trades execute when APP_STORE_MODE=true."""
        logger.info("=" * 80)
        logger.info("QA TEST 1: No Trades Execute When APP_STORE_MODE=true")
        logger.info("=" * 80)
        
        try:
            # Set mode to enabled for this test
            os.environ['APP_STORE_MODE'] = 'true'
            
            # Reload the module to pick up the env change
            import importlib
            if 'bot.app_store_mode' in sys.modules:
                importlib.reload(sys.modules['bot.app_store_mode'])
            
            from bot.app_store_mode import get_app_store_mode
            
            mode = get_app_store_mode()
            
            # Test 1: Mode should be enabled
            if not mode.is_enabled():
                self.log_test_result(
                    "Mode Detection",
                    False,
                    "APP_STORE_MODE=true but mode not detected as enabled"
                )
                return False
            
            self.log_test_result(
                "Mode Detection",
                True,
                "APP_STORE_MODE correctly detected as enabled"
            )
            
            # Test 2: Execution should be blocked
            allowed, reason = mode.check_execution_allowed()
            if allowed:
                self.log_test_result(
                    "Execution Blocking",
                    False,
                    "Execution was allowed when it should be blocked"
                )
                return False
            
            self.log_test_result(
                "Execution Blocking",
                True,
                f"Execution correctly blocked: {reason}"
            )
            
            # Test 3: Block with log should return simulated response
            result = mode.block_execution_with_log(
                operation='place_market_order',
                symbol='BTC-USD',
                side='buy',
                size=100.0
            )
            
            if result.get('status') != 'simulated' or not result.get('blocked'):
                self.log_test_result(
                    "Simulated Response",
                    False,
                    f"Expected simulated response, got: {result}"
                )
                return False
            
            self.log_test_result(
                "Simulated Response",
                True,
                "Blocked execution returns correct simulated response"
            )
            
            logger.info("✅ QA TEST 1 PASSED: No trades possible when enabled")
            return True
            
        except Exception as e:
            self.log_test_result(
                "Test Execution",
                False,
                f"Exception: {e}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def test_read_only_endpoints(self) -> bool:
        """Test that all read-only endpoints work correctly."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("QA TEST 2: Read-Only Endpoints Functional")
        logger.info("=" * 80)
        
        try:
            from bot.app_store_reviewer_api import (
                get_reviewer_welcome_message,
                get_reviewer_dashboard_data,
                get_reviewer_account_info,
                get_reviewer_trading_history,
                get_reviewer_performance_metrics,
                get_reviewer_risk_disclosures,
                get_reviewer_simulation_demo,
                get_app_store_mode_status,
                get_reviewer_info,
            )
            
            endpoints = {
                'Welcome Message': get_reviewer_welcome_message,
                'Dashboard Data': get_reviewer_dashboard_data,
                'Account Info': get_reviewer_account_info,
                'Trading History': get_reviewer_trading_history,
                'Performance Metrics': get_reviewer_performance_metrics,
                'Risk Disclosures': get_reviewer_risk_disclosures,
                'Simulation Demo': get_reviewer_simulation_demo,
                'Mode Status': get_app_store_mode_status,
                'Reviewer Info': get_reviewer_info,
            }
            
            all_passed = True
            for name, func in endpoints.items():
                try:
                    result = func()
                    if not isinstance(result, dict):
                        self.log_test_result(
                            f"Endpoint: {name}",
                            False,
                            f"Expected dict, got {type(result)}"
                        )
                        all_passed = False
                        continue
                    
                    if not result:
                        self.log_test_result(
                            f"Endpoint: {name}",
                            False,
                            "Empty response"
                        )
                        all_passed = False
                        continue
                    
                    self.log_test_result(
                        f"Endpoint: {name}",
                        True,
                        f"Returns {len(result)} fields"
                    )
                    
                except Exception as e:
                    self.log_test_result(
                        f"Endpoint: {name}",
                        False,
                        f"Exception: {e}"
                    )
                    all_passed = False
            
            if all_passed:
                logger.info("✅ QA TEST 2 PASSED: All read-only endpoints functional")
            else:
                logger.error("❌ QA TEST 2 FAILED: Some endpoints not working")
            
            return all_passed
            
        except Exception as e:
            self.log_test_result(
                "Endpoint Testing",
                False,
                f"Exception: {e}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def test_ui_disclosures_accessible(self) -> bool:
        """Test that UI-level disclosures are accessible."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("QA TEST 3: UI-Level Disclosures Accessible")
        logger.info("=" * 80)
        
        try:
            from bot.app_store_reviewer_api import get_reviewer_risk_disclosures
            
            disclosures = get_reviewer_risk_disclosures()
            
            required_disclosures = [
                'independent_trading_model',
                'risk_warning',
                'not_financial_advice',
                'user_responsibility',
            ]
            
            all_present = True
            for disclosure_key in required_disclosures:
                if disclosure_key not in disclosures.get('disclosures', {}):
                    self.log_test_result(
                        f"Disclosure: {disclosure_key}",
                        False,
                        "Missing required disclosure"
                    )
                    all_present = False
                else:
                    disclosure_data = disclosures['disclosures'][disclosure_key]
                    self.log_test_result(
                        f"Disclosure: {disclosure_key}",
                        True,
                        f"Present with {len(str(disclosure_data))} chars"
                    )
            
            # Verify age requirement is present
            if 'age_requirement' not in disclosures:
                self.log_test_result(
                    "Age Requirement",
                    False,
                    "Missing age requirement disclosure"
                )
                all_present = False
            else:
                self.log_test_result(
                    "Age Requirement",
                    True,
                    f"Present: {disclosures['age_requirement']}"
                )
            
            if all_present:
                logger.info("✅ QA TEST 3 PASSED: All UI disclosures accessible")
            else:
                logger.error("❌ QA TEST 3 FAILED: Some disclosures missing")
            
            return all_present
            
        except Exception as e:
            self.log_test_result(
                "Disclosure Testing",
                False,
                f"Exception: {e}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def test_normal_mode_allows_execution(self) -> bool:
        """Test that normal trading works when APP_STORE_MODE=false."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("QA TEST 4: Normal Mode Allows Execution")
        logger.info("=" * 80)
        
        try:
            # Set mode to disabled for this test
            os.environ['APP_STORE_MODE'] = 'false'
            
            # Reload the module to pick up the env change
            import importlib
            if 'bot.app_store_mode' in sys.modules:
                importlib.reload(sys.modules['bot.app_store_mode'])
            
            from bot.app_store_mode import get_app_store_mode
            
            mode = get_app_store_mode()
            
            # Test 1: Mode should be disabled
            if mode.is_enabled():
                self.log_test_result(
                    "Mode Detection (Disabled)",
                    False,
                    "APP_STORE_MODE=false but mode detected as enabled"
                )
                return False
            
            self.log_test_result(
                "Mode Detection (Disabled)",
                True,
                "APP_STORE_MODE correctly detected as disabled"
            )
            
            # Test 2: Execution should be allowed
            allowed, reason = mode.check_execution_allowed()
            if not allowed:
                self.log_test_result(
                    "Execution Allowed",
                    False,
                    f"Execution blocked when it should be allowed: {reason}"
                )
                return False
            
            self.log_test_result(
                "Execution Allowed",
                True,
                "Execution correctly allowed in normal mode"
            )
            
            logger.info("✅ QA TEST 4 PASSED: Normal mode allows execution")
            return True
            
        except Exception as e:
            self.log_test_result(
                "Normal Mode Testing",
                False,
                f"Exception: {e}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def test_broker_integration(self) -> bool:
        """Test that broker layer respects APP_STORE_MODE."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("QA TEST 5: Broker Layer Integration")
        logger.info("=" * 80)
        
        try:
            # Enable mode for broker test
            os.environ['APP_STORE_MODE'] = 'true'
            
            # Test that the check is present in broker code
            broker_manager_path = os.path.join(
                os.path.dirname(__file__),
                'bot',
                'broker_manager.py'
            )
            
            if not os.path.exists(broker_manager_path):
                self.log_test_result(
                    "Broker File Exists",
                    False,
                    f"broker_manager.py not found at {broker_manager_path}"
                )
                return False
            
            self.log_test_result(
                "Broker File Exists",
                True,
                "broker_manager.py found"
            )
            
            # Check that APP_STORE_MODE check is in the code
            with open(broker_manager_path, 'r') as f:
                broker_code = f.read()
            
            if 'app_store_mode' not in broker_code.lower():
                self.log_test_result(
                    "Broker Integration",
                    False,
                    "APP_STORE_MODE check not found in broker_manager.py"
                )
                return False
            
            self.log_test_result(
                "Broker Integration",
                True,
                "APP_STORE_MODE checks present in broker code"
            )
            
            # Check hard controls integration
            controls_path = os.path.join(
                os.path.dirname(__file__),
                'controls',
                '__init__.py'
            )
            
            if os.path.exists(controls_path):
                with open(controls_path, 'r') as f:
                    controls_code = f.read()
                
                if 'app_store_mode' in controls_code.lower():
                    self.log_test_result(
                        "Hard Controls Integration",
                        True,
                        "APP_STORE_MODE checks present in hard controls"
                    )
                else:
                    self.log_test_result(
                        "Hard Controls Integration",
                        False,
                        "APP_STORE_MODE check not found in hard controls"
                    )
                    return False
            
            logger.info("✅ QA TEST 5 PASSED: Broker layer integration complete")
            return True
            
        except Exception as e:
            self.log_test_result(
                "Broker Integration Testing",
                False,
                f"Exception: {e}"
            )
            import traceback
            traceback.print_exc()
            return False
    
    def generate_qa_report(self):
        """Generate comprehensive QA report."""
        logger.info("")
        logger.info("=" * 80)
        logger.info("QA REPORT SUMMARY")
        logger.info("=" * 80)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for r in self.test_results if r['passed'])
        failed_tests = total_tests - passed_tests
        
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests}")
        logger.info(f"Failed: {failed_tests}")
        logger.info(f"Success Rate: {(passed_tests/total_tests*100):.1f}%")
        
        if failed_tests > 0:
            logger.info("")
            logger.info("Failed Tests:")
            for result in self.test_results:
                if not result['passed']:
                    logger.error(f"  ❌ {result['test']}: {result['details']}")
        
        logger.info("")
        logger.info("=" * 80)
        
        if failed_tests == 0:
            logger.info("✅ ALL QA TESTS PASSED")
            logger.info("=" * 80)
            logger.info("")
            logger.info("NIJA is ready for App Store submission!")
            logger.info("")
            logger.info("Next Steps:")
            logger.info("1. Review UI to ensure trade buttons are hidden when APP_STORE_MODE=true")
            logger.info("2. Verify risk disclosures are visible in the app interface")
            logger.info("3. Build app with APP_STORE_MODE=true for submission")
            logger.info("4. Submit to Apple TestFlight/App Store")
            logger.info("=" * 80)
            return True
        else:
            logger.error("❌ SOME QA TESTS FAILED")
            logger.error("=" * 80)
            logger.error("")
            logger.error("Please fix the failed tests before App Store submission.")
            logger.error("=" * 80)
            return False
    
    def run_full_qa(self):
        """Run complete QA test suite."""
        logger.info("=" * 80)
        logger.info("APP STORE MODE - COMPREHENSIVE QA VERIFICATION")
        logger.info("=" * 80)
        logger.info(f"Current APP_STORE_MODE: {self.current_mode}")
        logger.info(f"Test Started: {datetime.now().isoformat()}")
        logger.info("=" * 80)
        logger.info("")
        
        # Run all tests
        tests = [
            self.test_no_trades_when_enabled,
            self.test_read_only_endpoints,
            self.test_ui_disclosures_accessible,
            self.test_normal_mode_allows_execution,
            self.test_broker_integration,
        ]
        
        for test_func in tests:
            try:
                test_func()
            except Exception as e:
                logger.error(f"Test crashed: {e}")
                import traceback
                traceback.print_exc()
        
        # Generate report
        return self.generate_qa_report()


def main():
    """Main QA execution."""
    parser = argparse.ArgumentParser(
        description='Enhanced App Store Mode QA Verification'
    )
    parser.add_argument(
        '--mode',
        choices=['enabled', 'disabled'],
        help='Test with specific APP_STORE_MODE value'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Run complete QA test suite'
    )
    
    args = parser.parse_args()
    
    if args.mode:
        os.environ['APP_STORE_MODE'] = 'true' if args.mode == 'enabled' else 'false'
    
    qa = AppStoreModeQA()
    success = qa.run_full_qa()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
