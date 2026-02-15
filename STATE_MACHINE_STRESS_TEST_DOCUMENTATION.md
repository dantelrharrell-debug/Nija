# State Machine Stress Testing Framework

## Overview

This implementation provides a comprehensive framework for stress-testing NIJA's trading state machines under realistic market crash scenarios. The system integrates three layers of state management:

1. **Market Crash Simulator** - Generates realistic crash scenarios
2. **Sector Cap State Layer** - Enforces sector diversification limits
3. **Portfolio Super-State Machine** - Coordinates high-level portfolio states

## Components

### 1. Market Crash Simulator (`bot/market_crash_simulator.py`)

Simulates various types of market crashes with realistic market conditions:

**Crash Types:**
- **Flash Crash**: Sudden 30% decline in 15 minutes, quick recovery
- **Gradual Decline**: Slow 40% decline over 4 hours
- **Sector Crash**: Specific sectors decline 50% while market declines 15%
- **Black Swan**: Extreme 60% decline with 15x volatility increase
- **Liquidity Crisis**: 90% liquidity reduction, 25x spread expansion

**Features:**
- Realistic price path generation
- Volatility simulation (5-15x normal levels)
- Liquidity deterioration (up to 90% reduction)
- Spread expansion (up to 25x normal spreads)
- Partial fill simulation (up to 85% probability in crisis)

**Usage:**
```python
from bot.market_crash_simulator import create_crash_simulator

simulator = create_crash_simulator()
scenario = simulator.create_flash_crash_scenario(max_decline_pct=0.30)

result = simulator.simulate_crash(
    scenario=scenario,
    symbols=['BTC-USD', 'ETH-USD'],
    initial_prices={'BTC-USD': 40000, 'ETH-USD': 2000}
)

print(f"Max Drawdown: {result.max_drawdown * 100:.1f}%")
```

### 2. Sector Cap State Layer (`bot/sector_cap_state.py`)

Enforces sector-level diversification limits across 19 cryptocurrency sectors:

**Sector Limits:**
- **Soft Limit**: 15% (warning)
- **Hard Limit**: 20% (blocks new positions)

**Features:**
- Real-time sector exposure tracking
- Position validation before adding
- Correlated sector monitoring
- Health status reporting (healthy/warning/critical)

**Sectors Tracked:**
- Bitcoin, Ethereum, Stablecoins
- Layer-1 (Alt & EVM), Layer-2
- DeFi (Lending, DEX, Derivatives, Staking)
- Exchange Tokens, Oracles
- Gaming & Metaverse, NFT Ecosystem
- Meme Coins, AI Tokens, Privacy Coins

**Usage:**
```python
from bot.sector_cap_state import SectorCapState

state = SectorCapState(
    global_soft_limit_pct=15.0,
    global_hard_limit_pct=20.0
)

state.update_portfolio_value(10000.0)
can_add, reason = state.can_add_position('BTC-USD', 1500.0)

if can_add:
    state.update_position('BTC-USD', 1500.0, add=True)
```

### 3. Portfolio Super-State Machine (`bot/portfolio_super_state_machine.py`)

High-level state machine that coordinates all subsystems based on market conditions:

**Portfolio States:**

| State | Trigger Conditions | Max Position | Utilization | New Positions | Risk Multiplier |
|-------|-------------------|--------------|-------------|---------------|-----------------|
| **NORMAL** | Vol < 3%, DD < 5% | 15% | 85% | ✅ Allowed | 1.0x |
| **CAUTIOUS** | Vol 3-5%, DD 5-15% | 12% | 75% | ✅ Allowed | 0.8x |
| **STRESSED** | Vol 5-10%, DD 15-30% | 8% | 60% | ❌ Blocked | 0.5x |
| **CRISIS** | Vol > 10%, DD > 30% | 5% | 30% | ❌ Blocked | 0.25x |
| **RECOVERY** | From crisis, improving | 10% | 70% | ✅ Allowed | 0.7x |
| **EMERGENCY_HALT** | Manual intervention | 0% | 0% | ❌ Blocked | 0.0x |

**State Transition Rules:**
- Automatic transitions based on market conditions
- Validates transitions (no direct CRISIS → NORMAL)
- Persists state to disk
- Integrates with trading state machine and sector caps

**Usage:**
```python
from bot.portfolio_super_state_machine import (
    PortfolioSuperStateMachine,
    MarketConditions
)

ssm = PortfolioSuperStateMachine()

# Update market conditions
conditions = MarketConditions(
    current_volatility=0.12,
    current_drawdown=0.35,
    liquidity_score=0.3
)

ssm.update_market_conditions(conditions)
print(f"Current state: {ssm.get_current_state().value}")

# Check if can open position
can_open, reason = ssm.can_open_new_position('BTC-USD', 1000, 10000)
```

### 4. Integrated Stress Tester (`bot/state_machine_stress_tester.py`)

Comprehensive testing framework that combines all components:

**Test Scenarios:**
- Flash crash stress test
- Gradual decline stress test
- Sector-specific crash test
- Black swan event test
- Full comprehensive test suite

**Validation Checks:**
- State transitions occur appropriately
- Positions blocked during crisis
- Sector limits enforced
- Drawdown within expected ranges

**Usage:**
```python
from bot.state_machine_stress_tester import create_stress_tester
from bot.portfolio_state import PortfolioState

tester = create_stress_tester()
portfolio = PortfolioState(available_cash=10000.0)

# Run comprehensive test
results = tester.run_comprehensive_stress_test(
    initial_portfolio=portfolio,
    symbols=['BTC-USD', 'ETH-USD', 'SOL-USD'],
    initial_prices={'BTC-USD': 40000, 'ETH-USD': 2000, 'SOL-USD': 100},
    sector_map={'BTC-USD': 'bitcoin', 'ETH-USD': 'ethereum', 'SOL-USD': 'layer_1_alt'}
)

for name, result in results.items():
    print(f"{name}: {'PASS' if result.test_passed else 'FAIL'}")
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                  Portfolio Super-State Machine                   │
│  States: NORMAL → CAUTIOUS → STRESSED → CRISIS → RECOVERY      │
│  Controls: Position sizing, utilization, new position approval  │
└──────────────────┬────────────────┬────────────────┬────────────┘
                   │                │                │
         ┌─────────▼──────┐  ┌──────▼───────┐  ┌───▼────────────┐
         │  Trading State │  │  Sector Cap  │  │  Portfolio     │
         │    Machine     │  │     State    │  │     State      │
         │ (OFF/DRY_RUN/  │  │ (15%/20%     │  │  (Positions,   │
         │  LIVE_ACTIVE)  │  │   limits)    │  │   Cash, P&L)   │
         └────────────────┘  └──────────────┘  └────────────────┘
                   │                │                │
                   └────────────────┴────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │  Market Crash       │
                        │    Simulator        │
                        │ (Flash, Gradual,    │
                        │  Sector, BlackSwan) │
                        └─────────────────────┘
```

## Testing

### Unit Tests (`test_state_machine_stress.py`)

```bash
python test_state_machine_stress.py
```

Tests cover:
- Market crash scenario creation
- Crash simulation execution
- Sector cap limit enforcement
- Portfolio super-state transitions
- Integrated stress testing

### Quick Demo (`demo_quick.py`)

```bash
python demo_quick.py
```

Demonstrates:
- Crash simulator
- Sector cap enforcement
- Super-state transitions
- Basic crash simulation

## Files Created

- `bot/market_crash_simulator.py` (646 lines) - Crash simulation engine
- `bot/sector_cap_state.py` (550 lines) - Sector cap enforcement
- `bot/portfolio_super_state_machine.py` (641 lines) - Super-state machine
- `bot/state_machine_stress_tester.py` (545 lines) - Integrated testing
- `test_state_machine_stress.py` (358 lines) - Unit tests
- `demo_quick.py` (109 lines) - Quick demonstration

**Total**: ~2,849 lines of production code + tests

## Key Features

✅ **Realistic Market Crash Simulation**
- 5 different crash types
- Realistic price paths with volatility
- Liquidity and spread modeling
- Market microstructure effects

✅ **Sector Diversification**
- 19 cryptocurrency sectors tracked
- Soft (15%) and hard (20%) limits
- Correlated sector monitoring
- Real-time exposure validation

✅ **Portfolio Super-State Management**
- 6 portfolio states with progressive controls
- Automatic state transitions
- State-specific risk rules
- Coordinates all subsystems

✅ **Comprehensive Stress Testing**
- Multiple crash scenarios
- State transition validation
- Risk control verification
- Pass/fail criteria

## Production Readiness

The system is designed for production use with:
- Thread-safe state management
- State persistence to disk
- Comprehensive logging
- Error handling
- Singleton patterns for global state
- Type hints for clarity
- Extensive documentation

## Next Steps

1. Run full integration tests
2. Add performance benchmarks
3. Create monitoring dashboard
4. Document edge cases
5. Add backtesting integration
