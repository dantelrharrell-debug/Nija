"""
NIJA Advanced Portfolio Management Integration
==============================================

Integrates three advanced portfolio management features:
1. Portfolio-level optimization (position scoring and rebalancing)
2. Multi-asset correlation weighting (diversification optimization)
3. Dynamic risk-on/risk-off capital allocation (regime-based exposure)

This module provides a unified interface to use all three systems together
for optimal portfolio construction and management.

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

# Import the three portfolio management modules
from bot.portfolio_optimizer import PortfolioOptimizer, OptimizationResult
from bot.correlation_weighting import CorrelationWeightingSystem, CorrelationWeightingResult
from bot.risk_regime_allocator import RiskOnRiskOffAllocator, RiskRegimeResult, MarketRegime

# Import existing portfolio state manager
try:
    from bot.portfolio_state import PortfolioState, get_portfolio_manager
    PORTFOLIO_STATE_AVAILABLE = True
except ImportError:
    PORTFOLIO_STATE_AVAILABLE = False
    logging.warning("PortfolioState not available - some features may be limited")

logger = logging.getLogger("nija.portfolio_management")


@dataclass
class IntegratedPortfolioResult:
    """Combined result from all portfolio management systems"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Risk regime analysis
    market_regime: MarketRegime = MarketRegime.NEUTRAL
    regime_confidence: float = 0.0
    recommended_exposure_pct: float = 0.60

    # Portfolio optimization
    optimization_result: Optional[OptimizationResult] = None

    # Correlation weighting
    correlation_result: Optional[CorrelationWeightingResult] = None

    # Final recommendations
    final_weights: Dict[str, float] = field(default_factory=dict)
    final_allocation: Dict[str, float] = field(default_factory=dict)  # USD amounts
    rebalancing_actions: List[Dict] = field(default_factory=list)

    # Summary
    summary: str = ""


class AdvancedPortfolioManager:
    """
    Advanced portfolio management system integrating:
    - Portfolio optimization
    - Correlation-based weighting
    - Risk regime detection and allocation
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Advanced Portfolio Manager

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Initialize sub-systems
        optimizer_config = self.config.get('optimizer', {})
        self.portfolio_optimizer = PortfolioOptimizer(optimizer_config)

        correlation_config = self.config.get('correlation', {})
        self.correlation_weighting = CorrelationWeightingSystem(correlation_config)

        regime_config = self.config.get('risk_regime', {})
        self.risk_regime_allocator = RiskOnRiskOffAllocator(regime_config)

        # Integration settings
        self.use_correlation_weighting = self.config.get('use_correlation_weighting', True)
        self.use_risk_regime = self.config.get('use_risk_regime', True)
        self.optimization_frequency = self.config.get('optimization_frequency', 3600)  # 1 hour

        # Weighting scheme for final recommendations
        self.weight_blending = {
            'optimizer': self.config.get('optimizer_weight', 0.40),  # 40% from optimizer scores
            'correlation': self.config.get('correlation_weight', 0.30),  # 30% from correlation
            'regime': self.config.get('regime_weight', 0.30),  # 30% from regime
        }

        # Last optimization timestamp
        self.last_optimization: Optional[datetime] = None

        logger.info("=" * 70)
        logger.info("🚀 Advanced Portfolio Manager Initialized")
        logger.info("=" * 70)
        logger.info("Active Systems:")
        logger.info(f"  Portfolio Optimizer: ✓")
        logger.info(f"  Correlation Weighting: {'✓' if self.use_correlation_weighting else '✗'}")
        logger.info(f"  Risk Regime Allocation: {'✓' if self.use_risk_regime else '✗'}")
        logger.info("")
        logger.info("Weight Blending:")
        for system, weight in self.weight_blending.items():
            logger.info(f"  {system}: {weight*100:.0f}%")
        logger.info("=" * 70)

    def manage_portfolio(
        self,
        positions: List[Dict],
        market_data: Dict[str, Dict],
        total_capital: float,
        price_history: Optional[Dict[str, pd.Series]] = None,
        force_optimization: bool = False
    ) -> IntegratedPortfolioResult:
        """
        Complete portfolio management including optimization, correlation weighting,
        and risk regime allocation

        Args:
            positions: List of current positions
            market_data: Dictionary of symbol -> market metrics
            total_capital: Total portfolio capital
            price_history: Optional price history for correlation analysis
            force_optimization: Force optimization even if not due

        Returns:
            IntegratedPortfolioResult with all recommendations
        """
        logger.info("=" * 70)
        logger.info("🚀 INTEGRATED PORTFOLIO MANAGEMENT")
        logger.info("=" * 70)
        logger.info(f"Total Capital: ${total_capital:,.2f}")
        logger.info(f"Current Positions: {len(positions)}")
        logger.info("=" * 70)

        # Check if optimization is due
        if not force_optimization and self.last_optimization:
            time_since_last = (datetime.now() - self.last_optimization).total_seconds()
            if time_since_last < self.optimization_frequency:
                logger.info(
                    f"Optimization not due yet ({time_since_last:.0f}s < {self.optimization_frequency}s)"
                )
                return None

        # Step 1: Detect market regime and get base allocation
        regime_result = None
        if self.use_risk_regime:
            logger.info("\n📊 Step 1: Risk Regime Analysis")
            regime_result = self.risk_regime_allocator.analyze_and_allocate(
                market_data=market_data,
                total_capital=total_capital
            )
            market_regime = regime_result.regime_signal.regime
            regime_confidence = regime_result.regime_signal.confidence
            base_exposure_pct = regime_result.allocation.recommended_exposure_pct
            position_multiplier = regime_result.allocation.position_sizing_multiplier
        else:
            market_regime = MarketRegime.NEUTRAL
            regime_confidence = 0.5
            base_exposure_pct = 0.60
            position_multiplier = 1.0

        # Step 2: Calculate correlation matrix and weights
        correlation_result = None
        correlation_matrix = None

        if self.use_correlation_weighting and price_history:
            logger.info("\n🔗 Step 2: Correlation Analysis")
            # Update price history in correlation system
            for symbol, prices in price_history.items():
                self.correlation_weighting.update_price_history(symbol, prices)

            # Calculate correlation matrix
            symbols = [pos.get('symbol') for pos in positions]
            correlation_matrix = self.correlation_weighting.calculate_correlation_matrix(symbols)

            if correlation_matrix is not None:
                # Get base weights (equal weight as starting point)
                base_weights = {symbol: 1.0/len(positions) for symbol in symbols}

                # Calculate correlation-adjusted weights
                correlation_result = self.correlation_weighting.calculate_correlation_weights(
                    positions=positions,
                    base_weights=base_weights,
                    correlation_matrix=correlation_matrix
                )

        # Step 3: Run portfolio optimization
        logger.info("\n📈 Step 3: Portfolio Optimization")
        optimization_result = self.portfolio_optimizer.optimize_portfolio(
            positions=positions,
            market_data=market_data,
            total_equity=total_capital,
            correlation_matrix=correlation_matrix
        )

        # Step 4: Blend weights from all systems
        logger.info("\n⚖️  Step 4: Weight Blending")
        final_weights = self._blend_weights(
            optimization_result=optimization_result,
            correlation_result=correlation_result,
            regime_multiplier=position_multiplier
        )

        # Step 5: Calculate final capital allocation
        logger.info("\n💰 Step 5: Final Capital Allocation")
        deployable_capital = total_capital * base_exposure_pct
        final_allocation = self._calculate_final_allocation(
            weights=final_weights,
            deployable_capital=deployable_capital
        )

        # Step 6: Generate rebalancing actions
        logger.info("\n🔄 Step 6: Rebalancing Recommendations")
        rebalancing_actions = self._generate_integrated_rebalancing(
            positions=positions,
            final_allocation=final_allocation,
            total_capital=total_capital
        )

        # Generate comprehensive summary
        summary = self._generate_integrated_summary(
            regime_result=regime_result,
            optimization_result=optimization_result,
            correlation_result=correlation_result,
            final_allocation=final_allocation,
            rebalancing_actions=rebalancing_actions,
            total_capital=total_capital
        )

        # Update last optimization time
        self.last_optimization = datetime.now()

        result = IntegratedPortfolioResult(
            market_regime=market_regime,
            regime_confidence=regime_confidence,
            recommended_exposure_pct=base_exposure_pct,
            optimization_result=optimization_result,
            correlation_result=correlation_result,
            final_weights=final_weights,
            final_allocation=final_allocation,
            rebalancing_actions=rebalancing_actions,
            summary=summary
        )

        logger.info("=" * 70)
        logger.info(summary)
        logger.info("=" * 70)

        return result

    def _blend_weights(
        self,
        optimization_result: OptimizationResult,
        correlation_result: Optional[CorrelationWeightingResult],
        regime_multiplier: float
    ) -> Dict[str, float]:
        """
        Blend weights from all three systems

        Args:
            optimization_result: Result from portfolio optimizer
            correlation_result: Result from correlation weighting (optional)
            regime_multiplier: Multiplier from risk regime (0.5-2.0)

        Returns:
            Dictionary of symbol -> blended weight
        """
        # Start with optimizer weights
        optimizer_weights = optimization_result.recommended_weights.copy()

        # Get correlation weights if available
        correlation_weights = {}
        if correlation_result:
            correlation_weights = {
                symbol: weight.adjusted_weight
                for symbol, weight in correlation_result.weights.items()
            }

        # Blend weights
        blended_weights = {}
        all_symbols = set(optimizer_weights.keys()) | set(correlation_weights.keys())

        for symbol in all_symbols:
            opt_weight = optimizer_weights.get(symbol, 0.0)
            corr_weight = correlation_weights.get(symbol, opt_weight)  # Use optimizer as fallback

            # Weighted blend
            if self.use_correlation_weighting and correlation_result:
                blended = (
                    opt_weight * self.weight_blending['optimizer'] +
                    corr_weight * self.weight_blending['correlation']
                )
                # Normalize the remaining weight
                remaining_weight = 1.0 - (
                    self.weight_blending['optimizer'] +
                    self.weight_blending['correlation']
                )
                blended += opt_weight * remaining_weight  # Use optimizer for remainder
            else:
                blended = opt_weight

            # Apply regime multiplier
            blended *= regime_multiplier

            blended_weights[symbol] = blended

        # Normalize to sum to 1.0
        total_weight = sum(blended_weights.values())
        if total_weight > 0:
            blended_weights = {
                symbol: weight / total_weight
                for symbol, weight in blended_weights.items()
            }

        logger.info("Weight Blending Results:")
        for symbol in sorted(blended_weights.keys()):
            opt_w = optimizer_weights.get(symbol, 0) * 100
            corr_w = correlation_weights.get(symbol, 0) * 100 if correlation_weights else 0
            final_w = blended_weights[symbol] * 100
            logger.info(
                f"  {symbol:12s}: Opt={opt_w:5.1f}% | Corr={corr_w:5.1f}% | "
                f"Final={final_w:5.1f}% (regime: {regime_multiplier:.2f}x)"
            )

        return blended_weights

    def _calculate_final_allocation(
        self,
        weights: Dict[str, float],
        deployable_capital: float
    ) -> Dict[str, float]:
        """Calculate final USD allocation for each position"""
        allocation = {}
        for symbol, weight in weights.items():
            allocation[symbol] = deployable_capital * weight

        return allocation

    def _generate_integrated_rebalancing(
        self,
        positions: List[Dict],
        final_allocation: Dict[str, float],
        total_capital: float
    ) -> List[Dict]:
        """Generate integrated rebalancing actions"""
        actions = []

        # Build current allocation map
        current_allocation = {}
        for pos in positions:
            symbol = pos.get('symbol')
            value = pos.get('market_value', 0)
            current_allocation[symbol] = value

        # Compare current vs target
        all_symbols = set(current_allocation.keys()) | set(final_allocation.keys())

        for symbol in all_symbols:
            current = current_allocation.get(symbol, 0)
            target = final_allocation.get(symbol, 0)
            difference = target - current

            # Only create action if difference is significant (>1% of position or >$10)
            if abs(difference) > max(current * 0.01, 10.0):
                action = {
                    'symbol': symbol,
                    'action': 'increase' if difference > 0 else 'decrease',
                    'current_value': current,
                    'target_value': target,
                    'change_usd': difference,
                    'change_pct': (difference / current * 100) if current > 0 else 100.0,
                    'priority': abs(difference) / total_capital,  # As fraction of total capital
                }
                actions.append(action)

        # Sort by priority
        actions.sort(key=lambda x: x['priority'], reverse=True)

        return actions

    def _generate_integrated_summary(
        self,
        regime_result: Optional[RiskRegimeResult],
        optimization_result: OptimizationResult,
        correlation_result: Optional[CorrelationWeightingResult],
        final_allocation: Dict[str, float],
        rebalancing_actions: List[Dict],
        total_capital: float
    ) -> str:
        """Generate comprehensive summary"""
        lines = [
            "\n🚀 INTEGRATED PORTFOLIO MANAGEMENT SUMMARY",
            "=" * 70,
        ]

        # Regime analysis
        if regime_result:
            lines.append("\n⚡ Market Regime:")
            lines.append(f"  Status: {regime_result.regime_signal.regime.value.upper()}")
            lines.append(f"  Confidence: {regime_result.regime_signal.confidence:.2%}")
            lines.append(f"  Recommended Exposure: {regime_result.allocation.recommended_exposure_pct*100:.0f}%")
            lines.append(f"  Position Sizing: {regime_result.allocation.position_sizing_multiplier:.1f}x")

        # Optimization results
        if optimization_result:
            metrics = optimization_result.efficiency_metrics
            lines.append("\n📈 Portfolio Quality:")
            lines.append(f"  Quality Rating: {metrics.get('portfolio_quality', 'unknown').upper()}")
            lines.append(f"  Average Score: {metrics.get('average_score', 0):.1f}/100")
            lines.append(f"  Position Count: {metrics.get('position_count', 0)}")
            lines.append(f"  Unrealized P&L: ${metrics.get('total_unrealized_pnl', 0):,.2f} ({metrics.get('total_unrealized_pnl_pct', 0):.2f}%)")

        # Correlation analysis
        if correlation_result:
            lines.append("\n🔗 Diversification:")
            lines.append(f"  Correlation Clusters: {len(correlation_result.clusters)}")
            # Calculate average diversification score
            if correlation_result.weights:
                avg_div = np.mean([w.diversification_score for w in correlation_result.weights.values()])
                lines.append(f"  Average Diversification Score: {avg_div:.2f}/1.00")

        # Final allocation
        lines.append("\n💰 Final Allocation:")
        total_deployed = sum(final_allocation.values())
        lines.append(f"  Total Deployed: ${total_deployed:,.2f} ({total_deployed/total_capital*100:.1f}%)")
        lines.append(f"  Reserve: ${total_capital - total_deployed:,.2f} ({(total_capital-total_deployed)/total_capital*100:.1f}%)")

        # Top allocations
        lines.append("\n  Top 5 Allocations:")
        sorted_allocations = sorted(final_allocation.items(), key=lambda x: x[1], reverse=True)[:5]
        for symbol, amount in sorted_allocations:
            pct = (amount / total_deployed * 100) if total_deployed > 0 else 0
            lines.append(f"    {symbol:12s}: ${amount:>10,.2f} ({pct:5.1f}%)")

        # Rebalancing actions
        if rebalancing_actions:
            lines.append(f"\n🔄 Rebalancing Actions Required: {len(rebalancing_actions)}")
            lines.append("\n  Top 3 Priority Actions:")
            for i, action in enumerate(rebalancing_actions[:3], 1):
                lines.append(
                    f"    {i}. {action['action'].upper()} {action['symbol']}: "
                    f"${action['current_value']:,.2f} → ${action['target_value']:,.2f} "
                    f"({action['change_usd']:+,.2f})"
                )
        else:
            lines.append("\n✅ Portfolio is well-balanced - no rebalancing needed")

        lines.append("\n" + "=" * 70)

        return "\n".join(lines)

    def get_position_recommendations(
        self,
        symbol: str,
        result: IntegratedPortfolioResult
    ) -> Dict:
        """
        Get specific recommendations for a symbol

        Args:
            symbol: Trading pair symbol
            result: IntegratedPortfolioResult

        Returns:
            Dictionary with recommendations
        """
        recommendations = {
            'symbol': symbol,
            'market_regime': result.market_regime.value,
            'target_weight': result.final_weights.get(symbol, 0),
            'target_allocation': result.final_allocation.get(symbol, 0),
        }

        # Find rebalancing action if exists
        for action in result.rebalancing_actions:
            if action['symbol'] == symbol:
                recommendations['action'] = action
                break

        # Get optimization score if available
        if result.optimization_result and symbol in result.optimization_result.current_positions:
            pos_score = result.optimization_result.current_positions[symbol]
            recommendations['optimization_score'] = pos_score.total_score
            recommendations['recommendation'] = pos_score.recommendation

        # Get correlation info if available
        if result.correlation_result and symbol in result.correlation_result.weights:
            corr_weight = result.correlation_result.weights[symbol]
            recommendations['diversification_score'] = corr_weight.diversification_score
            recommendations['cluster_id'] = corr_weight.cluster_id

        return recommendations


def create_advanced_portfolio_manager(config: Dict = None) -> AdvancedPortfolioManager:
    """
    Factory function to create AdvancedPortfolioManager instance

    Args:
        config: Optional configuration

    Returns:
        AdvancedPortfolioManager instance
    """
    return AdvancedPortfolioManager(config)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create manager
    manager = create_advanced_portfolio_manager({
        'use_correlation_weighting': True,
        'use_risk_regime': True,
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
        {
            'symbol': 'ETH-USD',
            'quantity': 10,
            'entry_price': 2000,
            'current_price': 2100,
            'market_value': 21000,
            'unrealized_pnl': 1000,
            'pnl_pct': 5.0,
        },
    ]

    market_data = {
        'BTC-USD': {'adx': 35, 'rsi': 65, 'atr': 1200, 'price': 42000, 'volume_ratio': 1.4, 'trend_direction': 1},
        'ETH-USD': {'adx': 30, 'rsi': 60, 'atr': 80, 'price': 2100, 'volume_ratio': 1.3, 'trend_direction': 1},
    }

    # Run integrated management
    result = manager.manage_portfolio(
        positions=positions,
        market_data=market_data,
        total_capital=100000,
        force_optimization=True
    )

    if result:
        print(result.summary)
