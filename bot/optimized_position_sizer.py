"""
NIJA Optimized Position Sizing Engine
======================================

Advanced position sizing that integrates multiple optimization strategies:
1. Equity-based dynamic scaling (grows with account)
2. Kelly Criterion for optimal bet sizing
3. Volatility-adjusted position sizing
4. Risk-reward ratio optimization
5. Capital compounding acceleration

This module provides institutional-grade position sizing that maximizes
growth while controlling risk.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.optimized_position_sizer")


class PositionSizingMethod(Enum):
    """Position sizing methodologies"""
    FIXED_FRACTIONAL = "fixed_fractional"  # Fixed % of capital
    KELLY_CRITERION = "kelly_criterion"  # Optimal bet sizing
    VOLATILITY_ADJUSTED = "volatility_adjusted"  # Adjust for volatility
    EQUITY_CURVE = "equity_curve"  # Scale based on equity curve
    HYBRID = "hybrid"  # Combine multiple methods


@dataclass
class PositionSizingConfig:
    """Configuration for position sizing"""
    method: PositionSizingMethod = PositionSizingMethod.HYBRID
    base_risk_pct: float = 0.02  # 2% base risk per trade
    max_risk_pct: float = 0.10  # 10% maximum risk per trade
    min_risk_pct: float = 0.005  # 0.5% minimum risk per trade
    
    # Kelly Criterion settings
    kelly_fraction: float = 0.25  # Use 25% of Kelly (fractional Kelly)
    enable_kelly: bool = True
    
    # Volatility adjustments
    target_volatility: float = 0.02  # 2% daily target volatility
    volatility_lookback: int = 20  # Days for volatility calculation
    
    # Equity curve adjustments
    enable_equity_scaling: bool = True
    equity_growth_multiplier: float = 1.5  # Scale up 1.5x when equity grows
    equity_decline_multiplier: float = 0.5  # Scale down 0.5x when equity declines
    
    # Risk-reward ratio optimization
    min_risk_reward_ratio: float = 2.0  # Minimum 1:2 risk/reward
    target_risk_reward_ratio: float = 3.0  # Target 1:3 risk/reward
    optimal_risk_reward_ratio: float = 5.0  # Optimal 1:5 risk/reward


class OptimizedPositionSizer:
    """
    Advanced position sizing engine that optimizes position sizes based on
    multiple factors including equity growth, volatility, win rate, and
    risk-reward ratios.
    
    Key Features:
    1. Kelly Criterion for mathematically optimal sizing
    2. Volatility targeting for consistent risk exposure
    3. Equity curve scaling for compounding growth
    4. Dynamic risk-reward optimization
    5. Multi-factor hybrid approach
    """
    
    def __init__(self, config: Optional[PositionSizingConfig] = None):
        """
        Initialize Optimized Position Sizer
        
        Args:
            config: Position sizing configuration
        """
        self.config = config or PositionSizingConfig()
        
        # Performance tracking for Kelly Criterion
        self.win_rate = 0.50  # Default 50% win rate
        self.avg_win = 1.0  # Average win size (R-multiples)
        self.avg_loss = 1.0  # Average loss size (R-multiples)
        self.total_trades = 0
        self.winning_trades = 0
        
        # Equity tracking
        self.base_equity = 0.0
        self.peak_equity = 0.0
        self.current_equity = 0.0
        
        # Volatility tracking
        self.recent_returns = []
        
        logger.info("=" * 70)
        logger.info("🎯 Optimized Position Sizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Method: {self.config.method.value}")
        logger.info(f"Base Risk: {self.config.base_risk_pct*100:.2f}%")
        logger.info(f"Kelly Enabled: {self.config.enable_kelly}")
        logger.info(f"Equity Scaling: {self.config.enable_equity_scaling}")
        logger.info(f"Target R:R Ratio: 1:{self.config.target_risk_reward_ratio:.1f}")
        logger.info("=" * 70)
    
    def calculate_optimal_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        profit_target_price: Optional[float] = None,
        volatility: Optional[float] = None,
        signal_strength: float = 1.0,
        market_regime: str = "neutral"
    ) -> Dict:
        """
        Calculate optimal position size using hybrid methodology
        
        Args:
            account_balance: Current account balance
            entry_price: Planned entry price
            stop_loss_price: Stop loss price
            profit_target_price: Optional profit target price
            volatility: Market volatility (optional)
            signal_strength: Signal strength multiplier (0-2, default 1.0)
            market_regime: Market regime (trending/ranging/volatile)
        
        Returns:
            Dictionary with position sizing details
        """
        # Initialize result
        result = {
            'method': self.config.method.value,
            'account_balance': account_balance,
            'entry_price': entry_price,
            'stop_loss_price': stop_loss_price,
        }
        
        # Calculate risk per share
        risk_per_share = abs(entry_price - stop_loss_price)
        if risk_per_share == 0:
            logger.error("❌ Risk per share is zero - cannot size position")
            return {**result, 'position_size': 0, 'shares': 0, 'error': 'zero_risk'}
        
        # Calculate risk-reward ratio if profit target provided
        risk_reward_ratio = None
        if profit_target_price:
            reward_per_share = abs(profit_target_price - entry_price)
            risk_reward_ratio = reward_per_share / risk_per_share
            result['profit_target_price'] = profit_target_price
            result['risk_reward_ratio'] = risk_reward_ratio
            
            # Validate minimum risk-reward ratio
            if risk_reward_ratio < self.config.min_risk_reward_ratio:
                logger.warning(
                    f"⚠️  Risk-reward ratio {risk_reward_ratio:.2f} below minimum "
                    f"{self.config.min_risk_reward_ratio:.2f}"
                )
                # Adjust profit target to meet minimum R:R
                adjusted_reward = risk_per_share * self.config.min_risk_reward_ratio
                profit_target_price = entry_price + (
                    adjusted_reward if profit_target_price > entry_price else -adjusted_reward
                )
                risk_reward_ratio = self.config.min_risk_reward_ratio
                result['adjusted_profit_target'] = profit_target_price
                logger.info(f"✅ Adjusted profit target to ${profit_target_price:.2f} for R:R={risk_reward_ratio:.2f}")
        
        # Calculate base position size using selected method
        if self.config.method == PositionSizingMethod.KELLY_CRITERION:
            position_usd = self._calculate_kelly_position(
                account_balance, risk_per_share, entry_price, risk_reward_ratio
            )
        elif self.config.method == PositionSizingMethod.VOLATILITY_ADJUSTED:
            position_usd = self._calculate_volatility_adjusted_position(
                account_balance, risk_per_share, entry_price, volatility
            )
        elif self.config.method == PositionSizingMethod.EQUITY_CURVE:
            position_usd = self._calculate_equity_curve_position(
                account_balance, risk_per_share, entry_price
            )
        elif self.config.method == PositionSizingMethod.HYBRID:
            position_usd = self._calculate_hybrid_position(
                account_balance, risk_per_share, entry_price, volatility, risk_reward_ratio
            )
        else:  # FIXED_FRACTIONAL
            position_usd = self._calculate_fixed_fractional_position(
                account_balance, risk_per_share, entry_price
            )
        
        result['base_position_usd'] = position_usd
        
        # Apply signal strength adjustment
        if signal_strength != 1.0:
            position_usd *= signal_strength
            result['signal_strength'] = signal_strength
            result['signal_adjusted_position_usd'] = position_usd
        
        # Apply market regime adjustment
        regime_multiplier = self._get_regime_multiplier(market_regime)
        if regime_multiplier != 1.0:
            position_usd *= regime_multiplier
            result['market_regime'] = market_regime
            result['regime_multiplier'] = regime_multiplier
            result['regime_adjusted_position_usd'] = position_usd
        
        # Apply risk-reward bonus (reward better setups)
        if risk_reward_ratio and risk_reward_ratio >= self.config.target_risk_reward_ratio:
            rr_bonus = min(1.0 + (risk_reward_ratio - self.config.target_risk_reward_ratio) * 0.1, 1.5)
            position_usd *= rr_bonus
            result['rr_bonus'] = rr_bonus
            result['rr_adjusted_position_usd'] = position_usd
        
        # Ensure position is within bounds
        max_position = account_balance * self.config.max_risk_pct / (risk_per_share / entry_price)
        min_position = account_balance * self.config.min_risk_pct / (risk_per_share / entry_price)
        
        position_usd = max(min(position_usd, max_position), min_position)
        
        # Calculate shares
        shares = position_usd / entry_price
        actual_position_usd = shares * entry_price
        actual_risk_usd = shares * risk_per_share
        risk_pct = (actual_risk_usd / account_balance) * 100
        
        result.update({
            'final_position_usd': actual_position_usd,
            'shares': shares,
            'risk_usd': actual_risk_usd,
            'risk_pct': risk_pct,
            'max_position_usd': max_position,
            'min_position_usd': min_position,
        })
        
        logger.info(f"💰 Optimized Position Size: ${actual_position_usd:.2f} ({shares:.4f} shares)")
        logger.info(f"   Risk: ${actual_risk_usd:.2f} ({risk_pct:.2f}%)")
        if risk_reward_ratio:
            logger.info(f"   Risk:Reward = 1:{risk_reward_ratio:.2f}")
        
        return result
    
    def _calculate_fixed_fractional_position(
        self, account_balance: float, risk_per_share: float, entry_price: float
    ) -> float:
        """Calculate position using fixed fractional method"""
        risk_amount = account_balance * self.config.base_risk_pct
        shares = risk_amount / risk_per_share
        return shares * entry_price
    
    def _calculate_kelly_position(
        self, account_balance: float, risk_per_share: float, entry_price: float,
        risk_reward_ratio: Optional[float] = None
    ) -> float:
        """
        Calculate position using Kelly Criterion
        
        Kelly % = (Win% * Avg_Win - Loss% * Avg_Loss) / Avg_Loss
        
        We use fractional Kelly (typically 25-50%) to reduce volatility
        """
        if not self.config.enable_kelly or self.total_trades < 10:
            # Not enough data, fall back to fixed fractional
            return self._calculate_fixed_fractional_position(
                account_balance, risk_per_share, entry_price
            )
        
        # Calculate win/loss parameters
        win_pct = self.win_rate
        loss_pct = 1.0 - win_pct
        
        # Use risk-reward ratio if provided, otherwise use historical averages
        if risk_reward_ratio:
            avg_win = risk_reward_ratio
            avg_loss = 1.0
        else:
            avg_win = self.avg_win
            avg_loss = self.avg_loss
        
        # Kelly formula
        kelly_pct = (win_pct * avg_win - loss_pct * avg_loss) / avg_loss
        
        # Apply fractional Kelly to reduce volatility
        kelly_pct *= self.config.kelly_fraction
        
        # Ensure Kelly is within reasonable bounds
        kelly_pct = max(min(kelly_pct, self.config.max_risk_pct), self.config.min_risk_pct)
        
        risk_amount = account_balance * kelly_pct
        shares = risk_amount / risk_per_share
        
        logger.debug(
            f"📊 Kelly Criterion: {kelly_pct*100:.2f}% "
            f"(Win Rate: {win_pct*100:.1f}%, R:R: {avg_win:.2f})"
        )
        
        return shares * entry_price
    
    def _calculate_volatility_adjusted_position(
        self, account_balance: float, risk_per_share: float, entry_price: float,
        volatility: Optional[float] = None
    ) -> float:
        """
        Calculate position adjusted for market volatility
        
        Target: Maintain constant volatility exposure
        If volatility is 2x target, reduce position by 50%
        If volatility is 0.5x target, increase position by 2x
        """
        base_position = self._calculate_fixed_fractional_position(
            account_balance, risk_per_share, entry_price
        )
        
        if volatility is None or volatility == 0:
            return base_position
        
        # Calculate volatility scalar
        vol_ratio = self.config.target_volatility / volatility
        
        # Limit adjustment range (0.5x to 2.0x)
        vol_scalar = max(min(vol_ratio, 2.0), 0.5)
        
        adjusted_position = base_position * vol_scalar
        
        logger.debug(
            f"📊 Volatility Adjustment: {volatility*100:.2f}% vol → "
            f"{vol_scalar:.2f}x scalar"
        )
        
        return adjusted_position
    
    def _calculate_equity_curve_position(
        self, account_balance: float, risk_per_share: float, entry_price: float
    ) -> float:
        """
        Calculate position based on equity curve performance
        
        Scale up when equity is rising above peak
        Scale down when equity is below peak
        """
        base_position = self._calculate_fixed_fractional_position(
            account_balance, risk_per_share, entry_price
        )
        
        if not self.config.enable_equity_scaling or self.base_equity == 0:
            return base_position
        
        # Update equity tracking
        self.current_equity = account_balance
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity
        
        # Calculate equity curve scalar
        if self.current_equity >= self.peak_equity:
            # At new equity high - scale up
            growth_pct = (self.current_equity - self.base_equity) / self.base_equity
            equity_scalar = 1.0 + (growth_pct * self.config.equity_growth_multiplier)
            equity_scalar = min(equity_scalar, 2.0)  # Cap at 2x
        else:
            # Below peak - scale down
            drawdown_pct = (self.peak_equity - self.current_equity) / self.peak_equity
            equity_scalar = 1.0 - (drawdown_pct * self.config.equity_decline_multiplier)
            equity_scalar = max(equity_scalar, 0.5)  # Floor at 0.5x
        
        adjusted_position = base_position * equity_scalar
        
        logger.debug(
            f"📊 Equity Curve: ${self.current_equity:.2f} "
            f"(Peak: ${self.peak_equity:.2f}) → {equity_scalar:.2f}x scalar"
        )
        
        return adjusted_position
    
    def _calculate_hybrid_position(
        self, account_balance: float, risk_per_share: float, entry_price: float,
        volatility: Optional[float] = None,
        risk_reward_ratio: Optional[float] = None
    ) -> float:
        """
        Calculate position using hybrid approach combining multiple methods
        
        Weighted combination:
        - 40% Kelly Criterion
        - 30% Volatility Adjusted
        - 30% Equity Curve
        """
        # Calculate each component
        kelly_position = self._calculate_kelly_position(
            account_balance, risk_per_share, entry_price, risk_reward_ratio
        )
        
        vol_position = self._calculate_volatility_adjusted_position(
            account_balance, risk_per_share, entry_price, volatility
        )
        
        equity_position = self._calculate_equity_curve_position(
            account_balance, risk_per_share, entry_price
        )
        
        # Weighted average
        hybrid_position = (
            kelly_position * 0.4 +
            vol_position * 0.3 +
            equity_position * 0.3
        )
        
        logger.debug(
            f"📊 Hybrid Position: Kelly=${kelly_position:.2f} (40%), "
            f"Vol=${vol_position:.2f} (30%), Equity=${equity_position:.2f} (30%)"
        )
        
        return hybrid_position
    
    def _get_regime_multiplier(self, regime: str) -> float:
        """Get position size multiplier based on market regime"""
        regime_multipliers = {
            'trending': 1.2,  # Increase size in strong trends
            'ranging': 0.8,  # Reduce size in ranges
            'volatile': 0.7,  # Reduce size in high volatility
            'neutral': 1.0,  # No adjustment
        }
        return regime_multipliers.get(regime.lower(), 1.0)
    
    def update_performance(self, is_win: bool, profit_pct: float):
        """
        Update performance tracking for Kelly Criterion
        
        Args:
            is_win: Whether trade was a win
            profit_pct: Profit/loss as percentage of risk
        """
        self.total_trades += 1
        
        if is_win:
            self.winning_trades += 1
            # Update average win (exponential moving average)
            alpha = 0.1  # Smoothing factor
            self.avg_win = (1 - alpha) * self.avg_win + alpha * abs(profit_pct)
        else:
            # Update average loss
            alpha = 0.1
            self.avg_loss = (1 - alpha) * self.avg_loss + alpha * abs(profit_pct)
        
        # Update win rate
        self.win_rate = self.winning_trades / self.total_trades
        
        logger.debug(
            f"📊 Performance Updated: Win Rate={self.win_rate*100:.1f}%, "
            f"Avg Win={self.avg_win:.2f}R, Avg Loss={self.avg_loss:.2f}R"
        )
    
    def set_base_equity(self, equity: float):
        """Set base equity for equity curve scaling"""
        self.base_equity = equity
        self.peak_equity = equity
        self.current_equity = equity
        logger.info(f"💰 Base equity set to ${equity:.2f}")
    
    def get_optimal_risk_reward_ratio(
        self, win_rate: float, avg_win: float = None, avg_loss: float = None
    ) -> float:
        """
        Calculate optimal risk-reward ratio for given win rate
        
        For profitable trading, need: Win% * Avg_Win > Loss% * Avg_Loss
        Solving for Avg_Win/Avg_Loss ratio needed
        
        Args:
            win_rate: Historical win rate (0-1)
            avg_win: Average win size (optional)
            avg_loss: Average loss size (optional)
        
        Returns:
            Optimal risk-reward ratio
        """
        if win_rate <= 0 or win_rate >= 1:
            return self.config.target_risk_reward_ratio
        
        # Minimum R:R to be profitable at this win rate
        min_rr = (1 - win_rate) / win_rate
        
        # Target R:R for good profit (2x the minimum)
        target_rr = min_rr * 2
        
        # Ensure it's at least our configured minimum
        target_rr = max(target_rr, self.config.min_risk_reward_ratio)
        
        logger.info(
            f"📊 Optimal R:R for {win_rate*100:.1f}% win rate: "
            f"Min={min_rr:.2f}, Target={target_rr:.2f}"
        )
        
        return target_rr


def create_optimized_position_sizer(
    method: str = "hybrid",
    base_risk_pct: float = 0.02,
    enable_kelly: bool = True,
    enable_equity_scaling: bool = True
) -> OptimizedPositionSizer:
    """
    Factory function to create OptimizedPositionSizer
    
    Args:
        method: Position sizing method
        base_risk_pct: Base risk percentage
        enable_kelly: Enable Kelly Criterion
        enable_equity_scaling: Enable equity curve scaling
    
    Returns:
        OptimizedPositionSizer instance
    """
    method_enum = PositionSizingMethod(method.lower())
    
    config = PositionSizingConfig(
        method=method_enum,
        base_risk_pct=base_risk_pct,
        enable_kelly=enable_kelly,
        enable_equity_scaling=enable_equity_scaling
    )
    
    return OptimizedPositionSizer(config)


if __name__ == "__main__":
    # Test/demonstration
    import logging
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create position sizer
    sizer = create_optimized_position_sizer(
        method="hybrid",
        base_risk_pct=0.02,
        enable_kelly=True,
        enable_equity_scaling=True
    )
    
    # Set base equity
    sizer.set_base_equity(10000.0)
    
    # Simulate some trades to build performance history
    print("\n📊 Simulating 20 trades to build performance history...\n")
    for i in range(20):
        is_win = i % 3 != 0  # 66% win rate
        profit_pct = 3.0 if is_win else -1.0  # 3R wins, -1R losses
        sizer.update_performance(is_win, profit_pct)
    
    # Calculate position size for a trade
    print("\n" + "=" * 70)
    print("POSITION SIZING EXAMPLE")
    print("=" * 70)
    
    result = sizer.calculate_optimal_position_size(
        account_balance=10000.0,
        entry_price=100.0,
        stop_loss_price=98.0,
        profit_target_price=106.0,  # 1:3 R:R
        volatility=0.015,  # 1.5% volatility
        signal_strength=1.2,  # Strong signal
        market_regime="trending"
    )
    
    print(f"\nAccount Balance: ${result['account_balance']:,.2f}")
    print(f"Entry Price: ${result['entry_price']:.2f}")
    print(f"Stop Loss: ${result['stop_loss_price']:.2f}")
    print(f"Profit Target: ${result['profit_target_price']:.2f}")
    print(f"Risk:Reward Ratio: 1:{result['risk_reward_ratio']:.2f}")
    print(f"\n✅ OPTIMAL POSITION SIZE: ${result['final_position_usd']:,.2f}")
    print(f"   Shares: {result['shares']:.4f}")
    print(f"   Risk: ${result['risk_usd']:.2f} ({result['risk_pct']:.2f}%)")
    
    # Calculate optimal R:R ratio
    optimal_rr = sizer.get_optimal_risk_reward_ratio(win_rate=0.66)
    print(f"\n🎯 Optimal R:R for 66% win rate: 1:{optimal_rr:.2f}")
