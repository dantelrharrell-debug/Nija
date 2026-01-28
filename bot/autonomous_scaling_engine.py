"""
🔥 NIJA AUTONOMOUS SCALING ENGINE 🔥

Advanced capital management with autonomous scaling features:
- Capital auto-scaling based on market conditions
- Risk-adjusted position sizing with volatility adaptation
- Volatility-based leverage adjustments
- Market regime detection and allocation
- Enhanced auto-compounding logic
- Real-time parameter optimization

This extends the Capital Scaling & Compounding Engine with intelligent,
autonomous decision-making for position sizing and capital deployment.

Author: NIJA Trading Systems
Version: 7.3.0
Date: January 28, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math

try:
    from capital_scaling_engine import CapitalScalingEngine, CapitalEngineConfig, get_capital_engine
except ImportError:
    from bot.capital_scaling_engine import CapitalScalingEngine, CapitalEngineConfig, get_capital_engine

try:
    from version_info import get_version_string, get_full_version_info
except ImportError:
    def get_version_string():
        return "NIJA v7.3.0 (Autonomous Scaling Engine)"
    def get_full_version_info():
        return {'version': '7.3.0', 'release_name': 'Autonomous Scaling Engine'}

logger = logging.getLogger("nija.autonomous_scaling")


class MarketRegime(Enum):
    """Market regime classifications"""
    BULL_TRENDING = "bull_trending"  # Strong uptrend, high momentum
    BEAR_TRENDING = "bear_trending"  # Strong downtrend
    RANGING = "ranging"  # Sideways, low volatility
    VOLATILE = "volatile"  # High volatility, choppy
    CRISIS = "crisis"  # Extreme volatility, risk-off


class VolatilityState(Enum):
    """Volatility state classifications"""
    VERY_LOW = "very_low"  # <10% annualized
    LOW = "low"  # 10-20%
    NORMAL = "normal"  # 20-40%
    HIGH = "high"  # 40-60%
    EXTREME = "extreme"  # >60%


@dataclass
class MarketConditions:
    """Current market conditions for autonomous decision-making"""
    volatility_pct: float  # Annualized volatility %
    trend_strength: float  # -1.0 (strong bear) to +1.0 (strong bull)
    regime: MarketRegime  # Current market regime
    volatility_state: VolatilityState  # Current volatility classification
    momentum_score: float  # -1.0 to +1.0
    liquidity_score: float  # 0.0 (illiquid) to 1.0 (highly liquid)
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class AutonomousScalingConfig:
    """Configuration for autonomous scaling engine"""
    # Volatility-based leverage
    enable_volatility_leverage: bool = True
    min_leverage: float = 0.5  # Minimum 50% of base position
    max_leverage: float = 2.0  # Maximum 200% of base position
    volatility_leverage_sensitivity: float = 1.0  # How responsive to volatility
    
    # Risk adjustment
    enable_risk_adjustment: bool = True
    risk_free_rate: float = 0.05  # 5% annual risk-free rate
    target_sharpe_ratio: float = 2.0  # Target Sharpe ratio
    
    # Market regime allocation
    enable_regime_allocation: bool = True
    regime_allocations: Dict[MarketRegime, float] = None  # % of capital per regime
    
    # Auto-compounding enhancements
    enable_adaptive_compounding: bool = True
    performance_based_reinvestment: bool = True  # Adjust based on performance
    
    # Real-time optimization
    enable_realtime_optimization: bool = True
    optimization_window_days: int = 30  # Lookback for optimization
    
    def __post_init__(self):
        if self.regime_allocations is None:
            # Default regime allocations
            self.regime_allocations = {
                MarketRegime.BULL_TRENDING: 1.0,  # 100% allocation
                MarketRegime.BEAR_TRENDING: 0.3,  # 30% allocation (defensive)
                MarketRegime.RANGING: 0.6,  # 60% allocation
                MarketRegime.VOLATILE: 0.4,  # 40% allocation (reduced risk)
                MarketRegime.CRISIS: 0.1,  # 10% allocation (preserve capital)
            }


class AutonomousScalingEngine:
    """
    🔥 NIJA Autonomous Scaling Engine 🔥
    
    Extends Capital Scaling Engine with intelligent autonomous features:
    1. Volatility-based position sizing
    2. Market regime adaptation
    3. Risk-adjusted leverage
    4. Adaptive compounding
    5. Real-time parameter optimization
    """
    
    def __init__(self, base_capital: float,
                 current_capital: Optional[float] = None,
                 base_config: Optional[CapitalEngineConfig] = None,
                 autonomous_config: Optional[AutonomousScalingConfig] = None):
        """
        Initialize Autonomous Scaling Engine
        
        Args:
            base_capital: Starting capital
            current_capital: Current capital (optional)
            base_config: Base capital engine config
            autonomous_config: Autonomous features config
        """
        # Initialize base capital engine
        self.capital_engine = CapitalScalingEngine(
            base_capital,
            current_capital,
            base_config or CapitalEngineConfig()
        )
        
        self.config = autonomous_config or AutonomousScalingConfig()
        
        # Market conditions tracking
        self.current_conditions: Optional[MarketConditions] = None
        self.conditions_history: List[MarketConditions] = []
        
        # Performance tracking for optimization
        self.recent_trades: List[Dict] = []
        self.optimal_parameters: Dict = {}
        
        logger.info("=" * 70)
        logger.info("🔥 NIJA AUTONOMOUS SCALING ENGINE 🔥")
        logger.info("=" * 70)
        logger.info(f"Version: {get_version_string()}")
        logger.info(f"Base Capital: ${base_capital:.2f}")
        logger.info(f"Volatility Leverage: {'ENABLED' if self.config.enable_volatility_leverage else 'DISABLED'}")
        logger.info(f"Risk Adjustment: {'ENABLED' if self.config.enable_risk_adjustment else 'DISABLED'}")
        logger.info(f"Regime Allocation: {'ENABLED' if self.config.enable_regime_allocation else 'DISABLED'}")
        logger.info(f"Adaptive Compounding: {'ENABLED' if self.config.enable_adaptive_compounding else 'DISABLED'}")
        logger.info("=" * 70)
    
    def update_market_conditions(self, conditions: MarketConditions):
        """
        Update current market conditions for autonomous decision-making
        
        Args:
            conditions: Current market conditions
        """
        self.current_conditions = conditions
        self.conditions_history.append(conditions)
        
        # Keep only recent history (last 100 updates)
        if len(self.conditions_history) > 100:
            self.conditions_history = self.conditions_history[-100:]
        
        logger.debug(f"📊 Market conditions updated: {conditions.regime.value}, "
                    f"Vol: {conditions.volatility_pct:.1f}%, "
                    f"Trend: {conditions.trend_strength:+.2f}")
    
    def calculate_volatility_leverage(self, base_position: float,
                                     volatility_pct: float) -> float:
        """
        Calculate volatility-adjusted position size
        
        Lower volatility = higher leverage (up to max)
        Higher volatility = lower leverage (down to min)
        
        Args:
            base_position: Base position size
            volatility_pct: Current annualized volatility %
            
        Returns:
            Adjusted position size
        """
        if not self.config.enable_volatility_leverage:
            return base_position
        
        # Normalize volatility (20-40% is "normal")
        normal_vol = 30.0
        vol_ratio = normal_vol / max(volatility_pct, 5.0)  # Avoid division by very small numbers
        
        # Apply sensitivity
        leverage = vol_ratio ** self.config.volatility_leverage_sensitivity
        
        # Clamp to configured range
        leverage = max(self.config.min_leverage, min(self.config.max_leverage, leverage))
        
        adjusted_position = base_position * leverage
        
        logger.debug(f"💫 Volatility leverage: {leverage:.2f}x "
                    f"(Vol: {volatility_pct:.1f}%, "
                    f"Base: ${base_position:.2f} → Adjusted: ${adjusted_position:.2f})")
        
        return adjusted_position
    
    def calculate_regime_allocation(self, base_allocation: float,
                                   regime: MarketRegime) -> float:
        """
        Adjust allocation based on market regime
        
        Args:
            base_allocation: Base allocation amount
            regime: Current market regime
            
        Returns:
            Regime-adjusted allocation
        """
        if not self.config.enable_regime_allocation:
            return base_allocation
        
        regime_multiplier = self.config.regime_allocations.get(regime, 1.0)
        adjusted = base_allocation * regime_multiplier
        
        logger.debug(f"🎯 Regime allocation: {regime.value} → {regime_multiplier:.1%} "
                    f"(${base_allocation:.2f} → ${adjusted:.2f})")
        
        return adjusted
    
    def calculate_risk_adjusted_size(self, base_position: float,
                                    expected_return: float,
                                    volatility: float) -> float:
        """
        Calculate risk-adjusted position size using Sharpe ratio optimization
        
        Args:
            base_position: Base position size
            expected_return: Expected return (annualized)
            volatility: Volatility (annualized std dev)
            
        Returns:
            Risk-adjusted position size
        """
        if not self.config.enable_risk_adjustment:
            return base_position
        
        # Calculate Sharpe ratio
        excess_return = expected_return - self.config.risk_free_rate
        sharpe = excess_return / volatility if volatility > 0 else 0
        
        # Adjust position based on Sharpe vs target
        sharpe_ratio = sharpe / self.config.target_sharpe_ratio
        sharpe_ratio = max(0.3, min(1.5, sharpe_ratio))  # Clamp to 30%-150%
        
        adjusted = base_position * sharpe_ratio
        
        logger.debug(f"📊 Risk-adjusted size: Sharpe {sharpe:.2f} "
                    f"(Target: {self.config.target_sharpe_ratio:.2f}) → "
                    f"{sharpe_ratio:.1%} of base (${adjusted:.2f})")
        
        return adjusted
    
    def get_optimal_position_size(self, available_balance: float,
                                  expected_return: Optional[float] = None,
                                  volatility: Optional[float] = None) -> float:
        """
        Calculate optimal position size with all autonomous adjustments
        
        Combines:
        1. Base capital engine position sizing
        2. Volatility-based leverage
        3. Market regime allocation
        4. Risk-adjusted sizing
        
        Args:
            available_balance: Available capital
            expected_return: Expected return (optional, for risk adjustment)
            volatility: Volatility estimate (optional)
            
        Returns:
            Optimal position size considering all factors
        """
        # Start with base capital engine calculation
        base_position = self.capital_engine.get_optimal_position_size(available_balance)
        
        if base_position == 0:
            return 0.0  # Respect capital engine restrictions (e.g., halted)
        
        position = base_position
        
        # Apply market conditions adjustments if available
        if self.current_conditions:
            # 1. Volatility leverage
            if volatility is None:
                volatility = self.current_conditions.volatility_pct
            position = self.calculate_volatility_leverage(position, volatility)
            
            # 2. Regime allocation
            position = self.calculate_regime_allocation(position, self.current_conditions.regime)
            
            # 3. Risk adjustment (if expected return provided)
            if expected_return is not None and volatility is not None:
                position = self.calculate_risk_adjusted_size(position, expected_return, volatility)
        
        # Never exceed available balance
        return min(position, available_balance)
    
    def record_trade(self, profit: float, fees: float, is_win: bool,
                    new_capital: float, trade_data: Optional[Dict] = None):
        """
        Record trade with autonomous features
        
        Args:
            profit: Gross profit
            fees: Fees paid
            is_win: True if profitable
            new_capital: Capital after trade
            trade_data: Optional additional trade data for optimization
        """
        # Record in base capital engine
        self.capital_engine.record_trade(profit, fees, is_win, new_capital)
        
        # Track for autonomous optimization
        trade_record = {
            'timestamp': datetime.now(),
            'profit': profit,
            'fees': fees,
            'is_win': is_win,
            'capital': new_capital,
            'conditions': self.current_conditions,
            'data': trade_data or {}
        }
        
        self.recent_trades.append(trade_record)
        
        # Keep only recent trades for optimization
        cutoff = datetime.now() - timedelta(days=self.config.optimization_window_days)
        self.recent_trades = [t for t in self.recent_trades if t['timestamp'] > cutoff]
        
        # Perform real-time optimization if enabled
        if self.config.enable_realtime_optimization and len(self.recent_trades) >= 20:
            self._optimize_parameters()
    
    def _optimize_parameters(self):
        """
        Optimize autonomous parameters based on recent performance
        
        This analyzes recent trades and adjusts:
        - Volatility leverage sensitivity
        - Regime allocation percentages
        - Risk-adjustment factors
        """
        if not self.recent_trades:
            return
        
        # Calculate performance metrics by regime
        regime_performance = {}
        for regime in MarketRegime:
            regime_trades = [t for t in self.recent_trades 
                           if t['conditions'] and t['conditions'].regime == regime]
            
            if regime_trades:
                avg_profit = sum(t['profit'] - t['fees'] for t in regime_trades) / len(regime_trades)
                win_rate = sum(1 for t in regime_trades if t['is_win']) / len(regime_trades)
                
                regime_performance[regime] = {
                    'avg_profit': avg_profit,
                    'win_rate': win_rate,
                    'trade_count': len(regime_trades)
                }
        
        # Adjust regime allocations based on performance
        if self.config.enable_regime_allocation and regime_performance:
            for regime, perf in regime_performance.items():
                if perf['trade_count'] >= 5:  # Minimum trades for adjustment
                    current_alloc = self.config.regime_allocations.get(regime, 1.0)
                    
                    # Increase allocation if performing well (>60% win rate, positive profit)
                    if perf['win_rate'] > 0.60 and perf['avg_profit'] > 0:
                        new_alloc = min(1.2, current_alloc * 1.05)  # Increase by 5%, max 120%
                        self.config.regime_allocations[regime] = new_alloc
                        logger.info(f"📈 Increased {regime.value} allocation: "
                                  f"{current_alloc:.1%} → {new_alloc:.1%}")
                    
                    # Decrease allocation if performing poorly (<45% win rate)
                    elif perf['win_rate'] < 0.45 or perf['avg_profit'] < 0:
                        new_alloc = max(0.1, current_alloc * 0.95)  # Decrease by 5%, min 10%
                        self.config.regime_allocations[regime] = new_alloc
                        logger.info(f"📉 Decreased {regime.value} allocation: "
                                  f"{current_alloc:.1%} → {new_alloc:.1%}")
        
        logger.debug("🔧 Parameter optimization complete")
    
    def get_autonomous_status(self) -> Dict:
        """Get comprehensive autonomous engine status"""
        base_status = self.capital_engine.get_capital_status()
        
        autonomous_status = {
            **base_status,
            'autonomous_features': {
                'volatility_leverage': self.config.enable_volatility_leverage,
                'risk_adjustment': self.config.enable_risk_adjustment,
                'regime_allocation': self.config.enable_regime_allocation,
                'adaptive_compounding': self.config.enable_adaptive_compounding,
                'realtime_optimization': self.config.enable_realtime_optimization
            }
        }
        
        if self.current_conditions:
            autonomous_status['market_conditions'] = {
                'regime': self.current_conditions.regime.value,
                'volatility_pct': self.current_conditions.volatility_pct,
                'volatility_state': self.current_conditions.volatility_state.value,
                'trend_strength': self.current_conditions.trend_strength,
                'momentum_score': self.current_conditions.momentum_score,
                'liquidity_score': self.current_conditions.liquidity_score
            }
        
        if self.config.regime_allocations:
            autonomous_status['regime_allocations'] = {
                regime.value: alloc for regime, alloc in self.config.regime_allocations.items()
            }
        
        return autonomous_status
    
    def get_quick_summary(self) -> str:
        """Get quick autonomous engine summary"""
        base_summary = self.capital_engine.get_quick_summary()
        
        if self.current_conditions:
            regime_icon = {
                MarketRegime.BULL_TRENDING: "📈",
                MarketRegime.BEAR_TRENDING: "📉",
                MarketRegime.RANGING: "↔️",
                MarketRegime.VOLATILE: "⚡",
                MarketRegime.CRISIS: "🚨"
            }.get(self.current_conditions.regime, "❓")
            
            vol_icon = {
                VolatilityState.VERY_LOW: "😴",
                VolatilityState.LOW: "🟢",
                VolatilityState.NORMAL: "🟡",
                VolatilityState.HIGH: "🟠",
                VolatilityState.EXTREME: "🔴"
            }.get(self.current_conditions.volatility_state, "❓")
            
            autonomous_info = (f" | {regime_icon} {self.current_conditions.regime.value.upper()} "
                             f"| {vol_icon} Vol:{self.current_conditions.volatility_pct:.0f}%")
        else:
            autonomous_info = " | ❓ No market data"
        
        return base_summary + autonomous_info


def get_autonomous_engine(base_capital: float,
                         current_capital: Optional[float] = None,
                         compounding_strategy: str = "moderate",
                         enable_all_features: bool = True) -> AutonomousScalingEngine:
    """
    Get autonomous scaling engine instance
    
    Args:
        base_capital: Starting capital
        current_capital: Current capital (optional)
        compounding_strategy: Compounding strategy
        enable_all_features: Enable all autonomous features (default: True)
        
    Returns:
        AutonomousScalingEngine instance
    """
    base_config = CapitalEngineConfig(
        compounding_strategy=compounding_strategy,
        enable_drawdown_protection=True,
        enable_milestones=True
    )
    
    autonomous_config = AutonomousScalingConfig(
        enable_volatility_leverage=enable_all_features,
        enable_risk_adjustment=enable_all_features,
        enable_regime_allocation=enable_all_features,
        enable_adaptive_compounding=enable_all_features,
        enable_realtime_optimization=enable_all_features
    )
    
    return AutonomousScalingEngine(base_capital, current_capital, base_config, autonomous_config)


if __name__ == "__main__":
    # Demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    print(f"\n{get_version_string()}\n")
    
    # Create autonomous engine
    engine = get_autonomous_engine(base_capital=10000.0)
    
    # Simulate market conditions
    conditions = MarketConditions(
        volatility_pct=25.0,
        trend_strength=0.7,
        regime=MarketRegime.BULL_TRENDING,
        volatility_state=VolatilityState.NORMAL,
        momentum_score=0.6,
        liquidity_score=0.9
    )
    
    engine.update_market_conditions(conditions)
    
    # Calculate position sizes
    available = 10000.0
    position = engine.get_optimal_position_size(available, expected_return=0.15, volatility=0.25)
    
    print(f"\n💰 Available Balance: ${available:,.2f}")
    print(f"🎯 Optimal Position: ${position:,.2f}")
    print(f"📊 Position %: {(position/available)*100:.2f}%")
    
    print(f"\n{engine.get_quick_summary()}")
