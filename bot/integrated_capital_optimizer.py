"""
NIJA Integrated Capital Optimization Engine
============================================

Master integration module that combines:
1. Optimized Position Sizing
2. Dynamic Risk-Reward Optimization
3. Capital Compounding Curves
4. Drawdown Protection
5. Profit Compounding

This creates a complete capital optimization system that maximizes growth
while intelligently managing risk.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

# Import our new optimization modules
from bot.optimized_position_sizer import (
    OptimizedPositionSizer,
    PositionSizingConfig,
    PositionSizingMethod,
    create_optimized_position_sizer
)
from bot.dynamic_risk_reward_optimizer import (
    DynamicRiskRewardOptimizer,
    RiskRewardConfig,
    RiskRewardMode,
    create_risk_reward_optimizer
)
from bot.capital_compounding_curves import (
    CapitalCompoundingCurvesDesigner,
    CompoundingCurveConfig,
    CompoundingCurve,
    create_compounding_curve_designer
)

# Import existing systems
try:
    from bot.drawdown_protection_system import (
        DrawdownProtectionSystem,
        DrawdownConfig,
        get_drawdown_protection
    )
except ImportError:
    from drawdown_protection_system import (
        DrawdownProtectionSystem,
        DrawdownConfig,
        get_drawdown_protection
    )

try:
    from bot.profit_compounding_engine import (
        ProfitCompoundingEngine,
        CompoundingConfig,
        CompoundingStrategy,
        get_compounding_engine
    )
except ImportError:
    from profit_compounding_engine import (
        ProfitCompoundingEngine,
        CompoundingConfig,
        CompoundingStrategy,
        get_compounding_engine
    )

logger = logging.getLogger("nija.capital_optimizer")


@dataclass
class CapitalOptimizationConfig:
    """Master configuration for capital optimization"""
    # Position sizing
    position_sizing_method: str = "hybrid"  # hybrid/kelly/volatility/equity_curve
    base_risk_pct: float = 0.02  # 2% base risk
    enable_kelly: bool = True
    
    # Risk-reward
    risk_reward_mode: str = "optimal"  # optimal/conservative/balanced/aggressive
    target_risk_reward: float = 3.0  # Target 1:3 R:R
    enable_trailing_stops: bool = True
    
    # Compounding
    compounding_curve: str = "kelly_optimized"  # linear/exponential/s_curve/kelly_optimized
    enable_milestones: bool = True
    enable_equity_scaling: bool = True
    
    # Protection
    enable_drawdown_protection: bool = True
    drawdown_halt_threshold: float = 20.0  # Halt at 20% drawdown
    
    # Profit compounding
    compounding_strategy: str = "moderate"  # conservative/moderate/aggressive
    reinvest_pct: float = 0.75  # 75% reinvestment


class IntegratedCapitalOptimizer:
    """
    Master capital optimization engine integrating all systems
    
    This is the single interface for all capital optimization decisions:
    - Position sizing
    - Stop loss / profit target placement
    - Capital compounding
    - Risk scaling
    - Drawdown protection
    """
    
    def __init__(self, base_capital: float,
                 config: Optional[CapitalOptimizationConfig] = None):
        """
        Initialize Integrated Capital Optimizer
        
        Args:
            base_capital: Starting capital
            config: Optimization configuration
        """
        self.config = config or CapitalOptimizationConfig()
        self.base_capital = base_capital
        self.current_capital = base_capital
        
        # Initialize all subsystems
        logger.info("=" * 70)
        logger.info("🚀 Initializing Integrated Capital Optimizer")
        logger.info("=" * 70)
        
        # 1. Position Sizing
        self.position_sizer = create_optimized_position_sizer(
            method=self.config.position_sizing_method,
            base_risk_pct=self.config.base_risk_pct,
            enable_kelly=self.config.enable_kelly,
            enable_equity_scaling=self.config.enable_equity_scaling
        )
        self.position_sizer.set_base_equity(base_capital)
        
        # 2. Risk-Reward Optimizer
        self.risk_reward_optimizer = create_risk_reward_optimizer(
            mode=self.config.risk_reward_mode,
            target_risk_reward=self.config.target_risk_reward,
            enable_trailing=self.config.enable_trailing_stops
        )
        
        # 3. Compounding Curves
        self.compounding_curves = create_compounding_curve_designer(
            base_capital=base_capital,
            curve_type=self.config.compounding_curve,
            enable_milestones=self.config.enable_milestones,
            enable_equity_scaling=self.config.enable_equity_scaling
        )
        
        # 4. Drawdown Protection
        if self.config.enable_drawdown_protection:
            self.drawdown_protection = get_drawdown_protection(
                base_capital=base_capital,
                halt_threshold=self.config.drawdown_halt_threshold
            )
        else:
            self.drawdown_protection = None
        
        # 5. Profit Compounding
        self.profit_compounding = get_compounding_engine(
            base_capital=base_capital,
            strategy=self.config.compounding_strategy
        )
        
        logger.info("✅ All subsystems initialized successfully")
        logger.info("=" * 70)
    
    def calculate_trade_parameters(
        self,
        entry_price: float,
        atr: float,
        direction: str = "long",
        volatility: Optional[float] = None,
        signal_strength: float = 1.0,
        market_regime: str = "neutral",
        trend_strength: Optional[float] = None,
        support_level: Optional[float] = None,
        resistance_level: Optional[float] = None
    ) -> Dict:
        """
        Calculate complete trade parameters (position size, stops, targets)
        
        This is the main entry point for getting optimized trade parameters.
        
        Args:
            entry_price: Planned entry price
            atr: Average True Range
            direction: Trade direction ("long" or "short")
            volatility: Market volatility (optional)
            signal_strength: Signal strength multiplier (0-2)
            market_regime: Market regime (trending/ranging/volatile)
            trend_strength: Trend strength (0-100, e.g., ADX)
            support_level: Support price level (optional)
            resistance_level: Resistance price level (optional)
        
        Returns:
            Complete trade parameters dictionary
        """
        logger.info("=" * 70)
        logger.info("📊 Calculating Optimized Trade Parameters")
        logger.info("=" * 70)
        
        # Check if trading is allowed
        can_trade, trade_reason = self._can_trade()
        if not can_trade:
            logger.warning(f"❌ Trading not allowed: {trade_reason}")
            return {
                'can_trade': False,
                'reason': trade_reason,
                'position_size': 0,
            }
        
        # 1. Calculate optimal stop-loss and profit target
        logger.info("\n🎯 Step 1: Calculating Risk-Reward Levels")
        risk_reward_result = self.risk_reward_optimizer.calculate_optimal_levels(
            entry_price=entry_price,
            atr=atr,
            direction=direction,
            volatility_regime=self._classify_volatility(volatility) if volatility else "normal",
            trend_strength=trend_strength,
            support_level=support_level,
            resistance_level=resistance_level
        )
        
        stop_loss = risk_reward_result['stop_loss']
        profit_target = risk_reward_result['profit_target']
        risk_reward_ratio = risk_reward_result['risk_reward_ratio']
        
        # 2. Calculate optimal position size
        logger.info("\n💰 Step 2: Calculating Optimal Position Size")
        
        # Get available capital (considering drawdown protection)
        available_capital = self._get_available_capital()
        
        position_result = self.position_sizer.calculate_optimal_position_size(
            account_balance=available_capital,
            entry_price=entry_price,
            stop_loss_price=stop_loss,
            profit_target_price=profit_target,
            volatility=volatility,
            signal_strength=signal_strength,
            market_regime=market_regime
        )
        
        # 3. Apply compounding curve adjustments
        logger.info("\n📈 Step 3: Applying Compounding Curve Adjustments")
        compounding_params = self.compounding_curves.get_current_parameters()
        position_multiplier = compounding_params['position_multiplier']
        
        # Adjust position size by compounding multiplier
        adjusted_position_usd = position_result['final_position_usd'] * position_multiplier
        adjusted_shares = adjusted_position_usd / entry_price
        adjusted_risk_usd = adjusted_shares * abs(entry_price - stop_loss)
        adjusted_risk_pct = (adjusted_risk_usd / available_capital) * 100
        
        # 4. Apply drawdown protection if enabled
        if self.drawdown_protection:
            logger.info("\n🛡️  Step 4: Applying Drawdown Protection")
            protection_multiplier = self.drawdown_protection.get_position_size_multiplier()
            adjusted_position_usd *= protection_multiplier
            adjusted_shares *= protection_multiplier
            adjusted_risk_usd *= protection_multiplier
            adjusted_risk_pct *= protection_multiplier
            
            logger.info(f"   Protection Level: {self.drawdown_protection.state.protection_level.value}")
            logger.info(f"   Position Adjustment: {protection_multiplier*100:.0f}%")
        
        # Compile complete result
        result = {
            'can_trade': True,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'profit_target': profit_target,
            'risk_reward_ratio': risk_reward_ratio,
            'position_size_usd': adjusted_position_usd,
            'shares': adjusted_shares,
            'risk_usd': adjusted_risk_usd,
            'risk_pct': adjusted_risk_pct,
            'available_capital': available_capital,
            'compounding_multiplier': position_multiplier,
            'drawdown_multiplier': protection_multiplier if self.drawdown_protection else 1.0,
            'trailing_stop_config': risk_reward_result.get('trailing_stop_levels'),
            'base_position_result': position_result,
            'risk_reward_result': risk_reward_result,
            'compounding_params': compounding_params,
        }
        
        logger.info("\n" + "=" * 70)
        logger.info("✅ OPTIMIZED TRADE PARAMETERS")
        logger.info("=" * 70)
        logger.info(f"Entry:          ${entry_price:.2f}")
        logger.info(f"Stop Loss:      ${stop_loss:.2f}")
        logger.info(f"Profit Target:  ${profit_target:.2f}")
        logger.info(f"Risk:Reward:    1:{risk_reward_ratio:.2f}")
        logger.info(f"Position Size:  ${adjusted_position_usd:.2f} ({adjusted_shares:.4f} shares)")
        logger.info(f"Risk:           ${adjusted_risk_usd:.2f} ({adjusted_risk_pct:.2f}%)")
        logger.info("=" * 70)
        
        return result
    
    def record_trade_result(
        self, entry_price: float, exit_price: float,
        stop_loss: float, profit_target: float,
        direction: str, fees: float = 0.0
    ):
        """
        Record trade result and update all subsystems
        
        Args:
            entry_price: Entry price
            exit_price: Exit price
            stop_loss: Stop loss price
            profit_target: Profit target price
            direction: Trade direction
            fees: Trading fees paid
        """
        # Calculate P&L
        if direction.lower() == "long":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
        
        gross_profit = pnl
        net_profit = pnl - fees
        is_win = net_profit > 0
        
        # Calculate R achieved
        stop_distance = abs(entry_price - stop_loss)
        r_achieved = pnl / stop_distance if stop_distance > 0 else 0
        
        logger.info("=" * 70)
        logger.info(f"📊 Recording Trade Result: {'WIN ✅' if is_win else 'LOSS ❌'}")
        logger.info("=" * 70)
        logger.info(f"P&L:    ${net_profit:.2f}")
        logger.info(f"Fees:   ${fees:.2f}")
        logger.info(f"R:      {r_achieved:.2f}R")
        logger.info("=" * 70)
        
        # Update all subsystems
        
        # 1. Position Sizer (for Kelly)
        self.position_sizer.update_performance(is_win, r_achieved)
        
        # 2. Risk-Reward Optimizer
        self.risk_reward_optimizer.record_trade_result(
            entry_price, exit_price, stop_loss, profit_target, direction
        )
        
        # 3. Compounding Curves
        self.compounding_curves.record_trade(gross_profit, fees, is_win)
        self.compounding_curves.update_capital(self.current_capital + net_profit)
        
        # 4. Drawdown Protection
        if self.drawdown_protection:
            new_capital = self.current_capital + net_profit
            self.drawdown_protection.record_trade(new_capital, is_win)
        
        # 5. Profit Compounding
        self.profit_compounding.record_trade(gross_profit, fees, is_win)
        
        # Update current capital
        self.current_capital += net_profit
        
        logger.info(f"💰 New Capital: ${self.current_capital:.2f}\n")
    
    def update_capital(self, new_capital: float):
        """Update capital across all subsystems"""
        self.current_capital = new_capital
        
        self.position_sizer.set_base_equity(new_capital)
        self.compounding_curves.update_capital(new_capital)
        
        if self.drawdown_protection:
            self.drawdown_protection.update_capital(new_capital)
        
        self.profit_compounding.update_balance(new_capital)
    
    def _can_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed"""
        if self.drawdown_protection:
            return self.drawdown_protection.can_trade()
        return (True, "Trading allowed")
    
    def _get_available_capital(self) -> float:
        """Get capital available for trading"""
        # Use tradeable capital from profit compounding
        tradeable = self.profit_compounding.get_tradeable_capital()
        
        # Ensure it doesn't exceed current capital
        return min(tradeable, self.current_capital)
    
    def _classify_volatility(self, volatility: float) -> str:
        """Classify volatility regime"""
        if volatility < 0.01:
            return "low"
        elif volatility > 0.03:
            return "high"
        else:
            return "normal"
    
    def get_comprehensive_status(self) -> Dict:
        """Get comprehensive status of all subsystems"""
        status = {
            'current_capital': self.current_capital,
            'base_capital': self.base_capital,
            'total_profit': self.current_capital - self.base_capital,
            'roi_pct': ((self.current_capital - self.base_capital) / self.base_capital) * 100,
        }
        
        # Add compounding curve info
        compounding_params = self.compounding_curves.get_current_parameters()
        status.update({
            'reinvest_pct': compounding_params['reinvest_pct'],
            'position_multiplier': compounding_params['position_multiplier'],
            'milestones_achieved': compounding_params['milestones_achieved'],
            'next_milestone': compounding_params['next_milestone'],
        })
        
        # Add drawdown protection info
        if self.drawdown_protection:
            status.update({
                'drawdown_pct': self.drawdown_protection.state.drawdown_pct,
                'protection_level': self.drawdown_protection.state.protection_level.value,
                'can_trade': self.drawdown_protection.can_trade()[0],
            })
        
        # Add risk-reward stats
        rr_stats = self.risk_reward_optimizer.get_performance_summary()
        status.update({
            'win_rate': rr_stats['win_rate'],
            'avg_win_rr': rr_stats['avg_win_rr'],
            'expectancy': rr_stats['expectancy'],
        })
        
        return status
    
    def generate_comprehensive_report(self) -> str:
        """Generate comprehensive optimization report"""
        report = [
            "\n" + "=" * 90,
            "INTEGRATED CAPITAL OPTIMIZATION ENGINE - COMPREHENSIVE REPORT",
            "=" * 90,
        ]
        
        # Overall status
        status = self.get_comprehensive_status()
        
        report.extend([
            "\n💰 OVERALL STATUS",
            "-" * 90,
            f"  Base Capital:         ${self.base_capital:>12,.2f}",
            f"  Current Capital:      ${self.current_capital:>12,.2f}",
            f"  Total Profit:         ${status['total_profit']:>12,.2f}",
            f"  ROI:                  {status['roi_pct']:>12.2f}%",
            ""
        ])
        
        # Compounding status
        if status.get('next_milestone'):
            nm = status['next_milestone']
            report.extend([
                "📍 NEXT MILESTONE",
                "-" * 90,
                f"  Target: {nm['name']} at ${nm['target']:,.2f}",
                f"  Progress: {nm['progress_pct']:.1f}%",
                f"  Remaining: ${nm['remaining']:,.2f}",
                ""
            ])
        
        # Protection status
        if self.drawdown_protection:
            report.extend([
                "🛡️  PROTECTION STATUS",
                "-" * 90,
                f"  Protection Level:     {status['protection_level'].upper()}",
                f"  Drawdown:             {status['drawdown_pct']:.2f}%",
                f"  Can Trade:            {'YES ✅' if status['can_trade'] else 'NO ❌'}",
                ""
            ])
        
        # Performance metrics
        report.extend([
            "📊 PERFORMANCE METRICS",
            "-" * 90,
            f"  Win Rate:             {status['win_rate']*100:>12.1f}%",
            f"  Average Win:          {status['avg_win_rr']:>12.2f}R",
            f"  Expectancy:           {status['expectancy']:>12.2f}R",
            f"  Reinvestment:         {status['reinvest_pct']*100:>12.0f}%",
            f"  Position Multiplier:  {status['position_multiplier']:>12.2f}x",
            ""
        ])
        
        report.append("=" * 90 + "\n")
        
        return "\n".join(report)


def create_integrated_optimizer(
    base_capital: float,
    position_sizing_method: str = "hybrid",
    risk_reward_mode: str = "optimal",
    compounding_curve: str = "kelly_optimized",
    enable_all_features: bool = True
) -> IntegratedCapitalOptimizer:
    """
    Factory function to create IntegratedCapitalOptimizer
    
    Args:
        base_capital: Starting capital
        position_sizing_method: Position sizing method
        risk_reward_mode: Risk-reward optimization mode
        compounding_curve: Compounding curve type
        enable_all_features: Enable all optimization features
    
    Returns:
        IntegratedCapitalOptimizer instance
    """
    config = CapitalOptimizationConfig(
        position_sizing_method=position_sizing_method,
        risk_reward_mode=risk_reward_mode,
        compounding_curve=compounding_curve,
        enable_kelly=enable_all_features,
        enable_trailing_stops=enable_all_features,
        enable_milestones=enable_all_features,
        enable_equity_scaling=enable_all_features,
        enable_drawdown_protection=enable_all_features,
    )
    
    return IntegratedCapitalOptimizer(base_capital, config)


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create integrated optimizer
    optimizer = create_integrated_optimizer(
        base_capital=10000.0,
        position_sizing_method="hybrid",
        risk_reward_mode="optimal",
        compounding_curve="kelly_optimized",
        enable_all_features=True
    )
    
    print("\n" + "=" * 90)
    print("INTEGRATED CAPITAL OPTIMIZER - EXAMPLE TRADE")
    print("=" * 90)
    
    # Calculate trade parameters
    params = optimizer.calculate_trade_parameters(
        entry_price=100.0,
        atr=2.5,
        direction="long",
        volatility=0.015,
        signal_strength=1.2,
        market_regime="trending",
        trend_strength=35,
        support_level=97.0,
        resistance_level=110.0
    )
    
    if params['can_trade']:
        print(f"\n✅ TRADE APPROVED")
        print(f"   Position Size: ${params['position_size_usd']:,.2f}")
        print(f"   Risk: ${params['risk_usd']:.2f} ({params['risk_pct']:.2f}%)")
        print(f"   R:R Ratio: 1:{params['risk_reward_ratio']:.2f}")
        
        # Simulate trade execution and result
        print(f"\n📈 Simulating trade execution...")
        
        # Assume exit at profit target
        optimizer.record_trade_result(
            entry_price=params['entry_price'],
            exit_price=params['profit_target'],
            stop_loss=params['stop_loss'],
            profit_target=params['profit_target'],
            direction="long",
            fees=10.0
        )
    
    # Generate comprehensive report
    print(optimizer.generate_comprehensive_report())
