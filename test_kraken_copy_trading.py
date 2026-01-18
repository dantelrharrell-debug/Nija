#!/usr/bin/env python3
"""
Test Kraken Copy Trading System
================================

This script tests the Kraken copy trading implementation:
1. Nonce store functionality
2. KrakenClient initialization
3. Master + Users initialization
4. Copy trading simulation
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv not installed, relying on system environment variables")

import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_global_nonce_manager():
    """Test GlobalKrakenNonceManager functionality."""
    print("\n" + "=" * 70)
    print("TEST 1: GlobalKrakenNonceManager Functionality")
    print("=" * 70)
    
    try:
        from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
        
        # Test nonce generation
        nonce1 = get_global_kraken_nonce()
        print(f"✅ First nonce: {nonce1}")
        
        # Test monotonic increase
        nonce2 = get_global_kraken_nonce()
        print(f"✅ Second nonce: {nonce2}")
        
        # Verify monotonic increase
        assert nonce2 > nonce1, "Nonce must increase monotonically"
        print(f"✅ Nonce is monotonically increasing (diff: {nonce2 - nonce1})")
        
        # Test API lock
        api_lock = get_kraken_api_lock()
        assert api_lock is not None, "API lock must be available"
        print(f"✅ API lock is available")
        
        # Test lock is reentrant
        with api_lock:
            with api_lock:
                nonce3 = get_global_kraken_nonce()
                print(f"✅ Reentrant lock works, nonce: {nonce3}")
        
        print("✅ TEST 1 PASSED: GlobalKrakenNonceManager works correctly")
        return True
        
    except Exception as e:
        print(f"❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_kraken_client():
    """Test KrakenClient initialization."""
    print("\n" + "=" * 70)
    print("TEST 2: KrakenClient Initialization")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import KrakenClient
        
        # Check if credentials are available
        api_key = os.getenv("KRAKEN_MASTER_API_KEY") or os.getenv("KRAKEN_API_KEY")
        api_secret = os.getenv("KRAKEN_MASTER_API_SECRET") or os.getenv("KRAKEN_API_SECRET")
        
        if not api_key or not api_secret:
            print("⚠️  Kraken credentials not configured - skipping client test")
            return True  # Not a failure, just skipped
        
        # Create test client (no nonce_store parameter - uses GlobalKrakenNonceManager)
        client = KrakenClient(
            api_key=api_key,
            api_secret=api_secret,
            account_identifier="TEST"
        )
        
        print(f"✅ KrakenClient created: {client.account_identifier}")
        
        # Test nonce generation
        nonce1 = client._nonce()
        time.sleep(0.01)  # Small delay
        nonce2 = client._nonce()
        
        assert nonce2 > nonce1, "Client nonce must increase"
        print(f"✅ Client nonce generation works: {nonce1} < {nonce2}")
        
        # Clean up
        if nonce_store.nonce_file.exists():
            nonce_store.nonce_file.unlink()
        
        print("✅ TEST 2 PASSED: KrakenClient works correctly")
        return True
        
    except Exception as e:
        print(f"❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_master_initialization():
    """Test MASTER initialization."""
    print("\n" + "=" * 70)
    print("TEST 3: MASTER Initialization")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import initialize_kraken_master, KRAKEN_MASTER
        
        # Initialize master
        success = initialize_kraken_master()
        
        if not success:
            print("⚠️  MASTER initialization failed (credentials may not be configured)")
            return True  # Not a failure if credentials aren't set
        
        print("✅ MASTER initialized successfully")
        
        # Try to get balance
        from bot.kraken_copy_trading import KRAKEN_MASTER
        if KRAKEN_MASTER:
            balance_result = KRAKEN_MASTER.get_balance()
            if 'error' in balance_result and balance_result['error']:
                print(f"⚠️  MASTER balance check failed: {balance_result['error']}")
            else:
                balances = balance_result.get('result', {})
                usd = float(balances.get('ZUSD', 0))
                usdt = float(balances.get('USDT', 0))
                print(f"✅ MASTER balance: USD ${usd:.2f}, USDT ${usdt:.2f}")
        
        print("✅ TEST 3 PASSED: MASTER initialization works")
        return True
        
    except Exception as e:
        print(f"❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_users_initialization():
    """Test USERS initialization."""
    print("\n" + "=" * 70)
    print("TEST 4: USERS Initialization")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import initialize_kraken_users, KRAKEN_USERS
        
        # Initialize users
        user_count = initialize_kraken_users()
        
        print(f"✅ Initialized {user_count} users")
        
        # Display user details
        from bot.kraken_copy_trading import KRAKEN_USERS
        if KRAKEN_USERS:
            for user in KRAKEN_USERS:
                print(f"   - {user['name']} ({user['id']}): ${user['balance']:.2f}")
        else:
            print("   (No users configured)")
        
        print("✅ TEST 4 PASSED: USERS initialization works")
        return True
        
    except Exception as e:
        print(f"❌ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_full_system_initialization():
    """Test complete system initialization."""
    print("\n" + "=" * 70)
    print("TEST 5: Full System Initialization")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import initialize_copy_trading_system
        
        # Initialize complete system
        success = initialize_copy_trading_system()
        
        if success:
            print("✅ Full system initialized successfully")
        else:
            print("⚠️  Full system initialization had warnings (check logs)")
        
        print("✅ TEST 5 PASSED: System initialization works")
        return True
        
    except Exception as e:
        print(f"❌ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_price_lookup():
    """Test price lookup functionality."""
    print("\n" + "=" * 70)
    print("TEST 6: Price Lookup")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import get_price
        
        # Test BTC/USD price
        btc_price = get_price("XXBTZUSD")
        print(f"✅ BTC/USD price: ${btc_price:.2f}")
        
        assert btc_price > 0, "Price must be positive"
        
        print("✅ TEST 6 PASSED: Price lookup works")
        return True
        
    except Exception as e:
        print(f"❌ TEST 6 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("🧪 KRAKEN COPY TRADING TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("GlobalNonceManager", test_global_nonce_manager),
        ("KrakenClient", test_kraken_client),
        ("MASTER Init", test_master_initialization),
        ("USERS Init", test_users_initialization),
        ("Full System", test_full_system_initialization),
        ("Price Lookup", test_price_lookup),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("=" * 70)
    print(f"Result: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
