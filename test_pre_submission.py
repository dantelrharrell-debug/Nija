#!/usr/bin/env python3
"""
NIJA Pre-Submission Test Suite
================================

This script runs automated tests to verify all critical components
are ready for app store submission.

Run this script 24 hours before submission to catch any issues.

Usage:
    python test_pre_submission.py
    python test_pre_submission.py --verbose
    python test_pre_submission.py --fix-issues  # Attempt to auto-fix minor issues
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict

# Color codes for output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


class PreSubmissionChecker:
    """Automated checker for app store submission readiness."""
    
    def __init__(self, verbose=False, fix_issues=False):
        self.verbose = verbose
        self.fix_issues = fix_issues
        self.tests_passed = 0
        self.tests_failed = 0
        self.warnings = 0
        self.project_root = Path('/home/runner/work/Nija/Nija')
        self.issues = []
        
    def print_header(self, text):
        """Print section header."""
        print(f"\n{BLUE}{'=' * 70}{RESET}")
        print(f"{BLUE}{text}{RESET}")
        print(f"{BLUE}{'=' * 70}{RESET}\n")
    
    def print_success(self, text):
        """Print success message."""
        print(f"{GREEN}✅ {text}{RESET}")
        self.tests_passed += 1
    
    def print_failure(self, text, fix_hint=None):
        """Print failure message."""
        print(f"{RED}❌ {text}{RESET}")
        if fix_hint:
            print(f"{YELLOW}   Fix: {fix_hint}{RESET}")
        self.tests_failed += 1
        self.issues.append(text)
    
    def print_warning(self, text):
        """Print warning message."""
        print(f"{YELLOW}⚠️  {text}{RESET}")
        self.warnings += 1
    
    def print_info(self, text):
        """Print info message."""
        if self.verbose:
            print(f"   {text}")
    
    def check_file_exists(self, filepath: Path, description: str) -> bool:
        """Check if a file exists."""
        if filepath.exists():
            self.print_success(f"{description} exists: {filepath.name}")
            return True
        else:
            self.print_failure(
                f"{description} missing: {filepath}",
                f"Create this file before submission"
            )
            return False
    
    def check_file_contains(self, filepath: Path, search_terms: List[str], 
                           description: str) -> bool:
        """Check if file contains required terms."""
        if not filepath.exists():
            self.print_failure(f"Cannot check {filepath.name} - file missing")
            return False
        
        try:
            content = filepath.read_text()
            missing_terms = [term for term in search_terms if term not in content]
            
            if not missing_terms:
                self.print_success(f"{description} contains required content")
                return True
            else:
                self.print_failure(
                    f"{description} missing terms: {', '.join(missing_terms)}",
                    f"Add these terms to {filepath.name}"
                )
                return False
        except Exception as e:
            self.print_failure(f"Error reading {filepath.name}: {e}")
            return False
    
    def check_no_prohibited_terms(self, filepath: Path, prohibited_terms: List[str],
                                  description: str) -> bool:
        """Check that file doesn't contain prohibited terms."""
        if not filepath.exists():
            return True  # Skip if file doesn't exist
        
        try:
            content = filepath.read_text().lower()
            found_terms = [term for term in prohibited_terms if term.lower() in content]
            
            if not found_terms:
                self.print_success(f"{description} has no prohibited terms")
                return True
            else:
                self.print_failure(
                    f"{description} contains prohibited: {', '.join(found_terms)}",
                    f"Remove these terms from {filepath.name} - they will cause rejection"
                )
                return False
        except Exception as e:
            self.print_warning(f"Could not check {filepath.name}: {e}")
            return True
    
    def check_simulation_results(self) -> bool:
        """Check if simulation results exist and are valid."""
        results_file = self.project_root / 'results' / 'demo_backtest.json'
        
        if not results_file.exists():
            self.print_failure(
                "Simulation results missing",
                "Run: python bot/unified_backtest_engine.py"
            )
            return False
        
        try:
            with open(results_file) as f:
                data = json.load(f)
            
            required_keys = ['summary', 'trades']
            if all(key in data for key in required_keys):
                self.print_success(f"Simulation results valid ({len(data.get('trades', []))} trades)")
                return True
            else:
                self.print_failure("Simulation results incomplete")
                return False
        except Exception as e:
            self.print_failure(f"Simulation results corrupted: {e}")
            return False
    
    def run_all_tests(self):
        """Run all pre-submission tests."""
        
        # Test 1: Critical Files
        self.print_header("TEST 1: CRITICAL FILES")
        
        critical_files = [
            (self.project_root / 'frontend/static/js/onboarding.js', 'Onboarding JavaScript'),
            (self.project_root / 'frontend/static/css/onboarding.css', 'Onboarding CSS'),
            (self.project_root / 'bot/financial_disclaimers.py', 'Financial Disclaimers'),
            (self.project_root / 'api_server.py', 'API Server'),
            (self.project_root / 'mobile_api.py', 'Mobile API'),
        ]
        
        for filepath, description in critical_files:
            self.check_file_exists(filepath, description)
        
        # Test 2: Risk Disclaimers Content
        self.print_header("TEST 2: RISK DISCLAIMERS PRESENT")
        
        required_warnings = [
            "YOU CAN LOSE MONEY",
            "substantial risk of loss",
            "NO GUARANTEES",
            "NOT investment advice",
            "solely responsible"
        ]
        
        onboarding_js = self.project_root / 'frontend/static/js/onboarding.js'
        self.check_file_contains(onboarding_js, required_warnings, 'Onboarding disclaimers')
        
        disclaimers_py = self.project_root / 'bot/financial_disclaimers.py'
        self.check_file_contains(disclaimers_py, required_warnings, 'Python disclaimers')
        
        # Test 3: Prohibited Language
        self.print_header("TEST 3: NO PROHIBITED LANGUAGE")
        
        prohibited_terms = [
            "guaranteed profit",
            "guarantee profit",
            "always profitable",
            "never lose",
            "risk-free",
            "100% win rate"
        ]
        
        files_to_check = [
            (self.project_root / 'README.md', 'README'),
            (onboarding_js, 'Onboarding'),
            (self.project_root / 'frontend/static/js/app.js', 'Main App JS'),
        ]
        
        for filepath, description in files_to_check:
            self.check_no_prohibited_terms(filepath, prohibited_terms, description)
        
        # Test 4: API Endpoints
        self.print_header("TEST 4: SIMULATION API ENDPOINTS")
        
        api_endpoints = [
            '/api/simulation/results',
            '/api/simulation/status',
            '/api/mobile/simulation/dashboard'
        ]
        
        api_server = self.project_root / 'api_server.py'
        mobile_api = self.project_root / 'mobile_api.py'
        
        for endpoint in api_endpoints[:2]:
            self.check_file_contains(
                api_server, 
                [endpoint],
                f"API endpoint {endpoint}"
            )
        
        self.check_file_contains(
            mobile_api,
            [api_endpoints[2]],
            f"Mobile API endpoint {api_endpoints[2]}"
        )
        
        # Test 5: Simulation Results
        self.print_header("TEST 5: SIMULATION RESULTS")
        self.check_simulation_results()
        
        # Test 6: Documentation
        self.print_header("TEST 6: SUBMISSION DOCUMENTATION")
        
        docs = [
            (self.project_root / 'GOOGLE_PLAY_SUBMISSION_CHECKLIST.md', 'Google Play Checklist'),
            (self.project_root / 'APPLE_SUBMISSION_GREEN_LIGHT_CHECKLIST.md', 'Apple Checklist'),
            (self.project_root / 'NIJA_APP_STORE_LAUNCH_READINESS_CHECKLIST.md', 'Launch Readiness'),
            (self.project_root / 'FINAL_PRE_SUBMISSION_CHECKLIST.md', 'Final Checklist'),
        ]
        
        for filepath, description in docs:
            self.check_file_exists(filepath, description)
        
        # Test 7: Environment Configuration
        self.print_header("TEST 7: ENVIRONMENT CONFIGURATION")
        
        env_example = self.project_root / '.env.example'
        if env_example.exists():
            self.print_success("Environment example exists")
            self.print_info("Make sure .env is configured for production")
        else:
            self.print_warning("No .env.example found")
        
        # Test 8: No Secrets in Code
        self.print_header("TEST 8: NO HARDCODED SECRETS")
        
        secret_patterns = ['sk_live_', 'pk_live_', 'AIza']
        js_files = list((self.project_root / 'frontend/static/js').glob('*.js'))
        
        secrets_found = False
        for js_file in js_files:
            if self.check_no_prohibited_terms(js_file, secret_patterns, f"{js_file.name}"):
                pass
            else:
                secrets_found = True
        
        if not secrets_found:
            self.print_success("No hardcoded secrets detected in JS files")
        
        # Test 9: Mobile App Structure
        self.print_header("TEST 9: MOBILE APP STRUCTURE")
        
        mobile_dirs = [
            (self.project_root / 'mobile', 'Mobile directory'),
            (self.project_root / 'mobile/ios', 'iOS directory'),
            (self.project_root / 'mobile/android', 'Android directory'),
        ]
        
        for dirpath, description in mobile_dirs:
            if dirpath.exists():
                self.print_success(f"{description} exists")
            else:
                self.print_warning(f"{description} not found - mobile app may not be configured")
        
        # Test 10: Legal Documents
        self.print_header("TEST 10: LEGAL DOCUMENTS")
        
        legal_docs = [
            (self.project_root / 'mobile/PRIVACY_POLICY.md', 'Privacy Policy'),
            (self.project_root / 'mobile/TERMS_OF_SERVICE.md', 'Terms of Service'),
            (self.project_root / 'RISK_DISCLOSURE.md', 'Risk Disclosure'),
        ]
        
        for filepath, description in legal_docs:
            if self.check_file_exists(filepath, description):
                self.print_info(f"Remember to publish {description} at a public URL")
    
    def print_summary(self):
        """Print test summary."""
        self.print_header("TEST SUMMARY")
        
        total_tests = self.tests_passed + self.tests_failed
        pass_rate = (self.tests_passed / total_tests * 100) if total_tests > 0 else 0
        
        print(f"Total Tests: {total_tests}")
        print(f"{GREEN}Passed: {self.tests_passed}{RESET}")
        print(f"{RED}Failed: {self.tests_failed}{RESET}")
        print(f"{YELLOW}Warnings: {self.warnings}{RESET}")
        print(f"Pass Rate: {pass_rate:.1f}%\n")
        
        if self.tests_failed == 0:
            print(f"{GREEN}{'=' * 70}{RESET}")
            print(f"{GREEN}🎉 ALL CRITICAL TESTS PASSED! Ready for submission.{RESET}")
            print(f"{GREEN}{'=' * 70}{RESET}\n")
            print("Next steps:")
            print("1. Review FINAL_PRE_SUBMISSION_CHECKLIST.md")
            print("2. Test on actual devices (iPhone + Android)")
            print("3. Create screenshots for app stores")
            print("4. Upload builds to TestFlight and Play Console")
            return 0
        else:
            print(f"{RED}{'=' * 70}{RESET}")
            print(f"{RED}⚠️  {self.tests_failed} CRITICAL ISSUES FOUND{RESET}")
            print(f"{RED}{'=' * 70}{RESET}\n")
            print("Issues to fix before submission:")
            for i, issue in enumerate(self.issues, 1):
                print(f"{i}. {issue}")
            print(f"\n{YELLOW}DO NOT SUBMIT until all issues are resolved.{RESET}")
            return 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='NIJA Pre-Submission Test Suite')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--fix-issues', '-f', action='store_true', help='Attempt to auto-fix issues')
    args = parser.parse_args()
    
    print(f"{BLUE}╔{'═' * 68}╗{RESET}")
    print(f"{BLUE}║{' ' * 15}NIJA PRE-SUBMISSION TEST SUITE{' ' * 22}║{RESET}")
    print(f"{BLUE}╚{'═' * 68}╝{RESET}")
    print(f"\nThis test suite checks if NIJA is ready for app store submission.")
    print(f"Run this 24 hours before submitting to catch critical issues.\n")
    
    checker = PreSubmissionChecker(verbose=args.verbose, fix_issues=args.fix_issues)
    checker.run_all_tests()
    return checker.print_summary()


if __name__ == '__main__':
    sys.exit(main())
