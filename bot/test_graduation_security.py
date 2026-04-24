"""
Security tests for Paper Trading Graduation System

Tests the graduation system for path traversal vulnerabilities and other security issues.

Author: NIJA Trading Systems
Date: January 31, 2026
"""

import os
import sys
import json
import tempfile
import shutil
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bot.paper_trading_graduation import PaperTradingGraduationSystem
from bot.path_validator import sanitize_filename


class TestGraduationSecurity:
    """Test suite for graduation system security"""
    
    def __init__(self):
        self.test_dir = None
        self.passed = 0
        self.failed = 0
    
    def setup(self):
        """Create temporary test directory"""
        self.test_dir = tempfile.mkdtemp(prefix="test_graduation_")
        print(f"Created test directory: {self.test_dir}")
    
    def teardown(self):
        """Remove temporary test directory"""
        if self.test_dir and os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)
            print(f"Cleaned up test directory: {self.test_dir}")
    
    def assert_true(self, condition, message):
        """Assert that condition is true"""
        if condition:
            self.passed += 1
            print(f"  ✓ {message}")
        else:
            self.failed += 1
            print(f"  ✗ FAILED: {message}")
    
    def assert_false(self, condition, message):
        """Assert that condition is false"""
        self.assert_true(not condition, message)
    
    def test_user_id_sanitization(self):
        """Test that user_id is properly sanitized"""
        print("\n1. Testing user_id sanitization...")
        
        # Test basic path traversal
        system = PaperTradingGraduationSystem(
            user_id="../../../etc/passwd",
            data_dir=self.test_dir
        )
        
        # Verify sanitized user_id doesn't contain path traversal
        self.assert_false(
            ".." in system.user_id,
            "Path traversal characters removed from user_id"
        )
        self.assert_false(
            "/" in system.user_id,
            "Forward slashes removed from user_id"
        )
        
        # Verify file is created in correct directory
        expected_dir = Path(self.test_dir).resolve()
        actual_file = system.user_file.resolve()
        
        try:
            actual_file.relative_to(expected_dir)
            self.assert_true(True, "User file is within data directory")
        except ValueError:
            self.assert_true(False, "User file is within data directory")
    
    def test_absolute_path_attack(self):
        """Test that absolute paths are sanitized"""
        print("\n2. Testing absolute path attack prevention...")
        
        # Try Unix absolute path
        system = PaperTradingGraduationSystem(
            user_id="/etc/passwd",
            data_dir=self.test_dir
        )
        
        self.assert_false(
            system.user_id.startswith('/'),
            "Unix absolute path prevented"
        )
        
        # Try Windows absolute path
        system2 = PaperTradingGraduationSystem(
            user_id="C:\\Windows\\System32\\config",
            data_dir=self.test_dir
        )
        
        self.assert_false(
            ':' in system2.user_id,
            "Windows absolute path prevented"
        )
        
        # Verify both files are in data directory
        for sys in [system, system2]:
            try:
                sys.user_file.resolve().relative_to(Path(self.test_dir).resolve())
                self.assert_true(True, f"File for {sys.user_id} is in data directory")
            except ValueError:
                self.assert_true(False, f"File for {sys.user_id} is in data directory")
    
    def test_null_byte_injection(self):
        """Test that null bytes are removed"""
        print("\n3. Testing null byte injection prevention...")
        
        system = PaperTradingGraduationSystem(
            user_id="user\x00../../etc/passwd",
            data_dir=self.test_dir
        )
        
        self.assert_false(
            '\x00' in system.user_id,
            "Null bytes removed from user_id"
        )
        self.assert_false(
            '..' in system.user_id,
            "Path traversal after null byte removed"
        )
    
    def test_special_characters(self):
        """Test that special characters are handled"""
        print("\n4. Testing special character handling...")
        
        dangerous_chars = ['<', '>', ':', '"', '|', '?', '*']
        
        for char in dangerous_chars:
            user_id = f"user{char}test"
            system = PaperTradingGraduationSystem(
                user_id=user_id,
                data_dir=self.test_dir
            )
            
            self.assert_false(
                char in system.user_id,
                f"Dangerous character '{char}' removed"
            )
    
    def test_directory_containment(self):
        """Test that all files stay within data directory"""
        print("\n5. Testing directory containment...")
        
        attack_vectors = [
            "../../../etc/passwd",
            "../../sensitive_data",
            "/etc/shadow",
            "C:\\Windows\\System32",
            "user/../../../etc/passwd",
            "~/sensitive_data",
            ".ssh/id_rsa"
        ]
        
        base_dir = Path(self.test_dir).resolve()
        
        for vector in attack_vectors:
            try:
                system = PaperTradingGraduationSystem(
                    user_id=vector,
                    data_dir=self.test_dir
                )
                
                # Check file is within base directory
                try:
                    system.user_file.resolve().relative_to(base_dir)
                    contained = True
                except ValueError:
                    contained = False
                
                self.assert_true(
                    contained,
                    f"Attack vector '{vector}' contained in data directory"
                )
            except ValueError as e:
                # If ValueError is raised during init, that's also good (security validation)
                self.assert_true(
                    True,
                    f"Attack vector '{vector}' rejected by security validation"
                )
    
    def test_file_operations_secure(self):
        """Test that file operations are secure"""
        print("\n6. Testing secure file operations...")
        
        system = PaperTradingGraduationSystem(
            user_id="test_user",
            data_dir=self.test_dir
        )
        
        # Update metrics (triggers save)
        system.update_metrics({
            'total_trades': 50,
            'win_rate': 0.55,
            'sharpe_ratio': 1.2,
            'max_drawdown': 0.10,
            'profit_factor': 1.5,
            'avg_risk_reward': 1.8
        })
        
        # Verify file was created in correct location
        self.assert_true(
            system.user_file.exists(),
            "User file created successfully"
        )
        
        # Verify file is within data directory
        try:
            system.user_file.resolve().relative_to(Path(self.test_dir).resolve())
            self.assert_true(True, "Saved file is in data directory")
        except ValueError:
            self.assert_true(False, "Saved file is in data directory")
        
        # Verify file contents are valid JSON
        try:
            with open(system.user_file, 'r') as f:
                data = json.load(f)
            self.assert_true(
                'user_id' in data,
                "Saved file contains valid JSON"
            )
        except json.JSONDecodeError:
            self.assert_true(False, "Saved file contains valid JSON")
    
    def test_graduation_workflow(self):
        """Test complete graduation workflow"""
        print("\n7. Testing graduation workflow...")
        
        system = PaperTradingGraduationSystem(
            user_id="graduation_test",
            data_dir=self.test_dir
        )
        
        # Start in paper trading
        self.assert_true(
            system.progress.level == "paper",
            "User starts in paper trading level"
        )
        
        # Update with good metrics
        system.update_metrics({
            'total_trades': 60,
            'win_rate': 0.60,
            'sharpe_ratio': 1.5,
            'max_drawdown': 0.10,
            'profit_factor': 1.8,
            'avg_risk_reward': 2.0
        })
        
        # Should be ready for restricted live
        self.assert_true(
            system.is_ready_for_restricted_live(),
            "User ready for restricted live after meeting criteria"
        )
        
        # Graduate to restricted live
        success = system.graduate_to_restricted_live()
        self.assert_true(
            success,
            "Graduation to restricted live successful"
        )
        
        self.assert_true(
            system.progress.level == "restricted_live",
            "User level updated to restricted_live"
        )
        
        # Get limits
        limits = system.get_current_limits()
        self.assert_true(
            limits['level'] == 'restricted_live',
            "Limits reflect restricted_live level"
        )
        self.assert_true(
            limits['max_position_size'] == 500,
            "Position size limit correct for restricted live"
        )
    
    def test_limits_by_level(self):
        """Test that limits are correct for each level"""
        print("\n8. Testing trading limits by level...")
        
        system = PaperTradingGraduationSystem(
            user_id="limits_test",
            data_dir=self.test_dir
        )
        
        # Paper trading limits
        limits = system.get_current_limits()
        self.assert_true(
            limits['level'] == 'paper',
            "Paper trading level correct"
        )
        self.assert_true(
            limits['max_total_capital'] == 10000,
            "Paper trading capital limit correct"
        )
        
        # Manually set to restricted live (for testing)
        system.progress.level = "restricted_live"
        limits = system.get_current_limits()
        self.assert_true(
            limits['max_position_size'] == 500,
            "Restricted live position limit correct"
        )
        self.assert_true(
            limits['max_total_capital'] == 500,
            "Restricted live capital limit correct"
        )
        
        # Full live limits
        system.progress.level = "full_live"
        limits = system.get_current_limits()
        self.assert_true(
            limits['level'] == 'full_live',
            "Full live level correct"
        )
    
    def test_status_api_data(self):
        """Test status API data structure"""
        print("\n9. Testing status API data...")
        
        system = PaperTradingGraduationSystem(
            user_id="status_test",
            data_dir=self.test_dir
        )
        
        status = system.get_status()
        
        # Verify required fields
        required_fields = ['user_id', 'level', 'metrics', 'criteria_met', 'limits']
        for field in required_fields:
            self.assert_true(
                field in status,
                f"Status contains required field: {field}"
            )
        
        # Verify metrics structure
        metric_fields = ['total_trades', 'win_rate', 'sharpe_ratio', 
                        'max_drawdown', 'profit_factor', 'avg_risk_reward']
        for field in metric_fields:
            self.assert_true(
                field in status['metrics'],
                f"Metrics contains field: {field}"
            )
    
    def test_criteria_validation(self):
        """Test graduation criteria validation"""
        print("\n10. Testing criteria validation...")
        
        system = PaperTradingGraduationSystem(
            user_id="criteria_test",
            data_dir=self.test_dir
        )
        
        # Not ready initially
        self.assert_false(
            system.is_ready_for_restricted_live(),
            "Not ready for graduation initially"
        )
        
        # Update with insufficient metrics
        system.update_metrics({
            'total_trades': 20,  # Too few
            'win_rate': 0.45,    # Too low
            'sharpe_ratio': 0.5, # Too low
            'max_drawdown': 0.20,# Too high
            'profit_factor': 1.0,# Too low
            'avg_risk_reward': 1.0 # Too low
        })
        
        self.assert_false(
            system.is_ready_for_restricted_live(),
            "Not ready with insufficient metrics"
        )
        
        # Update with sufficient metrics
        system.update_metrics({
            'total_trades': 55,
            'win_rate': 0.55,
            'sharpe_ratio': 1.2,
            'max_drawdown': 0.12,
            'profit_factor': 1.4,
            'avg_risk_reward': 1.6
        })
        
        self.assert_true(
            system.is_ready_for_restricted_live(),
            "Ready with sufficient metrics"
        )
    
    def run_all_tests(self):
        """Run all security tests"""
        print("=" * 60)
        print("GRADUATION SYSTEM SECURITY TEST SUITE")
        print("=" * 60)
        
        self.setup()
        
        try:
            self.test_user_id_sanitization()
            self.test_absolute_path_attack()
            self.test_null_byte_injection()
            self.test_special_characters()
            self.test_directory_containment()
            self.test_file_operations_secure()
            self.test_graduation_workflow()
            self.test_limits_by_level()
            self.test_status_api_data()
            self.test_criteria_validation()
            
        finally:
            self.teardown()
        
        print("\n" + "=" * 60)
        print("TEST RESULTS")
        print("=" * 60)
        print(f"Passed: {self.passed}")
        print(f"Failed: {self.failed}")
        print(f"Total:  {self.passed + self.failed}")
        
        if self.failed == 0:
            print("\n✅ ALL TESTS PASSED - System is secure!")
            return 0
        else:
            print(f"\n❌ {self.failed} TEST(S) FAILED - Security issues detected!")
            return 1


if __name__ == '__main__':
    tester = TestGraduationSecurity()
    exit_code = tester.run_all_tests()
    sys.exit(exit_code)
