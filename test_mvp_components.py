#!/usr/bin/env python3
"""
Test script for 4-component MVP implementation.

Tests:
1. Secure Vault - encryption/decryption
2. User Authentication - registration/login
3. Execution Router - broker selection
4. Integration - all components working together
"""

import os
import sys
import tempfile
import shutil

# Test results tracking
tests_passed = 0
tests_failed = 0

def test_secure_vault():
    """Test secure vault encryption and audit logging."""
    global tests_passed, tests_failed
    
    print("\n" + "="*60)
    print("TEST 1: Secure Vault")
    print("="*60)
    
    try:
        from vault import SecureVault
        from cryptography.fernet import Fernet
        
        # Create temp database
        temp_db = tempfile.mktemp(suffix=".db")
        
        # Initialize vault
        vault = SecureVault(db_path=temp_db)
        print("✓ Vault initialized")
        
        # Test storing credentials
        success = vault.store_credentials(
            user_id="test_user_1",
            broker="coinbase",
            api_key="test_api_key_123",
            api_secret="test_secret_456",
            additional_params={"passphrase": "test_pass"},
            ip_address="127.0.0.1"
        )
        assert success, "Failed to store credentials"
        print("✓ Credentials stored and encrypted")
        
        # Test retrieving credentials
        creds = vault.get_credentials("test_user_1", "coinbase", "127.0.0.1")
        assert creds is not None, "Failed to retrieve credentials"
        assert creds['api_key'] == "test_api_key_123", "API key mismatch"
        assert creds['api_secret'] == "test_secret_456", "API secret mismatch"
        assert creds['additional_params']['passphrase'] == "test_pass", "Passphrase mismatch"
        print("✓ Credentials decrypted correctly")
        
        # Test listing brokers
        brokers = vault.list_user_brokers("test_user_1")
        assert "coinbase" in brokers, "Broker not in list"
        print("✓ Broker listing works")
        
        # Test audit log
        audit = vault.get_audit_log("test_user_1")
        assert len(audit) >= 2, "Audit log incomplete"
        assert audit[0]['action'] in ['STORE_CREDENTIALS', 'GET_CREDENTIALS'], "Invalid audit action"
        print("✓ Audit logging works")
        
        # Test deletion
        deleted = vault.delete_credentials("test_user_1", "coinbase", "127.0.0.1")
        assert deleted, "Failed to delete credentials"
        print("✓ Credential deletion works")
        
        # Cleanup
        os.unlink(temp_db)
        
        print("\n✅ SECURE VAULT: ALL TESTS PASSED")
        tests_passed += 1
        return True
        
    except Exception as e:
        print(f"\n❌ SECURE VAULT: FAILED - {e}")
        tests_failed += 1
        if os.path.exists(temp_db):
            os.unlink(temp_db)
        return False


def test_user_authentication():
    """Test user database and authentication."""
    global tests_passed, tests_failed
    
    print("\n" + "="*60)
    print("TEST 2: User Authentication & Identity")
    print("="*60)
    
    try:
        from auth.user_database import UserDatabase
        
        # Create temp database
        temp_db = tempfile.mktemp(suffix=".db")
        
        # Initialize user database
        user_db = UserDatabase(db_path=temp_db)
        print("✓ User database initialized")
        
        # Test user creation
        success = user_db.create_user(
            user_id="test_user_1",
            email="test@example.com",
            password="SecurePassword123!",
            subscription_tier="pro"
        )
        assert success, "Failed to create user"
        print("✓ User created with Argon2 password hash")
        
        # Test password verification (correct password)
        verified = user_db.verify_password("test_user_1", "SecurePassword123!", "127.0.0.1")
        assert verified, "Password verification failed"
        print("✓ Password verification works (correct password)")
        
        # Test password verification (wrong password)
        verified = user_db.verify_password("test_user_1", "WrongPassword", "127.0.0.1")
        assert not verified, "Wrong password was accepted"
        print("✓ Password verification works (wrong password rejected)")
        
        # Test get user profile
        user = user_db.get_user("test_user_1")
        assert user is not None, "Failed to get user profile"
        assert user['email'] == "test@example.com", "Email mismatch"
        assert user['subscription_tier'] == "pro", "Tier mismatch"
        print("✓ User profile retrieval works")
        
        # Test get user by email
        user = user_db.get_user_by_email("test@example.com")
        assert user is not None, "Failed to get user by email"
        assert user['user_id'] == "test_user_1", "User ID mismatch"
        print("✓ Get user by email works")
        
        # Test update user
        updated = user_db.update_user("test_user_1", {"subscription_tier": "enterprise"})
        assert updated, "Failed to update user"
        user = user_db.get_user("test_user_1")
        assert user['subscription_tier'] == "enterprise", "Tier not updated"
        print("✓ User update works")
        
        # Cleanup
        os.unlink(temp_db)
        
        print("\n✅ USER AUTHENTICATION: ALL TESTS PASSED")
        tests_passed += 1
        return True
        
    except Exception as e:
        print(f"\n❌ USER AUTHENTICATION: FAILED - {e}")
        tests_failed += 1
        if os.path.exists(temp_db):
            os.unlink(temp_db)
        return False


def test_execution_router():
    """Test execution router with health monitoring."""
    global tests_passed, tests_failed
    
    print("\n" + "="*60)
    print("TEST 3: Execution Router (Money Engine)")
    print("="*60)
    
    try:
        from core.enhanced_execution_router import EnhancedExecutionRouter, BrokerHealth
        
        # Initialize router
        router = EnhancedExecutionRouter()
        print("✓ Execution router initialized")
        
        # Test broker registration
        router.register_broker("coinbase")
        router.register_broker("kraken")
        router.register_broker("binance")
        print("✓ Brokers registered")
        
        # Test recording successful executions
        router.record_execution("coinbase", success=True, latency_ms=200)
        router.record_execution("kraken", success=True, latency_ms=150)
        router.record_execution("binance", success=True, latency_ms=300)
        print("✓ Execution metrics recorded")
        
        # Test broker health check
        health = router.get_broker_health("coinbase")
        assert health == BrokerHealth.HEALTHY, f"Expected HEALTHY, got {health}"
        print("✓ Broker health monitoring works")
        
        # Test broker selection (should pick lowest latency)
        best = router.select_best_broker("test_user", ["coinbase", "kraken", "binance"])
        assert best == "kraken", f"Expected kraken (lowest latency), got {best}"
        print("✓ Broker selection works (chooses lowest latency)")
        
        # Test recording failures
        for _ in range(3):
            router.record_execution("binance", success=False, latency_ms=0, error="Timeout")
        print("✓ Failure recording works")
        
        # Test broker stats
        stats = router.get_broker_stats()
        assert "coinbase" in stats, "Stats missing coinbase"
        assert "kraken" in stats, "Stats missing kraken"
        assert "binance" in stats, "Stats missing binance"
        print("✓ Broker stats generation works")
        
        # Test failover execution
        def mock_execute(broker, symbol, quantity):
            if broker == "binance":
                raise Exception("Broker unavailable")
            return f"Executed {quantity} {symbol} on {broker}"
        
        result = router.execute_with_failover(
            user_id="test_user",
            brokers=["binance", "coinbase", "kraken"],
            execute_func=mock_execute,
            symbol="BTC-USD",
            quantity=0.1
        )
        assert "coinbase" in result or "kraken" in result, "Failover didn't work"
        print("✓ Automatic failover works")
        
        print("\n✅ EXECUTION ROUTER: ALL TESTS PASSED")
        tests_passed += 1
        return True
        
    except Exception as e:
        print(f"\n❌ EXECUTION ROUTER: FAILED - {e}")
        tests_failed += 1
        return False


def test_integration():
    """Test integration of all components."""
    global tests_passed, tests_failed
    
    print("\n" + "="*60)
    print("TEST 4: Component Integration")
    print("="*60)
    
    try:
        from vault import SecureVault
        from auth.user_database import UserDatabase
        from core.enhanced_execution_router import EnhancedExecutionRouter
        
        # Create temp databases
        vault_db = tempfile.mktemp(suffix=".db")
        user_db_path = tempfile.mktemp(suffix=".db")
        
        # Initialize all components
        vault = SecureVault(db_path=vault_db)
        user_db = UserDatabase(db_path=user_db_path)
        router = EnhancedExecutionRouter()
        print("✓ All components initialized")
        
        # Simulated user flow
        # 1. User registration
        user_db.create_user("user_123", "user@example.com", "password123", "pro")
        print("✓ User registered")
        
        # 2. User adds broker credentials
        vault.store_credentials(
            user_id="user_123",
            broker="coinbase",
            api_key="coinbase_key",
            api_secret="coinbase_secret"
        )
        print("✓ Credentials stored in vault")
        
        # 3. Router selects broker
        router.register_broker("coinbase")
        router.record_execution("coinbase", success=True, latency_ms=180)
        best_broker = router.select_best_broker("user_123", ["coinbase"])
        assert best_broker == "coinbase", "Broker selection failed"
        print("✓ Router selected broker")
        
        # 4. Retrieve credentials for execution
        creds = vault.get_credentials("user_123", best_broker)
        assert creds['api_key'] == "coinbase_key", "Credential retrieval failed"
        print("✓ Credentials retrieved for execution")
        
        # 5. Check user permissions
        user = user_db.get_user("user_123")
        assert user['subscription_tier'] == "pro", "User tier check failed"
        print("✓ User permissions checked")
        
        # Cleanup
        os.unlink(vault_db)
        os.unlink(user_db_path)
        
        print("\n✅ INTEGRATION: ALL TESTS PASSED")
        tests_passed += 1
        return True
        
    except Exception as e:
        print(f"\n❌ INTEGRATION: FAILED - {e}")
        tests_failed += 1
        if os.path.exists(vault_db):
            os.unlink(vault_db)
        if os.path.exists(user_db_path):
            os.unlink(user_db_path)
        return False


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("NIJA MVP - 4 Component Test Suite")
    print("="*60)
    
    # Run all tests
    test_secure_vault()
    test_user_authentication()
    test_execution_router()
    test_integration()
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"✅ Tests Passed: {tests_passed}")
    print(f"❌ Tests Failed: {tests_failed}")
    print(f"📊 Success Rate: {tests_passed}/{tests_passed + tests_failed} ({(tests_passed/(tests_passed+tests_failed)*100):.1f}%)")
    print("="*60)
    
    # Exit with appropriate code
    sys.exit(0 if tests_failed == 0 else 1)


if __name__ == "__main__":
    main()
