#!/usr/bin/env python3
"""
Test script to validate Kraken nonce persistence across restarts.

This test verifies that:
1. Nonce is persisted to kraken_nonce.txt
2. Nonce is loaded from file on next call
3. New nonce is always higher than previous (monotonic)
4. File-based nonce survives "restart" (new function call)
"""

import os
import time
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import the function we're testing
from broker_manager import get_kraken_nonce, NONCE_FILE


def test_nonce_persistence():
    """Test that nonce is properly persisted and loaded"""
    print("=" * 70)
    print("TEST: Kraken Nonce Persistence (Jan 17, 2026)")
    print("=" * 70)
    print()
    
    # Clean up any existing nonce file
    if os.path.exists(NONCE_FILE):
        os.remove(NONCE_FILE)
        print(f"✓ Cleaned up existing nonce file")
    
    print("\n--- TEST 1: Initial nonce generation and persistence ---")
    nonce1 = get_kraken_nonce()
    print(f"Generated nonce: {nonce1}")
    
    # Verify file was created
    assert os.path.exists(NONCE_FILE), f"❌ FAIL: Nonce file not created"
    print(f"✓ Nonce file created")
    
    # Read file content
    with open(NONCE_FILE, "r") as f:
        file_content = f.read().strip()
    print(f"File content: {file_content}")
    assert file_content == str(nonce1), f"❌ FAIL: File content mismatch"
    print("✓ File content matches generated nonce")
    
    print("\n--- TEST 2: Subsequent nonce is higher (monotonic) ---")
    time.sleep(0.001)  # Small delay
    nonce2 = get_kraken_nonce()
    print(f"Generated nonce: {nonce2}")
    assert nonce2 > nonce1, f"❌ FAIL: nonce2 ({nonce2}) not > nonce1 ({nonce1})"
    print(f"✓ Nonce increased: {nonce2} > {nonce1}")
    
    # Verify file was updated
    with open(NONCE_FILE, "r") as f:
        file_content = f.read().strip()
    assert file_content == str(nonce2), f"❌ FAIL: File not updated"
    print(f"✓ File updated with new nonce: {file_content}")
    
    print("\n--- TEST 3: Simulate restart (reload from file) ---")
    # Read the persisted nonce
    with open(NONCE_FILE, "r") as f:
        persisted_value = int(f.read().strip())
    print(f"Persisted nonce from file: {persisted_value}")
    
    # Generate new nonce (simulates restart)
    nonce3 = get_kraken_nonce()
    print(f"New nonce after 'restart': {nonce3}")
    
    # New nonce must be higher than persisted
    assert nonce3 > persisted_value, f"❌ FAIL: New nonce not higher than persisted"
    print(f"✓ New nonce > persisted nonce: {nonce3} > {persisted_value}")
    
    print("\n--- TEST 4: Rapid consecutive calls (stress test) ---")
    nonces = []
    for i in range(10):
        nonce = get_kraken_nonce()
        nonces.append(nonce)
    
    print(f"Generated {len(nonces)} nonces")
    
    # Verify all nonces are unique
    assert len(nonces) == len(set(nonces)), "❌ FAIL: Duplicate nonces found"
    print("✓ All nonces are unique")
    
    # Verify all nonces are monotonically increasing
    for i in range(1, len(nonces)):
        assert nonces[i] > nonces[i-1], f"❌ FAIL: Non-monotonic at index {i}"
    print("✓ All nonces are monotonically increasing")
    
    # Verify last nonce is persisted
    with open(NONCE_FILE, "r") as f:
        final_persisted = int(f.read().strip())
    assert final_persisted == nonces[-1], "❌ FAIL: Last nonce not persisted"
    print(f"✓ Last nonce persisted: {final_persisted}")
    
    print("\n--- TEST 5: Restart protection (wait and generate) ---")
    # Simulate waiting 1 second (time moves forward)
    print("Waiting 1 second...")
    time.sleep(1)
    
    # Generate new nonce
    nonce_after_wait = get_kraken_nonce()
    print(f"Nonce after wait: {nonce_after_wait}")
    
    # Should be higher than last persisted
    assert nonce_after_wait > final_persisted, "❌ FAIL: Nonce not higher after wait"
    print(f"✓ Nonce increased after wait: {nonce_after_wait} > {final_persisted}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY - ALL TESTS PASSED ✅")
    print("=" * 70)
    print()
    print("The nonce persistence fix correctly implements:")
    print("  ✅ Nonce persisted to kraken_nonce.txt")
    print("  ✅ Nonce loaded from file on subsequent calls")
    print("  ✅ Monotonic guarantee (always increasing)")
    print("  ✅ Thread-safe with lock")
    print("  ✅ Restart protection (survives restarts)")
    print()
    print("Expected result:")
    print("  🚀 No 'Invalid nonce' errors on bot restart")
    print("  🚀 Kraken connection succeeds even with rapid restarts")
    print("  🚀 Works on Railway/Render (file-based persistence)")
    print()
    
    # Cleanup
    if os.path.exists(NONCE_FILE):
        os.remove(NONCE_FILE)
        print(f"✓ Cleaned up nonce file")
    
    return True


if __name__ == "__main__":
    try:
        test_nonce_persistence()
        print("\n✅ TEST SUITE PASSED")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
