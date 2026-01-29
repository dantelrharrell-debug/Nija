"""
Test Multi-Asset Platform Core Components

This script tests the core multi-asset platform modules.
Requires the core modules to be available in Python path.

Prerequisites:
- Install all dependencies: pip install -r requirements.txt
- Ensure core/ directory is in Python path

Run with: python test_multi_asset_platform.py
"""

import sys
import logging
from decimal import Decimal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_multi_asset_router():
    """Test multi-asset router."""
    from core.multi_asset_router import MultiAssetRouter, MarketConditions, AssetClass

    logger.info("\n" + "="*60)
    logger.info("Testing Multi-Asset Router")
    logger.info("="*60)

    # Create router for INVESTOR tier
    router = MultiAssetRouter(
        user_tier="INVESTOR",
        total_capital=1000.0,
        risk_tolerance="moderate"
    )

    # Test capital allocation
    allocation = router.route_capital()
    logger.info(f"Allocation: {allocation.to_dict()}")

    # Verify allocation sums to 100%
    assert allocation.validate(), "Allocation should sum to 100%"

    # Get capital by asset class
    capital_by_asset = router.get_capital_by_asset_class(allocation)
    logger.info(f"Capital by asset class:")
    for asset_class, amount in capital_by_asset.items():
        logger.info(f"  {asset_class.value}: ${amount:.2f}")

    # Test tier constraints (INVESTOR should not have derivatives)
    assert allocation.derivatives_pct == 0.0, "INVESTOR tier should have no derivatives"

    logger.info("✅ Multi-Asset Router tests passed")
    return True


def test_asset_engines():
    """Test asset engines."""
    from core.asset_engines import create_engine

    logger.info("\n" + "="*60)
    logger.info("Testing Asset Engines")
    logger.info("="*60)

    # Create crypto engine
    crypto_engine = create_engine("crypto", 500.0, "INVESTOR")
    logger.info(f"Crypto engine created: capital=${crypto_engine.capital:.2f}")

    # Create equity engine
    equity_engine = create_engine("equity", 500.0, "INVESTOR")
    logger.info(f"Equity engine created: capital=${equity_engine.capital:.2f}")

    # Test strategy selection
    market_conditions = {
        'crypto_volatility': 65.0,
        'crypto_momentum': 30.0
    }
    strategy = crypto_engine.select_strategy(market_conditions)
    logger.info(f"Selected crypto strategy: {strategy.value}")

    logger.info("✅ Asset Engine tests passed")
    return True


def test_tiered_risk_engine():
    """Test tiered risk engine."""
    from core.tiered_risk_engine import TieredRiskEngine, RiskLevel

    logger.info("\n" + "="*60)
    logger.info("Testing Tiered Risk Engine")
    logger.info("="*60)

    # Create risk engine for INVESTOR tier
    risk_engine = TieredRiskEngine(
        user_tier="INVESTOR",
        total_capital=1000.0
    )

    # Test valid trade
    approved, risk_level, message = risk_engine.validate_trade(
        trade_size=50.0,
        current_positions=1,
        market_volatility=45.0
    )
    logger.info(f"Trade validation: approved={approved}, level={risk_level.value}, msg={message}")
    assert approved, "Valid trade should be approved"

    # Test trade too large
    approved, risk_level, message = risk_engine.validate_trade(
        trade_size=1000.0,  # Exceeds max for INVESTOR
        current_positions=0,
        market_volatility=45.0
    )
    logger.info(f"Large trade validation: approved={approved}, level={risk_level.value}, msg={message}")
    assert not approved, "Trade exceeding limit should be rejected"

    # Test risk status
    status = risk_engine.get_risk_status()
    logger.info(f"Risk status: tier={status['tier']}, capital=${status['total_capital']:.2f}")

    logger.info("✅ Tiered Risk Engine tests passed")
    return True


def test_execution_router():
    """Test execution router."""
    from core.execution_router import ExecutionRouter

    logger.info("\n" + "="*60)
    logger.info("Testing Execution Router")
    logger.info("="*60)

    router = ExecutionRouter()

    # Test order routing for different tiers
    tiers = ["STARTER", "INVESTOR", "BALLER"]
    for tier in tiers:
        order = {
            "symbol": "BTC-USD",
            "side": "buy",
            "size": 50.0
        }
        result = router.route_order(tier, order)
        logger.info(f"{tier}: priority={result['priority']}, infrastructure={result['infrastructure']}")

    # Check queue status
    queue_status = router.get_queue_status()
    logger.info(f"Queue status: {queue_status}")

    logger.info("✅ Execution Router tests passed")
    return True


def test_revenue_tracker():
    """Test revenue tracker."""
    from core.revenue_tracker import RevenueTracker, SubscriptionTier, RevenueType

    logger.info("\n" + "="*60)
    logger.info("Testing Revenue Tracker")
    logger.info("="*60)

    tracker = RevenueTracker()

    # Record subscription
    event = tracker.record_subscription(
        user_id="test_user_1",
        tier=SubscriptionTier.INVESTOR,
        is_annual=False
    )
    logger.info(f"Subscription recorded: ${event.amount}")

    # Record performance fee
    event = tracker.record_performance_fee(
        user_id="test_user_1",
        profit=100.0,
        current_equity=1100.0
    )
    if event:
        logger.info(f"Performance fee recorded: ${event.amount}")

    # Record copy trading fee
    platform_event, master_event = tracker.record_copy_trading_fee(
        master_user_id="master_1",
        follower_user_id="follower_1",
        follower_profit=100.0
    )
    logger.info(f"Copy trading fees - Platform: ${platform_event.amount}, Master: ${master_event.amount}")

    # Get revenue summary
    summary = tracker.get_revenue_summary()
    logger.info(f"Revenue summary:")
    logger.info(f"  Total: ${summary['total_revenue']:.2f}")
    logger.info(f"  MRR: ${summary['mrr']:.2f}")
    logger.info(f"  ARR: ${summary['arr']:.2f}")
    logger.info(f"  By type: {summary['revenue_by_type']}")

    logger.info("✅ Revenue Tracker tests passed")
    return True


def test_equity_broker():
    """Test equity broker integration (without actual API calls)."""
    from core.equity_broker_integration import AlpacaBroker

    logger.info("\n" + "="*60)
    logger.info("Testing Equity Broker Integration")
    logger.info("="*60)

    # Create broker (won't authenticate without credentials)
    broker = AlpacaBroker(paper_trading=True)
    logger.info(f"Alpaca broker created: paper_trading={broker.paper_trading}")

    # Just verify the broker was created
    assert broker.paper_trading == True
    assert broker.authenticated == False

    logger.info("✅ Equity Broker tests passed (no API calls)")
    return True


def main():
    """Run all tests."""
    logger.info("\n" + "="*60)
    logger.info("NIJA Multi-Asset Platform - Core Component Tests")
    logger.info("="*60)

    tests = [
        ("Multi-Asset Router", test_multi_asset_router),
        ("Asset Engines", test_asset_engines),
        ("Tiered Risk Engine", test_tiered_risk_engine),
        ("Execution Router", test_execution_router),
        ("Revenue Tracker", test_revenue_tracker),
        ("Equity Broker", test_equity_broker),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            logger.error(f"❌ {test_name} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    logger.info("\n" + "="*60)
    logger.info("Test Summary")
    logger.info("="*60)
    logger.info(f"Passed: {passed}/{len(tests)}")
    logger.info(f"Failed: {failed}/{len(tests)}")

    if failed == 0:
        logger.info("\n✅ All tests passed!")
        return 0
    else:
        logger.error(f"\n❌ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
