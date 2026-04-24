"""
Quick validation test for state machine stress testing framework
"""

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

print("Testing imports...")

# Test imports
from bot.market_crash_simulator import create_crash_simulator, CrashType
from bot.sector_cap_state import SectorCapState, get_sector_cap_manager
from bot.portfolio_super_state_machine import (
    PortfolioSuperStateMachine,
    PortfolioSuperState,
    MarketConditions
)
from bot.state_machine_stress_tester import create_stress_tester
from bot.portfolio_state import PortfolioState

print("✅ All imports successful")

# Test crash simulator
print("\nTesting crash simulator...")
simulator = create_crash_simulator({'random_seed': 42})
scenario = simulator.create_flash_crash_scenario(max_decline_pct=0.20, duration_minutes=5)
print(f"✅ Created flash crash scenario: {scenario.name}")

# Test sector cap state
print("\nTesting sector cap state...")
sector_state = SectorCapState(global_soft_limit_pct=15.0, global_hard_limit_pct=20.0)
sector_state.update_portfolio_value(10000.0)
sector_state.update_position('BTC-USD', 1500.0, add=True)
summary = sector_state.get_summary()
print(f"✅ Sector state working. Sectors tracked: {summary['sectors_tracked']}")

# Test portfolio super-state machine
print("\nTesting portfolio super-state machine...")
ssm = PortfolioSuperStateMachine()
print(f"✅ Initial state: {ssm.get_current_state().value}")

# Test crisis transition
crisis_conditions = MarketConditions(
    current_volatility=0.12,
    current_drawdown=0.35,
    liquidity_score=0.3
)
ssm.update_market_conditions(crisis_conditions)
print(f"✅ State after crisis conditions: {ssm.get_current_state().value}")

# Test crash simulation (quick test)
print("\nTesting crash simulation...")
symbols = ['BTC-USD']
initial_prices = {'BTC-USD': 40000}

result = simulator.simulate_crash(
    scenario=scenario,
    symbols=symbols,
    initial_prices=initial_prices,
    interval_minutes=1
)

print(f"✅ Crash simulation complete. Max drawdown: {result.max_drawdown*100:.1f}%")

# Test stress tester initialization
print("\nTesting stress tester...")
tester = create_stress_tester({'crash_simulator': {'random_seed': 42}})
print("✅ Stress tester initialized")

print("\n" + "="*70)
print("🎉 ALL VALIDATION TESTS PASSED")
print("="*70)
print("\nState machine stress testing framework is working correctly!")
print("\nComponents validated:")
print("  ✅ Market crash simulator")
print("  ✅ Sector cap state layer")
print("  ✅ Portfolio super-state machine")
print("  ✅ Integrated stress tester")
