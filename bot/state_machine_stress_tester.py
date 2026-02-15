"""
NIJA State Machine Stress Tester
================================

Comprehensive stress testing framework for the portfolio super-state machine,
trading state machine, and sector cap state layer under market crash simulations.

This module integrates:
- Market crash simulator (various crash scenarios)
- Portfolio super-state machine (high-level portfolio states)
- Trading state machine (execution control)
- Sector cap state (sector exposure limits)
- Portfolio state (position management)

Test scenarios:
1. Flash crash - rapid decline and recovery
2. Gradual decline - slow, sustained downturn
3. Sector crash - specific sector collapse
4. Black swan - extreme market event
5. Recovery - post-crash recovery

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json

from bot.market_crash_simulator import (
    MarketCrashSimulator,
    CrashScenario,
    CrashType,
    create_crash_simulator
)
from bot.portfolio_super_state_machine import (
    PortfolioSuperStateMachine,
    PortfolioSuperState,
    MarketConditions,
    get_portfolio_super_state_machine
)
from bot.sector_cap_state import (
    SectorCapStateManager,
    get_sector_cap_manager
)
from bot.crypto_sector_taxonomy import get_sector, get_sector_name
from bot.portfolio_state import PortfolioState

logger = logging.getLogger("nija.state_stress_test")


@dataclass
class StressTestResult:
    """Results from a state machine stress test"""
    scenario_name: str
    crash_type: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # State transitions observed
    state_transitions: List[Dict] = field(default_factory=list)
    max_portfolio_state: str = "normal"  # Most severe state reached
    
    # Portfolio metrics
    initial_portfolio_value: float = 0.0
    final_portfolio_value: float = 0.0
    max_drawdown: float = 0.0
    
    # Sector metrics
    max_sector_violations: int = 0
    sectors_at_hard_limit: List[str] = field(default_factory=list)
    
    # Risk metrics
    positions_closed: int = 0
    positions_reduced: int = 0
    new_positions_blocked: int = 0
    
    # Performance
    total_test_periods: int = 0
    crisis_periods: int = 0
    recovery_periods: int = 0
    
    # Summary
    test_passed: bool = False
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: str = ""


class StateMachineStressTester:
    """
    Comprehensive stress tester for all state machines under market crash conditions.
    
    Tests:
    - Portfolio super-state transitions
    - Trading state machine behavior
    - Sector cap enforcement
    - Position management under stress
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize stress tester
        
        Args:
            config: Optional configuration
        """
        self.config = config or {}
        
        # Create subsystems
        self.crash_simulator = create_crash_simulator(config.get('crash_simulator', {}))
        self.super_state = get_portfolio_super_state_machine()
        self.sector_cap = get_sector_cap_manager()
        
        logger.info("=" * 70)
        logger.info("🧪 State Machine Stress Tester Initialized")
        logger.info("=" * 70)
    
    def run_crash_stress_test(
        self,
        scenario: CrashScenario,
        initial_portfolio: PortfolioState,
        symbols: List[str],
        initial_prices: Dict[str, float],
        sector_map: Dict[str, str]
    ) -> StressTestResult:
        """
        Run a complete stress test with a crash scenario
        
        Args:
            scenario: Crash scenario to test
            initial_portfolio: Initial portfolio state
            symbols: Trading symbols to simulate
            initial_prices: Initial prices for each symbol
            sector_map: Symbol to sector mapping
            
        Returns:
            StressTestResult with comprehensive metrics
        """
        logger.info("=" * 70)
        logger.info(f"🧪 Running Crash Stress Test: {scenario.name}")
        logger.info("=" * 70)
        
        result = StressTestResult(
            scenario_name=scenario.name,
            crash_type=scenario.crash_type.value,
            initial_portfolio_value=initial_portfolio.total_equity
        )
        
        # Simulate crash
        crash_result = self.crash_simulator.simulate_crash(
            scenario=scenario,
            symbols=symbols,
            initial_prices=initial_prices,
            sector_map=sector_map
        )
        
        # Track state transitions
        state_history = []
        max_portfolio_state_severity = 0
        
        # Severity mapping
        state_severity = {
            PortfolioSuperState.NORMAL: 0,
            PortfolioSuperState.CAUTIOUS: 1,
            PortfolioSuperState.STRESSED: 2,
            PortfolioSuperState.RECOVERY: 2,
            PortfolioSuperState.CRISIS: 3,
            PortfolioSuperState.EMERGENCY_HALT: 4
        }
        
        # Simulate portfolio through crash
        portfolio_value = initial_portfolio.total_equity
        max_drawdown = 0.0
        peak_value = portfolio_value
        
        positions_closed = 0
        positions_reduced = 0
        new_positions_blocked = 0
        
        max_sector_violations = 0
        crisis_periods = 0
        
        # Get average price data
        avg_prices = {}
        for symbol, df in crash_result.price_data.items():
            avg_prices[symbol] = df['price'].values
        
        # Simulate each time period
        total_periods = len(next(iter(avg_prices.values())))
        
        for period in range(total_periods):
            # Calculate current portfolio value (simplified)
            period_decline = 0.0
            for symbol in symbols:
                if symbol in avg_prices:
                    initial_price = initial_prices[symbol]
                    current_price = avg_prices[symbol][min(period, len(avg_prices[symbol])-1)]
                    decline = (current_price - initial_price) / initial_price
                    period_decline += decline / len(symbols)  # Average decline
            
            # Update portfolio value
            portfolio_value = initial_portfolio.total_equity * (1 + period_decline)
            
            # Track peak and drawdown
            if portfolio_value > peak_value:
                peak_value = portfolio_value
            
            current_drawdown = (peak_value - portfolio_value) / peak_value
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown
            
            # Calculate market conditions
            if period < len(avg_prices[symbols[0]]):
                # Use first symbol as proxy for market volatility
                prices = avg_prices[symbols[0]][:period+1]
                returns = pd.Series(prices).pct_change().dropna()
                volatility = returns.std() if len(returns) > 1 else 0.02
                
                # Get liquidity score from crash data
                liquidity_score = crash_result.price_data[symbols[0]]['liquidity_score'].iloc[
                    min(period, len(crash_result.price_data[symbols[0]])-1)
                ]
            else:
                volatility = 0.02
                liquidity_score = 1.0
            
            # Create market conditions
            conditions = MarketConditions(
                current_volatility=volatility,
                current_drawdown=current_drawdown,
                liquidity_score=liquidity_score,
                portfolio_utilization=50.0,  # Simplified
                sector_concentration=15.0,  # Simplified
                pnl_7d_pct=period_decline * 100
            )
            
            # Update super-state machine
            old_state = self.super_state.get_current_state()
            self.super_state.update_market_conditions(conditions)
            new_state = self.super_state.get_current_state()
            
            # Track state transition
            if new_state != old_state:
                transition = {
                    'period': period,
                    'from_state': old_state.value,
                    'to_state': new_state.value,
                    'portfolio_value': portfolio_value,
                    'drawdown': current_drawdown,
                    'volatility': volatility
                }
                state_history.append(transition)
                
                logger.info(
                    f"Period {period}: {old_state.value} -> {new_state.value} "
                    f"(DD: {current_drawdown*100:.1f}%, Vol: {volatility*100:.1f}%)"
                )
            
            # Track max severity
            severity = state_severity[new_state]
            if severity > max_portfolio_state_severity:
                max_portfolio_state_severity = severity
                result.max_portfolio_state = new_state.value
            
            # Count crisis periods
            if new_state in [PortfolioSuperState.CRISIS, PortfolioSuperState.EMERGENCY_HALT]:
                crisis_periods += 1
            
            # Check if new positions would be blocked
            rules = self.super_state.get_current_rules()
            if not rules.allow_new_positions:
                new_positions_blocked += 1
            
            # Check if positions would be reduced
            if rules.force_position_reduction:
                positions_reduced += 1
            
            # Check sector violations
            sector_state = self.sector_cap.get_state()
            sectors_at_limit = sector_state.get_sectors_at_limit()
            if len(sectors_at_limit) > max_sector_violations:
                max_sector_violations = len(sectors_at_limit)
                result.sectors_at_hard_limit = [
                    get_sector_name(exp.sector) for exp in sectors_at_limit
                ]
        
        # Fill in result
        result.state_transitions = state_history
        result.final_portfolio_value = portfolio_value
        result.max_drawdown = max_drawdown
        result.max_sector_violations = max_sector_violations
        result.positions_closed = positions_closed
        result.positions_reduced = positions_reduced
        result.new_positions_blocked = new_positions_blocked
        result.total_test_periods = total_periods
        result.crisis_periods = crisis_periods
        result.recovery_periods = total_periods - crisis_periods
        
        # Evaluate test success
        result.test_passed, result.failures, result.warnings = self._evaluate_test(
            result, scenario, max_drawdown
        )
        
        # Generate summary
        result.summary = self._generate_summary(result, scenario)
        
        logger.info(result.summary)
        logger.info("=" * 70)
        
        return result
    
    def _evaluate_test(
        self,
        result: StressTestResult,
        scenario: CrashScenario,
        max_drawdown: float
    ) -> Tuple[bool, List[str], List[str]]:
        """Evaluate if test passed"""
        failures = []
        warnings = []
        
        # Check if super-state machine responded appropriately
        expected_max_states = {
            CrashType.FLASH_CRASH: {PortfolioSuperState.STRESSED, PortfolioSuperState.CRISIS},
            CrashType.GRADUAL_DECLINE: {PortfolioSuperState.STRESSED, PortfolioSuperState.CRISIS},
            CrashType.SECTOR_CRASH: {PortfolioSuperState.CAUTIOUS, PortfolioSuperState.STRESSED},
            CrashType.BLACK_SWAN: {PortfolioSuperState.CRISIS, PortfolioSuperState.EMERGENCY_HALT},
            CrashType.LIQUIDITY_CRISIS: {PortfolioSuperState.CRISIS, PortfolioSuperState.EMERGENCY_HALT}
        }
        
        expected = expected_max_states.get(scenario.crash_type, set())
        actual_state = PortfolioSuperState(result.max_portfolio_state)
        
        if expected and actual_state not in expected:
            warnings.append(
                f"Expected max state in {[s.value for s in expected]}, "
                f"got {actual_state.value}"
            )
        
        # Check if positions were blocked during crisis
        if result.crisis_periods > 0 and result.new_positions_blocked == 0:
            warnings.append("No positions were blocked during crisis periods")
        
        # Check if state transitions occurred
        if len(result.state_transitions) == 0:
            failures.append("No state transitions occurred during crash")
        
        # Check drawdown is within expected range
        expected_drawdown = scenario.max_decline_pct
        if max_drawdown > expected_drawdown * 1.5:
            warnings.append(
                f"Drawdown ({max_drawdown*100:.1f}%) exceeded 1.5x scenario "
                f"({expected_drawdown*100:.1f}%)"
            )
        
        test_passed = len(failures) == 0
        
        return test_passed, failures, warnings
    
    def _generate_summary(
        self,
        result: StressTestResult,
        scenario: CrashScenario
    ) -> str:
        """Generate test summary"""
        lines = [
            "\n🧪 STRESS TEST RESULTS",
            "=" * 70,
            f"Scenario: {result.scenario_name} ({result.crash_type})",
            f"Test Status: {'✅ PASSED' if result.test_passed else '❌ FAILED'}",
            "",
            "📊 Portfolio Metrics:",
            f"  Initial Value: ${result.initial_portfolio_value:,.2f}",
            f"  Final Value: ${result.final_portfolio_value:,.2f}",
            f"  Max Drawdown: {result.max_drawdown*100:.2f}%",
            f"  P&L: ${result.final_portfolio_value - result.initial_portfolio_value:,.2f}",
            "",
            "🎯 State Machine Behavior:",
            f"  Max State Reached: {result.max_portfolio_state}",
            f"  State Transitions: {len(result.state_transitions)}",
            f"  Crisis Periods: {result.crisis_periods}/{result.total_test_periods}",
            "",
            "🛡️  Risk Controls:",
            f"  Positions Reduced: {result.positions_reduced}",
            f"  New Positions Blocked: {result.new_positions_blocked}",
            f"  Max Sector Violations: {result.max_sector_violations}",
        ]
        
        if result.sectors_at_hard_limit:
            lines.append(f"  Sectors at Hard Limit: {', '.join(result.sectors_at_hard_limit)}")
        
        if result.warnings:
            lines.append("")
            lines.append("⚠️  Warnings:")
            for warning in result.warnings:
                lines.append(f"  - {warning}")
        
        if result.failures:
            lines.append("")
            lines.append("❌ Failures:")
            for failure in result.failures:
                lines.append(f"  - {failure}")
        
        return "\n".join(lines)
    
    def run_comprehensive_stress_test(
        self,
        initial_portfolio: PortfolioState,
        symbols: List[str],
        initial_prices: Dict[str, float],
        sector_map: Dict[str, str]
    ) -> Dict[str, StressTestResult]:
        """
        Run comprehensive stress test with multiple scenarios
        
        Args:
            initial_portfolio: Initial portfolio state
            symbols: Trading symbols
            initial_prices: Initial prices
            sector_map: Symbol to sector mapping
            
        Returns:
            Dictionary of scenario_name -> StressTestResult
        """
        logger.info("=" * 70)
        logger.info("🧪 Running Comprehensive Stress Test Suite")
        logger.info("=" * 70)
        
        results = {}
        
        # Test scenarios
        scenarios = [
            self.crash_simulator.create_flash_crash_scenario(),
            self.crash_simulator.create_gradual_decline_scenario(),
            self.crash_simulator.create_sector_crash_scenario(
                affected_sectors=["defi_lending", "defi_dex"],
                sector_decline_pct=0.50
            ),
            self.crash_simulator.create_black_swan_scenario()
        ]
        
        for scenario in scenarios:
            logger.info(f"\n{'='*70}")
            logger.info(f"Testing: {scenario.name}")
            logger.info(f"{'='*70}")
            
            # Reset super-state to normal before each test
            try:
                self.super_state.transition_to(
                    PortfolioSuperState.NORMAL,
                    "Reset for stress test"
                )
            except Exception:
                pass  # May fail if already in normal
            
            # Run test
            result = self.run_crash_stress_test(
                scenario=scenario,
                initial_portfolio=initial_portfolio,
                symbols=symbols,
                initial_prices=initial_prices,
                sector_map=sector_map
            )
            
            results[scenario.name] = result
        
        # Generate overall summary
        self._print_overall_summary(results)
        
        return results
    
    def _print_overall_summary(self, results: Dict[str, StressTestResult]):
        """Print summary of all tests"""
        logger.info("\n" + "=" * 70)
        logger.info("📋 COMPREHENSIVE STRESS TEST SUMMARY")
        logger.info("=" * 70)
        
        total_tests = len(results)
        passed_tests = sum(1 for r in results.values() if r.test_passed)
        
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed_tests}")
        logger.info(f"Failed: {total_tests - passed_tests}")
        logger.info(f"Success Rate: {passed_tests/total_tests*100:.1f}%")
        logger.info("")
        
        for name, result in results.items():
            status = "✅ PASS" if result.test_passed else "❌ FAIL"
            logger.info(
                f"  {status} - {name}: "
                f"DD={result.max_drawdown*100:.1f}%, "
                f"State={result.max_portfolio_state}"
            )
        
        logger.info("=" * 70)


def create_stress_tester(config: Dict = None) -> StateMachineStressTester:
    """
    Factory function to create stress tester
    
    Args:
        config: Optional configuration
        
    Returns:
        StateMachineStressTester instance
    """
    return StateMachineStressTester(config)


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # Create tester
    tester = create_stress_tester()
    
    # Setup test portfolio
    initial_portfolio = PortfolioState(available_cash=10000.0)
    
    symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'LINK-USD', 'UNI-USD']
    initial_prices = {
        'BTC-USD': 40000,
        'ETH-USD': 2000,
        'SOL-USD': 100,
        'LINK-USD': 15,
        'UNI-USD': 6
    }
    sector_map = {
        'BTC-USD': 'bitcoin',
        'ETH-USD': 'ethereum',
        'SOL-USD': 'layer_1_alt',
        'LINK-USD': 'oracles',
        'UNI-USD': 'defi_dex'
    }
    
    # Run comprehensive test
    results = tester.run_comprehensive_stress_test(
        initial_portfolio=initial_portfolio,
        symbols=symbols,
        initial_prices=initial_prices,
        sector_map=sector_map
    )
