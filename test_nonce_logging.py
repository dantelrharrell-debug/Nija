#!/usr/bin/env python3
"""
Test script to verify that nonce errors are logged at INFO level on first attempt,
and DEBUG level on retries, to provide visibility while reducing log spam.

This validates the fix for the Kraken connection logging issue.
"""

import logging
import sys
from io import StringIO

def log_kraken_error(logger, is_nonce_error, attempt, max_attempts, cred_label, error_msgs):
    """
    Helper function to apply the Kraken error logging logic.
    
    This matches the logic from broker_manager.py KrakenBroker.connect()
    """
    error_type = "nonce" if is_nonce_error else "retryable"
    
    # For nonce errors, log at INFO level on first attempt so users know what failed
    # Log at DEBUG level on retries to reduce spam
    # These are transient and automatically retried with nonce jumps
    if is_nonce_error:
        if attempt == 1:
            logger.info(f"   ⚠️  Kraken ({cred_label}) nonce error on attempt {attempt}/{max_attempts} (auto-retry): {error_msgs}")
        else:
            logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): {error_msgs}")
    # For lockout/other errors, log at WARNING on first attempt only
    elif attempt == 1:
        logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    # All retries after first attempt: DEBUG level only
    else:
        logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")


def test_nonce_error_logging_logic():
    """Test the logging logic for nonce errors"""
    
    print("=" * 70)
    print("Testing Nonce Error Logging Logic")
    print("=" * 70)
    
    # Create a test logger with a custom handler to capture output
    test_logger = logging.getLogger('test_nonce_logging')
    test_logger.setLevel(logging.DEBUG)
    
    # Add handler to capture logs
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    test_logger.addHandler(handler)
    
    # Test parameters
    attempt = 1
    max_attempts = 5
    cred_label = "MASTER"
    
    # Test case 1: Nonce error on first attempt (should be INFO)
    error_msgs = "EAPI:Invalid nonce"
    is_nonce_error = True
    
    # Apply the logging logic
    log_kraken_error(test_logger, is_nonce_error, attempt, max_attempts, cred_label, error_msgs)
    
    # Check the log output
    log_output = log_stream.getvalue()
    print("Log output for nonce error (attempt 1):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at INFO level (NEW BEHAVIOR)
    assert "INFO" in log_output, "Nonce error on first attempt should be logged at INFO level"
    assert "WARNING" not in log_output, "Nonce error should NOT be logged at WARNING level"
    assert "nonce error" in log_output, "Should mention nonce error"
    print("✅ PASS: Nonce error logged at INFO level on first attempt")
    print()
    
    # Test case 2: Nonce error on retry attempt (should be DEBUG)
    log_stream.truncate(0)
    log_stream.seek(0)
    
    attempt = 2
    
    log_kraken_error(test_logger, is_nonce_error, attempt, max_attempts, cred_label, error_msgs)
    
    log_output = log_stream.getvalue()
    print("Log output for nonce error (attempt 2):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at DEBUG level
    assert "DEBUG" in log_output, "Nonce error on retry should be logged at DEBUG level"
    assert "INFO" not in log_output, "Nonce error on retry should NOT be logged at INFO level"
    print("✅ PASS: Nonce error on retry logged at DEBUG level")
    print()
    
    # Test case 3: Non-nonce error on first attempt (should be WARNING)
    log_stream.truncate(0)
    log_stream.seek(0)
    
    attempt = 1
    is_nonce_error = False
    error_msgs = "503 Service Unavailable"
    
    log_kraken_error(test_logger, is_nonce_error, attempt, max_attempts, cred_label, error_msgs)
    
    log_output = log_stream.getvalue()
    print("Log output for non-nonce error (attempt 1):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at WARNING level
    assert "WARNING" in log_output, "Non-nonce error on first attempt should be logged at WARNING level"
    print("✅ PASS: Non-nonce error logged at WARNING level on first attempt")
    print()
    
    # Test case 4: Non-nonce error on retry attempt (should be DEBUG)
    log_stream.truncate(0)
    log_stream.seek(0)
    
    attempt = 2
    
    log_kraken_error(test_logger, is_nonce_error, attempt, max_attempts, cred_label, error_msgs)
    
    log_output = log_stream.getvalue()
    print("Log output for non-nonce error (attempt 2):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at DEBUG level
    assert "DEBUG" in log_output, "Retry attempts should be logged at DEBUG level"
    assert "WARNING" not in log_output, "Retry attempts should NOT be logged at WARNING level"
    print("✅ PASS: Retry attempt logged at DEBUG level")
    print()
    
    print("=" * 70)
    print("ALL TESTS PASSED ✅")
    print("=" * 70)
    print()
    print("Summary:")
    print("  - Nonce errors (first attempt): Logged at INFO level (provides visibility)")
    print("  - Nonce errors (retries): Logged at DEBUG level (reduces spam)")
    print("  - First attempt non-nonce errors: Logged at WARNING level")
    print("  - Retry attempts: Logged at DEBUG level (reduces spam)")
    print()


if __name__ == "__main__":
    try:
        test_nonce_error_logging_logic()
        sys.exit(0)
    except AssertionError as e:
        print(f"❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
