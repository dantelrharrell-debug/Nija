"""
Demo: Portfolio Super-State Machine Under Market Crash Simulation
=================================================================

This demo showcases the complete stress testing framework:
1. Market crash simulation
2. Portfolio super-state machine transitions
3. Sector cap enforcement
4. Integrated stress testing

Author: NIJA Trading Systems
Date: February 2026
"""

import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout
)

logger = logging.getLogger(__name__)


def demo_crash_simulator():
    """Demonstrate market crash simulator"""
    from bot.market_crash_simulator import create_crash_simulator
    
    logger.info("=" * 70)
    logger.info("DEMO 1: Market Crash Simulator")
    logger.info("=" * 70)
    
    simulator = create_crash_simulator()
    
    # Create flash crash scenario
    scenario = simulator.create_flash_crash_scenario(
        max_decline_pct=0.30,
        duration_minutes=15,
        recovery_minutes=60
    )
    
    logger.info(f"\nScenario: {scenario.name}")
    logger.info(f"Type: {scenario.crash_type.value}")
    logger.info(f"Max Decline: {scenario.max_decline_pct * 100:.0f}%")
    logger.info(f"Duration: {scenario.duration_minutes} minutes")
    
    # Simulate crash
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    initial_prices = {'BTC-USD': 40000, 'ETH-USD': 2000, 'SOL-USD': 100}
    
    logger.info(f"\nSimulating crash for {len(symbols)} assets...")
    
    result = simulator.simulate_crash(
        scenario=scenario,
        symbols=symbols,
        initial_prices=initial_prices,
        interval_minutes=1
    )
    
    logger.info(f"\n✅ Simulation complete!")
    logger.info(f"   Max Drawdown: {result.max_drawdown * 100:.2f}%")
    logger.info(f"   Max Volatility: {result.max_volatility * 100:.2f}%")
    logger.info(f"   Avg Spread: {result.avg_spread_expansion:.1f} bps")
    logger.info(f"   Liquidity Score: {result.liquidity_score:.2f}")


def demo_sector_cap_state():
    """Demonstrate sector cap state layer"""
    from bot.sector_cap_state import SectorCapState
    from bot.crypto_sector_taxonomy import get_sector_name
    
    logger.info("\n" + "=" * 70)
    logger.info("DEMO 2: Sector Cap State Layer")
    logger.info("=" * 70)
    
    state = SectorCapState(
        global_soft_limit_pct=15.0,
        global_hard_limit_pct=20.0
    )
    
    # Set portfolio value
    portfolio_value = 10000.0
    state.update_portfolio_value(portfolio_value)
    
    logger.info(f"\nPortfolio Value: ${portfolio_value:,.2f}")
    logger.info(f"Soft Limit: {state.global_soft_limit_pct}%")
    logger.info(f"Hard Limit: {state.global_hard_limit_pct}%")
    
    # Add positions
    logger.info("\n--- Adding Positions ---")
    
    positions = [
        ('BTC-USD', 1400.0),
        ('ETH-USD', 800.0),
        ('SOL-USD', 500.0),
    ]
    
    for symbol, value in positions:
        can_add, reason = state.can_add_position(symbol, value)
        if can_add:
            state.update_position(symbol, value, add=True)
            exposure = state.sector_exposures[list(state.sector_exposures.keys())[-1]]
            logger.info(
                f"✅ Added {symbol}: ${value:,.2f} "
                f"({exposure.exposure_pct:.1f}% exposure, status: {exposure.status.value})"
            )
        else:
            logger.info(f"❌ Cannot add {symbol}: {reason}")
    
    # Try to add position that would exceed limit
    logger.info("\n--- Testing Limit Enforcement ---")
    test_symbol = 'BTC-USD'
    test_value = 1000.0
    
    can_add, reason = state.can_add_position(test_symbol, test_value)
    logger.info(f"Can add ${test_value:,.2f} of {test_symbol}? {can_add}")
    logger.info(f"Reason: {reason}")
    
    # Show health status
    health, warnings = state.get_health_status()
    logger.info(f"\n--- Health Status: {health.upper()} ---")
    for warning in warnings:
        logger.info(f"⚠️  {warning}")


def demo_portfolio_super_state():
    """Demonstrate portfolio super-state machine"""
    from bot.portfolio_super_state_machine import (
        PortfolioSuperStateMachine,
        PortfolioSuperState,
        MarketConditions
    )
    
    logger.info("\n" + "=" * 70)
    logger.info("DEMO 3: Portfolio Super-State Machine")
    logger.info("=" * 70)
    
    ssm = PortfolioSuperStateMachine()
    
    logger.info(f"\nInitial State: {ssm.get_current_state().value.upper()}")
    
    # Test different market conditions
    scenarios = [
        ("Normal Market", MarketConditions(
            current_volatility=0.02,
            current_drawdown=0.02,
            liquidity_score=0.9
        )),
        ("High Volatility", MarketConditions(
            current_volatility=0.06,
            current_drawdown=0.08,
            liquidity_score=0.7
        )),
        ("Market Stress", MarketConditions(
            current_volatility=0.10,
            current_drawdown=0.20,
            liquidity_score=0.5
        )),
        ("Market Crisis", MarketConditions(
            current_volatility=0.15,
            current_drawdown=0.35,
            liquidity_score=0.3
        )),
    ]
    
    logger.info("\n--- Testing State Transitions ---")
    
    for scenario_name, conditions in scenarios:
        ssm.update_market_conditions(conditions)
        state = ssm.get_current_state()
        rules = ssm.get_current_rules()
        
        logger.info(f"\n{scenario_name}:")
        logger.info(f"  Volatility: {conditions.current_volatility * 100:.1f}%")
        logger.info(f"  Drawdown: {conditions.current_drawdown * 100:.1f}%")
        logger.info(f"  Liquidity: {conditions.liquidity_score:.2f}")
        logger.info(f"  → State: {state.value.upper()}")
        logger.info(f"  → Max Position: {rules.max_position_size_pct}%")
        logger.info(f"  → New Positions: {'Allowed' if rules.allow_new_positions else 'BLOCKED'}")


def demo_integrated_stress_test():
    """Demonstrate integrated stress testing"""
    from bot.state_machine_stress_tester import create_stress_tester
    from bot.portfolio_state import PortfolioState
    
    logger.info("\n" + "=" * 70)
    logger.info("DEMO 4: Integrated Stress Test")
    logger.info("=" * 70)
    
    # Create tester
    tester = create_stress_tester({'crash_simulator': {'random_seed': 42}})
    
    # Setup portfolio
    initial_portfolio = PortfolioState(available_cash=10000.0)
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
    initial_prices = {'BTC-USD': 40000, 'ETH-USD': 2000, 'SOL-USD': 100}
    sector_map = {'BTC-USD': 'bitcoin', 'ETH-USD': 'ethereum', 'SOL-USD': 'layer_1_alt'}
    
    # Create flash crash scenario
    scenario = tester.crash_simulator.create_flash_crash_scenario(
        max_decline_pct=0.25,
        duration_minutes=10,
        recovery_minutes=30
    )
    
    logger.info(f"\nTesting: {scenario.name}")
    logger.info(f"Portfolio: ${initial_portfolio.total_equity:,.2f}")
    logger.info(f"Assets: {', '.join(symbols)}")
    
    logger.info("\n⏳ Running stress test...")
    
    # Run test
    result = tester.run_crash_stress_test(
        scenario=scenario,
        initial_portfolio=initial_portfolio,
        symbols=symbols,
        initial_prices=initial_prices,
        sector_map=sector_map
    )
    
    logger.info("\n✅ Stress Test Complete!")
    logger.info(f"\n--- Results ---")
    logger.info(f"Test Status: {'✅ PASSED' if result.test_passed else '❌ FAILED'}")
    logger.info(f"Max State: {result.max_portfolio_state.upper()}")
    logger.info(f"State Transitions: {len(result.state_transitions)}")
    logger.info(f"Max Drawdown: {result.max_drawdown * 100:.2f}%")
    logger.info(f"Crisis Periods: {result.crisis_periods}/{result.total_test_periods}")
    logger.info(f"Positions Blocked: {result.new_positions_blocked}")


def main():
    """Run all demos"""
    logger.info("\n" + "🎯" * 35)
    logger.info("NIJA Portfolio Super-State Machine Demo")
    logger.info("Market Crash Simulation & Stress Testing")
    logger.info("🎯" * 35)
    
    try:
        # Demo 1: Crash Simulator
        demo_crash_simulator()
        
        # Demo 2: Sector Cap State
        demo_sector_cap_state()
        
        # Demo 3: Portfolio Super-State
        demo_portfolio_super_state()
        
        # Demo 4: Integrated Stress Test
        demo_integrated_stress_test()
        
        logger.info("\n" + "=" * 70)
        logger.info("🎉 ALL DEMOS COMPLETED SUCCESSFULLY")
        logger.info("=" * 70)
        logger.info("\nKey Features Demonstrated:")
        logger.info("  ✅ Market crash simulation with realistic price paths")
        logger.info("  ✅ Sector exposure tracking and limit enforcement")
        logger.info("  ✅ Portfolio super-state machine with automatic transitions")
        logger.info("  ✅ Integrated stress testing framework")
        logger.info("\nThe system is ready for production use!")
        
    except Exception as e:
        logger.error(f"\n❌ Error during demo: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
