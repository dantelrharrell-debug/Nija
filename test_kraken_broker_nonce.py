#!/usr/bin/env python3
"""
Test KrakenBroker instances use separate nonce files.

This test verifies that when multiple KrakenBroker instances are created
(MASTER and USER accounts), each uses its own nonce file.
"""

import os
import sys
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import KrakenBroker, AccountType, get_kraken_nonce_file

def test_kraken_broker_nonce_files():
    """Test that KrakenBroker instances use account-specific nonce files."""
    print()
    print("=" * 70)
    print("🧪 KRAKEN BROKER NONCE FILE TEST")
    print("=" * 70)
    print()
    
    # Create MASTER broker instance
    print("Creating MASTER broker instance...")
    master_broker = KrakenBroker(account_type=AccountType.MASTER)
    print(f"   Account identifier: {master_broker.account_identifier}")
    print(f"   Nonce file: {master_broker._nonce_file}")
    
    expected_master_file = get_kraken_nonce_file("MASTER")
    assert master_broker._nonce_file == expected_master_file, \
        f"MASTER nonce file mismatch: {master_broker._nonce_file} != {expected_master_file}"
    print(f"✅ MASTER broker uses correct nonce file")
    print()
    
    # Create USER broker instances
    print("Creating USER broker instance for daivon_frazier...")
    daivon_broker = KrakenBroker(account_type=AccountType.USER, user_id="daivon_frazier")
    print(f"   Account identifier: {daivon_broker.account_identifier}")
    print(f"   Nonce file: {daivon_broker._nonce_file}")
    
    expected_daivon_file = get_kraken_nonce_file("USER:daivon_frazier")
    assert daivon_broker._nonce_file == expected_daivon_file, \
        f"Daivon nonce file mismatch: {daivon_broker._nonce_file} != {expected_daivon_file}"
    print(f"✅ Daivon broker uses correct nonce file")
    print()
    
    print("Creating USER broker instance for tania_gilbert...")
    tania_broker = KrakenBroker(account_type=AccountType.USER, user_id="tania_gilbert")
    print(f"   Account identifier: {tania_broker.account_identifier}")
    print(f"   Nonce file: {tania_broker._nonce_file}")
    
    expected_tania_file = get_kraken_nonce_file("USER:tania_gilbert")
    assert tania_broker._nonce_file == expected_tania_file, \
        f"Tania nonce file mismatch: {tania_broker._nonce_file} != {expected_tania_file}"
    print(f"✅ Tania broker uses correct nonce file")
    print()
    
    # Verify all three nonce files are different
    print("Verifying nonce file isolation...")
    assert master_broker._nonce_file != daivon_broker._nonce_file, \
        "MASTER and Daivon should use different nonce files"
    assert master_broker._nonce_file != tania_broker._nonce_file, \
        "MASTER and Tania should use different nonce files"
    assert daivon_broker._nonce_file != tania_broker._nonce_file, \
        "Daivon and Tania should use different nonce files"
    print(f"✅ All brokers use isolated nonce files")
    print()
    
    # Check that initial nonces are loaded correctly
    print("Checking initial nonce values...")
    print(f"   MASTER initial nonce: {master_broker._last_nonce}")
    print(f"   Daivon initial nonce: {daivon_broker._last_nonce}")
    print(f"   Tania initial nonce: {tania_broker._last_nonce}")
    
    # All should have valid nonce values (> 0)
    assert master_broker._last_nonce > 0, "MASTER should have valid initial nonce"
    assert daivon_broker._last_nonce > 0, "Daivon should have valid initial nonce"
    assert tania_broker._last_nonce > 0, "Tania should have valid initial nonce"
    print(f"✅ All brokers initialized with valid nonces")
    print()
    
    print("=" * 70)
    print("✅ ALL KRAKEN BROKER TESTS PASSED")
    print("=" * 70)
    print()
    print("Summary:")
    print(f"  ✅ MASTER uses: {os.path.basename(master_broker._nonce_file)}")
    print(f"  ✅ Daivon uses: {os.path.basename(daivon_broker._nonce_file)}")
    print(f"  ✅ Tania uses: {os.path.basename(tania_broker._nonce_file)}")
    print(f"  ✅ All nonce files are isolated")
    print(f"  ✅ No nonce collisions possible")
    print()
    
    return 0

def main():
    """Run the test."""
    try:
        return test_kraken_broker_nonce_files()
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
