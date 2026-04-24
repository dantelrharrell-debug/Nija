"""
NIJA Advanced Capital Engine - Platform Integration
=================================================

Integrates all advanced portfolio management features into a single,
cohesive capital engine:

1. Portfolio Optimization (position scoring & rebalancing)
2. Correlation Weighting (diversification optimization)
3. Risk Regime Allocation (risk-on/risk-off capital shifting)
4. Volatility Targeting (2% daily vol target with dynamic scaling)
5. Strategy Selection (regime-based strategy switching)
6. Monte Carlo Testing (execution robustness validation)

This creates a fund-grade, institutional-quality trading system.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# Import all advanced systems
from bot.advanced_portfolio_management import (
    AdvancedPortfolioManager, IntegratedPortfolioResult
)
from bot.volatility_targeting import (
    VolatilityTargetingEngine, VolatilityTargetingResult
)
from bot.regime_strategy_selector import (
    RegimeBasedStrategySelector, StrategySelectionResult, TradingStrategy
)
from bot.monte_carlo_stress_test import (
    MonteCarloStressTestEngine, MonteCarloResult
)

logger = logging.getLogger("nija.capital_engine")


@dataclass
class CapitalEngineState:
    """Current state of the capital engine"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Portfolio state
    total_capital: float = 0.0
    deployed_capital: float = 0.0
    reserve_capital: float = 0.0

    # Volatility metrics
    realized_volatility: float = 0.0
    target_volatility: float = 0.02
    volatility_scalar: float = 1.0

    # Risk metrics
    market_regime: str = "neutral"
    risk_mode: str = "neutral"

    # Strategy
    active_strategy: str = "none"
    strategy_confidence: float = 0.0

    # Performance
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0


@dataclass
class CapitalEngineResult:
    """Complete result from capital engine analysis"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Current state
    state: CapitalEngineState = None

    # Sub-system results
    portfolio_result: Optional[IntegratedPortfolioResult] = None
    volatility_result: Optional[VolatilityTargetingResult] = None
    strategy_result: Optional[StrategySelectionResult] = None
    stress_test_result: Optional[MonteCarloResult] = None

    # Final recommendations
    recommended_positions: Dict[str, Dict] = field(default_factory=dict)
    rebalancing_actions: List[Dict] = field(default_factory=list)

    # Comprehensive summary
    summary: str = ""


class AdvancedCapitalEngine:
    """
    Advanced Capital Engine - Platform Integration

    Orchestrates all portfolio management systems for optimal
    capital deployment and risk management.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Advanced Capital Engine

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Initialize all sub-systems
        portfolio_config = self.config.get('portfolio', {})
        self.portfolio_manager = AdvancedPortfolioManager(portfolio_config)

        volatility_config = self.config.get('volatility', {})
        self.volatility_engine = VolatilityTargetingEngine(volatility_config)

        strategy_config = self.config.get('strategy', {})
        self.strategy_selector = RegimeBasedStrategySelector(strategy_config)

        stress_test_config = self.config.get('stress_test', {})
        self.stress_test_engine = MonteCarloStressTestEngine(stress_test_config)

        # Engine settings
        self.enable_volatility_targeting = self.config.get('enable_volatility_targeting', True)
        self.enable_strategy_selection = self.config.get('enable_strategy_selection', True)
        self.enable_stress_testing = self.config.get('enable_stress_testing', False)  # On-demand

        # Current state
        self.current_state = CapitalEngineState()

        logger.info("=" * 70)
        logger.info("🚀 ADVANCED CAPITAL ENGINE INITIALIZED")
        logger.info("=" * 70)
        logger.info("Active Systems:")
        logger.info(f"  Portfolio Manager: ✓")
        logger.info(f"  Volatility Targeting: {'✓' if self.enable_volatility_targeting else '✗'}")
        logger.info(f"  Strategy Selection: {'✓' if self.enable_strategy_selection else '✗'}")
        logger.info(f"  Stress Testing: {'✓' if self.enable_stress_testing else '✗ (on-demand)'}")
        logger.info("=" * 70)

    def analyze_and_optimize(
        self,
        positions: List[Dict],
        market_data: Dict[str, Dict],
        total_capital: float,
        portfolio_value: Optional[float] = None,
        price_history: Optional[Dict[str, pd.Series]] = None,
        df: Optional[pd.DataFrame] = None,
        indicators: Optional[Dict] = None,
        run_stress_test: bool = False
    ) -> CapitalEngineResult:
        """
        Complete capital engine analysis and optimization

        Args:
            positions: Current open positions
            market_data: Market metrics for all symbols
            total_capital: Total account capital
            portfolio_value: Current portfolio value (for volatility calculation)
            price_history: Historical price data for correlation analysis
            df: Price DataFrame for regime detection
            indicators: Technical indicators for regime detection
            run_stress_test: Whether to run Monte Carlo stress test

        Returns:
            CapitalEngineResult with complete analysis and recommendations
        """
        logger.info("=" * 80)
        logger.info("🚀 ADVANCED CAPITAL ENGINE - FULL ANALYSIS")
        logger.info("=" * 80)
        logger.info(f"Total Capital: ${total_capital:,.2f}")
        logger.info(f"Open Positions: {len(positions)}")
        logger.info(f"Volatility Targeting: {'ENABLED' if self.enable_volatility_targeting else 'DISABLED'}")
        logger.info(f"Strategy Selection: {'ENABLED' if self.enable_strategy_selection else 'DISABLED'}")
        logger.info("=" * 80)

        # Step 1: Volatility Targeting
        volatility_result = None
        if self.enable_volatility_targeting and portfolio_value is not None:
            logger.info("\n📊 STEP 1: Volatility Targeting")
            logger.info("-" * 80)
            volatility_result = self.volatility_engine.target_volatility(
                portfolio_value=portfolio_value,
                force_update=True
            )

            # Update volatility metrics in state
            self.current_state.realized_volatility = volatility_result.metrics.daily_volatility
            self.current_state.target_volatility = volatility_result.metrics.target_volatility
            self.current_state.volatility_scalar = volatility_result.metrics.position_scalar
            self.current_state.risk_mode = volatility_result.risk_mode

        # Step 2: Strategy Selection (if data available)
        strategy_result = None
        if self.enable_strategy_selection and df is not None and indicators is not None:
            logger.info("\n🎯 STEP 2: Regime-Based Strategy Selection")
            logger.info("-" * 80)
            strategy_result = self.strategy_selector.select_strategy(df, indicators)

            # Update strategy in state
            self.current_state.active_strategy = strategy_result.selected_strategy.value
            self.current_state.strategy_confidence = strategy_result.regime_detection.confidence

        # Step 3: Portfolio Optimization
        logger.info("\n📈 STEP 3: Portfolio Optimization")
        logger.info("-" * 80)
        portfolio_result = self.portfolio_manager.manage_portfolio(
            positions=positions,
            market_data=market_data,
            total_capital=total_capital,
            price_history=price_history,
            force_optimization=True
        )

        # Update portfolio state
        if portfolio_result:
            self.current_state.market_regime = portfolio_result.market_regime.value
            self.current_state.deployed_capital = total_capital * portfolio_result.recommended_exposure_pct
            self.current_state.reserve_capital = total_capital - self.current_state.deployed_capital

        # Step 4: Integrate Results
        logger.info("\n⚖️  STEP 4: Integrating All Systems")
        logger.info("-" * 80)

        recommended_positions = self._integrate_recommendations(
            portfolio_result=portfolio_result,
            volatility_result=volatility_result,
            strategy_result=strategy_result,
            total_capital=total_capital
        )

        # Step 5: Stress Testing (optional)
        stress_test_result = None
        if run_stress_test or self.enable_stress_testing:
            logger.info("\n🎲 STEP 5: Monte Carlo Stress Testing")
            logger.info("-" * 80)

            # Convert positions to trade format for stress testing
            test_trades = self._prepare_stress_test_trades(positions, recommended_positions)

            if test_trades:
                stress_test_result = self.stress_test_engine.run_monte_carlo(test_trades)

        # Update state
        self.current_state.timestamp = datetime.now().isoformat()
        self.current_state.total_capital = total_capital

        # Generate comprehensive summary
        summary = self._generate_comprehensive_summary(
            portfolio_result, volatility_result, strategy_result,
            stress_test_result, recommended_positions
        )

        result = CapitalEngineResult(
            state=self.current_state,
            portfolio_result=portfolio_result,
            volatility_result=volatility_result,
            strategy_result=strategy_result,
            stress_test_result=stress_test_result,
            recommended_positions=recommended_positions,
            rebalancing_actions=portfolio_result.rebalancing_actions if portfolio_result else [],
            summary=summary
        )

        logger.info("=" * 80)
        logger.info(summary)
        logger.info("=" * 80)

        return result

    def _integrate_recommendations(
        self,
        portfolio_result: Optional[IntegratedPortfolioResult],
        volatility_result: Optional[VolatilityTargetingResult],
        strategy_result: Optional[StrategySelectionResult],
        total_capital: float
    ) -> Dict[str, Dict]:
        """
        Integrate recommendations from all systems

        Returns:
            Dictionary of symbol -> recommended position parameters
        """
        recommendations = {}

        if not portfolio_result:
            return recommendations

        # Start with portfolio recommendations
        for symbol, allocation in portfolio_result.final_allocation.items():
            # Base recommendation from portfolio optimization
            rec = {
                'symbol': symbol,
                'target_allocation_usd': allocation,
                'target_weight': portfolio_result.final_weights.get(symbol, 0),
                'source': 'portfolio_optimization',
            }

            # Apply volatility scaling if available
            if volatility_result:
                # Get symbol-specific volatility if available
                symbol_vol = 0.02  # Default 2%
                # Apply volatility scalar
                rec['volatility_scalar'] = volatility_result.metrics.position_scalar
                rec['position_size_pct'] = volatility_result.recommended_position_size_pct
                rec['risk_mode'] = volatility_result.risk_mode

                # Adjust allocation by volatility scalar
                rec['adjusted_allocation_usd'] = allocation * volatility_result.metrics.exposure_scalar
            else:
                rec['adjusted_allocation_usd'] = allocation

            # Add strategy recommendation if available
            if strategy_result:
                rec['recommended_strategy'] = strategy_result.selected_strategy.value
                rec['strategy_confidence'] = strategy_result.regime_detection.confidence

                # Get strategy parameters
                if strategy_result.strategy_params:
                    rec['entry_conditions'] = strategy_result.strategy_params.entry_conditions
                    rec['exit_conditions'] = strategy_result.strategy_params.exit_conditions
                    rec['risk_management'] = strategy_result.strategy_params.risk_management

            recommendations[symbol] = rec

        return recommendations

    def _prepare_stress_test_trades(
        self,
        current_positions: List[Dict],
        recommended_positions: Dict[str, Dict]
    ) -> List[Dict]:
        """Prepare trades for stress testing"""
        trades = []

        # Mock some recent trades for stress testing
        # In production, this would use actual trade history
        for pos in current_positions:
            symbol = pos.get('symbol')
            entry_price = pos.get('entry_price', 0)
            current_price = pos.get('current_price', 0)
            quantity = pos.get('quantity', 0)

            if entry_price > 0 and current_price > 0 and quantity > 0:
                trade = {
                    'symbol': symbol,
                    'direction': 'long',  # Assume long for now
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'quantity': quantity,
                    'entry_volatility': 0.02,
                    'exit_volatility': 0.02,
                }
                trades.append(trade)

        return trades

    def _generate_comprehensive_summary(
        self,
        portfolio_result: Optional[IntegratedPortfolioResult],
        volatility_result: Optional[VolatilityTargetingResult],
        strategy_result: Optional[StrategySelectionResult],
        stress_test_result: Optional[MonteCarloResult],
        recommendations: Dict[str, Dict]
    ) -> str:
        """Generate comprehensive summary of all systems"""
        lines = [
            "\n" + "=" * 80,
            "🚀 ADVANCED CAPITAL ENGINE - COMPREHENSIVE ANALYSIS SUMMARY",
            "=" * 80,
        ]

        # Volatility Targeting Summary
        if volatility_result:
            lines.append("\n📊 VOLATILITY TARGETING:")
            lines.append(f"  Realized Volatility: {volatility_result.metrics.daily_volatility*100:.2f}%")
            lines.append(f"  Target Volatility: {volatility_result.metrics.target_volatility*100:.2f}%")
            lines.append(f"  Position Scalar: {volatility_result.metrics.position_scalar:.2f}x")
            lines.append(f"  Risk Mode: {volatility_result.risk_mode.upper()}")

        # Strategy Selection Summary
        if strategy_result:
            lines.append("\n🎯 STRATEGY SELECTION:")
            lines.append(f"  Market Regime: {strategy_result.regime_detection.regime.value.upper()}")
            lines.append(f"  Selected Strategy: {strategy_result.selected_strategy.value.upper()}")
            lines.append(f"  Confidence: {strategy_result.regime_detection.confidence:.2%}")

        # Portfolio Optimization Summary
        if portfolio_result:
            lines.append("\n📈 PORTFOLIO OPTIMIZATION:")
            lines.append(f"  Market Regime: {portfolio_result.market_regime.value.upper()}")
            lines.append(f"  Recommended Exposure: {portfolio_result.recommended_exposure_pct*100:.0f}%")
            lines.append(f"  Rebalancing Actions: {len(portfolio_result.rebalancing_actions)}")

            if portfolio_result.optimization_result:
                metrics = portfolio_result.optimization_result.efficiency_metrics
                lines.append(f"  Portfolio Quality: {metrics.get('portfolio_quality', 'unknown').upper()}")
                lines.append(f"  Average Score: {metrics.get('average_score', 0):.1f}/100")

        # Stress Test Summary
        if stress_test_result:
            lines.append("\n🎲 STRESS TEST RESULTS:")
            lines.append(f"  Simulations: {stress_test_result.num_simulations}")
            lines.append(f"  Expected Degradation: {stress_test_result.mean_degradation_pct:.2f}%")
            lines.append(f"  Worst Case Degradation: {stress_test_result.worst_case_degradation_pct:.2f}%")
            lines.append(f"  5th Percentile P&L: ${stress_test_result.pnl_percentiles.get(5, 0):,.2f}")

        # Recommendations Summary
        lines.append(f"\n💰 FINAL RECOMMENDATIONS:")
        lines.append(f"  Total Positions: {len(recommendations)}")

        if recommendations:
            lines.append("\n  Top 5 Allocations:")
            sorted_recs = sorted(
                recommendations.items(),
                key=lambda x: x[1].get('adjusted_allocation_usd', 0),
                reverse=True
            )[:5]

            for symbol, rec in sorted_recs:
                allocation = rec.get('adjusted_allocation_usd', 0)
                weight = rec.get('target_weight', 0)
                lines.append(
                    f"    {symbol:12s}: ${allocation:>10,.2f} ({weight*100:5.1f}%)"
                )

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    def get_current_state(self) -> CapitalEngineState:
        """Get current engine state"""
        return self.current_state

    def update_portfolio_value(self, value: float):
        """Update portfolio value for volatility tracking"""
        self.volatility_engine.update_portfolio_return(value)


def create_advanced_capital_engine(config: Dict = None) -> AdvancedCapitalEngine:
    """
    Factory function to create AdvancedCapitalEngine

    Args:
        config: Optional configuration

    Returns:
        AdvancedCapitalEngine instance
    """
    return AdvancedCapitalEngine(config)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create engine
    engine = create_advanced_capital_engine({
        'enable_volatility_targeting': True,
        'enable_strategy_selection': True,
        'enable_stress_testing': False,
    })

    # Mock data
    positions = [
        {
            'symbol': 'BTC-USD',
            'quantity': 0.5,
            'entry_price': 40000,
            'current_price': 42000,
            'market_value': 21000,
            'unrealized_pnl': 1000,
            'pnl_pct': 5.0,
        },
    ]

    market_data = {
        'BTC-USD': {
            'adx': 35,
            'rsi': 65,
            'atr': 1200,
            'price': 42000,
            'volume_ratio': 1.4,
            'trend_direction': 1,
        },
    }

    # Mock price data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.cumsum(np.random.randn(100) * 0.5) + 42000,
        'high': np.cumsum(np.random.randn(100) * 0.5) + 42100,
        'low': np.cumsum(np.random.randn(100) * 0.5) + 41900,
        'volume': np.random.randint(1000, 5000, 100),
    })

    indicators = {
        'adx': pd.Series([35.0] * 100),
        'rsi': pd.Series([65.0] * 100),
        'atr': pd.Series([1200.0] * 100),
        'bb_upper': pd.Series([43000.0] * 100),
        'bb_lower': pd.Series([41000.0] * 100),
    }

    # Run full analysis
    result = engine.analyze_and_optimize(
        positions=positions,
        market_data=market_data,
        total_capital=100000,
        portfolio_value=105000,
        df=df,
        indicators=indicators,
        run_stress_test=True
    )

    print(result.summary)
