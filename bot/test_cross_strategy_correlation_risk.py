"""
Test Cross-Strategy Correlation Risk Control
=============================================

Validates the three approval gates (peer correlation, portfolio correlation,
concurrent-strategy cap), proportional size reduction, status reporting, and
the singleton accessor.
"""

import sys
import os

# Ensure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from bot.cross_strategy_correlation_risk import (
    CrossStrategyCorrelationRisk,
    get_cross_strategy_correlation_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(**kwargs) -> CrossStrategyCorrelationRisk:
    """Return a fresh (non-singleton) engine for isolated tests."""
    return CrossStrategyCorrelationRisk(**kwargs)


def _fill_correlated_returns(
    engine: CrossStrategyCorrelationRisk,
    strategy_a: str,
    strategy_b: str,
    n: int = 20,
    seed: int = 0,
) -> None:
    """Populate two strategies with near-perfectly correlated returns."""
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(n)
    for i in range(n):
        engine.record_return(strategy_a, float(base[i]))
        engine.record_return(strategy_b, float(base[i] + rng.normal(0, 0.01)))


def _fill_uncorrelated_returns(
    engine: CrossStrategyCorrelationRisk,
    strategy_a: str,
    strategy_b: str,
    n: int = 20,
    seed: int = 42,
) -> None:
    """Populate two strategies with uncorrelated returns."""
    rng = np.random.default_rng(seed)
    for _ in range(n):
        engine.record_return(strategy_a, float(rng.standard_normal()))
        engine.record_return(strategy_b, float(rng.standard_normal()))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gate_a_blocks_high_peer_correlation():
    """Gate A must block a new entry when peer correlation exceeds the limit."""
    print("\n" + "=" * 70)
    print("TEST 1: Gate A – High peer correlation blocks entry")
    print("=" * 70)

    engine = _make_engine(max_peer_corr=0.80, min_history=10)
    _fill_correlated_returns(engine, "RSI_9", "RSI_14", n=20)

    decision = engine.approve_entry(
        strategy="RSI_9",
        symbol="BTC-USD",
        proposed_size_usd=500.0,
        active_strategies={"RSI_14": 800.0},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Max peer corr: {decision.max_peer_corr:.4f}")
    print(f"  Reason: {decision.reason}")

    assert not decision.allowed, "Should be blocked by peer correlation gate"
    assert decision.max_peer_corr > 0.80, "max_peer_corr should exceed the threshold"
    assert "peer_corr" in decision.reason
    print("✅ Gate A (peer correlation) test PASSED")


def test_gate_a_allows_low_peer_correlation():
    """Gate A must allow an entry when peer correlation is below the limit."""
    print("\n" + "=" * 70)
    print("TEST 2: Gate A – Low peer correlation allows entry")
    print("=" * 70)

    engine = _make_engine(max_peer_corr=0.85, min_history=10)
    _fill_uncorrelated_returns(engine, "RSI_9", "MACD", n=20)

    decision = engine.approve_entry(
        strategy="RSI_9",
        symbol="ETH-USD",
        proposed_size_usd=400.0,
        active_strategies={"MACD": 600.0},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Max peer corr: {decision.max_peer_corr:.4f}")
    print(f"  Reason: {decision.reason}")

    assert decision.allowed, "Should be allowed with uncorrelated strategies"
    print("✅ Gate A (low peer correlation) test PASSED")


def test_gate_b_blocks_high_portfolio_correlation():
    """Gate B must block when average portfolio correlation is too high."""
    print("\n" + "=" * 70)
    print("TEST 3: Gate B – High portfolio correlation blocks entry")
    print("=" * 70)

    engine = _make_engine(max_portfolio_corr=0.60, max_peer_corr=0.99, min_history=10)

    # Three highly correlated strategies already active
    base_seed = np.random.default_rng(7)
    base = base_seed.standard_normal(20)
    for strat in ("A", "B", "C"):
        for val in base:
            engine.record_return(strat, float(val + np.random.normal(0, 0.005)))

    # Candidate strategy also correlated with the group
    for val in base:
        engine.record_return("D", float(val + np.random.normal(0, 0.005)))

    decision = engine.approve_entry(
        strategy="D",
        symbol="SOL-USD",
        proposed_size_usd=300.0,
        active_strategies={"A": 500.0, "B": 500.0, "C": 500.0},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Portfolio corr score: {decision.strategy_corr_score:.4f}")
    print(f"  Reason: {decision.reason}")

    assert not decision.allowed, "Should be blocked by portfolio correlation gate"
    print("✅ Gate B (portfolio correlation) test PASSED")


def test_gate_c_blocks_too_many_concurrent_strategies():
    """Gate C must block when the concurrent-strategy cap is exceeded."""
    print("\n" + "=" * 70)
    print("TEST 4: Gate C – Too many concurrent strategies blocks entry")
    print("=" * 70)

    engine = _make_engine(max_concurrent=3, max_peer_corr=0.99, max_portfolio_corr=0.99)

    # Three strategies already active (cap is 3)
    active = {"A": 300.0, "B": 300.0, "C": 300.0}

    decision = engine.approve_entry(
        strategy="D",
        symbol="ADA-USD",
        proposed_size_usd=200.0,
        active_strategies=active,
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Active peers: {decision.active_peers}")
    print(f"  Reason: {decision.reason}")

    assert not decision.allowed, "Should be blocked by concurrent strategy cap"
    assert "active_strategies" in decision.reason
    print("✅ Gate C (concurrent cap) test PASSED")


def test_size_reduction_on_elevated_correlation():
    """Approved entries with elevated (but sub-limit) correlation must be scaled down."""
    print("\n" + "=" * 70)
    print("TEST 5: Size reduction on elevated (but allowed) correlation")
    print("=" * 70)

    import collections

    # Gate threshold set to 0.95 so a ~0.60 correlation is clearly below it
    engine = _make_engine(
        max_peer_corr=0.95,
        max_portfolio_corr=0.95,
        size_reduction_slope=0.5,
        min_history=10,
    )

    # Inject moderately correlated returns (shared signal + large noise)
    rng = np.random.default_rng(42)
    shared = rng.standard_normal(30)
    noise_a = rng.standard_normal(30) * 1.5
    noise_b = rng.standard_normal(30) * 1.5
    engine._returns["RSI_9"] = collections.deque(
        [float(v) for v in (shared + noise_a)], maxlen=engine.lookback
    )
    engine._returns["RSI_14"] = collections.deque(
        [float(v) for v in (shared + noise_b)], maxlen=engine.lookback
    )
    engine._matrix_dirty = True

    decision = engine.approve_entry(
        strategy="RSI_9",
        symbol="BTC-USD",
        proposed_size_usd=1000.0,
        active_strategies={"RSI_14": 800.0},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Max peer corr: {decision.max_peer_corr:.4f}")
    print(f"  Proposed size: ${decision.proposed_size_usd:.2f}")
    print(f"  Adjusted size: ${decision.adjusted_size_usd:.2f}")
    print(f"  Reason: {decision.reason}")

    assert decision.allowed, "Should be allowed (below threshold)"
    assert decision.adjusted_size_usd < decision.proposed_size_usd, (
        "Adjusted size must be smaller when peer correlation is elevated"
    )
    print("✅ Size reduction test PASSED")


def test_no_size_reduction_when_no_peers():
    """No size reduction should occur when there are no active peers."""
    print("\n" + "=" * 70)
    print("TEST 6: No size reduction with zero active peers")
    print("=" * 70)

    engine = _make_engine()

    decision = engine.approve_entry(
        strategy="RSI_9",
        symbol="BTC-USD",
        proposed_size_usd=500.0,
        active_strategies={},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Proposed: ${decision.proposed_size_usd:.2f}")
    print(f"  Adjusted: ${decision.adjusted_size_usd:.2f}")

    assert decision.allowed
    assert decision.adjusted_size_usd == decision.proposed_size_usd
    print("✅ No-peer size preservation test PASSED")


def test_insufficient_history_passes_gate():
    """
    When there is insufficient return history, correlation cannot be estimated
    and the engine must pass the gate (fail-open to avoid blocking all trades
    at startup).
    """
    print("\n" + "=" * 70)
    print("TEST 7: Insufficient history → gate passes (fail-open)")
    print("=" * 70)

    engine = _make_engine(min_history=20)
    # Only record 5 returns – below the 20-bar minimum
    for val in [0.01, -0.02, 0.03, -0.01, 0.02]:
        engine.record_return("RSI_9", val)
        engine.record_return("RSI_14", val)

    decision = engine.approve_entry(
        strategy="RSI_9",
        symbol="BTC-USD",
        proposed_size_usd=500.0,
        active_strategies={"RSI_14": 800.0},
        portfolio_value=10_000.0,
    )

    print(f"  Allowed: {decision.allowed}")
    print(f"  Max peer corr: {decision.max_peer_corr}")
    print(f"  Reason: {decision.reason}")

    assert decision.allowed, "Should pass gate when history is insufficient"
    assert decision.max_peer_corr == 0.0
    print("✅ Insufficient history (fail-open) test PASSED")


def test_get_status():
    """get_status() must return sensible values."""
    print("\n" + "=" * 70)
    print("TEST 8: get_status() reporting")
    print("=" * 70)

    engine = _make_engine(min_history=5)
    for strat in ("A", "B"):
        for val in [0.01, 0.02, -0.01, 0.03, -0.02]:
            engine.record_return(strat, val)

    engine.open_position("A", 500.0)
    engine.open_position("B", 300.0)

    status = engine.get_status()

    print(f"  Tracked strategies: {status.num_tracked_strategies}")
    print(f"  Active strategies: {status.num_active_strategies}")
    print(f"  Portfolio corr score: {status.portfolio_corr_score:.4f}")
    print(f"  Top pairs: {status.top_pairs}")

    assert status.num_tracked_strategies == 2
    assert status.num_active_strategies == 2
    assert 0.0 <= status.portfolio_corr_score <= 1.0
    print("✅ get_status() test PASSED")


def test_close_position_removes_from_active():
    """close_position() must remove the strategy from active positions."""
    print("\n" + "=" * 70)
    print("TEST 9: close_position() removes strategy from active set")
    print("=" * 70)

    engine = _make_engine()
    engine.open_position("RSI_9", 500.0)
    engine.open_position("RSI_14", 400.0)

    assert "RSI_9" in engine._positions
    assert "RSI_14" in engine._positions

    engine.close_position("RSI_9")

    assert "RSI_9" not in engine._positions
    assert "RSI_14" in engine._positions
    print("✅ close_position() test PASSED")


def test_pair_correlation_lookup():
    """get_pair_correlation() must return a valid float after sufficient history."""
    print("\n" + "=" * 70)
    print("TEST 10: get_pair_correlation() lookup")
    print("=" * 70)

    engine = _make_engine(min_history=10)
    _fill_correlated_returns(engine, "A", "B", n=15)

    corr = engine.get_pair_correlation("A", "B")
    print(f"  Correlation A↔B: {corr:.4f}")

    assert corr is not None, "Should return a correlation value"
    assert -1.0 <= corr <= 1.0, "Correlation must be in [-1, 1]"
    assert corr > 0.90, "Correlated strategies should have high positive correlation"
    print("✅ get_pair_correlation() test PASSED")


def test_singleton_accessor():
    """get_cross_strategy_correlation_risk() must return the same instance."""
    print("\n" + "=" * 70)
    print("TEST 11: Singleton accessor")
    print("=" * 70)

    # Reset the module-level singleton for isolation
    import bot.cross_strategy_correlation_risk as mod
    mod._cscr_instance = None

    engine1 = get_cross_strategy_correlation_risk(lookback=30)
    engine2 = get_cross_strategy_correlation_risk(lookback=99)  # different kwargs ignored

    assert engine1 is engine2, "Must return the same instance"
    assert engine1.lookback == 30, "First-call kwargs must be used"

    # Restore
    mod._cscr_instance = None
    print("✅ Singleton accessor test PASSED")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("CROSS-STRATEGY CORRELATION RISK CONTROL – TEST SUITE")
    print("=" * 70)

    tests = [
        test_gate_a_blocks_high_peer_correlation,
        test_gate_a_allows_low_peer_correlation,
        test_gate_b_blocks_high_portfolio_correlation,
        test_gate_c_blocks_too_many_concurrent_strategies,
        test_size_reduction_on_elevated_correlation,
        test_no_size_reduction_when_no_peers,
        test_insufficient_history_passes_gate,
        test_get_status,
        test_close_position_removes_from_active,
        test_pair_correlation_lookup,
        test_singleton_accessor,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as exc:
            failed += 1
            print(f"\n❌ {test_fn.__name__} FAILED: {exc}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    if failed == 0:
        print(f"✅ ALL {passed} TESTS PASSED")
    else:
        print(f"❌ {failed} FAILED / {passed} PASSED")
    print("=" * 70)

    if failed:
        sys.exit(1)
