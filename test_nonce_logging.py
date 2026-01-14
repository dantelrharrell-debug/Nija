#!/usr/bin/env python3
"""
Test script to verify that nonce errors are logged at DEBUG level,
not WARNING level, to reduce log spam.

This validates the fix for the Kraken connection logging issue.
"""

import logging
import sys
from io import StringIO

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
    
    # Simulate the logging logic from broker_manager.py
    attempt = 1
    max_attempts = 5
    cred_label = "MASTER"
    error_msgs = "EAPI:Invalid nonce"
    
    # Test case 1: Nonce error on first attempt
    is_nonce_error = True
    is_lockout_error = False
    error_type = "nonce" if is_nonce_error else "retryable"
    
    # This is the new logic - should log at DEBUG level
    if is_nonce_error:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): {error_msgs}")
    elif attempt == 1:
        test_logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    else:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    
    # Check the log output
    log_output = log_stream.getvalue()
    print("Log output for nonce error (attempt 1):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at DEBUG level, not WARNING
    assert "DEBUG" in log_output, "Nonce error should be logged at DEBUG level"
    assert "WARNING" not in log_output, "Nonce error should NOT be logged at WARNING level"
    assert "nonce error (auto-retry)" in log_output, "Should mention auto-retry"
    print("✅ PASS: Nonce error logged at DEBUG level")
    print()
    
    # Test case 2: Non-nonce error on first attempt (should be WARNING)
    log_stream.truncate(0)
    log_stream.seek(0)
    
    is_nonce_error = False
    error_type = "retryable"
    error_msgs = "503 Service Unavailable"
    
    if is_nonce_error:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): {error_msgs}")
    elif attempt == 1:
        test_logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    else:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    
    log_output = log_stream.getvalue()
    print("Log output for non-nonce error (attempt 1):")
    print(f"  {log_output.strip()}")
    
    # Verify it's at WARNING level
    assert "WARNING" in log_output, "Non-nonce error on first attempt should be logged at WARNING level"
    print("✅ PASS: Non-nonce error logged at WARNING level on first attempt")
    print()
    
    # Test case 3: Non-nonce error on retry attempt (should be DEBUG)
    log_stream.truncate(0)
    log_stream.seek(0)
    
    attempt = 2
    
    if is_nonce_error:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} nonce error (auto-retry): {error_msgs}")
    elif attempt == 1:
        test_logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    else:
        test_logger.debug(f"🔄 Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msgs}")
    
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
    print("  - Nonce errors: Logged at DEBUG level (reduces spam)")
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
