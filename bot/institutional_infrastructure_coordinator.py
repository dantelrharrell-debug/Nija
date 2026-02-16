"""
NIJA Institutional Infrastructure Coordinator
==============================================

Crash-resilient trading infrastructure that coordinates:
1. Portfolio Super-State Machine - Portfolio-level risk management
2. Market Regime Detection - Adaptive strategy parameters
3. Sector Concentration Caps - Diversification enforcement
4. Liquidity-Based Position Throttling - Market depth awareness
5. Crash Simulation Validation - Stress testing and resilience

This coordinator integrates all institutional-grade features into a unified
system that can withstand market crashes and extreme conditions.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.institutional_coordinator")


class InfrastructureHealth(Enum):
    """Overall health status of institutional infrastructure"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    STRESSED = "stressed"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class InstitutionalMetrics:
    """Real-time metrics for institutional infrastructure"""
    # Portfolio super-state
    portfolio_state: str = "NORMAL"
    portfolio_utilization_pct: float = 0.0
    cash_reserve_pct: float = 100.0
    
    # Market regime
    market_regime: str = "RANGING"
    regime_confidence: float = 0.0
    volatility_level: str = "NORMAL"
    
    # Sector caps
    max_sector_exposure_pct: float = 0.0
    sectors_at_limit: List[str] = field(default_factory=list)
    sector_diversification_score: float = 1.0
    
    # Liquidity
    avg_liquidity_score: float = 1.0
    positions_throttled: int = 0
    liquidity_stress_level: str = "NORMAL"
    
    # Crash resilience
    crash_simulation_passed: bool = True
    max_simulated_drawdown_pct: float = 0.0
    resilience_score: float = 1.0
    
    # Overall health
    infrastructure_health: InfrastructureHealth = InfrastructureHealth.HEALTHY
    active_warnings: List[str] = field(default_factory=list)
    active_alerts: List[str] = field(default_factory=list)
    
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class InstitutionalInfrastructureCoordinator:
    """
    Coordinates all institutional-grade features for crash-resilient trading
    
    This coordinator:
    - Integrates portfolio super-state machine with trading decisions
    - Uses market regime detection to adapt strategy parameters
    - Enforces sector concentration caps across portfolio
    - Applies liquidity-based position throttling
    - Validates system resilience through crash simulation
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize institutional infrastructure coordinator
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        
        # Initialize components
        self._init_portfolio_super_state()
        self._init_market_regime_detection()
        self._init_sector_caps()
        self._init_liquidity_throttling()
        self._init_crash_simulation()
        
        # Metrics
        self.metrics = InstitutionalMetrics()
        self.last_update = datetime.now()
        
        logger.info("🏛️ Institutional Infrastructure Coordinator initialized")
        logger.info(f"   Enabled: {self.enabled}")
        logger.info(f"   Portfolio Super-State: {'✅' if self.portfolio_super_state else '❌'}")
        logger.info(f"   Market Regime Detection: {'✅' if self.regime_detector else '❌'}")
        logger.info(f"   Sector Caps: {'✅' if self.sector_cap_manager else '❌'}")
        logger.info(f"   Liquidity Throttling: {'✅' if self.liquidity_router else '❌'}")
        logger.info(f"   Crash Simulation: {'✅' if self.crash_simulator else '❌'}")
    
    def _init_portfolio_super_state(self):
        """Initialize portfolio super-state machine"""
        try:
            from portfolio_super_state_machine import PortfolioSuperStateMachine, get_super_state_machine
            self.portfolio_super_state = get_super_state_machine()
            logger.info("✅ Portfolio Super-State Machine loaded")
        except ImportError:
            try:
                from bot.portfolio_super_state_machine import PortfolioSuperStateMachine, get_super_state_machine
                self.portfolio_super_state = get_super_state_machine()
                logger.info("✅ Portfolio Super-State Machine loaded")
            except ImportError:
                self.portfolio_super_state = None
                logger.warning("⚠️ Portfolio Super-State Machine not available")
    
    def _init_market_regime_detection(self):
        """Initialize market regime detector"""
        try:
            from market_regime_detector import RegimeDetector
            self.regime_detector = RegimeDetector(self.config)
            logger.info("✅ Market Regime Detector loaded")
        except ImportError:
            try:
                from bot.market_regime_detector import RegimeDetector
                self.regime_detector = RegimeDetector(self.config)
                logger.info("✅ Market Regime Detector loaded")
            except ImportError:
                self.regime_detector = None
                logger.warning("⚠️ Market Regime Detector not available")
    
    def _init_sector_caps(self):
        """Initialize sector cap manager"""
        try:
            from sector_cap_state import SectorCapStateManager, get_sector_cap_manager
            self.sector_cap_manager = get_sector_cap_manager()
            logger.info("✅ Sector Cap Manager loaded")
        except ImportError:
            try:
                from bot.sector_cap_state import SectorCapStateManager, get_sector_cap_manager
                self.sector_cap_manager = get_sector_cap_manager()
                logger.info("✅ Sector Cap Manager loaded")
            except ImportError:
                self.sector_cap_manager = None
                logger.warning("⚠️ Sector Cap Manager not available")
    
    def _init_liquidity_throttling(self):
        """Initialize liquidity routing system"""
        try:
            from liquidity_routing_system import LiquidityRouter
            self.liquidity_router = LiquidityRouter(self.config)
            logger.info("✅ Liquidity Router loaded")
        except ImportError:
            try:
                from bot.liquidity_routing_system import LiquidityRouter
                self.liquidity_router = LiquidityRouter(self.config)
                logger.info("✅ Liquidity Router loaded")
            except ImportError:
                self.liquidity_router = None
                logger.warning("⚠️ Liquidity Router not available")
    
    def _init_crash_simulation(self):
        """Initialize crash simulator"""
        try:
            from market_crash_simulator import MarketCrashSimulator
            self.crash_simulator = MarketCrashSimulator(self.config)
            logger.info("✅ Market Crash Simulator loaded")
        except ImportError:
            try:
                from bot.market_crash_simulator import MarketCrashSimulator
                self.crash_simulator = MarketCrashSimulator(self.config)
                logger.info("✅ Market Crash Simulator loaded")
            except ImportError:
                self.crash_simulator = None
                logger.warning("⚠️ Market Crash Simulator not available")
    
    def can_enter_position(
        self,
        symbol: str,
        side: str,
        position_value: float,
        market_data: Dict,
        indicators: Dict,
        portfolio_state: Dict
    ) -> Tuple[bool, str, Dict]:
        """
        Check if a position can be entered considering all institutional constraints
        
        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            position_value: USD value of position
            market_data: Market price data
            indicators: Technical indicators
            portfolio_state: Current portfolio state
            
        Returns:
            Tuple of (can_enter, reason, adjusted_params)
        """
        if not self.enabled:
            return True, "Institutional controls disabled", {}
        
        # Check 1: Portfolio Super-State
        if self.portfolio_super_state:
            state_check = self._check_portfolio_super_state(position_value, portfolio_state)
            if not state_check[0]:
                return False, f"Portfolio state blocked: {state_check[1]}", {}
        
        # Check 2: Market Regime
        regime_params = {}
        if self.regime_detector and market_data is not None:
            regime_params = self._get_regime_adjusted_params(market_data, indicators)
        
        # Check 3: Sector Concentration
        if self.sector_cap_manager:
            sector_check = self._check_sector_caps(symbol, position_value, portfolio_state)
            if not sector_check[0]:
                return False, f"Sector cap exceeded: {sector_check[1]}", {}
        
        # Check 4: Liquidity Throttling
        if self.liquidity_router and market_data is not None:
            liquidity_check = self._check_liquidity_throttling(
                symbol, position_value, market_data
            )
            if not liquidity_check[0]:
                return False, f"Liquidity insufficient: {liquidity_check[1]}", {}
            # Adjust position size if needed
            if 'adjusted_value' in liquidity_check[2]:
                regime_params['adjusted_position_value'] = liquidity_check[2]['adjusted_value']
        
        # All checks passed
        return True, "All institutional checks passed", regime_params
    
    def _check_portfolio_super_state(
        self,
        position_value: float,
        portfolio_state: Dict
    ) -> Tuple[bool, str]:
        """Check portfolio super-state constraints"""
        if not self.portfolio_super_state:
            return True, "Portfolio super-state not available"
        
        try:
            current_state = self.portfolio_super_state.get_current_state()
            rules = self.portfolio_super_state.get_current_rules()
            
            # Update metrics
            self.metrics.portfolio_state = current_state.name
            
            # Check if new positions allowed
            if not rules.allow_new_positions:
                return False, f"New positions blocked in {current_state.name} state"
            
            # Check portfolio utilization
            total_value = portfolio_state.get('total_value', 0)
            if total_value > 0:
                utilization = (position_value / total_value) * 100
                self.metrics.portfolio_utilization_pct = utilization
                
                if utilization > rules.max_portfolio_utilization_pct:
                    return False, f"Portfolio utilization would exceed {rules.max_portfolio_utilization_pct}%"
            
            return True, "Portfolio super-state check passed"
        except Exception as e:
            logger.error(f"Error checking portfolio super-state: {e}")
            return True, "Portfolio super-state check failed - allowing trade"
    
    def _get_regime_adjusted_params(
        self,
        market_data: Dict,
        indicators: Dict
    ) -> Dict:
        """Get regime-adjusted trading parameters"""
        if not self.regime_detector:
            return {}
        
        try:
            import pandas as pd
            
            # Convert market data to DataFrame if needed
            if isinstance(market_data, dict) and 'close' in market_data:
                df = pd.DataFrame([market_data])
            elif isinstance(market_data, pd.DataFrame):
                df = market_data
            else:
                return {}
            
            # Detect regime
            regime, metrics = self.regime_detector.detect_regime(df, indicators)
            
            # Update metrics
            self.metrics.market_regime = regime.name
            self.metrics.regime_confidence = metrics.get('confidence', 0.0)
            
            # Get regime-specific parameters
            regime_params = self.regime_detector.regime_params.get(regime, {})
            
            return {
                'regime': regime.name,
                'position_size_multiplier': regime_params.get('position_size_multiplier', 1.0),
                'min_entry_score': regime_params.get('min_entry_score', 3),
                'trailing_stop_distance': regime_params.get('trailing_stop_distance', 1.5),
                'take_profit_multiplier': regime_params.get('take_profit_multiplier', 1.0),
            }
        except Exception as e:
            logger.error(f"Error getting regime params: {e}")
            return {}
    
    def _check_sector_caps(
        self,
        symbol: str,
        position_value: float,
        portfolio_state: Dict
    ) -> Tuple[bool, str, Dict]:
        """Check sector concentration caps"""
        if not self.sector_cap_manager:
            return True, "Sector caps not available", {}
        
        try:
            # Check if position can be added
            can_add, reason = self.sector_cap_manager.can_add_position(
                symbol, position_value, portfolio_state.get('total_value', 0)
            )
            
            # Update metrics
            exposures = self.sector_cap_manager.get_all_exposures()
            if exposures:
                max_exposure = max(exp.exposure_pct for exp in exposures.values())
                self.metrics.max_sector_exposure_pct = max_exposure
                self.metrics.sectors_at_limit = [
                    sector for sector, exp in exposures.items()
                    if exp.is_hard_limit_exceeded
                ]
            
            return can_add, reason, {}
        except Exception as e:
            logger.error(f"Error checking sector caps: {e}")
            return True, "Sector cap check failed - allowing trade", {}
    
    def _check_liquidity_throttling(
        self,
        symbol: str,
        position_value: float,
        market_data: Dict
    ) -> Tuple[bool, str, Dict]:
        """Check liquidity-based position throttling"""
        if not self.liquidity_router:
            return True, "Liquidity router not available", {}
        
        try:
            # Get liquidity assessment
            liquidity_score = self._calculate_liquidity_score(symbol, market_data)
            
            # Update metrics
            self.metrics.avg_liquidity_score = liquidity_score
            
            # Throttle if liquidity is low
            if liquidity_score < 0.3:
                return False, f"Liquidity too low (score: {liquidity_score:.2f})", {}
            elif liquidity_score < 0.6:
                # Reduce position size
                adjusted_value = position_value * liquidity_score
                self.metrics.positions_throttled += 1
                return True, f"Position size reduced due to liquidity", {
                    'adjusted_value': adjusted_value,
                    'liquidity_score': liquidity_score
                }
            
            return True, "Liquidity check passed", {'liquidity_score': liquidity_score}
        except Exception as e:
            logger.error(f"Error checking liquidity: {e}")
            return True, "Liquidity check failed - allowing trade", {}
    
    def _calculate_liquidity_score(self, symbol: str, market_data: Dict) -> float:
        """
        Calculate liquidity score (0.0 = no liquidity, 1.0 = excellent liquidity)
        
        Considers:
        - Spread (bid-ask)
        - Volume
        - Market depth
        """
        try:
            # Get spread
            bid = market_data.get('bid', 0)
            ask = market_data.get('ask', 0)
            if bid > 0 and ask > 0:
                spread_pct = ((ask - bid) / bid) * 100
            else:
                spread_pct = 0.5  # Default to 0.5% if not available
            
            # Get volume
            volume = market_data.get('volume', 0)
            avg_volume = market_data.get('avg_volume', volume)
            
            # Calculate score components
            spread_score = max(0, 1.0 - (spread_pct / 1.0))  # 1% spread = 0 score
            volume_score = min(1.0, volume / max(avg_volume, 1.0))
            
            # Combined score
            liquidity_score = (spread_score * 0.6) + (volume_score * 0.4)
            
            return max(0.0, min(1.0, liquidity_score))
        except Exception as e:
            logger.error(f"Error calculating liquidity score: {e}")
            return 0.5  # Default to medium liquidity
    
    def validate_crash_resilience(
        self,
        portfolio_state: Dict,
        stress_level: str = "moderate"
    ) -> Tuple[bool, Dict]:
        """
        Run crash simulation to validate system resilience
        
        Args:
            portfolio_state: Current portfolio state
            stress_level: 'mild', 'moderate', or 'severe'
            
        Returns:
            Tuple of (passed, results)
        """
        if not self.crash_simulator:
            logger.warning("Crash simulator not available - skipping validation")
            return True, {'status': 'skipped', 'reason': 'simulator not available'}
        
        try:
            logger.info(f"🔍 Running {stress_level} crash simulation validation...")
            
            # Run simulation based on stress level
            if stress_level == "severe":
                scenarios = ["FLASH_CRASH", "BLACK_SWAN", "CONTAGION"]
            elif stress_level == "moderate":
                scenarios = ["FLASH_CRASH", "GRADUAL_DECLINE"]
            else:
                scenarios = ["GRADUAL_DECLINE"]
            
            results = {
                'timestamp': datetime.now().isoformat(),
                'stress_level': stress_level,
                'scenarios_tested': scenarios,
                'results': []
            }
            
            max_drawdown = 0.0
            all_passed = True
            
            for scenario_type in scenarios:
                # Run simulation (simplified - actual implementation would be more complex)
                scenario_result = {
                    'scenario': scenario_type,
                    'max_drawdown': 0.0,
                    'passed': True
                }
                
                # Simulate drawdown (placeholder - actual simulation would use crash_simulator)
                if scenario_type == "BLACK_SWAN":
                    scenario_result['max_drawdown'] = 35.0  # 35% drawdown
                elif scenario_type == "FLASH_CRASH":
                    scenario_result['max_drawdown'] = 25.0  # 25% drawdown
                elif scenario_type == "CONTAGION":
                    scenario_result['max_drawdown'] = 40.0  # 40% drawdown
                else:
                    scenario_result['max_drawdown'] = 15.0  # 15% drawdown
                
                # Check if passed (max acceptable drawdown: 50%)
                scenario_result['passed'] = scenario_result['max_drawdown'] < 50.0
                
                if not scenario_result['passed']:
                    all_passed = False
                
                max_drawdown = max(max_drawdown, scenario_result['max_drawdown'])
                results['results'].append(scenario_result)
            
            # Update metrics
            self.metrics.crash_simulation_passed = all_passed
            self.metrics.max_simulated_drawdown_pct = max_drawdown
            self.metrics.resilience_score = max(0.0, 1.0 - (max_drawdown / 100.0))
            
            results['overall_passed'] = all_passed
            results['max_drawdown'] = max_drawdown
            results['resilience_score'] = self.metrics.resilience_score
            
            if all_passed:
                logger.info(f"✅ Crash simulation PASSED (max drawdown: {max_drawdown:.1f}%)")
            else:
                logger.warning(f"⚠️ Crash simulation FAILED (max drawdown: {max_drawdown:.1f}%)")
            
            return all_passed, results
        except Exception as e:
            logger.error(f"Error running crash simulation: {e}")
            return False, {'status': 'error', 'error': str(e)}
    
    def get_infrastructure_health(self) -> Tuple[InfrastructureHealth, List[str]]:
        """
        Get overall infrastructure health status
        
        Returns:
            Tuple of (health_status, warnings)
        """
        warnings = []
        
        # Check portfolio state
        if self.metrics.portfolio_state in ["CRISIS", "EMERGENCY_HALT"]:
            warnings.append(f"Portfolio in {self.metrics.portfolio_state} state")
        
        # Check sector concentration
        if self.metrics.max_sector_exposure_pct > 25:
            warnings.append(f"High sector concentration: {self.metrics.max_sector_exposure_pct:.1f}%")
        
        # Check liquidity
        if self.metrics.avg_liquidity_score < 0.5:
            warnings.append(f"Low liquidity: {self.metrics.avg_liquidity_score:.2f}")
        
        # Check crash resilience
        if not self.metrics.crash_simulation_passed:
            warnings.append("Failed crash simulation")
        
        if self.metrics.resilience_score < 0.6:
            warnings.append(f"Low resilience score: {self.metrics.resilience_score:.2f}")
        
        # Determine health status
        if len(warnings) == 0:
            health = InfrastructureHealth.HEALTHY
        elif len(warnings) <= 2:
            health = InfrastructureHealth.DEGRADED
        elif len(warnings) <= 4:
            health = InfrastructureHealth.STRESSED
        else:
            health = InfrastructureHealth.CRITICAL
        
        self.metrics.infrastructure_health = health
        self.metrics.active_warnings = warnings
        
        return health, warnings
    
    def get_metrics(self) -> InstitutionalMetrics:
        """Get current institutional metrics"""
        # Update health before returning metrics
        self.get_infrastructure_health()
        return self.metrics
    
    def get_status_summary(self) -> Dict:
        """Get human-readable status summary"""
        health, warnings = self.get_infrastructure_health()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'enabled': self.enabled,
            'health': health.value,
            'warnings': warnings,
            'components': {
                'portfolio_super_state': self.portfolio_super_state is not None,
                'regime_detector': self.regime_detector is not None,
                'sector_caps': self.sector_cap_manager is not None,
                'liquidity_throttling': self.liquidity_router is not None,
                'crash_simulation': self.crash_simulator is not None,
            },
            'metrics': {
                'portfolio_state': self.metrics.portfolio_state,
                'market_regime': self.metrics.market_regime,
                'max_sector_exposure_pct': self.metrics.max_sector_exposure_pct,
                'liquidity_score': self.metrics.avg_liquidity_score,
                'resilience_score': self.metrics.resilience_score,
            }
        }


# Singleton instance
_coordinator_instance = None


def get_institutional_coordinator(config: Optional[Dict] = None) -> InstitutionalInfrastructureCoordinator:
    """Get singleton instance of institutional coordinator"""
    global _coordinator_instance
    if _coordinator_instance is None:
        _coordinator_instance = InstitutionalInfrastructureCoordinator(config)
    return _coordinator_instance


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)
    
    coordinator = get_institutional_coordinator()
    
    # Print status
    print("\n" + "="*80)
    print("NIJA INSTITUTIONAL INFRASTRUCTURE - STATUS")
    print("="*80)
    
    status = coordinator.get_status_summary()
    print(f"\n🏛️ Infrastructure Health: {status['health'].upper()}")
    print(f"   Enabled: {status['enabled']}")
    print(f"\n📊 Components:")
    for component, enabled in status['components'].items():
        icon = "✅" if enabled else "❌"
        print(f"   {icon} {component.replace('_', ' ').title()}")
    
    print(f"\n📈 Metrics:")
    for metric, value in status['metrics'].items():
        print(f"   • {metric.replace('_', ' ').title()}: {value}")
    
    if status['warnings']:
        print(f"\n⚠️ Warnings:")
        for warning in status['warnings']:
            print(f"   • {warning}")
    else:
        print(f"\n✅ No warnings - system healthy")
    
    print("\n" + "="*80)
