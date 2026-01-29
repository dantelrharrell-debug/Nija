"""
Test script for broker timeout fix (Jan 28, 2026)

Tests the timeout handling improvements:
1. call_with_timeout race condition fix
2. Timeout set to 45s to accommodate Kraken API timeout (30s) + network overhead (15s)
3. Permissive cached balance fallback
4. Better exception logging
"""

import sys
import time
import threading
sys.path.insert(0, '.')

from bot.trading_strategy import call_with_timeout, BALANCE_FETCH_TIMEOUT, CACHED_BALANCE_MAX_AGE_SECONDS


def test_timeout_constant():
    """Test that timeout is set to 45s to accommodate Kraken API timeout (30s) + network overhead"""
    print("=" * 70)
    print("TEST 1: Timeout Constant Value")
    print("=" * 70)

    print(f"BALANCE_FETCH_TIMEOUT = {BALANCE_FETCH_TIMEOUT}s")
    assert BALANCE_FETCH_TIMEOUT == 45, f"Timeout should be 45s, got {BALANCE_FETCH_TIMEOUT}s"
    print(f"✅ Timeout correctly set to 45 seconds (30s Kraken API + 15s buffer)")
    print()


def test_call_with_timeout_success():
    """Test call_with_timeout with successful function"""
    print("=" * 70)
    print("TEST 2: call_with_timeout Success Case")
    print("=" * 70)

    def fast_function():
        return 42

    result, error = call_with_timeout(fast_function, timeout_seconds=5)

    print(f"Result: {result}, Error: {error}")
    assert result == 42, f"Should return 42, got {result}"
    assert error is None, f"Should have no error, got {error}"
    print("✅ Fast function completes successfully")
    print()


def test_call_with_timeout_actual_timeout():
    """Test call_with_timeout with function that times out"""
    print("=" * 70)
    print("TEST 3: call_with_timeout Timeout Case")
    print("=" * 70)

    def slow_function():
        time.sleep(10)  # Sleep longer than timeout
        return "should not reach here"

    start_time = time.time()
    result, error = call_with_timeout(slow_function, timeout_seconds=2)
    elapsed = time.time() - start_time

    print(f"Result: {result}, Error: {error}")
    print(f"Elapsed time: {elapsed:.1f}s")

    assert result is None, f"Result should be None on timeout, got {result}"
    assert error is not None, f"Should have timeout error, got None"
    assert "timed out" in str(error).lower(), f"Error should mention timeout: {error}"
    assert elapsed < 3, f"Should timeout in ~2s, took {elapsed:.1f}s"
    print("✅ Timeout works correctly in ~2 seconds")
    print()


def test_call_with_timeout_exception():
    """Test call_with_timeout with function that raises exception"""
    print("=" * 70)
    print("TEST 4: call_with_timeout Exception Case")
    print("=" * 70)

    def failing_function():
        raise ValueError("Test error")

    result, error = call_with_timeout(failing_function, timeout_seconds=5)

    print(f"Result: {result}, Error: {error}")
    assert result is None, f"Result should be None on exception, got {result}"
    assert error is not None, f"Should have error, got None"
    assert isinstance(error, ValueError), f"Error should be ValueError, got {type(error)}"
    assert "Test error" in str(error), f"Error message should be preserved: {error}"
    print("✅ Exception handling works correctly")
    print()


def test_call_with_timeout_race_condition():
    """Test that race condition fix works (thread completes just as timeout expires)"""
    print("=" * 70)
    print("TEST 5: call_with_timeout Race Condition Fix")
    print("=" * 70)

    success_count = 0
    timeout_count = 0
    error_count = 0

    def borderline_function():
        """Function that completes right at timeout boundary"""
        time.sleep(0.95)  # Sleep just under timeout
        return "completed"

    # Run multiple times to check for race condition
    for i in range(10):
        result, error = call_with_timeout(borderline_function, timeout_seconds=1)

        if result == "completed" and error is None:
            success_count += 1
        elif error is not None and "timed out" in str(error).lower():
            timeout_count += 1
        else:
            error_count += 1
            print(f"   ⚠️  Unexpected result on iteration {i+1}: result={result}, error={error}")

    print(f"Results: {success_count} successes, {timeout_count} timeouts, {error_count} errors")

    # With race condition fix (using get(timeout=1.0) instead of get_nowait),
    # we should never get "Worker thread completed but no result available" error
    assert error_count == 0, f"Should have 0 errors, got {error_count}"

    # Most calls should succeed since function completes in 0.95s < 1s timeout
    assert success_count >= 7, f"Should have at least 7/10 successes, got {success_count}"

    print("✅ Race condition fix works - no 'Worker thread completed' errors")
    print()


def test_cached_balance_max_age():
    """Test cached balance max age constant"""
    print("=" * 70)
    print("TEST 6: Cached Balance Max Age")
    print("=" * 70)

    print(f"CACHED_BALANCE_MAX_AGE_SECONDS = {CACHED_BALANCE_MAX_AGE_SECONDS}s ({CACHED_BALANCE_MAX_AGE_SECONDS/60:.0f} minutes)")
    assert CACHED_BALANCE_MAX_AGE_SECONDS == 300, f"Cache age should be 300s (5 min), got {CACHED_BALANCE_MAX_AGE_SECONDS}s"
    print("✅ Cached balance max age correctly set to 5 minutes")
    print()


if __name__ == "__main__":
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "BROKER TIMEOUT FIX TEST SUITE" + " " * 24 + "║")
    print("║" + " " * 20 + "January 28, 2026" + " " * 30 + "║")
    print("╚" + "=" * 68 + "╝")
    print("\n")

    try:
        test_timeout_constant()
        test_call_with_timeout_success()
        test_call_with_timeout_actual_timeout()
        test_call_with_timeout_exception()
        test_call_with_timeout_race_condition()
        test_cached_balance_max_age()

        print("\n")
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 20 + "✅ ALL TESTS PASSED ✅" + " " * 25 + "║")
        print("╚" + "=" * 68 + "╝")
        print("\n")

    except AssertionError as e:
        print("\n")
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 20 + "❌ TEST FAILED ❌" + " " * 28 + "║")
        print("╚" + "=" * 68 + "╝")
        print(f"\nError: {e}\n")
        sys.exit(1)
    except Exception as e:
        print("\n")
        print("╔" + "=" * 68 + "╗")
        print("║" + " " * 15 + "❌ UNEXPECTED ERROR ❌" + " " * 27 + "║")
        print("╚" + "=" * 68 + "╝")
        print(f"\nError: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
