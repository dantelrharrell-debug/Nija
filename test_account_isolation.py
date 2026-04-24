"""
Integration Tests for Account Isolation Architecture
=====================================================

Tests that verify one account failure can NEVER affect another account.

Key Test Scenarios:
1. Single account failure doesn't affect other accounts
2. Circuit breaker activates and recovers properly
3. Cascading failures are prevented
4. Resource cleanup happens on failure
5. Isolation metrics are tracked correctly

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import unittest
import time
import threading
from typing import Dict
from unittest.mock import Mock, MagicMock, patch

# Import isolation manager
try:
    from bot.account_isolation_manager import (
        AccountIsolationManager,
        AccountHealthStatus,
        FailureType,
        CircuitBreakerConfig,
        get_isolation_manager
    )
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from account_isolation_manager import (
        AccountIsolationManager,
        AccountHealthStatus,
        FailureType,
        CircuitBreakerConfig,
        get_isolation_manager
    )


class TestAccountIsolation(unittest.TestCase):
    """Test cases for account isolation manager"""
    
    def setUp(self):
        """Set up test environment"""
        # Create a fresh isolation manager for each test
        self.config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            timeout_seconds=5,  # Short timeout for tests
            half_open_max_calls=1
        )
        self.manager = AccountIsolationManager(self.config)
    
    def test_account_registration(self):
        """Test that accounts can be registered"""
        result = self.manager.register_account('user', 'user1', 'KRAKEN')
        self.assertTrue(result)
        
        # Verify account is registered
        status, metrics = self.manager.get_account_status('user', 'user1', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.HEALTHY)
    
    def test_isolated_failures(self):
        """
        Test that failure in one account doesn't affect another account.
        
        This is the CORE isolation guarantee.
        """
        # Register two accounts
        self.manager.register_account('user', 'user1', 'KRAKEN')
        self.manager.register_account('user', 'user2', 'KRAKEN')
        
        # Cause failures in user1
        for i in range(5):
            self.manager.record_failure(
                'user', 'user1', 'KRAKEN',
                Exception(f"Test failure {i}"),
                FailureType.API_ERROR
            )
        
        # Check user1 is quarantined
        status1, metrics1 = self.manager.get_account_status('user', 'user1', 'KRAKEN')
        self.assertEqual(status1, AccountHealthStatus.QUARANTINED)
        
        # Check user2 is still healthy (isolation guarantee)
        status2, metrics2 = self.manager.get_account_status('user', 'user2', 'KRAKEN')
        self.assertEqual(status2, AccountHealthStatus.HEALTHY)
        
        # Verify user2 can still execute operations
        can_execute, reason = self.manager.can_execute_operation('user', 'user2', 'KRAKEN')
        self.assertTrue(can_execute)
    
    def test_circuit_breaker_opens(self):
        """Test that circuit breaker opens after failure threshold"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Record failures up to threshold (3)
        for i in range(3):
            self.manager.record_failure(
                'user', 'testuser', 'KRAKEN',
                Exception(f"Test failure {i}"),
                FailureType.API_ERROR
            )
        
        # Circuit should be open
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.QUARANTINED)
        self.assertTrue(metrics['circuit_open'])
        
        # Operations should be blocked
        can_execute, reason = self.manager.can_execute_operation('user', 'testuser', 'KRAKEN')
        self.assertFalse(can_execute)
    
    def test_circuit_breaker_recovers(self):
        """Test that circuit breaker can recover after timeout"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Cause circuit to open
        for i in range(3):
            self.manager.record_failure(
                'user', 'testuser', 'KRAKEN',
                Exception(f"Test failure {i}"),
                FailureType.API_ERROR
            )
        
        # Verify circuit is open
        can_execute, _ = self.manager.can_execute_operation('user', 'testuser', 'KRAKEN')
        self.assertFalse(can_execute)
        
        # Wait for timeout (5 seconds in test config)
        time.sleep(6)
        
        # Circuit should enter half-open state
        can_execute, reason = self.manager.can_execute_operation('user', 'testuser', 'KRAKEN')
        self.assertTrue(can_execute)
        self.assertEqual(reason, "Recovery attempt")
        
        # Record successes to close circuit
        self.manager.record_success('user', 'testuser', 'KRAKEN')
        self.manager.record_success('user', 'testuser', 'KRAKEN')
        
        # Circuit should be closed
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.HEALTHY)
        self.assertFalse(metrics['circuit_open'])
    
    def test_degraded_state(self):
        """Test that account enters degraded state with moderate failures"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Record failures below threshold (1-2 failures)
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Test failure"),
            FailureType.API_ERROR
        )
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Test failure 2"),
            FailureType.API_ERROR
        )
        
        # Account should be degraded but operational
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.DEGRADED)
        
        # Operations should still be allowed
        can_execute, _ = self.manager.can_execute_operation('user', 'testuser', 'KRAKEN')
        self.assertTrue(can_execute)
    
    def test_success_tracking(self):
        """Test that successes are tracked and restore health"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Degrade account
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Test failure"),
            FailureType.API_ERROR
        )
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Test failure 2"),
            FailureType.API_ERROR
        )
        
        status, _ = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.DEGRADED)
        
        # Record successes to restore health
        self.manager.record_success('user', 'testuser', 'KRAKEN')
        self.manager.record_success('user', 'testuser', 'KRAKEN')
        
        # Account should be healthy again
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.HEALTHY)
        self.assertEqual(metrics['consecutive_successes'], 2)
        self.assertEqual(metrics['consecutive_failures'], 0)
    
    def test_failure_type_tracking(self):
        """Test that different failure types are tracked separately"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Record different types of failures
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("API error"),
            FailureType.API_ERROR
        )
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Network error"),
            FailureType.NETWORK_ERROR
        )
        self.manager.record_failure(
            'user', 'testuser', 'KRAKEN',
            Exception("Rate limit"),
            FailureType.RATE_LIMIT_ERROR
        )
        
        # Check failure breakdown
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(metrics['failure_breakdown']['api_error'], 1)
        self.assertEqual(metrics['failure_breakdown']['network_error'], 1)
        self.assertEqual(metrics['failure_breakdown']['rate_limit_error'], 1)
        self.assertEqual(metrics['total_failures'], 3)
    
    def test_thread_safety(self):
        """Test that isolation manager is thread-safe"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        errors = []
        
        def worker(worker_id):
            try:
                for i in range(10):
                    if i % 2 == 0:
                        self.manager.record_success('user', 'testuser', 'KRAKEN')
                    else:
                        self.manager.record_failure(
                            'user', 'testuser', 'KRAKEN',
                            Exception(f"Worker {worker_id} failure {i}"),
                            FailureType.API_ERROR
                        )
                    # Small delay to increase chance of race conditions
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)
        
        # Start multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have no errors (thread-safe)
        self.assertEqual(len(errors), 0)
        
        # Verify account still has valid state
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertIsNotNone(status)
        self.assertGreater(metrics['total_failures'], 0)
    
    def test_isolation_report(self):
        """Test that isolation report provides comprehensive metrics"""
        # Register multiple accounts
        self.manager.register_account('platform', 'platform', 'KRAKEN')
        self.manager.register_account('user', 'user1', 'KRAKEN')
        self.manager.register_account('user', 'user2', 'COINBASE')
        
        # Cause some failures
        for i in range(3):
            self.manager.record_failure(
                'user', 'user1', 'KRAKEN',
                Exception(f"Failure {i}"),
                FailureType.API_ERROR
            )
        
        # Get report
        report = self.manager.get_isolation_report()
        
        # Verify report structure
        self.assertEqual(report['total_accounts'], 3)
        self.assertEqual(report['healthy_accounts'], 2)
        self.assertEqual(report['quarantined_accounts'], 1)
        self.assertEqual(report['isolation_guarantee'], 'ACTIVE')
        self.assertEqual(report['cross_account_errors_detected'], 0)
    
    def test_manual_reset(self):
        """Test that accounts can be manually reset"""
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        
        # Quarantine account
        for i in range(3):
            self.manager.record_failure(
                'user', 'testuser', 'KRAKEN',
                Exception(f"Failure {i}"),
                FailureType.API_ERROR
            )
        
        status, _ = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.QUARANTINED)
        
        # Reset account
        result = self.manager.reset_account('user', 'testuser', 'KRAKEN')
        self.assertTrue(result)
        
        # Verify account is healthy
        status, metrics = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status, AccountHealthStatus.HEALTHY)
        self.assertEqual(metrics['consecutive_failures'], 0)
        self.assertFalse(metrics['circuit_open'])
    
    def test_multiple_brokers_per_user(self):
        """Test that one broker failure doesn't affect other brokers for same user"""
        # Register same user on different brokers
        self.manager.register_account('user', 'testuser', 'KRAKEN')
        self.manager.register_account('user', 'testuser', 'COINBASE')
        
        # Fail KRAKEN
        for i in range(3):
            self.manager.record_failure(
                'user', 'testuser', 'KRAKEN',
                Exception(f"Failure {i}"),
                FailureType.API_ERROR
            )
        
        # Check KRAKEN is quarantined
        status_kraken, _ = self.manager.get_account_status('user', 'testuser', 'KRAKEN')
        self.assertEqual(status_kraken, AccountHealthStatus.QUARANTINED)
        
        # Check COINBASE is still healthy
        status_coinbase, _ = self.manager.get_account_status('user', 'testuser', 'COINBASE')
        self.assertEqual(status_coinbase, AccountHealthStatus.HEALTHY)
        
        # Verify COINBASE can still operate
        can_execute, _ = self.manager.can_execute_operation('user', 'testuser', 'COINBASE')
        self.assertTrue(can_execute)


def run_tests():
    """Run all tests and report results"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestAccountIsolation)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("ACCOUNT ISOLATION TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED - ISOLATION GUARANTEE VERIFIED")
    else:
        print("\n❌ SOME TESTS FAILED - ISOLATION MAY BE COMPROMISED")
    
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
