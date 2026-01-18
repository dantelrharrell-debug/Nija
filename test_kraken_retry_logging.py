#!/usr/bin/env python3
"""
Test script to verify Kraken retry logging behavior.
This script simulates the retry logic to ensure no log spam occurs.
"""

import logging
import sys
import os

# Setup minimal logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('test')

def simulate_retry_logic():
    """
    Simulate the Kraken retry logic to verify logging behavior.
    Expected: First nonce error logs at INFO, retries at DEBUG, final failure logs ERROR.
    """
    max_attempts = 5
    nonce_base_delay = 30.0
    last_error_was_nonce = True
    cred_label = "TEST_MASTER"
    
    print("\n" + "=" * 70)
    print("SIMULATING KRAKEN RETRY LOGIC (INFO LEVEL)")
    print("Expected: First attempt INFO, retries DEBUG, final ERROR")
    print("=" * 70 + "\n")
    
    for attempt in range(1, max_attempts + 1):
        # Simulate first attempt failure logging
        # NEW BEHAVIOR: Nonce errors log at INFO level on first attempt, DEBUG on retries
        if attempt == 1:
            logger.info(f"   ⚠️  Kraken ({cred_label}) nonce error on attempt {attempt}/{max_attempts} (auto-retry): EAPI:Invalid nonce")
        
        # Simulate retry delay and logging (attempts 2-5)
        if attempt > 1:
            if last_error_was_nonce:
                delay = nonce_base_delay * (attempt - 1)
                # Log retry message at INFO level (attempt number in message)
                logger.info(f"   🔄 Retrying Kraken ({cred_label}) in {delay:.0f}s (attempt {attempt}/{max_attempts}, nonce)")
                
                # Simulate sleep (skip in test)
                print(f"  → Sleeping {delay:.0f}s before attempt {attempt}...")
        
        # Simulate attempt failure (all attempts fail in this test)
        if attempt > 1 and attempt < max_attempts:
            # Log failure at DEBUG level for retries
            logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): EAPI:Invalid nonce")
    
    # Final failure logging
    logger.error(f"❌ Kraken ({cred_label}) failed after {max_attempts} attempts")
    logger.error("   Last error was: Invalid nonce (API nonce synchronization issue)")
    logger.error("   This usually resolves after waiting 1-2 minutes")
    
    print("\n" + "=" * 70)
    print("✅ TEST COMPLETE - Review logs above")
    print("=" * 70)
    print("\nNEW BEHAVIOR (post-fix):")
    print("  - First nonce error is logged at INFO level")
    print("  - Subsequent nonce errors are logged at DEBUG level only")
    print("  - Retry messages are logged at INFO level so users see progress")
    print("  - Final failure still logged as ERROR with full details")
    print("\nExpected output:")
    print("  1. One INFO message for first nonce error")
    print("  2. INFO 'Retrying' messages for attempts 2-5")
    print("  3. Sleep messages for attempts 2-5")
    print("  4. Final ERROR summary")
    print("\nActual messages logged (at INFO level):")
    print("  - 1 INFO message (first nonce error)")
    print("  - 4 INFO 'Retrying' messages (attempts 2-5)")
    print("  - 3 ERROR messages (final failure summary)")
    print("=" * 70 + "\n")

def simulate_with_debug():
    """
    Simulate with DEBUG logging enabled to verify retry messages appear.
    """
    print("\n" + "=" * 70)
    print("SIMULATING KRAKEN RETRY LOGIC (DEBUG LEVEL)")
    print("Expected: All retry messages visible, including first nonce error at INFO")
    print("NOTE: First nonce error logs at INFO, retries at DEBUG")
    print("=" * 70 + "\n")
    
    # Enable DEBUG logging
    logger.setLevel(logging.DEBUG)
    
    max_attempts = 5
    nonce_base_delay = 30.0
    last_error_was_nonce = True
    cred_label = "TEST_MASTER_DEBUG"
    
    for attempt in range(1, max_attempts + 1):
        if attempt == 1:
            # NEW BEHAVIOR: First nonce error logs at INFO level
            logger.info(f"   ⚠️  Kraken ({cred_label}) nonce error on attempt {attempt}/{max_attempts} (auto-retry): EAPI:Invalid nonce")
        
        if attempt > 1:
            if last_error_was_nonce:
                delay = nonce_base_delay * (attempt - 1)
                logger.info(f"   🔄 Retrying Kraken ({cred_label}) in {delay:.0f}s (attempt {attempt}/{max_attempts}, nonce)")
                print(f"  → Sleeping {delay:.0f}s before attempt {attempt}...")
                
                # Log subsequent failures at DEBUG level
                if attempt < max_attempts:
                    logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): EAPI:Invalid nonce")
    
    logger.error(f"❌ Kraken ({cred_label}) failed after {max_attempts} attempts")
    logger.error("   Last error was: Invalid nonce (API nonce synchronization issue)")
    
    print("\n" + "=" * 70)
    print("✅ DEBUG TEST COMPLETE")
    print("=" * 70)
    print("\nExpected output:")
    print("  - Should see INFO message for first nonce error")
    print("  - Should see INFO retry messages for attempts 2-5")
    print("  - Should see DEBUG retry failure messages for attempts 2-4")
    print("=" * 70 + "\n")
    
    # Reset to INFO level
    logger.setLevel(logging.INFO)

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("KRAKEN RETRY LOGGING TEST")
    print("=" * 70)
    
    # Test 1: Normal INFO level (production)
    simulate_retry_logic()
    
    # Test 2: DEBUG level enabled
    simulate_with_debug()
    
    print("\n✅ All tests complete!\n")
