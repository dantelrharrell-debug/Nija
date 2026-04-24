"""
Quick Demo: Portfolio Super-State Machine
==========================================

Fast demonstration of key features without full stress test.
"""

import logging
logging.basicConfig(level=logging.WARNING)  # Reduce noise

print("=" * 70)
print("NIJA Portfolio Super-State Machine - Quick Demo")
print("=" * 70)

# Test 1: Crash Simulator
print("\n1️⃣  Market Crash Simulator")
print("-" * 70)
from bot.market_crash_simulator import create_crash_simulator

simulator = create_crash_simulator()
scenario = simulator.create_flash_crash_scenario(max_decline_pct=0.30)
print(f"✅ Created scenario: {scenario.name}")
print(f"   Type: {scenario.crash_type.value}")
print(f"   Max decline: {scenario.max_decline_pct * 100:.0f}%")
print(f"   Duration: {scenario.duration_minutes} minutes")

# Test 2: Sector Cap State
print("\n2️⃣  Sector Cap State Layer")
print("-" * 70)
from bot.sector_cap_state import SectorCapState

state = SectorCapState(global_soft_limit_pct=15.0, global_hard_limit_pct=20.0)
state.update_portfolio_value(10000.0)
state.update_position('BTC-USD', 1500.0, add=True)

exposure = list(state.sector_exposures.values())[0]
print(f"✅ Portfolio value: $10,000")
print(f"   Bitcoin exposure: ${exposure.total_value:,.0f} ({exposure.exposure_pct:.1f}%)")
print(f"   Status: {exposure.status.value}")

# Try to add more Bitcoin
can_add, reason = state.can_add_position('BTC-USD', 1000.0)
print(f"   Can add more BTC? {can_add}")
if not can_add:
    print(f"   Reason: {reason}")

# Test 3: Portfolio Super-State Machine  
print("\n3️⃣  Portfolio Super-State Machine")
print("-" * 70)
from bot.portfolio_super_state_machine import (
    PortfolioSuperStateMachine,
    MarketConditions
)

ssm = PortfolioSuperStateMachine()
print(f"✅ Initial state: {ssm.get_current_state().value}")

# Test crisis transition
crisis_conditions = MarketConditions(
    current_volatility=0.15,
    current_drawdown=0.40,
    liquidity_score=0.2
)

print("\n   Simulating market crisis...")
print(f"   - Volatility: {crisis_conditions.current_volatility * 100:.0f}%")
print(f"   - Drawdown: {crisis_conditions.current_drawdown * 100:.0f}%")
print(f"   - Liquidity: {crisis_conditions.liquidity_score:.1f}")

ssm.update_market_conditions(crisis_conditions)
new_state = ssm.get_current_state()
rules = ssm.get_current_rules()

print(f"\n   → Transitioned to: {new_state.value.upper()}")
print(f"   → Max position size: {rules.max_position_size_pct}%")
print(f"   → New positions: {'Allowed' if rules.allow_new_positions else 'BLOCKED'}")
print(f"   → Position reduction: {'Required' if rules.force_position_reduction else 'Not required'}")

# Test 4: Simple crash simulation
print("\n4️⃣  Quick Crash Simulation")
print("-" * 70)

symbols = ['BTC-USD']
initial_prices = {'BTC-USD': 40000}

print(f"   Simulating flash crash for BTC-USD...")
result = simulator.simulate_crash(
    scenario=scenario,
    symbols=symbols,
    initial_prices=initial_prices,
    interval_minutes=5  # Longer intervals for faster execution
)

print(f"✅ Crash simulation complete:")
print(f"   - Max drawdown: {result.max_drawdown * 100:.1f}%")
print(f"   - Max volatility: {result.max_volatility * 100:.1f}%")
print(f"   - Avg spread: {result.avg_spread_expansion:.0f} bps")
print(f"   - Liquidity score: {result.liquidity_score:.2f}")

# Summary
print("\n" + "=" * 70)
print("🎉 QUICK DEMO COMPLETE")
print("=" * 70)
print("\n✅ All components working correctly:")
print("   • Market crash simulator")
print("   • Sector cap state layer")
print("   • Portfolio super-state machine")
print("   • Integrated crash simulation")
print("\n" + "=" * 70)
