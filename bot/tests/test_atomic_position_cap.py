"""
Test that the position cap check in PositionArchitecture is atomic.

Two threads that simultaneously pass can_open_position must not both succeed
in registering a position when the cap would be exceeded by the second one.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time


def test_concurrent_open_respects_cap():
    """
    Two threads race to open positions when only one slot remains.
    Exactly one registration must succeed; the second must be blocked by the
    atomic re-check inside register_position.
    """
    print("=" * 70)
    print("TEST: Atomic position cap check prevents concurrent cap bypass")
    print("=" * 70)

    from position_architecture import PositionArchitecture

    arch = PositionArchitecture(
        tier_name="TEST",
        account_balance=10_000.0,
        max_positions=3,
        data_dir="/tmp/test_atomic_cap",
    )

    # Pre-fill 2 of the 3 allowed positions
    arch.register_position("BTC-USD", 500.0, 50_000.0, "LONG", 49_000.0)
    arch.register_position("ETH-USD", 300.0, 3_000.0, "LONG", 2_900.0)
    assert len(arch.positions) == 2, "Setup failed"

    results = []
    barrier = threading.Barrier(2)  # synchronise both threads to maximise race

    def try_open(symbol):
        # Both threads check the cap at roughly the same time
        can_open, reason = arch.can_open_position(symbol, 200.0)
        barrier.wait()  # ensure both have read before either writes
        if can_open:
            arch.register_position(symbol, 200.0, 100.0, "LONG", 90.0)
        results.append((symbol, can_open, reason))

    thread1 = threading.Thread(target=try_open, args=("SOL-USD",))
    thread2 = threading.Thread(target=try_open, args=("AVAX-USD",))

    thread1.start()
    thread2.start()
    thread1.join()
    thread2.join()

    final_count = len(arch.positions)
    print(f"Results: {results}")
    print(f"Final position count: {final_count} (max allowed: 3)")

    assert final_count <= 3, (
        f"Cap violated! {final_count} positions open (max 3). "
        "Atomic lock is not working."
    )

    # Exactly one of the two new symbols should have been registered
    new_symbols = [s for s in arch.positions if s not in ("BTC-USD", "ETH-USD")]
    assert len(new_symbols) == 1, (
        f"Expected exactly 1 new position; got {new_symbols}"
    )

    print(f"✅ PASSED: Only 1 of 2 concurrent opens succeeded → cap enforced atomically")
    print()
    return True


def test_can_open_position_is_threadsafe():
    """
    Rapid concurrent calls to can_open_position should never report True
    more times than positions are actually available.
    """
    print("=" * 70)
    print("TEST: can_open_position returns consistent results under concurrency")
    print("=" * 70)

    from position_architecture import PositionArchitecture

    arch = PositionArchitecture(
        tier_name="TEST",
        account_balance=10_000.0,
        max_positions=2,
        data_dir="/tmp/test_atomic_cap2",
    )

    # Fill to capacity
    arch.register_position("BTC-USD", 500.0, 50_000.0, "LONG", 49_000.0)
    arch.register_position("ETH-USD", 300.0, 3_000.0, "LONG", 2_900.0)
    assert len(arch.positions) == 2

    approvals = []

    def check():
        ok, _ = arch.can_open_position("SOL-USD", 100.0)
        if ok:
            approvals.append(True)

    threads = [threading.Thread(target=check) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(approvals) == 0, (
        f"cap already reached but can_open_position approved {len(approvals)} "
        "concurrent requests"
    )
    print("✅ PASSED: can_open_position correctly rejects all calls when at capacity")
    print()
    return True


def run_all_tests():
    print("\n")
    print("=" * 70)
    print("ATOMIC POSITION CAP TESTS")
    print("=" * 70)
    print()

    try:
        test_concurrent_open_respects_cap()
        test_can_open_position_is_threadsafe()

        print("=" * 70)
        print("✅ ALL ATOMIC CAP TESTS PASSED")
        print("=" * 70)
        return True

    except AssertionError as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
