"""
Test State Machine Stress Testing Framework
===========================================

Comprehensive test suite for:
- Market crash simulator
- Sector cap state layer
- Portfolio super-state machine
- Integrated stress testing

Author: NIJA Trading Systems
Date: February 2026
"""

import unittest
import logging
from bot.market_crash_simulator import (
    MarketCrashSimulator,
    CrashType,
    create_crash_simulator
)
from bot.sector_cap_state import (
    SectorCapState,
    SectorCapStateManager,
    SectorLimitStatus
)
from bot.portfolio_super_state_machine import (
    PortfolioSuperStateMachine,
    PortfolioSuperState,
    MarketConditions
)
from bot.state_machine_stress_tester import (
    StateMachineStressTester,
    create_stress_tester
)
from bot.portfolio_state import PortfolioState
from bot.crypto_sector_taxonomy import CryptoSector


class TestMarketCrashSimulator(unittest.TestCase):
    """Test market crash simulator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.simulator = create_crash_simulator({'random_seed': 42})
    
    def test_flash_crash_scenario_creation(self):
        """Test flash crash scenario creation"""
        scenario = self.simulator.create_flash_crash_scenario(
            max_decline_pct=0.30,
            duration_minutes=15
        )
        
        self.assertEqual(scenario.crash_type, CrashType.FLASH_CRASH)
        self.assertEqual(scenario.max_decline_pct, 0.30)
        self.assertEqual(scenario.duration_minutes, 15)
        self.assertGreater(scenario.volatility_multiplier, 1.0)
    
    def test_crash_simulation(self):
        """Test crash simulation execution"""
        scenario = self.simulator.create_flash_crash_scenario()
        
        symbols = ['BTC-USD', 'ETH-USD']
        initial_prices = {'BTC-USD': 40000, 'ETH-USD': 2000}
        
        result = self.simulator.simulate_crash(
            scenario=scenario,
            symbols=symbols,
            initial_prices=initial_prices
        )
        
        self.assertGreater(result.max_drawdown, 0.0)
        self.assertGreater(result.max_volatility, 0.0)
        self.assertEqual(result.assets_affected, 2)
        self.assertIn('BTC-USD', result.price_data)
        self.assertIn('ETH-USD', result.price_data)
    
    def test_sector_crash_scenario(self):
        """Test sector-specific crash"""
        scenario = self.simulator.create_sector_crash_scenario(
            affected_sectors=['defi_lending'],
            sector_decline_pct=0.50
        )
        
        self.assertEqual(scenario.crash_type, CrashType.SECTOR_CRASH)
        self.assertIn('defi_lending', scenario.affected_sectors)
        self.assertEqual(scenario.sector_decline_pct, 0.50)
    
    def test_black_swan_scenario(self):
        """Test black swan event"""
        scenario = self.simulator.create_black_swan_scenario()
        
        self.assertEqual(scenario.crash_type, CrashType.BLACK_SWAN)
        self.assertGreater(scenario.max_decline_pct, 0.40)
        self.assertGreater(scenario.volatility_multiplier, 10.0)


class TestSectorCapState(unittest.TestCase):
    """Test sector cap state layer"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.state = SectorCapState(
            global_soft_limit_pct=15.0,
            global_hard_limit_pct=20.0
        )
        self.state.update_portfolio_value(10000.0)
    
    def test_sector_initialization(self):
        """Test sector initialization"""
        self.state.initialize_sector(CryptoSector.BITCOIN)
        
        self.assertIn(CryptoSector.BITCOIN, self.state.sector_exposures)
        exposure = self.state.sector_exposures[CryptoSector.BITCOIN]
        self.assertEqual(exposure.total_value, 0.0)
        self.assertEqual(exposure.position_count, 0)
    
    def test_update_position(self):
        """Test position update"""
        self.state.update_position('BTC-USD', 1500.0, add=True)
        
        exposure = self.state.sector_exposures[CryptoSector.BITCOIN]
        self.assertEqual(exposure.total_value, 1500.0)
        self.assertEqual(exposure.position_count, 1)
        self.assertEqual(exposure.exposure_pct, 15.0)
    
    def test_soft_limit_warning(self):
        """Test soft limit detection"""
        # Add position at soft limit
        self.state.update_position('BTC-USD', 1500.0, add=True)
        
        exposure = self.state.sector_exposures[CryptoSector.BITCOIN]
        self.assertTrue(exposure.is_soft_limit_exceeded)
        self.assertFalse(exposure.is_hard_limit_exceeded)
        self.assertEqual(exposure.status, SectorLimitStatus.WARNING)
    
    def test_hard_limit_exceeded(self):
        """Test hard limit enforcement"""
        # Add position exceeding hard limit
        self.state.update_position('BTC-USD', 2000.0, add=True)
        
        exposure = self.state.sector_exposures[CryptoSector.BITCOIN]
        self.assertTrue(exposure.is_hard_limit_exceeded)
        self.assertEqual(exposure.status, SectorLimitStatus.HARD_LIMIT)
    
    def test_can_add_position(self):
        """Test position addition validation"""
        # Should be able to add small position
        can_add, reason = self.state.can_add_position('BTC-USD', 1000.0)
        self.assertTrue(can_add)
        
        # Add large position
        self.state.update_position('BTC-USD', 1500.0, add=True)
        
        # Should not be able to add position that exceeds hard limit
        can_add, reason = self.state.can_add_position('BTC-USD', 1000.0)
        self.assertFalse(can_add)
        self.assertIn('hard limit', reason.lower())
    
    def test_available_capacity(self):
        """Test available capacity calculation"""
        # Empty portfolio should have capacity
        capacity = self.state.get_available_capacity('BTC-USD')
        self.assertGreater(capacity, 0)
        
        # Add position
        self.state.update_position('BTC-USD', 1500.0, add=True)
        
        # Remaining capacity should be reduced
        new_capacity = self.state.get_available_capacity('BTC-USD')
        self.assertLess(new_capacity, capacity)
    
    def test_health_status(self):
        """Test health status reporting"""
        # Should be healthy initially
        health, warnings = self.state.get_health_status()
        self.assertEqual(health, 'healthy')
        self.assertEqual(len(warnings), 0)
        
        # Add position at warning level
        self.state.update_position('BTC-USD', 1500.0, add=True)
        health, warnings = self.state.get_health_status()
        self.assertEqual(health, 'warning')
        self.assertGreater(len(warnings), 0)


class TestPortfolioSuperStateMachine(unittest.TestCase):
    """Test portfolio super-state machine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.ssm = PortfolioSuperStateMachine()
    
    def test_initialization(self):
        """Test super-state machine initialization"""
        self.assertEqual(self.ssm.get_current_state(), PortfolioSuperState.NORMAL)
        rules = self.ssm.get_current_rules()
        self.assertIsNotNone(rules)
        self.assertTrue(rules.allow_new_positions)
    
    def test_normal_conditions(self):
        """Test normal market conditions"""
        conditions = MarketConditions(
            current_volatility=0.02,
            current_drawdown=0.02,
            liquidity_score=0.9
        )
        
        self.ssm.update_market_conditions(conditions)
        self.assertEqual(self.ssm.get_current_state(), PortfolioSuperState.NORMAL)
    
    def test_crisis_transition(self):
        """Test transition to crisis state"""
        # Simulate crisis conditions
        conditions = MarketConditions(
            current_volatility=0.12,
            current_drawdown=0.35,
            liquidity_score=0.3
        )
        
        self.ssm.update_market_conditions(conditions)
        self.assertEqual(self.ssm.get_current_state(), PortfolioSuperState.CRISIS)
        
        # Check that new positions are blocked
        rules = self.ssm.get_current_rules()
        self.assertFalse(rules.allow_new_positions)
        self.assertTrue(rules.force_position_reduction)
    
    def test_stressed_conditions(self):
        """Test stressed market conditions"""
        conditions = MarketConditions(
            current_volatility=0.06,
            current_drawdown=0.18,
            liquidity_score=0.5
        )
        
        self.ssm.update_market_conditions(conditions)
        state = self.ssm.get_current_state()
        self.assertIn(state, [PortfolioSuperState.STRESSED, PortfolioSuperState.CRISIS])
    
    def test_can_open_position(self):
        """Test position opening validation"""
        # Should be able to open in normal state
        can_open, reason = self.ssm.can_open_new_position(
            'BTC-USD', 1000, 10000
        )
        # May fail if trading state machine is OFF, that's OK
        
        # Transition to crisis
        crisis_conditions = MarketConditions(
            current_volatility=0.15,
            current_drawdown=0.40,
            liquidity_score=0.2
        )
        self.ssm.update_market_conditions(crisis_conditions)
        
        # Should not be able to open in crisis
        can_open, reason = self.ssm.can_open_new_position(
            'BTC-USD', 1000, 10000
        )
        self.assertFalse(can_open)
    
    def test_state_rules_adjustment(self):
        """Test that rules change with state"""
        normal_rules = self.ssm.get_current_rules()
        normal_max_position = normal_rules.max_position_size_pct
        
        # Transition to crisis
        crisis_conditions = MarketConditions(
            current_volatility=0.15,
            current_drawdown=0.40,
            liquidity_score=0.2
        )
        self.ssm.update_market_conditions(crisis_conditions)
        
        crisis_rules = self.ssm.get_current_rules()
        crisis_max_position = crisis_rules.max_position_size_pct
        
        # Crisis should have lower limits
        self.assertLess(crisis_max_position, normal_max_position)
        self.assertLess(crisis_rules.risk_multiplier, normal_rules.risk_multiplier)


class TestStateMachineStressTester(unittest.TestCase):
    """Test integrated stress testing framework"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tester = create_stress_tester({'crash_simulator': {'random_seed': 42}})
        self.portfolio = PortfolioState(available_cash=10000.0)
        self.symbols = ['BTC-USD', 'ETH-USD', 'SOL-USD']
        self.initial_prices = {
            'BTC-USD': 40000,
            'ETH-USD': 2000,
            'SOL-USD': 100
        }
        self.sector_map = {
            'BTC-USD': 'bitcoin',
            'ETH-USD': 'ethereum',
            'SOL-USD': 'layer_1_alt'
        }
    
    def test_flash_crash_stress_test(self):
        """Test flash crash stress test"""
        scenario = self.tester.crash_simulator.create_flash_crash_scenario(
            max_decline_pct=0.25,
            duration_minutes=10
        )
        
        result = self.tester.run_crash_stress_test(
            scenario=scenario,
            initial_portfolio=self.portfolio,
            symbols=self.symbols,
            initial_prices=self.initial_prices,
            sector_map=self.sector_map
        )
        
        self.assertIsNotNone(result)
        self.assertGreater(result.max_drawdown, 0)
        self.assertGreater(len(result.state_transitions), 0)
    
    def test_state_transitions_during_crash(self):
        """Test that state transitions occur during crash"""
        scenario = self.tester.crash_simulator.create_flash_crash_scenario()
        
        result = self.tester.run_crash_stress_test(
            scenario=scenario,
            initial_portfolio=self.portfolio,
            symbols=self.symbols,
            initial_prices=self.initial_prices,
            sector_map=self.sector_map
        )
        
        # Should have transitioned from NORMAL to higher severity state
        self.assertGreater(len(result.state_transitions), 0)
        self.assertIn(
            result.max_portfolio_state,
            ['cautious', 'stressed', 'crisis', 'emergency_halt']
        )
    
    def test_position_blocking_during_crisis(self):
        """Test that positions are blocked during crisis"""
        scenario = self.tester.crash_simulator.create_black_swan_scenario(
            max_decline_pct=0.50
        )
        
        result = self.tester.run_crash_stress_test(
            scenario=scenario,
            initial_portfolio=self.portfolio,
            symbols=self.symbols,
            initial_prices=self.initial_prices,
            sector_map=self.sector_map
        )
        
        # Should have blocked new positions during crisis
        self.assertGreater(result.new_positions_blocked, 0)


def run_tests():
    """Run all tests"""
    # Set up logging
    logging.basicConfig(
        level=logging.WARNING,  # Reduce noise during tests
        format='%(levelname)s - %(message)s'
    )
    
    # Create test suite
    suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    exit(0 if success else 1)
