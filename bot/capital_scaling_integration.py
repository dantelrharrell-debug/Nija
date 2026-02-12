"""
NIJA Capital Scaling Integration
==================================

Integrates capital scaling logic into the main trading flow.
Provides a unified interface for position sizing that incorporates:
- Base capital tracking
- Profit compounding
- Drawdown protection
- Performance attribution
- Risk-adjusted position sizing

This module bridges the capital scaling engine with the trading strategy.

Author: NIJA Trading Systems
Version: 1.0
Date: February 12, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger("nija.capital_scaling")

# Import capital scaling components
try:
    from capital_scaling_engine import (
        CapitalScalingEngine,
        CapitalEngineConfig,
        get_capital_engine
    )
    from autonomous_scaling_engine import (
        AutonomousScalingEngine,
        AutonomousScalingConfig,
        MarketRegime
    )
    from performance_attribution import (
        PerformanceAttribution,
        get_performance_attribution
    )
    from performance_metrics import (
        PerformanceMetricsCalculator,
        PerformanceSnapshot,
        get_performance_calculator
    )
except ImportError:
    try:
        from bot.capital_scaling_engine import (
            CapitalScalingEngine,
            CapitalEngineConfig,
            get_capital_engine
        )
        from bot.autonomous_scaling_engine import (
            AutonomousScalingEngine,
            AutonomousScalingConfig,
            MarketRegime
        )
        from bot.performance_attribution import (
            PerformanceAttribution,
            get_performance_attribution
        )
        from bot.performance_metrics import (
            PerformanceMetricsCalculator,
            PerformanceSnapshot,
            get_performance_calculator
        )
    except ImportError as e:
        logger.error(f"Failed to import capital scaling components: {e}")
        raise


@dataclass
class PositionSizingParams:
    """Parameters for position sizing calculation"""
    available_balance: float
    current_price: float
    volatility: float
    expected_return: float
    signal_strength: float  # 0.0 to 1.0
    market_regime: str
    strategy_name: str
    max_position_pct: float = 0.10  # FROZEN RISK LIMIT - maximum % of capital per trade


@dataclass
class PositionSizingResult:
    """Result of position sizing calculation"""
    position_size_usd: float
    position_size_base: float  # In base currency units
    position_pct_of_capital: float
    scaling_factors: Dict[str, float]  # Breakdown of scaling adjustments
    can_trade: bool
    reason: str


class CapitalScalingIntegration:
    """
    Unified Capital Scaling Integration
    
    Coordinates between:
    - Capital Scaling Engine (compounding, drawdown protection)
    - Autonomous Scaling Engine (volatility, regime adjustments)
    - Performance Attribution (tracking sources of returns)
    - Performance Metrics (investor-grade metrics)
    
    Provides a single interface for position sizing that incorporates
    all capital management and risk adjustment logic.
    """
    
    def __init__(
        self,
        initial_capital: float,
        current_capital: Optional[float] = None,
        base_position_pct: float = 0.05,
        enable_autonomous_scaling: bool = True,
        enable_attribution: bool = True,
        compounding_strategy: str = "moderate"
    ):
        """
        Initialize capital scaling integration
        
        Args:
            initial_capital: Starting capital
            current_capital: Current capital (defaults to initial_capital)
            base_position_pct: Base position size as % of capital (default: 5%)
            enable_autonomous_scaling: Enable autonomous volatility/regime scaling
            enable_attribution: Enable performance attribution tracking
            compounding_strategy: Compounding strategy (conservative/moderate/aggressive)
        """
        self.initial_capital = initial_capital
        self.current_capital = current_capital or initial_capital
        self.base_position_pct = base_position_pct
        
        logger.info("=" * 70)
        logger.info("🚀 INITIALIZING CAPITAL SCALING INTEGRATION")
        logger.info("=" * 70)
        
        # Initialize capital scaling engine
        logger.info("📊 Initializing Capital Scaling Engine...")
        self.capital_engine = get_capital_engine(
            base_capital=initial_capital,
            current_capital=self.current_capital,
            strategy=compounding_strategy,
            enable_protection=True,
            enable_milestones=True
        )
        
        # Initialize autonomous scaling if enabled
        self.autonomous_engine: Optional[AutonomousScalingEngine] = None
        if enable_autonomous_scaling:
            try:
                logger.info("🤖 Initializing Autonomous Scaling Engine...")
                from bot.autonomous_scaling_engine import get_autonomous_engine
                
                self.autonomous_engine = get_autonomous_engine(
                    base_capital=initial_capital,
                    current_capital=self.current_capital,
                    enable_volatility_leverage=True,
                    enable_regime_allocation=True
                )
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize autonomous scaling: {e}")
        
        # Initialize performance attribution if enabled
        self.attribution: Optional[PerformanceAttribution] = None
        if enable_attribution:
            try:
                logger.info("📈 Initializing Performance Attribution...")
                self.attribution = get_performance_attribution()
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize attribution: {e}")
        
        # Initialize performance metrics
        try:
            logger.info("📊 Initializing Performance Metrics...")
            self.metrics_calculator = get_performance_calculator(
                initial_capital=initial_capital
            )
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize metrics calculator: {e}")
            self.metrics_calculator = None
        
        # Trade tracking
        self.trade_count = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        logger.info("=" * 70)
        logger.info("✅ CAPITAL SCALING INTEGRATION READY")
        logger.info("=" * 70)
        logger.info(f"   Initial Capital:        ${self.initial_capital:,.2f}")
        logger.info(f"   Current Capital:        ${self.current_capital:,.2f}")
        logger.info(f"   Base Position %:        {self.base_position_pct * 100:.1f}%")
        logger.info(f"   Compounding:            {compounding_strategy}")
        logger.info(f"   Autonomous Scaling:     {'ENABLED' if self.autonomous_engine else 'DISABLED'}")
        logger.info(f"   Attribution:            {'ENABLED' if self.attribution else 'DISABLED'}")
        logger.info("=" * 70)
    
    def calculate_position_size(
        self,
        params: PositionSizingParams
    ) -> PositionSizingResult:
        """
        Calculate optimal position size with all scaling factors
        
        **CRITICAL: Respects frozen risk limits - position size will NEVER exceed
        params.max_position_pct regardless of scaling factors**
        
        Args:
            params: PositionSizingParams with all required inputs
        
        Returns:
            PositionSizingResult with position size and scaling breakdown
        """
        # Check if trading is allowed
        can_trade, reason = self.capital_engine.can_trade()
        if not can_trade:
            return PositionSizingResult(
                position_size_usd=0.0,
                position_size_base=0.0,
                position_pct_of_capital=0.0,
                scaling_factors={},
                can_trade=False,
                reason=reason
            )
        
        # FROZEN RISK LIMIT - Calculate absolute maximum position size
        # This limit CANNOT be exceeded regardless of any scaling factors
        frozen_max_position_usd = params.available_balance * params.max_position_pct
        
        # Start with base position size
        base_size_usd = params.available_balance * self.base_position_pct
        
        scaling_factors = {
            'base': 1.0,
            'signal_strength': params.signal_strength,
            'compounding': 1.0,
            'drawdown_protection': 1.0,
            'volatility_adjustment': 1.0,
            'regime_adjustment': 1.0,
            'frozen_limit_applied': False  # Track if we hit the frozen limit
        }
        
        # Apply capital scaling engine adjustments
        capital_scaled_size = self.capital_engine.get_optimal_position_size(
            available_balance=params.available_balance
        )
        scaling_factors['compounding'] = capital_scaled_size / base_size_usd if base_size_usd > 0 else 1.0
        
        # Apply autonomous scaling adjustments if available
        if self.autonomous_engine:
            try:
                # Update market regime
                self.autonomous_engine.update_market_regime(MarketRegime(params.market_regime))
                
                # Get autonomous position size
                auto_size = self.autonomous_engine.get_optimal_position_size(
                    available_balance=params.available_balance,
                    expected_return=params.expected_return,
                    volatility=params.volatility
                )
                
                # Extract additional scaling factors
                status = self.autonomous_engine.get_status()
                if 'volatility_multiplier' in status:
                    scaling_factors['volatility_adjustment'] = status['volatility_multiplier']
                if 'regime_multiplier' in status:
                    scaling_factors['regime_adjustment'] = status['regime_multiplier']
                
                # Use the more conservative of the two sizes
                final_size_usd = min(capital_scaled_size, auto_size)
            except Exception as e:
                logger.warning(f"⚠️ Error in autonomous scaling: {e}")
                final_size_usd = capital_scaled_size
        else:
            final_size_usd = capital_scaled_size
        
        # Apply signal strength adjustment
        final_size_usd *= params.signal_strength
        
        # 🔒 ENFORCE FROZEN RISK LIMIT - This is the hard cap that cannot be exceeded
        if final_size_usd > frozen_max_position_usd:
            logger.info(
                f"🔒 Frozen risk limit applied: ${final_size_usd:.2f} capped to "
                f"${frozen_max_position_usd:.2f} ({params.max_position_pct*100:.1f}% max)"
            )
            final_size_usd = frozen_max_position_usd
            scaling_factors['frozen_limit_applied'] = True
        
        # Calculate position size in base currency units
        position_size_base = final_size_usd / params.current_price if params.current_price > 0 else 0.0
        
        # Calculate percentage of capital
        position_pct = (final_size_usd / params.available_balance * 100) if params.available_balance > 0 else 0.0
        
        return PositionSizingResult(
            position_size_usd=final_size_usd,
            position_size_base=position_size_base,
            position_pct_of_capital=position_pct,
            scaling_factors=scaling_factors,
            can_trade=True,
            reason="Position sized with all scaling factors (frozen limits respected)"
        )
    
    def record_trade(
        self,
        trade_id: str,
        symbol: str,
        strategy: str,
        market_regime: str,
        entry_price: float,
        exit_price: Optional[float],
        position_size: float,
        side: str,
        pnl: float,
        fees: float,
        risk_capital: float,
        new_capital: float
    ):
        """
        Record a completed trade and update all systems
        
        Args:
            trade_id: Unique trade ID
            symbol: Trading symbol
            strategy: Strategy name
            market_regime: Market regime during trade
            entry_price: Entry price
            exit_price: Exit price (None if still open)
            position_size: Position size
            side: 'long' or 'short'
            pnl: Gross PnL
            fees: Trading fees
            risk_capital: Capital at risk
            new_capital: Updated capital after trade
        """
        is_win = pnl > fees
        net_pnl = pnl - fees
        
        # Update trade counts
        self.trade_count += 1
        if is_win:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Update capital scaling engine
        self.capital_engine.record_trade(
            profit=pnl,
            fees=fees,
            is_win=is_win,
            new_capital=new_capital
        )
        
        # Update current capital
        self.current_capital = new_capital
        
        # Update performance attribution if enabled
        if self.attribution and exit_price is not None:
            try:
                self.attribution.record_trade(
                    trade_id=trade_id,
                    symbol=symbol,
                    strategy=strategy,
                    market_regime=market_regime,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    position_size=position_size,
                    side=side,
                    pnl=pnl,
                    fees=fees,
                    risk_capital=risk_capital
                )
            except Exception as e:
                logger.warning(f"⚠️ Error recording attribution: {e}")
        
        # Update performance metrics if enabled
        if self.metrics_calculator:
            try:
                # Create performance snapshot
                snapshot = PerformanceSnapshot(
                    timestamp=datetime.now(),
                    nav=new_capital,
                    equity=new_capital,
                    cash=new_capital,  # Simplified - would need actual breakdown
                    positions_value=0.0,
                    unrealized_pnl=0.0,
                    realized_pnl_today=net_pnl,
                    total_trades=self.trade_count,
                    winning_trades=self.winning_trades,
                    losing_trades=self.losing_trades
                )
                
                self.metrics_calculator.record_snapshot(snapshot)
            except Exception as e:
                logger.warning(f"⚠️ Error recording metrics: {e}")
        
        logger.info(
            f"📊 Trade recorded: {trade_id} | "
            f"{'WIN ✅' if is_win else 'LOSS ❌'} | "
            f"PnL: ${net_pnl:.2f} | "
            f"Capital: ${new_capital:.2f}"
        )
    
    def update_capital(self, new_capital: float):
        """
        Update current capital across all systems
        
        Args:
            new_capital: New capital amount
        """
        self.current_capital = new_capital
        self.capital_engine.update_capital(new_capital)
        
        if self.autonomous_engine:
            self.autonomous_engine.update_capital(new_capital)
    
    def get_status(self) -> Dict:
        """
        Get comprehensive status from all systems
        
        Returns:
            Dictionary with complete status
        """
        status = {
            'initial_capital': self.initial_capital,
            'current_capital': self.current_capital,
            'total_return': self.current_capital - self.initial_capital,
            'total_return_pct': ((self.current_capital - self.initial_capital) / self.initial_capital * 100) if self.initial_capital > 0 else 0.0,
            'trade_count': self.trade_count,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': (self.winning_trades / self.trade_count * 100) if self.trade_count > 0 else 0.0
        }
        
        # Add capital engine status
        capital_status = self.capital_engine.get_capital_status()
        status['capital_engine'] = capital_status
        
        # Add autonomous engine status if available
        if self.autonomous_engine:
            try:
                auto_status = self.autonomous_engine.get_status()
                status['autonomous_engine'] = auto_status
            except Exception as e:
                logger.warning(f"⚠️ Error getting autonomous status: {e}")
        
        # Add performance metrics if available
        if self.metrics_calculator:
            try:
                metrics = self.metrics_calculator.calculate_metrics()
                status['performance_metrics'] = {
                    'sharpe_ratio': metrics.sharpe_ratio,
                    'sortino_ratio': metrics.sortino_ratio,
                    'max_drawdown_pct': metrics.max_drawdown_pct,
                    'current_drawdown_pct': metrics.current_drawdown_pct,
                    'profit_factor': metrics.profit_factor,
                    'annualized_return_pct': metrics.annualized_return_pct
                }
            except Exception as e:
                logger.warning(f"⚠️ Error getting performance metrics: {e}")
        
        return status
    
    def generate_comprehensive_report(self) -> str:
        """
        Generate comprehensive report from all systems
        
        Returns:
            Formatted report string
        """
        report = [
            "\n" + "=" * 90,
            "COMPREHENSIVE CAPITAL SCALING & PERFORMANCE REPORT",
            "=" * 90,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]
        
        # Get status
        status = self.get_status()
        
        # Overall performance
        report.extend([
            "📊 OVERALL PERFORMANCE",
            "-" * 90,
            f"  Initial Capital:      ${status['initial_capital']:>12,.2f}",
            f"  Current Capital:      ${status['current_capital']:>12,.2f}",
            f"  Total Return:         ${status['total_return']:>12,.2f} ({status['total_return_pct']:+.2f}%)",
            f"  Total Trades:         {status['trade_count']:>12}",
            f"  Win Rate:             {status['win_rate']:>12.1f}%",
            ""
        ])
        
        # Capital engine report
        report.append(self.capital_engine.get_comprehensive_report())
        
        # Performance metrics if available
        if 'performance_metrics' in status:
            pm = status['performance_metrics']
            report.extend([
                "📈 PERFORMANCE METRICS",
                "-" * 90,
                f"  Sharpe Ratio:         {pm['sharpe_ratio']:>12.2f}",
                f"  Sortino Ratio:        {pm['sortino_ratio']:>12.2f}",
                f"  Max Drawdown:         {pm['max_drawdown_pct']:>12.2f}%",
                f"  Current Drawdown:     {pm['current_drawdown_pct']:>12.2f}%",
                f"  Profit Factor:        {pm['profit_factor']:>12.2f}",
                f"  Annualized Return:    {pm['annualized_return_pct']:>12.2f}%",
                ""
            ])
        
        # Attribution report if available
        if self.attribution:
            report.append(self.attribution.generate_attribution_report())
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)


# Singleton instance
_capital_scaling_integration: Optional[CapitalScalingIntegration] = None


def get_capital_scaling_integration(
    initial_capital: float = 1000.0,
    current_capital: Optional[float] = None,
    base_position_pct: float = 0.05,
    reset: bool = False
) -> CapitalScalingIntegration:
    """
    Get or create the capital scaling integration singleton
    
    Args:
        initial_capital: Starting capital (only used on first creation)
        current_capital: Current capital (optional)
        base_position_pct: Base position size percentage (default: 5%)
        reset: Force reset and create new instance
    
    Returns:
        CapitalScalingIntegration instance
    """
    global _capital_scaling_integration
    
    if _capital_scaling_integration is None or reset:
        _capital_scaling_integration = CapitalScalingIntegration(
            initial_capital=initial_capital,
            current_capital=current_capital,
            base_position_pct=base_position_pct
        )
    
    return _capital_scaling_integration


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create integration
    integration = get_capital_scaling_integration(
        initial_capital=10000.0,
        base_position_pct=0.05
    )
    
    print("\n" + "=" * 90)
    print("TESTING CAPITAL SCALING INTEGRATION")
    print("=" * 90 + "\n")
    
    # Test position sizing
    params = PositionSizingParams(
        available_balance=10000.0,
        current_price=45000.0,
        volatility=0.25,
        expected_return=0.15,
        signal_strength=0.8,
        market_regime="bull_trending",
        strategy_name="APEX_V71"
    )
    
    result = integration.calculate_position_size(params)
    
    print("📊 Position Sizing Result:")
    print(f"  Position Size (USD): ${result.position_size_usd:,.2f}")
    print(f"  Position Size (Base): {result.position_size_base:.6f}")
    print(f"  Position % of Capital: {result.position_pct_of_capital:.2f}%")
    print(f"  Can Trade: {result.can_trade}")
    print(f"  Reason: {result.reason}")
    print("\n  Scaling Factors:")
    for factor, value in result.scaling_factors.items():
        print(f"    {factor}: {value:.4f}")
    
    # Simulate some trades
    print("\n" + "=" * 90)
    print("SIMULATING TRADES")
    print("=" * 90 + "\n")
    
    capital = 10000.0
    
    # Winning trade
    print("📈 Recording winning trade...")
    integration.record_trade(
        trade_id="trade_001",
        symbol="BTC-USD",
        strategy="APEX_V71",
        market_regime="bull_trending",
        entry_price=45000.0,
        exit_price=46000.0,
        position_size=0.011,
        side="long",
        pnl=100.0,
        fees=2.0,
        risk_capital=500.0,
        new_capital=capital + 98.0
    )
    capital += 98.0
    
    # Losing trade
    print("📉 Recording losing trade...")
    integration.record_trade(
        trade_id="trade_002",
        symbol="ETH-USD",
        strategy="APEX_V71",
        market_regime="volatile",
        entry_price=3000.0,
        exit_price=2950.0,
        position_size=0.166,
        side="long",
        pnl=-50.0,
        fees=1.5,
        risk_capital=500.0,
        new_capital=capital - 51.5
    )
    capital -= 51.5
    
    # Generate comprehensive report
    print("\n" + integration.generate_comprehensive_report())
