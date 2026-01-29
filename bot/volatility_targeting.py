"""
NIJA Portfolio-Level Volatility Targeting System
================================================

Volatility-targeted capital engine that maintains target portfolio volatility
by dynamically scaling:
- Position sizes
- Active exposure
- Risk-on/risk-off modes

Target: 2% daily portfolio volatility (configurable)

This transforms NIJA into a professional-grade volatility-controlled system
similar to hedge fund risk parity and vol-targeting strategies.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger("nija.volatility_targeting")


@dataclass
class VolatilityMetrics:
    """Portfolio volatility metrics"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    realized_volatility: float = 0.0  # Annualized realized volatility
    daily_volatility: float = 0.0  # Daily volatility
    target_volatility: float = 0.02  # Target daily volatility (2%)
    volatility_ratio: float = 1.0  # realized / target
    position_scalar: float = 1.0  # Position size multiplier
    exposure_scalar: float = 1.0  # Portfolio exposure multiplier
    lookback_periods: int = 20
    confidence: float = 1.0  # Confidence in volatility estimate (0-1)


@dataclass
class VolatilityTargetingResult:
    """Result of volatility targeting calculation"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metrics: VolatilityMetrics = None
    recommended_position_size_pct: float = 0.05
    recommended_max_exposure_pct: float = 0.60
    risk_mode: str = "neutral"  # "aggressive", "neutral", "defensive"
    scaling_rationale: str = ""
    historical_volatility: List[float] = field(default_factory=list)
    summary: str = ""


class VolatilityTargetingEngine:
    """
    Portfolio-level volatility targeting engine
    
    Maintains target portfolio volatility by dynamically adjusting:
    - Position sizing
    - Portfolio exposure
    - Risk-on/risk-off positioning
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Volatility Targeting Engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Target volatility (daily)
        self.target_vol_daily = self.config.get('target_volatility_daily', 0.02)  # 2% daily
        self.target_vol_annual = self.target_vol_daily * np.sqrt(252)  # Annualized
        
        # Volatility calculation settings
        self.lookback_periods = self.config.get('lookback_periods', 20)  # 20 periods for vol calc
        self.min_periods = self.config.get('min_periods', 10)  # Minimum data for calculation
        self.vol_halflife = self.config.get('vol_halflife', 10)  # EWMA half-life for vol weighting
        
        # Scaling parameters
        self.max_scalar = self.config.get('max_position_scalar', 3.0)  # Max 3x leverage
        self.min_scalar = self.config.get('min_position_scalar', 0.2)  # Min 0.2x (defensive)
        
        # Exposure limits based on volatility regime
        self.exposure_limits = {
            'low_vol': {  # realized_vol < 0.5 * target
                'max_exposure': 0.85,
                'position_size_pct': 0.08,
                'risk_mode': 'aggressive',
            },
            'target_vol': {  # realized_vol ~ target (0.5x to 1.5x)
                'max_exposure': 0.65,
                'position_size_pct': 0.05,
                'risk_mode': 'neutral',
            },
            'high_vol': {  # realized_vol > 1.5x target
                'max_exposure': 0.40,
                'position_size_pct': 0.03,
                'risk_mode': 'defensive',
            },
            'extreme_vol': {  # realized_vol > 3x target
                'max_exposure': 0.20,
                'position_size_pct': 0.02,
                'risk_mode': 'defensive',
            },
        }
        
        # Historical data
        self.portfolio_returns: deque = deque(maxlen=self.lookback_periods * 3)  # Keep 3x lookback
        self.volatility_history: deque = deque(maxlen=100)  # Keep last 100 vol readings
        
        # Current state
        self.current_volatility: Optional[float] = None
        self.current_scalar: float = 1.0
        
        logger.info("=" * 70)
        logger.info("📊 Volatility Targeting Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Target Daily Volatility: {self.target_vol_daily*100:.2f}%")
        logger.info(f"Target Annual Volatility: {self.target_vol_annual*100:.2f}%")
        logger.info(f"Lookback Periods: {self.lookback_periods}")
        logger.info(f"Position Scalar Range: {self.min_scalar:.2f}x - {self.max_scalar:.2f}x")
        logger.info("")
        logger.info("Volatility Regimes:")
        for regime, limits in self.exposure_limits.items():
            logger.info(f"  {regime.upper()}:")
            logger.info(f"    Max Exposure: {limits['max_exposure']*100:.0f}%")
            logger.info(f"    Position Size: {limits['position_size_pct']*100:.1f}%")
            logger.info(f"    Risk Mode: {limits['risk_mode']}")
        logger.info("=" * 70)
    
    def update_portfolio_return(self, portfolio_value: float, timestamp: Optional[datetime] = None):
        """
        Update portfolio value and calculate return
        
        Args:
            portfolio_value: Current total portfolio value
            timestamp: Optional timestamp for the return
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        # Calculate return if we have previous value
        if len(self.portfolio_returns) > 0:
            prev_value = self.portfolio_returns[-1][1]
            if prev_value > 0:
                ret = (portfolio_value - prev_value) / prev_value
                self.portfolio_returns.append((timestamp, portfolio_value, ret))
            else:
                self.portfolio_returns.append((timestamp, portfolio_value, 0.0))
        else:
            # First value, no return
            self.portfolio_returns.append((timestamp, portfolio_value, 0.0))
    
    def calculate_realized_volatility(
        self,
        returns: Optional[List[float]] = None,
        use_ewma: bool = True
    ) -> Tuple[float, float]:
        """
        Calculate realized portfolio volatility
        
        Args:
            returns: Optional list of returns (uses internal history if not provided)
            use_ewma: Use exponentially weighted moving average (True) or simple std (False)
            
        Returns:
            Tuple of (daily_volatility, annualized_volatility)
        """
        # Get returns data
        if returns is None:
            if len(self.portfolio_returns) < self.min_periods:
                logger.warning(f"Insufficient data for volatility calculation: {len(self.portfolio_returns)} < {self.min_periods}")
                return 0.0, 0.0
            
            # Extract returns from history
            returns = [r[2] for r in list(self.portfolio_returns)[-self.lookback_periods:]]
        
        if len(returns) < self.min_periods:
            logger.warning(f"Insufficient returns for volatility: {len(returns)} < {self.min_periods}")
            return 0.0, 0.0
        
        returns_array = np.array(returns)
        
        if use_ewma:
            # Exponentially weighted volatility (more recent = more weight)
            span = self.vol_halflife * 2
            ewma_variance = pd.Series(returns_array).ewm(span=span).var().iloc[-1]
            daily_vol = np.sqrt(ewma_variance) if ewma_variance > 0 else 0.0
        else:
            # Simple standard deviation
            daily_vol = np.std(returns_array, ddof=1)
        
        # Annualize (assuming 252 trading days)
        annual_vol = daily_vol * np.sqrt(252)
        
        return daily_vol, annual_vol
    
    def calculate_volatility_scalar(self, realized_vol: float) -> Tuple[float, float]:
        """
        Calculate position sizing scalar based on realized vs target volatility
        
        Formula: scalar = target_vol / realized_vol
        
        This ensures that if volatility doubles, position sizes halve (constant risk)
        
        Args:
            realized_vol: Realized daily volatility
            
        Returns:
            Tuple of (position_scalar, exposure_scalar)
        """
        if realized_vol <= 0:
            logger.warning("Zero or negative realized volatility, using default scalar")
            return 1.0, 1.0
        
        # Position scalar = target / realized
        # If realized vol is 4% and target is 2%, scalar = 0.5 (halve positions)
        # If realized vol is 1% and target is 2%, scalar = 2.0 (double positions)
        position_scalar = self.target_vol_daily / realized_vol
        
        # Apply min/max constraints
        position_scalar = max(self.min_scalar, min(self.max_scalar, position_scalar))
        
        # Exposure scalar is more conservative (square root of position scalar)
        # This prevents over-leveraging in low vol environments
        exposure_scalar = np.sqrt(position_scalar)
        exposure_scalar = max(0.5, min(2.0, exposure_scalar))
        
        return position_scalar, exposure_scalar
    
    def determine_volatility_regime(self, realized_vol: float) -> str:
        """
        Determine which volatility regime we're in
        
        Args:
            realized_vol: Realized daily volatility
            
        Returns:
            Regime name: 'low_vol', 'target_vol', 'high_vol', or 'extreme_vol'
        """
        vol_ratio = realized_vol / self.target_vol_daily
        
        if vol_ratio < 0.5:
            return 'low_vol'
        elif vol_ratio <= 1.5:
            return 'target_vol'
        elif vol_ratio <= 3.0:
            return 'high_vol'
        else:
            return 'extreme_vol'
    
    def target_volatility(
        self,
        portfolio_value: Optional[float] = None,
        returns: Optional[List[float]] = None,
        force_update: bool = False
    ) -> VolatilityTargetingResult:
        """
        Complete volatility targeting: calculate vol, determine regime, scale positions
        
        Args:
            portfolio_value: Current portfolio value (for return calculation)
            returns: Optional list of returns
            force_update: Force update even if not enough data
            
        Returns:
            VolatilityTargetingResult with recommendations
        """
        logger.info("=" * 70)
        logger.info("📊 VOLATILITY TARGETING ANALYSIS")
        logger.info("=" * 70)
        
        # Update portfolio return if value provided
        if portfolio_value is not None:
            self.update_portfolio_return(portfolio_value)
        
        # Calculate realized volatility
        daily_vol, annual_vol = self.calculate_realized_volatility(returns)
        
        # Store current volatility
        self.current_volatility = daily_vol
        self.volatility_history.append(daily_vol)
        
        # Calculate confidence based on data availability
        data_points = len(self.portfolio_returns) if returns is None else len(returns)
        confidence = min(1.0, data_points / self.lookback_periods)
        
        # Calculate scalars
        position_scalar, exposure_scalar = self.calculate_volatility_scalar(daily_vol)
        self.current_scalar = position_scalar
        
        # Calculate volatility ratio
        vol_ratio = daily_vol / self.target_vol_daily if self.target_vol_daily > 0 else 1.0
        
        # Determine regime
        regime = self.determine_volatility_regime(daily_vol)
        regime_config = self.exposure_limits[regime]
        
        # Get recommendations from regime
        recommended_exposure = regime_config['max_exposure']
        recommended_position_size = regime_config['position_size_pct']
        risk_mode = regime_config['risk_mode']
        
        # Adjust recommendations by scalar
        recommended_position_size *= position_scalar
        recommended_exposure *= exposure_scalar
        
        # Apply absolute limits
        recommended_position_size = max(0.01, min(0.15, recommended_position_size))  # 1%-15%
        recommended_exposure = max(0.20, min(0.90, recommended_exposure))  # 20%-90%
        
        # Build metrics
        metrics = VolatilityMetrics(
            realized_volatility=annual_vol,
            daily_volatility=daily_vol,
            target_volatility=self.target_vol_daily,
            volatility_ratio=vol_ratio,
            position_scalar=position_scalar,
            exposure_scalar=exposure_scalar,
            lookback_periods=self.lookback_periods,
            confidence=confidence
        )
        
        # Generate scaling rationale
        if vol_ratio < 0.5:
            scaling_rationale = (
                f"Low volatility regime ({daily_vol*100:.2f}% < {self.target_vol_daily*0.5*100:.2f}%). "
                f"Scaling UP positions by {position_scalar:.2f}x to maintain target risk exposure."
            )
        elif vol_ratio <= 1.5:
            scaling_rationale = (
                f"Normal volatility regime ({daily_vol*100:.2f}% ≈ {self.target_vol_daily*100:.2f}%). "
                f"Position sizing near baseline ({position_scalar:.2f}x)."
            )
        elif vol_ratio <= 3.0:
            scaling_rationale = (
                f"High volatility regime ({daily_vol*100:.2f}% > {self.target_vol_daily*1.5*100:.2f}%). "
                f"Scaling DOWN positions by {position_scalar:.2f}x to control risk."
            )
        else:
            scaling_rationale = (
                f"EXTREME volatility regime ({daily_vol*100:.2f}% >> {self.target_vol_daily*3*100:.2f}%). "
                f"DEFENSIVE positioning: {position_scalar:.2f}x scalar, {recommended_exposure*100:.0f}% max exposure."
            )
        
        # Get historical volatility
        historical_vol = list(self.volatility_history)
        
        # Generate summary
        summary = self._generate_summary(
            metrics, regime, recommended_position_size, recommended_exposure, risk_mode, scaling_rationale
        )
        
        logger.info(summary)
        logger.info("=" * 70)
        
        return VolatilityTargetingResult(
            metrics=metrics,
            recommended_position_size_pct=recommended_position_size,
            recommended_max_exposure_pct=recommended_exposure,
            risk_mode=risk_mode,
            scaling_rationale=scaling_rationale,
            historical_volatility=historical_vol,
            summary=summary
        )
    
    def _generate_summary(
        self,
        metrics: VolatilityMetrics,
        regime: str,
        position_size: float,
        max_exposure: float,
        risk_mode: str,
        rationale: str
    ) -> str:
        """Generate human-readable summary"""
        lines = [
            "\n📊 VOLATILITY TARGETING SUMMARY",
            "=" * 70,
            f"Volatility Regime: {regime.upper().replace('_', ' ')}",
            f"Risk Mode: {risk_mode.upper()}",
            "",
            "📈 Volatility Metrics:",
            f"  Target Daily Vol: {metrics.target_volatility*100:.2f}%",
            f"  Realized Daily Vol: {metrics.daily_volatility*100:.2f}%",
            f"  Realized Annual Vol: {metrics.realized_volatility*100:.2f}%",
            f"  Vol Ratio: {metrics.volatility_ratio:.2f}x (realized / target)",
            f"  Confidence: {metrics.confidence:.2%}",
            "",
            "⚖️  Scaling Factors:",
            f"  Position Scalar: {metrics.position_scalar:.2f}x",
            f"  Exposure Scalar: {metrics.exposure_scalar:.2f}x",
            "",
            "💰 Recommended Settings:",
            f"  Position Size: {position_size*100:.2f}% of equity",
            f"  Max Portfolio Exposure: {max_exposure*100:.0f}%",
            f"  Risk Mode: {risk_mode.upper()}",
            "",
            "📋 Rationale:",
            f"  {rationale}",
        ]
        
        # Add volatility trend if we have history
        if len(self.volatility_history) >= 5:
            recent_vol = list(self.volatility_history)[-5:]
            vol_trend = "INCREASING" if recent_vol[-1] > recent_vol[0] else "DECREASING"
            vol_change = ((recent_vol[-1] - recent_vol[0]) / recent_vol[0] * 100) if recent_vol[0] > 0 else 0
            lines.append("")
            lines.append(f"📊 Volatility Trend (last 5 periods): {vol_trend} ({vol_change:+.1f}%)")
        
        return "\n".join(lines)
    
    def get_position_size_for_symbol(
        self,
        symbol_volatility: float,
        result: VolatilityTargetingResult
    ) -> float:
        """
        Calculate position size for a specific symbol based on its volatility
        
        This allows for vol-weighting across different assets
        (higher vol assets get smaller positions)
        
        Args:
            symbol_volatility: Daily volatility of the symbol
            result: VolatilityTargetingResult from portfolio analysis
            
        Returns:
            Recommended position size as percentage (0-1)
        """
        if symbol_volatility <= 0:
            return result.recommended_position_size_pct
        
        # Inverse volatility weighting
        # Lower vol = larger position, higher vol = smaller position
        base_vol = 0.02  # 2% baseline
        vol_adjustment = base_vol / symbol_volatility
        
        # Apply to recommended size
        adjusted_size = result.recommended_position_size_pct * vol_adjustment
        
        # Constrain to reasonable range
        adjusted_size = max(0.01, min(0.20, adjusted_size))
        
        return adjusted_size


def create_volatility_targeting_engine(config: Dict = None) -> VolatilityTargetingEngine:
    """
    Factory function to create VolatilityTargetingEngine instance
    
    Args:
        config: Optional configuration
        
    Returns:
        VolatilityTargetingEngine instance
    """
    return VolatilityTargetingEngine(config)


# Example usage
if __name__ == "__main__":
    import logging
    
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create engine
    engine = create_volatility_targeting_engine({
        'target_volatility_daily': 0.02,  # 2% daily target
        'lookback_periods': 20,
    })
    
    # Simulate portfolio returns
    np.random.seed(42)
    base_value = 100000
    
    # Simulate different volatility scenarios
    print("\n" + "=" * 70)
    print("SCENARIO 1: Normal Volatility (2% daily)")
    print("=" * 70)
    
    for i in range(25):
        ret = np.random.normal(0.001, 0.02)  # 2% daily vol
        base_value *= (1 + ret)
        engine.update_portfolio_return(base_value)
    
    result = engine.target_volatility(force_update=True)
    print(result.summary)
    
    # Reset for high volatility scenario
    engine2 = create_volatility_targeting_engine({'target_volatility_daily': 0.02})
    base_value2 = 100000
    
    print("\n" + "=" * 70)
    print("SCENARIO 2: High Volatility (4% daily)")
    print("=" * 70)
    
    for i in range(25):
        ret = np.random.normal(0.001, 0.04)  # 4% daily vol (2x target)
        base_value2 *= (1 + ret)
        engine2.update_portfolio_return(base_value2)
    
    result2 = engine2.target_volatility(force_update=True)
    print(result2.summary)
