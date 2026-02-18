"""
NIJA Institutional Capital Manager
===================================

Master orchestrator for institutional-grade capital management features.
Coordinates all advanced risk and capital management systems to provide
true institutional-level capital protection and optimization.

Core Systems:
1. Correlation-weighted compression
2. Liquidity/volume gating at higher tiers  
3. Drawdown-based risk throttle
4. Performance-based risk scaling
5. Volatility-adjusted position sizing per tier
6. Capital preservation override layer

This transforms NIJA from a trading bot into a comprehensive capital
management system suitable for institutional deployment.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.institutional_capital_manager")


class RiskThrottleLevel(Enum):
    """Risk throttle levels for institutional management"""
    NORMAL = "normal"  # Full capital deployment
    REDUCED = "reduced"  # 75% capital deployment
    CONSERVATIVE = "conservative"  # 50% capital deployment
    MINIMAL = "minimal"  # 25% capital deployment
    PRESERVATION = "preservation"  # Capital preservation mode only


@dataclass
class InstitutionalConfig:
    """Configuration for institutional capital management"""
    # Correlation compression
    enable_correlation_compression: bool = True
    correlation_threshold: float = 0.65  # Start compression above this
    max_correlation_penalty: float = 0.5  # Max 50% reduction for high correlation
    
    # Liquidity gating
    enable_liquidity_gating: bool = True
    tier_volume_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "STARTER": 1.0,
        "SAVER": 1.5,
        "INVESTOR": 2.0,
        "INCOME": 3.0,
        "LIVABLE": 4.0,
        "BALLER": 5.0
    })
    
    # Drawdown throttle
    enable_drawdown_throttle: bool = True
    throttle_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "NORMAL": 0.0,
        "REDUCED": 5.0,
        "CONSERVATIVE": 10.0,
        "MINIMAL": 15.0,
        "PRESERVATION": 20.0
    })
    
    # Performance-based scaling
    enable_performance_scaling: bool = True
    performance_lookback_days: int = 30
    scale_up_threshold: float = 0.15  # 15% monthly return to scale up
    scale_down_threshold: float = -0.05  # -5% monthly return to scale down
    
    # Volatility adjustment per tier
    enable_volatility_adjustment: bool = True
    tier_volatility_caps: Dict[str, float] = field(default_factory=lambda: {
        "STARTER": 0.10,  # 10% max position
        "SAVER": 0.15,
        "INVESTOR": 0.20,
        "INCOME": 0.25,
        "LIVABLE": 0.30,
        "BALLER": 0.40
    })
    
    # Capital preservation
    enable_capital_preservation: bool = True
    preservation_floor_pct: float = 0.90  # Preserve 90% of peak capital
    preservation_override_drawdown: float = 25.0  # Override at 25% drawdown


@dataclass
class InstitutionalMetrics:
    """Real-time metrics for institutional management"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Capital metrics
    current_capital: float = 0.0
    peak_capital: float = 0.0
    drawdown_pct: float = 0.0
    
    # Risk metrics
    current_throttle_level: RiskThrottleLevel = RiskThrottleLevel.NORMAL
    portfolio_correlation: float = 0.0
    average_volatility: float = 0.0
    
    # Performance metrics
    monthly_return: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    
    # Position metrics
    active_positions: int = 0
    total_exposure: float = 0.0
    liquidity_score: float = 1.0
    
    # Adjustment factors
    correlation_factor: float = 1.0  # 0.5 - 1.0 (compression)
    liquidity_factor: float = 1.0  # 0.0 - 1.0 (gating)
    drawdown_factor: float = 1.0  # 0.0 - 1.0 (throttle)
    performance_factor: float = 1.0  # 0.5 - 1.5 (scaling)
    volatility_factor: float = 1.0  # 0.5 - 1.5 (adjustment)
    
    # Final multiplier
    composite_multiplier: float = 1.0


class InstitutionalCapitalManager:
    """
    Master orchestrator for institutional-grade capital management.
    
    Integrates all advanced risk management features into a unified system
    that can protect and grow capital at institutional standards.
    
    Key responsibilities:
    1. Monitor all risk factors continuously
    2. Calculate composite risk adjustments
    3. Enforce capital preservation overrides
    4. Coordinate subsystems (correlation, liquidity, performance, etc.)
    5. Provide real-time risk metrics and reporting
    """
    
    def __init__(
        self,
        base_capital: float,
        current_tier: str = "INVESTOR",
        config: Optional[InstitutionalConfig] = None
    ):
        """
        Initialize Institutional Capital Manager
        
        Args:
            base_capital: Base capital amount
            current_tier: Current trading tier
            config: Optional configuration
        """
        self.base_capital = base_capital
        self.current_tier = current_tier
        self.config = config or InstitutionalConfig()
        
        # Initialize metrics
        self.metrics = InstitutionalMetrics(
            current_capital=base_capital,
            peak_capital=base_capital
        )
        
        # Subsystems will be loaded lazily
        self._drawdown_protection = None
        self._correlation_weighting = None
        self._performance_tracker = None
        self._volatility_sizer = None
        
        logger.info("=" * 80)
        logger.info("🏛️  INSTITUTIONAL CAPITAL MANAGER INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"Base Capital: ${base_capital:,.2f}")
        logger.info(f"Current Tier: {current_tier}")
        logger.info(f"Correlation Compression: {'ENABLED' if config.enable_correlation_compression else 'DISABLED'}")
        logger.info(f"Liquidity Gating: {'ENABLED' if config.enable_liquidity_gating else 'DISABLED'}")
        logger.info(f"Drawdown Throttle: {'ENABLED' if config.enable_drawdown_throttle else 'DISABLED'}")
        logger.info(f"Performance Scaling: {'ENABLED' if config.enable_performance_scaling else 'DISABLED'}")
        logger.info(f"Volatility Adjustment: {'ENABLED' if config.enable_volatility_adjustment else 'DISABLED'}")
        logger.info(f"Capital Preservation: {'ENABLED' if config.enable_capital_preservation else 'DISABLED'}")
        logger.info("=" * 80)
    
    def calculate_position_size(
        self,
        base_size: float,
        symbol: str,
        market_data: Dict,
        portfolio_state: Optional[Dict] = None
    ) -> Tuple[float, str]:
        """
        Calculate institutional-grade position size with all adjustments.
        
        Args:
            base_size: Base position size from risk manager
            symbol: Trading symbol
            market_data: Market data including price, volume, volatility
            portfolio_state: Current portfolio state (optional)
            
        Returns:
            Tuple of (adjusted_size, reasoning)
        """
        adjustments = []
        final_size = base_size
        
        # 1. Capital Preservation Override (HIGHEST PRIORITY)
        if self.config.enable_capital_preservation:
            preservation_check, size_override = self._check_capital_preservation(final_size)
            if size_override is not None:
                final_size = size_override
                adjustments.append(f"Capital Preservation Override: {size_override}")
                self.metrics.composite_multiplier = 0.0
                return final_size, "CAPITAL PRESERVATION MODE - " + " | ".join(adjustments)
        
        # 2. Drawdown Throttle
        if self.config.enable_drawdown_throttle:
            throttle_factor = self._calculate_drawdown_throttle()
            final_size *= throttle_factor
            self.metrics.drawdown_factor = throttle_factor
            if throttle_factor < 1.0:
                adjustments.append(f"Drawdown Throttle: {throttle_factor:.1%}")
        
        # 3. Correlation Compression
        if self.config.enable_correlation_compression and portfolio_state:
            correlation_factor = self._calculate_correlation_compression(symbol, portfolio_state)
            final_size *= correlation_factor
            self.metrics.correlation_factor = correlation_factor
            if correlation_factor < 1.0:
                adjustments.append(f"Correlation Compression: {correlation_factor:.1%}")
        
        # 4. Performance-Based Scaling
        if self.config.enable_performance_scaling:
            performance_factor = self._calculate_performance_scaling()
            final_size *= performance_factor
            self.metrics.performance_factor = performance_factor
            if performance_factor != 1.0:
                adjustments.append(f"Performance Scaling: {performance_factor:.1%}")
        
        # 5. Volatility Adjustment (Tier-Specific)
        if self.config.enable_volatility_adjustment:
            volatility_factor = self._calculate_volatility_adjustment(market_data)
            final_size *= volatility_factor
            self.metrics.volatility_factor = volatility_factor
            if volatility_factor != 1.0:
                adjustments.append(f"Volatility Adjustment: {volatility_factor:.1%}")
        
        # 6. Liquidity Gating
        if self.config.enable_liquidity_gating:
            liquidity_passed, liquidity_reason = self._check_liquidity_gate(market_data)
            self.metrics.liquidity_factor = 1.0 if liquidity_passed else 0.0
            if not liquidity_passed:
                adjustments.append(f"Liquidity Gate: FAILED - {liquidity_reason}")
                return 0.0, "REJECTED - " + " | ".join(adjustments)
        
        # Calculate composite multiplier
        self.metrics.composite_multiplier = final_size / base_size if base_size > 0 else 0.0
        
        # Build reasoning
        if not adjustments:
            reasoning = "No adjustments applied - normal trading"
        else:
            reasoning = " | ".join(adjustments)
        
        logger.debug(f"Position size for {symbol}: ${base_size:.2f} → ${final_size:.2f} ({reasoning})")
        
        return final_size, reasoning
    
    def _check_capital_preservation(self, proposed_size: float) -> Tuple[bool, Optional[float]]:
        """
        Check if capital preservation override should be triggered.
        
        Returns:
            Tuple of (override_triggered, size_override)
        """
        # Check drawdown threshold
        if self.metrics.drawdown_pct >= self.config.preservation_override_drawdown:
            logger.critical(f"🚨 CAPITAL PRESERVATION OVERRIDE - Drawdown: {self.metrics.drawdown_pct:.2f}%")
            return True, 0.0
        
        # Check capital floor
        preservation_floor = self.metrics.peak_capital * self.config.preservation_floor_pct
        if self.metrics.current_capital <= preservation_floor:
            remaining_pct = (self.metrics.current_capital / self.metrics.peak_capital) * 100
            logger.critical(f"🚨 CAPITAL PRESERVATION OVERRIDE - {remaining_pct:.1f}% of peak capital remaining")
            return True, 0.0
        
        return False, None
    
    def _calculate_drawdown_throttle(self) -> float:
        """
        Calculate position size reduction based on drawdown.
        More aggressive than basic drawdown protection.
        
        Returns:
            Throttle factor (0.0 - 1.0)
        """
        dd_pct = self.metrics.drawdown_pct
        
        # Determine throttle level
        if dd_pct >= self.config.throttle_thresholds["PRESERVATION"]:
            self.metrics.current_throttle_level = RiskThrottleLevel.PRESERVATION
            return 0.0
        elif dd_pct >= self.config.throttle_thresholds["MINIMAL"]:
            self.metrics.current_throttle_level = RiskThrottleLevel.MINIMAL
            return 0.25
        elif dd_pct >= self.config.throttle_thresholds["CONSERVATIVE"]:
            self.metrics.current_throttle_level = RiskThrottleLevel.CONSERVATIVE
            return 0.50
        elif dd_pct >= self.config.throttle_thresholds["REDUCED"]:
            self.metrics.current_throttle_level = RiskThrottleLevel.REDUCED
            return 0.75
        else:
            self.metrics.current_throttle_level = RiskThrottleLevel.NORMAL
            return 1.0
    
    def _calculate_correlation_compression(self, symbol: str, portfolio_state: Dict) -> float:
        """
        Calculate position size compression based on portfolio correlation.
        
        Args:
            symbol: Symbol to trade
            portfolio_state: Current portfolio positions and correlations
            
        Returns:
            Compression factor (0.5 - 1.0)
        """
        # Get portfolio correlation
        avg_correlation = portfolio_state.get('average_correlation', 0.0)
        
        if avg_correlation <= self.config.correlation_threshold:
            # Low correlation - no compression
            return 1.0
        
        # Calculate compression based on how much correlation exceeds threshold
        excess_correlation = avg_correlation - self.config.correlation_threshold
        max_excess = 1.0 - self.config.correlation_threshold
        
        if max_excess > 0:
            compression_pct = excess_correlation / max_excess
            # Apply max penalty
            compression_factor = 1.0 - (compression_pct * self.config.max_correlation_penalty)
            return max(0.5, compression_factor)  # Never compress more than 50%
        
        return 1.0
    
    def _calculate_performance_scaling(self) -> float:
        """
        Scale position sizes based on recent performance.
        
        Returns:
            Scaling factor (0.5 - 1.5)
        """
        monthly_return = self.metrics.monthly_return
        
        if monthly_return >= self.config.scale_up_threshold:
            # Strong performance - scale up
            scale_factor = 1.0 + (monthly_return - self.config.scale_up_threshold) * 2.0
            return min(1.5, scale_factor)  # Cap at 1.5x
        elif monthly_return <= self.config.scale_down_threshold:
            # Poor performance - scale down
            scale_factor = 1.0 + (monthly_return - self.config.scale_down_threshold) * 5.0
            return max(0.5, scale_factor)  # Floor at 0.5x
        
        return 1.0
    
    def _calculate_volatility_adjustment(self, market_data: Dict) -> float:
        """
        Adjust position size based on current volatility vs tier limits.
        
        Args:
            market_data: Market data including volatility metrics
            
        Returns:
            Volatility factor (0.5 - 1.5)
        """
        current_vol = market_data.get('atr_pct', 0.0)
        tier_vol_cap = self.config.tier_volatility_caps.get(self.current_tier, 0.20)
        
        # Calculate adjustment
        if current_vol <= 0:
            return 1.0
        
        vol_ratio = tier_vol_cap / current_vol
        
        # Inverse relationship: high vol = smaller size, low vol = larger size
        if vol_ratio > 1.0:
            # Low volatility - can increase size
            return min(1.5, 1.0 + (vol_ratio - 1.0) * 0.5)
        else:
            # High volatility - must decrease size
            return max(0.5, vol_ratio)
    
    def _check_liquidity_gate(self, market_data: Dict) -> Tuple[bool, str]:
        """
        Check if trade passes liquidity requirements for current tier.
        
        Args:
            market_data: Market data including volume
            
        Returns:
            Tuple of (passed, reason)
        """
        volume = market_data.get('volume_24h', 0.0)
        avg_volume = market_data.get('avg_volume', volume)
        
        # Get tier multiplier
        tier_multiplier = self.config.tier_volume_multipliers.get(self.current_tier, 1.0)
        
        # Calculate required volume
        base_volume_requirement = 1_000_000  # $1M base
        required_volume = base_volume_requirement * tier_multiplier
        
        if volume < required_volume:
            return False, f"Volume ${volume:,.0f} below tier requirement ${required_volume:,.0f}"
        
        # Check volume stability (current vs average)
        if avg_volume > 0:
            volume_ratio = volume / avg_volume
            if volume_ratio < 0.5:
                return False, f"Volume {volume_ratio:.1%} of average - insufficient liquidity"
        
        return True, "Liquidity requirements met"
    
    def update_metrics(
        self,
        current_capital: float,
        portfolio_correlation: float = 0.0,
        monthly_return: float = 0.0,
        active_positions: int = 0,
        **kwargs
    ):
        """
        Update institutional metrics for risk calculations.
        
        Args:
            current_capital: Current capital
            portfolio_correlation: Average portfolio correlation
            monthly_return: Monthly return percentage
            active_positions: Number of active positions
            **kwargs: Additional metrics
        """
        # Update capital
        self.metrics.current_capital = current_capital
        if current_capital > self.metrics.peak_capital:
            self.metrics.peak_capital = current_capital
        
        # Calculate drawdown
        if self.metrics.peak_capital > 0:
            self.metrics.drawdown_pct = ((self.metrics.peak_capital - current_capital) / 
                                         self.metrics.peak_capital * 100)
        
        # Update other metrics
        self.metrics.portfolio_correlation = portfolio_correlation
        self.metrics.monthly_return = monthly_return
        self.metrics.active_positions = active_positions
        
        # Update from kwargs
        for key, value in kwargs.items():
            if hasattr(self.metrics, key):
                setattr(self.metrics, key, value)
    
    def get_risk_report(self) -> str:
        """
        Generate comprehensive institutional risk report.
        
        Returns:
            Formatted risk report string
        """
        lines = [
            "\n" + "=" * 90,
            "INSTITUTIONAL CAPITAL MANAGEMENT REPORT",
            "=" * 90,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Tier: {self.current_tier}",
            "",
            "💰 CAPITAL STATUS",
            "-" * 90,
            f"  Current Capital:      ${self.metrics.current_capital:>15,.2f}",
            f"  Peak Capital:         ${self.metrics.peak_capital:>15,.2f}",
            f"  Drawdown:             {self.metrics.drawdown_pct:>15.2f}%",
            f"  Preservation Floor:   ${self.metrics.peak_capital * self.config.preservation_floor_pct:>15,.2f}",
            "",
            "🎚️  RISK THROTTLE",
            "-" * 90,
            f"  Throttle Level:       {self.metrics.current_throttle_level.value.upper():>15}",
            f"  Drawdown Factor:      {self.metrics.drawdown_factor:>15.1%}",
            "",
            "📊 PORTFOLIO METRICS",
            "-" * 90,
            f"  Active Positions:     {self.metrics.active_positions:>15}",
            f"  Correlation:          {self.metrics.portfolio_correlation:>15.2f}",
            f"  Correlation Factor:   {self.metrics.correlation_factor:>15.1%}",
            "",
            "📈 PERFORMANCE",
            "-" * 90,
            f"  Monthly Return:       {self.metrics.monthly_return:>15.2%}",
            f"  Performance Factor:   {self.metrics.performance_factor:>15.1%}",
            f"  Win Rate:             {self.metrics.win_rate:>15.1%}",
            "",
            "🌊 VOLATILITY & LIQUIDITY",
            "-" * 90,
            f"  Volatility Factor:    {self.metrics.volatility_factor:>15.1%}",
            f"  Liquidity Score:      {self.metrics.liquidity_score:>15.2f}",
            "",
            "🎯 COMPOSITE ADJUSTMENT",
            "-" * 90,
            f"  Final Multiplier:     {self.metrics.composite_multiplier:>15.1%}",
            "",
            "=" * 90 + "\n"
        ]
        
        return "\n".join(lines)
    
    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed under institutional rules.
        
        Returns:
            Tuple of (can_trade, reason)
        """
        # Capital preservation check
        preservation_floor = self.metrics.peak_capital * self.config.preservation_floor_pct
        if self.metrics.current_capital <= preservation_floor:
            return False, f"Capital preservation floor reached: ${self.metrics.current_capital:.2f}"
        
        # Drawdown preservation check
        if self.metrics.drawdown_pct >= self.config.preservation_override_drawdown:
            return False, f"Preservation drawdown limit reached: {self.metrics.drawdown_pct:.2f}%"
        
        # Throttle check
        if self.metrics.current_throttle_level == RiskThrottleLevel.PRESERVATION:
            return False, "Risk throttle in preservation mode"
        
        return True, "Trading allowed"


def create_institutional_manager(
    base_capital: float,
    tier: str = "INVESTOR",
    config_overrides: Optional[Dict] = None
) -> InstitutionalCapitalManager:
    """
    Factory function to create institutional capital manager.
    
    Args:
        base_capital: Base capital amount
        tier: Trading tier
        config_overrides: Optional config overrides
        
    Returns:
        InstitutionalCapitalManager instance
    """
    config = InstitutionalConfig()
    
    if config_overrides:
        for key, value in config_overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)
    
    return InstitutionalCapitalManager(base_capital, tier, config)


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Create manager
    manager = create_institutional_manager(10_000.0, "INCOME")
    
    # Test position sizing
    market_data = {
        'volume_24h': 5_000_000,
        'avg_volume': 4_500_000,
        'atr_pct': 2.5
    }
    
    portfolio_state = {
        'average_correlation': 0.70
    }
    
    # Update metrics
    manager.update_metrics(
        current_capital=9_500.0,
        portfolio_correlation=0.70,
        monthly_return=0.05,
        active_positions=3
    )
    
    # Calculate position size
    base_size = 500.0
    adjusted_size, reasoning = manager.calculate_position_size(
        base_size,
        "BTC-USD",
        market_data,
        portfolio_state
    )
    
    print(f"\nBase Size: ${base_size:.2f}")
    print(f"Adjusted Size: ${adjusted_size:.2f}")
    print(f"Reasoning: {reasoning}")
    
    print(manager.get_risk_report())
