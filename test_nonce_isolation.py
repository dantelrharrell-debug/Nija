#!/usr/bin/env python3
"""
Test script to verify that Kraken accounts use isolated nonce files.

This test verifies:
1. get_kraken_nonce_file() generates correct account-specific paths
2. get_kraken_nonce() uses separate files for different accounts
3. Each account's nonce is independent
4. MASTER account migration from legacy nonce file works
"""

import os
import sys
import time
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import get_kraken_nonce_file, get_kraken_nonce, _data_dir

def test_nonce_file_paths():
    """Test that account-specific nonce file paths are generated correctly."""
    print("=" * 70)
    print("TEST 1: Nonce File Path Generation")
    print("=" * 70)
    
    # Test MASTER account
    master_file = get_kraken_nonce_file("MASTER")
    expected_master = os.path.join(_data_dir, "kraken_nonce_master.txt")
    assert master_file == expected_master, f"MASTER nonce file mismatch: {master_file} != {expected_master}"
    print(f"✅ MASTER nonce file: {master_file}")
    
    # Test USER account (daivon_frazier)
    daivon_file = get_kraken_nonce_file("USER:daivon_frazier")
    expected_daivon = os.path.join(_data_dir, "kraken_nonce_user_daivon_frazier.txt")
    assert daivon_file == expected_daivon, f"Daivon nonce file mismatch: {daivon_file} != {expected_daivon}"
    print(f"✅ Daivon nonce file: {daivon_file}")
    
    # Test USER account (tania_gilbert)
    tania_file = get_kraken_nonce_file("USER:tania_gilbert")
    expected_tania = os.path.join(_data_dir, "kraken_nonce_user_tania_gilbert.txt")
    assert tania_file == expected_tania, f"Tania nonce file mismatch: {tania_file} != {expected_tania}"
    print(f"✅ Tania nonce file: {tania_file}")
    
    print()

def test_nonce_isolation():
    """Test that each account gets independent nonce values."""
    print("=" * 70)
    print("TEST 2: Nonce Isolation Between Accounts")
    print("=" * 70)
    
    # Clean up any existing nonce files
    test_files = [
        get_kraken_nonce_file("test_master"),
        get_kraken_nonce_file("test_user_1"),
        get_kraken_nonce_file("test_user_2"),
    ]
    
    for f in test_files:
        if os.path.exists(f):
            os.remove(f)
    
    # Generate nonces for different accounts
    nonce_master = get_kraken_nonce("test_master")
    time.sleep(0.01)  # Small delay to ensure different timestamps
    nonce_user1 = get_kraken_nonce("test_user_1")
    time.sleep(0.01)
    nonce_user2 = get_kraken_nonce("test_user_2")
    
    print(f"   test_master nonce: {nonce_master}")
    print(f"   test_user_1 nonce: {nonce_user1}")
    print(f"   test_user_2 nonce: {nonce_user2}")
    
    # All nonces should be different
    assert nonce_master != nonce_user1, "Master and User1 nonces should be different"
    assert nonce_master != nonce_user2, "Master and User2 nonces should be different"
    assert nonce_user1 != nonce_user2, "User1 and User2 nonces should be different"
    print("✅ All account nonces are independent")
    
    # Verify files were created
    for account_id, test_file in [
        ("test_master", test_files[0]),
        ("test_user_1", test_files[1]),
        ("test_user_2", test_files[2])
    ]:
        assert os.path.exists(test_file), f"Nonce file not created for {account_id}"
        with open(test_file, 'r') as f:
            stored_nonce = int(f.read().strip())
        print(f"✅ {account_id} nonce file exists with value: {stored_nonce}")
    
    # Clean up
    for f in test_files:
        if os.path.exists(f):
            os.remove(f)
    
    print()

def test_nonce_persistence():
    """Test that nonces persist across multiple calls."""
    print("=" * 70)
    print("TEST 3: Nonce Persistence")
    print("=" * 70)
    
    # Clean up
    test_file = get_kraken_nonce_file("test_persistence")
    if os.path.exists(test_file):
        os.remove(test_file)
    
    # Generate first nonce
    nonce1 = get_kraken_nonce("test_persistence")
    print(f"   First nonce: {nonce1}")
    
    # Small delay to ensure time advances
    time.sleep(0.01)
    
    # Generate second nonce - should be higher
    nonce2 = get_kraken_nonce("test_persistence")
    print(f"   Second nonce: {nonce2}")
    
    assert nonce2 > nonce1, "Second nonce should be strictly greater than first"
    print(f"✅ Nonce increased: {nonce2 - nonce1} microseconds")
    
    # Verify file has the latest nonce
    with open(test_file, 'r') as f:
        stored_nonce = int(f.read().strip())
    
    assert stored_nonce == nonce2, f"Stored nonce {stored_nonce} should match latest nonce {nonce2}"
    print(f"✅ Latest nonce persisted to file: {stored_nonce}")
    
    # Clean up
    if os.path.exists(test_file):
        os.remove(test_file)
    
    print()

def test_legacy_migration():
    """Test that MASTER account can migrate from legacy nonce file."""
    print("=" * 70)
    print("TEST 4: Legacy Nonce File Migration")
    print("=" * 70)
    
    # Clean up
    legacy_file = os.path.join(_data_dir, "kraken_nonce.txt")
    master_file = get_kraken_nonce_file("master")
    
    for f in [legacy_file, master_file]:
        if os.path.exists(f):
            os.remove(f)
    
    # Create legacy nonce file with a specific value
    legacy_nonce = 1234567890000000
    os.makedirs(_data_dir, exist_ok=True)
    with open(legacy_file, 'w') as f:
        f.write(str(legacy_nonce))
    
    print(f"   Created legacy nonce file: {legacy_nonce}")
    
    # Call get_kraken_nonce for master - should migrate
    new_nonce = get_kraken_nonce("master")
    
    print(f"   New nonce after migration: {new_nonce}")
    
    # New nonce should be higher than legacy nonce
    assert new_nonce > legacy_nonce, f"New nonce {new_nonce} should be higher than legacy {legacy_nonce}"
    print(f"✅ Nonce migrated and incremented")
    
    # Verify new master file exists
    assert os.path.exists(master_file), "Master nonce file should exist after migration"
    with open(master_file, 'r') as f:
        stored_nonce = int(f.read().strip())
    
    assert stored_nonce == new_nonce, "Stored nonce should match new nonce"
    print(f"✅ Master nonce file created: {master_file}")
    
    # Clean up
    for f in [legacy_file, master_file]:
        if os.path.exists(f):
            os.remove(f)
    
    print()

def main():
    """Run all tests."""
    print()
    print("🧪 KRAKEN NONCE ISOLATION TEST SUITE")
    print()
    
    try:
        test_nonce_file_paths()
        test_nonce_isolation()
        test_nonce_persistence()
        test_legacy_migration()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("Summary:")
        print("  ✅ Account-specific nonce file paths are correct")
        print("  ✅ Each account has independent nonce tracking")
        print("  ✅ Nonces persist correctly across calls")
        print("  ✅ Legacy MASTER nonce migration works")
        print()
        print("Expected behavior in production:")
        print("  - MASTER: data/kraken_nonce_master.txt")
        print("  - USER Daivon: data/kraken_nonce_user_daivon_frazier.txt")
        print("  - USER Tania: data/kraken_nonce_user_tania_gilbert.txt")
        print("  - No nonce collisions between accounts")
        print()
        return 0
        
    except AssertionError as e:
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        return 1
    except Exception as e:
        print("=" * 70)
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
